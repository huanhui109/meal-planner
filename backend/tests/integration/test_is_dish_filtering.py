"""集成测试: 四条候选加载路径都得挡住非菜品

为什么单独一个文件:
    「饭决」主链路之外还有三条路径各 SELECT 一次 recipe —— 换一道菜、冰箱荐菜、
    周菜单生成。主链路修好而旁路没修, 用户体验是一样的崩坏: 点「换一个」照样能
    刷出油泼辣子。而且这类泄漏最难复现 —— 没人会把"偶尔冒出来一道蘸酱"当成 bug 报。

所以需要 MySQL (TEST_DATABASE_URL), 未设置时整文件跳过。
"""
from __future__ import annotations

from datetime import date

from app.config import get_settings
from app.models.recipe import Recipe
from app.services.decision_service import DecisionService
from app.services.fridge_menu_service import FridgeMenuService
from app.services.generation_service import MenuGenerationPipeline
from app.services.replacement_service import ReplaceContext, ReplacementService
from sqlalchemy import select

from tests.conftest import requires_mysql
from tests.factories import make_ingredient, make_recipe

pytestmark = requires_mysql

# 清单里真实存在的一条 —— 它就是这次事故的主角
CONDIMENT_NAME = "油泼辣子"
NORMAL_NAME = "番茄炒蛋"


async def seed(db_session) -> None:
    """造两道菜: 一道正常菜 + 一道被判非菜的调味品

    两道都按各条路径的准入条件填满(有步骤/有耗时/有食材/有热量), 否则候选加载会因为
    "字段不齐" 而不是 "不是一道菜" 把它们滤掉 —— 那样测试就成假绿了。
    """
    salt = await make_ingredient(db_session, "辣椒面")
    egg = await make_ingredient(db_session, "鸡蛋")

    normal = await make_recipe(db_session, NORMAL_NAME, egg, 100)
    normal.is_dish = True

    condiment = await make_recipe(db_session, CONDIMENT_NAME, salt, 20)
    condiment.is_dish = False

    await db_session.commit()


def assert_clean(names, path: str) -> None:
    assert names, f"{path}: 一条候选都没加载出来, 这个测试本身没意义"
    assert CONDIMENT_NAME not in names, f"{path} 泄漏了非菜品: {names}"


async def test_decision_main_path_excludes_non_dishes(db_session):
    await seed(db_session)
    names = [c.name for c in await DecisionService(db_session).load_candidates()]
    assert_clean(names, "decision_service.load_candidates")
    assert NORMAL_NAME in names


async def test_replace_one_excludes_non_dishes(db_session, monkeypatch):
    """换一道菜。SQL 跑真的, 只把打分那一步换成捕获器 —— 断言落在「加载出来的候选
    有哪些」上, 不吃打分权重漂移的影响"""
    await seed(db_session)

    seen: list = []
    service = ReplacementService(db_session)
    monkeypatch.setattr(
        service,
        "_collect",
        lambda recipes, ctx, inventory, skip_rejected=False: seen.extend(recipes) or [],
    )
    ctx = ReplaceContext(
        user_id=0, menu_id=0, item_id=0,
        meal_date=date(2026, 1, 5), meal_type="dinner", week_start=date(2026, 1, 5),
        cook_minutes_cap=60, target_calories=None,
        exclude_names=[], allergens=[], avoid=[], cuisines=[],
        pref_context="", inventory_lines=[], inventory_names=[],
        rejected_ids=[], spice_level=2, taste_tags=[], meal_budget=None,
    )
    await service._pick_local(ctx)

    names = [r.name for r in seen]
    assert_clean(names, "replacement_service._pick_local")
    assert NORMAL_NAME in names


async def test_fridge_menu_excludes_non_dishes(db_session):
    await seed(db_session)
    recipes = await FridgeMenuService(db_session)._load_candidates()
    assert_clean([r.name for r in recipes], "fridge_menu_service._load_candidates")


async def test_weekly_generation_excludes_non_dishes(db_session):
    """周菜单生成。这条路一年的量比「饭决」大得多, 排到调味品更不容易被察觉"""
    await seed(db_session)
    pipeline = MenuGenerationPipeline.__new__(MenuGenerationPipeline)
    pipeline.settings = get_settings()
    # 候选加载只用 settings 里的扫描上限, 不读 ctx
    recipes = await pipeline._load_local_candidates(None)  # type: ignore[arg-type]
    assert_clean([r.name for r in recipes], "generation_service._load_local_candidates")


async def test_non_dish_rows_stay_in_the_library(db_session):
    """只置 0 不删除: 用户主动搜调味品时仍然要能搜到"""
    await seed(db_session)
    row = (
        await db_session.execute(select(Recipe).where(Recipe.name == CONDIMENT_NAME))
    ).scalar_one_or_none()
    assert row is not None
    assert row.is_dish is False
