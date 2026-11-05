"""Exercise real MySQL locking with separate request transactions."""
from __future__ import annotations

import asyncio

from app.models.fridge_inventory import FridgeInventory
from app.models.meal import MealEvent, MealProposal, MealSession, MealStockMovement
from app.schemas.meal import MealContextPatch
from app.services.meal_service import MealService
from sqlalchemy import func, select

from tests.conftest import requires_mysql
from tests.factories import make_ingredient, make_recipe, make_stock, make_user

pytestmark = requires_mysql


async def test_concurrent_initial_proposals_share_one_session(db_session, api_client, auth_headers):
    user = await make_user(db_session)
    await db_session.commit()
    headers = auth_headers(user.id)
    payload = {"context": {"meal_slot": "dinner"}, "expected_revision": 0}
    responses = await asyncio.gather(*[
        api_client.post("/api/meals/propose", headers=headers, json=payload) for _ in range(2)
    ])
    assert sorted(r.status_code for r in responses) == [200, 409], [r.text for r in responses]
    assert await db_session.scalar(select(func.count()).select_from(MealSession)) == 1
    assert await db_session.scalar(select(func.count()).select_from(MealProposal)) == 1


async def test_concurrent_completion_and_undo_do_not_double_move_stock(db_session, api_client, auth_headers):
    user = await make_user(db_session)
    ingredient = await make_ingredient(db_session, "面条")
    recipe = await make_recipe(db_session, "家常拌面", ingredient, 100)
    recipe.category = "面食"
    recipe.base_servings = 1
    await make_stock(db_session, user.id, ingredient, 500)
    await db_session.commit()
    service = MealService(db_session)
    view = await service.propose(
        user.id, MealContextPatch(meal_slot="dinner", servings=1, max_minutes=60),
        0, [f"recipe:{recipe.id}"],
    )
    await db_session.commit()
    headers = auth_headers(user.id)
    proposal_id = view["proposal"]["id"]

    async def concurrent_action(verb, revision, deduct=False):
        results = await asyncio.gather(*[
            api_client.post(f"/api/meals/{proposal_id}/{verb}", headers=headers, json={
                "expected_revision": revision, "deduct_inventory": deduct,
            }) for _ in range(2)
        ])
        assert [r.status_code for r in results] == [200, 200], [r.text for r in results]
        assert results[0].json()["data"]["revision"] == results[1].json()["data"]["revision"]
        return results[0].json()["data"]

    view = await concurrent_action("accept", view["revision"])
    view = await concurrent_action("complete", view["revision"], True)
    await db_session.rollback()
    assert await db_session.scalar(select(FridgeInventory.quantity)) == 400
    assert await db_session.scalar(select(func.count()).select_from(MealStockMovement)) == 1
    assert await db_session.scalar(select(func.count()).select_from(MealEvent).where(MealEvent.kind == "eaten")) == 1
    await db_session.rollback()
    await concurrent_action("undo", view["revision"])
    assert await db_session.scalar(select(FridgeInventory.quantity)) == 500
    assert await db_session.scalar(select(func.count()).select_from(MealStockMovement)) == 0


async def test_polling_during_meal_actions_does_not_deadlock(db_session, api_client, auth_headers):
    user = await make_user(db_session)
    await db_session.commit()
    headers = auth_headers(user.id)
    response = await api_client.post("/api/meals/propose", headers=headers, json={
        "context": {"meal_slot": "dinner"}, "expected_revision": 0,
    })
    assert response.status_code == 200, response.text
    view = response.json()["data"]

    async def polling():
        for _ in range(8):
            response = await api_client.get("/api/meals/current?meal_slot=dinner", headers=headers)
            assert response.status_code == 200, response.text
            assert response.json()["data"]["proposal"]["id"] == view["proposal"]["id"]

    async def actions():
        current = view
        for verb in ("accept", "complete", "undo"):
            response = await api_client.post(
                f"/api/meals/{view['proposal']['id']}/{verb}", headers=headers,
                json={"expected_revision": current["revision"]},
            )
            assert response.status_code == 200, response.text
            current = response.json()["data"]
        return current

    _, _, current = await asyncio.gather(polling(), polling(), actions())
    assert current["proposal"]["status"] == "accepted"
    assert current["revision"] == view["revision"] + 3
