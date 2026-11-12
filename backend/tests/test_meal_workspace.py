"""Real HTTP and database tests. SQLite covers portable behavior; MySQL covers locking in CI."""

from __future__ import annotations

import hashlib
from datetime import timedelta

import httpx
import pytest
import pytest_asyncio
from app.auth.tokens import create_access_token
from app.dependencies import get_db
from app.main import app
from app.models.allergy_restriction import AllergyRestriction
from app.models.base import Base
from app.models.decision import DecisionLog
from app.models.meal import AssistantGrant, MealEvent, MealStockMovement
from app.schemas.meal import MealContextPatch
from app.services.meal_service import MealService, meal_now
from fastapi import HTTPException
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.factories import make_ingredient, make_recipe, make_stock, make_user


@pytest_asyncio.fixture
async def workspace():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        user = await make_user(db)
        other = await make_user(db, open_id="ou_other")
        await db.commit()

        async def override():
            try:
                yield db
                await db.commit()
            except Exception:
                await db.rollback()
                raise

        app.dependency_overrides[get_db] = override
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
            headers={"Authorization": f"Bearer {create_access_token(user.id)}"},
        ) as client:
            yield db, client, user.id, other.id
        app.dependency_overrides.pop(get_db, None)
    await engine.dispose()


async def propose(client, revision=0, **context):
    return await client.post("/api/meals/propose", json={
        "expected_revision": revision,
        "context": {"meal_slot": "dinner", **context},
    })


async def action(client, view, verb, **kwargs):
    return await client.post(f"/api/meals/{view['proposal']['id']}/{verb}", json={
        "expected_revision": view["revision"], **kwargs,
    })


async def test_no_key_no_inventory_auto_proposes_complete_family_meal(workspace):
    _, client, _, _ = workspace
    response = await propose(client, servings=3, max_minutes=60)
    assert response.status_code == 200, response.text
    view = response.json()["data"]
    assert view["proposal"]["source"] == "quick"
    assert view["proposal"]["servings"] == 3
    roles = {d["role"] for d in view["proposal"]["dishes"]}
    assert {"main", "side", "staple"} <= roles or {"complete", "side"} <= roles
    assert view["proposal"]["estimated_cost"] is None
    assert view["proposal"]["inventory_result"] is None
    assert all(d["name"] in view["proposal"]["title"] for d in view["proposal"]["dishes"])
    current = await client.get("/api/meals/current?meal_slot=dinner")
    assert current.json()["data"]["proposal"]["id"] == view["proposal"]["id"]


async def test_view_accept_complete_are_distinct_and_retries_idempotent(workspace):
    db, client, user_id, _ = workspace
    view = (await propose(client)).json()["data"]
    proposal_id = view["proposal"]["id"]
    assert not await MealService(db).eaten_names(user_id, meal_now().date())
    await client.post(f"/api/meals/{proposal_id}/viewed")
    await client.post(f"/api/meals/{proposal_id}/viewed")
    accepted = (await action(client, view, "accept")).json()["data"]
    assert accepted["proposal"]["status"] == "accepted"
    assert not await MealService(db).eaten_names(user_id, meal_now().date())
    retry = (await action(client, view, "accept")).json()["data"]
    assert retry["revision"] == accepted["revision"]
    eaten = (await action(client, accepted, "complete")).json()["data"]
    assert eaten["proposal"]["status"] == "eaten"
    assert await MealService(db).eaten_names(user_id, meal_now().date())
    assert eaten["proposal"]["inventory_result"]["deducted"] is False
    retry = (await action(client, accepted, "complete")).json()["data"]
    assert retry["revision"] == eaten["revision"]
    events = (await db.execute(select(MealEvent.kind).where(
        MealEvent.proposal_id == proposal_id,
    ))).scalars().all()
    assert events.count("accepted") == events.count("viewed") == events.count("eaten") == 1
    undone = (await action(client, eaten, "undo")).json()["data"]
    assert undone["proposal"]["status"] == "accepted"
    assert not await MealService(db).eaten_names(user_id, meal_now().date())


async def test_stale_revision_and_old_proposals_cannot_replace_current(workspace):
    _, client, _, _ = workspace
    old = (await propose(client)).json()["data"]
    new = (await propose(client, old["revision"])).json()["data"]
    assert new["proposal"]["id"] != old["proposal"]["id"]
    assert (await propose(client, old["revision"])).status_code == 409
    assert (await action(client, old, "accept")).status_code == 409


async def test_impossible_explicit_constraints_are_not_ignored(workspace):
    _, client, _, _ = workspace
    old = (await propose(client)).json()["data"]
    response = await propose(
        client, old["revision"], mode="cook", max_minutes=5,
        avoid=["米", "面", "蛋", "肉", "菜", "豆", "鱼", "虾", "粉", "粥", "土豆"],
    )
    assert response.status_code == 422
    current = (await client.get("/api/meals/current?meal_slot=dinner")).json()["data"]
    assert current["proposal"]["id"] == old["proposal"]["id"]
    assert current["revision"] == old["revision"]


async def test_takeout_has_no_fake_price_or_eta(workspace):
    _, client, _, _ = workspace
    view = (await propose(client, mode="takeout", budget=30, max_spice=0)).json()["data"]
    p = view["proposal"]
    assert p["mode"] == "takeout"
    assert p["estimated_minutes"] is None and p["estimated_cost"] is None
    assert p["takeout"]["search_term"] and "不辣" in p["takeout"]["order_note"]
    assert all(d["name"] in p["takeout"]["search_term"] for d in p["dishes"])
    assert all(d["spice"] == 0 for d in p["dishes"])


async def test_history_does_not_treat_seen_or_planned_as_eaten(workspace):
    db, _, user_id, _ = workspace
    db.add(DecisionLog(
        user_id=user_id, dish_name="番茄炒蛋", decision_date=meal_now().date(),
        meal_slot="dinner", source="local", is_cooked=False,
    ))
    await db.flush()
    assert "番茄炒蛋" not in await MealService(db).eaten_names(user_id, meal_now().date())
    row = (await db.execute(select(DecisionLog))).scalars().first()
    row.is_cooked = True
    await db.flush()
    assert "番茄炒蛋" in await MealService(db).eaten_names(user_id, meal_now().date())


async def test_cross_user_proposals_are_hidden(workspace):
    _, client, _, other = workspace
    view = (await propose(client)).json()["data"]
    client.headers["Authorization"] = f"Bearer {create_access_token(other)}"
    assert (await action(client, view, "accept")).status_code == 404
    assert (await client.get("/api/meals/history")).json()["data"] == []
    assert (await client.post(f"/api/meals/{view['proposal']['id']}/viewed")).status_code == 404


async def test_skill_can_save_but_cannot_accept_or_deduct_and_revocation_works(workspace):
    db, client, _, _ = workspace
    grant = (await client.post("/api/assistant/grants", json={})).json()["data"]
    token = grant["token"]
    stored = await db.get(AssistantGrant, grant["id"])
    assert stored.token_hash == hashlib.sha256(token.encode()).hexdigest()
    listed = (await client.get("/api/assistant/grants")).json()["data"]
    assert "token" not in listed[0] and "token_hash" not in listed[0]
    headers = {"Authorization": f"Bearer {token}"}
    context = (await client.post("/api/assistant/context", json={"meal_slot": "dinner"}, headers=headers)).json()["data"]
    keys = []
    for role in ("main", "side", "staple"):
        keys.append(next(d["key"] for d in context["candidates"] if d["role"] == role))
    saved = await client.post("/api/assistant/proposals", headers=headers, json={
        "context": {**context["context"], "max_minutes": 180},
        "candidate_keys": keys, "expected_revision": 0, "reason": "今晚按你的要求搭配",
    })
    assert saved.status_code == 200, saved.text
    view = saved.json()["data"]
    assert view["proposal"]["source"] == "assistant"
    assert (await client.get("/api/meals/current?meal_slot=dinner")).json()["data"]["proposal"]["id"] == view["proposal"]["id"]
    assert (await client.post(
        f"/api/meals/{view['proposal']['id']}/accept", headers=headers,
        json={"expected_revision": view["revision"]},
    )).status_code == 401
    await client.delete(f"/api/assistant/grants/{grant['id']}")
    assert (await client.post("/api/assistant/context", json={}, headers=headers)).status_code == 401


async def test_skill_cannot_override_saved_allergies_or_invent_candidates(workspace):
    db, client, user_id, _ = workspace
    db.add(AllergyRestriction(user_id=user_id, allergens='["蛋"]', avoid_ingredients="[]"))
    await db.commit()
    grant = (await client.post("/api/assistant/grants", json={})).json()["data"]
    headers = {"Authorization": f"Bearer {grant['token']}"}
    context = (await client.post("/api/assistant/context", headers=headers, json={
        "meal_slot": "dinner", "avoid": [],
    })).json()["data"]
    assert not any("蛋" in " ".join(d["ingredients"]) for d in context["candidates"])
    response = await client.post("/api/assistant/proposals", headers=headers, json={
        "context": context["context"], "expected_revision": 0,
        "candidate_keys": ["recipe:99999"],
    })
    assert response.status_code == 422


async def test_known_servings_scale_stock_and_undo_restores_expiry_even_after_batch_delete(workspace):
    db, _, user_id, _ = workspace
    ingredient = await make_ingredient(db, "面条")
    recipe = await make_recipe(db, "家常拌面", ingredient, 100)
    recipe.category = "面食"
    recipe.base_servings = 1
    expiry = meal_now().date() + timedelta(days=2)
    batch = await make_stock(db, user_id, ingredient, 500, expiry=expiry)
    await db.commit()
    service = MealService(db)
    view = await service.propose(user_id, MealContextPatch(
        meal_slot="dinner", servings=1, max_minutes=60,
    ), 0, [f"recipe:{recipe.id}"])
    await db.commit()
    view = await service.action(user_id, view["proposal"]["id"], "accept", view["revision"])
    await db.commit()
    view = await service.action(user_id, view["proposal"]["id"], "complete", view["revision"], True)
    await db.commit()
    assert batch.quantity == 400
    assert len((await db.execute(select(MealStockMovement))).scalars().all()) == 1
    # Deletion by another inventory workflow must not break undo or lose the expiry.
    await db.delete(batch)
    await db.commit()
    await service.action(user_id, view["proposal"]["id"], "undo", view["revision"])
    await db.commit()
    from app.models.fridge_inventory import FridgeInventory

    restored = (await db.execute(select(FridgeInventory))).scalars().one()
    assert restored.quantity == 100 and restored.expiry_date == expiry
    assert not (await db.execute(select(MealStockMovement))).scalars().all()


async def test_family_quantities_scale_and_future_completion_rejected(workspace):
    db, _, user_id, _ = workspace
    ingredient = await make_ingredient(db, "面条")
    recipe = await make_recipe(db, "家常拌面", ingredient, 100)
    recipe.category = "面食"
    recipe.base_servings = 1
    await db.commit()
    service = MealService(db)
    ctx = await service.assistant_context(user_id, MealContextPatch(
        meal_slot="dinner", servings=3, max_minutes=180,
        meal_date=meal_now().date() + timedelta(days=1),
    ))
    side = next(c["key"] for c in ctx["candidates"] if c["role"] == "side")
    view = await service.propose(
        user_id, MealContextPatch(**ctx["context"]), 0, [f"recipe:{recipe.id}", side],
    )
    assert view["proposal"]["dishes"][0]["requirements"][0]["quantity"] == 300
    view = await service.action(user_id, view["proposal"]["id"], "accept", view["revision"])
    with pytest.raises(HTTPException) as error:
        await service.action(user_id, view["proposal"]["id"], "complete", view["revision"])
    assert error.value.status_code == 422


async def test_saved_free_text_restrictions_are_not_silently_ignored(workspace):
    db, client, user_id, _ = workspace
    db.add(AllergyRestriction(user_id=user_id, dietary_restrictions="清真"))
    await db.commit()
    response = await propose(client)
    assert response.status_code == 422
    assert "不会忽略" in response.json()["detail"]


async def test_new_saved_allergy_invalidates_old_proposal_on_accept(workspace):
    db, client, user_id, _ = workspace
    view = (await propose(client)).json()["data"]
    name = view["proposal"]["dishes"][0]["ingredients"][0]
    import json

    db.add(AllergyRestriction(user_id=user_id, allergens=json.dumps([name])))
    await db.commit()
    response = await action(client, view, "accept")
    assert response.status_code == 409


async def test_skill_user_isolation_and_download(workspace):
    _, client, _, other = workspace
    grant = (await client.post("/api/assistant/grants", json={})).json()["data"]
    first = (await propose(client)).json()["data"]
    client.headers["Authorization"] = f"Bearer {create_access_token(other)}"
    assert (await client.get("/api/assistant/grants")).json()["data"] == []
    assert (await client.delete(f"/api/assistant/grants/{grant['id']}")).status_code == 404
    context = (await client.post("/api/assistant/context", json={"meal_slot": "dinner"}, headers={
        "Authorization": f"Bearer {grant['token']}",
    })).json()["data"]
    assert context["proposal"]["id"] == first["proposal"]["id"]
    assert (await client.get("/api/meals/current?meal_slot=dinner")).json()["data"]["proposal"] is None
    package = await client.get("/api/assistant/skill.zip")
    assert package.status_code == 200
    from io import BytesIO
    from zipfile import ZipFile

    with ZipFile(BytesIO(package.content)) as archive:
        # 精确清单：既有选菜 Skill 两件 + 应用内候选菜品 Skill 的规格与输出契约。
        # 保持「恰好这些文件」的断言力度，避免悄悄夹带其它内容进安装包。
        assert sorted(archive.namelist()) == [
            "fandecide/SKILL.md",
            "fandecide/candidates/SKILL.md",
            "fandecide/candidates/contract.json",
            "fandecide/scripts/fandecide.py",
        ]


async def test_serving_labels_misimported_as_ingredients_are_not_recommended(workspace):
    db, _, user_id, _ = workspace
    ingredient = await make_ingredient(db, "单人")
    recipe = await make_recipe(db, "煮泡面加蛋", ingredient, 1)
    recipe.category = "主食"
    await db.commit()
    context = await MealService(db).assistant_context(user_id, MealContextPatch(meal_slot="dinner"))
    assert not any(dish["key"] == f"recipe:{recipe.id}" for dish in context["candidates"])


async def test_plain_rice_is_not_a_complete_meal(workspace):
    db, _, user_id, _ = workspace
    ingredient = await make_ingredient(db, "大米")
    recipe = await make_recipe(db, "米饭", ingredient, 75)
    recipe.category = "主食"
    await db.commit()
    with pytest.raises(HTTPException) as error:
        await MealService(db).propose(
            user_id, MealContextPatch(meal_slot="dinner"), 0, [f"recipe:{recipe.id}"],
        )
    assert error.value.status_code == 422


async def test_bread_and_sweet_congee_cannot_replace_family_vegetables(workspace):
    db, _, user_id, _ = workspace
    bread = await make_ingredient(db, "吐司")
    toast = await make_recipe(db, "吐司果酱", bread, 2)
    toast.category = "小吃"
    rice = await make_ingredient(db, "糯米")
    congee = await make_recipe(db, "桂圆红枣粥", rice, 75)
    congee.category = "主食"
    await db.commit()
    context = await MealService(db).assistant_context(
        user_id, MealContextPatch(meal_slot="dinner", max_minutes=180),
    )
    candidates = {dish["key"]: dish for dish in context["candidates"]}
    assert candidates[f"recipe:{toast.id}"]["role"] == "staple"
    assert candidates[f"recipe:{congee.id}"]["role"] == "staple"


async def test_unclassified_food_is_not_mislabeled_as_vegetables(workspace):
    db, _, user_id, _ = workspace
    ingredient = await make_ingredient(db, "燕麦")
    recipe = await make_recipe(db, "即食燕麦", ingredient, 50)
    recipe.category = "小吃"
    await db.commit()
    context = await MealService(db).assistant_context(user_id, MealContextPatch(meal_slot="dinner"))
    assert not any(dish["key"] == f"recipe:{recipe.id}" for dish in context["candidates"])


@pytest.mark.parametrize("name", ["主料", "调料", "蒸架"])
async def test_placeholder_ingredients_and_utensils_are_not_food_candidates(workspace, name):
    db, _, user_id, _ = workspace
    ingredient = await make_ingredient(db, name)
    recipe = await make_recipe(db, "问题鸡肉饭", ingredient, 1)
    recipe.category = "主食"
    await db.commit()
    context = await MealService(db).assistant_context(user_id, MealContextPatch(meal_slot="dinner"))
    assert not any(dish["key"] == f"recipe:{recipe.id}" for dish in context["candidates"])


@pytest.mark.parametrize("avoid,name,ingredient", [
    ("肉", "日式肥牛丼饭", "肥牛"),
    ("牛肉", "葱爆肥牛", "肥牛"),
    ("大米", "日式肥牛丼饭", "肥牛"),
    ("小麦", "炒意大利面", "意大利面"),
])
async def test_explicit_ingredient_aliases_are_protected(workspace, avoid, name, ingredient):
    db, _, user_id, _ = workspace
    food = await make_ingredient(db, ingredient)
    recipe = await make_recipe(db, name, food, 100)
    recipe.category = "主食"
    await db.commit()
    context = await MealService(db).assistant_context(
        user_id, MealContextPatch(meal_slot="dinner", avoid=[avoid]),
    )
    assert not any(dish["key"] == f"recipe:{recipe.id}" for dish in context["candidates"])


async def test_zero_spice_excludes_chili_sauce_even_with_wrong_legacy_spice(workspace):
    db, _, user_id, _ = workspace
    ingredient = await make_ingredient(db, "韩式辣酱")
    recipe = await make_recipe(db, "韩式拌饭", ingredient, 10)
    recipe.category = "主食"
    recipe.spice_level = 0
    await db.commit()
    context = await MealService(db).assistant_context(
        user_id, MealContextPatch(meal_slot="dinner", mode="takeout", max_spice=0),
    )
    assert not any(dish["key"] == f"recipe:{recipe.id}" for dish in context["candidates"])


# ---- 菜品类别互斥大类 (迁移 0027) ----


async def _grant_headers(client):
    grant = (await client.post("/api/assistant/grants", json={})).json()["data"]
    return {"Authorization": f"Bearer {grant['token']}"}


def _key(candidates, category, role):
    return next(d["key"] for d in candidates if d["dish_category"] == category and d["role"] == role)


async def test_single_category_proposals_pass_and_cross_category_ones_are_blocked(workspace):
    """核心验证场景: 单一类别(含纯西餐)通过; 跨类别、尤其中西混排被 422 拦截"""
    _, client, _, _ = workspace
    headers = await _grant_headers(client)
    context = (await client.post("/api/assistant/context", headers=headers, json={
        "meal_slot": "dinner", "servings": 3, "max_minutes": 180,
    })).json()["data"]
    candidates = context["candidates"]

    async def post(keys, revision):
        return await client.post("/api/assistant/proposals", headers=headers, json={
            "context": {**context["context"], "servings": 3, "max_minutes": 180},
            "candidate_keys": keys, "expected_revision": revision,
        })

    # 1) 单一类别: 中餐三道 —— 通过
    cn = [_key(candidates, "chinese", role) for role in ("main", "side", "staple")]
    ok_cn = await post(cn, 0)
    assert ok_cn.status_code == 200, ok_cn.text
    assert {d["dish_category"] for d in ok_cn.json()["data"]["proposal"]["dishes"]} == {"chinese"}
    revision = ok_cn.json()["data"]["revision"]

    # 2) 跨类别: 中餐主菜+配菜 配 西餐主食 —— 中西专门文案
    mixed_west = [_key(candidates, "chinese", "main"), _key(candidates, "chinese", "side"),
                  _key(candidates, "western", "staple")]
    bad = await post(mixed_west, revision)
    assert bad.status_code == 422, bad.text
    assert "中餐与西餐" in bad.json()["detail"]
    # 被拦后原方案不变, 不会静默成功
    current = (await client.get("/api/meals/current?meal_slot=dinner")).json()["data"]
    assert current["revision"] == revision
    assert current["proposal"]["id"] == ok_cn.json()["data"]["proposal"]["id"]

    # 3) 非中西跨类别也被拦(所有菜品类别必须一致)
    mixed_jk = [_key(candidates, "chinese", "main"), _key(candidates, "japanese_korean", "side"),
                _key(candidates, "chinese", "staple")]
    bad2 = await post(mixed_jk, revision)
    assert bad2.status_code == 422, bad2.text
    assert "类别必须一致" in bad2.json()["detail"]

    # 4) 纯西餐单一类别也能通过 —— 严格口径没有把西餐饿死
    west = [_key(candidates, "western", role) for role in ("main", "side", "staple")]
    ok_west = await post(west, revision)
    assert ok_west.status_code == 200, ok_west.text
    assert {d["dish_category"] for d in ok_west.json()["data"]["proposal"]["dishes"]} == {"western"}


async def test_dish_category_preference_filters_candidates_and_keeps_other_preferences(workspace):
    """偏好单选生效; 忌口/辣度等原有偏好不受影响; 自动组装也只出同类别方案"""
    from app.models.diet_preference import DietPreference

    db, client, user_id, _ = workspace
    db.add(DietPreference(
        user_id=user_id, cuisines='["家常"]', spice_level=1, dish_category="western",
    ))
    db.add(AllergyRestriction(
        user_id=user_id, allergens="[]", avoid_ingredients='["花生"]', dietary_restrictions="",
    ))
    await db.commit()

    view = (await client.get("/api/meals/current?meal_slot=dinner")).json()["data"]
    assert view["context"]["dish_category"] == "western"
    assert view["context"]["max_spice"] == 1  # 原有辣度偏好仍在

    auto = await propose(client, servings=3, max_minutes=180)
    assert auto.status_code == 200, auto.text
    dishes = auto.json()["data"]["proposal"]["dishes"]
    assert dishes and {d["dish_category"] for d in dishes} == {"western"}

    headers = await _grant_headers(client)
    ctx = (await client.post("/api/assistant/context", headers=headers, json={
        "meal_slot": "dinner", "max_minutes": 180,
    })).json()["data"]
    assert ctx["candidates"]
    assert {d["dish_category"] for d in ctx["candidates"]} == {"western"}
    assert not any("花生" in " ".join(d["ingredients"]) for d in ctx["candidates"])


async def test_invalid_dish_category_value_is_rejected_at_schema_layer(workspace):
    _, client, _, _ = workspace
    response = await client.put("/api/preferences/diet", json={
        "cuisines": ["家常"], "spice_level": 2, "dish_category": "川菜",
    })
    assert response.status_code == 422
    # 合法值 + 空串(不限)都要能保存
    for value in ("western", ""):
        ok = await client.put("/api/preferences/diet", json={
            "cuisines": ["家常"], "spice_level": 2, "dish_category": value,
        })
        assert ok.status_code == 200, ok.text


async def test_changed_category_preference_is_not_overridden_by_old_session(workspace):
    """设置页改了类别之后, 旧的 session.context 不能把它盖回去"""
    from app.models.diet_preference import DietPreference

    db, client, user_id, _ = workspace
    first = await propose(client, servings=3, max_minutes=180)
    assert first.status_code == 200
    db.add(DietPreference(
        user_id=user_id, cuisines='["家常"]', spice_level=2, dish_category="western",
    ))
    await db.commit()
    view = (await client.get("/api/meals/current?meal_slot=dinner")).json()["data"]
    assert view["context"]["dish_category"] == "western"


async def test_diet_update_without_category_field_keeps_stored_category(workspace):
    """老客户端(引导流程)请求体里没有 dish_category 时, 不能把已选类别清掉

    /preferences/diet 是整对象覆盖, 但「没送这个字段」和「显式送 null」语义不同:
    前者是老客户端不认这个字段, 后者才是用户主动选了「不限」。
    """
    _, client, _, _ = workspace
    base = {"cuisines": ["家常"], "spice_level": 2}
    await client.put("/api/preferences/diet", json={**base, "dish_category": "chinese"})

    kept = await client.put("/api/preferences/diet", json=base)
    assert kept.status_code == 200, kept.text
    assert kept.json()["data"]["dish_category"] == "chinese"

    cleared = await client.put("/api/preferences/diet", json={**base, "dish_category": None})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["data"]["dish_category"] is None
