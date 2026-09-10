"""F3.4/F6.5 deeplink 生成服务"""
from __future__ import annotations

from typing import List


class DeeplinkService:
    """生成小象超市跳转链接"""

    XIAOXIANG_BASE = "https://h5.waimai.meituan.com"

    @staticmethod
    def generate_search_link(keyword: str) -> str:
        """生成搜索链接"""
        return f"{DeeplinkService.XIAOXIANG_BASE}/search/{keyword}"

    @staticmethod
    def generate_product_link(sku_id: str) -> str:
        """生成商品直达链接"""
        return f"{DeeplinkService.XIAOXIANG_BASE}/product/{sku_id}"

    @staticmethod
    def generate_multi_item_links(items: List[str]) -> List[dict]:
        """生成多食材跳转链接列表"""
        return [
            {"name": item, "link": DeeplinkService.generate_search_link(item)}
            for item in items
        ]
