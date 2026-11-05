#!/usr/bin/env python3
"""双向唤醒模块运维脚本（饭决 2.9.0 · T05 运维收口）。

【为什么是本机脚本，而不是后台管理接口】
本项目没有 RBAC：``backend/app/models/user.py`` 的 User 模型没有 role / is_admin /
is_superuser 字段，``backend/app/dependencies.py`` 里也没有 require_admin 依赖。
因此「服务级」的全局操作（停用 / 恢复 / 全局撤销 / 审计导出 / 清理）由本脚本配合
本机 ``.env`` 凭据、由能登录服务器的人执行；「用户级」的连接管理走网页自助，二者不混。

【安全口径】
- 数据库连接串的唯一真源是 ``.env`` / 环境变量 ``APP__DATABASE__URL``；代码里不写任何
  真实账号、密码、主机，也不接受任何命令行令牌参数。
- 输出绝不显示令牌明文 / Fernet 密文 / SHA256 哈希；所有输出与错误都经 ``_safe()``
  脱敏（令牌前缀口径同后端 ``scrub()``，并额外屏蔽连接串里的密码与整串）。
- 只读写状态列与审计白名单列，绝不触碰 ``_token_hash`` / ``_secret_enc``；
  不自动下单、确认吃过、扣库存、发外部消息。
- 真实 WorkBuddy 账号尚未完成平台级联调，本脚本的模拟验收不等于真实联调。

【子命令】
  status        查看 L0/L1 开关、令牌对、在途任务、审计的计数概览
  kill          紧急停用：置 L1=0，并把在途任务收敛为 disconnected
  resume        恢复：只把 L1 置 1，不自动恢复在途任务
  allowlist     打印事件白名单枚举、版本与永久禁止清单（纯离线，不连库）
  revoke-all    全局撤销所有 active 令牌对（仅改状态列）
  audit-export  导出审计行（仅 AuditService.SAFE_FIELDS 十个字段）
  purge         清理过期审计行
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# 让脚本能 import backend/app/*，与 scripts/backup_db.py 的做法一致。
_ROOT = Path(__file__).resolve().parents[1]
_BACKEND = str(_ROOT / "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

# 默认审计保留天数，来源 backend/app/config.py::InboundBridgeSettings.audit_retention_days。
DEFAULT_RETENTION_DAYS = 90
DEFAULT_EXPORT_LIMIT = 100

# 与 backend/app/services/inbound_bridge/__init__.py::scrub 同口径的脱敏前缀。
# 内置而非 import：让 --help 与错误路径无需拉起整个后端依赖链。
_SENSITIVE_PREFIXES = ("fd_ib_", "fd_skill_", "private-")


def _describe(url: str) -> str:
    """脱敏后的连接地址：只显示 scheme/账号/主机/端口/库名，绝不回显密码与 query。"""
    p = urlparse(url)
    return f"{p.scheme}://{p.username or '?'}:***@{p.hostname or '?'}:{p.port or 3306}{p.path or ''}"


def _safe(text: object) -> str:
    """统一脱敏：令牌前缀替换为 [redacted]，并屏蔽连接串里的密码与整串。

    SQLAlchemy / aiomysql 的连接异常常把完整连接串带回消息，这里在打印前统一处理，
    保证「错误输出脱敏、绝不回显凭据」。
    """
    msg = str(text)
    for prefix in _SENSITIVE_PREFIXES:
        msg = msg.replace(prefix, "[redacted]")
    url = os.getenv("APP__DATABASE__URL", "")
    if url:
        p = urlparse(url)
        if p.password:
            msg = msg.replace(p.password, "***")
        msg = msg.replace(url, _describe(url))
    return msg


def _out(text: object = "") -> None:
    """所有标准输出都走这里，保证脱敏。"""
    print(_safe(text))


def _fmt_counts(rows) -> str:
    """把 (状态, 计数) 列表格式化成 ``active=3, revoked=1``，空列表返回「无」。"""
    return ", ".join(f"{key}={count}" for key, count in rows) or "无"


def _settings():
    """从 .env / APP__DATABASE__URL 装配配置（唯一真源），占位串快速失败。

    get_settings() 内部也会 load_dotenv；这里显式按项目根定位，保证从任意 cwd 运行
    都能读到 .env，且 override=False 保证已导出的环境变量优先。
    """
    load_dotenv(_ROOT / ".env", override=False)
    from app.config import get_settings, looks_like_placeholder_url

    s = get_settings()
    if looks_like_placeholder_url(s.database.url):
        raise RuntimeError("数据库连接串仍是模板占位值，请在 .env 配置 APP__DATABASE__URL")
    return s


def _connect(s):
    """建立异步引擎与会话工厂；调用方负责在 finally 里 dispose。"""
    engine = create_async_engine(s.database.url, pool_pre_ping=True)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


# ---------------------------------------------------------------- 各子命令


async def cmd_status(s, args) -> int:
    """只读概览：L0/L1 开关、令牌对状态分布、在途任务数、审计总行数。"""
    from app.models.inbound_bridge import (
        InboundAudit,
        InboundBridgeConfig,
        InboundTask,
        InboundTokenPair,
    )
    from app.services.inbound_bridge import ACTIVE_TASK_STATUSES

    engine, factory = _connect(s)
    try:
        async with factory() as db:
            cfg = await db.get(InboundBridgeConfig, 1)
            pairs = (await db.execute(select(func.count(InboundTokenPair.id)))).scalar_one()
            web_states = (await db.execute(
                select(InboundTokenPair.web_state, func.count())
                .group_by(InboundTokenPair.web_state)
            )).all()
            asst_states = (await db.execute(
                select(InboundTokenPair.assistant_state, func.count())
                .group_by(InboundTokenPair.assistant_state)
            )).all()
            tasks = (await db.execute(
                select(func.count(InboundTask.id))
                .where(InboundTask.status.in_(ACTIVE_TASK_STATUSES))
            )).scalar_one()
            audits = (await db.execute(select(func.count(InboundAudit.id)))).scalar_one()
    finally:
        await engine.dispose()

    _out(f"L0  APP__INBOUND_BRIDGE__ENABLED = {s.inbound_bridge.enabled}")
    l1 = bool(cfg.enabled) if cfg is not None else False
    reason = cfg.reason if cfg is not None and cfg.reason else "无"
    _out(f"L1  inbound_bridge_config.enabled = {l1}（停用原因: {reason}）")
    _out(f"令牌对总数: {pairs}")
    _out(f"  web_state: {_fmt_counts(web_states)}")
    _out(f"  assistant_state: {_fmt_counts(asst_states)}")
    _out(f"在途任务数（{len(ACTIVE_TASK_STATUSES)} 个在途状态）: {tasks}")
    _out(f"审计总行数: {audits}")
    return 0


async def cmd_kill(s, args) -> int:
    """紧急停用：置 L1=0，并把全部在途任务收敛为 disconnected。"""
    from app.models.inbound_bridge import InboundBridgeConfig, InboundTask
    from app.services.inbound_bridge import ACTIVE_TASK_STATUSES
    from app.services.meal_service import meal_now

    reason = (args.reason or "运维紧急停用").strip()[:200]
    engine, factory = _connect(s)
    try:
        async with factory() as db:
            # L1 固定单行 id=1；不存在则创建，与 BridgeSwitch._set() 口径一致。
            cfg = await db.get(InboundBridgeConfig, 1)
            if cfg is None:
                cfg = InboundBridgeConfig(id=1)
                db.add(cfg)
            cfg.enabled = False
            cfg.reason = reason
            cfg.updated_at = meal_now()

            # 在途任务收敛为 disconnected。
            # 语义差异说明：shared/inboundBridge.ts 的 INBOUND_TASK_STATUSES 把
            # disconnected 登记为合法终态（文案「连接已断开，本次调整不会保存」）；
            # 而应用内 backend/app/services/inbound_bridge/switch.py 的
            # BridgeSwitch.kill() 走 cancel_in_flight() 收敛为 cancelled。
            # 本脚本按发布口径独立实现为 disconnected，不改任何后端源码。
            result = await db.execute(
                update(InboundTask)
                .where(InboundTask.status.in_(ACTIVE_TASK_STATUSES))
                .values(status="disconnected", error="连接已断开，本次调整不会保存")
            )
            affected = int(result.rowcount or 0)
            await db.commit()
    finally:
        await engine.dispose()
    _out(f"已停用：L1=0，停用原因「{reason}」")
    _out(f"在途任务收敛为 disconnected：{affected} 条（原方案不变，不自动恢复）")
    return 0


async def cmd_resume(s, args) -> int:
    """恢复：只把 L1 置 1 并清空停用原因，绝不自动恢复在途任务。"""
    from app.models.inbound_bridge import InboundBridgeConfig
    from app.services.meal_service import meal_now

    engine, factory = _connect(s)
    try:
        async with factory() as db:
            cfg = await db.get(InboundBridgeConfig, 1)
            if cfg is None:
                cfg = InboundBridgeConfig(id=1)
                db.add(cfg)
            cfg.enabled = True
            cfg.reason = None
            cfg.updated_at = meal_now()
            # 只恢复 L1 开关；在途任务一律不改写，等待用户在网页侧自行处理。
            await db.commit()
    finally:
        await engine.dispose()
    _out("已恢复：L1=1，停用原因已清空；在途任务未做任何自动恢复。")
    return 0


async def cmd_allowlist() -> int:
    """打印白名单枚举、版本与永久禁止清单。纯离线：不装配配置、不连库。"""
    from app.services.inbound_bridge import AllowlistRegistry

    reg = AllowlistRegistry()
    _out(f"白名单版本: {reg.VERSION}")
    _out("显式事件白名单（默认拒绝；未登记 / disabled / 方向或阶段不匹配一律 403）:")
    for item in reg.enumerate():
        _out(
            f"  {item['event_type']}: enabled={item['enabled']} "
            f"directions={','.join(item['directions'])} "
            f"phases={','.join(item['phases'])} version={item['version']}"
        )
    _out(f"永久禁止清单 FROZEN_FORBIDDEN（{len(reg.FROZEN_FORBIDDEN)} 条，命中即 403）:")
    for pattern in sorted(reg.FROZEN_FORBIDDEN):
        _out(f"  {pattern}")
    return 0


async def cmd_revoke_all(s, args) -> int:
    """全局撤销所有 active 令牌对：只 UPDATE 状态列与撤销时间，绝不 SELECT / 改写密文。"""
    from app.models.inbound_bridge import InboundTokenPair
    from app.services.meal_service import meal_now

    now = meal_now()
    engine, factory = _connect(s)
    try:
        async with factory() as db:
            # 只改状态列；不触碰 web_token_hash / assistant_token_hash / *_secret_enc。
            r_web = await db.execute(
                update(InboundTokenPair)
                .where(InboundTokenPair.web_state == "active")
                .values(web_state="revoked", web_revoked_at=now)
            )
            r_asst = await db.execute(
                update(InboundTokenPair)
                .where(InboundTokenPair.assistant_state == "active")
                .values(assistant_state="revoked", assistant_revoked_at=now)
            )
            await db.commit()
    finally:
        await engine.dispose()
    _out(
        f"已全局撤销 active 令牌：web 端 {int(r_web.rowcount or 0)} 条、"
        f"assistant 端 {int(r_asst.rowcount or 0)} 条（仅改状态列，哈希与密文未动）。"
    )
    return 0


async def cmd_audit_export(s, args) -> int:
    """按时间倒序导出审计行，只输出 AuditService.SAFE_FIELDS 这十个字段。"""
    from app.models.inbound_bridge import InboundAudit
    from app.services.inbound_bridge.audit import AuditService

    fields = AuditService.SAFE_FIELDS
    limit = max(1, args.limit)
    engine, factory = _connect(s)
    try:
        async with factory() as db:
            rows = (await db.execute(
                select(InboundAudit)
                .order_by(InboundAudit.created_at.desc(), InboundAudit.id.desc())
                .limit(limit)
            )).scalars().all()
    finally:
        await engine.dispose()
    items = []
    for row in rows:
        item = {}
        for field in fields:
            value = getattr(row, field, None)
            if field == "created_at" and value is not None:
                value = value.isoformat()
            item[field] = value
        items.append(item)
    _out(f"审计导出（仅 SAFE_FIELDS 共 {len(fields)} 列，limit={limit}）:")
    _out(json.dumps(items, ensure_ascii=False, indent=2))
    return 0


async def cmd_purge(s, args) -> int:
    """清理超过保留期的审计行。"""
    from app.models.inbound_bridge import InboundAudit
    from app.services.meal_service import meal_now

    days = max(1, args.days)
    cutoff = meal_now() - timedelta(days=days)
    engine, factory = _connect(s)
    try:
        async with factory() as db:
            result = await db.execute(
                delete(InboundAudit).where(InboundAudit.created_at < cutoff)
            )
            await db.commit()
    finally:
        await engine.dispose()
    _out(
        f"已清理过期审计 {int(result.rowcount or 0)} 条（保留 {days} 天，"
        f"截止 {cutoff.isoformat()}）。"
    )
    return 0


# ---------------------------------------------------------------- 入口


async def dispatch(args) -> int:
    """allowlist 是纯离线枚举，不装配配置、不连库；其余命令先确认脱敏目标库。"""
    if args.cmd == "allowlist":
        return await cmd_allowlist()
    s = _settings()
    _out(f"目标库（脱敏）: {_describe(s.database.url)}")
    handlers = {
        "status": cmd_status,
        "kill": cmd_kill,
        "resume": cmd_resume,
        "revoke-all": cmd_revoke_all,
        "audit-export": cmd_audit_export,
        "purge": cmd_purge,
    }
    return await handlers[args.cmd](s, args)


def build_parser() -> argparse.ArgumentParser:
    """构造 7 个子命令，所有说明均为中文。"""
    parser = argparse.ArgumentParser(
        prog="inbound_bridge_ctl.py",
        description="饭决双向唤醒模块运维脚本（服务级操作；项目无 RBAC，用户级操作走网页自助）",
        epilog="数据库地址唯一真源：.env / APP__DATABASE__URL。输出经脱敏，绝不显示令牌。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True, metavar="<子命令>")

    sub.add_parser("status", help="查看 L0/L1 开关、令牌对、在途任务、审计的计数概览")
    kill = sub.add_parser("kill", help="紧急停用：置 L1=0，并把在途任务收敛为 disconnected")
    kill.add_argument("--reason", default="", help="停用原因（写入 config.reason，可选）")
    sub.add_parser("resume", help="恢复：只把 L1 置 1，绝不自动恢复在途任务")
    sub.add_parser("allowlist", help="打印事件白名单、版本与永久禁止清单（纯离线，不连库）")
    sub.add_parser("revoke-all", help="全局撤销所有 active 令牌对（仅改状态列）")
    export = sub.add_parser("audit-export", help="导出审计行（仅 SAFE_FIELDS 十个字段）")
    export.add_argument(
        "--limit", type=int, default=DEFAULT_EXPORT_LIMIT,
        help=f"导出条数，默认 {DEFAULT_EXPORT_LIMIT}",
    )
    purge = sub.add_parser("purge", help="清理过期审计行")
    purge.add_argument(
        "--days", type=int, default=DEFAULT_RETENTION_DAYS,
        help=f"保留天数，默认 {DEFAULT_RETENTION_DAYS}（同 InboundBridgeSettings.audit_retention_days）",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return asyncio.run(dispatch(args))
    except Exception as exc:  # noqa: BLE001 - 运维脚本统一收敛错误，绝不回显凭据
        print(f"[错误] {_safe(exc)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
