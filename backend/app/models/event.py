"""用户行为事件 (audit T2.6)

上报后端做 DAU / 转化 / 行为路径分析。
批量上报 (单条 5KB, 批量上限 50 条), 失败不抛异常给前端。

⏱ 时间口径: 统一用服务端的 received_at, 不要用客户端 ts。

这是 V1.2.0 首页改版的归因前提。ts 由客户端生成, 用户改一下系统时间、
或者一台没对过时的设备, ts 就能差出几小时甚至跨天; 用它算 DAU / 漏斗会把人
算到昨天去。同一个 session 内的事件排序同样要用 received_at —— ts 乱序会让
「先看筛选后出结果」的会话序列被反过来看, 序列分析直接失去意义。
ts 保留的意义只有一个: 事后按 (received_at - ts) 估算客户端上报延迟做校正。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Event(Base):
    """单条事件 - properties 直接存 JSON 字符串, 不强 schema"""

    __tablename__ = "event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 允许 NULL: 匿名事件 / 启动期事件也能上报
    user_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="触发事件的用户, 匿名事件为空"
    )
    event_name: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="事件名, e.g. 'login' / 'generate_menu'"
    )
    # 上报时间: 客户端时间。⚠️ 只用于客户端校正, 指标一律用 received_at, 原因见模块 docstring
    #
    # 必须是 BIGINT: 毫秒级时间戳 (如 1770000000000) 早就超过 MySQL INT 的有符号范围
    # (2147483647), 写进去直接报 1264 Out of range。0010_event 迁移里建的就是 bigint,
    # 而这里一度写成了 Integer —— 生产库类型是 bigint 所以没炸, 但任何用 create_all
    # 建的库(测试库、新环境)一打事件就崩。这条 BUG 是 V1.2.0 埋点测试跑出来的
    ts: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="客户端 Unix 毫秒时间戳 (指标请用 received_at)"
    )
    # 业务字段 - 自由 KV
    properties: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="业务字段 JSON 字符串"
    )
    # 客户端元信息 - 型号 / 微信版本 / 客户端版本
    app_version: Mapped[str | None] = mapped_column(
        String(40), nullable=True, comment="小程序版本号"
    )
    platform: Mapped[str | None] = mapped_column(
        String(40), nullable=True, comment="客户端平台 (weapp/h5/mini-app)"
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )
    # ---- V1.2.0 R-06: 会话与决策关联, 让漏斗能按"一次定下来"串起来 ----
    # 前端进首页时生成 UUIDv4, 一次「打开首页 → 定下来」的全过程共用同一个值,
    # 离开 30 分钟后换新。没有它就算不出 J1 闭环率 —— 分母必须是会话数而不是事件数。
    # 可空: 首页链路之外的事件 (登录/菜单生成) 没有会话概念。
    session_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, comment="会话 ID (前端 UUIDv4), 串联一次决策全链路事件"
    )
    # 可空: home_view / decide_roll 发生在决策之前, 那时还没有 decision_id。
    # ondelete=SET NULL 而不是 CASCADE: 决策流水删了, 事件还得留着算 DAU。
    decision_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("decision_log.id", ondelete="SET NULL"),
        nullable=True,
        comment="关联的决策流水 id, 决策前的事件为空",
    )

    # ---- V1.2.0 R-16: 首页灰度版本 ----
    # 同一个 app 版本的用户可能落在 v1.1 / v1.2 两个灰度组, 只有服务端下发的值
    # 能把"改版是好是坏"切开。
    # 必须可空且没有默认值: 服务端没配置/老数据就应该是 NULL —— 后端替前端兜底成
    # 'v1.2' 会把"不知道自己分在哪组"的行算进某一组, 灰度结论直接失效。
    layout_version: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="首页灰度版本: v1.1/v1.2; 未灰度或未知时为 NULL"
    )

    __table_args__ = (
        Index("ix_event_name_ts", "event_name", "ts"),
        Index("ix_event_user_ts", "user_id", "ts"),
        Index("ix_event_received_at", "received_at"),
        # 会话时间线: received_at 保证会话内顺序可信 (见模块 docstring 的时间口径)
        # 复合索引的左前缀 session_id 已覆盖"只按 session_id 查"的场景, 不再单独建索引
        Index("ix_event_session_received", "session_id", "received_at"),
        # 反查某次决策前后发生了什么 (J5 决策→开做转化要 join 这里)
        Index("ix_event_decision_id", "decision_id"),
        # 灰度归因切片 (只有两个取值, 单列索引 MySQL 也不会用, 必须带上时间才是真查询形态)
        Index("ix_event_layout_received", "layout_version", "received_at"),
    )

    def to_properties_dict(self) -> dict[str, Any] | None:
        if not self.properties:
            return None
        try:
            return json.loads(self.properties)
        except (ValueError, TypeError):
            return None
