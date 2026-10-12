#!/usr/bin/env python3
"""
抽签带(band)回归门禁 —— 防止「二元打分项」把抽签带切成两半
=========================================================
背景
----
`DecisionService._random_band()` 的定义是:

    band = [c for score, c in scored if score >= best - random_band]

`random_band` 默认 5.0。这意味着**只有落在最高分 5 分以内的候选才会被抽到**。
由此推出一条硬规则:

    任何【二元型】打分项(命中/未命中直接 ±X), 只要 |X| > random_band,
    就会把候选切成「抽得到」和「抽不到」两半 ——
        减分: 把被罚的那一半整类排除(等效于硬过滤)
        加分: 让被奖的那一半垄断抽签带(同样是硬分区)
    两者都是静默失败: 池子没空、candidate_count 正常、放宽阶梯不触发、告警不响。

    连续型打分项(按比率缩放, 如 score_inventory = 25 * ratio)不受此限 ——
    它产生连续分布, 不会切断 band。

⚠️ 静态自检的覆盖盲区
--------------------
静态自检只能扫到【模块级常量】。目前还有一组二元加分**硬编码在 `_score()` 之外**,
不受自检覆盖, 只能靠下面的蒙特卡洛抓:

    intent.bonus():     cuisine 匹配 -> +15.0 (现在是死信号, cuisine 几乎全 NULL;
                        一旦 cuisine 字段修好会立刻塌缩成"只出该菜系")

    ⚠️ prefer_fridge 也曾属于这里(+6.0, 对每道菜都成立的全量加分)。2026-09-23 改
    成放大 inventory 命中数 (PREFER_FRIDGE_MULTIPLIER=1.5): 它不是包成员而是系数,
    放行后仍过 INVENTORY_SCORE_CAP 与 SOFT_PREFERENCE_CAP 两道封顶,
    但它的**档位是浮动的** —— `inventory_tiers()` 必须带上这个系数单独算一遍
    (下面的静态自检里有一条 PREFER_FRIDGE_MULTIPLIER 就是干这个的),
    改这个倍数时要回来补算。

早餐那一组已于 2026-09-23 提取为模块级常量 (BREAKFAST_CATEGORY_BONUS=3.0 /
BREAKFAST_QUICK_BONUS=1.5, 与餐次贴合**取 max 不叠加**, 合计 4.5 < random_band),
并已纳入静态自检 —— 在此之前它是 +12.0 / +8.0 硬编码, 合计 +20, 早餐档 band=14、
主面 100%、品类数恒为 2, 当时只能靠 KNOWN_XFAIL 豁免(现在那条已摘掉)。

实测记录(2026-09-23, random_band=5.0, pool=342, slot=dinner, N=500)
-------------------------------------------------------------------
    BONUS  PENALTY   汤羹%   主面%   band中位   判定
      0       0      5.6%   12.8%     116     基线
      3       0      9.4%   12.2%      60     ✅ 软偏好(推荐值)
      5       0     10.8%   10.6%      60     临界
      6       0     64.8%   23.2%       9     🔴 塌缩
     12     -20     64.8%   23.2%       9     🔴 塌缩(曾经落地的错误值)

塌缩点精确落在 random_band 上: 把 random_band 改成 10.0 重跑, 塌缩点从 6 移到 11。
这是因果, 不是相关性。

本脚本做什么
------------
1. 静态自检: 把所有二元打分项常量的幅度与 random_band 对比, 超限即报警
2. 离线蒙特卡洛: 对每个餐次跑 N 次「打分 -> 取 band -> 抽一道」, 统计 band 大小与
   品类分布, 断言 band 没塌、品类没被单一类别垄断
3. 退出码非 0 表示门禁失败, 可直接接 CI

⚠️ band 下限的分母是**各餐次自己的池子**, 不是全库 (2026-09-23 裁定)
--------------------------------------------------------------------
    下限(slot) = max(12, ceil(0.05 × 该餐次实际候选数))
    实测: breakfast/lunch/dinner 池 342 → 18;  late_night 池 45 → 12
夜宵按设计只能从「轻食 / 主食 / 面食 ∩ <=20min」里挑, 池子本来就是 45 道。
以前拿全库 342 当分母, 夜宵 band=14 被判 < 18 —— 红的是分母, 不是夜宵塌了。
(改的是判据让它更准, 不是给夜宵开豁免让规则对自己不适用。)
数字与实现见 DEFAULT_BAND_RATIO 处和 slot_pool_sizes()。

为什么【不能】调用 decide()
--------------------------
decide() 会往 decision_log 写行。跑 500 次就是 500 行合成数据,
会污染 J3/J6'/J7' 的分母 —— 这正是 190 行压测数据那次事故的复现。
本脚本只调用 load_candidates() / _score() / _random_band(), 全程只读。

用法
----
    cd backend && .venv/bin/python scripts/band_regression.py
    .venv/bin/python scripts/band_regression.py --samples 500 --band-min 20 --soup-max 0.30
    .venv/bin/python scripts/band_regression.py --json          # 机器可读输出
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import json
import math
import random
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.services import decision_service as ds  # noqa: E402
from app.services.decision_service import (  # noqa: E402
    DecisionService,
    Profile,
    RecentHistory,
)
from app.services.intent_service import MealIntent  # noqa: E402
from app.services.weather_service import WeatherContext  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

# ---------------------------------------------------------------- 门禁阈值
DEFAULT_SAMPLES = 500
# band 中位数下限, 取「绝对值下限」与「池子占比下限」的较大者。
#   DEFAULT_BAND_MIN  绝对下限。塌缩时是 8~9(个位数), 正常是 25~116
#   DEFAULT_BAND_RATIO 相对下限, 与 PRD 验收⑦ 的判据 band/池 >= 5% 对齐。
#     为什么必须相对: 池子会随菜品录入增长, 绝对阈值(如 12)在 342 池时是 3.5%,
#     在 2000 池时会退化成 0.6% —— 阈值随池子变大而变松, 会漏掉真实塌缩。
#
# ⚠️ ⚠️ 分母是**各餐次自己的池子**, 不是全库 (2026-09-23 team-lead 裁定):
#     下限(slot) = max(DEFAULT_BAND_MIN, ceil(DEFAULT_BAND_RATIO × 该餐次实际候选数))
#
#     为什么不能用全库当分母: 夜宵按设计只能从「轻食 / 主食 / 面食 ∩ <=20min」里挑,
#     池子本来就是 45 道。拿全库 342 当分母去衡量夜宵的选择空间, 是**分母选错了** ——
#     和"早餐打散已经先砍掉一半池子、却还拿全池算比例"是同一类错误。那时夜宵
#     band=14 被打成 < 18 判红, 红的是分母, 不是夜宵塌了。
#     ⇒ 修的是判据(让它更准), 不是给夜宵开豁免(让规则对自己不适用)。
#
# 实测(2026-09-23, 真库 342 道, Profile 默认 cook_cap=60, 空历史/无排除/无忌口):
#     breakfast  池 342  下限 max(12, ceil(17.1)) = 18
#     lunch      池 342  下限 18
#     dinner     池 342  下限 18
#     late_night 池  45  下限 max(12, ceil(2.25)) = 12   ← 分母改口径前是 18, 假红
#   夜宵那 45 是**硬过滤之后**的数: 轻食, 或「主食/面食 ∩ <=20min」(见
#   LATE_NIGHT_EXTRA_CATEGORIES)。白天三个餐次不吃这套过滤, 所以池子就是全库。
#   ⚠️ 池子数会随菜品录入变化, 数字过期了就照 `slot_pool_sizes()` 重拍一行。
DEFAULT_BAND_MIN = 12
DEFAULT_BAND_RATIO = 0.05
DEFAULT_SOUP_MAX = 0.30        # 晚饭档汤羹占比上限(O2)。正常 5.6~23.8%, 塌缩 64.8~77%
DEFAULT_MONOPOLY = 0.90        # 单一品类占比超过此值 -> 判定「垄断」, 仅告警不失败
DEFAULT_SEED = 20260923

SLOTS = ("breakfast", "lunch", "dinner", "late_night")

# 已知豁免(xfail): 门禁不阻断, 但必须显式列出并打印, 不允许静默通过。
# 每条必须写清「为什么豁免」和「什么时候必须摘掉」。
#
# ⚠️ 现在是空的, 这不是"没有已知问题"的意思 —— 早餐那一条是被**修好之后摘掉的**:
#    旧口径 +12.0(主食/面食) / +8.0(<=15min) 硬编码在 _score() 里, 合计 20 分,
#    早餐档 band 只有 14、品类数恒为 2、主面 100%。2026-09-23 提取成
#    BREAKFAST_CATEGORY_BONUS=3.0 / BREAKFAST_QUICK_BONUS=1.5(合计 4.5 < random_band)
#    并与 meal_slots 取 max() 后, 该条豁免的摘掉条件成立, 故删除。
#    再往这里加条目之前先问: 是"暂时修不动", 还是"修好了但懒得删" —— 后者等于
#    给门禁开一个长期红灯豁免, 门禁就没人看了。
KNOWN_XFAIL: dict[str, str] = {}

# 固定历史变体。必须写死 —— 历史里若含 1 次汤羹, category_penalty_step=25 会让
# 24 道汤羹整类出局, P0=P1=0, 跑出来的数不可复现。
HISTORY_VARIANTS = {
    "空历史": lambda: RecentHistory(),
    "荤菜x1": lambda: RecentHistory(category_counts={"荤菜": 1}, last_category="荤菜"),
}


# ---------------------------------------------------------------- 静态自检
def inventory_tiers(rng_band: float, multiplier: float = 1.0,
                    const: str = "INVENTORY_SCORE_CAP") -> dict:
    """R-09 库存加分的**每一档**幅度, 而不是只看最大值

    为什么要把档位摊开算: inventory 不是连续型, 它是 `单位分 × min(hits,FULL)/FULL`
    的离散档。只看最大值会漏掉两件事, 而这两件事管的是**不同的失败形态** ——
      跨度:   最低档到最高档的总跨度。管"这一项会不会把人整档切出带外";
      档间距: 相邻两档之间的跳变。管"相邻档之间会不会也塌" —— 跨度合格但档间距
              过大时, 每一档自己就是一个台阶, 用户只在同一档那几道里横跳。
    两个都要, 缺一个就漏一种塌法。

    multiplier 是 prefer_fridge 那条路径的放大系数(其余调用传 1.0)。它作用在
    **命中数**上、在归一化之前, 所以放大之后用的仍是同一把 unit / full,
    幅度一样能被 min(..., cap) 兜住 —— 但档位被抬高了, 必须按放大后的档位来判。

    判据一律用**严格小于** random_band: 等于 random_band 时, "分差恰好等于 band"
    是闭区间里"刚好留在带内"的临界(见 `_random_band` 的 `score >= best - band`),
    看着没塌, 但只要再叠上任何一项加分就会越线 —— 不留这个余量等于赌运气。
    """
    cap = float(getattr(ds, "INVENTORY_SCORE_CAP", 0.0))
    full = int(getattr(ds, "INVENTORY_HITS_FULL", 1))
    unit = min(float(ds.get_settings().decide.score_inventory), cap)
    tiers = [round(unit * min(h * multiplier, full) / full, 3) for h in range(full + 1)]
    steps = [round(tiers[i + 1] - tiers[i], 3) for i in range(len(tiers) - 1)]
    span = round(tiers[-1] - tiers[0], 3)
    return {
        "const": const,
        "value": multiplier if const == "PREFER_FRIDGE_MULTIPLIER" else cap,
        "abs": span,
        "step": max(steps) if steps else span,
        "tiers": tiers,
        "steps": steps,
        "random_band": rng_band,
        "ok": span < rng_band and (max(steps) if steps else span) < rng_band,
        "desc": (f"库存命中档位 {' / '.join(f'{t:g}' for t in tiers)}"
                 f"(FULL={full}, 单位分={unit:g}"
                 + (f", prefer_fridge×{multiplier:g})" if multiplier != 1.0 else ")")),
    }


def static_check(rng_band: float) -> list[dict]:
    """列出所有【二元/离散档位型】打分常量, 检查幅度是否 < random_band"""
    items = [
        ("MEAL_SLOT_MATCH_BONUS", getattr(ds, "MEAL_SLOT_MATCH_BONUS", None), "meal_slots 命中餐次(加分)"),
        ("MEAL_SLOT_MISMATCH_PENALTY", getattr(ds, "MEAL_SLOT_MISMATCH_PENALTY", None), "meal_slots 不匹配(减分)"),
        ("BREAKFAST_CATEGORY_BONUS", getattr(ds, "BREAKFAST_CATEGORY_BONUS", None), "早餐代理补偿 主食/面食(加分)"),
        ("BREAKFAST_QUICK_BONUS", getattr(ds, "BREAKFAST_QUICK_BONUS", None), "早餐代理补偿 <=15min(加分)"),
    ]
    out = []
    for name, value, desc in items:
        if value is None:
            continue
        amp = abs(float(value))
        out.append({
            "const": name,
            "value": float(value),
            "abs": amp,
            "step": amp,
            "tiers": None,
            "random_band": rng_band,
            "ok": amp < rng_band,
            "desc": desc,
        })
    # 早餐代理补偿的两笔是**相加**的(同一道菜可以既是主食又够快), 单项合规挡不住合力。
    # 只检单项会漏掉"3.0 合规 + 1.5 合规 = 4.5 也合规"以外的组合 —— 比如有人把 QUICK
    # 按"凑整"改成 2.0, 合计 5.0 就贴到 random_band 上了。
    comp = float(getattr(ds, "BREAKFAST_CATEGORY_BONUS", 0.0)) + float(
        getattr(ds, "BREAKFAST_QUICK_BONUS", 0.0)
    )
    out.append({
        "const": "BREAKFAST_COMP_MAX",
        "value": comp,
        "abs": comp,
        "step": comp,
        "tiers": None,
        "random_band": rng_band,
        "ok": comp < rng_band,
        "desc": "早餐代理补偿两笔合计(主食/面食 + <=15min 可同时命中)",
    })

    # SOFT_PREFERENCE_CAP 是**包上限**不是某一项的幅度: 它是"不得超过"的边界,
    # 允许等于 random_band, 但绝不允许超过 —— 超过就等于默认许可一次能切带的加分。
    pkg = float(getattr(ds, "SOFT_PREFERENCE_CAP", 0.0))
    out.append({
        "const": "SOFT_PREFERENCE_CAP",
        "value": pkg,
        "abs": pkg,
        "step": pkg,
        "tiers": None,
        "random_band": rng_band,
        "ok": pkg <= rng_band,
        "desc": "软偏好包上限(允许 == random_band, 不允许 > ); 单项合规不等于包合规",
    })
    out.append(inventory_tiers(rng_band))
    # prefer_fridge 不是一个独立加分项, 而是 inventory 命中数的放大系数
    # (见 decision_service.PREFER_FRIDGE_MULTIPLIER)。它一样要过这一关:
    # 新常量不登记就是新盲区 —— 它同样是个模块级常量, 和 intent.bonus() 里那些
    # 硬编码幅度一样, 扫不到就没人替它看着。
    out.append(
        inventory_tiers(
            rng_band,
            multiplier=float(getattr(ds, "PREFER_FRIDGE_MULTIPLIER", 1.0)),
            const="PREFER_FRIDGE_MULTIPLIER",
        )
    )
    return out


# ---------------------------------------------------------------- 早餐档: 结果判红
#
# 为什么这一档不看幅度、只看结果 (2026-09-23 方案 A 落定后的门禁改造):
#   幅度判据是"算术判据": 它算得出 7.5 > 5.0, 但算不出分布。实测已经证明两次:
#     取 max 的旧写法(单项合规)   → 早餐主面 15.0%, **低于自然占比 20.4%, 反向**
#     叠加不封顶(幅度 7.5 > band) → 44.2%, 补标后最坏情况 40.4% 且 band=22 不塌
#   两者都"该红"或"不该红"按旧判据是反的。所以改成直接盯用户能感知的三个数:
#     natural_band_size / 品类数 / 最大单品类占比
# 幅度判据保留但降为 warn —— 它仍然能提示"有人在改幅度", 只是不再单独决定红绿。
BREAKFAST_MIN_NATURAL_BAND = 18    # 与全局 band 下限同口径: max(12, ceil(5% × 池))
BREAKFAST_MIN_CATEGORIES = 4       # 少于 4 个品类 = 早餐只有那几样, 零多样性

# 垄断线: **相对基线**, 不写死, 且只告警不判红。
#
# 为什么不写死成 40%: 池子自然占比就是荤菜 52.2%。一个"最大单品类 ≤ 40%"的门禁
# 在池子本身 52.2% 是荤菜的前提下, 量到的不是"算法有没有把结果做集中", 而是
# "池子本身集不集中" —— 阈值比被量对象的自然分布还严, 它永远只会报"池子长这样"。
# (这是本项目第三次同型问题: INVENTORY_SCORE_CAP 4.0 vs random_band 5.0、
#  早餐 band 18 vs 全局下限 18、本条。⇒ 阈值必须有对被量对象的语义来源。)
#
# ⇒ 基线由脚本按**当前池子的自然品类占比现算**, 超出的部分才算"我们做集中的"。
# ⚠️ 12pp 这个数是人为给的, 它的语义来源是"抽签带 18~23 道时的抽样噪声幅度" ——
#    能说清楚它由什么导出的, 就改; 说"改成 20pp 它就绿了"不算理由。
BREAKFAST_MONOPOLY_DELTA = 0.12

# 五种场景: 覆盖"默认"与四种最容易把带压窄的真实输入
# ⚠️ 加/删场景后不要回来改这里的"五"字 —— 打印那行是按 len() 现算的, 只有这个注释
#    会过期。改注释比改打印安全, 但两者都别写死。
BREAKFAST_SCENARIOS = {
    "空偏好": lambda: (Profile(), RecentHistory(), set(), None),
    "荤菜x1": lambda: (
        Profile(), RecentHistory(category_counts={"荤菜": 1}, last_category="荤菜"), set(), None,
    ),
    "有库存": lambda: (Profile(), RecentHistory(), {"鸡蛋", "土豆", "青椒"}, None),
    "prefer_fridge": lambda: (
        Profile(), RecentHistory(), {"鸡蛋", "土豆", "青椒"},
        MealIntent(understood=True, prefer_fridge=True),
    ),
    # P5 = 昨天主食×2 + spice=1（数析 2026-09-24 补进，team-lead 采纳）
    #
    # 为什么这一格必须常驻: 本轮抓出问题的两个现象**都只在 P5 出现** ——
    #   · A 方案真带 7 < POOL_MIN(8)（空偏好 / 荤菜x1 两格是 23 / 18，全绿）
    #   · 现状 CAP=4.0 补标后主面倍数反向 0.93x（同样只在 P5）
    # 门禁此前只跑 4 个场景 ⇒ 这两个现象**根本不会出现在输出里**。
    # ⚠️ 注意区分: "连看都看不到" 与 "看了判定不红" 是两回事 —— 补这一格不是为了
    #    让它判红(0.93x 是效果指标, 按 AC-3 排第二、不判红), 而是为了让哪天有人问
    #    "早餐怎么不出主食了"时, 门禁日志里查得到。
    "昨天主食x2+spice1": lambda: (
        Profile(spice_level=1),
        RecentHistory(category_counts={"主食": 2}, last_category="主食"),
        set(),
        None,
    ),
}


def _relabeled_for_breakfast(cands):
    """模拟"meal_slots 补标完成"的最坏情况

    为什么必须跑补标后: 早餐的两笔代理(主食/面食、<=15min)靠的是 category 与
    cook_minutes, 而 meal_slots 覆盖率只有 20.5%。补标之后拿到餐次加分的菜会
    从 46 道涨到 159 道 —— **命中组从 13% 涨到 46%**, 这是"幅度会不会塌"的
    最坏输入。team-lead 前两次否决方案 A 的依据就是"补标后会塌", 实测证伪,
    所以这一列必须常驻门禁, 不能只在改的那天跑一次。
    """
    out = []
    for c in cands:
        needs = (c.category in ("主食", "面食")) or ((c.minutes or 0) <= 15)
        slots = list(c.meal_slots or [])
        if needs and "breakfast" not in slots:
            slots = slots + ["breakfast"]
        if slots != (c.meal_slots or []):
            c = replace(c, meal_slots=slots)
        out.append(c)
    return out


def breakfast_result_gate(svc, cands) -> list[dict]:
    """早餐档: 每种场景 × 补标前后, 直接盯结果（场景集见 BREAKFAST_SCENARIOS）"""
    rows = []
    variants = [("现状标注", cands), ("补标后", _relabeled_for_breakfast(cands))]
    for scenario, mk in BREAKFAST_SCENARIOS.items():
        profile, history, inventory, intent = mk()
        for variant_name, pool in variants:
            scored = []
            for c in pool:
                s = svc._score(
                    c, profile, history, WeatherContext(),
                    inventory=inventory, expiring=[], slot="breakfast",
                    intent=intent, no_category_penalty=False, no_main_penalty=False,
                )
                scored.append((s, c))
            scored.sort(key=lambda t: t[0], reverse=True)
            band = svc._random_band(scored)
            natural = svc._natural_band_size(scored)
            cats: collections.Counter = collections.Counter(c.category for c in band)
            top_cat, top_n = cats.most_common(1)[0] if cats else ("-", 0)
            top_share = top_n / len(band) if band else 1.0

            # 垄断基线: 用**同一批池子**的自然品类占比现算, 不是写死的常数
            pool_cats: collections.Counter = collections.Counter(c.category for c in pool)
            base_cat, base_n = pool_cats.most_common(1)[0]
            baseline = base_n / len(pool)
            line = baseline + BREAKFAST_MONOPOLY_DELTA

            problems = []
            if natural < BREAKFAST_MIN_NATURAL_BAND:
                problems.append(f"natural_band {natural} < {BREAKFAST_MIN_NATURAL_BAND}")
            if len(cats) < BREAKFAST_MIN_CATEGORIES:
                problems.append(f"品类数 {len(cats)} < {BREAKFAST_MIN_CATEGORIES}")

            # 垄断只告警: 池子本身荤菜就占 52.2%, 判红只会永远报"池子长这样"
            warns = []
            if top_share > line:
                warns.append(
                    f"「{top_cat}」在带里占 {top_share * 100:.1f}%, 池子基线 "
                    f"{baseline * 100:.1f}%(+{BREAKFAST_MONOPOLY_DELTA * 100:.0f}pp 线 = "
                    f"{line * 100:.1f}%), 高出 {(top_share - baseline) * 100:+.1f}pp"
                )
            rows.append({
                "scenario": scenario,
                "variant": variant_name,
                "natural_band": natural,
                "categories": len(cats),
                "top": f"{top_cat}({top_share * 100:.1f}%)",
                "baseline": f"{base_cat}({baseline * 100:.1f}%)",
                "delta_pp": round((top_share - baseline) * 100, 1),
                "ok": not problems,
                "problems": problems,
                "warns": warns,
            })
    return rows


# ---------------------------------------------------------------- 各餐次自己的池子
def slot_pool_sizes(svc, cands) -> dict:
    """每个餐次**实际能被选中**的候选数 —— 门禁下限的分母

    为什么必须是这个数而不是 `len(cands)`(全库): 池子是被餐次的硬过滤先切过的。
    夜宵尤其明显 —— 它按设计只从「轻食 / 主食 / 面食 ∩ <=20min」里挑, 真库 342 道
    里只有 45 道进得来。拿 342 去要求夜宵的 band >= 18, 等价于要求"45 道里要有
    18 道落在 5 分以内", 而这是拿全库的尺度量一个本来就该窄的餐次。

    ⚠️ 只改分母, 不改采样: 蒙特卡洛仍然对全库打分(见 run() 的口径说明)。
    即"band 在全库口径下量, 下限按餐次池子定" —— 分母更准了, 分子口径没动。
    两者口径不一致是**已知且有意**的(改采样会让 band 中位数整体变小、需要重新标定),
    要一起改成"只对该餐次池子打分"的话, 得先重拍 8 格基线, 别顺手改。
    """
    base = Profile()
    out = {}
    for slot in SLOTS:
        out[slot] = sum(
            1
            for c in cands
            if svc._passes(
                c, base, RecentHistory(), WeatherContext(), set(), slot, set(),
                cook_cap=base.cook_cap,
            )
        )
    return out


# ---------------------------------------------------------------- 采样
def sample_once(svc, cands, slot, history, rng):
    scored = []
    for c in cands:
        s = svc._score(
            c, Profile(), history, WeatherContext(),
            inventory=set(), expiring=[], slot=slot,
            intent=None, no_category_penalty=False, no_main_penalty=False,
        )
        scored.append((s, c))
    scored.sort(key=lambda t: t[0], reverse=True)
    band = svc._random_band(scored)
    return rng.choice(band).category, len(band)


async def run(samples: int, band_min: int, soup_max: float, seed: int,
              monopoly: float = DEFAULT_MONOPOLY,
              band_ratio: float = DEFAULT_BAND_RATIO) -> dict:
    rng_band = float(get_settings().decide.random_band)
    url = get_settings().database.url
    engine = create_async_engine(url, pool_pre_ping=True)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # 连不上 DB 时**不降级到合成池** —— 合成池与真库结论不同却都显示 PASS,
    # 那比"跑不了"更糟: 判据在最差实现下也能给绿灯。缺数据就明说缺, 别伪造覆盖。
    try:
        async with Session() as db:
            svc = DecisionService(db)
            cands = await svc.load_candidates()
    except Exception as exc:  # noqa: BLE001 - 连不上就是连不上, 类型不重要
        await engine.dispose()
        err = f"{type(exc).__name__}: {exc}".splitlines()[0][:120]
        return {
            "db": False,
            "db_error": err,
            "status": "SKIP",
            "pool": 0,
            "random_band": rng_band,
            "samples": samples,
            "seed": seed,
            "static": static_check(rng_band),
            "slots": {},
            "failures": [],
            "warnings": [],
            "xfails": [],
        }
    await engine.dispose()

    rng_band = float(svc.settings.random_band)
    # 实际生效的 band 下限 = max(绝对下限, ceil(相对下限 × **该餐次自己的池子**))
    # 分母不再用全库 len(cands) —— 见 slot_pool_sizes() 与 DEFAULT_BAND_RATIO 处的说明。
    slot_pools = slot_pool_sizes(svc, cands)
    slot_band_min = {
        slot: max(int(band_min), int(math.ceil(band_ratio * n)))
        for slot, n in slot_pools.items()
    }
    result = {
        "db": True,
        "pool": len(cands),
        "slot_pools": slot_pools,
        "slot_band_min": slot_band_min,
        "random_band": rng_band,
        "random_min_choices": svc.settings.random_min_choices,
        "samples": samples,
        "seed": seed,
        "band_min_abs": band_min,
        "band_ratio": band_ratio,
        "soup_max": soup_max,
        "static": static_check(rng_band),
        "slots": {},
        "failures": [],
        "warnings": [],
        "xfails": [],
    }

    for slot in SLOTS:
        for hname, mk in HISTORY_VARIANTS.items():
            history = mk()
            rng = random.Random(seed)
            counter: collections.Counter = collections.Counter()
            bands: list[int] = []
            for _ in range(samples):
                cat, bsz = sample_once(svc, cands, slot, history, rng)
                counter[cat] += 1
                bands.append(bsz)

            bands_sorted = sorted(bands)
            band_med = bands_sorted[len(bands_sorted) // 2]
            soup_p = counter["汤羹"] / samples
            staple_p = (counter["主食"] + counter["面食"]) / samples
            top_cat, top_n = counter.most_common(1)[0]
            top_p = top_n / samples
            distinct = len(counter)

            entry = {
                "history": hname,
                "band_median": band_med,
                "soup_pct": round(soup_p * 100, 1),
                "staple_pct": round(staple_p * 100, 1),
                "top_category": top_cat,
                "top_pct": round(top_p * 100, 1),
                "distinct_categories": distinct,
                "distribution": dict(counter.most_common()),
            }
            result["slots"].setdefault(slot, []).append(entry)

            key = f"{slot}/{hname}"
            if band_med < slot_band_min[slot]:
                msg = (
                    f"{key}: band 中位数 {band_med} < {slot_band_min[slot]} "
                    f"(= max({band_min}, ceil({band_ratio}×{slot_pools[slot]})), "
                    f"分母是**该餐次自己的池子**, 全库是 {len(cands)}) —— 抽签带塌缩, "
                    f"疑似某个二元打分项幅度超过 random_band({rng_band})"
                )
                reason = KNOWN_XFAIL.get(slot)
                if reason:
                    result["xfails"].append({"key": key, "msg": msg, "reason": reason})
                else:
                    result["failures"].append(msg)
            if slot == "dinner" and soup_p > soup_max:
                result["failures"].append(
                    f"{key}: 晚饭汤羹占比 {soup_p*100:.1f}% > {soup_max*100:.0f}% —— O2 超限, "
                    f"疑似 meal_slots 加分垄断"
                )
            if top_p >= monopoly:
                result["warnings"].append(
                    f"{key}: 「{top_cat}」占 {top_p*100:.1f}% >= {monopoly*100:.0f}% —— "
                    f"单一品类垄断抽签带, 疑似某个二元加分项幅度超过 random_band({rng_band})"
                )
            # 品类数 <=2 是更灵敏的"零多样性"信号: 早餐档就是这样 ——
            # 主面合计 100%, 但拆成 面食58.5%+主食41.5%, 单品类检查抓不到
            if distinct <= 2:
                result["warnings"].append(
                    f"{key}: 只抽到 {distinct} 个品类 —— 零多样性, "
                    f"疑似某个二元加分项(如早餐偏好 +12/+8)幅度超过 random_band({rng_band})"
                )

    # 早餐档结果判红: 幅度判不出分布, 直接盯用户能感知的三个数
    result["breakfast"] = breakfast_result_gate(svc, cands)
    for row in result["breakfast"]:
        if not row["ok"]:
            result["failures"].append(
                f"breakfast/{row['scenario']}/{row['variant']}: "
                + "; ".join(row["problems"])
            )
        # 垄断线是相对基线的 warn, 不进退出码 —— 但它必须打出来, 且带基线一起打
        for w in row["warns"]:
            result["warnings"].append(f"breakfast/{row['scenario']}/{row['variant']}: {w}")
    result["status"] = "FAIL" if result["failures"] else "PASS"
    return result


# ---------------------------------------------------------------- 输出
def print_human(r: dict) -> None:
    if r.get("db", True):
        print(f"候选池(全库) = {r['pool']}   random_band = {r['random_band']}   "
              f"random_min_choices = {r['random_min_choices']}   N = {r['samples']}")
        # 下限按**各餐次自己的池子**算 —— 下一个人看 0.05×N 得知道 N 是哪个 N
        pools = r.get("slot_pools", {})
        mins = r.get("slot_band_min", {})
        line = "  ".join(
            f"{slot} 池{n}→下限{mins.get(slot, '?')}"
            for slot, n in pools.items()
        )
        print(f"各餐次池子 / 下限: {line}")
        print(f"  (下限 = max(绝对 {r['band_min_abs']}, ceil({r['band_ratio']}×该餐次池子)); "
              f"分母不是全库 {r['pool']} —— 夜宵池本来就窄, 拿全库当分母是假红)")

    if not r.get("db", True):
        # 铁律: 无 DB 时绝不打印 [PASS]。蒙特卡洛没跑就是没跑, 静态自检再干净也不算通过。
        print(f"\n[SKIP] 无 DB(连不上 {r.get('db_error', '?')}): 蒙特卡洛未执行, "
              f"下面只有静态自检, **不能**当作门禁通过")
    print("\n[静态自检 · 仅告警] 打分项幅度 < random_band —— 幅度判不出分布, 红绿看结果判据")
    for it in r["static"]:
        flag = "OK " if it["ok"] else "WARN"
        print(f"  [{flag}] {it['const']:<30} = {it['value']:>7.1f}  "
              f"跨度={it['abs']:.1f} 档间距={it['step']:.1f} "
              f"vs random_band={it['random_band']}  # {it['desc']}")

    if not r.get("db", True):
        print("\n[SKIP] 状态 = SKIP —— band 回归未执行(无 DB)。"
              "CI 若配了 DB, 请加 --require-db 把这种情况判成失败")
        return

    # 免责声明必须和"当前是哪些口径"一起打出来 —— 只有先看见口径,
    # "绝对值不可跨口径比较"这句才有人读得懂, 否则又是一句没人看的提示。
    print("\n[口径] band 只能做**固定口径下的相对回归**, 不是绝对健康度指标。")
    print(f"       当前口径: {', '.join(HISTORY_VARIANTS)} + seed={r.get('seed', '?')}; "
          f"换口径(如真实多餐历史)绝对值不可直接比较 —— "
          f"已知: 真实 5 餐历史 dinner band=14 < 下限 18 会假红。"
          f"阈值是在这些口径下标定的, 不是凭空取的。")

    print("\n[蒙特卡洛] band 中位数 / 汤羹% / 主食面食% / 最大品类% / 品类数")
    for slot, entries in r["slots"].items():
        for e in entries:
            print(f"  {slot:<11} {e['history']:<8} band={e['band_median']:>4}  "
                  f"汤羹={e['soup_pct']:>5.1f}%  主面={e['staple_pct']:>5.1f}%  "
                  f"最大={e['top_category']}({e['top_pct']:.1f}%)  品类数={e['distinct_categories']}")

    # 早餐档结果判红 —— 判据是用户能感知的三个数, 不是幅度
    if r.get("breakfast"):
        print(f"\n[早餐档 · 结果判红] natural_band >= {BREAKFAST_MIN_NATURAL_BAND} / "
              # 场景数按 BREAKFAST_SCENARIOS 现算 —— 写死"四种"会在加场景后变成过期标注
              f"品类数 >= {BREAKFAST_MIN_CATEGORIES}   "
              f"({len(BREAKFAST_SCENARIOS)} 种场景 × 补标前后)")
        print(f"  垄断线只告警: 带内最大品类 > 池子基线 +{BREAKFAST_MONOPOLY_DELTA * 100:.0f}pp "
              f"才提示 —— 基线按池子自然占比现算, 不写死")
        for row in r["breakfast"]:
            flag = "OK " if row["ok"] else "FAIL"
            print(f"  [{flag}] {row['scenario']:<14} {row['variant']:<6} "
                  f"natural_band={row['natural_band']:>4}  品类数={row['categories']:>2}  "
                  f"最大={row['top']:<16} 池子基线={row['baseline']:<14} "
                  f"Δ={row['delta_pp']:+.1f}pp"
                  + ("  ← " + "; ".join(row["problems"]) if not row["ok"] else ""))

    if r["warnings"]:
        print(f"\n[WARN] {len(r['warnings'])} 条告警(不阻断):")
        for w in r["warnings"]:
            print(f"  - {w}")

    if r.get("xfails"):
        print(f"\n[XFAIL] {len(r['xfails'])} 项已知豁免(不阻断, 但不得静默通过):")
        for x in r["xfails"]:
            print(f"  - {x['msg']}")
            print(f"      豁免理由: {x['reason']}")

    print()
    if r["failures"]:
        print(f"[FAIL] {len(r['failures'])} 项未通过门禁:")
        for f in r["failures"]:
            print(f"  - {f}")
    else:
        print("[PASS] 全部通过")


def main() -> int:
    ap = argparse.ArgumentParser(description="抽签带(band)回归门禁 —— 只读, 不写库")
    ap.add_argument("--samples", type=int, default=DEFAULT_SAMPLES)
    ap.add_argument("--band-min", type=int, default=DEFAULT_BAND_MIN)
    ap.add_argument("--band-ratio", type=float, default=DEFAULT_BAND_RATIO,
                    help="band 相对下限(占池子比例), 实际下限取绝对值与相对值的较大者")
    ap.add_argument("--soup-max", type=float, default=DEFAULT_SOUP_MAX)
    ap.add_argument("--monopoly", type=float, default=DEFAULT_MONOPOLY,
                    help="单一品类占比告警线(仅告警, 不阻断)")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--json", action="store_true", help="输出 JSON 而非人类可读")
    ap.add_argument("--require-db", action="store_true",
                    help="连不上 DB 时按失败处理(退出码 1)。CI 上配了 DB 就该开这个, "
                         "否则环境问题会被一个 SKIP 悄悄盖过去")
    args = ap.parse_args()

    r = asyncio.run(run(args.samples, args.band_min, args.soup_max, args.seed,
                        args.monopoly, args.band_ratio))

    # 静态自检(幅度判据)的结果并入 **warnings, 不是 failures** —— 2026-09-23 起:
    #   幅度是算术判据, 算得出 7.5 > 5.0, 算不出分布。实测两次证明它是反的:
    #   单项合规的 max() 写法给出反向效果(主面 15.0% < 自然 20.4%),
    #   而幅度超标的叠加写法给出 44.2%、补标后仍不塌。
    #   所以红绿交给 breakfast_result_gate 的**结果判据**, 幅度只保留提示作用。
    # ⚠️ 仍然要在**打印之前**并入: 否则会先打出 [PASS] 再补一行告警, 而 CI/人眼
    #    只看最后一行 —— 门禁屏幕上出现 PASS 就是事故。
    static_fail = [i for i in r["static"] if not i["ok"]]
    if static_fail:
        r["warnings"].extend(
            f"{i['const']} = {i['value']}: 跨度 {i['abs']} / 档间距 {i['step']} "
            f"未严格小于 random_band {i['random_band']} —— 幅度判据已降为 warn, "
            f"红绿看早餐档的结果判据"
            for i in static_fail
        )

    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print_human(r)

    # SKIP 单独占一条路径: 它既不是 PASS 也不是 FAIL。
    # 默认退出 0 但输出里必须带 [SKIP](CI 靠 grep 它), 开了 --require-db 就当失败。
    if not r.get("db", True):
        return 1 if args.require_db else 0
    return 1 if r["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
