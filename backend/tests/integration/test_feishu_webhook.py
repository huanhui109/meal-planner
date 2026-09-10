"""集成测试: 飞书事件回调 (签名/解密/去重/指令落库)

不真的发飞书请求: 用 dependency_overrides 注入 FakeBotClient, 只记录 reply 调用。
后台处理走 session_scope 直接连测试库, 因此必须提交后才能被断言看到。
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional, Tuple

from app.bot.command_handler import UNKNOWN_USER_TEXT
from app.bot.feishu_client import get_feishu_bot_client
from app.bot.webhook_security import calculate_signature, encrypt_event
from app.models.fridge_inventory import FridgeInventory
from sqlalchemy import select

from tests.conftest import requires_mysql
from tests.factories import make_user

pytestmark = requires_mysql

TIMESTAMP = "1735689600"


class FakeBotClient:
    """替身: 只记录回复, 不发起任何网络请求"""

    def __init__(self, encrypt_key: str = "", verification_token: str = ""):
        self.encrypt_key = encrypt_key
        self.verification_token = verification_token
        self.configured = True
        self.replies: List[Tuple[str, str, Any]] = []

    async def reply(self, message_id: str, msg_type: str, content: Any) -> Dict[str, Any]:
        self.replies.append((message_id, msg_type, content))
        return {"code": 0, "data": {}}

    def replied_texts(self) -> List[str]:
        texts = []
        for _message_id, msg_type, content in self.replies:
            if msg_type != "text":
                continue
            payload = json.loads(content) if isinstance(content, str) else content
            texts.append(payload.get("text", ""))
        return texts


async def _post(api_client, fake: FakeBotClient, body: Dict[str, Any], sign: bool = True):
    from app.main import app

    headers = {}
    if sign and fake.encrypt_key:
        headers = {
            "X-Lark-Signature": calculate_signature(TIMESTAMP, fake.encrypt_key),
            "X-Lark-Request-Timestamp": TIMESTAMP,
        }
    app.dependency_overrides[get_feishu_bot_client] = lambda: fake
    try:
        return await api_client.post("/feishu/webhook", json=body, headers=headers)
    finally:
        app.dependency_overrides.pop(get_feishu_bot_client, None)


def _message_event(
    text: str,
    open_id: str = "ou_alice",
    event_id: Optional[str] = None,
    sender_type: str = "user",
    message_type: str = "text",
) -> Dict[str, Any]:
    return {
        "type": "event_callback",
        "header": {"event_id": event_id or f"evt_{uuid.uuid4().hex}", "token": ""},
        "event": {
            "type": "im.message.receive_v1",
            "sender": {"sender_type": sender_type, "sender_id": {"open_id": open_id}},
            "message": {
                "message_id": "om_test_1",
                "message_type": message_type,
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
        },
    }


# ---------- 握手与安全 ----------


async def test_url_verification_returns_challenge(api_client):
    response = await _post(
        api_client,
        FakeBotClient(),
        {"type": "url_verification", "challenge": "challenge-abc", "token": ""},
    )
    assert response.status_code == 200
    assert response.json() == {"challenge": "challenge-abc"}


async def test_bad_signature_is_403(api_client):
    response = await _post(
        api_client,
        FakeBotClient(encrypt_key="enc-key"),
        {"type": "url_verification", "challenge": "x"},
        sign=False,
    )
    assert response.status_code == 403


async def test_bad_verification_token_is_403(api_client):
    response = await _post(
        api_client,
        FakeBotClient(verification_token="expected-token"),
        {"type": "url_verification", "challenge": "x", "token": "wrong-token"},
    )
    assert response.status_code == 403


async def test_encrypted_body_is_rejected_when_not_decryptable(api_client):
    response = await _post(
        api_client,
        FakeBotClient(encrypt_key="enc-key"),
        {"encrypt": "bm90LXJlYWwtY2lwaGVydGV4dA=="},
    )
    assert response.status_code == 400


async def test_malformed_json_body_is_400(api_client):
    from app.main import app

    fake = FakeBotClient()
    app.dependency_overrides[get_feishu_bot_client] = lambda: fake
    try:
        response = await api_client.post(
            "/feishu/webhook", content=b"{not json", headers={"Content-Type": "application/json"}
        )
    finally:
        app.dependency_overrides.pop(get_feishu_bot_client, None)
    assert response.status_code == 400


# ---------- 事件处理 ----------


async def test_encrypted_event_is_decrypted_and_answered(api_client, db_session):
    await make_user(db_session, open_id="ou_stranger", name="陌生回调用户")
    await db_session.commit()

    fake = FakeBotClient(encrypt_key="enc-key", verification_token="ver-token")
    event = _message_event("帮助", open_id="ou_stranger")
    inner = {**event, "token": "ver-token"}
    body = encrypt_event(inner, "enc-key")

    response = await _post(api_client, fake, body)

    assert response.status_code == 200
    assert len(fake.replies) == 1
    assert "AI 菜谱助手" in fake.replied_texts()[0]


async def test_unknown_user_gets_hint(api_client, db_session):
    fake = FakeBotClient()
    response = await _post(api_client, fake, _message_event("菜单", open_id="ou_nobody"))

    assert response.status_code == 200
    assert fake.replied_texts() == [UNKNOWN_USER_TEXT]


async def test_duplicate_event_id_is_answered_once(api_client, db_session):
    await make_user(db_session, open_id="ou_dup", name="重复测试")
    await db_session.commit()

    fake = FakeBotClient()
    event = _message_event("帮助", open_id="ou_dup", event_id=f"evt_{uuid.uuid4().hex}")

    await _post(api_client, fake, event)
    await _post(api_client, fake, event)

    assert len(fake.replies) == 1


async def test_message_sent_by_app_is_ignored(api_client, db_session):
    await make_user(db_session, open_id="ou_self", name="机器人")
    await db_session.commit()

    fake = FakeBotClient()
    await _post(api_client, fake, _message_event("菜单", open_id="ou_self", sender_type="app"))

    assert fake.replies == []


async def test_non_text_message_gets_hint(api_client, db_session):
    await make_user(db_session, open_id="ou_image", name="图片用户")
    await db_session.commit()

    fake = FakeBotClient()
    await _post(api_client, fake, _message_event("", open_id="ou_image", message_type="image"))

    assert fake.replied_texts() == ["我暂时只看得懂文字, 可以发「帮助」看看能做什么。"]


async def test_add_inventory_command_writes_row(api_client, db_session):
    await make_user(db_session, open_id="ou_cook", name="下厨的人")
    await db_session.commit()

    fake = FakeBotClient()
    await _post(api_client, fake, _message_event("添加库存 鸡蛋 10个", open_id="ou_cook"))

    assert any("已入库" in text for text in fake.replied_texts())

    await db_session.rollback()
    rows = (await db_session.execute(select(FridgeInventory))).scalars().all()
    assert len(rows) == 1
    assert float(rows[0].quantity) == 10.0
    assert rows[0].unit == "个"
    assert rows[0].source == "feishu_bot"


async def test_view_inventory_command_lists_items(api_client, db_session):
    user = await make_user(db_session, open_id="ou_stock", name="有库存的人")
    from tests.factories import make_ingredient, make_stock

    ingredient = await make_ingredient(db_session, "西红柿", unit="个", price=1.5)
    await make_stock(db_session, user.id, ingredient, 6, unit="个")
    await db_session.commit()

    fake = FakeBotClient()
    await _post(api_client, fake, _message_event("库存", open_id="ou_stock"))

    text = fake.replied_texts()[0]
    assert "西红柿" in text
    assert "6个" in text
