"""T2.6 事件上报 API - 小程序/H5 客户端把行为日志打到这里

不鉴权 (匿名事件也能上报), 失败不抛 4xx (即便事件语法不对也静默接受) —
埋点跟业务不一样, 客户端永远要能 fire-and-forget, 出问题不影响主流程

V1.2.0 R-06 扩展: 接 session_id / decision_id 两列, 让「一次打开首页到定下来」
能被串成一条会话 —— 没有 session_id 就算不出 J1 闭环率 (分母是会话数不是事件数)。
没新建 decision_event 表: 这张 event 表已经有匿名上报 / 批量 / 大小拦截, 再加一张
表只会让漏斗 SQL 多一层 union, 而 Semantics 完全一致。

session_id 的来源有两个 (顶层字段 / properties 里的同名字段), 取值规则见
`_resolve_session_id` —— 这不是为了兼容旧版, 是因为双端 track 正在并行改造期,
后端这条列不能被改到一半的前端静默写成全 NULL。

离线决策没有 decision_log 行: 断网兜底 (decideOffline) 的结果 id 是 0, 双端按 null
上报, 落库即 NULL (0 会被外键拒绝, 见 report_events 里的归一)。这是**符合事实**的
空值, 不是异常 —— 漏斗 SQL 里 `decision_id IS NULL` **必须保留**, 否则整段离线流量
会被当成脏数据丢掉, 而"永远有答案"这条主张恰恰是靠离线兜底成立的。"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user_optional, get_db
from app.models.event import Event
from app.models.user import User
from app.schemas.common import SuccessResponse
from app.schemas.events import EventBatchAck, EventBatchIn

router = APIRouter(prefix="/events", tags=["埋点"])

ALLOWED_PLATFORM = {"weapp", "h5", "mini-app", "unknown"}

# UUIDv4 带连字符是 36 字符, 超了就是脏数据 — 截断到 36 保证一定插得进去 (列是 varchar(36))
MAX_SESSION_ID_LEN = 36
# 灰度版本是服务端下发的短枚举值 ("v1.1"/"v1.2"), 列是 varchar(20), 超了同样是脏数据
MAX_LAYOUT_VERSION_LEN = 20


def _normalize_platform(value: str | None) -> str:
    if not value:
        return "unknown"
    if value in ALLOWED_PLATFORM:
        return value
    # 截断到 40 字符并替换不可见字符
    cleaned = "".join(c for c in value if c.isprintable())[:40]
    return cleaned or "unknown"


def _clean(value: str | None, max_len: int) -> str | None:
    """去空白 + 截断到列宽

    列宽必须和迁移里的 varchar(N) 对得上, 截断是为了"脏数据也能落库" —— 埋点宁可
    存下一个被截断的值让后续能查到谁传错了, 也不要静默丢掉整批事件。
    """
    if not value:
        return None
    cleaned = value.strip()
    return cleaned[:max_len] or None


def _normalize_session_id(value: str | None) -> str | None:
    """会话 ID 归一化: 去空白 + 截断

    不做 UUID 格式校验 — 埋点宁可存下一个格式不对的值让后续能查到"谁传错了",
    也不要静默丢掉整条链路上的其它事件。
    """
    return _clean(value, MAX_SESSION_ID_LEN)


def _resolve_session_id(raw_session_id: str | None, properties: dict | None) -> str | None:
    """会话 ID 取值: 优先取请求体顶层, 没有才回落到 properties

    为什么要回落而不是只认顶层:
        V1.2.0 前端的 track.ts 已经把 session_id 塞在 properties 里(self-heal 不了,
        那是另一个 worker 的文件)。如果后端只认顶层, 上线后 session_id 一列会
        **静默全为 NULL** —— J1 闭环率的分母是会话数, 取不到就等于这次埋点白做,
        而且默认是没人会立刻发现的。宁可用回落把它接住。

    取值优先级写死为 顶层 > properties: 两个来源都给了值的时候, 顶层是明确的意图,
    properties 里的算历史包袱。

    ⏳ 删除条件 (到点就删, 不要无限期保留):
        当 H5 与小程序双端 track 都已把 session_id 放到请求体顶层、且 properties 里
        不再出现 session_id 时 —— 删掉本函数的回落分支, 改成严格模式(只取顶层),
        并同步删掉 tests/integration/test_decision_analytics.py 里的
        test_session_id_falls_back_to_properties。

        判据 SQL (两个条件必须同时满足)::

            SELECT COUNT(*) AS total_with_session,
                   SUM(JSON_EXTRACT(properties, '$.session_id') IS NOT NULL) AS from_properties
            FROM `event`
            WHERE session_id IS NOT NULL
              AND received_at >= '<双端都改成顶层之后的日期>';

            达标 = total_with_session > 0 AND from_properties = 0

        ⚠️ 一定要先看 total_with_session: 上线前这张表还没有任何带 session_id 的行,
        只看 from_properties 会得到一个"干净"的 0, 于是误判成达标、把回落提前删掉 ——
        而上线那天小程序端恰恰还依赖它。恒为零的计数不等于达标。

    保留期间的代价是"两个来源"这件事本身, 所以上面那句是硬删除条件而不是建议:
    埋点契约一旦稳定, 任何双来源取值都会在排查时多一层不可确定性。
    """
    top_level = _normalize_session_id(raw_session_id)
    if top_level:
        return top_level
    if not properties:
        return None
    legacy = properties.get("session_id")
    return _normalize_session_id(legacy if isinstance(legacy, str) else None)


def _resolve_layout_version(raw: str | None, properties: dict | None) -> str | None:
    """灰度版本取值: 顶层优先, 回落 properties

    与 `_resolve_session_id` 完全同款, 删除条件也同款(双端都改成顶层、且 properties
    里不再出现 layout_version 之后删回落), 判据 SQL 同样要求
    "先看 total > 0 再看 from_properties = 0", 否则上线前会被空集合误判成达标。

    ⚠️ 拿不到就必须是 **None**: 不能兜底成 'v1.2'。不知道用户分在哪组, 就老老实实
    记 NULL —— 替它填一个组, 灰度结论就是假的。
    """
    top_level = _clean(raw, MAX_LAYOUT_VERSION_LEN)
    if top_level:
        return top_level
    if not properties:
        return None
    legacy = properties.get("layout_version")
    return _clean(legacy if isinstance(legacy, str) else None, MAX_LAYOUT_VERSION_LEN)


@router.post("", response_model=SuccessResponse)
async def report_events(
    payload: EventBatchIn,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    """批量上报: 单批 1-50 条, 最多 5KB/条

    user_id 自动绑定 (登录用户); 失败原因只在控制台打印
    """
    accepted = 0
    skipped = 0
    user_id = user.id if user else None
    for raw in payload.events:
        try:
            properties_json = (
                json.dumps(raw.properties, ensure_ascii=False) if raw.properties else None
            )
            # 拦截过大单条 (5KB 阈值)
            if properties_json and len(properties_json.encode("utf-8")) > 5 * 1024:
                skipped += 1
                continue
            row = Event(
                user_id=user_id,
                event_name=raw.event_name,
                ts=raw.ts,
                properties=properties_json,
                app_version=raw.app_version,
                platform=_normalize_platform(raw.platform),
                session_id=_resolve_session_id(raw.session_id, raw.properties),
                # 0 不是合法的 decision_log.id: 离线兜底的结果在 decision_log 里没有行,
                # 前端用 0 表示"没有" (dev-h5-home 的 toResult())。直接写 0 会被外键
                # 拒掉(1452), 而且是 **commit 时报** —— 在循环外面, 没被 try 接住,
                # 于是整批事件一起 500。埋点绝不能因为一个占位值把主流程打断,
                # 所以这里把 0 归一成 NULL —— NULL 的语义本来就是"这次还没有决策行"。
                decision_id=raw.decision_id or None,
                layout_version=_resolve_layout_version(raw.layout_version, raw.properties),
            )
            db.add(row)
            accepted += 1
        except Exception:  # noqa: BLE001 - 埋点失败不影响业务
            skipped += 1
            continue
    await db.commit()
    return SuccessResponse(
        code=0,
        message="success",
        data=EventBatchAck(accepted=accepted, skipped=skipped).model_dump(),
    )
