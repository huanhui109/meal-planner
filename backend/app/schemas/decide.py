"""饭决决策接口的数据模型"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.models.decision import MealSlot


class DecideRequest(BaseModel):
    """请求一次决策

    meal_slot 一般不用传: 服务端按当前时间推断。
    前端在"早餐/夜宵"这种用户主动切换的场景才显式传。
    """

    meal_slot: Optional[str] = Field(default=None, description="breakfast/lunch/dinner/late_night")
    # 本次会话已经拒绝掉的菜名, 点「换一个」时带上, 避免来回横跳
    exclude: List[str] = Field(default_factory=list)
    # 一句口语诉求, 如「今天想吃清淡点的, 别太辣」。不传就完全不碰 Jev。
    utterance: Optional[str] = Field(default=None, max_length=200)
    # V1.2.0 R-07: 本次会话 ID, 前端生成的 UUIDv4, 与 event.session_id 同源。
    # 它落进 decision_log.session_id, 是把"一次决策"和"这个会话里打了哪些事件"
    # join 起来的唯一纽带 —— 缺了它 J1 闭环率的分母就拿不到。
    session_id: Optional[str] = Field(default=None, max_length=36)


class UnderstandRequest(BaseModel):
    """只解析诉求, 不做决策 —— 给前端做"我听懂了"的回显与调试用"""

    utterance: str = Field(description="用户的口语诉求", max_length=200)
    meal_slot: Optional[str] = Field(default=None)
    fridge: List[str] = Field(default_factory=list)


class DecideFeedbackRequest(BaseModel):
    liked: bool = Field(description="True=就这个, False=换一个")


class DecideDish(BaseModel):
    recipe_id: Optional[int] = None
    name: str
    cuisine: str = ""
    category: str = ""
    cover_text: str = ""
    cook_minutes: int = 0
    calories: int = 0
    difficulty: int = 2
    main_ingredient: str = ""
    ingredients: List[str] = Field(default_factory=list)
    # 极简做法 3-5 步 (需求 10)
    steps: List[str] = Field(default_factory=list)


class DecisionResult(BaseModel):
    """一次决策的完整结果 —— 前端结果卡照着这个渲染"""

    id: int = 0
    dish: DecideDish
    # 一句话理由, <=20 字 (需求 6)
    reason: str
    meal_slot: str
    meal_slot_label: str = ""
    source: str = "local"
    weather: Dict[str, Any] = Field(default_factory=dict)
    advice: Optional[str] = None
    relaxed: bool = False
    decided_at: str = ""

    # ---- V1.2.0 R-07/R-16: 度量与灰度字段 ----
    # 这些以前靠 SuccessResponse.data: Any 透传: 能过, 但字段名字对不上没人会发现 ——
    # 前端按猜的名字取值, 猜错就是静默丢数据(string->0 的那种丢法)。显式声明出来,
    # 至少让"服务端给了什么"这件事有一处唯一真源。
    # relaxed_level / candidate_count 必须与 decision_log 的列名同名：
    # result 里写好之后会被 json.dump 进 payload 快照, /decide/last 回放时用的是同一份 key。
    relaxed_level: int = Field(default=0, description="放宽级别 0=未放宽; 1-4 见 R-10")
    # 通过 `_passes` 的候选数。它会高估用户实际的选择空间, 看"实际在几道里抽"用 band_size
    candidate_count: int = Field(default=0, description="放宽前候选池大小")
    # `_random_band` 实际返回的条数, 即用户真正在其中抽签的那几道菜。
    # 老决策行没有这个值时为 None(引擎侧该列还没完全落地时不下发), 不是 0 ——
    # 0 会被当成"当时抽签带是空的", 那是缺陷信号, 不能由缺值伪造。
    band_size: Optional[int] = Field(default=None, description="实际抽签带大小")
    session_id: Optional[str] = Field(default=None, description="本次会话 ID")
    # R-16 灰度版本。**没配置就是 None**, 不兜底成 'v1.2' —— 不知道分在哪组就记空,
    # 替用户填一个组会让灰度结论失效。前端拿不到时自己兜底(layout-version.ts)。
    layout_version: Optional[str] = Field(default=None, description="首页灰度版本: v1.1/v1.2")


class DecideProfile(BaseModel):
    """GET /decide/profile —— 决策所需的压缩档案"""

    has_profile: bool = False
    cuisines: List[str] = Field(default_factory=list)
    spice_level: int = 2
    avoid: List[str] = Field(default_factory=list)
    allergens: List[str] = Field(default_factory=list)
    scene_tags: List[str] = Field(default_factory=list)
    cook_cap: int = 60
    # 这一餐的预算上限(元): 日预算 ÷ 当日餐次; 用户没设过预算为 None
    meal_budget: Optional[float] = None
    meal_slot: str = MealSlot.DINNER
    weather: Dict[str, Any] = Field(default_factory=dict)


class DecideRecentItem(BaseModel):
    id: int
    dish_name: str
    meal_slot: str
    reason: Optional[str] = None
    source: str = "local"
    accepted: Optional[bool] = None
    decision_date: str
