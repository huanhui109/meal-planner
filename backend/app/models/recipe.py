"""菜谱模型

字段分三层, 别混着看:
    基础层    name/cuisine/steps/nutrition —— 任何菜谱库都有
    决策层    0014 加的 category/main_ingredient/tags/spice_level/is_light —— 给「饭决」打分用
    场景层    0016 加的 meal_slots/meat_type/tools/season —— 回答"这一顿能不能吃它"

为什么还要场景层: 「今天吃啥」这个命题里, 前两层回答的是"好不好吃", 场景层回答的
是"合不合适"。早上 7 点推红烧肉、家里没烤箱推烤羊排, 打分再准也是错的。这些维度
以前一个都没有, 全靠 is_light + cook_minutes 硬凑。

数据来源两路: 规则兜底(确定性、可离线) + LLM 定时富集(写得更好)。谁写的记在
enrich_source / steps_source 上, 出问题能追到人。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class MeatType:
    """荤型 —— 替代以前靠菜名文本猜荤素的土办法

    以前 `intent_service._looks_like_meat()` 拿菜名+食材做字符串匹配, 于是「鸡蛋」
    含「鸡」被判成荤、「鸡精」含「鸡」被判成肉, 用户说"吃素"却连番茄炒蛋都吃不上。
    抠假阳性词只是打补丁: 数据里就该有明确答案。
    """

    NONE = "none"            # 纯素
    EGG_DAIRY = "egg_dairy"  # 蛋奶素(蛋/奶制品, 无肉)
    POULTRY = "poultry"      # 禽(鸡鸭鹅)
    RED_MEAT = "red_meat"    # 红肉(猪牛羊)
    SEAFOOD = "seafood"      # 水产(鱼虾蟹贝)
    MIXED = "mixed"          # 混合

    ALL = (NONE, EGG_DAIRY, POULTRY, RED_MEAT, SEAFOOD, MIXED)
    LABELS = {
        NONE: "素",
        EGG_DAIRY: "蛋奶素",
        POULTRY: "禽肉",
        RED_MEAT: "红肉",
        SEAFOOD: "水产",
        MIXED: "混合荤",
    }
    # 素食口径: 严格素只认 NONE; 蛋奶素看用户的忌口设置, 这里只给最小集合
    VEGETARIAN_OK = (NONE,)


class DishSeason:
    """时令。空数组 = 四季皆可, 不参与过滤"""

    SPRING = "spring"
    SUMMER = "summer"
    AUTUMN = "autumn"
    WINTER = "winter"

    ALL = (SPRING, SUMMER, AUTUMN, WINTER)
    LABELS = {SPRING: "春", SUMMER: "夏", AUTUMN: "秋", WINTER: "冬"}


class CookTool:
    """所需厨具。空数组/仅 [NONE] = 有口锅就能做"""

    NONE = "none"        # 无特殊要求
    WOK = "wok"          # 炒锅
    STEAMER = "steamer"  # 蒸锅
    OVEN = "oven"        # 烤箱
    AIR_FRYER = "air_fryer"
    MICROWAVE = "microwave"
    RICE_COOKER = "rice_cooker"  # 电饭煲
    POT = "pot"          # 汤锅/炖锅
    PAN = "pan"          # 平底锅
    GRILL = "grill"      # 烤架/烧烤

    ALL = (NONE, WOK, STEAMER, OVEN, AIR_FRYER, MICROWAVE, RICE_COOKER, POT, PAN, GRILL)
    LABELS = {
        NONE: "无特殊", WOK: "炒锅", STEAMER: "蒸锅", OVEN: "烤箱",
        AIR_FRYER: "空气炸锅", MICROWAVE: "微波炉", RICE_COOKER: "电饭煲",
        POT: "汤锅", PAN: "平底锅", GRILL: "烤架",
    }


class EnrichStatus:
    """字段富集的完成度 —— 定时任务靠它挑下一批该补谁"""

    PENDING = "pending"  # 还没补过
    PARTIAL = "partial"  # 补了一部分(例如只补了步骤)
    DONE = "done"        # 决策所需字段齐了
    FAILED = "failed"    # LLM 不可用/返回不可信, 下次再来

    ALL = (PENDING, PARTIAL, DONE, FAILED)


class EnrichSource:
    """谁写的这些数据。出问题时这是第一现场"""

    SEED = "seed"    # 导入时就带
    RULE = "rule"    # 规则推断
    LLM = "llm"      # 兜底大模型
    MANUAL = "manual"  # 人工校对(优先级最高, 不该被覆盖)

    ALL = (SEED, RULE, LLM, MANUAL)


class Recipe(Base, TimestampMixin):
    __tablename__ = "recipe"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, comment="菜名")
    cuisine: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, comment="菜系")
    category: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, comment="品类: 荤菜/素菜/汤羹/主食/面食/凉菜/小吃, 同品类打散用"
    )
    difficulty: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="难度 1-5")
    cook_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="烹饪时间(分钟)")
    calories: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="热量(kcal)")
    protein_g: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="蛋白质(g)")
    carb_g: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="碳水(g)")
    fat_g: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="脂肪(g)")
    steps: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="烹饪步骤")
    source: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        default="ai_generated",
        comment="来源: ai_generated/user_created/template",
    )

    # ---- 以下字段为「饭决」决策引擎服务 (v1.0.0 迁移 0014) ----
    # 主料: 判断"连续两餐不重样"的最小粒度。写菜的主角, 如 番茄炒蛋 → 鸡蛋
    main_ingredient: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, comment="主料")
    tags: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True, comment="场景标签 JSON 数组: 快手/一锅出/下饭/汤羹/轻食/夜宵/雨天/热辣/清爽"
    )
    flavor_tags: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True, comment="味型标签 JSON 数组: 辣/酸/甜/咸鲜/酱香"
    )
    spice_level: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="辣度 0-4"
    )
    is_light: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
        comment="是否轻食: 深夜时段只从这部分里挑",
    )
    cover_text: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, comment="结果卡角标短文本")
    quick_steps: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="极简做法 JSON 数组, 3-5 步, 每步 <=20 字"
    )

    # ---- 以下字段为「这一顿合不合适」服务 (v1.1.0 迁移 0016) ----
    meal_slots: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="适合餐次 JSON 数组: breakfast/lunch/dinner/late_night; NULL=不限制",
    )
    meat_type: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True, comment="荤型: none/egg_dairy/poultry/red_meat/seafood/mixed"
    )
    # ⚠️ 取值以库为准, 不要照老注释写: 老注释写的是 wok/steamer/oven/air_fryer,
    # 而库里**没有 wok**, 最常见的是 pot —— 谁照着老注释做中文映射, 42 道菜会显示空白。
    # (2026-09-23 实跑 SELECT tools, COUNT(*) FROM recipe GROUP BY tools:
    #  ["pot"] 42 / ["steamer"] 13 / ["oven"] 11 / ["air_fryer"] 5 / ["pot","steamer"] 1;
    #  共 72/396 有值 = 18.2% 覆盖率)
    # 另注: 数组可能是**多值** (那道 ["pot","steamer"]), 别假设只有一项。
    # 与 household.kitchen_equipments 词表不通(那边是中文"灶台/蒸锅/烤箱/空气炸锅"),
    # 做 R-13 厨具接线前必须先解决两边的映射。
    tools: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True, comment="所需厨具 JSON 数组: pot/steamer/oven/air_fryer"
    )
    season: Mapped[Optional[str]] = mapped_column(
        String(60), nullable=True, comment="时令 JSON 数组: spring/summer/autumn/winter; 空=四季"
    )
    enrich_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=EnrichStatus.PENDING,
        server_default="pending",
        comment="富集状态: pending/partial/done/failed",
    )
    enriched_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, comment="最近一次富集时间"
    )
    enrich_source: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True, comment="字段来源: seed/rule/llm/manual"
    )
    steps_source: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True, comment="做法来源: seed/rule/llm/manual"
    )

    # ---- 是否参与「饭决」 (v1.2.0 迁移 0017) ----
    # 为什么单独一列而不是拿 cuisine 判: cuisine 现在装的是源分类, 清洗成真菜系后
    # 基于它的黑名单会静默失效。判定走的始终是 app/services/dish_rules.guess_is_dish。
    is_dish: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
        comment="是否是一道正经的菜: 0=调味品/饮品/甜品/半成品加工, 不参与「饭决」决策; 1=正常候选",
    )

    recipe_ingredients = relationship(
        "RecipeIngredient", back_populates="recipe", cascade="all, delete-orphan", lazy="selectin"
    )


class RecipeIngredient(Base, TimestampMixin):
    __tablename__ = "recipe_ingredient"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recipe_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("recipe.id", ondelete="CASCADE"), nullable=False
    )
    ingredient_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ingredient.id", ondelete="CASCADE"), nullable=False
    )
    quantity: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, comment="用量(标准单位), 无法量化时为 NULL"
    )
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="", comment="标准单位")
    amount_text: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, comment="LLM 返回的原始用量文本, 如 '适量'"
    )

    recipe = relationship("Recipe", back_populates="recipe_ingredients")
    ingredient = relationship("Ingredient", lazy="selectin")


class EnrichKind:
    """富集任务的类型 —— 定时任务按缺口挑, 日志按这个分账"""

    FIELDS = "fields"  # 补决策/场景字段
    STEPS = "steps"    # 写做菜步骤(详细 steps + 极简 quick_steps)
    EXPAND = "expand"  # 补新菜品(按缺口定向生成)

    ALL = (FIELDS, STEPS, EXPAND)


class RecipeEnrichLog(Base):
    """每一次菜品富集的流水

    为什么单独一张表: 定时任务是在没人看着的时候跑的, 跑完了说不清"补了几道、
    哪些没补成、为什么"。recipe.enrich_status 只存**结果**, 这张表存**过程**。
    LLM 不可用时这里会记下原因, 否则线上"模型一直没生效"没人知道 —— 和
    SystemOneService.last_error 是同一个道理。
    """

    __tablename__ = "recipe_enrich_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recipe_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("recipe.id", ondelete="CASCADE"), nullable=True,
        comment="EXPAND 成功前为 NULL(菜还不存在)"
    )
    dish_name: Mapped[str] = mapped_column(String(200), nullable=False, comment="菜名(冗余)")
    kind: Mapped[str] = mapped_column(
        String(20), nullable=False, default=EnrichKind.FIELDS, comment="fields/steps/expand"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="ok/skipped/failed"
    )
    provider: Mapped[str] = mapped_column(
        String(30), nullable=False, default="", comment="llm 链里真正用上的那个客户端名"
    )
    fields: Mapped[Optional[str]] = mapped_column(
        String(300), nullable=True, comment="本次实际写入的字段名, 逗号分隔"
    )
    message: Mapped[Optional[str]] = mapped_column(String(500), nullable=True, comment="失败原因/备注")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )
