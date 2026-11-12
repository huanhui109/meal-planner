"""Unified in-app model request: one direct call -> one validated dish result.

This replaces the two parallel chains that used to exist here:

* the old "web direct" bridge (server sent a prompt into the WorkBuddy
  *conversation* through the official OAuth localassistant API, then polled
  ``/localassistant/message`` for a JSON reply, in two phases);
* the "bidirectional wake" bridge (signed token pairs + wake envelopes +
  assistant-pushed receipts through ``/api/inbound/bridge/receipts``).

Both are now one path, aligned with the connection capability of
``dsh-connect-workbuddy``: the backend reads the locally signed-in WorkBuddy
credential (vault) and calls the model ITSELF, once. The nine inbound endpoints
remain as compatibility aliases and delegate here.

Contract (unchanged externally):
    start() -> view(job) fast, no network
    poll()  -> performs the single model request, parses the JSON reply,
               re-validates conditions/candidates/revision, then calls
               MealService.propose() exactly once inside a nested transaction.

State machine: ``sending`` (task created) -> ``calling`` (model request in
flight, atomic row-locked gate) -> ``completed`` | ``failed`` | ``cancelled``.
``waiting`` is retained for legacy rows. Any abnormal terminal state leaves the
original proposal unchanged, never auto-resends, and never accepts/eats/orders
or deducts inventory. The model may only *suggest* (source='assistant',
status='proposed'); the user decides explicitly.

All model output is treated as DATA, never as an instruction. Server-side hard
rules (complete meal, allergies, spice, meal slot, equipment, candidate-key
whitelist, expected_revision) cannot be overridden by the model.
"""
from __future__ import annotations

import json
from datetime import timedelta
from typing import Optional

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assistant_bridge import AssistantAdjustment
from app.schemas.assistant_bridge import (
    AssistantAdjustmentRequest,
    ContextReply,
    FailureReply,
    ProposalReply,
)
from app.schemas.meal import MealContext, MealContextPatch
from app.services import fandecide_skill_contract as skill
from app.services.meal_service import MealService, meal_now, problem
from app.services.workbuddy_client import WorkBuddyClient
from app.services.workbuddy_model_catalog import ModelCatalogService
from app.services.workbuddy_model_client import (
    ChatEnvelope,
    WorkBuddyModelClient,
    WorkBuddyModelError,
    scrub,
)
from app.services.workbuddy_service import ACTIVE_ADJUSTMENTS

# Fields copied out of a real catalog candidate. Execution details (steps,
# requirements, tags...) are deliberately omitted so a large recipe library
# fits in one model turn and the model cannot treat them as instructions.
# Fields copied out of a real catalog candidate. ``dish_category`` is REQUIRED:
# the server rejects mixed-category meals, so without it the model cannot know
# whether a combination is legal and will hit a 422 it had no way to avoid.
_CANDIDATE_FIELDS = (
    "key", "name", "role", "dish_category", "ingredients",
    "estimated_minutes", "estimated_cost", "spice",
)
_MAX_PER_ROLE = 24



class AssistantAdjustmentService:
    """Unified orchestrator. ``client`` is the legacy OAuth client (optional),
    ``model`` is the direct WorkBuddy model client used by the unified path."""

    def __init__(
        self,
        db: AsyncSession,
        client: Optional[WorkBuddyClient] = None,
        model: Optional[WorkBuddyModelClient] = None,
    ):
        self.db = db
        self.client = client
        self.model = model or WorkBuddyModelClient()
        self.meals = MealService(db)

    # ------------------------------------------------------------------ helpers

    async def owned(self, user_id: int, job_id: str) -> AssistantAdjustment:
        """Serialize per-user state changes with the same user row lock."""
        await self.meals.lock_user(user_id)
        job = (await self.db.execute(
            select(AssistantAdjustment).where(
                AssistantAdjustment.id == job_id, AssistantAdjustment.user_id == user_id,
            ).with_for_update().execution_options(populate_existing=True)
        )).scalar_one_or_none()
        if job is None:
            problem(404, "找不到这次 AI 调整")
        return job

    @staticmethod
    def fail(job: AssistantAdjustment, message: str) -> None:
        job.status = "failed"
        job.error = scrub(str(message))[:500]

    @staticmethod
    def view(job: AssistantAdjustment) -> dict:
        return {
            "id": job.id, "instruction": job.instruction, "context": job.context,
            "status": job.status, "phase": job.phase, "error": job.error,
            "proposal_id": job.proposal_id,
            "source": "model",
            # 可追溯：本次请求是否补全过候选池、补了什么（未触发时为空串）。
            "generation_note": (job.payload or {}).get("generation_note", ""),
            "poll_after_ms": max(1000, min(30000, int((job.next_poll_at - meal_now()).total_seconds() * 1000))),
            "expires_at": job.expires_at.isoformat(),
        }

    @staticmethod
    def _trim_candidates(dishes: list[dict], *, keep_keys: list[str] | None = None) -> list[dict]:
        """Balance roles and drop execution details, max 24 per role.

        ``keep_keys`` are ALWAYS retained even if their role is already full:
        these are the dishes the user explicitly named, and handing the model a
        ``named_matches`` key that is not in the candidate list would make the
        model choose an invalid key.
        """
        pinned = set(keep_keys or [])
        counts: dict[str, int] = {}
        chosen: list[dict] = []
        pinned_dishes: list[dict] = []
        for dish in sorted(dishes, key=lambda d: d.get("estimated_minutes") or 0):
            if dish.get("key") in pinned:
                pinned_dishes.append(dish)
                pinned.discard(dish.get("key"))
        for dish in pinned_dishes:
            chosen.append(dish)
        for dish in sorted(pinned_dishes, key=lambda d: d.get("role", "")):
            counts[dish.get("role", "")] = counts.get(dish.get("role", ""), 0) + 1
        for dish in sorted(dishes, key=lambda d: d.get("estimated_minutes") or 0):
            if dish in chosen:
                continue
            role = dish.get("role", "")
            if counts.get(role, 0) >= _MAX_PER_ROLE:
                continue
            counts[role] = counts.get(role, 0) + 1
            chosen.append(dish)
        return [{field: dish.get(field) for field in _CANDIDATE_FIELDS} for dish in chosen]

    @classmethod
    def prompt(cls, job: AssistantAdjustment, data: dict) -> str:
        """Build the single-turn request through the 饭决 skill contract.

        The contract module owns both the wording and the strict validator, so
        the prompt and the acceptance rule can never drift apart.
        """
        return skill.build_prompt(
            request_id=job.id,
            instruction=job.instruction,
            context=data.get("context", job.context),
            candidates=data.get("candidates", []),
            rules=data.get("rules", {}),
            protected_avoid=data.get("protected_avoid", []),
            current_proposal=data.get("current_proposal"),
            named_matches=data.get("named_matches") or None,
        )

    @staticmethod
    def parse_reply(text: str, job: AssistantAdjustment) -> dict | None:
        """Extract the one matching JSON receipt from a model reply.

        Strips ```json fences, caps at 20000 chars, and requires the exact
        ``request_id`` + ``phase`` match (unrelated conversation is ignored).
        """
        if not isinstance(text, str):
            return None
        stripped = text.strip()
        if len(stripped) > 20000:
            return None
        lines = stripped.splitlines()
        if len(lines) > 2 and lines[0] in ("```json", "```") and lines[-1] == "```":
            stripped = "\n".join(lines[1:-1]).strip()
        try:
            value = json.loads(stripped)
        except ValueError:
            return None
        if not isinstance(value, dict) or value.get("request_id") != job.id:
            return None
        if value.get("phase") not in ("context", "proposal"):
            return None
        return value

    @classmethod
    def reply(cls, messages, job: AssistantAdjustment) -> dict | None:
        """Compatibility shim: accepts a model text string OR the old message list."""
        if isinstance(messages, str):
            return cls.parse_reply(messages, job)
        for message in messages if isinstance(messages, list) else []:
            if not isinstance(message, dict) or message.get("role") != "assistant":
                continue
            if message.get("msg_type") not in (None, "text"):
                continue
            content = message.get("content")
            if isinstance(content, list):
                content = "".join(part for part in content if isinstance(part, str))
            found = cls.parse_reply(content, job)
            if found is not None:
                return found
        return None

    # ------------------------------------------------------------------ start

    async def start(self, user_id: int, request: AssistantAdjustmentRequest) -> dict:
        """Create one bounded task.

        The candidate-gap-fill step MAY call the model (up to the full request
        timeout). It is the only network call allowed here, and it runs AFTER the
        user row lock has been released: holding that lock across a 90-second
        model call makes every other request for the same user fail with
        ``Lock wait timeout exceeded`` (MySQL 1205). Keep this invariant — it was
        violated once and took the whole home page down.
        """
        await self.meals.lock_user(user_id)
        job_id = str(request.request_id)
        existing = (await self.db.execute(select(AssistantAdjustment).where(
            AssistantAdjustment.id == job_id,
        ).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
        if existing:
            if existing.user_id != user_id:
                problem(404, "找不到这次 AI 调整")
            if (
                existing.instruction != request.instruction or existing.context != request.context.model_dump(mode="json")
                or existing.expected_revision != request.expected_revision
            ):
                problem(409, "同一请求编号不能用于不同调整，请重新发送")
            return self.view(existing)
        active = (await self.db.execute(select(AssistantAdjustment).where(
            AssistantAdjustment.user_id == user_id, AssistantAdjustment.status.in_(ACTIVE_ADJUSTMENTS),
        ).with_for_update())).scalars().all()
        for job in active:
            if job.expires_at <= meal_now():
                self.fail(job, "等待模型超时，原方案未改变")
            else:
                problem(409, "已有一项 AI 调整正在处理，请等待或取消后再发送")

        data = await self.meals.assistant_context(
            user_id, MealContextPatch.model_validate(request.context.model_dump(mode="json")),
        )
        if data["revision"] != request.expected_revision:
            problem(409, "这一餐已更新，请刷新后再发送")
        if data["proposal"] and data["proposal"]["status"] == "eaten":
            problem(409, "这一餐已吃过，请先撤销记录再调整")

        # The pool snapshot we already loaded is enough to DECIDE whether gap fill
        # is needed. Do that decision now, then release the user lock BEFORE the
        # network call, and re-read after it finishes.
        matched = skill.resolve_named(request.instruction, data["candidates"])
        named = self._named_miss(request.instruction, data["candidates"])
        need_gap_fill = bool(named) or (
            not matched
            and skill.is_need_only(request.instruction, data["candidates"])
            and not self._has_enough_candidates(data["candidates"], request.context.servings)
        )
        if need_gap_fill:
            # Release the user lock: the model call below must not hold it.
            await self.db.commit()

        # ---- 候选补全（「禁止杜撰」的受控例外）----
        # 两条互补的触发路径，都走同一套「真实菜 + 依据 + 做法」校验：
        #   A) 点名了菜但池里没有（或只有近似） → 以该菜/食材为主料补候选；
        #   B) 只描述需求且候选不足           → 按需求补候选。
        # 数量口径由 fandecide-candidates 技能契约统一：默认 4 道，范围 3-5。
        # 点名了且池里**有**可用近似菜时，优先用现成的，不浪费生成调用。
        generation_note = ""
        # `matched` / `named` were computed above, BEFORE the lock was released.
        if named:
            outcome = await self._generate_candidates(user_id, request, named=named)
            if outcome.ok:
                data = await self.meals.assistant_context(
                    user_id, MealContextPatch.model_validate(request.context.model_dump(mode="json")),
                )
                generation_note = f"你点名的「{named}」池里暂时没有，已补入 {len(outcome.written)} 道真实菜谱：{'、'.join(outcome.written)}"
            elif outcome.reason:
                generation_note = outcome.reason
        elif matched:
            # 近似命中：把命中的候选显式指给模型，避免它在 167 道里挑错或说「没有」。
            data = dict(data)
            data["named_matches"] = [dish.get("key") for dish in matched]
            data["rules"] = [*data.get("rules", []),
                             f"用户点名想吃：{'、'.join(d.get('name', '') for d in matched)}，必须从这些 key 里选"]
        elif skill.is_need_only(request.instruction, data["candidates"]):
            if not self._has_enough_candidates(data["candidates"], request.context.servings):
                outcome = await self._generate_candidates(user_id, request)
                if outcome.ok:
                    data = await self.meals.assistant_context(
                        user_id, MealContextPatch.model_validate(request.context.model_dump(mode="json")),
                    )
                    generation_note = f"按你的需求补入 {len(outcome.written)} 道真实菜谱：{'、'.join(outcome.written)}"
                elif outcome.reason:
                    generation_note = outcome.reason

        if need_gap_fill:
            # Re-acquire the lock: everything below mutates user-scoped state.
            await self.meals.lock_user(user_id)
            # A concurrent adjustment or a cancel may have landed while we were
            # generating; re-check the same preconditions instead of assuming.
            active = (await self.db.execute(select(AssistantAdjustment).where(
                AssistantAdjustment.user_id == user_id,
                AssistantAdjustment.status.in_(ACTIVE_ADJUSTMENTS),
            ).with_for_update())).scalars().all()
            for other in active:
                if other.expires_at <= meal_now():
                    self.fail(other, "等待模型超时，原方案未改变")
                else:
                    problem(409, "已有一项 AI 调整正在处理，请等待或取消后再发送")
            data = await self.meals.assistant_context(
                user_id, MealContextPatch.model_validate(request.context.model_dump(mode="json")),
            )
            if data["revision"] != request.expected_revision:
                problem(409, "这一餐已更新，请刷新后再发送")

        candidates = self._trim_candidates(
            data["candidates"], keep_keys=list(data.get("named_matches") or []),
        )
        if not candidates:
            problem(422, generation_note or "这些条件下没有合适候选，请调整要求；忌口不会被自动放宽")

        now = meal_now()
        job = AssistantAdjustment(
            id=job_id, user_id=user_id, instruction=request.instruction,
            context=request.context.model_dump(mode="json"), expected_revision=request.expected_revision,
            status="sending", phase="proposal",
            payload={
                "context": data["context"],
                "candidate_keys": [dish["key"] for dish in candidates],
                "candidates": candidates,
                "protected_avoid": data["protected_avoid"],
                "inventory": data["inventory"][:100] if request.context.use_fridge else [],
                "rules": data["rules"],
                "current_proposal": data["proposal"]["title"] if data["proposal"] else None,
                # 可追溯：这次请求是否触发了候选补全，以及补了什么；
                # named_matches 记录服务端把用户措辞对上了哪些真实候选。
                "generation_note": generation_note,
                "named_matches": list(data.get("named_matches") or []),
                "named_miss": named,
            },
            created_at=now,
            expires_at=now + timedelta(seconds=self._timeout_seconds()),
            # The first GET poll should immediately trigger the direct call.
            next_poll_at=now,
            poll_failures=0,
        )
        self.db.add(job)
        await self.db.commit()
        return self.view(job)

    @staticmethod
    def _has_enough_candidates(candidates: list[dict], servings: int) -> bool:
        """Whether the pool can already compose a meal without any gap fill."""
        roles = {dish.get("role") for dish in candidates}
        if servings > 1:
            return bool({dish.get("role") for dish in candidates} & {"complete", "main"}) and (
                "side" in roles or {"staple", "side"} <= roles
            )
        return bool(roles & {"complete", "main"})

    @staticmethod
    def _named_miss(instruction: str, candidates: list[dict]) -> str:
        """The dish name the user asked for that the pool cannot serve ('' if none).

        Uses the same conservative resolution as the prompt: a name only counts as
        a "miss" when nothing in the pool matches it even loosely.
        """
        wants = skill.named_wants(instruction, candidates)
        if not wants:
            return ""
        if skill.resolve_named(instruction, candidates):
            return ""
        return wants[0][:50]

    async def _generate_candidates(self, user_id: int, request, named: str = "") -> object:
        """Ask the AI for real dishes; the SERVER decides what is written.

        A failure here must never break the request: this is an *enhancement*, so
        the job still proceeds with whatever the pool already has. Its DB writes
        are wrapped in a savepoint so a partial failure cannot leak a dish.
        """
        from app.services.dish_generation_service import (
            DEFAULT_GENERATED,
            DEFAULT_TIMEOUT_SECONDS,
            DishGenerationService,
            GenerateOutcome,
        )

        workbuddy = getattr(getattr(self.model, "settings", None), "workbuddy", None)
        timeout = float(getattr(workbuddy, "candidate_timeout_seconds", DEFAULT_TIMEOUT_SECONDS))
        try:
            async with self.db.begin_nested():
                service = DishGenerationService(
                    self.db, self.model, model=await self.selected_model(user_id),
                    timeout_seconds=timeout,
                )
                return await service.generate(
                    request.instruction,
                    context=request.context.model_dump(mode="json"),
                    named=named,
                    count=DEFAULT_GENERATED,
                )
        except Exception:  # noqa: BLE001 - never let gap fill break the main flow
            return GenerateOutcome(
                wanted=request.instruction[:120],
                reason="本次候选补全没有完成，先用现有候选安排；原方案未改变",
            )

    async def selected_model(self, user_id: int) -> str:
        """The user's explicit model choice, or '' to let the client auto-pick."""
        try:
            selection = await ModelCatalogService(self.db, self.model).selected(user_id)
        except Exception:  # noqa: BLE001 - a preference read must never block a meal
            return ""
        return selection.get("model", "")

    def _timeout_seconds(self) -> int:
        # Keep the legacy adjustment timeout as the outer bound, but never let a
        # single model call outlive it (the client has its own, shorter, bound).
        settings = self.model.settings.workbuddy
        return max(int(settings.adjustment_timeout_seconds), int(settings.model_timeout_seconds) + 30)

    # ------------------------------------------------------------------ poll

    async def poll(self, user_id: int, job_id: str) -> dict:
        """The unified callback: one direct model call -> one validated result.

        Concurrency: ``sending -> calling`` happens under the user row lock and
        is committed BEFORE the (long) network call. Any concurrent poll then
        sees ``calling`` and returns the current view without a second request.
        """
        job = await self.owned(user_id, job_id)
        if job.status not in ACTIVE_ADJUSTMENTS:
            return self.view(job)
        if job.expires_at <= meal_now():
            self.fail(job, "等待模型超时，原方案未改变。可在修改要求后重新发送")
            await self.db.commit()
            return self.view(job)
        if job.status == "calling":
            # Another request owns the in-flight model call; just report progress.
            return self.view(job)
        if job.status == "waiting":
            # Legacy row created by the pre-unification bridge: converge to a
            # clean terminal state instead of silently resending anything.
            self.fail(job, "旧的等待任务不会自动续发；原方案未改变，请重新发送")
            await self.db.commit()
            return self.view(job)
        if job.next_poll_at > meal_now():
            return self.view(job)

        # Atomically claim this task as the single in-flight model request.
        job.status = "calling"
        job.next_poll_at = meal_now() + timedelta(seconds=self.model.settings.workbuddy.poll_seconds)
        job.error = None
        prompt = self.prompt(job, dict(job.payload or {}))
        # The user's explicit model choice (if any) wins; otherwise the client
        # picks a free catalog model. Read BEFORE committing so the row lock is
        # not held across the network call.
        chosen_model = await self.selected_model(user_id)
        await self.db.commit()  # release the user lock before the network call

        try:
            envelope = await self.model.chat(prompt, model=chosen_model)
        except WorkBuddyModelError as exc:
            envelope = ChatEnvelope.failure(503, "session_dead", str(exc))

        # Re-acquire the lock: a cancel/disconnect during the call must win.
        job = await self.owned(user_id, job_id)
        if job.status != "calling":
            return self.view(job)
        if job.expires_at <= meal_now():
            self.fail(job, "等待模型超时，原方案未改变")
            await self.db.commit()
            return self.view(job)

        if not envelope.ok:
            self.fail(job, f"{envelope.message}。本次不会自动重发；原方案未改变")
            await self.db.commit()
            return self.view(job)

        # Every reply MUST satisfy the 饭决 skill contract. A reply that fails
        # here is a failure, never a saved proposal: that is what confines a
        # general model to this product's vocabulary.
        try:
            reply = skill.validate_reply(envelope.text or "", request_id=job.id)
        except skill.SkillContractError as exc:
            self.fail(job, f"{exc}。本次不会自动重发；原方案未改变")
            await self.db.commit()
            return self.view(job)

        try:
            return await self.commit(user_id, job, reply)
        except ValidationError:
            self.fail(job, "模型回执格式不正确，未替换原方案。可修改要求后重试")
            await self.db.commit()
            return self.view(job)
        except HTTPException as exc:
            self.fail(job, f"{exc.detail}。原方案未改变")
            await self.db.commit()
            return self.view(job)
        except ValueError as exc:
            self.fail(job, str(exc))
            await self.db.commit()
            return self.view(job)

    # ------------------------------------------------------------------ commit

    async def commit(self, user_id: int, job: AssistantAdjustment, reply: dict) -> dict:
        """Single write entry. Validates then calls MealService.propose() once."""
        if job.status == "completed":
            return self.view(job)  # idempotent on repeated polls
        if "error" in reply:
            failure = FailureReply.model_validate(reply)
            # Never show the user internal schema words (candidates/role/servings…).
            # The skill contract asks the model for plain Chinese, but a model can
            # still leak our vocabulary; this is the server-side guarantee.
            friendly = skill.humanize_error(
                failure.error, (job.payload or {}).get("candidates") or [],
            )
            self.fail(job, f"{friendly}（原方案未改变）")
            await self.db.commit()
            return self.view(job)

        phase = reply.get("phase")
        data = dict(job.payload or {})

        # A returned condition patch is applied SERVER-SIDE: candidates are
        # recomputed under it, so the model can never widen a hard restriction.
        if "context" in reply:
            await self.apply_context_patch(job, reply["context"], data)

        keys = reply.get("candidate_keys")
        if not isinstance(keys, list) or not keys:
            # Legacy ContextReply (conditions only): compose a valid meal
            # deterministically from the server-recomputed candidates so the
            # app still receives a usable dish result.
            if phase == "context":
                keys = self.compose_from_candidates(data.get("candidates") or [])
            else:
                raise ValueError("模型未给出候选组合，原方案未改变")

        # Build a clean payload: the optional `context` patch has already been
        # consumed above and ProposalReply forbids extra fields.
        reason = (reply.get("reason") or "").strip()
        proposal = ProposalReply.model_validate({
            "request_id": job.id,
            "phase": "proposal",
            "candidate_keys": keys,
            # Never echo the user's raw instruction as the reason: the saved
            # note must stay inside 饭决's own vocabulary.
            "reason": reason or "按当前条件从真实候选里搭配这一餐",
        })
        allowed = set(data.get("candidate_keys") or [])
        if not set(proposal.candidate_keys) <= allowed:
            raise ValueError("模型选择了未提供的候选，可能因新增忌口或条件变化已失效；原方案未改变")

        patch = MealContextPatch.model_validate(data.get("context") or {})
        try:
            async with self.db.begin_nested():
                result = await self.meals.propose(
                    user_id, patch, job.expected_revision, proposal.candidate_keys, proposal.reason,
                )
                job.proposal_id = result["proposal"]["id"]
                job.status = "completed"
                job.error = None
                await self.db.flush()
        except HTTPException as exc:
            job.status = "failed"
            job.error = scrub(str(exc.detail))[:500]
            await self.db.commit()
            return self.view(job)
        await self.db.commit()
        return self.view(job)

    async def apply_context_patch(self, job: AssistantAdjustment, changes: dict, data: dict) -> None:
        """Re-validate a condition patch and recompute real candidates."""
        if not isinstance(changes, dict):
            raise ValueError("模型返回了不合法的用餐条件，原方案未改变")
        if any(value is None and key != "budget" for key, value in changes.items()):
            raise ValueError("模型返回了不完整的用餐条件，原方案未改变")
        try:
            target = MealContext.model_validate({**job.context, **changes})
        except ValidationError:
            raise ValueError("模型返回了不合法的用餐条件，原方案未改变") from None
        if (
            target.meal_date.isoformat() != job.context["meal_date"]
            or target.meal_slot != job.context["meal_slot"]
        ):
            raise ValueError("请先在网页切换日期或餐次，再发送调整要求；原方案未改变")
        old_avoid = set(job.context.get("avoid") or [])
        if (
            old_avoid - set(target.avoid)
            or (job.context.get("vegetarian") and not target.vegetarian)
            or (job.context.get("light") and not target.light)
        ):
            raise ValueError("已保存的忌口不会被自动放宽，原方案未改变")

        fresh = await self.meals.assistant_context(
            job.user_id, MealContextPatch.model_validate(target.model_dump(mode="json")),
        )
        if fresh["revision"] != job.expected_revision:
            raise ValueError("这一餐已在另一处更新，已保留最新方案，请重新发送调整")
        candidates = self._trim_candidates(fresh["candidates"])
        if not candidates:
            raise ValueError("这些条件下没有合适候选，忌口不会被自动放宽")
        data["context"] = fresh["context"]
        data["candidate_keys"] = [dish["key"] for dish in candidates]
        data["candidates"] = candidates
        data["protected_avoid"] = fresh["protected_avoid"]
        job.payload = data

    @staticmethod
    def compose_from_candidates(candidates: list[dict]) -> list[str]:
        """Deterministic valid combination from SERVER-recomputed candidates."""
        by_role: dict[str, list[dict]] = {}
        for dish in candidates:
            by_role.setdefault(dish.get("role", ""), []).append(dish)
        if by_role.get("complete"):
            return [by_role["complete"][0]["key"]]
        keys = [
            by_role["main"][0]["key"] if by_role.get("main") else None,
            by_role["side"][0]["key"] if by_role.get("side") else None,
            by_role["staple"][0]["key"] if by_role.get("staple") else None,
        ]
        picked = [key for key in keys if key]
        if not picked:
            raise ValueError("这些条件下没有能组成完整一餐的候选，原方案未改变")
        return picked

    # ------------------------------------------------------------------ compat

    async def propose_for_compat(
        self,
        user_id: int,
        patch: MealContextPatch,
        expected_revision: int,
        candidate_keys: list[str],
        reason: str,
    ) -> dict:
        """The single canonical write entry, shared with the inbound-bridge alias.

        The nine ``/api/inbound/bridge/*`` endpoints remain a compatibility
        island and still own their own ``InboundTask`` row, but they MUST NOT
        call ``MealService.propose()`` themselves: they delegate here so the
        whole application has exactly one place that writes a dish proposal.
        Returns ``MealService.propose()``'s view (with ``proposal.id``).
        """
        async with self.db.begin_nested():
            return await self.meals.propose(user_id, patch, expected_revision, candidate_keys, reason)

    async def dispatch(self, user_id: int, job_id: str, prompt: str, *, check_online: bool = False) -> dict:
        """Deprecated compat shim. The unified path sends inside poll(), not here."""
        return self.view(await self.owned(user_id, job_id))

    async def choose(self, user_id: int, job: AssistantAdjustment, reply: ContextReply) -> dict:
        """Deprecated compat shim: keep the legacy context-phase entry working."""
        return await self.commit(user_id, job, reply.model_dump(mode="json"))

    async def current(self, user_id: int, context: MealContextPatch) -> dict | None:
        await self.meals.lock_user(user_id)
        resolved, _ = await self.meals.resolve(user_id, context)
        jobs = (await self.db.execute(select(AssistantAdjustment).where(
            AssistantAdjustment.user_id == user_id, AssistantAdjustment.status.in_(ACTIVE_ADJUSTMENTS),
        ).order_by(AssistantAdjustment.created_at.desc()).with_for_update())).scalars().all()
        for job in jobs:
            if (
                job.context["meal_date"] == resolved.meal_date.isoformat()
                and job.context["meal_slot"] == resolved.meal_slot
            ):
                if job.expires_at <= meal_now():
                    self.fail(job, "等待模型超时，原方案未改变")
                return self.view(job)
        return None

    async def cancel(self, user_id: int, job_id: str) -> dict:
        job = await self.owned(user_id, job_id)
        if job.status in ACTIVE_ADJUSTMENTS:
            job.status = "cancelled"
            job.error = "已取消等待，本次回复不会保存；模型请求可能仍在进行，但结果不会保存"
        return self.view(job)
