"""API 路由注册 - 由 main 调用, 避免 app <-> router 循环导入"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI

from app.api.auth import router as auth_router
from app.api.automation import router as automation_router
from app.api.build import router as build_router
from app.api.decide import router as decide_router
from app.api.events import router as events_router
from app.api.feedback import router as feedback_router
from app.api.inventory import router as inventory_router
from app.api.invite import router as invite_router
from app.api.menus import router as menus_router
from app.api.preferences import router as preferences_router
from app.api.products import router as products_router
from app.api.recipes import router as recipes_router
from app.api.subscribe import router as subscribe_router
from app.api.today import router as today_router
from app.bot.webhook_routes import router as feishu_router

API_PREFIX = "/api"


def register_routes(app: FastAPI) -> None:
    """挂载全部路由"""
    api_router = APIRouter(prefix=API_PREFIX)
    api_router.include_router(auth_router)
    api_router.include_router(preferences_router)
    # /decide 必须挂在 /menus 之前: menus 里有 /{menu_id} 通配,
    # 虽然前缀不同不会真冲突, 但路由匹配是按注册顺序的, 放前面更不容易出意外。
    api_router.include_router(decide_router)
    api_router.include_router(today_router)
    api_router.include_router(menus_router)
    api_router.include_router(inventory_router)
    api_router.include_router(products_router)
    api_router.include_router(recipes_router)
    api_router.include_router(automation_router)
    api_router.include_router(feedback_router)
    api_router.include_router(build_router)
    api_router.include_router(events_router)
    api_router.include_router(subscribe_router)
    api_router.include_router(invite_router)

    # 飞书事件回调不带 /api 前缀
    app.include_router(feishu_router)
    app.include_router(api_router)
