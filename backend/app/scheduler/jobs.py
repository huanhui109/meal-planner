"""定时任务实现

约定:
  * 每个任务是"先在会话里把要发的内容算出来, 再脱离会话发消息", 不在持有数据库连接时做网络请求。
  * 逐个用户 try/except: 单个用户数据异常不影响其他人, 但整体失败 (例如库连不上) 会抛出去,
    由 APScheduler 记日志, 不静默吞掉。
  * 飞书没配置时统一跳过并只记一条日志。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.card_builder import CardBuilder
from app.bot.feishu_client import FeishuClientError
from app.config import Settings, get_settings
from app.database import session_scope
from app.models.household import Household
from app.models.user import User
from app.services.activity_service import (
    CHANNEL_FEISHU,
    KIND_DAILY_MENU_PUSH,
    KIND_EVENING_CHECK,
    KIND_EXPIRY_CHECK,
    STATUS_FAILED,
    STATUS_SENT,
    ActivityService,
)
from app.services.feishu_config_service import FeishuConfigService, ResolvedCredentials
from app.services.generation_service import count_today_tasks, create_generation_task
from app.services.inventory_service import InventoryService
from app.services.menu_service import MenuService, week_start_of

logger = logging.getLogger(__name__)

EXPIRING_WINDOW_DAYS = 3


@dataclass
class PushMessage:
    """一条待推送的消息 (open_id 直接作为接收方, 不需要用户事先加群)"""

    open_id: str
    user_name: str
    user_id: Optional[int] = None
    text: Optional[str] = None
    card: Optional[dict] = None


async def _send_all(
    settings: Settings,
    messages: List[PushMessage],
    *,
    kind: Optional[str] = None,
    title: str = "",
    http_client: Optional[httpx.AsyncClient] = None,
) -> int:
    """逐条发送, 返回成功条数; 结果写进 activity_log (今日页时间线与我的页状态卡都读它)

    凭证是按用户解析的: 谁配了自己的飞书应用就用谁的, 没配的回落部署默认配置
    (见 FeishuConfigService.resolve)。两边都没有的用户直接跳过, 不写失败流水 ——
    "没配飞书"不是错误, 只是收不到推送而已。
    """
    if not messages:
        return 0

    sent = 0
    outcomes: List[tuple] = []
    async with session_scope() as session:
        service = FeishuConfigService(session, settings)
        cache: Dict[int, Optional[ResolvedCredentials]] = {}
        for message in messages:
            if message.user_id is None:
                continue
            if message.user_id not in cache:
                user = (
                    await session.execute(select(User).where(User.id == message.user_id))
                ).scalar_one_or_none()
                cache[message.user_id] = await service.resolve(user) if user else None
            creds = cache[message.user_id]
            if creds is None:
                logger.info("用户 %s 未配置飞书, 跳过推送", message.user_name)
                continue

            bot = service.build_client(creds, client=http_client)
            try:
                if message.card is not None:
                    await bot.send_card(creds.receive_id, message.card, receive_id_type=creds.receive_id_type)
                elif message.text:
                    await bot.send_text(creds.receive_id, message.text, receive_id_type=creds.receive_id_type)
                else:
                    continue
            except FeishuClientError as exc:
                logger.warning("推送给 %s 失败: %s", message.user_name, exc)
                outcomes.append((message, STATUS_FAILED, str(exc)[:200]))
                continue
            sent += 1
            outcomes.append((message, STATUS_SENT, None))

    if kind:
        await _record_activity(outcomes, kind=kind, title=title)
    return sent


async def _record_activity(outcomes: List[tuple], *, kind: str, title: str) -> None:
    """脱离发送用的会话再写流水, 不把网络请求和数据库连接缠在一起"""
    if not outcomes:
        return
    async with session_scope() as session:
        service = ActivityService(session)
        for message, status, detail in outcomes:
            if message.user_id is None:
                continue
            await service.log(
                message.user_id,
                channel=CHANNEL_FEISHU,
                kind=kind,
                title=title,
                detail=detail or message.user_name,
                status=status,
            )


async def _all_users(session: AsyncSession) -> List[User]:
    return list((await session.execute(select(User))).scalars().all())


# ---------- 每日菜单推送 ----------


async def push_daily_menu(settings: Optional[Settings] = None) -> int:
    """每日早晨推送当天菜单"""
    settings = settings or get_settings()
    messages = await _collect_daily_menus(date.today())
    sent = await _send_all(settings, messages, kind=KIND_DAILY_MENU_PUSH, title="今日菜单推送")
    logger.info("每日菜单推送完成: %s/%s", sent, len(messages))
    return sent


async def _collect_daily_menus(today: date) -> List[PushMessage]:
    messages: List[PushMessage] = []
    async with session_scope() as session:
        service = MenuService(session)
        for user in await _all_users(session):
            try:
                menu = await service.get_current_menu(user.id)
            except Exception:  # noqa: BLE001 - 单个用户的数据问题不阻断整轮推送
                logger.exception("读取用户 %s 的菜单失败", user.id)
                continue
            if menu is None:
                continue
            items = [item for item in menu.menu_items if item.meal_date == today]
            if not items:
                continue
            meals: Dict[str, List[dict]] = {}
            total_calories = 0
            for item in sorted(items, key=lambda i: i.id):
                recipe = item.recipe
                meals.setdefault(item.meal_type, []).append(
                    {
                        "name": recipe.name if recipe else "(菜品已删除)",
                        "calories": recipe.calories if recipe else None,
                    }
                )
                total_calories += (recipe.calories or 0) if recipe else 0
            messages.append(
                PushMessage(
                    open_id=user.open_id,
                    user_name=user.name,
                    user_id=user.id,
                    card=CardBuilder.build_daily_menu_card(
                        today.strftime("%Y-%m-%d"), meals, total_calories or None
                    ),
                )
            )
    return messages


# ---------- 晚间库存检查 ----------


async def evening_inventory_check(settings: Optional[Settings] = None) -> int:
    """工作日晚间检查明天要做的菜缺什么, 缺了才提醒"""
    settings = settings or get_settings()
    messages = await _collect_missing_ingredients(date.today() + timedelta(days=1))
    sent = await _send_all(settings, messages, kind=KIND_EVENING_CHECK, title="明日备菜缺料提醒")
    logger.info("晚间库存检查完成: %s/%s", sent, len(messages))
    return sent


async def _collect_missing_ingredients(target_date: date) -> List[PushMessage]:
    messages: List[PushMessage] = []
    async with session_scope() as session:
        menu_service = MenuService(session)
        inventory_service = InventoryService(session)
        for user in await _all_users(session):
            try:
                menu = await menu_service.get_current_menu(user.id)
                if menu is None:
                    continue
                items = [item for item in menu.menu_items if item.meal_date == target_date]
                if not items:
                    continue
                missing: List[str] = []
                for item in items:
                    for row in await inventory_service.check_missing_ingredients(item.id, user.id):
                        if row["ingredient_name"] not in missing:
                            missing.append(row["ingredient_name"])
            except Exception:  # noqa: BLE001
                logger.exception("检查用户 %s 的缺料失败", user.id)
                continue
            if not missing:
                continue
            messages.append(
                PushMessage(
                    open_id=user.open_id,
                    user_name=user.name,
                    user_id=user.id,
                    card=CardBuilder.build_order_reminder_card(missing),
                )
            )
    return messages


# ---------- 临期提醒 ----------


async def daily_expiry_check(settings: Optional[Settings] = None) -> int:
    """每日提醒 {EXPIRING_WINDOW_DAYS} 天内到期的食材"""
    settings = settings or get_settings()
    messages = await _collect_expiring()
    sent = await _send_all(settings, messages, kind=KIND_EXPIRY_CHECK, title="临期食材提醒")
    logger.info("临期提醒完成: %s/%s", sent, len(messages))
    return sent


async def _collect_expiring() -> List[PushMessage]:
    messages: List[PushMessage] = []
    today = date.today()
    async with session_scope() as session:
        service = InventoryService(session)
        for user in await _all_users(session):
            try:
                rows = await service.list_with_ingredient_names(
                    user.id, expiring_within_days=EXPIRING_WINDOW_DAYS
                )
            except Exception:  # noqa: BLE001
                logger.exception("读取用户 %s 的临期食材失败", user.id)
                continue
            if not rows:
                continue
            items = [
                {
                    "name": name,
                    "expiry_date": str(item.expiry_date),
                    "days_left": (item.expiry_date - today).days,
                }
                for item, name, _category in rows
            ]
            urgency = "critical" if any(entry["days_left"] <= 1 for entry in items) else "warning"
            messages.append(
                PushMessage(
                    open_id=user.open_id,
                    user_name=user.name,
                    user_id=user.id,
                    card=CardBuilder.build_expiry_alert_card(items, urgency),
                )
            )
    return messages


# ---------- 周日自动生成下周菜单 ----------


async def generate_weekly_menu(settings: Optional[Settings] = None) -> int:
    """周日晚上给"已经配置过偏好"的用户提交下周生成任务 (由生成 worker 执行)

    只是入队, 不直接调模型: 这样额度和状态机与手动生成完全一致。
    """
    settings = settings or get_settings()
    next_week_start = week_start_of() + timedelta(days=7)
    created = 0
    async with session_scope() as session:
        menu_service = MenuService(session)
        users = list(
            (await session.execute(select(User).join(Household, Household.user_id == User.id).distinct()))
            .scalars()
            .all()
        )
        for user in users:
            try:
                existing = await menu_service.get_editable_menu_for_week(user.id, next_week_start)
                if existing is not None:
                    continue
                used = await count_today_tasks(session, user.id, False)
                if used >= settings.menu.daily_generation_limit:
                    logger.info("用户 %s 今日额度已用尽, 跳过自动生成", user.id)
                    continue
                await create_generation_task(
                    session,
                    user_id=user.id,
                    week_start=next_week_start,
                    payload={"week_start": str(next_week_start), "source": "scheduler"},
                )
            except Exception:  # noqa: BLE001
                logger.exception("为用户 %s 提交自动生成任务失败", user.id)
                continue
            created += 1
    logger.info("下周菜单自动生成已入队 %s 个用户", created)
    return created


# ---------- 商品采集 (二期) ----------


async def daily_scrape_products(settings: Optional[Settings] = None) -> int:
    """商品采集属于二期, 这里只留明确的日志, 不做任何事"""
    settings = settings or get_settings()
    if not settings.platforms.xiaoxiang.enabled:
        logger.info("小象采集未启用 (APP__PLATFORMS__XIAOXIANG__ENABLED=false), 跳过")
        return 0
    logger.info("商品采集功能将在二期实现, 本次跳过")
    return 0


__all__ = [
    "PushMessage",
    "daily_expiry_check",
    "daily_scrape_products",
    "evening_inventory_check",
    "generate_weekly_menu",
    "push_daily_menu",
]
