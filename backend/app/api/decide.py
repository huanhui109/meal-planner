"""饭决决策 API (需求 4 / 5 / 6 / 7 / 8 / 9 / 10)

端点设计上只有一个原则: **一次点击 = 一个答案**。
所以这个模块里没有任何"生成任务 + 轮询"的东西 —— 那是周菜单 (api/menus) 的模式,
决策不能让等, 等就是失败。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import current_layout_version
from app.dependencies import get_current_user, get_db
from app.models.decision import DecisionLog
from app.models.user import User
from app.schemas.common import SuccessResponse
from app.schemas.decide import (
    DecideFeedbackRequest,
    DecideRequest,
    UnderstandRequest,
)
from app.services.decision_service import DecisionService
from app.services.inventory_service import InventoryService
from app.services.intent_service import MealIntentService

router = APIRouter(prefix="/decide", tags=["饭决决策"])


@router.post("", response_model=SuccessResponse)
async def decide(
    payload: DecideRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """决定这一顿吃什么。

    返回带一句话理由的结果卡。近 7 天出过的菜不会再出现。
    可选传 utterance(一句口语诉求), 给了才会去解析并据此收敛候选。
    """
    result = await DecisionService(db).decide(
        user_id=user.id,
        meal_slot=payload.meal_slot,
        exclude=payload.exclude,
        utterance=payload.utterance,
        session_id=payload.session_id,
    )
    # layout_version 在这里注入而不是在决策服务里拼: 灰度是应用级开关, 决策引擎
    # 不该知道"页面有几套布局"。这样两个服务的职责也不互相污染。
    result["layout_version"] = current_layout_version()
    return SuccessResponse(data=result)


@router.post("/understand", response_model=SuccessResponse)
async def understand(
    payload: UnderstandRequest,
    user: User = Depends(get_current_user),
):
    """把一句口语解析成结构化诉求 (System One 决策模型, 默认开源 Laya)

    只解析不决策。用途有两个: 一是前端回显"我听懂了你要清淡、不辣", 让用户能
    立刻纠正; 二是调阈值时看模型到底怎么判的, 比翻日志直观。

    understood=false 表示没听懂或把握不足, 此时前端不该回显任何东西 ——
    没听懂就当没听见, 照常推荐, 比猜错之后再改用户的菜要好。
    """
    intent = await MealIntentService().understand(
        payload.utterance,
        slot=payload.meal_slot or "",
        fridge=payload.fridge,
    )
    return SuccessResponse(data=intent.to_dict())


@router.get("/last", response_model=SuccessResponse)
async def last_decision(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """上一次决策的快照 —— 冷启动用它秒开结果卡, 避免首屏闪一下空卡

    没有历史时返回 data=null, 前端据此展示"按一下饭决"的空态。
    """
    snapshot = await DecisionService(db).last(user.id)
    if snapshot is not None:
        # 快照是决策当时 dump 的, 灰度版本可能在那之后被改过 —— 以**当前**配置为准,
        # 否则用户会被锁在发版那一刻的灰度组里, 服务端再也没法把他切回 v1.1
        snapshot["layout_version"] = current_layout_version()
    return SuccessResponse(data=snapshot)


@router.get("/profile", response_model=SuccessResponse)
async def decide_profile(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """决策所需的压缩档案: 口味 + 忌口 + 时段 + 天气, 一次拿齐"""
    return SuccessResponse(data=await DecisionService(db).profile_view(user.id))


@router.get("/recent", response_model=SuccessResponse)
async def recent_decisions(
    days: int = Query(default=7, ge=1, le=30),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """近 N 天的决策记录"""
    return SuccessResponse(data=await DecisionService(db).recent(user.id, days=days))


@router.post("/{decision_id}/feedback", response_model=SuccessResponse)
async def decide_feedback(
    decision_id: int,
    payload: DecideFeedbackRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """对一次决策表态: 就这个 / 换一个"""
    ok = await DecisionService(db).feedback(user.id, decision_id, payload.liked)
    if not ok:
        return SuccessResponse(code=1, message="决策记录不存在或无权访问", data=None)
    return SuccessResponse(data={"accepted": payload.liked})


@router.post("/{decision_id}/cook", response_model=SuccessResponse)
async def cook_decision(
    decision_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """今日饭决「做完了」: 按结果菜谱扣减冰箱库存

    幂等: 已经 is_cooked 直接返回 already_cooked, 不重复扣。结果菜谱没有库内
    recipe_id (离线/本地兜底菜) 时只置标记、不扣减 (返回 no_recipe)。
    这是今日线唯一的扣库存入口 —— 周菜单走 /menus/{id}/items/{item_id}/cooked。
    """
    log = await db.get(DecisionLog, decision_id)
    if log is None or log.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="决策记录不存在或无权访问"
        )
    if log.is_cooked:
        return SuccessResponse(
            code=0,
            message="这顿已经做完并扣过库存了",
            data={"decision_id": log.id, "already_cooked": True, "consumed": [], "missing": []},
        )

    if not log.recipe_id:
        log.is_cooked = True
        await db.flush()
        return SuccessResponse(
            code=0,
            message="已记下, 但这道是离线菜谱, 没法精确扣库存",
            data={"decision_id": log.id, "already_cooked": False, "no_recipe": True, "consumed": [], "missing": []},
        )

    result = await InventoryService(db).consume_by_recipe(log.recipe_id, user.id, log.id)
    log.is_cooked = True
    await db.flush()
    return SuccessResponse(
        code=0,
        message="已扣减冰箱库存",
        data={
            "decision_id": log.id,
            "already_cooked": False,
            "consumed": result.consumed if result else [],
            "missing": result.missing if result else [],
        },
    )
