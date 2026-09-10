"""集成测试: 自动化状态 (我的页的机器人状态卡)

核心诉求是"别骗人": 没配飞书就说没配, 调度器没开就说没开, 推送失败要能看见。
"""
from __future__ import annotations

from tests.conftest import requires_mysql
from tests.factories import make_user

pytestmark = requires_mysql


async def test_status_reports_unconfigured_feishu_and_disabled_scheduler(
    api_client, db_session, auth_headers
):
    user = await make_user(db_session, open_id="ou_auto_1")
    await db_session.commit()

    response = await api_client.get("/api/automation/status", headers=auth_headers(user.id))
    assert response.status_code == 200
    data = response.json()["data"]

    assert data["feishu"]["configured"] is False
    assert data["feishu"]["bound"] is False
    assert data["feishu"]["last_push_at"] is None
    assert data["scheduler"]["enabled"] is False
    assert data["scheduler"]["running"] is False
    assert data["scheduler"]["jobs"] == []
    assert data["reminders"]["daily_menu_push"] == "08:00"
    assert data["reminders"]["evening_check"] == "17:30"
    assert data["notifications"] == []


async def test_status_surfaces_recent_activity(api_client, db_session, auth_headers):
    from app.services.activity_service import (
        CHANNEL_FEISHU,
        KIND_DAILY_MENU_PUSH,
        STATUS_FAILED,
        ActivityService,
    )

    user = await make_user(db_session, open_id="ou_auto_2")
    await db_session.flush()
    await ActivityService(db_session).log(
        user.id,
        channel=CHANNEL_FEISHU,
        kind=KIND_DAILY_MENU_PUSH,
        title="今日菜单推送",
        detail="飞书未绑定",
        status=STATUS_FAILED,
    )
    await db_session.commit()

    data = (
        await api_client.get("/api/automation/status", headers=auth_headers(user.id))
    ).json()["data"]
    assert len(data["notifications"]) == 1
    entry = data["notifications"][0]
    assert entry["kind"] == KIND_DAILY_MENU_PUSH
    assert entry["status"] == STATUS_FAILED
    assert entry["title"] == "今日菜单推送"
    assert data["feishu"]["last_push_status"] == STATUS_FAILED
    assert data["feishu"]["last_push_at"] is not None


async def test_status_is_isolated_per_user(api_client, db_session, auth_headers):
    from app.services.activity_service import (
        CHANNEL_FEISHU,
        KIND_DAILY_MENU_PUSH,
        ActivityService,
    )

    owner = await make_user(db_session, open_id="ou_auto_owner")
    other = await make_user(db_session, open_id="ou_auto_other")
    await db_session.flush()
    await ActivityService(db_session).log(
        owner.id,
        channel=CHANNEL_FEISHU,
        kind=KIND_DAILY_MENU_PUSH,
        title="今日菜单推送",
    )
    await db_session.commit()

    data = (
        await api_client.get("/api/automation/status", headers=auth_headers(other.id))
    ).json()["data"]
    assert data["notifications"] == []
