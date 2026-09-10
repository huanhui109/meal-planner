"""集成测试: 拍照识别接口

不联网也能测: VisionService 的 caller 可以注入, 这里直接把 api 层用的
VisionService 换成假实现, 专门验证路由层的配额、鉴权、降级与落库链路。
"""
from __future__ import annotations

import io

from app.models.activity_log import ActivityLog
from app.services.activity_service import KIND_VISION_RECOGNIZE
from sqlalchemy import func, select

from tests.conftest import requires_mysql
from tests.factories import make_ingredient, make_user

pytestmark = requires_mysql

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
    b"\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\xb0"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _upload():
    return {"file": ("fridge.png", io.BytesIO(PNG), "image/png")}


async def test_recognize_returns_503_when_vision_not_configured(api_client, db_session, auth_headers):
    user = await make_user(db_session, open_id="ou_rec_nocfg")
    await db_session.commit()
    response = await api_client.post(
        "/api/inventory/recognize", files=_upload(), headers=auth_headers(user.id)
    )
    assert response.status_code == 503
    assert "视觉模型" in response.json()["detail"]


async def test_recognize_requires_login(api_client, db_session):
    response = await api_client.post("/api/inventory/recognize", files=_upload())
    assert response.status_code == 401


async def test_recognize_matches_known_ingredient_and_logs_activity(
    api_client, db_session, auth_headers, monkeypatch
):
    import app.api.inventory as inventory_api

    user = await make_user(db_session, open_id="ou_rec_ok")
    await make_ingredient(db_session, "西红柿", unit="个", price=2.2)
    await db_session.commit()

    monkeypatch.setattr(inventory_api, "VisionService", _FakeVision)

    response = await api_client.post(
        "/api/inventory/recognize", files=_upload(), headers=auth_headers(user.id)
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["model"] == "fake-vision"
    assert data["used_today"] == 1
    assert data["daily_limit"] == 20

    matched = next(item for item in data["items"] if item["name"] == "西红柿")
    assert matched["known"] is True
    assert matched["ingredient_id"] is not None
    unknown = next(item for item in data["items"] if item["name"] == "没见过的菜")
    assert unknown["known"] is False
    assert unknown["ingredient_id"] is None

    count = await db_session.execute(
        select(func.count(ActivityLog.id)).where(ActivityLog.kind == KIND_VISION_RECOGNIZE)
    )
    assert count.scalar() == 1


async def test_recognize_hits_daily_quota(api_client, db_session, auth_headers, monkeypatch):
    import app.api.inventory as inventory_api
    from app.config import get_settings

    user = await make_user(db_session, open_id="ou_rec_quota")
    await db_session.commit()
    monkeypatch.setattr(inventory_api, "VisionService", _FakeVision)
    monkeypatch.setattr(get_settings().llm.vision, "daily_limit", 1)

    first = await api_client.post(
        "/api/inventory/recognize", files=_upload(), headers=auth_headers(user.id)
    )
    assert first.status_code == 200
    second = await api_client.post(
        "/api/inventory/recognize", files=_upload(), headers=auth_headers(user.id)
    )
    assert second.status_code == 429
    assert "上限" in second.json()["detail"]


async def test_recognize_surfaces_vision_errors_as_422(
    api_client, db_session, auth_headers, monkeypatch
):
    import app.api.inventory as inventory_api

    user = await make_user(db_session, open_id="ou_rec_err")
    await db_session.commit()
    monkeypatch.setattr(inventory_api, "VisionService", _FailingVision)

    response = await api_client.post(
        "/api/inventory/recognize", files=_upload(), headers=auth_headers(user.id)
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "识别服务暂时不可用, 请稍后再试或手动添加"


class _FakeVision:
    configured = True

    def __init__(self, *_args, **_kwargs):  # pragma: no cover - 只为满足构造签名
        pass

    async def recognize(self, image: bytes, content_type: str = "") -> dict:
        return {
            "items": [
                {"name": "西红柿", "quantity": 3, "unit": "个", "category": "蔬菜", "confidence": 0.9, "expiry_days": 5},
                {"name": "没见过的菜", "quantity": 1, "unit": "把", "category": "蔬菜", "confidence": 0.5, "expiry_days": None},
            ],
            "model": "fake-vision",
            "degraded": False,
            "note": "",
        }


class _FailingVision:
    configured = True

    def __init__(self, *_args, **_kwargs):  # pragma: no cover
        pass

    async def recognize(self, image: bytes, content_type: str = "") -> dict:
        from app.services.vision_service import VisionError

        raise VisionError("识别服务暂时不可用, 请稍后再试或手动添加")
