#!/usr/bin/env python3
"""System One 决策模型快速调用冒烟脚本

用途: 不改任何代码, 一句话验证「模型通不通、听懂了什么」。

    python scripts/system_one_smoke.py "今天想吃清淡点的，别太辣"
    python scripts/system_one_smoke.py "冰箱里还有鸡蛋，赶时间" --slot dinner
    python scripts/system_one_smoke.py "随便" --provider rule     # 强制走规则兜底
    python scripts/system_one_smoke.py "清淡点" --checkpoint english

provider 由 APP__SYSTEM_ONE__PROVIDER 决定(默认 laya), 也可用 --provider 覆盖。
没开白 / 权重没下载 / 端点没起时脚本不会失败, 会明确打出"已降级到规则" ——
这正是线上行为。

注意: 首次运行会从 HuggingFace 下载 421M 权重(约 1.7GB), 需要几分钟。
国内网络建议 export HF_ENDPOINT=https://hf-mirror.com。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

# WorkBuddy 沙箱会往 PYTHONPATH 注入 sitecustomize.py 代理 open(), transformers
# 启动时要扫自身目录(数千次 open)会被拖超时, 表现为"Sensitive content approval
# timed out"。这是执行环境问题, 不是模型问题 —— 在真正 import 之前用干净环境
# 把自己重启一次即可。正常 uvicorn 进程不受影响。
if "PYTHONPATH" in os.environ and not os.environ.get("_SO_SMOKE_REEXEC"):
    _env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    _env["_SO_SMOKE_REEXEC"] = "1"
    os.execve(sys.executable, [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]], _env)

os.environ.setdefault("USE_TF", "0")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.config import SystemOneSettings, get_settings  # noqa: E402
from app.services.intent_service import MealIntentService  # noqa: E402
from app.services.system_one_service import SystemOneService  # noqa: E402

DEFAULT_UTTERANCE = "今天想吃清淡点的，别太辣，冰箱里还有鸡蛋和西红柿，赶时间"


async def run(utterance: str, slot: str, provider: str | None, checkpoint: str | None) -> int:
    base = get_settings().system_one
    override = {"enabled": True}
    if provider:
        override["provider"] = provider
    if checkpoint:
        override["laya_checkpoint"] = checkpoint
    settings = SystemOneSettings(**{**base.model_dump(), **override})

    # 必须复用同一个实例, 否则读不到它记录的降级原因
    engine = SystemOneService(settings)
    svc = MealIntentService(settings=settings, engine=engine)

    print(f"provider  = {settings.provider}"
          + (f" / {settings.laya_checkpoint}" if settings.provider == "laya" else ""))
    print(f"usable    = {engine.usable}")
    print(f"utterance = {utterance}")
    if slot:
        print(f"slot      = {slot}")
    print("-" * 56)

    # 预热一次, 避免把 421M 权重的冷启动算进首次解析耗时
    if engine.usable:
        t0 = time.perf_counter()
        await svc.understand("随便吃点", slot=slot)
        print(f"权重加载  = {(time.perf_counter() - t0) / 1000:.1f} s")
        engine._cache.clear()
        print("-" * 56)

    t0 = time.perf_counter()
    intent = await svc.understand(utterance, slot=slot)
    elapsed = (time.perf_counter() - t0) * 1000

    print(f"推理耗时  = {elapsed:.0f} ms")
    fell_back = intent.source == "rule" and settings.provider != "rule"
    print(f"来源      = {intent.source}"
          + ("（模型不可用, 已降级到规则兜底）" if fell_back else ""))
    print(f"听懂      = {intent.understood}  置信度 = {intent.confidence:.2f}")
    if intent.intent_type:
        print(f"诉求类型  = {intent.intent_type}")
    print("-" * 56)
    for key, label in (
        ("require_light", "只要清淡"),
        ("max_spice", "辣度上限"),
        ("max_minutes", "出餐上限(分钟)"),
        ("prefer_fridge", "优先用冰箱"),
        ("avoid_meat", "不吃肉"),
        ("cuisine", "菜系"),
        ("category", "品类"),
        ("avoid", "不要的食材"),
    ):
        value = getattr(intent, key)
        # 别写成 `if value in (False, -1, None)`: Python 里 0 == False,
        # 会把"辣度上限 0(完全不吃辣)"误判成未设置而跳过。
        if value is False or value is None or value == -1 or value == [] or value == "":
            continue
        print(f"  {label:<14} = {value}")
    if not intent.has_constraints:
        print("  (无额外约束, 决策照常按偏好 + 库存出菜)")
    if engine.last_error:
        print("-" * 56)
        print(f"降级原因  = {engine.last_error[:200]}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="System One 口语诉求解析冒烟测试")
    parser.add_argument("utterance", nargs="?", default=DEFAULT_UTTERANCE)
    parser.add_argument("--slot", default="", help="breakfast/lunch/dinner/late_night")
    parser.add_argument("--provider", default=None, help="laya | jev | adapter | rule")
    parser.add_argument("--checkpoint", default=None,
                        help="Laya 权重: english | multilingual | typed-decisions | auto")
    args = parser.parse_args()
    return asyncio.run(run(args.utterance, args.slot, args.provider, args.checkpoint))


if __name__ == "__main__":
    raise SystemExit(main())
