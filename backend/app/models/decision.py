"""饭决决策记录模型

为什么需要这两张表, 而不是直接查 menu_item:

1. 用户点了「饭决」但没把结果放进周菜单 —— 这也是"吃过的/见过的", 必须计入去重,
   否则用户连点三次会看到同一道菜循环出现。
2. menu_item 没有 updated_at, 只靠 meal_date 无法区分同一天的两次决策先后。
3. 「近 7 天不重复」是按**天**的窗口, 而现有 menu_service.history_recipe_names
   是按**周**取 (week_start_date < 本周), 粒度完全对不上。

decision_log 就是决策这件事的唯一流水: 每一次「饭决」都落一行, 带当时的理由、
天气与餐次, 既用于去重, 也用于事后复盘"哪条理由更被接受"。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class DecisionSource:
    """决策来源"""

    LOCAL = "local"  # 服务端本地菜谱库编排
    OFFLINE = "offline"  # 客户端离线候选池 (断网兜底), 由前端上报
    AI = "ai"  # 大模型生成

    ALL = (LOCAL, OFFLINE, AI)


class MealSlot:
    """餐次槽位 - 比 menu_item.meal_type 多了 late_night, 因为深夜是个独立场景"""

    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"
    LATE_NIGHT = "late_night"

    ALL = (BREAKFAST, LUNCH, DINNER, LATE_NIGHT)
    LABELS = {
        BREAKFAST: "早餐",
        LUNCH: "午餐",
        DINNER: "晚餐",
        LATE_NIGHT: "夜宵",
    }


class DecisionLog(Base, TimestampMixin):
    """每一次「饭决」的流水"""

    __tablename__ = "decision_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    recipe_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("recipe.id", ondelete="SET NULL"), nullable=True
    )
    # 冗余存菜名: recipe 可能被删, 但"最近吃过什么"这件事不能被删掉
    dish_name: Mapped[str] = mapped_column(String(200), nullable=False, comment="菜名")
    dish_category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, comment="品类")
    dish_cuisine: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, comment="菜系")
    main_ingredient: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, comment="主料")
    decision_date: Mapped[date] = mapped_column(Date, nullable=False, comment="决策日期")
    meal_slot: Mapped[str] = mapped_column(
        String(20), nullable=False, default=MealSlot.DINNER, comment="餐次槽位"
    )
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, default=DecisionSource.LOCAL, comment="来源: local/offline/ai"
    )
    reason: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="给用户的理由")
    weather: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, comment="决策时的天气")
    # null = 还没表态; True = 就这个; False = 换一个
    accepted: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True, comment="用户是否采纳")
    # 今日饭决结果是否被「做完了」并扣减了冰箱库存 (V2.7 新增)。
    # 用来防止"刷新/再次点做完了"重复扣减 —— 今日线没有 menu_item, 这条是唯一幂等闸。
    is_cooked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("0"), comment="今日饭决是否已做并扣库存"
    )
    # 整份结果的快照。recipe 可能被删/被改, 但「上次饭决给了什么」必须能原样回放,
    # 否则 GET /decide/last 只能返回半个结果, 冷启动会闪一下空卡。
    payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="决策快照 JSON")

    # ---- V1.2.0 R-07: 决策质量的度量列 ----
    #
    # 为什么这些必须是真列, 不能留在 payload JSON 里:
    # payload 是给前端回放 UI 用的自由格式文档, 拿它当事实来源等于把数据指标建在
    # UI 快照上 —— 前端改一个渲染字段, 指标口径就跟着变。而且查"多少次决策放宽了
    # 条件"只能 LIKE '%"relaxed": true%' 全表扫, 190 行看不出问题, 上线后每天几百行必炸。
    # 这六列回答的都是同一个问题「引擎有没有把候选池抽干」, 是判据 J3 的分子分母。
    #
    # ⚠️ 历史数据口径: 迁移前已有的行 (数据依据 §5.6 说的那 190 行联调/压测数据)
    # 是**没有测过这些值**的, 落到 0 只是列非空的默认值, 不代表"当时没放宽"。
    # 任何统计都要带 created_at >= <上线时间> 过滤, 详见 app/services/decision_metrics.py。

    # 与 event.session_id 同源, 用来把「进了几次决策」和「哪几次放松宽了」join 起来
    session_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True, comment="会话 ID (前端 UUIDv4), 与 event.session_id 同源"
    )
    # 「换一个」是前端驱动的动作, 服务端只在落库时看到它累积到第几次
    reroll_index: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), comment="出此结果前已点了几次换一个"
    )
    # 曾经只有 payload 里有它, 现在提成真列 —— J3 的分母要能一次 SUM 出来
    relaxed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("0"), comment="是否放宽了候选条件"
    )
    # 0 = 未放宽; 1-4 = 放宽到第几级, 共 **5 档**(不是 6 档):
    #   1 = 松 cook_cap(耗时上限) → 2 = 松 category 打散(**开始牺牲多样性, J3 的分界线**)
    #   → 3 = 松 main_ingredient → 4 = 松 7 天不重复(最后的安全线)
    # ⚠️ tools / meal_slots **不是档位**: 两者覆盖率 18.2% / 21.9%, 都低于 30% 硬过滤门槛,
    # 只参与加分、不进 `_passes` 的过滤链, 因此没有它们对应的放宽级别。
    # 阈值不要在 SQL 里写数字, 一律引用 decision_service 的 RELAX_LEVEL_* 常量名 ——
    # J3 的门槛这轮已经漂过三次(旧 relaxed=true → 6 档时的 3 → 5 档时的 2)。
    relaxed_level: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), comment="放宽级别 0=未放宽, 1-4 见 R-10"
    )
    # 放宽**之前**的候选池大小, 即通过 `_passes` 的行数。
    # ⚠️ 它会**高估**用户实际可选范围: 晚饭档这里可能是 296, 但真正抽签只在
    # `_random_band` 返回的十几道里 —— 要看"用户实际在几道菜里选"请用 band_size。
    # candidate_count = 0 是缺陷级事件, R-10 会直接打 decide_empty_pool 告警
    candidate_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), comment="放宽前候选池大小(通过 _passes 的行数)"
    )
    # 用户真正在其中抽签的道数 = `_random_band(scored)` 返回列表的长度。
    #
    # 为什么还要单列一列: 实测晚饭档 candidate_count 是 296, 但抽签带只有 116 ——
    # "通过了过滤"不等于"真的进了抽签带"。塌缩时 band 会从三位数掉到个位数,
    # 比看占比灵敏而且不依赖样本量, 所以 J6'/J7' 的分母用它(PRD §C15)。
    #
    # ⚠️ 可空是有意的: 老决策行没有这个值, NULL 表示"当时没测", **不能当成 0 道**。
    # 0 在这里是缺陷信号(抽签带空了), 由缺值伪造出来的 0 会污染告警。
    band_size: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="实际抽签带大小(_random_band 长度); NULL=当时没测"
    )
    # **分数带内**的真带大小: 只数 `score >= best - random_band`, 不含"不足
    # random_min_choices 时按分数补齐"的那部分。
    #
    # 为什么两个都要: band_size 被 padding 保过底 —— `_random_band` 在真带不足时会
    # 补齐到 random_min_choices, 于是 `band_size >= random_min_choices` **恒真**
    # (实测真带只剩 1 道时 band_size 仍是 3)。任何"band_size >= N"形状的判据都会
    # 在池子塌掉的时候假绿。塌缩要看这一列。
    #
    # 分工: band_size 回答"换一个会不会横跳"(补齐出来的那些也是真能拿到的菜),
    # natural_band_size 回答"池子塌没塌"。别互相替代。
    # 语义同上: NULL = 当时没测, 不能当 0 —— 0 是"真带空了"的缺陷信号。
    natural_band_size: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="分数带内真带大小(不含补齐); NULL=当时没测"
    )
    # 当时实际生效的过滤条件 (耗时/忌口/餐次/厨具…)。"为什么当时没有菜可选"必须能复现,
    # 事后看代码版本是猜不出来的
    filters_snapshot: Mapped[Optional[dict]] = mapped_column(
        JSON, nullable=True, comment="本次决策的过滤条件快照"
    )

    recipe = relationship("Recipe", lazy="selectin")

    __table_args__ = (
        Index("ix_decision_user_date", "user_id", "decision_date"),
        Index("ix_decision_user_created", "user_id", "created_at"),
        # 按会话反查这次决策 (event 侧也有 session_id, join 时两边都要走索引)
        Index("ix_decision_session", "session_id"),
        # J3 枯竭率按餐次切片时的辅助索引 (夜宵 20% / 全时段 8% 两条线不能混)
        Index("ix_decision_slot_created", "meal_slot", "created_at"),
    )


class DecisionFeedback(Base):
    """决策反馈 - 用户对单次决策的态度

    accepted 落在 decision_log 上表示结果, 这里记的是过程(点了几次换一个),
    用来判断「倔强提示」该不该弹、以及哪类理由更容易被接受。
    """

    __tablename__ = "decision_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    decision_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("decision_log.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    liked: Mapped[bool] = mapped_column(Boolean, nullable=False, comment="True=就这个, False=换一个")
    # 第几次决策时给的反馈 (1 = 首次), 用于触发「别纠结了，我替你倔一回。」
    round_index: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )

    __table_args__ = (Index("ix_decision_fb_user_created", "user_id", "created_at"),)
