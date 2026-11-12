from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Optional
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.allergy_restriction import AllergyRestriction
from app.models.decision import DecisionLog
from app.models.diet_preference import DietPreference
from app.models.fridge_inventory import FridgeInventory
from app.models.household import Household
from app.models.ingredient import Ingredient
from app.models.meal import MealEvent, MealProposal, MealSession, MealStockMovement
from app.models.menu import Menu, MenuItem
from app.models.user import User
from app.schemas.meal import MealContext, MealContextPatch
from app.schemas.serializers import json_list
from app.services.decision_service import CST, DecisionService, normalize_dish_name
from app.services.deeplink_service import PLATFORM_MEITUAN, DeeplinkService
from app.services.ingredient_amount import convert_quantity
from app.services.meal_catalog import (
    STAPLES,
    MealCandidate,
    compose_meal,
    filter_catalog,
    ingredient_matches,
    load_meal_catalog,
    meal_minutes,
    validate_composition,
)


def meal_now() -> datetime:
    return datetime.now(CST).replace(tzinfo=None)


def problem(status: int, message: str):
    raise HTTPException(status_code=status, detail=message)


class MealService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def lock_user(self, user_id: int) -> None:
        # Serialize the meal's read-modify-write cycle, including first-session creation.
        await self.db.execute(
            select(User).where(User.id == user_id).with_for_update()
            .execution_options(populate_existing=True)
        )

    async def defaults(self, user_id: int) -> MealContext:
        engine = DecisionService(self.db)
        profile = await engine.load_profile(user_id)
        household = (await self.db.execute(
            select(Household).where(Household.user_id == user_id)
        )).scalar_one_or_none()
        diet = (await self.db.execute(
            select(DietPreference.dish_category).where(DietPreference.user_id == user_id)
        )).scalar_one_or_none()
        now = meal_now()
        return MealContext(
            meal_date=now.date(),
            meal_slot=engine._resolve_slot(None, now),
            servings=household.member_count if household else 1,
            max_minutes=min(180, max(5, profile.cook_cap if household else 30)),
            max_spice=min(4, max(0, profile.spice_level)),
            budget=profile.meal_budget,
            dish_category=diet or None,
        )

    async def session(self, user_id: int, context: MealContext) -> Optional[MealSession]:
        return (await self.db.execute(
            select(MealSession).where(
                MealSession.user_id == user_id, MealSession.meal_date == context.meal_date,
                MealSession.meal_slot == context.meal_slot,
            ).with_for_update().execution_options(populate_existing=True)
        )).scalar_one_or_none()

    async def resolve(
        self, user_id: int, patch: MealContextPatch,
    ) -> tuple[MealContext, Optional[MealSession]]:
        default = await self.defaults(user_id)
        changes = patch.model_dump(exclude_unset=True, mode="json")
        changes = {key: value for key, value in changes.items() if value is not None or key == "budget"}
        target = MealContext.model_validate({**default.model_dump(mode="json"), **changes})
        session = await self.session(user_id, target)
        if session:
            # 类别是长期口味: 设置页改了之后, 旧的 session.context 不能把它盖回去。
            # 其余条件沿用 session(单次会话里调过的时间/人数不该被重置);
            # patch 显式传的 dish_category 仍在最后合并, 优先级最高。
            stored = {**session.context, "dish_category": default.dish_category}
            target = MealContext.model_validate({**stored, **changes})
        if abs((target.meal_date - meal_now().date()).days) > 30:
            problem(422, "请选择前后 30 天内的一餐")
        return target, session

    async def current(self, user_id: int, patch: MealContextPatch) -> dict:
        await self.lock_user(user_id)
        context, session = await self.resolve(user_id, patch)
        return await self.view(context, session)

    async def view(self, context: MealContext, session: Optional[MealSession]) -> dict:
        proposal = await self.owned(session.user_id, session.current_proposal_id) \
            if session and session.current_proposal_id else None
        return {
            "context": context.model_dump(mode="json"),
            "session_id": session.id if session else None,
            "revision": session.revision if session else 0,
            "proposal": self.proposal_view(proposal) if proposal else None,
        }

    @staticmethod
    def proposal_view(proposal: MealProposal) -> dict:
        return {
            **proposal.snapshot, "id": proposal.id, "source": proposal.source,
            "status": proposal.status,
            "accepted_at": proposal.accepted_at.isoformat() if proposal.accepted_at else None,
            "eaten_at": proposal.eaten_at.isoformat() if proposal.eaten_at else None,
            "created_at": proposal.created_at.isoformat() if proposal.created_at else None,
        }

    async def eaten_names(self, user_id: int, day: date) -> set[str]:
        since = day - timedelta(days=7)
        snapshots = (await self.db.execute(
            select(MealProposal.snapshot).join(MealSession, MealSession.id == MealProposal.session_id)
            .where(
                MealProposal.user_id == user_id, MealProposal.status == "eaten",
                MealSession.meal_date >= since, MealSession.meal_date <= day,
            )
        )).scalars().all()
        names = {
            normalize_dish_name(d["name"]) for snap in snapshots for d in snap.get("dishes", [])
            if d.get("role") != "staple"
        }
        legacy = (await self.db.execute(select(DecisionLog.dish_name).where(
            DecisionLog.user_id == user_id, DecisionLog.is_cooked.is_(True),
            DecisionLog.decision_date >= since, DecisionLog.decision_date <= day,
        ))).scalars().all()
        names.update(normalize_dish_name(n) for n in legacy)
        from app.models.recipe import Recipe

        menu_names = (await self.db.execute(
            select(Recipe.name).join(MenuItem, MenuItem.recipe_id == Recipe.id)
            .join(Menu, Menu.id == MenuItem.menu_id).where(
                Menu.user_id == user_id, MenuItem.is_cooked.is_(True),
                MenuItem.meal_date >= since, MenuItem.meal_date <= day,
            )
        )).scalars().all()
        names.update(normalize_dish_name(n) for n in menu_names)
        return names

    async def inputs(self, user_id: int, context: MealContext) -> tuple[list[MealCandidate], list, list[str]]:
        restriction = (await self.db.execute(
            select(AllergyRestriction).where(AllergyRestriction.user_id == user_id)
        )).scalar_one_or_none()
        protected = (json_list(restriction.allergens) + json_list(restriction.avoid_ingredients)) \
            if restriction else []
        vegetarian = context.vegetarian
        if restriction and restriction.dietary_restrictions:
            for term in re.split(r"[，,、；;\n]+", restriction.dietary_restrictions.strip()):
                term = term.strip()
                if not term or term in ("无", "不限"):
                    continue
                if term in ("素食", "不吃肉", "蛋奶素"):
                    vegetarian = True
                elif term.startswith("不吃") and len(term) > 2 and not any(word in term for word in ("和", "或", "但")):
                    protected.append(term[2:])
                else:
                    problem(422, f"暂时无法可靠校验长期饮食限制“{term}”，请在偏好中明确为不吃的食材；不会忽略此要求")
        household = (await self.db.execute(
            select(Household).where(Household.user_id == user_id)
        )).scalar_one_or_none()
        equipment = json_list(household.kitchen_equipments) if household else []
        tool_names = {
            "灶台": "wok", "炒锅": "wok", "汤锅": "pot", "蒸锅": "steamer", "烤箱": "oven",
            "空气炸锅": "air_fryer", "微波炉": "microwave", "电饭煲": "rice_cooker",
            "平底锅": "pan", "烤架": "grill",
        }
        tools = {tool_names.get(tool, tool) for tool in equipment} if equipment else None
        catalog = filter_catalog(
            await load_meal_catalog(self.db), context.model_copy(update={"vegetarian": vegetarian}), protected,
            await self.eaten_names(user_id, context.meal_date), tools,
        )
        stock = list((await self.db.execute(
            select(FridgeInventory, Ingredient.name)
            .join(Ingredient, Ingredient.id == FridgeInventory.ingredient_id).where(
                FridgeInventory.user_id == user_id, FridgeInventory.quantity > 0,
            ).order_by(FridgeInventory.id)
        )).all())
        stock = [(row, name) for row, name in stock if not row.expiry_date or row.expiry_date >= context.meal_date]
        return catalog, stock, protected

    @staticmethod
    def check_revision(session: Optional[MealSession], expected: int) -> None:
        if (session.revision if session else 0) != expected:
            problem(409, "这一餐已在另一处更新，已保留最新方案，请刷新后再试")

    async def assistant_context(self, user_id: int, patch: MealContextPatch) -> dict:
        await self.lock_user(user_id)
        context, session = await self.resolve(user_id, patch)
        candidates, stock, protected = await self.inputs(user_id, context)
        return {
            **(await self.view(context, session)),
            "protected_avoid": protected,
            "inventory": [{"name": name, "quantity": row.quantity, "unit": row.unit,
                           "expiry_date": row.expiry_date.isoformat() if row.expiry_date else None}
                          for row, name in stock],
            "candidates": [c.view(context.servings) for c in candidates],
            "rules": [
                "仅使用候选 key，主食与菜品组成完整一餐，不能杜撰菜谱或配料",
                "同一份方案的菜品类别（含主食）必须完全一致；中餐与西餐绝对不能混搭",
                "保存只是建议，不代表已采纳或已吃，也不会扣库存",
                "参考价格和烹饪时间不是实价或实测；外卖配料需向商家确认",
            ],
        }

    async def propose(
        self, user_id: int, patch: MealContextPatch, expected: int,
        keys: Optional[list[str]] = None, reason: str = "",
    ) -> dict:
        await self.lock_user(user_id)
        context, session = await self.resolve(user_id, patch)
        self.check_revision(session, expected)
        old = await self.owned(user_id, session.current_proposal_id) \
            if session and session.current_proposal_id else None
        if old and old.status == "eaten":
            problem(409, "这一餐已记为吃过，请先撤销记录，再调整方案")
        candidates, stock, protected = await self.inputs(user_id, context)
        if keys is not None:
            selected = {c.key: c for c in candidates}
            if any(key not in selected for key in keys):
                problem(422, "部分候选不存在或不再符合当前要求，请重新读取上下文；已保存的忌口不能被覆盖")
            chosen = [selected[key] for key in keys]
            error = validate_composition(chosen, context)
            if error:
                problem(422, error)
        else:
            previous = (await self.db.execute(
                select(MealProposal.snapshot).where(MealProposal.session_id == session.id)
            )).scalars().all() if session else []
            rejected = {"|".join(sorted(d["key"] for d in p["dishes"])) for p in previous}
            chosen = compose_meal(candidates, context, [name for _, name in stock], rejected, str(uuid4()))
            if chosen is None and context.mode == "auto":
                context = context.model_copy(update={"mode": "takeout"})
                candidates, stock, protected = await self.inputs(user_id, context)
                chosen = compose_meal(candidates, context, [], rejected, str(uuid4()))
            if chosen is None:
                problem(422, "暂时凑不出符合要求的完整一餐。请调整时间、口味或用餐方式；忌口不会被自动放宽")
        if session is None:
            session = MealSession(
                id=str(uuid4()), user_id=user_id, meal_date=context.meal_date,
                meal_slot=context.meal_slot, context=context.model_dump(mode="json"), revision=0,
            )
            self.db.add(session)
            await self.db.flush()
        if old:
            old.status = "rejected"
            self.event(old.id, "rejected")
        snapshot = self.snapshot(chosen, context, stock, protected)
        if keys is not None and reason.strip():
            snapshot["assistant_note"] = reason.strip()
        proposal = MealProposal(
            id=str(uuid4()), session_id=session.id, user_id=user_id,
            source="assistant" if keys is not None else "quick",
            status="proposed", snapshot=snapshot,
        )
        self.db.add(proposal)
        await self.db.flush()
        session.current_proposal_id = proposal.id
        session.context = context.model_dump(mode="json")
        session.revision += 1
        self.event(proposal.id, "proposed")
        await self.db.flush()
        return await self.view(context, session)

    @staticmethod
    def snapshot(
        chosen: list[MealCandidate], context: MealContext, stock: list, protected: list[str],
    ) -> dict:
        dishes = [c.view(context.servings) for c in chosen]
        cooking = context.mode != "takeout"
        owned = [name for _, name in stock]
        ingredients = list(dict.fromkeys(
            ing for c in chosen for ing in c.dish.ingredients if ing not in STAPLES
        ))
        available = [ing for ing in ingredients if any(ingredient_matches(ing, n) for n in owned)]
        missing = [ing for ing in ingredients if ing not in available]
        costs = [d["estimated_cost"] for d in dishes]
        cost = round(sum(costs), 2) if cooking and all(c is not None for c in costs) else None
        warnings = []
        if cooking:
            warnings.append("用时为菜谱参考值；多人份及不同厨具可能需要更久")
            if any(c.base_servings is None for c in chosen):
                warnings.append(f"部分菜谱未标注原始份数，请按 {context.servings} 人确认份量，不能精确扣减这些食材")
            if cost is None:
                warnings.append("食材价格或配方份数不完整，暂不提供整餐成本")
        else:
            warnings.append("未接入商家实价和配送时间，具体配料与忌口请向商家确认")
        if context.budget and cost is None:
            warnings.append(f"本餐预算目标 ¥{context.budget:g}，尚未核验实际花费")
        dish_names = [c.dish.name for c in chosen]
        title = " · ".join(dish_names)
        keyword = " ".join(dish_names)
        all_avoids = list(dict.fromkeys(context.avoid + protected))
        deeplink = DeeplinkService().search_link(keyword, PLATFORM_MEITUAN)
        if not deeplink.startswith(("https://", "http://", "meituanwaimai://", "imeituan://")):
            deeplink = ""
        return {
            "title": title, "mode": "cook" if cooking else "takeout",
            "context": context.model_dump(mode="json"),
            "servings": context.servings, "dishes": dishes,
            "reason": (
                f"家里已有 {len(available)} 样主要食材，顺手安排这一餐"
                if cooking and available else
                "主食和配菜一起安排，今天不用再从头想"
                if cooking else "这一餐交给外卖，主食和配菜一起点好"
            ),
            "estimated_minutes": meal_minutes(chosen) if cooking else None,
            "estimated_cost": cost, "available": available, "missing": missing,
            "warnings": warnings,
            "protected_avoid": protected,
            "takeout": None if cooking else {
                "search_term": keyword, "search_url": deeplink,
                "order_note": f"{context.servings} 人份；"
                + ("不辣；" if context.max_spice == 0 else "")
                + (f"不要 {'、'.join(all_avoids)}；" if all_avoids else "")
                + "请确认配料和份量，按需备注餐具",
            },
            "inventory_result": None,
        }

    def event(self, proposal_id: str, kind: str) -> None:
        self.db.add(MealEvent(proposal_id=proposal_id, kind=kind, occurred_at=meal_now()))

    async def record_view(self, user_id: int, proposal_id: str) -> None:
        await self.lock_user(user_id)
        proposal = await self.owned(user_id, proposal_id)
        exists = (await self.db.execute(select(MealEvent.id).where(
            MealEvent.proposal_id == proposal.id, MealEvent.kind == "viewed",
        ).limit(1))).scalar_one_or_none()
        if exists is None:
            self.event(proposal.id, "viewed")
            await self.db.flush()

    async def owned(self, user_id: int, proposal_id: str) -> MealProposal:
        proposal = (await self.db.execute(select(MealProposal).where(
            MealProposal.id == proposal_id, MealProposal.user_id == user_id,
        ).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
        if proposal is None:
            problem(404, "找不到这一餐")
        return proposal

    async def action(
        self, user_id: int, proposal_id: str, action: str, expected: int, deduct: bool = False,
    ) -> dict:
        await self.lock_user(user_id)
        proposal = await self.owned(user_id, proposal_id)
        session = (await self.db.execute(select(MealSession).where(
            MealSession.id == proposal.session_id,
        ).with_for_update().execution_options(populate_existing=True))).scalar_one()
        if session.current_proposal_id != proposal.id:
            problem(409, "这份建议已被替换，请使用最新方案")
        context = MealContext.model_validate(session.context)
        # Retried successful actions are idempotent even with the previous revision.
        idempotent = (
            action == "accept" and proposal.status in ("accepted", "eaten")
            or action == "complete" and proposal.status == "eaten"
            or action == "undo" and proposal.status == "accepted" and proposal.eaten_at is None
        )
        if idempotent:
            return await self.view(context, session)
        self.check_revision(session, expected)
        if action == "accept":
            if proposal.status != "proposed":
                problem(409, "当前方案不能被采纳，请重新读取这一餐")
            current, _, _ = await self.inputs(user_id, context)
            valid = {c.key: c for c in current}
            for dish in proposal.snapshot["dishes"]:
                candidate = valid.get(dish["key"])
                if candidate is None or candidate.dish.ingredients != dish["ingredients"]:
                    problem(409, "偏好或菜谱已经变化，请重新生成符合当前要求的方案")
            proposal.status = "accepted"
            proposal.accepted_at = meal_now()
            self.event(proposal.id, "accepted")
        elif action == "complete":
            if proposal.status != "accepted":
                problem(409, "请先选定这一餐，再记录吃过")
            if context.meal_date > meal_now().date():
                problem(422, "未来的一餐还不能记为吃过")
            result = await self.consume(user_id, proposal) if deduct and proposal.snapshot["mode"] == "cook" else {
                "deducted": False, "consumed": [], "missing": [], "unquantified": [],
                "note": "仅记录吃过，没有扣减库存",
            }
            proposal.snapshot = {**proposal.snapshot, "inventory_result": result}
            proposal.status = "eaten"
            proposal.eaten_at = meal_now()
            self.event(proposal.id, "eaten")
        elif action == "undo":
            if proposal.status != "eaten":
                problem(409, "这餐尚未记为吃过")
            await self.restore(user_id, proposal.id)
            proposal.status = "accepted"
            proposal.eaten_at = None
            proposal.snapshot = {**proposal.snapshot, "inventory_result": None}
            self.event(proposal.id, "undone")
        else:
            problem(404, "未知操作")
        session.revision += 1
        await self.db.flush()
        return await self.view(context, session)

    async def consume(self, user_id: int, proposal: MealProposal) -> dict:
        result = {"deducted": False, "consumed": [], "missing": [], "unquantified": [], "note": ""}
        required = []
        for dish in proposal.snapshot["dishes"]:
            lines = dish.get("requirements", [])
            if not lines or not dish.get("base_servings"):
                result["unquantified"].append(dish["name"])
            required.extend(lines)
        stock = list((await self.db.execute(
            select(FridgeInventory).where(FridgeInventory.user_id == user_id, FridgeInventory.quantity > 0)
            .order_by(FridgeInventory.expiry_date.is_(None), FridgeInventory.expiry_date, FridgeInventory.id)
            .with_for_update().execution_options(populate_existing=True)
        )).scalars().all())
        ingredient_names = dict((await self.db.execute(select(Ingredient.id, Ingredient.name))).all())
        for line in required:
            quantity = line.get("quantity")
            if quantity is None or quantity <= 0:
                result["unquantified"].append(line["name"])
                continue
            remaining = quantity
            for batch in stock:
                if batch.quantity <= 0 or (batch.expiry_date and batch.expiry_date < meal_now().date()):
                    continue
                if line["ingredient_id"] is not None:
                    if batch.ingredient_id != line["ingredient_id"]:
                        continue
                elif ingredient_names.get(batch.ingredient_id) != line["name"]:
                    continue
                need = convert_quantity(remaining, line["unit"], batch.unit)
                if need is None:
                    continue
                take = min(batch.quantity, need)
                if take <= 1e-6:
                    continue
                receipt = MealStockMovement(
                    proposal_id=proposal.id, inventory_id=batch.id, ingredient_id=batch.ingredient_id,
                    quantity=take, unit=batch.unit,
                    batch={"purchase_date": batch.purchase_date.isoformat() if batch.purchase_date else None,
                           "expiry_date": batch.expiry_date.isoformat() if batch.expiry_date else None,
                           "source": batch.source},
                )
                self.db.add(receipt)
                batch.quantity = round(batch.quantity - take, 6)
                remaining -= convert_quantity(take, batch.unit, line["unit"]) or 0
                result["consumed"].append({"name": line["name"], "quantity": round(take, 3), "unit": batch.unit})
                if remaining <= 1e-6:
                    break
            if remaining > 1e-6:
                result["missing"].append({"name": line["name"], "quantity": round(remaining, 3), "unit": line["unit"]})
        # Keep zero-quantity rows: receipts retain their exact batch identity for undo.
        result["deducted"] = bool(result["consumed"])
        result["unquantified"] = list(dict.fromkeys(result["unquantified"]))
        result["note"] = "已按可靠用量扣减库存" if result["deducted"] else "没有可精确扣减的库存"
        await self.db.flush()
        return result

    async def restore(self, user_id: int, proposal_id: str) -> None:
        movements = (await self.db.execute(select(MealStockMovement).where(
            MealStockMovement.proposal_id == proposal_id,
        ))).scalars().all()
        for receipt in movements:
            batch = (await self.db.execute(select(FridgeInventory).where(
                FridgeInventory.id == receipt.inventory_id, FridgeInventory.user_id == user_id,
            ).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none() \
                if receipt.inventory_id else None
            if batch:
                batch.quantity = round(batch.quantity + receipt.quantity, 6)
            else:
                self.db.add(FridgeInventory(
                    user_id=user_id, ingredient_id=receipt.ingredient_id, quantity=receipt.quantity,
                    unit=receipt.unit,
                    purchase_date=date.fromisoformat(receipt.batch["purchase_date"])
                    if receipt.batch.get("purchase_date") else None,
                    expiry_date=date.fromisoformat(receipt.batch["expiry_date"])
                    if receipt.batch.get("expiry_date") else None,
                    source=receipt.batch.get("source") or "meal_undo",
                ))
            await self.db.delete(receipt)
        await self.db.flush()

    async def history(self, user_id: int, limit: int = 50) -> list[dict]:
        rows = (await self.db.execute(
            select(MealProposal, MealSession.meal_date, MealSession.meal_slot)
            .join(MealSession, MealSession.id == MealProposal.session_id)
            .where(MealProposal.user_id == user_id)
            .order_by(MealProposal.created_at.desc(), MealProposal.id.desc()).limit(limit)
        )).all()
        return [{
            **self.proposal_view(proposal), "meal_date": day.isoformat(), "meal_slot": slot,
        } for proposal, day, slot in rows]
