"""集成测试: 每个用户自己的飞书机器人配置"""
from __future__ import annotations

import json

import httpx
from app.config import get_settings
from app.models.user import User
from app.models.user_feishu_config import UserFeishuConfig
from app.services import secret_box
from app.services.feishu_config_service import FeishuConfigService
from sqlalchemy import select

from tests.conftest import requires_mysql
from tests.factories import make_user

pytestmark = requires_mysql

BASE = "/api/automation/feishu"


async def test_default_view_reports_deployment_source(api_client, db_session, auth_headers):
    """没配过自己的 -> 如实告诉前端"当前用的是部署默认/未配置" """
    user = await make_user(db_session, open_id="ou_fs_default")
    await db_session.commit()
    headers = auth_headers(user.id)

    response = await api_client.get(BASE, headers=headers)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["source"] == "deployment"
    assert data["has_secret"] is False
    # 测试环境没有部署级飞书凭证, 因此应当逐条列出缺什么
    assert data["configured"] is False
    assert "App ID" in data["missing_fields"]


async def test_save_then_read_masks_secret(api_client, db_session, auth_headers):
    """保存后能读到配置, 但 App Secret 只回掩码"""
    user = await make_user(db_session, open_id="ou_fs_save")
    await db_session.commit()
    headers = auth_headers(user.id)
    payload = {
        "app_id": "cli_test123456",
        "app_secret": "very-secret-value-abcdef",
        "receive_id": "me@example.com",
        "receive_id_type": "email",
        "remark": "家庭群",
    }

    saved = await api_client.put(BASE, json=payload, headers=headers)
    assert saved.status_code == 200
    data = saved.json()["data"]
    assert data["source"] == "user"
    assert data["configured"] is True
    assert data["missing_fields"] == []
    assert data["receive_id_type"] == "email"
    # 密钥不能明文回传
    assert "very-secret-value-abcdef" not in saved.text
    assert data["app_secret_masked"].startswith("very")
    assert data["has_secret"] is True

    # 库里存的也必须是密文
    await db_session.rollback()
    row = (
        await db_session.execute(
            select(UserFeishuConfig).where(UserFeishuConfig.user_id == user.id)
        )
    ).scalar_one()
    assert row.app_secret_encrypted != "very-secret-value-abcdef"
    assert secret_box.decrypt(row.app_secret_encrypted) == "very-secret-value-abcdef"


async def test_empty_secret_keeps_existing(api_client, db_session, auth_headers):
    """只写字段: 不改密钥只改接收人时, 密钥必须原样保留"""
    user = await make_user(db_session, open_id="ou_fs_keep")
    await db_session.commit()
    headers = auth_headers(user.id)

    await api_client.put(
        BASE,
        json={"app_id": "cli_a", "app_secret": "keep-me", "receive_id": "ou_1"},
        headers=headers,
    )
    again = await api_client.put(
        BASE,
        json={"app_id": "cli_a", "app_secret": "", "receive_id": "ou_2"},
        headers=headers,
    )
    assert again.status_code == 200
    assert again.json()["data"]["receive_id"] == "ou_2"
    assert again.json()["data"]["has_secret"] is True

    await db_session.rollback()
    row = (
        await db_session.execute(
            select(UserFeishuConfig).where(UserFeishuConfig.user_id == user.id)
        )
    ).scalar_one()
    assert secret_box.decrypt(row.app_secret_encrypted) == "keep-me"


async def test_config_is_isolated_per_user(api_client, db_session, auth_headers):
    """A 配的飞书参数, B 既看不到也用不上"""
    alice = await make_user(db_session, open_id="ou_fs_alice")
    bob = await make_user(db_session, open_id="ou_fs_bob")
    await db_session.commit()

    await api_client.put(
        BASE,
        json={
            "app_id": "cli_alice",
            "app_secret": "alice-secret",
            "receive_id": "alice@example.com",
        },
        headers=auth_headers(alice.id),
    )

    bob_view = (await api_client.get(BASE, headers=auth_headers(bob.id))).json()["data"]
    assert bob_view["source"] == "deployment"
    assert bob_view["app_id"] != "cli_alice"
    assert bob_view["app_secret_masked"] != "alice-secret"


async def test_delete_falls_back_to_deployment(api_client, db_session, auth_headers):
    user = await make_user(db_session, open_id="ou_fs_delete")
    await db_session.commit()
    headers = auth_headers(user.id)
    await api_client.put(
        BASE,
        json={"app_id": "cli_x", "app_secret": "s", "receive_id": "ou_x"},
        headers=headers,
    )

    removed = await api_client.delete(BASE, headers=headers)
    assert removed.status_code == 200

    view = (await api_client.get(BASE, headers=headers)).json()["data"]
    assert view["source"] == "deployment"

    await db_session.rollback()
    rows = (await db_session.execute(select(UserFeishuConfig))).scalars().all()
    assert rows == []


async def test_test_push_without_config_returns_readable_error(
    api_client, db_session, auth_headers
):
    """没配就点测试推送 -> 可读提示, 不是 500 堆栈"""
    user = await make_user(db_session, open_id="ou_fs_noconf")
    await db_session.commit()

    response = await api_client.post(f"{BASE}/test", headers=auth_headers(user.id))
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["ok"] is False
    assert "飞书配置" in data["message"]


async def test_send_uses_users_own_credentials(api_client, db_session, auth_headers):
    """发送走本人凭证: 用他的 app_id 换 token, 发给他的 receive_id"""
    user = await make_user(db_session, open_id="ou_fs_push")
    await db_session.commit()
    user_id = user.id
    headers = auth_headers(user_id)
    await api_client.put(
        BASE,
        json={
            "app_id": "cli_push",
            "app_secret": "push-secret",
            "receive_id": "me@example.com",
            "receive_id_type": "email",
        },
        headers=headers,
    )

    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(
            {
                "path": request.url.path,
                "params": dict(request.url.params),
                "body": json.loads(request.content.decode()),
            }
        )
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(
                200, json={"code": 0, "tenant_access_token": "t-1", "expire": 7200}
            )
        return httpx.Response(200, json={"code": 0, "data": {}})

    await db_session.rollback()
    refreshed = (
        await db_session.execute(select(User).where(User.id == user_id))
    ).scalar_one()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = FeishuConfigService(db_session, get_settings())
        ok, message = await service.send_text(refreshed, "测试消息", client=client)

    assert ok is True, message
    token_call = next(c for c in calls if c["path"].endswith("tenant_access_token/internal"))
    assert token_call["body"]["app_id"] == "cli_push"
    assert token_call["body"]["app_secret"] == "push-secret"

    msg_call = next(c for c in calls if "/im/v1/messages" in c["path"])
    assert msg_call["params"]["receive_id_type"] == "email"
    assert msg_call["body"]["receive_id"] == "me@example.com"

    # 服务层只 flush, 提交由调用方负责; 只取列值避免 ORM 过期实例触发懒加载
    await db_session.commit()
    verified_at, last_error = (
        await db_session.execute(
            select(UserFeishuConfig.last_verified_at, UserFeishuConfig.last_error).where(
                UserFeishuConfig.user_id == user_id
            )
        )
    ).one()
    assert verified_at is not None
    assert last_error is None


async def test_send_records_failure_reason(api_client, db_session, auth_headers):
    """凭证不对时把飞书返回的原因记下来, 前端能看到为什么没发出去"""
    user = await make_user(db_session, open_id="ou_fs_bad")
    await db_session.commit()
    user_id = user.id
    headers = auth_headers(user_id)
    await api_client.put(
        BASE,
        json={"app_id": "cli_bad", "app_secret": "bad", "receive_id": "ou_bad"},
        headers=headers,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 10003, "msg": "invalid app_secret"})

    await db_session.rollback()
    refreshed = (
        await db_session.execute(select(User).where(User.id == user_id))
    ).scalar_one()

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = FeishuConfigService(db_session, get_settings())
        ok, message = await service.send_text(refreshed, "测试消息", client=client)

    assert ok is False
    assert "invalid app_secret" in message

    await db_session.commit()
    last_error = (
        await db_session.execute(
            select(UserFeishuConfig.last_error).where(UserFeishuConfig.user_id == user_id)
        )
    ).scalar_one()
    assert last_error and "invalid app_secret" in last_error
