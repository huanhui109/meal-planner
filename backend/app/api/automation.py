"""自动化 API - 我的页的机器人状态卡 + 飞书配置表"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.automation import FeishuConfigUpdate
from app.schemas.common import SuccessResponse
from app.services.automation_service import AutomationService
from app.services.feishu_config_service import FeishuConfigService

router = APIRouter(prefix="/automation", tags=["自动化"])


@router.get("/status", response_model=SuccessResponse)
async def get_status(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """飞书机器人连接状态 + 定时推送配置 + 最近的活动流水"""
    data = await AutomationService(db).status(user)
    return SuccessResponse(code=0, message="success", data=data)


# ---------- 飞书机器人配置 (每个用户各配各的) ----------


@router.get("/feishu", response_model=SuccessResponse)
async def get_feishu_config(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """读取当前用户生效的飞书配置 (App Secret 只回掩码)"""
    data = await FeishuConfigService(db).view(user)
    return SuccessResponse(code=0, message="success", data=data)


@router.put("/feishu", response_model=SuccessResponse)
async def save_feishu_config(
    payload: FeishuConfigUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """保存当前用户自己的飞书应用凭证

    App Secret 是只写字段: 不传或传空表示沿用已保存的密钥, 不会把它清掉。
    """
    service = FeishuConfigService(db)
    await service.save(user, payload)
    await db.commit()
    data = await service.view(user)
    return SuccessResponse(code=0, message="已保存飞书配置", data=data)


@router.delete("/feishu", response_model=SuccessResponse)
async def delete_feishu_config(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """清除当前用户的飞书配置 (清除后回落到部署默认配置)"""
    service = FeishuConfigService(db)
    await service.clear(user)
    await db.commit()
    return SuccessResponse(code=0, message="已清除个人飞书配置", data=None)


@router.post("/feishu/test", response_model=SuccessResponse)
async def test_feishu_config(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """用当前配置发一条测试消息, 立刻知道参数对不对"""
    ok, message = await FeishuConfigService(db).send_text(
        user, "饭决 · 这是一条测试消息, 收到说明飞书机器人配置成功。"
    )
    await db.commit()
    return SuccessResponse(
        code=0 if ok else 1,
        message=message,
        data={"ok": ok, "message": message},
    )
