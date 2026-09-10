"""定时任务定义 - Sprint 6+ 完善"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def push_daily_menu():
    """每日 08:00 推送当天菜单"""
    logger.info("Job: push_daily_menu - TODO Sprint 6")


async def evening_inventory_check():
    """工作日 17:30 晚间库存检查"""
    logger.info("Job: evening_inventory_check - TODO Sprint 6")


async def generate_weekly_menu():
    """周日 20:00 生成下周菜单"""
    logger.info("Job: generate_weekly_menu - TODO Sprint 6")


async def daily_scrape_products():
    """每日 09:00 采集商品数据"""
    logger.info("Job: daily_scrape_products - TODO Sprint 7")


async def daily_expiry_check():
    """每日 10:00 检查临期食材"""
    logger.info("Job: daily_expiry_check - TODO Sprint 9")
