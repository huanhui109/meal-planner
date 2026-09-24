"""双端同构一致性 (shared/decide.ts 的硬约束)

为什么单独一个文件:
  断网时用户走的是 shared/decide.ts, 联网时走 Python decision_service。
  两端只要有一处权重/文案不同, 症状是"这个 App 有时候不对劲", 但没人能复现 ——
  因为用户自己也不知道刚才断没断网。这类 bug 只能靠断言拦住, 靠人 review 拦不住。

这里守三件事:
  1. 打分权重三处一致 (config.py 默认值 / config/default.yaml / decide.ts 的 SCORE)
  2. 分类词白名单两端一致 (shared 是唯一真源, Python 是副本)
  3. 理由文案两端逐字一致 (fixture 与 frontend/tests/shared.decide.test.ts 镜像)

不在这里做的事: 不跑 TS 运行时。逐字一致的另一半在前端单测里钉着,
Python 侧用同一组 fixture 断言同样的字符串, 两边都过就说明没漂移。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from app.config import DecideSettings
from app.services import fridge_menu_service, generation_service, replacement_service
from app.services.reason_service import _GENERIC_CUISINE_LABELS, ReasonContext, ReasonService

REPO_ROOT = Path(__file__).resolve().parents[2]
TS_SOURCE = (REPO_ROOT / "shared" / "decide.ts").read_text(encoding="utf-8")
PY_SOURCE = (REPO_ROOT / "backend" / "app" / "services" / "decision_service.py").read_text(
    encoding="utf-8"
)
YAML_DECIDE = (
    yaml.safe_load((REPO_ROOT / "config" / "default.yaml").read_text(encoding="utf-8")) or {}
)["decide"]

# TS SCORE 的 key -> (config.py 字段, default.yaml 字段)
WEIGHT_MAP = {
    "cuisine": ("score_cuisine", "score_cuisine"),
    "spice": ("score_spice", "score_spice"),
    "inventory": ("score_inventory", "score_inventory"),
    "weather": ("score_weather", "score_weather"),
    "budget": ("score_budget", "score_budget"),
    "budgetOverTolerance": ("budget_over_tolerance", "budget_over_tolerance"),
    "categoryPenalty": ("category_penalty_step", "category_penalty_step"),
    "sameCuisinePenalty": ("same_cuisine_penalty", "same_cuisine_penalty"),
    "mainIngredientPenalty": ("main_ingredient_penalty", "main_ingredient_penalty"),
    "randomBand": ("random_band", "random_band"),
    "minChoices": ("random_min_choices", "random_min_choices"),
    "noRepeatDays": ("no_repeat_days", "no_repeat_days"),
    "lateNightMaxMinutes": ("late_night_max_minutes", "late_night_max_minutes"),
}


def _ts_score() -> dict[str, float]:
    block = re.search(r"const SCORE = \{(.*?)\n\}", TS_SOURCE, re.S)
    assert block, "shared/decide.ts 里找不到 SCORE, 解析方式要跟着改"
    out: dict[str, float] = {}
    for key, value in re.findall(r"(\w+):\s*([\d.]+)", block.group(1)):
        out[key] = float(value)
    return out


def _ts_labels() -> set[str]:
    block = re.search(r"const GENERIC_CUISINE_LABELS = new Set\(\[(.*?)\]\)", TS_SOURCE, re.S)
    assert block, "shared/decide.ts 里找不到 GENERIC_CUISINE_LABELS"
    return set(re.findall(r"'([^']+)'", block.group(1)))


def _two_sided(name: str) -> tuple[str, str]:
    """取同名常量在两端的值 (字符串原样), 用于比对口径"""
    ts = re.search(rf"const {name} = (.+)", TS_SOURCE)
    py = re.search(rf"^{name} = (.+)$", PY_SOURCE, re.M)
    assert ts, f"shared/decide.ts 里找不到 {name}"
    assert py, f"decision_service.py 里找不到 {name}"
    # TS 的行尾注释要摘掉 ("8, // 水位线" / "2, // 松到这一档…"), 否则 float() 会拿整行
    return (
        ts.group(1).split("//")[0].strip().rstrip(","),
        py.group(1).split("#")[0].strip().rstrip(","),
    )


TS_SCORE = _ts_score()
TS_LABELS = _ts_labels()


@pytest.mark.parametrize("ts_key", sorted(WEIGHT_MAP))
def test_weights_agree_in_all_three_places(ts_key: str):
    """权重三处一致: 改一处忘改另一处, 联网和断网给出的菜就不一样"""
    py_field, yaml_field = WEIGHT_MAP[ts_key]
    expected = TS_SCORE[ts_key]
    assert getattr(DecideSettings(), py_field) == pytest.approx(expected)
    assert YAML_DECIDE[yaml_field] == pytest.approx(expected)


def test_cuisine_weight_is_zero_until_cuisine_column_is_cleaned():
    """cuisine 列现在存的是分类不是菜系, 权重必须保持 0

    这条是前面那条通用断言的"为什么": 0 不是顺手填的, 带上权重就是在假装在打分。
    cuisine 清洗完成(真菜系回填)后, 这里会红 —— 那就是恢复 20 的信号。
    """
    assert TS_SCORE["cuisine"] == 0
    assert DecideSettings().score_cuisine == 0
    assert YAML_DECIDE["score_cuisine"] == 0


def test_service_level_cuisine_constants_are_zero_too():
    """三条旁路的 SCORE_CUISINE 也必须是 0 —— 它们是模块级硬编码, 不受 config 管

    决策链路归零了但旁路还挂着 20.0, 就是本次事故的形状: 用户点「换一个」时权重
    悄悄生效, 而 configuration 侧一片全绿。注释会被跳过, 测试不会 —— 这条钉子是
    唯一能在它们分叉时发出声音的东西。

    cuisine 清洗完成(真菜系由凌晨 LLM 富集任务标注并回填)那天, **这条会红** ——
    那不是断言过期, 是"6 处一起恢复"的信号:
        config.py / config/default.yaml / shared/decide.ts /
        replacement_service.py / generation_service.py / fridge_menu_service.py
    ⚠️ fridge_menu_service 恢复目标是 **5.0 不是 20.0**, 别照着另外两条一起填 20。
    ⚠️ 恢复前必须先解决「幅度 > random_band(5.0)」的约束, 否则「换一换」会塌缩。
    """
    assert replacement_service.SCORE_CUISINE == 0.0
    assert generation_service.SCORE_CUISINE == 0.0
    assert fridge_menu_service.SCORE_CUISINE == 0.0


def test_generic_cuisine_labels_match_ts():
    """分类词白名单: shared 是唯一真源, Python 副本必须逐条对得上"""
    assert set(_GENERIC_CUISINE_LABELS) == TS_LABELS


# V1.2.0 引擎侧的新常量。这几个不在 config/default.yaml 里 (它们是引擎的规则常量,
# 不是可调权重), 所以只能靠"两端同名变量逐字一致"这一条钉子拦漂移。
@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("POOL_MIN", 8),                          # 抽签池水位线 (R-10)
        ("MAX_RELAX_LEVEL", 4),                   # 5 档阶梯的最高档
        ("RELAX_LEVEL_CATEGORY_SPREAD", 2),       # 档位名字: SQL / 埋点阈值引用它们,
        ("RELAX_LEVEL_NO_REPEAT", 4),             # 写数字的地方漂过三次了, 别再抄
        ("INVENTORY_HITS_FULL", 2),               # 库存打分归一化 (R-09); A22 定标值
        ("INVENTORY_SCORE_CAP", 4),               # 库存家族幅度上限 (档位 0/2/4, 留 1 余量)
        ("MEAL_SLOT_MATCH_BONUS", 3),             # meal_slots 软惩罚 (R-11)
        ("MEAL_SLOT_MISMATCH_PENALTY", 0),
        ("BREAKFAST_CATEGORY_BONUS", 3),          # 早餐代理补偿: 主食/面食
        ("BREAKFAST_QUICK_BONUS", 1.5),           # 早餐代理补偿: <=15min (1.5 不是 2, 为留余量)
        ("SOFT_PREFERENCE_CAP", 4),               # 软偏好包统一封顶; 留 1 余量, 不取成 band 本身
    ],
)
def test_engine_constants_agree_on_both_sides(name: str, expected: int):
    ts_value, py_value = _two_sided(name)
    assert float(ts_value) == pytest.approx(expected)
    assert float(py_value) == pytest.approx(expected)


@pytest.mark.parametrize(
    "name",
    ["MEAL_SLOT_MATCH_BONUS", "MEAL_SLOT_MISMATCH_PENALTY"],
)
def test_binary_scores_stay_inside_random_band(name: str):
    """「命中/不命中」型二元打分的幅度必须 <= random_band —— 超了就不叫软惩罚了

    抽签按"距最优分的距离"选人(`_random_band`), 不按绝对分。所以幅度大于 band 时:
      减分侧 ⇒ 被罚菜全被拉出抽签带, 等价于硬过滤 (meal_slots 覆盖率才两成多, 等于
              只用那批有标注的菜)
      加分侧 ⇒ 受加分的菜抬高最优分、把其他人挤出带, 连点几次会是同一类菜
    这条是全部这类常量的通则, 不是 meal_slots 一处的特例: 加新的二元打分时同样适用。
    """
    ts_value, py_value = _two_sided(name)
    band = float(TS_SCORE["randomBand"])
    for side, value in (("shared/decide.ts", ts_value), ("decision_service.py", py_value)):
        assert abs(float(value)) <= band, f"{side} 的 {name}={value} 超过 random_band={band}"


def test_breakfast_compensation_stays_inside_random_band():
    """早餐补偿的两笔**相加**也必须 <= random_band

    单项各自合规还不够: 这两笔会同时命中(主食/面食 + <=15min, 早餐档的典型菜),
    合计 4.5 —— 留的那 0.5 余量就是给它的。BREAKFAST_QUICK_BONUS 写成 2.0 就会穿。

    ⚠️ 这条只管"两笔相加", 不管"再加上库存": 后者由 SOFT_PREFERENCE_CAP 兜。
    """
    ts_cat, py_cat = _two_sided("BREAKFAST_CATEGORY_BONUS")
    ts_quick, py_quick = _two_sided("BREAKFAST_QUICK_BONUS")
    band = float(TS_SCORE["randomBand"])
    for side, cat, quick in (
        ("shared/decide.ts", ts_cat, ts_quick),
        ("decision_service.py", py_cat, py_quick),
    ):
        total = float(cat) + float(quick)
        assert total <= band, f"{side} 的早餐补偿合计 {total} 超过 random_band={band}"


def test_aromatic_exclusion_is_disabled_on_both_sides():
    """葱姜蒜剔除必须**两端都没启用** —— 只启用一端就是最坏的一种漂移

    2026-09-23 判定整件排 V1.3: 三个方案实测把「交给外卖吧」的触发率推了
    +10.7 ~ +14.7pp, 超过"用户可见文案 ±5pp"的判据(见两端各自的注释)。

    现在盯的不是"两张表是否一致", 而是"谁也别偷偷开": 一端开着一端没开,
    联网和断网的文案触发率就不一样 —— 用户什么都没做, 看到的话变了,
    而这在单侧代码里看起来完全正常。要开就两端一起开, 并且先过 ±5pp。
    """
    for side, source in (("shared/decide.ts", TS_SOURCE), ("decision_service.py", PY_SOURCE)):
        assert "AROMATIC_SUBSTRINGS" not in source, (
            f"{side} 里出现了 AROMATIC_SUBSTRINGS —— 葱姜蒜剔除在 V1.3 之前不得启用, "
            f"要启用必须两端同时加回来并先过 ±5pp 判据"
        )


def test_late_night_boundary_agrees_with_config():
    """深夜钟点边界三处一致: config/default.yaml ↔ shared/decide.ts ↔ 服务端推断

    为什么这条要钉: 服务端按 `late_night_from/to` 这两个配置项判定, 而离线端
    (`shared/decide.ts` 的 resolveMealSlot) 只能把钟点写在代码里。配置项一改,
    断网用户和联网用户会被分到不同餐次 —— 症状是"同样的 22:30, 有时候给夜宵
    有时候给晚餐", 没人能复现。

    ⚠️ 目前 shared/decide-context.ts 的 isLateNight() 又抄了一份这两个数字
    (LATE_NIGHT_START_HOUR / LATE_NIGHT_END_HOUR), 它不在本测试的比对范围内 ——
    改边界时那一处要一并改, 否则首页的深夜判定会和决策的错开。
    """
    block = re.search(
        r"export function resolveMealSlot\(.*?\n\}", TS_SOURCE, re.S
    )
    assert block, "shared/decide.ts 里找不到 resolveMealSlot"
    start, end = re.search(r"hour >= (\d+).*?hour < (\d+)", block.group(0), re.S).groups()

    assert int(start) == int(YAML_DECIDE["late_night_from"])
    assert int(end) == int(YAML_DECIDE["late_night_to"])


def test_late_night_whitelist_agrees_on_both_sides():
    """夜宵白名单必须逐字一致: 断网时能不能吃上碗面, 取决于这份名单有没有同步过去"""
    ts_value, py_value = _two_sided("LATE_NIGHT_EXTRA_CATEGORIES")
    assert set(re.findall(r"[('\"]([^'\"]+)[)'\"]", ts_value)) == set(
        re.findall(r"[('\"]([^'\"]+)[)'\"]", py_value)
    )
    # 白名单不能悄悄扩大 —— 放宽成"深夜什么都能吃"就把这条规则的意义改没了
    assert set(re.findall(r"[('\"]([^'\"]+)[)'\"]", py_value)) == {"主食", "面食"}


# 与 frontend/tests/shared.decide.test.ts 的 REASON_FIXTURES 镜像。
# 改任何一侧的文案, 两边都会红 —— 这是"逐字一致"另一半的钉子。
REASON_FIXTURES = [
    (ReasonContext(dish="麻婆豆腐", days_since_spicy=3), "你 3 天没吃辣了"),
    (ReasonContext(dish="麻婆豆腐", days_since_spicy=30), "你 30 天没吃辣了"),
    (ReasonContext(dish="麻婆豆腐", expiring_item="番茄"), "冰箱的番茄快到期了"),
    (ReasonContext(dish="麻婆豆腐", expiring_item="金针菇炒肉末配菜"), "冰箱的金针菇炒快到期了"),
    (ReasonContext(dish="麻婆豆腐", weather="rain"), "外面下雨，在家煮锅暖的"),
    (ReasonContext(dish="麻婆豆腐", weather="snow"), "下雪天，来点热乎的"),
    (ReasonContext(dish="麻婆豆腐", weather="hot"), "天热，吃点清爽的"),
    (ReasonContext(dish="麻婆豆腐", weather="cold"), "天冷，喝口热的"),
    (ReasonContext(dish="紫菜蛋花汤", meal_slot="late_night"), "深夜吃点轻的，负担小"),
    (ReasonContext(dish="阳春面", meal_slot="late_night"), "夜宵别太重，这个刚好"),
    (ReasonContext(dish="麻婆豆腐", days_since_dish=6), "这道菜 6 天没上桌了"),
    (ReasonContext(dish="三杯鸡", cuisine="粤式", cuisine_rotated=True), "换换口味，试试粤式"),
    (ReasonContext(dish="鱼香肉丝", cuisine="川湘", cuisine_rotated=True), "川湘好久没吃了"),
    (ReasonContext(dish="阳春面", cuisine="江浙", cuisine_rotated=True), "江浙好久没吃了"),
    (ReasonContext(dish="麻婆豆腐", inventory_ratio=0.5), "家里有一半食材，顺手"),
    (ReasonContext(dish="麻婆豆腐", inventory_ratio=0.9), "家里现成就有，别买了"),
    # 一条规则都不命中 -> 空, 不许兜万能句 (与 frontend/tests/shared.decide.test.ts 镜像)
    (ReasonContext(dish="麻婆豆腐"), ""),
    (ReasonContext(dish="皮蛋瘦肉粥", cuisine="早餐", cuisine_rotated=True), ""),
    # 分类词被跳过后落到下一条(库存)规则
    (ReasonContext(dish="阳春面", cuisine="主食", cuisine_rotated=True, inventory_ratio=0.6), "家里有一半食材，顺手"),
    (ReasonContext(dish="麻婆豆腐", relaxed=True), "可选项不多了，就它吧。"),
]


@pytest.mark.parametrize(("ctx", "expected"), REASON_FIXTURES)
def test_reason_matches_ts_verbatim(ctx: ReasonContext, expected: str):
    assert ReasonService().build(ctx) == expected
