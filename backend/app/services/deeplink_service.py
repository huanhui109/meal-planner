"""补单出口 - 把"缺什么"变成"点一下就能去买"

本期不采集任何商品数据 (没有爬虫、没有价格库), 所以这里只做一件诚实的事:
用配置里的 search_template 拼出平台搜索链接 + 告诉前端"是否可以直接打开小程序"。

模板写法: `https://example.com/search/?keyword={keyword}`, {keyword} 会被替换成
URL 编码后的食材名; 模板里没有 {keyword} 时退化成"模板 + 编码后的关键字"。
"""

from __future__ import annotations

from typing import List, Optional, Sequence
from urllib.parse import quote

from app.config import Settings, get_settings

PLATFORM_XIAOXIANG = "xiaoxiang"
PLATFORM_MEITUAN = "meituan_waimai"


class DeeplinkService:
    """生成平台跳转链接, 所有地址都来自配置, 不硬编码在代码里"""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()

    # ---------- 平台能力 ----------

    def platform_config(self, platform: str):
        platforms = self.settings.platforms
        return platforms.meituan_waimai if platform == PLATFORM_MEITUAN else platforms.xiaoxiang

    def enabled(self, platform: str = PLATFORM_XIAOXIANG) -> bool:
        return bool(self.platform_config(platform).enabled)

    def min_order_amount(self, platform: str = PLATFORM_XIAOXIANG) -> float:
        return float(self.platform_config(platform).min_order_amount or 0.0)

    def miniapp_app_id(self, platform: str = PLATFORM_XIAOXIANG) -> str:
        return self.platform_config(platform).miniapp_app_id or ""

    def delivery_note(self, platform: str = PLATFORM_XIAOXIANG) -> str:
        return self.platform_config(platform).delivery_note or ""

    # ---------- 链接 ----------

    def search_link(self, keyword: str, platform: str = PLATFORM_XIAOXIANG) -> str:
        """按模板拼搜索链接; keyword 为空时回落到平台首页"""
        config = self.platform_config(platform)
        text = (keyword or "").strip()
        if not text:
            return config.base_url
        encoded = quote(text, safe="")
        template = config.search_template or ""
        if "{keyword}" in template:
            return template.replace("{keyword}", encoded)
        if template:
            return f"{template}{encoded}"
        return f"{config.base_url}/search/{encoded}"

    def multi_item_links(self, names: Sequence[str], platform: str = PLATFORM_XIAOXIANG) -> List[dict]:
        """每个食材一条搜索链接, 前端可以逐项跳转"""
        seen: List[str] = []
        for name in names:
            text = (name or "").strip()
            if text and text not in seen:
                seen.append(text)
        return [
            {"name": name, "link": self.search_link(name, platform), "platform": platform} for name in seen
        ]

    def shopping_link(self, names: Sequence[str], platform: str = PLATFORM_XIAOXIANG) -> str:
        """一篮子食材的入口链接: 用空格拼成一个搜索词, 用户落地后能直接看到清单"""
        cleaned = [name.strip() for name in names if name and name.strip()]
        return self.search_link(" ".join(cleaned[:6]), platform)
