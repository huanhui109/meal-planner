"""V3.0 商品价格采集脚手架 (audit T4.1)

每个平台一个 Scraper 子类:
- name: 平台标识 (string, 用于日志 + 数据库 source_platform)
- search(ingredient): 返回该食材的候选商品列表 (Product 字典)
- fetch_price(sku_id): 重新拉价格 (用于定时调价)

注册表 ScraperRegistry 在启动期扫描子类, 调度器按 registry 顺序遍历所有 scraper.

注意:
- 默认所有 platform 的 Scraper 实现都是 stub (返回 []): 真实采集留 V3.x 各平台单独 PR
- config.app.scraper.enabled = false 默认关闭, 调度器不会调用
- 第一次接入新平台时在 ScraperRegistry.register() 后面加一行即可
"""
from __future__ import annotations

import abc
import logging
from dataclasses import dataclass, field
from typing import List

logger = logging.getLogger(__name__)


@dataclass
class ScraperProduct:
    """scraper 输出的标准商品结构, 与 Product 模型字段一一对应 (除 id)"""

    sku_id: str
    name: str
    category: str | None = None
    price: float = 0.0
    unit: str | None = None
    in_stock: bool = True


class Scraper(abc.ABC):
    """平台抽象基类"""

    #: 平台标识: xiaoxiang / meituan_waimai / jd_daojia / samclub / 等等
    name: str = ""

    @abc.abstractmethod
    async def search(self, ingredient: str) -> List[ScraperProduct]:
        """搜索某食材的候选商品"""

    @abc.abstractmethod
    async def fetch_price(self, sku_id: str) -> ScraperProduct | None:
        """取单个商品的最新价格"""


class ScraperRegistry:
    """扫描注册: 各平台 scraper 在此声明存在"""

    _items: List[Scraper] = []

    @classmethod
    def register(cls, scraper: Scraper) -> None:
        if not scraper.name:
            raise ValueError("Scraper 必须声明非空 name")
        cls._items.append(scraper)

    @classmethod
    def all(cls) -> List[Scraper]:
        return list(cls._items)

    @classmethod
    def reset(cls) -> None:
        """测试用: 清掉注册项"""
        cls._items = []


@dataclass
class StubScraper(Scraper):
    """占位实现 - 真实采集留 V3.x 各平台单独 PR"""

    name: str = ""
    reason: str = field(default="stub")

    async def search(self, ingredient: str) -> List[ScraperProduct]:
        logger.debug("[stub scraper %s] 搜索 %s 被跳过: %s", self.name, ingredient, self.reason)
        return []

    async def fetch_price(self, sku_id: str) -> ScraperProduct | None:
        return None


# Stub 注册: 把每个待接入平台先声明一遍, 调度器能看到名字但不会真实采集
ScraperRegistry.register(StubScraper(name="xiaoxiang", reason="待 V3.0.1 接入"))
ScraperRegistry.register(StubScraper(name="meituan_waimai", reason="待 V3.0.2 接入"))


async def run_daily_scrape() -> dict:
    """调度器入口: 跑所有已注册 scraper, 仅返回统计

    V3.0 阶段 Stub 实现下永远返回 0/0/0.
    """
    summary = {"platforms": [], "products": 0, "prices": 0, "errors": 0}
    for scraper in ScraperRegistry.all():
        try:
            platform_count = 0
            # 真实场景下从 ingredient 表拉待搜列表
            # Stub 实现下直接跳过
            summary["platforms"].append({
                "name": scraper.name,
                "products_found": 0,
            })
        except Exception:  # noqa: BLE001 - 调度器不能因为单平台崩
            logger.exception("[scraper %s] 抓取出错", scraper.name)
            summary["errors"] += 1
    return summary
