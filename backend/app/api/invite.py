"""T3.1 邀请裂变 API

GET  /api/invite/code            — 我的邀请码 (没有就生成)
POST /api/invite/redeem          — 兑换别人的邀请码

奖励机制 (V1): 双方各 +3 次 AI 生成额度
真实发放需要 quota 表, 当前只在 activity_log 记一条 (kind='invite_reward')
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.activity_log import ActivityLog
from app.models.invite import Invite, generate_code
from app.models.user import User
from app.schemas.common import SuccessResponse
from app.schemas.invite import InviteCodeOut, InviteRedeemIn, InviteRedeemOut

router = APIRouter(prefix="/invite", tags=["邀请"])

REWARD_PER_INVITE = 3
MAX_REDEEM_PER_USER = 1  # 一个用户只能被邀请一次


@router.get("/code", response_model=SuccessResponse)
async def get_my_invite_code(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """我的邀请码 (首次调用自动生成一个 6 位短码)"""
    result = await db.execute(
        select(Invite).where(Invite.inviter_id == user.id).order_by(Invite.id.asc()).limit(1)
    )
    record = result.scalar_one_or_none()
    if not record:
        # 生成短码, 冲突重试 5 次
        code = None
        for _ in range(5):
            candidate = generate_code()
            exists = await db.execute(select(Invite).where(Invite.invite_code == candidate))
            if not exists.scalar_one_or_none():
                code = candidate
                break
        if not code:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="邀请码生成失败, 请重试"
            )
        record = Invite(inviter_id=user.id, invite_code=code)
        db.add(record)
        await db.commit()
        await db.refresh(record)

    # 统计已邀请人数
    count = await db.execute(
        select(func.count(Invite.id)).where(
            Invite.inviter_id == user.id, Invite.invitee_id.isnot(None)
        )
    )
    invite_count = count.scalar_one() or 0

    return SuccessResponse(
        code=0,
        message="success",
        data=InviteCodeOut(
            code=record.invite_code,
            share_path=f"/pages/today/index?invite_code={record.invite_code}",
            invite_count=invite_count,
            reward_granted=invite_count * REWARD_PER_INVITE,
        ).model_dump(),
    )


@router.post("/redeem", response_model=SuccessResponse)
async def redeem_invite_code(
    payload: InviteRedeemIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """兑换邀请码

    约束:
    - 不能兑换自己的码
    - 每个用户只能被邀请一次
    - 码不存在 / 已被别人用过 → 404/409
    """
    code = payload.code.strip().lower()

    # 1) 已被邀请过?
    already = await db.execute(
        select(Invite).where(Invite.invitee_id == user.id)
    )
    if already.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="你已经用过邀请码了"
        )

    # 2) 找码
    result = await db.execute(select(Invite).where(Invite.invite_code == code))
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="邀请码不存在")
    if record.inviter_id == user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="不能用自己的邀请码"
        )
    if record.invitee_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="这个邀请码已经被用过了"
        )

    record.invitee_id = user.id
    record.redeemed_at = datetime.utcnow()
    record.rewarded = True

    # 3) 记奖励流水 (真实额度表上线后改成 UPDATE quota)
    db.add(
        ActivityLog(
            user_id=record.inviter_id,
            channel="miniapp",
            kind="invite_reward",
            status="sent",
            title=f"邀请 {user.nickname or '好友'} 成功, +{REWARD_PER_INVITE} 次 AI 额度",
            detail=f"invite_code={code}",
        )
    )
    db.add(
        ActivityLog(
            user_id=user.id,
            channel="miniapp",
            kind="invite_reward",
            status="sent",
            title=f"接受邀请, +{REWARD_PER_INVITE} 次 AI 额度",
            detail=f"invite_code={code}",
        )
    )
    await db.commit()

    return SuccessResponse(
        code=0,
        message="兑换成功",
        data=InviteRedeemOut(
            ok=True,
            message=f"你和邀请人都到账 {REWARD_PER_INVITE} 次 AI 生成额度",
            reward=REWARD_PER_INVITE,
        ).model_dump(),
    )
