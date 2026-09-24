#!/usr/bin/env python3
"""用标注语料拟合 System One 的三个阈值

为什么非得有这个脚本:
    Laya 官方明确写了**零样本能力弱**, 中文上的 noul 基线又明显偏高(一句里根本没
    提到的诉求也能拿到 0.7)。阈值只能靠真实语料拟合, 拍脑袋定的 0.75/0.35/0.55
    只是起点。语料一换(换了权重 / 换了措辞 / 换了用户群)就得重跑一次。

    python scripts/system_one_calibrate.py
    python scripts/system_one_calibrate.py --provider rule      # 对比规则兜底
    python scripts/system_one_calibrate.py --write              # 把拟合值写回 default.yaml

它做的事:
    1. 每条语料跑一遍完整的 _questions()(和线上同一组问题, 不另造一套)
    2. 导出每条的原始 noul / choice 置信度, 落盘到 output/ 供人工复核
    3. 网格搜索 noul_accept × noul_reject, 按**非对称代价**选最优
    4. 网格搜索 min_confidence(菜系那道 Choice)

代价为什么不对称:
    漏掉一条真诉求(用户说了清淡没听出来)= 少个约束, 菜还是能出;
    凭空捏造一条假诉求(用户没说吃素却全给素的)= 用户觉得这 App 有毛病。
    后者代价是前者的两倍, 所以 FP 记 -2 / FN 记 -1, 逼搜索往"保守"那侧靠。
    不确定区(None)落在 label=False 上算对(本来就不该加约束), 落在 label=True
    上算漏 —— 这正是三态折叠想要的行为。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# WorkBuddy 沙箱会往 PYTHONPATH 注入 sitecustomize.py 代理 open(), transformers
# 启动时要扫自身目录(数千次 open)会被拖超时。这是执行环境问题, 不是模型问题,
# 所以在真正 import 之前把自己用干净环境重启一次。
if "PYTHONPATH" in os.environ and not os.environ.get("_SO_CALIB_REEXEC"):
    _env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    _env["_SO_CALIB_REEXEC"] = "1"
    os.execve(sys.executable, [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]], _env)

os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.config import SystemOneSettings, get_settings  # noqa: E402
from app.services.intent_service import _questions, _rule_understand  # noqa: E402
from app.services.system_one_service import SystemOneService  # noqa: E402

CORPUS = ROOT / "data" / "utterance_corpus.json"
DUMP = ROOT / "output" / "system-one-calibration.json"
NOUL_KEYS = ("require_light", "avoid_spicy", "rush", "use_fridge", "avoid_meat", "want_soup")

# 三态: True / False / None(不采纳)
Tri = Optional[bool]


def verdict(p: float, accept: float, reject: float) -> Tri:
    if p >= accept:
        return True
    if p <= reject:
        return False
    return None


def score_pair(label: bool, pred: Tri, fp_cost: int = 2) -> int:
    """单条判断的得分。FP 代价翻倍 —— 宁可漏, 不可凭空加约束"""
    if label:
        return 1 if pred is True else -1
    return -fp_cost if pred is True else 1


# ------------------------------------------------------------------ 跑模型

async def collect(settings: SystemOneSettings, items: List[dict]) -> List[dict]:
    engine = SystemOneService(settings)
    questions = _questions()
    rows: List[dict] = []
    print(f"provider   = {settings.provider}"
          + (f" / {settings.laya_checkpoint}" if settings.provider == "laya" else ""))
    print(f"usable     = {engine.usable}")
    print(f"语料条数   = {len(items)}")
    print("-" * 60)

    # 预热一次, 别把 421M 权重的冷启动算进第一条的耗时
    if engine.usable:
        t0 = time.perf_counter()
        await engine.evaluate({"utterance": "随便吃点"}, questions)
        print(f"权重加载   = {time.perf_counter() - t0:.1f} s\n")

    for i, item in enumerate(items, 1):
        text = item["utterance"]
        t0 = time.perf_counter()
        res = await engine.evaluate({"utterance": text}, questions)
        ms = (time.perf_counter() - t0) * 1000
        row = {
            "utterance": text,
            "group": item.get("group", ""),
            "labels": item.get("labels", {}),
            "ms": round(ms, 1),
            "ok": res.ok,
            "noul": {k: round(res.noul(k), 4) for k in NOUL_KEYS},
            "cuisine": res.choice("cuisine"),
            "cuisine_conf": round(res.confidence("cuisine"), 4),
        }
        rows.append(row)
        if i % 20 == 0 or i == len(items):
            print(f"  {i:>3}/{len(items)}  最近 {ms:.0f} ms")

    if engine.last_error:
        print(f"\n⚠ 模型不可用, 以上全是空结果: {engine.last_error[:200]}")
    return rows


# ------------------------------------------------------------------ 拟合

def _rule_flags(text: str) -> Dict[str, bool]:
    """规则兜底在这六个维度上的判断 —— 融合策略的另一半"""
    it = _rule_understand(text)
    return {
        "require_light": it.require_light,
        "avoid_spicy": it.max_spice >= 0,
        "rush": it.max_minutes is not None,
        "use_fridge": it.prefer_fridge,
        "avoid_meat": it.avoid_meat,
        "want_soup": it.category == "汤",
    }


def confusion(rows: List[dict], accept: float, reject: float, mode: str) -> Dict[str, float]:
    """三种策略在同一批语料上的混淆矩阵

    model    只听模型(模型判 None 也算没这回事)
    rule     只听规则
    fusion   线上实际用的: 模型有把握(True/False)听模型, 中间地带听规则
    """
    tp = fp = fn = tn = 0
    for row in rows:
        rf = _rule_flags(row["utterance"])
        for key in NOUL_KEYS:
            want = bool(row["labels"].get(key, False))
            m = verdict(row["noul"][key], accept, reject)
            if mode == "fusion":
                got = True if m is True else (rf[key] if m is None else False)
            elif mode == "model":
                got = m is True
            else:
                got = rf[key]
            if want and got:
                tp += 1
            elif want:
                fn += 1
            elif got:
                fp += 1
            else:
                tn += 1
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": prec, "recall": rec,
            "f1": 2 * prec * rec / (prec + rec) if prec + rec else 0.0}


def fit_noul(rows: List[dict]) -> Dict[str, Any]:
    pairs: List[Tuple[str, bool, float]] = []
    for row in rows:
        for key in NOUL_KEYS:
            # 语料只标 true, 缺项就是 false ——「没说」才是这套语料的大头(反例),
            # 不能跳过, 否则等于只拿正例拟合, 阈值会被压到最低。
            pairs.append((key, bool(row["labels"].get(key, False)), row["noul"][key]))

    # 目标函数用**融合策略的 F1**, 而不是纯模型 —— 线上跑的是融合, 拟合就得拟合线上那条。
    # 次级排序用精确率: F1 相同时选更保守的那个, 少给用户凭空加约束。
    best: Optional[Tuple[float, float, float, float]] = None
    grid = [round(0.50 + 0.01 * i, 2) for i in range(46)]
    for acc in grid:
        for rej in [round(0.05 + 0.05 * i, 2) for i in range(9)]:
            if rej >= acc - 0.05:
                continue
            m = confusion(rows, acc, rej, "fusion")
            key = (round(m["f1"], 6), round(m["precision"], 6))
            if best is None or key > best[0]:
                best = (key, acc, rej, m["f1"])

    (_, _), accept, reject, _f1 = best or (((0, 0), 0.91, 0.20, 0.0))
    total = sum(score_pair(w, verdict(p, accept, reject)) for _, w, p in pairs)
    ceiling = len(pairs)  # 全对时的满分

    # 每个问题单独看真假分布, 间距小的就是措辞还不行的那个
    per_q = []
    for key in NOUL_KEYS:
        trues = sorted(p for k, w, p in pairs if k == key and w)
        falses = sorted(p for k, w, p in pairs if k == key and not w)
        if not trues or not falses:
            continue
        per_q.append({
            "key": key,
            "n_true": len(trues),
            "n_false": len(falses),
            "min_true": round(trues[0], 3),
            "max_false": round(falses[-1], 3),
            "median_true": round(trues[len(trues) // 2], 3),
            "median_false": round(falses[len(falses) // 2], 3),
            "gap": round(trues[0] - falses[-1], 3),
        })

    return {
        "pairs": len(pairs),
        "accept": accept,
        "reject": reject,
        "score": total,
        "ceiling": ceiling,
        "accuracy": round(total / ceiling, 3) if ceiling else 0.0,
        "f1": round(confusion(rows, accept, reject, "fusion")["f1"], 3),
        "current": round(confusion(rows, 0.75, 0.35, "fusion")["f1"], 3),
        "strategies": {
            mode: confusion(rows, accept, reject, mode) for mode in ("rule", "model", "fusion")
        },
        "per_question": sorted(per_q, key=lambda d: d["gap"]),
    }


def fit_confidence(rows: List[dict]) -> Dict[str, Any]:
    """菜系那道 Choice 的 min_confidence

    label 为 null 表示"没说菜系", 此时预测成"无所谓"/None 都对, 预测成具体菜系算错。
    """
    best: Optional[Tuple[float, int]] = None
    curve: List[Tuple[float, int]] = []
    for conf in [round(0.30 + 0.05 * i, 2) for i in range(13)]:
        total = 0
        for row in rows:
            # 缺项 = 没说菜系。和 noul 同理, 这部分反例必须算进来。
            want = row["labels"].get("cuisine")
            got = row["cuisine"] if row["cuisine_conf"] >= conf else None
            if got in (None, "无所谓"):
                got = None
            if want == got:
                total += 1
            elif got is not None:
                total -= 2  # 凭空定菜系, 比漏掉更糟
        curve.append((conf, total))
        if best is None or total > best[1]:
            best = (conf, total)
    conf, total = best or (0.55, 0)
    n = len(rows)
    return {
        "samples": n,
        "min_confidence": conf,
        "score": total,
        "ceiling": n,
        "accuracy": round(total / n, 3) if n else 0.0,
        "curve": curve,
    }


# ------------------------------------------------------------------ 输出

def report(rows: List[dict], noul_fit: dict, conf_fit: dict) -> None:
    print("\n" + "=" * 60)
    print("Noul 阈值拟合")
    print("=" * 60)
    print(f"判断条数   = {noul_fit['pairs']}  (满分 {noul_fit['ceiling']})")
    print(f"拟合结果   = accept {noul_fit['accept']:.2f} / reject {noul_fit['reject']:.2f}"
          f"  代价分 {noul_fit['score']}/{noul_fit['ceiling']}  融合 F1 = {noul_fit['f1']:.3f}")
    print(f"改前的默认值 = accept 0.75 / reject 0.35 → 融合 F1 = {noul_fit['current']:.3f}")
    print(f"提升       = {noul_fit['f1'] - noul_fit['current']:+.3f}"
          + ("（建议写回）" if noul_fit["f1"] > noul_fit["current"] else "（保持现状即可）"))

    print("\n三种策略在同一批语料上 (阈值取上面拟合出的那组):")
    print(f"  {'策略':<22}{'精确率':>8}{'召回':>8}{'F1':>8}{'TP':>6}{'FP':>6}{'FN':>6}")
    for mode, label in (("rule", "纯规则"), ("model", "纯模型"), ("fusion", "模型+规则融合(线上)")):
        m = noul_fit["strategies"][mode]
        print(f"  {label:<22}{m['precision']:>8.0%}{m['recall']:>8.0%}{m['f1']:>8.2f}"
              f"{m['tp']:>6}{m['fp']:>6}{m['fn']:>6}")

    print("\n每个问题的真假间距 (gap 越小说明这道问题的措辞越差, 该改措辞而不是调阈值):")
    print(f"  {'问题':<16}{'真信号最低':>10}{'假信号最高':>10}{'间距':>8}{'真/假':>9}")
    for d in noul_fit["per_question"]:
        flag = "  ⚠" if d["gap"] <= 0 else ""
        print(f"  {d['key']:<16}{d['min_true']:>10.3f}{d['max_false']:>10.3f}"
              f"{d['gap']:>8.3f}{str(d['n_true']) + '/' + str(d['n_false']):>9}{flag}")

    print("\n" + "=" * 60)
    print("菜系 Choice 置信度拟合")
    print("=" * 60)
    print(f"样本数     = {conf_fit['samples']}")
    print(f"拟合结果   = min_confidence {conf_fit['min_confidence']:.2f}"
          f"  得分 {conf_fit['score']}/{conf_fit['ceiling']} ({conf_fit['accuracy']:.1%})")
    print("置信度曲线 (conf → 得分):")
    line = "  "
    for conf, total in conf_fit["curve"]:
        line += f"{conf:.2f}:{total:<4}"
        if len(line) > 100:
            print(line)
            line = "  "
    if line.strip():
        print(line)

    # 最该看的误判: 融合之后(也就是线上真实结果)仍然判错的那些
    acc, rej = noul_fit["accept"], noul_fit["reject"]
    print("\n" + "=" * 60)
    print(f"融合后的残余误判 (accept={acc:.2f} / reject={rej:.2f})")
    print("=" * 60)
    bad = []
    for row in rows:
        rf = _rule_flags(row["utterance"])
        for key in NOUL_KEYS:
            want = bool(row["labels"].get(key, False))
            p = row["noul"][key]
            m = verdict(p, acc, rej)
            got = True if m is True else (rf[key] if m is None else False)
            if want != got:
                kind = "漏判" if want else "误判"
                bad.append((key, kind, row["utterance"], p))
    if not bad:
        print("  无 —— 这套语料在当前阈值下全对")
    for key, kind, text, p in bad[:25]:
        print(f"  [{kind}] {key:<14} p={p:.3f}  「{text}」")
    if len(bad) > 25:
        print(f"  ... 另有 {len(bad) - 25} 条, 见 {DUMP.relative_to(ROOT)}")


def write_back(noul_fit: dict, conf_fit: dict) -> None:
    """把拟合值写回 config/default.yaml —— 只改这三个数, 别的原样保留"""
    path = ROOT / "config" / "default.yaml"
    text = path.read_text(encoding="utf-8")

    def repl(key: str, value: float, src: str) -> str:
        new, n = re.subn(rf"(?m)^(\s*){key}:\s*[\d.]+", lambda m: f"{m.group(1)}{key}: {value:.2f}", src)
        if n == 0:
            print(f"⚠ default.yaml 里没找到 {key}, 跳过")
        return new

    text = repl("min_confidence", conf_fit["min_confidence"], text)
    if re.search(r"(?m)^\s*noul_accept:", text):
        text = repl("noul_accept", noul_fit["accept"], text)
        text = repl("noul_reject", noul_fit["reject"], text)
    else:
        # yaml 里原本没有这两个键(只在 config.py 有默认值), 补在 min_confidence 后面
        anchor = re.search(r"(?m)^\s*min_confidence:.*$", text)
        if not anchor:
            print("⚠ default.yaml 里没找到 min_confidence 锚点, 跳过写回")
            return
        block = (
            f"\n  # 由 scripts/system_one_calibrate.py 在 {noul_fit['pairs']} 条标注语料上拟合得出\n"
            f"  noul_accept: {noul_fit['accept']:.2f}\n"
            f"  noul_reject: {noul_fit['reject']:.2f}"
        )
        text = text[: anchor.end()] + block + text[anchor.end():]

    path.write_text(text, encoding="utf-8")
    print(f"\n已写回 {path.relative_to(ROOT)}: noul_accept={noul_fit['accept']:.2f} "
          f"noul_reject={noul_fit['reject']:.2f} min_confidence={conf_fit['min_confidence']:.2f}")
    print("⚠ config.py 里的同名默认值也要同步改(它是 yaml 缺项时的兜底)")


# ------------------------------------------------------------------ main

async def run(args: argparse.Namespace) -> int:
    corpus = json.loads(Path(args.corpus).read_text(encoding="utf-8"))
    items = corpus["items"]
    if args.limit:
        items = items[: args.limit]

    base = get_settings().system_one
    override = {"enabled": True}
    if args.provider:
        override["provider"] = args.provider
    if args.checkpoint:
        override["laya_checkpoint"] = args.checkpoint
    settings = SystemOneSettings(**{**base.model_dump(), **override})

    t0 = time.perf_counter()
    rows = await collect(settings, items)
    print(f"\n总耗时     = {time.perf_counter() - t0:.1f} s "
          f"(含权重冷启动; 均 {sum(r['ms'] for r in rows) / max(len(rows), 1):.0f} ms/条)")

    ok_rows = [r for r in rows if r["ok"]]
    if not ok_rows:
        print("模型没有任何可用输出, 无法拟合。先跑 scripts/system_one_smoke.py 确认通路。")
        return 1

    noul_fit = fit_noul(ok_rows)
    conf_fit = fit_confidence(ok_rows)
    report(ok_rows, noul_fit, conf_fit)

    DUMP.parent.mkdir(parents=True, exist_ok=True)
    DUMP.write_text(
        json.dumps({"fit": {"noul": noul_fit, "confidence": conf_fit}, "rows": rows},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n原始导出   = {DUMP.relative_to(ROOT)}")

    if args.write:
        write_back(noul_fit, conf_fit)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="System One 阈值拟合")
    parser.add_argument("--corpus", default=str(CORPUS))
    parser.add_argument("--provider", default=None, help="laya | jev | adapter | rule")
    parser.add_argument("--checkpoint", default=None)
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 条(快速试跑)")
    parser.add_argument("--write", action="store_true", help="把拟合值写回 config/default.yaml")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
