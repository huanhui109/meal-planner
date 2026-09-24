"""天气服务 - 「饭决」的天气 / 时段感知 (需求 9)

设计原则: **天气只能是加分项, 绝不能成为失败点。**

决定吃什么是主链路, 天气只是让它更贴心。所以这里所有的失败都静默降级:
provider 没开、网络不通、超时、返回格式变了 —— 一律返回 condition=None,
调用方照常只用时段 + 偏好出结果, 用户完全无感。

provider 可插拔是因为国内部署到底用哪家不确定:
- none       默认。完全不请求外部网络
- open-meteo 免密钥, 适合自建/海外
- heweather  和风天气, 需要 KEY, 国内延迟低

用法:
    weather = await WeatherService().get()
    if weather.is_rain: ...
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

# Open-Meteo 的 WMO weather code → 我们的粗粒度条件
# https://open-meteo.com/en/docs  (WMO code table)
_WMO_RAIN = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}
_WMO_SNOW = {71, 73, 75, 77, 85, 86}
_WMO_CLOUDY = {1, 2, 3, 45, 48}


@dataclass(frozen=True)
class WeatherContext:
    """决策用的天气上下文

    condition 为 None 表示"不知道天气", 所有天气规则必须整体跳过,
    而不是当成晴天处理 —— 当成晴天会让雨天用户拿到凉拌菜。
    """

    condition: Optional[str] = None  # sunny | cloudy | rain | snow | hot | cold
    temp_c: Optional[float] = None
    source: str = "none"  # none | cache | open-meteo | heweather
    city: str = ""

    @property
    def is_rain(self) -> bool:
        return self.condition == "rain"

    @property
    def is_snow(self) -> bool:
        return self.condition == "snow"

    @property
    def is_bad(self) -> bool:
        """不想出门的天气"""
        return self.is_rain or self.is_snow

    @property
    def is_hot(self) -> bool:
        return self.condition == "hot"

    @property
    def is_cold(self) -> bool:
        return self.condition == "cold"

    def as_dict(self) -> dict:
        return {
            "condition": self.condition,
            "temp_c": self.temp_c,
            "source": self.source,
            "city": self.city,
        }


EMPTY = WeatherContext()


class WeatherService:
    """带进程内缓存的天气查询

    进程内缓存而不是 Redis: 天气这种低价值数据, 多 worker 各存一份无所谓,
    为它引入 Redis 依赖不划算。缓存的意义只是"别让每个用户每次决策都打一次外网"。
    """

    def __init__(self) -> None:
        self._settings = get_settings().weather
        self._cache_at: float = 0.0
        self._cache: WeatherContext = EMPTY

    async def get(self) -> WeatherContext:
        settings = self._settings
        if not settings.enabled or settings.provider == "none":
            return EMPTY

        now = time.monotonic()
        if self._cache and (now - self._cache_at) < settings.cache_minutes * 60:
            return WeatherContext(
                condition=self._cache.condition,
                temp_c=self._cache.temp_c,
                source="cache",
                city=self._cache.city,
            )

        try:
            fetched = await self._fetch()
        except Exception as exc:  # noqa: BLE001 - 任何异常都只降级, 不冒泡
            logger.warning("天气查询失败, 本次决策按无天气处理: %s", exc)
            return EMPTY

        self._cache = fetched
        self._cache_at = now
        return fetched

    async def _fetch(self) -> WeatherContext:
        provider = self._settings.provider
        if provider == "heweather":
            return await self._fetch_heweather()
        return await self._fetch_open_meteo()

    async def _fetch_open_meteo(self) -> WeatherContext:
        settings = self._settings
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": settings.latitude,
            "longitude": settings.longitude,
            "current": "temperature_2m,weather_code",
            "timezone": "auto",
        }
        async with httpx.AsyncClient(timeout=settings.timeout_seconds) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            payload = resp.json()

        current = payload.get("current") or {}
        temp = current.get("temperature_2m")
        code = current.get("weather_code")
        return WeatherContext(
            condition=self._classify(code, temp),
            temp_c=temp,
            source="open-meteo",
            city=settings.city,
        )

    async def _fetch_heweather(self) -> WeatherContext:
        """和风天气 —— 国内延迟低, 但要 KEY；没 KEY 直接降级, 不报错"""
        settings = self._settings
        if not settings.api_key:
            logger.info("heweather 未配置 api_key, 按无天气处理")
            return EMPTY

        url = "https://devapi.qweather.com/v7/weather/now"
        params = {"location": f"{settings.longitude},{settings.latitude}", "key": settings.api_key}
        async with httpx.AsyncClient(timeout=settings.timeout_seconds) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            payload = resp.json()

        now = (payload.get("now") or {}) if payload.get("code") == "200" else {}
        if not now:
            return EMPTY
        try:
            temp = float(now.get("temp"))
        except (TypeError, ValueError):
            temp = None
        return WeatherContext(
            condition=self._classify_text(now.get("text"), temp),
            temp_c=temp,
            source="heweather",
            city=settings.city,
        )

    def _classify(self, code: Optional[int], temp: Optional[float]) -> Optional[str]:
        """WMO code + 温度 → 粗粒度条件。温度优先于降水, 因为体感更影响吃什么"""
        settings = self._settings
        if temp is not None and temp >= settings.hot_temp_c:
            return "hot"
        if temp is not None and temp <= settings.cold_temp_c:
            return "cold"
        if code is None:
            return None
        if code in _WMO_RAIN:
            return "rain"
        if code in _WMO_SNOW:
            return "snow"
        if code == 0:
            return "sunny"
        if code in _WMO_CLOUDY:
            return "cloudy"
        return None

    @staticmethod
    def _classify_text(text: Optional[str], temp: Optional[float]) -> Optional[str]:
        """和风返回的是中文描述, 只能做关键词匹配"""
        if not text:
            return None
        if "雨" in text:
            return "rain"
        if "雪" in text:
            return "snow"
        if "晴" in text:
            return "sunny"
        if "云" in text or "阴" in text:
            return "cloudy"
        return None
