"""POST /api/decide 的端点级冒烟

这个测试存在的原因比较尴尬: 它是饭决**最核心的一个接口**(主按钮就打它), 但在它
之前 `_曾经_` 没有任何一条用例真的打过它 —— 单元测试全都直接构造 DecisionService。
后果是任何"签名对不上""kwargs 传错"的问题在 CI 里都是绿的, 直到有人在页面上按那颗
按钮才发现主流程 500。

所以这里钉两件事: 接口能通、以及灰度字段按 R-16 的规矩下发(null 而不是 'v1.2')。
"""
from __future__ import annotations

import pytest
from app.api.decide import current_layout_version
from app.models.decision import DecisionLog
from sqlalchemy import select

from tests.factories import make_user


@pytest.fixture(autouse=True)
def _unset_layout_version():
    """没配灰度是默认状态 —— 别让本机 .env 把这条用例跑成另一回事"""
    import os

    saved = os.environ.pop("APP__LAYOUT_VERSION", None)
    yield
    if saved is not None:
        os.environ["APP__LAYOUT_VERSION"] = saved


async def test_decide_endpoint_returns_a_dish(api_client, auth_headers, db_session):
    """按下主按钮 —— 必须真出一道菜, 并且带上 R-16 的灰度字段"""
    user = await make_user(db_session, open_id="ou_decide_endpoint")
    await db_session.commit()

    resp = await api_client.post("/api/decide", headers=auth_headers(user.id), json={})
    assert resp.status_code == 200, resp.text

    data = resp.json()["data"]
    assert data["dish"]["name"]
    # R-16: 服务端没配灰度时必须是 null, 不许兜底成 'v1.2'
    assert data["layout_version"] is None
    assert current_layout_version() is None
    # R-07 的度量字段: 命名必须和 decision_log 的列名一致, 前端照它取值
    assert "relaxed_level" in data
    assert "candidate_count" in data


async def test_decide_persists_the_measure_columns(api_client, auth_headers, db_session):
    """打完端点, 度量列必须**真的写进 decision_log** —— 不是"接口里有"就行

    为什么单列一条: 端点返回里有 `candidate_count` 不代表库里有。这两件事中间隔着
    `_persist`, 而它断掉的时候: 单测全绿(都是直接构造 DecisionService)、端点也绿
    (返回值照给)、只有报表永远是空的 —— 这就是本版第三种静默失败的形状(前两种是
    `score_cuisine` 99.5% 不生效、`/api/decide` 全量单测绿但端点 500)。

    带库跑完 895 passed / 0 skipped 之后, 这条仍然值得有: 那 895 条里**没有一条**
    断言"这七列写进去了", 真库跑过 ≠ 断言过。
    """
    user = await make_user(db_session, open_id="ou_decide_persist")
    await db_session.commit()

    resp = await api_client.post("/api/decide", headers=auth_headers(user.id), json={})
    assert resp.status_code == 200, resp.text

    row = (
        await db_session.execute(select(DecisionLog).where(DecisionLog.user_id == user.id))
    ).scalars().first()
    assert row is not None, "打了 /api/decide 却没有一行 decision_log"

    # 六列: 只要有一列是 NULL, 对应判据就会静默失明
    assert row.relaxed_level is not None
    assert row.candidate_count > 0
    assert row.reroll_index is not None
    assert row.band_size is not None, "band_size 没落库 —— band_width_p10() 会读到全 NULL"
    assert (
        row.natural_band_size is not None
    ), "natural_band_size 没落库 —— 塌缩类失败会彻底隐身"


async def test_decide_persists_filters_snapshot(api_client, auth_headers, db_session):
    """`filters_snapshot` 必须真的落库 —— 快照空了,"为什么当时没有菜可选"就永远复现不了

    这条用例当初带的是 xfail(非 strict), 理由是: 库里那批 decision_log 都产生于该字段
    落地之前, 所以按现有数据查是 0 行有值 —— **从 0 行有值反推"代码没写"是错的**。
    2026-09-23 全量 900 passed / 1 xpassed 时它转成了 XPASS: 新决策已经普遍带值,
    按用例里写死的规定把标记删掉了。现在它是硬断言 —— 再退化成 NULL 会直接红。
    """
    user = await make_user(db_session, open_id="ou_decide_filters_snapshot")
    await db_session.commit()

    resp = await api_client.post("/api/decide", headers=auth_headers(user.id), json={})
    assert resp.status_code == 200, resp.text

    row = (
        await db_session.execute(select(DecisionLog).where(DecisionLog.user_id == user.id))
    ).scalars().first()
    assert row.filters_snapshot is not None
