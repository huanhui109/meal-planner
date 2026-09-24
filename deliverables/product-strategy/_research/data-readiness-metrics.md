# 饭决 V1.2.0 首页重构 — 数据支撑度评估 + 指标埋点设计

> 作者：数析（Metric）· 数据分析师
> 数据源：本机 MySQL 8.0.46 `meal_planner`（连接串取自项目根 `.env` 的 `APP__DATABASE__URL`），**全程只读 SELECT**，无任何 INSERT/UPDATE/ALTER/DROP
> 采集时间：2026-09-23　|　**口径裁定日期：2026-09-23（team-lead）**

---

## 📏 全文口径声明（2026-09-23 裁定，读任何数字前先看这段）

| 分母 | 值 | 什么时候用 |
|---|---:|---|
| **342** | `is_dish = 1` | **默认分母。** 凡涉及「能不能硬过滤 / 覆盖率多少 / 决策会怎么样」一律用它 |
| 396 | recipe 全表 | **只在写「recipe 全量 / 含非菜品」时用**，不用于任何决策判定 |

**为什么**：`load_candidates()` 用 `dish_only()` 过滤，实际决策池就是 `is_dish=1` 的 342 道；
396 里那 54 道非菜品（调味品/酒水/甜品/半成品）**根本不进决策**，拿它们摊薄分母会让所有覆盖率系统性偏低。

> 📌 **快照基数纪律（2026-09-23 新增）**：所有覆盖率数字**必须带上"当时的 `COUNT(*) WHERE is_dish=1`"一起记**。
> 依据：`is_dish=1` 已实测从 **342 → 343**（2026-09-23 20:30 落了一道 `id=397「纯 AI 菜」`，未经过 `is_dish` 判定即进池）。
> 差 1 道不改变本报告任何结论，但**基线会自己漂移** —— 不记基数，下次对不上还得重查一遍。
>
> 🔄 **2026-09-23 21:30 复核**：那 1 道**已被删除**，基数回到 **342**（`COUNT=396 / MIN(id)=1 / MAX(id)=396` 无缺口，
> 但 `AUTO_INCREMENT=398` ⇒ 397 曾被分配 ⇒ **是被 DELETE，不是 `is_dish` 翻转**；`enrich_source` 随行消失）。
> 详见 §5.2 **(39)**。**本节所有百分比分母均为 342。**

**已核对结论**：两个分母下**没有任何字段跨档**（详见 §1.2b）。所以这次改口径
**不改变任何一个"能否硬过滤"的判定**，只改变数字的写法。

**⚠️ 本文历史段落**（§1.2 / §1.3 等）里有不少按 396 统计的旧数，**保留原值并已就地标注 342 换算**，
不是遗漏。§1.2b 是全文唯一的权威对照版本。

**342 分母下的关键数（本次重算）**：

| 项 | 396 旧值 | **342 新值** | |
|---|---:|---:|---|
| `is_light = 1` | 35（8.8%） | **34（9.9%）** | |
| 「要辣」spice ≥ 1 | 136（34.3%） | **132（38.6%）** | |
| 「很辣」spice ≥ 3 | 39（9.8%） | **37（10.8%）** | |
| 有食材行（R-09 可达） | 373（94.2%） | **321（93.9%）** | 另 21 道无任何食材行 |
| 至少缺一个食材价 | 352（88.9%） | **300（87.7%）** | |
| steps ≥ 40 字 | 371（93.7%） | **318（93.0%）** | |
| 三场景字段全有 | 3 | **3** | 不变 |

---

## 0. 一句话结论

**现有数据撑得住"做不做 / 多久吃上 / 忌口 / 家里有啥"这 4 个维度，撑不住"时间(餐次) / 饿的程度 / 预算 / 几个人 / 厨具条件 / 最近吃过没"这 6 个维度。**

更准确地说：

- 396 道菜里，**只有 3 道菜**同时具备 `meal_slots + tools + season` 三个场景字段（`enrich_source` 100% 是 `rule`，**凌晨 LLM 富集从未跑过**）；
- 决策引擎里**权重第二高的打分项（菜系 20 分）实际命中率 ≈ 0.5%**，因为 `recipe.cuisine` 存的是"荤菜/素菜/主食/早餐"，而用户档案里存的是"川湘/粤菜/江浙"——两套词表完全对不上。**（✅ 权重侧已修复：`score_cuisine` 归零为 0.0，见 §2.4 / §2.2；本条保留作事实记录，不再是待办。数据侧 `cuisine` 列仍未清洗，是 V1.3 待办）**
- ~~夜宵时段 **80% 的决策已经触发放宽**（`relaxed=true`）~~ → **此数字是压测伪影，已撤回**（15 条集中在 77 分钟内，测的是"脚本点了多少次"）。真因见下条。

**所以 V1.2.0 首页如果按"人决定吃啥时会想什么"摆 10 个筛选项，会有 4 个格子点下去筛不出菜。**
建议：**先按"覆盖率阈值法则"把 10 个维度分成「可硬过滤 / 只能加分 / 本版不上」三档，再决定首页摆几个格子。**

### 0.1 定稿摘要（2026-09-23，team-lead 裁决后）

| 议题 | 定稿结论 |
|---|---|
| **ladder** | **5 档 0–4**，不留空位；`tools` / `meal_slots` **都不是档位、也不进过滤链**（覆盖率 18.2% / 21.9%，均 < 30% 门槛）。**0–4 发布即冻结，后续只追加不插入** |
| **J3** | `relaxed_level >= RELAX_LEVEL_CATEGORY_SPREAD`（**= 2**）≤8%，夜宵降档 ≤20%。**按常量名引用，禁止写字面量** |
| **J3b / J3c** | J3b = `>= COOK_CAP`(1) 观测不设目标；J3c = `>= NO_REPEAT`(4) ≤1%，单日 >0 告警 |
| **J6' / J7'** | 替换已作废的「四时段 0 空结果」（**该判据恒真、不可证伪**）：`candidate_count` 按 `meal_slot` 的 P10（夜宵 ≥8）；`<8` 占比 ≤5% |
| **`candidate_count`** | R-07 **必需列**，必须是**放宽之前**的池子大小 |
| **夜宵（R-24）** | 品类白名单口径修正，**16 → 45**（≤15min 34）。**扩池作废**（新菜照样被 `is_light` 筛掉）；`late_night_max_minutes` 维持 20 |
| **R-11（`meal_slots`）** | **软惩罚**，非硬过滤。硬过滤会把夜宵池 **45 打回 28**，删掉的正是白名单救回的 17 道面 |
| **`is_light` 护栏** | 不改字段值。断言：`is_light=1 ∩ 主食/面食 ∩ ≤20min` = **0 且不得增加**（不加时间条件的基线是 3，合法） |

---

## 1. 字段支撑度盘点表（SQL 实跑，非估算）

### 1.1 主查询

```sql
SELECT
  COUNT(*) AS total,
  COUNT(cook_minutes) cook_minutes,
  COUNT(NULLIF(meal_slots,'')) meal_slots,
  COUNT(NULLIF(meat_type,'')) meat_type,
  COUNT(NULLIF(tools,'')) tools,
  COUNT(NULLIF(season,'')) season,
  COUNT(spice_level) spice_level,
  COUNT(is_light) is_light,
  COUNT(NULLIF(tags,'')) tags,
  COUNT(NULLIF(flavor_tags,'')) flavor_tags,
  COUNT(NULLIF(category,'')) category,
  COUNT(NULLIF(main_ingredient,'')) main_ingredient,
  COUNT(calories) calories,
  COUNT(protein_g) protein_g,
  COUNT(carb_g) carb_g,
  COUNT(fat_g) fat_g,
  COUNT(NULLIF(steps,'')) steps,
  COUNT(NULLIF(quick_steps,'')) quick_steps,
  COUNT(NULLIF(cover_text,'')) cover_text,
  COUNT(NULLIF(cuisine,'')) cuisine,
  COUNT(difficulty) difficulty
FROM recipe;
```

**实跑结果：**

```
total | cook_minutes | meal_slots | meat_type | tools | season | spice_level | is_light | tags | flavor_tags | category | main_ingredient | calories | protein_g | carb_g | fat_g | steps | quick_steps | cover_text | cuisine | difficulty
 396  |     396      |     81     |    281    |   72  |   30   |     396     |    396    |  391 |     391     |   391    |       391       |    388    |     24     |   24   |   24  |  396  |     391     |     391     |   372   |    372
```

> ⚠️ 注意：`COUNT(NULLIF(col,''))` 会把 `"[]"`（空 JSON 数组）算成有值。所以第二列另行做了空数组剔除，得到**真实可用数**，见下表。

### 1.2 空数组剔除后的真实可用数

```sql
SELECT 'meal_slots' AS f, COUNT(*) total,
  SUM(meal_slots IS NULL OR meal_slots='' OR meal_slots='[]') n_empty,
  SUM(meal_slots IS NOT NULL AND meal_slots<>'' AND meal_slots<>'[]') n_usable FROM recipe;
-- 同构 SQL 对 tools / season / tags / flavor_tags / quick_steps 各跑一遍
```

```
f            | total | n_empty | n_usable
meal_slots   |  396  |   315   |    81
tools        |  396  |   324   |    72
season       |  396  |   366   |    30
tags         |  396  |    62   |   334
flavor_tags  |  396  |     5   |   391
quick_steps  |  396  |     5   |   391
```

### 1.2b ✅ 覆盖率分母口径：**用 342（`is_dish=1`），不用 396**（2026-09-23 裁定）

**应 requirement-analyst 提问（PRD v1.5 §5.1）确认。** 结论：**正确分母是 342** —— 因为 `load_candidates()` 用 `dish_only()` 过滤，
实际决策池就是 `is_dish=1` 的 342 道，396 里的 54 道非菜品**根本不会进入决策**。

**双分母实测对照（全文唯一权威版本）**：

| 字段 | 有值(全表) | 有值(is_dish=1) | **覆盖率 396** | **覆盖率 342** | 偏移 | 档位（30/70/90） |
|---|---:|---:|---:|---:|---:|---|
| cook_minutes | 396 | 342 | 100.0% | **100.0%** | 0 | ≥90 不变 |
| spice_level | 396 | 342 | 100.0% | **100.0%** | 0 | ≥90 不变 |
| is_light | 396 | 342 | 100.0% | **100.0%** | 0 | ≥90 不变 |
| category | 391 | 337 | 98.7% | **98.5%** | −0.2 | ≥90 不变 |
| main_ingredient | 391 | 337 | 98.7% | **98.5%** | −0.2 | ≥90 不变 |
| flavor_tags | 391 | 337 | 98.7% | **98.5%** | −0.2 | ≥90 不变 |
| tags | 334 | 286 | 84.3% | **83.6%** | −0.7 | 70–90 不变 |
| **meat_type** | 281 | 263 | 71.0% | **76.9%** | **+5.9** | **70–90 不变**（且离 70 线从 1.0pp 拉开到 6.9pp，更安全） |
| **meal_slots** | 81 | 75 | 20.5% | **21.9%** | +1.4 | **<30 不变** |
| **tools** | 72 | 67 | 18.2% | **19.6%** | +1.4 | **<30 不变** |
| season | 30 | 27 | 7.6% | **7.9%** | +0.3 | <30 不变 |

**✅ 结论：没有任何字段跨档。** 最大偏移是 `meat_type` +5.9pp（71.0% → 76.9%），**仍在 70–90 档内**；
`tools` 与 `meal_slots` 虽是 requirement-analyst 担心的"离 30% 线最近的两个"，实际只从 18.2%/20.5% 移到 19.6%/21.9%，**离 30% 线反而更远了**（非菜品在这些稀疏字段上的覆盖率比菜品更低：meal_slots 6/54=11.1%、tools 5/54=9.3%，剔掉它们会抬升覆盖率）。

→ **PRD §5.1 请按 342 口径写，无需重算任何决策。** §3.1 的阈值法则判定（tools/meal_slots 不做硬过滤、meat_type 可做硬过滤+兜底）**全部保持不变**。

### 1.3 支撑度盘点表（核心交付）

> ⚠️ 本表的"非 NULL 数 / 覆盖率"列按 **396（全表）** 统计（跑于 `is_dish` 迁移之前）。
> **决策口径一律用 342** —— 见文首《全文口径声明》与 §1.2b。两列差异 ≤5.9pp，**不影响任何档位判定**。
> 下表逐行已就地补注 342 换算值（标 **[342]**），**引用时请用 [342] 那个数**。

| 字段 | 非 NULL 数 | 覆盖率 | 取值分布（前几名） | 能否直接用于首页筛选 | 缺口怎么办 |
|---|---:|---:|---|---|---|
| **cook_minutes** | 396 | **100%** | 22min(119) / 40min(47) / 12min(55) / 15min(55) / 60min(27) / 10min(21) / 20min(24) / 25min(40)，仅 13 个离散值 | ✅ **能**，但只有 13 档颗粒度（8/10/12/15/18/20/22/25/28/30/40/45/60），"≤15/≤30/≤60"三档可用，不能做"精确到分钟"的滑杆 | 够用。若要更细需 LLM 重估，但**收益低，不建议本版做** |
| **category** | 391 | **98.7%** | 荤菜192 / 素菜74 / 主食44 / 面食28 / 汤羹27 / 凉菜14 / 小吃12 / NULL 5 | ✅ **能**（最干净的一个字段） | 5 道 NULL 用规则兜 `dish_rules.guess_*` 或直接归"其他" |
| **main_ingredient** | 391 | **98.7%** | 232 个不同值；鸡蛋43 / 猪肉13 / 排骨12 / 五花肉9 / 土豆7 / 豆腐7 / 牛肉7 / 面粉7 / 米饭7 | ⚠️ 内部用可以，**对外展示不行** | 词表未归一：`猪肉/五花肉/猪五花肉/带皮五花肉`、`鸡肉/鸡胸肉/鸡腿/鸡腿肉` 各算各的。做"最近吃过没"必须**先建主料归一表**（把 232 → 约 60 个主料族），否则去重形同失效 |
| **flavor_tags** | 391 | **98.7%** | 咸鲜329 / 甜161 / 辣92 / 酸65 / 酱香37 | ✅ **能** | 无缺口 |
| **tags**（场景标签） | 334 | **84.3%** | 下饭251 / 雨天76 / 炖煮41 / 热辣39 / 轻食35 / 清爽29 / 汤羹27 / 夜宵13 / 快手10 / 一锅出7 | ✅ **能**（≥70% 硬过滤线） | 62 道是 `[]`。但"下饭"占 251 说明标签区分度差（63% 的菜都是下饭），**做筛选等于没筛**，建议只做加分不做筛选项 |
| **calories** | 388 | **98.0%** | <200:64 / 200-399:70 / 400-599:77 / 600-799:50 / ≥800:127 / NULL 8 | ⚠️ 覆盖够，**可信度存疑** | 127 道 ≥800 kcal（如中式馅饼 1265、可乐炒饭 913），明显是"整锅/整份"口径而非"一人份"。**用 calories 做"饿的程度"前必须先确认口径**，否则会误判 |
| **steps** | 396 | **100%**（371 道 ≥40 字，25 道偏薄） | — | ✅ 能（结果卡展示） | 无 |
| **quick_steps** | 391 | **98.7%** | 370 道 5 步 / 9 道 3 步 / 12 道 2 步 | ✅ 能 | 12 道只有 2 步，UI 要能容忍 |
| **cover_text** | 391 | **98.7%** | — | ✅ 能（角标） | 无 |
| **spice_level** | 396 | **100%**（但 0 值 260 道）**[342] 0 值 210 道 = 61.4%** | 0:260 / 1:44 / 2:53 / 3:21 / 4:18 | ✅ 能 | "不辣"260 道够用；"要辣"只有 136 道（34.3%）**[342] 132 道 = 38.6%**，"很辣(≥3)"只有 39 道 **[342] 37 道 = 10.8%** |
| **meat_type** | 281 | **71.0%** | red_meat98 / seafood84 / egg_dairy58 / poultry31 / none10 / NULL 115 | ⚠️ **勉强能**（刚好过 70% 线） | 115 道 NULL 中大量是素菜（`none` 只有 10 道，明显漏判）。素菜 74 道 vs meat_type='none' 10 道 → **规则把素菜漏判成 NULL 了**。补 run 一次 `guess_meat_type` 即可 |
| **cuisine** | 372 | 93.9% | 荤菜111 / 素菜61 / 主食59 / 水产28 / 早餐25 / 饮品23 / 甜品19 / 汤与粥18 / 半成品加工9 / 调味品8 / 汤羹4 / 家常菜3 / 川菜2 | ❌ **不能，且是 Bug** | **词表污染**：这列存的是"分类"不是"菜系"。用户档案 `diet_preference.cuisines` 存的是 `["川湘","粤菜","江浙","日料","家常"]`，全库只有 2 道菜能对上。**必须清洗：把 cuisine 归到真实菜系、分类留给 category** |
| **is_light** | 396 列满，但 =1 只有 **35 道** **[342] 34 道 = 9.9%** | **8.8%** **[342] 9.9%** | 汤羹10 / 荤菜8 / 素菜7 / 凉菜7 / 主食3 | ❌ **不能** | 夜宵硬过滤后：35 道 ∩ ≤20min = **16 道**。~~这是夜宵 80% 触发放宽的直接原因~~（该数字已撤回）。**口径修正见 §5.2：夜宵应按 `is_light=1 OR category IN ('主食','面食')`，16 → 45 道** |
| **meal_slots** | 81 | **20.5%** | breakfast48 / lunch48 / dinner33 / late_night6 | ❌ **不能** | 覆盖率 20.5%。且规则 `guess_meal_slots` 只会产出 breakfast / late_night / dinner，**永远不会产出 lunch**（除非从 breakfast 派生）。lunch 48 道全是 breakfast 派生来的 |
| **tools** | 72 | **18.2%** | pot43 / steamer14 / oven11 / air_fryer5 | ❌ **不能** | 覆盖率 18.2%。且 **词表与用户档案对不上**：`recipe.tools` = `pot/steamer/oven/air_fryer`，而 `household.kitchen_equipments` = `灶台/微波炉/空气炸锅/蒸锅/烤箱/电饭煲/压力锅`。**两个枚举完全无法 join** |
| **season** | 30 | **7.6%** | summer15 / winter15 / **spring 0 / autumn 0** | ❌ **不能，绝对不能** | `guess_season` 只写了夏/冬两条规则，春秋一道都没有。春秋两季点"当季"会 **0 结果** |
| **protein_g / carb_g / fat_g** | 24 | **6.1%** | protein 5–52g | ❌ 不能 | 营养三列基本是空的。`/api/today` 的 nutrition 块会算出 0 |
| **estimated_cost** | **字段不存在** | **0%** | — | ❌ 不能 | 只能靠 `recipe_ingredient` × `ingredient.reference_price` 现算。但 **771 个食材里只有 66 个有价（8.6%）**，396 道菜里 **352 道**至少缺一个食材价 **[342] 300/342 = 87.7%** → 估出来的成本不可信 |
| **difficulty** | 372 | 93.9% | — | ⚠️ 只进 payload 展示，**不参与打分** | 无 |
| **enrich_status** | 396 | 100% | done52 / partial337 / pending7 | — | 见下方"富集从未真正跑过" |
| **enrich_source** | 389 | 98.2% | **rule 389 / NULL 7**，**llm 0** | — | **凌晨 LLM 富集从未执行过**。所有场景字段都是规则猜的 |
| **steps_source** | 0 | 0% | 全 NULL | — | 未启用 |

### 1.4 补充：维度取值的 SQL 明细

```sql
-- 餐次分布
SELECT j.v, COUNT(*) c FROM recipe r,
  JSON_TABLE(r.meal_slots,'$[*]' COLUMNS(v VARCHAR(30) PATH '$')) j
WHERE r.meal_slots IS NOT NULL AND r.meal_slots<>'[]' GROUP BY j.v;
-- breakfast 48 | lunch 48 | dinner 33 | late_night 6

-- 厨具分布
-- pot 43 | steamer 14 | oven 11 | air_fryer 5

-- 时令分布
-- summer 15 | winter 15 | (spring 0, autumn 0)

-- 场景标签分布
-- 下饭 251 | 雨天 76 | 炖煮 41 | 热辣 39 | 轻食 35 | 清爽 29 | 汤羹 27 | 夜宵 13 | 快手 10 | 一锅出 7
```

### 1.5 派生能力盘点（"家里有啥" / "预算" 靠 join 得来）

```sql
SELECT COUNT(*) recipe_ingredient_rows, COUNT(DISTINCT recipe_id) recipes_covered FROM recipe_ingredient;
-- 2776 行，覆盖 373 道菜

SELECT AVG(n) FROM (SELECT recipe_id, COUNT(*) n FROM recipe_ingredient GROUP BY recipe_id) t;
-- 7.44 个食材/道

SELECT COUNT(*) FROM recipe r
WHERE NOT EXISTS (SELECT 1 FROM recipe_ingredient ri WHERE ri.recipe_id=r.id);
-- 23 道菜一个食材都没有

SELECT COUNT(*) ingredients, COUNT(reference_price) has_price FROM ingredient;
-- 771 个食材，只有 66 个有参考单价
```

| 派生能力 | 支撑情况 | 结论 |
|---|---|---|
| **家里有啥**（recipe_ingredient） | 373/396 = **94.2%** **[342] 321/342 = 93.9%**，平均 7.44 个食材/道 | ✅ **能**，这是本次盘点里**除 cook_minutes 外最扎实的一块**。但 `fridge_inventory` 表 **0 行** → 用户侧"我家里有什么"没有数据入口，能力有、数据空。**另见 §5.2(15)：候选池里 21 道菜没有任何食材行 → R-09 覆盖率天花板 93.9%** |
| **预算**（ingredient.reference_price 推算） | 66/771 = **8.6%** 食材有价；396 道里 **352 道**至少缺一个价 **[342] 300/342 = 87.7%** | ❌ **不能**。`PricingService.estimate` 在 `priced_items==0` 时返回 None，`score_budget`(15 分) 会**静默失效**——不报错，就是不生效 |
| **最近吃过没**（decision_log + menu_item） | decision_log 190 行 / 8 用户 / 3 天；menu_item 146 行 | ⚠️ 链路通了，但 `consumption_record` **0 行**、`fridge_inventory` **0 行** → 用户"实际吃了什么"没有任何反馈入口，只能靠"推荐过什么"反推 |
| **几个人**（household.member_count） | 8/8 家庭档案有值（1–2 人） | ⚠️ 用户侧有，**recipe 侧无对应字段**（没有 servings / 分量字段）。"几个人"只能靠 `category in (主食,面食)` 粗代理 |

### 1.6 候选池压力测试（决定首页能不能筛出菜）

```sql
SELECT 'C1 早餐∩<=15min' s, COUNT(*) c FROM recipe WHERE meal_slots LIKE '%breakfast%' AND cook_minutes<=15;
SELECT 'C3 午餐∩<=30min∩荤菜' s, COUNT(*) c FROM recipe WHERE meal_slots LIKE '%lunch%' AND cook_minutes<=30 AND category='荤菜';
SELECT 'C6 夜宵∩轻食∩<=20min' s, COUNT(*) c FROM recipe WHERE (is_light=1 OR meal_slots LIKE '%late_night%') AND cook_minutes<=20;
SELECT 'C10 三者齐全' s, COUNT(*) c FROM recipe WHERE tools IS NOT NULL AND tools<>'[]'
   AND season IS NOT NULL AND season<>'[]' AND meal_slots IS NOT NULL AND meal_slots<>'[]';
```

| 场景 | 候选池 | 判断 |
|---|---:|---|
| 早餐 ∩ ≤15min | **7** | 🔴 枯竭 |
| 早餐 ∩ ≤15min ∩ (主食/面食) | **7** | 🔴 枯竭 |
| 午餐 ∩ ≤30min ∩ 荤菜 | **6** | 🔴 枯竭 |
| 夜宵 ∩ 轻食 ∩ ≤20min | **19** | 🟡 勉强 |
| 夜宵（is_light=1，不限时） | 35 | 🟡 勉强 |
| 晚餐 ∩ ≤30min ∩ 不辣 | 180 | 🟢 健康 |
| 晚餐 ∩ ≤30min ∩ 辣≥2 | 72 | 🟢 健康 |
| 素菜 ∩ ≤20min ∩ 不辣 | 56 | 🟢 健康 |
| 汤羹 ∩ ≤45min | 27 | 🟡 勉强 |
| 时令=夏 | 15 | 🔴 枯竭 |
| 时令=春 / 秋 | **0 / 0** | 🔴 **直接空结果** |
| 只用空气炸锅 | 5 | 🔴 枯竭 |
| **meal_slots ∩ tools ∩ season 三者齐全** | **3** | 🔴 精确筛选模式基本不可用 |

**结论：只要首页把「餐次」和「时间」同时作为硬条件，早上和中午必然筛空。**

---

## 2. 决策链路现状：一次 `/api/decide` 到底用了哪些字段

读 `backend/app/services/decision_service.py`（945 行）+ `config.py` `DecideSettings`。

### 2.1 实际参与**过滤**的字段（`_passes`，第 586–624 行，2026-09-23 复核）

| 顺序 | 条件 | 用到的字段 | 会不会放宽 |
|---|---|---|---|
| 1 | 忌口 / 过敏 | `c.haystack` = 菜名 + **recipe_ingredient 全部食材名** | ❌ 永不放宽（安全线） |
| 2 | 本次会话手动排除 | `c.name` | ❌ |
| 3 | 近 7 天不重复 | `c.name`（归一化后 vs `decision_log` ∪ `menu_item`） | ✅ 第 4 级才放 |
| 4 | 深夜只留轻食且够快 | **`is_light`** + `cook_minutes` ≤ `late_night_max_minutes`(20) | ❌ |
| 5 | 出餐时间上限 | `cook_minutes` ≤ `cook_cap` | ✅ 第 2 级就放 |

### 2.2 实际参与**打分**的字段（`_score`，第 626–691 行，2026-09-23 复核）

| 权重项 | 分值 | 用到的字段 |
|---|---:|---|
| 库存命中率 | 25.0 | `recipe_ingredient` → 食材名 ∩ `fridge_inventory` |
| 菜系偏好 | **0.0**（原 20.0，**已归零 ✅**） | **`recipe.cuisine`** ← ⚠️ **信号本身是死的，见 §2.4** |
| 天气 | 18.0 | `tags` / `flavor_tags` / `category` / `spice_level` |
| 辣度贴合 | 15.0 | `spice_level` |
| 预算贴合 | 15.0 | 派生 `cost`（`ingredient.reference_price`）← ⚠️ 常为 None |
| 早餐偏好 | +12 / +8 | `category in (主食,面食)` / `cook_minutes ≤ 15` |
| 临期食材命中 | +10 | `fridge_inventory.expiry_date` |
| 同品类打散 | −25/次 | `category` |
| 连续两餐不重样 | −40 | **`main_ingredient`** |
| 同菜系连续 | −15 | `cuisine` ← ⚠️ 同样是死的 |
| 口语诉求加分 | ≤ +21 | `intent.bonus()` → `cuisine` / `ingredients` |

### 2.3 ⚠️ 买了武器没上战场：目前**完全没被用上**的字段

| 字段 | 建表/迁移成本 | 当前用途 | 说明 |
|---|---|---|---|
| **`meal_slots`** | 迁移 0016 建了 | **0 处引用** | 时段判断全靠 `_resolve_slot()` 硬编码小时段（22–5 夜宵 / <10 早餐 / <15 午餐 / 其余晚餐）。库里明明有"这道菜适合哪餐"的答案，引擎不看 |
| **`tools`** | 迁移 0016 建了 | **0 处引用** | 厨具条件完全没进决策。用户说自己有空气炸锅，系统不知道哪些菜能做 |
| **`season`** | 迁移 0016 建了 | **0 处引用** | 时令完全没进决策 |
| **`protein_g / carb_g / fat_g`** | 基础层 | **0 处引用** | 营养三列在决策里完全不存在 |
| **`calories`** | 基础层 | 只进 payload 展示 | 不参与打分。所以"饿的程度"目前**在决策里没有任何体现** |
| **`difficulty`** | 基础层 | 只进 payload 展示 | 不参与打分 |
| **`cover_text`** | 迁移 0014 | 只进 payload 展示 | |
| **`quick_steps`** | 迁移 0014 | 只作为 `steps` 来源展示 | |
| **`enrich_status / enriched_at / enrich_source / steps_source`** | 迁移 0016 | 0 处引用 | 富集质量对决策完全无影响——**富集得好不好，没人知道** |
| **`household.kitchen_equipments`** | 已有 | **0 处引用** | 用户填了厨具，决策不看 |
| **`household.member_count`** | 已有 | 只用于 `/api/today` 展示 `servings` | 决策不看 |
| **`is_light`** | 迁移 0014 | **只在 late_night 用了** | 白天"想吃清淡"走的是 `intent.require_light`，而 `intent.require_light` 用的也是 `is_light`。35 道的池子，**白天说"清淡"也只从 35 道里挑** |

### 2.4 🔴 最严重的一处：菜系打分是死的

```sql
-- recipe.cuisine 的实际取值（分类，不是菜系）
SELECT cuisine, COUNT(*) c FROM recipe GROUP BY cuisine ORDER BY c DESC;
-- 荤菜111 素菜61 主食59 水产28 早餐25 饮品23 甜品19 汤与粥18 半成品加工9 调味品8 汤羹4 家常菜3 川菜2 调料1 半成品1

-- diet_preference.cuisines 的实际取值（真实菜系）
SELECT id, user_id, cuisines FROM diet_preference;
-- ["川湘","粤菜","川菜","江浙"] / ["日料","江浙"] / ["spicy"] / ["家常"] / ["家常"] / ["川湘"]

-- 两边能对上的菜
SELECT COUNT(*) FROM recipe WHERE cuisine IN ('川湘','粤菜','江浙','家常','日料','西北','西餐','川菜','日韩','湘菜','鲁菜','闽菜','徽菜','东北','东南亚','意餐');
-- => 2  （仅"川菜"2 道；"家常菜"≠"家常"，对不上）
```

**后果 1（打分）：** `score_cuisine` 原为 20.0，是权重第二高的项，实际命中 **2/396 ≈ 0.5%**。等于这一路打分对 99.5% 的菜不生效。

> ✅ **已处置（2026-09-23，fix-cuisine-weight）**：`config.py` L148 已改为 `score_cuisine: float = 0.0`，注释原文："带 20 分权重时它在『假装在打分』，还挤占了库存/天气这些真实权重的空间，比不打更糟"。**本条结论保留为事实记录，不再作为待办。** 恢复条件写在 `config.py` L146-147：`cuisine` 由凌晨 LLM 富集标注回填后，恢复 20.0 并同步 `config/default.yaml` 与 `shared/decide.ts`。

**后果 2（理由文案，用户可见）：** `reason_service` 的"换换口味"系列用的是 `cuisine`，于是真实日志里出现：

```sql
SELECT reason, COUNT(*) c FROM decision_log GROUP BY reason ORDER BY c DESC LIMIT 12;
```

```
可选项不多了，就它吧。        36
换换口味，试试荤菜           16      ← cuisine="荤菜"
换换口味，试试主食           13      ← cuisine="主食"
主食好久没吃了               13
荤菜好久没吃了               12
来点主食，换个节奏           11
换换口味，试试素菜           10
换换口味，试试汤与粥          9
来点荤菜，换个节奏            8
```

还有 `换换口味，试试早餐`、`来点半成品加工，换个节奏`、`换换口味，试试川菜`。
**"换换口味，试试早餐" 是会出现在用户屏幕上的文案**——这事不用等埋点就能判定为缺陷。

### 2.5b 🔴 追加发现：候选池里有 61 道「非菜品」，且已经真实推荐给用户 18 次

起因是 user-researcher 提示"DB 的 cuisine 装的明明是 category 的值，可能是导入时列错位"。我去验了这个假设，结果**假设部分成立，但顺着它挖出一个比菜系严重得多的洞**。

#### (a) 列错位假设：成立，但**无法无损恢复菜系**

```sql
SELECT source, COUNT(*) FROM recipe GROUP BY source;
-- proj_kitchen 338 / howtocook 34 / ai_generated 24

SELECT source, cuisine, COUNT(*) FROM recipe GROUP BY source, cuisine;
```

| source | cuisine 的实际取值 | 结论 |
|---|---|---|
| `proj_kitchen` (338) | 荤菜99/主食57/素菜55/水产27/早餐24/饮品18/汤与粥18/甜品18/半成品加工9/调味品8/家常菜3/川菜2 | 源数据的**自有分类**被写进了 cuisine 列 |
| `howtocook` (34) | 荤菜12/素菜6/饮品5/汤羹4/主食2/早餐1/调料1/半成品1/水产1/甜品1 | 同上 |
| `ai_generated` (24) | **全部 NULL** | cuisine 从未被赋值 |

**关键判定**：`recipe.category` 是**正确的**（标准 7 值枚举：荤菜/素菜/主食/面食/汤羹/凉菜/小吃，由迁移 0014 规则生成），`recipe.cuisine` 装的是**源数据集自己的分类**。所以不是"两列互换"，而是**源数据的分类列被错误映射到了 cuisine 列**。

**但菜系无法恢复**——338 道 proj_kitchen 里只有 `家常菜3 + 川菜2` 共 5 道带菜系味，其余全是分类值；`ai_generated` 24 道 cuisine 全 NULL。**源数据集根本不带菜系字段**，所以"从源头无损恢复"这条路走不通，真要菜系只能靠 LLM 重标。

> 结论：**支持 user-researcher 的判断 —— 归零 + 删题，不要重标。** 数据侧给出的理由比心智侧更硬：不是"重标贵"，是**源数据里压根没有，只能凭空生成**。

#### (b) 顺着挖出来的更大的洞：61 道非菜品在候选池里

那批"源数据自有分类"里混进了大量**根本不是一道菜**的条目：

```sql
SELECT COUNT(*) FROM recipe
WHERE cuisine IN ('饮品','甜品','调味品','半成品加工','半成品','调料');   -- 61
```

| 源分类 | 数量 | 实例 |
|---|---:|---|
| 调味品 | 8 | **油泼辣子、油酥、炸串酱料、简易版炒糖色、糖醋汁、草莓酱、葱油、蒜香酱油** |
| 饮品 | 23 | **B52轰炸机、Mojito莫吉托、金汤力、可乐桶**、奶茶、柠檬水、冬瓜茶、杨枝甘露、酸梅汤 |
| 甜品 | 19 | 提拉米苏、奥利奥冰淇淋、草莓冰淇淋、雪花酥、龟苓膏、烤蛋挞、戚风蛋糕 |
| 半成品加工 | 9 | 速冻水饺、速冻馄饨、速冻汤圆、炸薯条、**牛油火锅底料** |
| 小吃/调料 | 2 | 速冻汤圆、油酥 |

**这些条目 `category` 被规则强行归到了「荤菜/素菜/小吃/汤羹/凉菜」，所以它们完全能通过决策引擎的所有过滤。**
例如：`牛油火锅底料` → `category=荤菜`；`油泼辣子` → `category=素菜`；`酸梅汤` → `category=汤羹`。

#### (c) 已经真实发生了：18 次非菜品被推荐出去

```sql
SELECT d.dish_name, r.cuisine, r.category, COUNT(*) times
FROM decision_log d JOIN recipe r ON r.id=d.recipe_id
WHERE r.cuisine IN ('饮品','甜品','调味品','半成品加工','半成品','调料','早餐')
GROUP BY d.dish_name, r.cuisine, r.category ORDER BY times DESC;
```

| 被推荐的"菜" | 源分类 | 被规则归成的 category | 次数 |
|---|---|---|---:|
| 空气炸锅鸡翅中 | 半成品加工 | 小吃 | 2 |
| 炸鲜奶 | 甜品 | 小吃 | 2 |
| 无厨师机蜂蜜面包 | 甜品 | 面食 | 2 |
| **油酥** | 调味品 | 小吃 | 2 |
| **油泼辣子** | 调味品 | 素菜 | 1 |
| **炸串酱料** | 调味品 | 小吃 | 1 |
| **B52轰炸机** | 饮品 | 小吃 | 1 |
| **金汤力** | 饮品 | 汤羹 | 1 |
| 酸梅汤 | 饮品 | 汤羹 | 1 |
| 速冻水饺 | 半成品加工 | 凉菜 | 1 |
| 炸薯条 | 半成品加工 | 小吃 | 1 |
| 咖啡椰奶冻 | 甜品 | 凉菜 | 1 |

**18 / 190 = 9.5% 的决策推出去的是非菜品。**
用户点「饭决」，屏幕上出现过 **「油泼辣子」「炸串酱料」「B52轰炸机」**——这不是潜在风险，是**已经发生的事故**。

#### (d) 附带修正：`cook_minutes` 是品类基准值，不是真实耗时

```sql
SELECT COUNT(*) FROM recipe WHERE cook_minutes=22;   -- 119 道（30%）
SELECT cuisine, COUNT(*) FROM recipe WHERE cook_minutes=22 GROUP BY cuisine;
-- 荤菜61 / 水产16 / 素菜14 / 早餐12 / 甜品6 / ...
```

`cook_minutes=22` 恰好等于 `dish_rules.CATEGORY_MINUTES["荤菜"] = 22`，且集中在荤菜系。13 个离散值完全对应 `CATEGORY_MINUTES` + `METHOD_MINUTES` 两张表的枚举。
→ **"100% 覆盖"是规则生成的品类基准值，不是实测耗时。** 实测：`完美水煮蛋 22 分钟`、`美式炒蛋 15 分钟`、`茶叶蛋 22 分钟`。
→ 修正 §1.3 的判断：cook_minutes **能用于粗分档（≤15/≤30/≤60），不能当精确耗时展示**，也不能做分钟级滑杆。**"多久吃上"三档里 ≤15 这一档的可信度最差**（因为它会把 22 分钟基准的菜挡在外面，而 22 只是"荤菜"的默认值）。

### 2.5 真实使用侧数据（decision_log 190 行）

```sql
SELECT SUM(payload LIKE '%"relaxed": true%') relaxed_true, COUNT(*) total FROM decision_log;
-- 36 / 190 = 18.9%

SELECT meal_slot, SUM(payload LIKE '%"relaxed": true%') relaxed_true, COUNT(*) total
FROM decision_log GROUP BY meal_slot;
-- dinner     24 / 167 = 14.4%
-- late_night 12 /  15 = 80.0%   ← 🔴
-- lunch       0 /   8 =  0%

SELECT accepted, COUNT(*) FROM decision_log GROUP BY accepted;
-- NULL 162 (85.3%) | 1 → 28 (14.7%)
```

> 🔴 **其中"夜宵 12/15 = 80%"已于 2026-09-23 撤回**：15 条 late_night 决策集中在 77 分钟内，而夜宵池只有 16 道，**连点 15 次必然抽干**——这是压测伪影，不是数据质量证据。已改为以结构性大小（16 道）定目标，见 §4.6 修订二。
>
> ⚠️ **数据可信度声明**：这份 decision_log **不能当作真实行为基线**。
> `SELECT user_id, decision_date, COUNT(*), TIMESTAMPDIFF(SECOND,MIN(created_at),MAX(created_at)) FROM decision_log GROUP BY user_id, decision_date`
> 显示：单用户单日最多 **58 次决策 / 246 秒**，2026-09-22 有 5 条决策在 **4 秒内**连续产生（id 186→190，全部 late_night + relaxed=true）。
> 这是**联调/压测数据**，不是用户行为。
> **但它仍然证明了两件事**：(a) 夜宵时段候选池确实会枯竭（80% 放宽）；(b) `accepted` 字段 85.3% 为 NULL，说明**采纳反馈链路前端根本没打全**（`DecideBoard.tsx` 的「换一个」只调 `roll()`，**从不调 `feedback(false)`**）。

---

## 3. 新首页字段 Gap 表：首页想要 → 现有字段 → 够不够 → 怎么补

按"人决定吃啥时会想什么"的 10 个决策维度逐项列。

### 3.1 覆盖率阈值法则（建议全队遵守）

| 覆盖率 | 允许的用法 |
|---|---|
| ≥ 90% | 可以做**硬过滤**（筛掉就是筛掉） |
| 70–90% | 可以做硬过滤，但**必须配放宽兜底**并上报 `relaxed_level` |
| 30–70% | **只能做加分/排序**，不能当筛选项 |
| < 30% | 只能做加分，且**不该出现在首页 UI 上**（点了就空，比没有更伤） |
| 存在"某个取值 = 0 结果" | **禁止上线**（例：时令=春 → 0 道） |

### 3.2 Gap 表

| # | 首页决策维度 | 现有字段 | 覆盖 | 够不够 | 补齐手段 | 优先级 |
|---|---|---|---|---|---|---|
| 1 | **多久吃上**（≤15 / ≤30 / 随便） | `cook_minutes` | 100% | ✅ **够** | 不用补。但只有 13 档，滑杆别做太细 | P0 直接用 |
| 2 | **做不做**（自己做 / 外卖 / 出去吃） | `cook_minutes` + `tags`(雨天) + `advice` 字段 | 100% | ✅ **够** | 现有 `_build_result` 已有 `advice="这种天出门不值当，交给外卖吧"` 逻辑，首页直接复用 | P0 直接用 |
| 3 | **忌口** | `recipe_ingredient` 食材名 + `allergy_restriction` | 94.2% | ✅ **够** | 23 道无食材行的菜，建议**默认排除**（宁可少 23 道，也不能漏忌口——这是安全线） | P0 直接用 |
| 4 | **家里有啥** | `recipe_ingredient` ∩ `fridge_inventory` | 食材侧 94.2%，**库存侧 0 行** | ⚠️ **能力有、数据空** | 不是数据问题，是**入口问题**：`fridge_inventory` 0 行说明用户没地方录。首页要把"冰箱里有啥"做成**一键勾选**（从 771 个 ingredient 里挑高频的 ~60 个），不能指望用户手动建库存 | P0 做入口 |
| 5 | **荤素 / 想吃肉还是吃菜** | `meat_type` + `category` | meat_type 71%，category 98.7% | ⚠️ **勉强够** | 纯规则回填：重跑 `guess_meat_type()`（`none` 只有 10 道 vs 素菜 74 道，明显漏判）。**不需要 LLM** | P0 规则回填 |
| 6 | **辣不辣** | `spice_level` | 100%（但"要辣"只有 136 道，34.3%） | ✅ **够** | 不用补。但"很辣(≥3)"只有 39 道，别做 4 档滑杆，做 3 档（不辣/微辣/辣） | P1 |
| 7 | **饿的程度**（垫一口 / 正常 / 很饿） | `calories`（口径存疑）+ `category` | 98% 但口径存疑 | ❌ **不够** | ① 先确认 calories 是"一人份"还是"整锅"（127 道 ≥800 强烈暗示是整锅）；② 口径确认后纯规则分档（<300 垫一口 / 300–600 正常 / >600 很饿）；③ 若要更准，凌晨 LLM 批量重估 calories，**但只对 8% 缺失 + 高异常值那批做** | P1 先清口径 |
| 8 | **时间 / 这一餐**（早/午/晚/夜宵） | `meal_slots` 20.5%，实际靠 `_resolve_slot()` 小时段 | **20.5%** | ❌ **不够** | **① 前端按当前钟点自动定餐次，不让用户手动选**（时段是客观事实，不是偏好）；② 后端只用 `meal_slots` 做**加分**不做过滤；③ 纯规则扩 `guess_meal_slots`：加 `午餐` 关键词（饭/盖饭/套餐/便当），把覆盖率从 20.5% 拉到 ~60% | P0 改交互 |
| 9 | **最近吃过没** | `decision_log` ∪ `menu_item`（推荐过什么） | 链路通，`consumption_record` 0 行 | ⚠️ **半够** | ① 短期：用"推荐过"当"吃过"的代理（现状）；② 首页加一个**「这个我吃过了」**的一键标记，落到 `consumption_record`——这是把代理换成事实的唯一低成本手段；③ `main_ingredient` **必须先归一**（232 → ~60 族），否则"不重样"是假的 | P0 建归一表 + 反馈入口 |
| 10 | **预算**（这一顿花多少） | 无 `estimated_cost`，靠 `ingredient.reference_price` 现算 | 食材有价 **8.6%** | ❌ **不够** | ① 凌晨 LLM/爬虫批量补 `ingredient.reference_price`（771 个里补最高频的 ~200 个即可覆盖 80% 的菜）；② 补不出来前，**预算维度不要上首页**；③ 兜底用 `category` 粗代理（荤菜 > 素菜 > 主食） | P2 本版不上 |
| 11 | **几个人** | `household.member_count`（用户侧有）；recipe 侧**无 servings 字段** | 用户侧 100%，菜侧 0% | ❌ **不够** | recipe 侧无字段。短期用 `category in (主食,面食)` + `cook_minutes` 粗代理；真要做得加 `recipe.serving_size` 字段 + 凌晨 LLM 富集 | P2 本版不上 |
| 12 | **厨具条件** | `recipe.tools` 18.2% vs `household.kitchen_equipments` 5/8 空，且**词表不通** | **18.2%** | ❌ **绝对不够** | ① **先做词表映射表**（pot↔灶台/压力锅/电饭煲，steamer↔蒸锅，oven↔烤箱，air_fryer↔空气炸锅，+microwave↔微波炉）；② 映射后把 `tools` 从"筛选项"降级为**加分项**（覆盖率 18.2% 远低于 70% 线）；③ 反向用：只做"**我没有的厨具做的菜，往后排**"，不做"只出我能做的菜" | P1 做映射 + 降级 |
| 13 | **当季 / 时令** | `season` 7.6%，**春/秋 = 0** | **7.6%** | ❌ **绝对不够，且会出 0 结果** | ① `guess_season` 补春（春笋/荠菜/韭菜/香椿）和秋（南瓜/栗子/藕/蟹）规则；② 补完也只到 ~15%，**本版首页不要放"当季"格子**；③ 真要放，做成"当季推荐"的**内容位**（人工运营 ~10 道），不做筛选器 | P2 本版不上 |
| 14 | **菜系偏好**（川湘/粤菜…） | `recipe.cuisine` 词表污染 | 93.9% 但**语义错** | ❌ **是 Bug，不是缺口** | **已与 user-researcher 达成一致：权重归零 + 删题，不重标。** 三方证据：① 用户不活跃（106 条语料里真点名菜系仅 6 条 = 5.7%，排末位）；② 模型判不准（Choice 到 0.90 阈值才触发，也是 6/106）；③ **数据里根本没有**（源数据 `proj_kitchen` 338 道只有"家常菜3+川菜2"带菜系味，`ai_generated` 24 道 cuisine 全 NULL → **源数据集不带菜系字段，无法恢复，只能凭空生成**）。落地：① `score_cuisine` 20 → 0；② 从 Onboarding 与档案页删掉这道题；③ **但必须捆绑**——口语侧"想吃川菜"要同时落到口味维度（他要的是辣/清淡，不是标签），否则会出现新的"我说了但没被听见"；④ 轮换轴从 cuisine 换成 category | **P0 必修**（归零+删题，非重标） |
| **15** | **候选池里有 61 道非菜品**（新增，严重度**高于菜系**） | 源分类 饮品23/甜品19/调味品8/半成品加工9/调料1/半成品1 | — | 🔴 **已造成真实事故** | **18/190 = 9.5% 的决策推出去过非菜品**（油泼辣子/炸串酱料/油酥/B52轰炸机/金汤力/速冻水饺）。这些条目 `category` 被规则强行归成荤菜/素菜/小吃/汤羹，能穿过所有过滤。**纯规则可修**：用源分类黑名单（饮品/甜品/调味品/半成品加工/调料/半成品）从候选池剔除 61 道，或加 `is_dish` 布尔列。剔除后全池 396 → **335** | **P0 必修** |
| **16** | **「直接点名一道菜」point_dish**（新增） | `normalize_dish_name()` + `ALIAS_PAIRS` 双端已有 | 语料 9.4%（≥10/106），第三大诉求 | ⚠️ **引擎认得出、接不住** | `intent_type` 里有 `point_dish` 分类，但 `MealIntent` **没有任何字段承接它**。实测可行性（106 条语料 × 396 道菜名求交）：**6 条可直接命中**（水煮鱼/红烧肉/牛排/番茄炒蛋/宫保鸡丁/鸡蛋羹），且 `ALIAS_PAIRS` 归一化确认有效——"番茄炒蛋"同时命中"西红柿炒鸡蛋"+"番茄炒蛋"两道。**≥7 条未命中**（意面/寿司/沙拉/泡菜炒饭/烤肉/蒸菜/牛肉面）→ 正好走"未命中→静默照常出菜→菜名记进 `decision_log.utterance`→凌晨定向补新菜"闭环。**纯规则可做，不需要模型** | **P1 建议做** |

### 3.3 补齐手段的分工原则

| 手段 | 适用 | 本版要做的 |
|---|---|---|
| **纯规则回填** | 能从菜名/食材名推断的：meal_slots、meat_type、season、tools | ✅ meal_slots 扩词、meat_type 重跑、tools/season 补春夏秋冬词 |
| **凌晨 LLM 富集** | 规则推不出的：真实菜系、serving_size、热量口径校准、轻食扩池 | ✅ 菜系标注（396 道）；⚠️ 预算/人数本版不做 |
| **用户手动补** | 只有用户知道的：家里有啥、最近吃过没、忌口 | ✅ 首页做**一键勾选**入口（高频食材 ~60 个 + 「这个我吃过了」） |
| **清洗/映射** | 词表不一致：cuisine、tools | ✅ 两块都要做，且成本极低 |

---

## 4. 埋点与指标体系（V1.2.0）

### 4.1 北极星指标

> **决策闭环率 DCR（Decision Closure Rate）**
> = 在一次「饭决」会话（session）内产生过「就这个」或「开始做」的决策会话数 ÷ 总决策会话数

**为什么是它：** 饭决的价值主张是"今天吃啥，交给饭决"——价值的兑现点是**用户不再纠结、拿到一个能执行的答案**。
- 用"采纳"而不是"出结果"：出结果是系统的动作，采纳是用户的认可；
- 用"会话"而不是"单次决策"：一次纠结过程（可能换 3 次）才是一个完整的需求单元。按单次决策算会把"换一个"稀释成"成功决策"，掩盖真实挫败感。

**基线：** 现有 `decision_log.accepted` 只有 28/190 = 14.7%，但**这份数据是压测，不可用作基线**（见 §2.5）。
**必须先把埋点补上，跑 2 周拿真实基线，再设目标值。** 在此之前不要对外宣称任何"采纳率提升"。

### 4.2 一级指标（5 个）

| # | 指标 | 定义 | 为什么看它 | 数据来源 |
|---|---|---|---|---|
| M1 | **首轮成决策率** | 换一个次数 = 0 就采纳的会话 ÷ 总会话 | 第一道菜能不能服人。这是"决策质量"最直接的表达 | `decision_event` |
| M2 | **换一个次数中位数** | 每会话 `decide_reroll` 次数的中位数 | 比 M1 更敏感；分布形态能看出"有没有一群人卡在某个维度" | `decision_event` |
| M3 | **候选枯竭率** | `relaxed=true` 的决策 ÷ 总决策 | **直接反映数据支撑度**。这是本次盘点所有缺口的上游指标，也是补齐工作的 ROI 度量 | `decision_log.payload` → 建议提成独立列 |
| M4 | **7 天去重率** | 7 天内不同菜名数 ÷ 决策总数 | 用户对"这个 App 就这几道菜"的感知强度 | `decision_log` |
| M5 | **决策→开做转化率** | `decide_cook_start` ÷ 采纳数 | 从"选出来了"到"真做了"的最后一跳。目前**这一跳完全不存在**（DecideBoard 没有「开始做」按钮） | 新增 |

### 4.3 关键漏斗

```
L0  首页曝光            home_view
        ↓  (首屏渲染完成，无论有没有历史结果)
L1  看到结果            decide_result_shown        ← /decide 返回并渲染（含冷启动 /decide/last 秒开）
        ↓
L2  换一个              decide_reroll             ← 可多次，带 reroll_index
        ↓  (回到 L1)
L3  就这个（采纳）       decide_accept
        ↓
L4  看做法              decide_view_steps
        ↓
L5  开始做              decide_cook_start         ← V1.2.0 新增，当前缺失
        ↓
L6  做完了 / 吃过了      decide_cook_done          ← V1.2.0 新增，当前缺失
```

**漏斗必须能按维度切片**，否则看不出是哪个格子在漏：
`meal_slot` × `relaxed_level` × `候选池大小` × `用户是否填过档案` × `用户是否录过冰箱`

### 4.4 事件表设计

#### (a) 新建 `decision_event` 埋点流水表

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | bigint PK | |
| `user_id` | int | |
| `decision_id` | int NULL | 关联 `decision_log.id` |
| `session_id` | varchar(36) | **关键**：一次"纠结过程"的唯一 ID。前端进首页生成，点「就这个」或离开页面 30 分钟后失效 |
| `event` | varchar(40) | 见下表 |
| `props` | json | 事件特有属性 |
| `created_at` | datetime | |

索引：`(user_id, created_at)`、`(session_id)`、`(event, created_at)`

#### (b) 事件清单

| # | event 名 | 触发时机 | 关键属性（props） |
|---|---|---|---|
| E1 | `home_view` | 首页首屏渲染完成 | `has_last_result`（是否秒开）、`meal_slot`、`has_profile`、`has_fridge`、`entry`（push/直接打开/小程序） |
| ~~E2~~ | ~~`home_filter_tap`~~ | — | ❌ **2026-09-23 删除**（事件清单 12 → 11）。J6/J7 作废后无消费方；唯一挂点语义是「录入食材」不是「筛选」。**实现侧可继续打点，但不得作为任何判据/报表的数据源**。原计划的 `result_count`（"哪个格子筛不出菜"）改由 `decision_log.candidate_count` 承担 → J6'/J7' |
| E3 | `decide_roll` | 点「饭决」/「换一个」 | `reroll_index`（0=首次）、`exclude_count`、`utterance_used`（是否用了口语输入）、**`filters_snapshot`（本次所有维度的取值快照）** |
| E4 | `decide_result_shown` | 结果卡渲染完成 | `decision_id`、`recipe_id`、`reason`、`reason_type`、`relaxed`、`relaxed_level`、`candidate_count`、`cook_minutes`、`category`、`main_ingredient` |
| E5 | `decide_reroll` | 点「换一个」 | `reroll_index`、`prev_recipe_id`、`prev_reason`、`prev_relaxed` |
| E6 | `decide_accept` | 点「就这个」 | `decision_id`、`reroll_index`、`relaxed`、`result_age_ms`（从出结果到采纳，衡量犹豫时长） |
| E7 | `decide_view_steps` | 点「看做法」 | `decision_id`、`step_count`、`steps_source`（quick_steps / 文本拆分） |
| E8 | `decide_cook_start` | 点「开始做」（新增按钮） | `decision_id`、`recipe_id` |
| E9 | `decide_cook_done` | 点「做完了/吃过了」（新增） | `decision_id`、`recipe_id` → **同时写 `consumption_record`**，把"最近吃过没"从代理换成事实 |
| E10 | `decide_reject` | 点「换一个」时显式上报未采纳（新增） | `decision_id`、`reroll_index` → **同时把 `decision_log.accepted` 置 0**。当前前端**从不打 false**，导致 85.3% 是 NULL |
| E11 | `decide_empty_pool` | 候选池 < 8 道时（即使最终放宽成功也上报） | `filters_snapshot`、`pool_size`、`relaxed_level` |
| E12 | `stubborn_shown` | 弹「饭决已经替你定了」 | `round` |

#### (c) `decision_log` 需增列（DDL 建议，不在本次执行范围）

| 新列 | 类型 | 用途 |
|---|---|---|
| `session_id` | varchar(36) | 串联一次纠结过程，算 M1/M2 必需 |
| `reroll_index` | int default 0 | 算 M2 必需 |
| `relaxed` | tinyint(1) | 现在埋在 `payload` 的 JSON 文本里，**只能 LIKE 扫全表**，必须提成列 |
| `relaxed_level` | int | 0=未放宽 / 1=松时间 / 2=松品类 / 3=松主料 / 4=松重复 |
| `candidate_count` | int | 候选池大小，判断数据支撑度的直接信号 |
| `filters_snapshot` | json | 用户这次勾了哪些维度 |

#### (d) 埋点落地要点（给前端的硬要求）

1. **`session_id` 必须前端生成并贯穿**——没有它，M1/M2 全部不可算。
2. **「换一个」必须同时打 `decide_reroll` + `decide_reject`**——现状是从不打 reject，导致 `accepted` 85.3% 为 NULL，采纳率算不出来。
3. ~~**`home_filter_tap` 必须带 `result_count`**~~ → **该事件已于 2026-09-23 删除**（见事件清单 E2）。**替代要求**：「哪个格子筛不出菜」改由 **`decision_log.candidate_count` + `filters_snapshot`** 承担 —— 每一跳决策都要落池子大小快照，否则 §5 的风险仍只能靠猜。**这条要求的实质没变，只是换了载体**，前端仍必须保证 `filters_snapshot` 非空。
4. **别依赖"AI 推荐准确率"**——按铁律，所有判据必须是纯规则可算的（计数、中位数、占比）。本报告所有指标都不需要模型参与。

### 4.5 判断重构成功与否的量化判据（5 条）

> ⚠️ **前提声明**：现有 decision_log 是压测数据，**不能作为基线**。下表给出的是**绝对目标 + 依据**；V1.2.0 上线后应先跑 2 周纯采集建立真实基线，再回填"相对提升"。

| # | 判据 | 目标区间 | 依据 |
|---|---|---|---|
| **J1** | **决策闭环率 DCR**（北极星） | **≥ 50%**，挑战值 60% | 依据：产品上"倔强提示"在 `stubborn_after=3` 次后强制锁定，说明系统设计容忍上限是 3 次换一个；闭环率 50% 对应"两次纠结里有一次能定下来"，是"交给饭决"这个主张的最低兑现线。基线需重采后校准 |
| **J2** | **换一个次数中位数 M2** | **≤ 1 次**；P75 ≤ 2 次 | 依据：`config.stubborn_after=3` 是产品容忍上限，健康态必须显著低于它。中位数 ≤1 意味着至少一半用户第一道就服气 |
| **J3** | **深度放宽率**（`relaxed_level ≥ 4` 占比） | **全时段 ≤ 8%**；**夜宵 ≤ 20%** | ⚠️ **已修订，见下方 §4.6**。原稿用 `relaxed=true` 占比、并以"夜宵 80%"为依据，**两处都已作废** |
| **J4** | **7 天去重率 M4** | **≥ 0.80**（7 天内不同菜名数 ÷ 决策数） | 依据：硬规则 `no_repeat_days=7` 保证 7 天内菜名不重样，但"总是同一批菜"发生在**主料/品类**层（`main_ingredient` 232 个值、鸡蛋一个就占 43 道）。去重率看菜名只能证明硬规则生效，所以**必须加看主料去重率 ≥ 0.6**——这一个才是用户真能感知的 |
| **J5** | **决策→开做转化率 M5** | **≥ 25%**（采纳者中点了「开始做」） | 依据：**这一跳当前完全不存在**（DecideBoard 只有「就这个/看做法」，没有「开始做」）。无基线，先按"采纳是真意愿、开做是真执行"的常识给 25%，上线后 4 周校准 |

### 4.6 J3 的两次修订（重要，原稿已作废）

> 由 roadmap-planner 指出、经我复核确认。**J3 的原定义和原依据都不能用**，理由如下。

#### 修订零：迁移 0017 后的实跑更新（`is_dish` 已落地）

```sql
SELECT is_dish, COUNT(*) FROM recipe GROUP BY is_dish;   -- 1 → 342 | 0 → 54
SELECT COUNT(*) FROM recipe WHERE is_dish=1 AND is_light=1 AND cook_minutes<=20;  -- 16
SELECT COUNT(*) FROM recipe WHERE is_dish=1 AND is_light=1 AND cook_minutes<=15;  -- 16
SELECT COUNT(*) FROM recipe WHERE is_dish=1 AND cook_minutes<=15;                 -- 101
```

| 项 | 数 | 备注 |
|---|---:|---|
| **可用候选总数 `is_dish=1`** | **342** | PRD/路线图里的 335 **需更新为 342** |
| 判为非菜品 `is_dish=0` | 54 | 饮品23 / 甜品19 / 调味品8 / 调料1 / 半成品加工2(109懒人蛋挞、195牛油火锅底料) / 番茄红酱1 |
| 夜宵池 `is_dish ∩ is_light ∩ ≤20min` | **16** | ✅ ≥12，**允许收紧** |
| 夜宵池 `is_dish ∩ is_light ∩ ≤15min` | **16** | ✅ 与 ≤20 **完全相等** → **20→15 收紧零代价** |
| `is_dish=1 ∩ is_light=1` | 34 | 原 35，删掉 id340 金汤力(40min) |
| **快手池 `is_dish=1 ∩ ≤15min`** | **101** | ⚠️ 剔除前是 **132**，**被砍掉 31 道（-23%）** |

**三条结论**：
1. **删除 54 道对夜宵池零影响** —— 被删项里唯一 `is_light=1` 的是 id340 金汤力（40min），本就不在 ≤20min 池内。所以夜宵池 16 道不变。
2. **20→15 收紧现在是零代价的**（16 = 16，现有轻食菜没有落在 16–20 区间的）。R-22 的 12 道闸门通过。但 **16 道刚好卡在理论底线 15 上，零余量**（推导见下）。
3. 🔴 **一个此前没注意到的副作用**：剔除的 54 道里大多是饮品/甜品（10–12 分钟），**把 ≤15min 快手池从 132 砍到 101（-23%）**。而"多久吃上"是首页 P0 维度 —— **删非菜品和快手池是负相关的**，扩池时应优先补快手菜。

夜宵池 16 道的构成：凉菜7 / 素菜6 / 荤菜3（**没有主食/汤羹**，深夜想吃碗面或喝碗汤没有解）。

#### 🔴 附：深夜无解的真正成因是 `is_light` 误伤，不是池子小（修正上一轮判断）

```sql
-- 快手主食/面食/汤羹
SELECT COUNT(*) FROM recipe
WHERE is_dish=1 AND cook_minutes<=15 AND category IN ('主食','面食','汤羹');   -- 18 (主食9/面食9/汤羹0)
-- 其中 is_light=1 的
SELECT COUNT(*) FROM recipe
WHERE is_dish=1 AND cook_minutes<=15 AND category IN ('主食','面食','汤羹') AND is_light=1;   -- 0
```

**库里有 18 道 15 分钟能做好的面/饭，但没有一道被标成 `is_light=1`。**
→ "深夜想吃碗面无解"的准确因果：**不是没有面，是夜宵硬过滤 `is_light=1` 把主食/面食全挡在门外**。
→ **因此"扩池"解决不了这个问题**——新补的面照样会被 `is_light` 筛掉。这是上一轮"池子小要扩池"判断的错误，此处修正。

**修法验证（纯规则，一行条件，无需扩池）**：

| 方案 | 夜宵池 | vs ≥30 目标 |
|---|---:|---|
| 现状 `is_light=1 ∩ ≤15min` | 16 | ❌ 不达标（卡在理论底线 15 上） |
| **`is_light=1 OR category IN ('主食','面食')` ∩ ≤15min** | **34** | ✅ **达标** |
| 同上 ∩ ≤20min | 45 | ✅ 有富余 |
| 再加汤羹放宽到 ≤30min | 36 | ✅ |

修法后构成：面食9 / 主食9 / 凉菜7 / 素菜6 / 荤菜3 —— **主食面食从 0 变 18**。

**建议**：本版先做「夜宵口径修正」（纯规则，立即见效），**扩池不必提前到 P0**。
**实现约束**：不要改 `is_light` 字段值（它还要服务白天"想吃清淡"的诉求，语义会被稀释——蛋炒饭算轻食吗？），应在 `decision_service._passes()` **L613-618**（2026-09-23 复核，文件已被其他 worker 改过，`_passes` 从 L576 移到 L586）的 late_night 分支加**独立的品类白名单**。

**汤羹侧**：全库汤羹 24 道，`≤15min` **0 道**、`≤30min` 仅 **2 道**（`dish_rules` 中汤羹基准 40min、煲炖 60min）。**汤本就不是快手菜**，可接受，但文案不要承诺"深夜来碗热汤"。

**数字更正**：`late_night_max_minutes` 现状为 **20**（`config.py` L150），故按现状配置夜宵池是 **16 → 45**；上表的 34 是 ≤15min 口径（对应 R-22 若收紧）。两口径均 ≥30，**R-22 收紧不再受夜宵池牵制**。

**45 道的来源拆解**：

| 来源 | 道数 | 占比 |
|---|---:|---:|
| 靠 `is_light=1` 进来 | 16 | 36% |
| **靠品类白名单救回**（`is_light=0` 的主食/面食） | **29** | **64%** |

→ **这次几乎完全是靠白名单救回来的**，菜品属性基本不支持夜宵：全库 `is_dish=1` 中 `meal_slots` 含 `late_night` 的**仅 5 道**（≤20min 的 3 道）。**R-11（meal_slots 软惩罚）在夜宵场景基本无效。**

#### 🔴 与 R-11 的冲突（必须一并处理）

被白名单救回的 29 道里，`meal_slots` 分布：

| meal_slots | 道数 | 是否会被 R-11 软惩罚 |
|---|---:|---|
| `NULL` | 9 | 否（约定"空值 = 不限制照常参与"） |
| **`["breakfast","lunch"]`** | **17** | **是** ← 明确不匹配 late_night，会被减分 |
| `["dinner","late_night"]` | 3 | 否 |

→ **白名单把 29 道放进池子，R-11 又把其中 17 道的分压下去，两个改动互相抵消。**
→ **必须约束**：LATE_NIGHT 时段内，命中 `LATE_NIGHT_EXTRA_CATEGORIES` 的候选**跳过 `meal_slots` 软惩罚**。

#### ✅ 补充实跑一：验收 SQL 期望值表（改前/改后逐条对照，可直接当断言用）

| # | 断言 | 改前 | 改后（期望） | 实跑 | 判据 |
|---|---|---:|---:|---:|---|
| A | LATE_NIGHT 候选池（`is_dish=1` ∩ 口径 ∩ ≤20min） | 16 | **45** | 45 ✅ | ≥8 水位线 |
| A3 | 其中靠 `is_light=1` 进来 / 靠白名单救回 | 16 / 0 | 16 / 29 | 16 / 29 ✅ | 白名单贡献 64% |
| A4 | ≤15min 口径下的池子（R-22 若收紧） | 16 | 34 | 34 ✅ | 收紧不会击穿 |
| B | 45 道里会被 R-11 减分的（`meal_slots` 只有早/午） | — | 17 | 17 ⚠️ | 见上节，须豁免 |
| B2 | 45 道里 `meal_slots` 含 `late_night` 的 | — | 3 | 3 | R-11 在夜宵场景几乎无效 |
| C | `is_light=1 ∩ 主食/面食 ∩ ≤20min` | 0 | **0（不得增加）** | 0 ✅ | 守白天"清淡"语义 |
| C2 | 池子里出现非 `is_light` 的荤菜 | 0 | 0 | 0 ✅ | 不把重荤菜放进夜宵 |
| D | 池子分类构成 | — | 面食20/主食9/凉菜7/素菜6/荤菜3 | 一致 ✅ | — |

**45 道池的分类构成（改后）**：

| category | n | 占比 | 其中 `is_light=1` |
|---|---:|---:|---:|
| 面食 | 20 | 44.4% | 0 |
| 主食 | 9 | 20.0% | 0 |
| 凉菜 | 7 | 15.6% | 7 |
| 素菜 | 6 | 13.3% | 6 |
| 荤菜 | 3 | 6.7% | 3 |

→ 面食占 44% 偏集中，但 `category_spread_meals=3` + `category_penalty_step=25.0` 会把它压下去；
`main_ingredient` 侧极度扁平（鸡蛋 3、其余 ≤2），`main_ingredient_penalty=40` 不会被过度触发。**不会出现"夜宵永远是那几道"。**

#### ✅ 补充实跑二：极限压测 —— 这次修正的真正价值是"夜宵池不再塌进放宽阶梯"

`_passes()` 不是只用夜宵口径，还要叠加**忌口/过敏硬过滤**和**近 7 天不重复**。真实用户的池子远小于 45。
按最坏组合实跑（忌口词用子串匹配近似 `c.haystack`）：

| 场景 | 旧口径（16 道池） | 新口径（45 道池） |
|---|---:|---:|
| 池子原始大小 | 16 | 45 |
| 忌 蒜+葱+辣+花生，再叠"近 7 天已吃 12 道" | — | **23** |
| **忌 辣+鸡+蛋（命中率最高的三词），再叠"已吃 12 道"** | **4** 🔴 | **20** ✅ |
| 单个忌口词最大杀伤 | 辣 11 道 / 鸡 7 / 蛋 7 | 辣 11 / 鸡 7 / 蛋 7 |

→ **4 < `random_min_choices=3` 的舒适区**（实际仅比下限多 1），且远低于 `<8` 水位线：
旧口径下**任何一个有点忌口的深夜用户，几乎必然触发放宽**，而放宽后仍是同一小撮菜在打转（ping-pong）。
→ 新口径同条件下 **20 道**，是水位线的 2.5 倍，**基本不会触发放宽**。

**这才是这次一行改动的真实收益**：不是"菜变多了"，而是**把夜宵场景从"结构性塌方"拉回"正常供给"**。
（补充：45 道池下忌口后仍有 20 道，说明剩余池子的**抗忌口能力**才是关键指标，建议把「夜宵池忌口后存活数」列为上线前必查项。）

#### 🔎 补充实跑三：`tags` 里那个"夜宵"标签是死标签，别指望它

库里显式打了 `tags` 含 `夜宵` 的共 **13 道**（`is_dish=1` 的 12 道）：

| 菜 | category | cook_minutes | is_light | 能否进 ≤20min 池 |
|---|---|---:|---:|---|
| 米粥 | 主食 | 25 | 1 | ❌ 超时 |
| 银耳莲子粥 | 主食 | 25 | 1 | ❌ 超时 |
| 牛奶粥 | 主食 | 30 | 1 | ❌ 超时 |
| 蒸箱鸡蛋羹 | 汤羹 | 25 | 1 | ❌ 超时 |
| 上汤娃娃菜 / 勾芡香菇汤 / 微波炉鸡蛋羹 / 朱雀汤 / 紫菜蛋花汤 / 西红柿豆腐汤羹 / 金针菇汤 / 鸡蛋羹 | 汤羹 | 40 | 1 | ❌ 超时 |
| 金汤力（鸡尾酒） | 汤羹 | 40 | 1 | ❌ 且 `is_dish=0` |

- **13 道全部 `is_light=1`**（`also_light=13`）→ 加不加 `OR tags LIKE '%夜宵%'`，池子都是 45，**增量为 0**。
- **`enters_pool_20 = 0`** → 这 13 道**一道都进不了夜宵池**，因为粥 25/25/30 分钟、汤羹 40 分钟，全被 `late_night_max_minutes=20` 卡死。
- **结论**：`tags` 里的"夜宵"是**历史遗留的死标签**，与 `is_light` 完全冗余，且**时间上全部不合法**。
  → **不要在白名单里再加 `tags` 项**（无收益，且会让过滤条件更难维护）。
  → 若产品侧日后真的要"深夜喝碗热粥/热汤"，**唯一要动的是 `late_night_max_minutes`**（配置值，一行），不是扩池也不是改标签：

| `late_night_max_minutes` | 仅 `is_light` | `is_light` OR 主食/面食 |
|---:|---:|---:|
| 20（现状） | 16 | **45** |
| 25 | 25 | 77 |
| 30 | 26 | 78 |

→ **建议维持 20**：45 道已经是水位线的 5.6 倍，再放宽只是把 25 分钟的主食塞进来，对"深夜要快"的心智无益，
且会与已定的文案约束（不承诺"深夜来碗热汤"）冲突。**这条留作已知选项，本版不做。**

#### 🧩 一个结构性提醒：`≤20min` 上限正在系统性误伤主食

`cook_minutes` 是**品类基准值**而非实测值（§2.5b(d)），`dish_rules.CATEGORY_MINUTES` 中 **主食=25、面食=20、汤羹=40**。
所以：面食基准恰好 20 → 全部过线；**主食基准 25 → 结构性被 ≤20 卡掉**。
45 道池里主食只有 9 道（真有实测短时间的，如猪油拌饭 10min、红芸豆拌饭 10min），其余主食是"被基准值判死刑"。
→ 这不是 bug，但意味着：**讨论"夜宵要不要放宽到 25min"时，实际讨论的是"要不要让基准值填充的主食进来"**，
而这些菜的真实耗时并不可知。**因此不建议靠调时间上限来扩池**，保持 20 + 品类白名单即可。

#### 落地代码（已交付执行，`decision_service.py` 行号以实读为准）

- 模块级常量插在 `ALIAS_PAIRS` 之后、`_PUNCT` 之前：
  `LATE_NIGHT_EXTRA_CATEGORIES = ("主食", "面食")`
- `_passes()` 深夜分支（现 L613-618）改为：
  ```python
  if slot == MealSlot.LATE_NIGHT:
      if not (c.light or c.category in LATE_NIGHT_EXTRA_CATEGORIES):
          return False
      if (c.minutes or 0) > self.settings.late_night_max_minutes:
          return False
  ```
- **核心回归（守"白天说清淡不会拿到蛋炒饭"）**：
  ```sql
  -- ⚠️ 修订：下面这条我原先写"必须恒为 0"，实跑后是 3，断言错误，此处更正。
  SELECT COUNT(*) FROM recipe WHERE is_light=1 AND category IN ('主食','面食');
  -- 实际 = 3（米粥25min / 银耳莲子粥25min / 牛奶粥30min）
  -- 这 3 道是「粥」，is_light=1 是**对的**（粥本来就清淡），属于合法共存，不是脏数据。
  -- 所以"恒为 0"这个断言本身是错的 —— 粥天然同时是「清淡」和「主食」。

  -- 真正该守的是这条（≤20min 口径下必须为 0，目前确实是 0）：
  SELECT COUNT(*) FROM recipe
  WHERE is_light=1 AND category IN ('主食','面食') AND COALESCE(cook_minutes,0)<=20;   -- = 0 ✅
  ```
  **断言改为**：改动前后该值**不得增加**（基线 0）。一旦 >0，说明有人把「主食/面食」整体刷成了 `is_light=1`，
  后果是白天说"想吃清淡的"会拿到蛋炒饭/拌面 —— 这才是要防的事。
  注意 3 道粥都在 ≤20min 池外（25/25/30min），**不参与夜宵**，所以它们存在不影响任何线上行为。

#### 修订一：指标定义 —— `relaxed=true` 占比不可用

现状 `_pick()`（L513-560）是"**pool 为空才置 `relaxed=True`**"的 4 级 if 链。而 V1.2.0 要求改成 **`pool_size < 8` 就提前放宽**（§5.2 第 2 条）。
**触发条件从 `=0` 放宽到 `<8`，触发频率必然上升** → 上线后 J3 数字会"变差"，但那是**定义变了，不是数据变差**。原稿的"18.9% → ≤8%"前后不可比。

**⚠️ 前置：阈值数字脱离 ladder 就没有意义。** roadmap-planner 的初稿用「≥3」，是基于"6 级 ladder（1=松tools、2=松meal_slots、3=松cook_cap）"；本文推荐的是"5 级 ladder（不加 tools/meal_slots 两级，因为按 §3.1 覆盖率 <30% 不做硬过滤）"，此时「松 cook_cap」是第 1 级。**两个 ≥3 指代的东西完全不同**，这是第二次定义漂移的风险源。**必须先钉 ladder，再谈阈值。**

**推荐 ladder（5 档，与现有 `_pick()` 保持语义一致）**：

```
0 = 未放宽
1 = 松 cook_cap（时间上限）        ← 现有代码在这一级置 relaxed=True
2 = 松 category 品类打散           ← 多样性开始受损的临界点
3 = 松 main_ingredient 两餐不重样
4 = 松 no_repeat_days 近 7 天不重复 ← 安全线，理论最深
```

#### ✅ 定稿 ladder（team-lead 2026-09-23 裁决：**5 档，不留空位**）

```
RELAX_LEVEL_NONE            = 0   未放宽
RELAX_LEVEL_COOK_CAP        = 1   松 cook_cap（时间上限）
RELAX_LEVEL_CATEGORY_SPREAD = 2   松 category 品类打散      ← 「开始牺牲多样性」
RELAX_LEVEL_MAIN_INGREDIENT = 3   松 main_ingredient 两餐不重样
RELAX_LEVEL_NO_REPEAT       = 4   松 no_repeat_days 近 7 天不重复  ← 安全线
```

**`tools` 与 `meal_slots` 都不是档位**（也不进过滤链）——依据即本文 §1 覆盖率数据：`tools` 18.2%（严格语义天花板 31.1%）、`meal_slots` 21.9%（且语义错：热干面/陕西油泼面/煮泡面加蛋被标成 `["breakfast","lunch"]`），**两者都低于 §3.1 的 30% 硬过滤门槛**。

**🔒 冻结规则（可比性第三重保障）**：
> **5 档 0–4 一旦发布即冻结；后续如需新增维度，只能追加到 5 及以上，不许插入中间。**

（不采纳"预留空位保可比性"：`1=tools` 这种背后没东西的空档，正是本次 `cook_cap` 从第 3 级漂到第 2 级的成因——**留空位就是埋下一次漂移**。）

**可比性三重保障**：① 常量名引用（禁止写死数字）+ ② `candidate_count` 存放宽前池子可事后重算 + ③ 档位只追加不插入。

#### ✅ 定稿判据（5 档取值）

```
J3  = relaxed_level >= RELAX_LEVEL_CATEGORY_SPREAD (=2)   全时段 ≤8%，夜宵降档 ≤20%
J3b = relaxed_level >= RELAX_LEVEL_COOK_CAP        (=1)   观测，不设目标
J3c = relaxed_level >= RELAX_LEVEL_NO_REPEAT       (=4)   ≤1%，任一单日 >0 立即告警
```

- **为什么用 `CATEGORY_SPREAD` 不用 `COOK_CAP`**（team-lead 采纳本文版本）：`≥COOK_CAP` 会把"松时间上限"这个**天天发生、对用户近乎无损**的动作算进分子，J3 会变吵。旧基线 18.9% 已承认不可比，**用 J3b 桥接，不做数字对齐**。
- **J3c 是唯一对触发阈值变化不敏感的指标**：无论水位线设 `<8` 还是 `=0`，走到第 4 级都意味着池子真的空了。而 `no_repeat_days=7` 是用户最不能忍的那条线。
- **落地要求**（已下发 dev-engine-relax）：常量在 `shared/decide.ts` 同源导出，`test_decide_parity.py` 加断言钉死双端相等；**J3 一律按常量名引用，禁止写字面量**。

#### 修订二：依据 —— "夜宵 80%" 是压测伪影，**我撤回**

原稿写"夜宵 12/15 = 80%"并以此作为夜宵目标依据。**这个数字不能用**，理由正是我自己 §2.5 警告过的：

15 条 late_night 决策集中在 **2026-09-22 21:10–22:27 的 77 分钟内**，而夜宵池只有 16 道 —— **换谁连点 15 次都会抽干**。这 80% 测的是"压测脚本点了多少次"，不是"数据够不够"。**我用压测数据当行为证据，与自己在 §2.5 的声明自相矛盾，撤回。**

**改为以结构性大小定目标**（这才是可验证的客观事实）：

| 口径 | 道数 |
|---|---:|
| `is_light=1` | 35 |
| `is_light=1` ∩ ≤20min | **16** |
| `is_light=1` ∩ ≤15min | **16**（两档相等：现有轻食菜没有落在 16–20 区间的） |
| 单会话可支撑"换一个"次数 | 池大小 − 1 = 18 |

- **J3-夜宵 = `relaxed_level >= RELAX_LEVEL_CATEGORY_SPREAD`（= 2）≤ 20%**（比全时段 8% 放宽，因池子客观上小）
- ~~配套扩容验收：`is_light=1` 35 → ≥50 道~~ → **已作废**（roadmap-planner 已撤）。
  **原因：夜宵问题的真因不是池子小，是 `is_light` 把主食/面食筛掉了**——库里 ≤15min 的主食/面食有 18 道但 `is_light=1` 的 **0 道**，**新补的菜照样会被 `is_light` 筛掉**，扩池无效。
  **替代**：R-24 品类白名单口径修正，夜宵池 **16 → 45**（≤15min 34），**纯规则、零数据改动**。
  - 45 的依据（可推导，非拍脑袋）：`random_min_choices=3` + `random_band=5.0` → 抽签池需 ≥8 才不显得横跳；再留 7 天不重复余量（7 天 × 1 餐 = 7 道），**8 + 7 = 15** 是单夜底线；极限压测（忌 辣+鸡+蛋 + 已吃 12 道）后仍需 ≥20，反推原始池 ≈ 45。

#### 修订三：新旧定义的换算映射（M7 基线报告用）

**先说硬约束**：现有 `_pick()` L521-535 里 `relaxed = True` **只在"松 cook_cap"那一级置位一次**，之后无论松到多深都不再改。所以：

| 旧体系 | 新体系（**定稿 5 档 ladder 0–4**） | 可比性 |
|---|---|---|
| `relaxed=False` | `relaxed_level = 0`（`RELAX_LEVEL_NONE`） | **严格等价** |
| `relaxed=True` | `relaxed_level ≥ 1`（`RELAX_LEVEL_COOK_CAP`） | **总量等价**（旧代码只在松 cook_cap 时置 True） |
| — 无对应 — | `relaxed_level ≥ 2`（`RELAX_LEVEL_CATEGORY_SPREAD`） | 新增，需新采 |
| — 无对应 — | `relaxed_level = 4`（`RELAX_LEVEL_NO_REPEAT`） | 新增，红线 |

**已作废的旧对照表**（6/7 档写法，仅为留痕，勿再引用）：

| 语义 | ~~6 档~~ | ~~7 档~~ | **定稿 5 档** |
|---|---:|---:|---:|
| 等价于旧 `relaxed=True` | ~~≥3~~ | ~~≥3~~ | **≥1** |
| "多样性开始受损"（J3） | ~~≥4~~ | ~~≥4~~ | **≥2** |
| 红线（松 7 天不重复，J3c） | ~~=6~~ | ~~=6~~ | **=4** |

🔴 **两条必须写进 M7 的警告**：
1. **旧基线的 18.9% 无法拆解成分级分布** —— payload 里只有一个 bool，没有记录"松到了哪一级"。所以旧数据只能提供**总量**，提供不了深度分布。**新体系的分级基线必须从零开始采。**
2. **18.9% 本身是压测数据，不可作基线**（§2.5）。即使用上面的映射换算，换出来的也是压测数字。**换算表的用途是"定义对齐"，不是"拿到可用基线"。**

**关于 R-10 前后的可比性，结论要说实话**：**没有任何一个"放宽发生率"指标在 R-10 前后严格可比**，因为触发条件本身从 `=0` 变成了 `<8`。可分三档看待：

| 可比性 | 指标 | 理由 |
|---|---|---|
| **严格可比** | 用 `candidate_count` **重算** | `=0` 语义就是 `candidate_count=0`，有此列即可事后还原旧口径 |
| **近似可比** | `relaxed_level = 4`（最深一级） | 从 `<8` 到 `=0` 之间还有中间地带，最深一级受水位线影响相对最小 |
| **不可比（只观测）** | `relaxed_level ≥ 1` | 等价于旧总量，但水位线会直接推高它 |

#### 修订四：可比性靠数据兜底，不靠约定

"禁止跨定义对比"是约定，约定会被忘。**改成让重算成为可能**：R-07 已要求记录 **`candidate_count`**（候选池大小）。有了它，事后永远可以重算"若按 `=0` 语义这次会不会放宽"——因为 `=0` 就是 `candidate_count = 0`。
→ **`candidate_count` 在 R-07 里必须标成必需列**，并把"重算口径"写进基线报告方法段。

#### 修订五：J3 阈值**不要写字面量，要写语义常量**（2026-09-23 补）

**问题**：核对 PRD 与 roadmap 后发现，ladder 档数与 J3 阈值在三方文档里不一致：

> ✅ **本冲突已由 team-lead 2026-09-23 裁决解决：统一为 5 档 0–4，J3 = ≥2。** 下表留痕，勿再引用。

| 来源（历史） | ladder 档数 | J3 阈值 | 现状 |
|---|---|---|---|
| **team-lead 裁决** | **5 档**（`tools`/`meal_slots` 都不进过滤链，R-11 改软惩罚） | **≥2** | ✅ **采纳，已落地**（`MAX_RELAX_LEVEL = 4`，`decision_service.py` L94） |
| PRD | 6 级（`1=tools, 2=meal_slots, 3=cook_cap, 4=category, 5=main_ingredient, 6=no_repeat`） | ≥3 | ❌ 作废，需改为常量引用 |
| roadmap | 7 级枚举 0–6（同上 + level 0） | ≥4 | ❌ 作废，需改为常量引用 |

**2 / 3 / 4 曾指代同一语义——"从开始牺牲多样性那一档起算"（即松 `category` 打散）——只因档数不同而数字不同。**
若落地 5 档而文档仍写 ≥3，则 `>=3` 在 5 档下等于"松 main_ingredient 不重样"，**同一条 SQL 量的是两种东西**，J3 失效。这是**第三次定义漂移**——**已由"常量名引用 + 冻结规则"终止**。

**解法（与修订四同思路：让定义靠数据/常量，不靠约定）**：

```
J3  = decision_log.relaxed_level >= RELAX_LEVEL_CATEGORY_SPREAD  占比 ≤8%
J3c = decision_log.relaxed_level >= RELAX_LEVEL_NO_REPEAT        占比 ≤1%（任一单日 >0 立即告警）
J3b = decision_log.relaxed_level >= 1                            观测，不设目标
J3-夜宵 = relaxed_level >= RELAX_LEVEL_CATEGORY_SPREAD AND meal_slot='late_night'   ≤20%
```

`RELAX_LEVEL_CATEGORY_SPREAD` / `RELAX_LEVEL_NO_REPEAT` 由 ladder 实现侧导出：

| ladder | `RELAX_LEVEL_CATEGORY_SPREAD` | `RELAX_LEVEL_NO_REPEAT` |
|---|---:|---:|
| 7 档（tools + meal_slots 都在） | 4 | 6 |
| 6 档（仅 meal_slots 在） | 3 | 5 |
| **5 档（都不在）** | **2** | **4** |

→ **ladder 以后加档/减档，J3 的 SQL 一行不用动。** 只钉"枚举"不够，必须钉**"枚举 ↔ 语义常量"的映射**。

#### 修订六：R-24（夜宵口径修正）的验收要分两层，别一起推迟

roadmap-planner 指出"R-24 与 R-10 改同一个 `_passes()`，必须同一人持有、同一 PR"，**我接受**；并补充：

| 验收层 | 内容 | 是否依赖 R-10 |
|---|---|---|
| **数据侧** | 池 = 45（≤15min 34）；忌 辣+鸡+蛋 + 已吃 12 道 剩 ≥20；`is_light=1 ∩ 主食/面食 ∩ ≤20min` = 0 且不得增加 | ❌ **纯 SQL，现在可验** |
| **行为侧** | 夜宵档 `relaxed_level` 分布 / J3-夜宵 ≤20% | ✅ 依赖 R-10 的 `relaxed_level` 上报 |

→ 写进 M2 完成定义时**两层分开**，避免数据侧验收陪着等引擎。

#### ⚠️ 附带发现：夜宵池与"剔除非菜品"是耦合的**（⚠️ 本段数字已过期，仅保留推理逻辑）**

```sql
-- 剔除 52 道非菜品前
(is_light=1 OR meal_slots LIKE '%late_night%') AND cook_minutes<=15  →  19  ✅
is_light=1 AND cook_minutes<=15                                     →  16
-- 剔除后（fix-non-dish 的 A+B 档）
(is_light=1 OR meal_slots LIKE '%late_night%') AND cook_minutes<=15  →  14  ⚠️
is_light=1 AND cook_minutes<=15                                      →  11  🔴 跌破 12 道闸门
```

**若先删非菜品、再把口径收成 `is_light` only，夜宵池会掉到 11 道。**
→ **顺序必须规定为：先扩池 → 再删非菜品 → 最后才允许收紧**。三者不能各自独立排期。

> **⚠️ 数字过期说明（2026-09-23）**：上表跑于迁移 0017（`is_dish`）落地**之前**，且当时还没提出品类白名单。
> **现行正确数字**（`is_dish=1` 已生效、白名单已定）：
> - `is_light=1` ∩ ≤15min = **16**（不是 11）
> - `is_light=1 OR category IN ('主食','面食')` ∩ ≤15min = **34**
> - 同上 ∩ ≤20min = **45**
> - 极限压测（忌 辣+鸡+蛋 + 已吃 12 道）：旧口径 **4** / 新口径 **20**
>
> **"先扩池"这一步已被推翻**：扩池无法解决该问题（新补的面照样被 `is_light` 筛掉），
> 正确修法是品类白名单（R-24）。**硬顺序修正为：删非菜品 → R-24 口径修正 → 最后才允许收紧 R-22。**

### 4.7 埋点载体现状：`event` 表已有真实数据（但有一个洞）

```sql
SELECT event_name, COUNT(*) FROM event GROUP BY event_name ORDER BY c DESC;
SELECT app_version, COUNT(*) FROM event GROUP BY app_version;
```

```
91 行 | 2026-09-12 ~ 09-18 | 4 个用户 | platform = weapp
replace_item 52 / login 12 / generate_menu 10 / logout 9 / recognize_open 4
mark_cooked 2 / invite_copy 1 / order_open 1

app_version:  unknown → 91 条（100%）
```

**三条结论**：

1. **埋点链路是通的，且有真实（非压测）数据** —— 与 `decision_log` 的压测数据不同，`event` 表这 91 行可信度更高，可以作为"现有埋点能力"的证据。
2. 🔴 **`app_version` 100% 是 `"unknown"`** → **灰度开关（R-16）在埋点侧分不出 v1.1 / v1.2**，开关能切但切了无法度量。**修 `app_version` 打标必须作为 R-16 的硬前置**；并建议加一列 `layout_version`（服务端灰度值，比 app_version 更直接，因为同一 app 版本可能落在两组）。
3. **`mark_cooked` 事件已存在**（2 次）→ 修正原报告"决策→开做这一跳完全不存在"的说法：准确表述是**决策维度没有**（`DecideBoard` 无「开始做」按钮），但**菜单维度有**。R-06 应复用这个事件名，不要新造。

**时间口径约定**（与 roadmap-planner 达成一致）：
- **时间分桶（日/餐次/小时）用 `received_at`**（服务端时间，不受客户端时钟影响）
- **会话内事件排序用 `ts`**（批量上报时同批 `received_at` 几乎相同，无法分先后；而 `ts` 的批内相对顺序是对的）
- `session_id` 的 30 分钟失效：窗口用 `received_at` 算，窗口内排序用 `ts`
- **加时钟偏移兜底**：`|ts - received_at| > 24h` 判为客户端时钟异常 → 整条回退 `received_at`，并打 `event_clock_skew` 便于监控

**附加判据（数据侧，不是用户侧）：**

| # | 判据 | 目标 | 依据 |
|---|---|---|---|
| ~~**J6**~~ | ~~`home_filter_tap` 中 `result_count = 0` 的占比~~ | — | ❌ **双重作废**：① 判据本身恒真不可证伪；② 数据源 `home_filter_tap` 已于 2026-09-23 从事件清单删除（见下方 E2）。**由 J6' 取代** |
| ~~**J7**~~ | ~~`home_filter_tap` 中 `result_count < 8` 的占比~~ | — | ❌ **作废**，同上。**由 J7' 取代**（`candidate_count < 8`） |

> **2026-09-23 变更（requirement-analyst / PRD v1.6）**：埋点事件数 12 → 11，**删除 `home_filter_tap`**。
> 原因：J6/J7 作废后它没有消费方；实现侧唯一挂点在冰箱快选 chip 上，语义是「录入食材」不是「筛选」。
> **口径纪律**：实现侧若继续打点不算违规，但**任何报表/判据都不得再以它为数据源** —— 它挂的是「录入食材」，
> 拿它算「筛选漏斗」会把录入行为误读成筛选行为，方向性错误。本表 J6/J7 已在文档内全部摘除，
> 判据迁移到 J6'/J7'（数据源 `decision_log.candidate_count`，见 §4.6 / 附录 E2）。

### 3.4 ✅ 与用户研究结论的交叉验证（重要）

`user-research-decision-mind.md` 从"用户心智"得出的结论，与本次从"数据覆盖率"得出的结论，**在同一批维度上独立收敛到了同一个答案**：

| 维度 | 用户研究怎么说（心智） | 数据怎么说（覆盖率） | 是否一致 |
|---|---|---|---|
| 餐次 / 现在几点 | Q1 系统推断，**零交互**，"不该出现请选择餐次" | `meal_slots` **20.5%**，只能加分不能过滤 | ✅ **完全一致** |
| 多久能吃上 | Q3 硬约束，最先被放宽 | `cook_minutes` **100%**，可硬过滤 | ✅ 一致 |
| 家里有什么 | Q4 硬约束，零交互 | 食材侧 **94.2%**，可硬过滤（但库存侧 0 行，缺录入入口） | ✅ 一致 |
| 忌口 / 不吃什么 | Q5 唯一永不放宽的安全线 | 食材侧 94.2%，23 道无食材行的菜应默认排除 | ✅ 一致 |
| 做 / 买（模式闸门） | Q2 全漏斗最大流失点 | `advice` 逻辑已存在，可复用 | ✅ 一致 |
| 去重 / 最近吃过 | "否决反射，**完全交给引擎，不进 UI**" | `main_ingredient` 232 值未归一，硬规则大部分匹配不上 → **必须在引擎侧修，不能靠 UI** | ✅ 一致 |
| **花多少钱** | 加分题，"首页一个都不要出现" | 食材有价 **8.6%**，352/396 道菜缺价 **[342] 300/342 = 87.7%** | ✅ **完全一致** |
| **几个人吃** | 加分题，"首页一个都不要出现" | recipe 侧 **无 servings 字段（0%）** | ✅ **完全一致** |
| **厨具条件** | 加分题，"首页一个都不要出现" | `tools` **18.2%** 且词表与 household 不通 | ✅ **完全一致** |

> **这条交叉验证是本次评估里最值得对主理人强调的一条：**
> **"用户不想被问" 的题，恰好就是 "数据撑不住" 的题。**
> 也就是说——**首页少摆格子这件事，不需要在"体验"和"数据可行性"之间做权衡，两边都指向同一个答案。**
> 反过来说，如果有人主张"预算/人数/厨具/餐次"要上首页，他需要**同时**反驳用户心智和数据覆盖率两件事。

---

## 5. 数据风险与兜底建议

### 5.1 风险清单（按"会不会让用户当场看到空页面"排序）

| 级别 | 风险 | 实测数据 | 后果 |
|---|---|---|---|
| 🔴 P0 | **候选池有 61 道非菜品，已推荐 18 次** | 调味品8/饮品23/甜品19/半成品加工9；decision_log 实证 18/190 = **9.5%** | 用户屏幕上出现过**「油泼辣子」「炸串酱料」「油酥」「B52轰炸机」「金汤力」**。**已经发生的事故，不是风险** |
| 🔴 P0 | **时令=春 / 秋 → 0 道菜** | `season LIKE '%spring%'` = **0**，`'%autumn%'` = **0** | 春秋两季点"当季"**直接空页面**。这是唯一会 100% 复现的空结果 |
| 🔴 P0 | **夜宵候选池枯竭** | `is_light=1` 35 道，∩ ≤20min **16 道**；日志实测夜宵 **80% 触发放宽** | 夜宵用户连点几次就看到重复菜，理由变成"可选项不多了，就它吧" |
| 🟡 补充 | **深夜阈值 20→15min 不会缩小池子** | 实测 `is_light ∩ ≤15` = **16**，`is_light ∩ ≤20` = **16**，两档相等（现有轻食菜的 cook_minutes 只落在 ≤15 档，没有 16–20 区间的） | ⚠️ 这条**推翻**了"收紧到 15min 会抽干池子"的担心：阈值侧无风险。但 **16 道本身太小**，补池仍是必须的 |
| 🔴 P0 | **早餐 ∩ ≤15min = 7 道**；**午餐 ∩ ≤30min ∩ 荤菜 = 6 道** | §1.6 | 早上/中午"快速 + 对品类"必然筛空 |
| 🟠 P1 | **`tags` 里"下饭"占 251 道（63%）** | §1.3 | 拿 tags 做筛选 ≈ 没筛。用户勾了"下饭"，结果和没勾一样 |
| 🟠 P1 | **`tools` 与 `household.kitchen_equipments` 词表不通** | recipe=`pot/steamer/oven/air_fryer`；household=`灶台/微波炉/空气炸锅/蒸锅/烤箱/电饭煲/压力锅` | 若按"只出我能做的菜"硬过滤，会把 324 道无 tools 标注的菜**全部误杀**（他们只是没标注，不是做不了） |
| 🟠 P1 | **预算维度：`ingredient.reference_price` 只有 8.6%** | 352/396 道菜缺价 **[342] 300/342 = 87.7%** | `score_budget`(15 分) 静默失效；若首页做"预算 ≤X"筛选，会大量误杀/误留 |
| 🟠 P1 | **`main_ingredient` 232 个值未归一** | 猪肉/五花肉/猪五花肉/带皮五花肉各算各的 | "连续两餐不重样"（−40 分，最重的惩罚）大部分时候匹配不上 → 用户连着两顿吃猪肉，系统不知道 |
| 🟠 P1 | **`cuisine` 词表污染** | 396 道里只有 2 道能对上真实菜系（`cuisine` 非空 318/342 = 93.0%，但全是"荤菜/早餐"这类分类词，**没有一个是真菜系**） | ~~20 分权重失效~~ → ✅ 权重已归零；**但数据侧未修**：列里仍是分类词表，理由文案仍会泄漏"换换口味，试试早餐"（文案侧已由 fix-cuisine-weight 单独修）。真菜系需等凌晨 LLM 富集回填 |
| 🟡 P2 | **`calories` 口径存疑** | 127 道 ≥800 kcal，中式馅饼 1265 | 若按 calories 做"饿的程度"，会把馅饼推给"很饿"的人、把汤推给"垫一口"的人，方向可能是对的但阈值全错 |
| 🟡 P2 | **`consumption_record` 0 行 / `fridge_inventory` 0 行** | §1.5 | "最近吃过没"只能靠"推荐过什么"代理；"家里有啥"没有用户侧数据 |
| 🟡 P2 | **`protein_g/carb_g/fat_g` 6.1%** | §1.3 | `/api/today` 的 nutrition 块会算出接近 0 的蛋白质，首页若展示营养会很难看 |

### 5.2 兜底建议

#### (1) 分级放宽阶梯（✅ 定稿 **5 档 0–4**，且每级都要上报）

> 本节原稿写的是"4 级 → 扩到 6 级（含 tools / meal_slots）"，**已被 team-lead 裁决取代**：`tools`(18.2%) 与 `meal_slots`(21.9%) 覆盖率均低于 §3.1 的 30% 硬过滤门槛，**不进过滤链、不做档位**。

**定稿顺序**（按用户可感知度从低到高）：

| level | 常量 | 放行内容 | 性质 |
|---:|---|---|---|
| 0 | `RELAX_LEVEL_NONE` | 未放宽 | — |
| 1 | `RELAX_LEVEL_COOK_CAP` | 松 `cook_cap`（用户最不在意多花十分钟） | 廉价 |
| 2 | `RELAX_LEVEL_CATEGORY_SPREAD` | 松 `category` 打散 | **多样性开始受损（J3 起算点）** |
| 3 | `RELAX_LEVEL_MAIN_INGREDIENT` | 松 `main_ingredient` 不重样 | 多样性 |
| 4 | `RELAX_LEVEL_NO_REPEAT` | 松 `no_repeat_days` 近 7 天不重复 | **安全线（J3c 红线）** |

- **每一级都要把 `relaxed_level` 写进 `decision_log` 和 `decide_result_shown` 事件**，否则只知道"放宽了"，不知道"放宽到哪一级"，无法定位是哪个维度在卡；
- **永远不放宽的**：忌口/过敏（现状正确，保持不变）；
- **🔒 冻结规则**：0–4 发布即冻结，后续新增维度**只能追加到 5 及以上，不许插入中间**。

#### (2) 候选池水位线：`< 8` 就提前放宽，不要等到 `= 0`

现状是"池子空了才放宽"，用户已经看到了一次失败。建议改成**水位线制**：

- `pool_size < 8` → 直接跳下一级放宽，并打 `decide_empty_pool` 事件（带 `pool_size` 和 `filters_snapshot`）；
- `pool_size = 0` → 必须打 P0 告警级事件，视为缺陷。

依据：`random_min_choices=3` + `random_band=5.0` 意味着抽签池至少要 8 道左右才能让"换一个"看起来不像横跳。

#### (3) "不限制"必须是显式选项，不能靠 NULL 表达

`dish_rules.py` 的设计原则是"判断不了就返回 None（不限制）"，这个原则在数据层是对的，但**到了 UI 层必须变成显式的一颗按钮「随便/不挑」**。
否则用户会以为"我没勾 = 系统没考虑"，而实际是"系统不知道"。
特别是 `meal_slots` / `tools` / `season` 这三个覆盖率 <25% 的维度——**UI 上应该默认选中「不限」，而不是默认什么都不选**。

#### (4) 首页格子按"覆盖率阈值法则"分级上（§3.1）

| 档 | 维度 | 首页形态 |
|---|---|---|
| **可硬过滤**（≥90%） | 多久吃上（cook_minutes）、忌口、做不做 | 主格子，勾选即生效 |
| **硬过滤 + 放宽兜底**（70–90%） | 荤素（meat_type 71%）、辣度（spice 100%）、家里有啥（食材侧 94%） | 主格子，配 `relaxed_level` 上报 |
| **只加分不筛选**（30–70%） | 餐次（**21.9%**（`is_dish=1` 口径；旧稿 20.5% 为全表口径）→ 由钟点自动定）、厨具（18.2% → 映射后加分）、时令（7.6% → 人工内容位） | **不做勾选器**。餐次自动判定并在卡片上显示"晚餐"；厨具做成"有的加分，没有不杀"；时令做运营位不做筛选 |
| **本版不上** | 预算（8.6% 有价）、几个人（菜侧 0%）、当季（春秋 0 道） | V1.3 再上 |

#### (5) 三个"成本极低、收益极高"的修复（建议排在首页重构之前做）

1. ~~把 `score_cuisine` 从 20.0 临时降到 0~~ → **✅ 已落地**（`config.py` L148 = 0.0）。
   **剩余待办（V1.3）**：`cuisine` 列数据清洗 —— 真菜系由凌晨 LLM 富集任务标注回填；回填后把权重恢复 20.0，并**同步 `config/default.yaml` 与 `shared/decide.ts`**（三处必须一起改，否则双端打分口径分叉）。
   现在它 99.5% 不命中，却在静默地占用一个高权重位——**"假装在打分"比"不打这个分"更危险**，因为它会让人以为偏好系统在工作。
2. **`reason_service` 增加词表白名单**：`cuisine ∈ {荤菜, 素菜, 主食, 早餐, 半成品加工, 调味品, 饮品, 甜品}` 时，不生成"换换口味，试试X"文案，改用 category 的安全文案（如"来点荤菜，换个节奏"）。**这是用户可见的缺陷，改一行就能好。**
3. **重跑一次 `guess_meat_type()`**：`none` 只有 10 道 vs 素菜 74 道，说明漏判严重。纯规则、零成本。
4. **【最高优先】把 61 道非菜品剔出候选池**：已真实推荐出去 18 次（油泼辣子/炸串酱料/B52轰炸机/金汤力）。用源分类黑名单纯规则剔除即可，不需要模型。**这一条的严重度高于上面三条**——前三条是"效果差"，这一条是"用户看到荒谬结果"。

#### (6) 埋点先行

**建议 V1.2.0 拆成两步走**：
- **第 1 步（1–2 周）**：只上埋点（`decision_event` 表 + `decision_log` 增列 + 前端 `session_id`/`decide_reject`），不改首页。跑出真实基线。
- **第 2 步**：再上首页重构，用第 1 步的基线校准 J1–J5 的目标值。

理由：现在**没有任何可信的行为基线**（190 条全是压测，85.3% 的采纳反馈缺失）。没有基线就改首页，事后无法归因——是首页改好了，还是数据补齐了，还是用户变多了，分不清。

> ⚠️ **本条已被 requirement-analyst 否掉**（PRD §11-Q3）：他的反驳成立 —— "没有流量 ⇒ 这两周什么都收集不到"。
> 替代方案是他的 **R-16 灰度开关** + "J3/J6/J7 是纯引擎指标、DCR 先只采集不设目标"。我接受。
> **保留的一点保留意见**：J1（决策完成率 ≥50%）是**绝对达标线**而非"提升目标"，它不需要历史基线也能判，不应被推迟到第 2 步。

#### (7) 🔴 `meal_slots` 硬过滤 vs 软惩罚（2026-09-23 补，决定 R-10 ladder 档数）

**覆盖率实况**（`is_dish=1`，342 道）：

| meal_slots | 道数 | 占比 |
|---|---:|---:|
| `NULL` | **267** | 78.1% |
| `["breakfast","lunch"]` | 46 | 13.5% |
| `["dinner"]` | 24 | 7.0% |
| `["dinner","late_night"]` | **5** | 1.5% |
| **有值合计** | **75** | **21.9%** |

→ 全库**只有 5 道菜**带 `late_night`。按 §3.1 阈值法则（<30% 只能加分、不该上 UI），**21.9% 做硬过滤本就超线**。

**决定性对照：夜宵池（R-24 白名单 + ≤20min）**

| 口径 | 夜宵池 |
|---|---:|
| 不做 `meal_slots` 硬过滤（软惩罚） | **45** |
| **做 `meal_slots` 硬过滤** | **28** 🔴 |

**被删掉的 17 道正是"深夜想吃碗面"的全部答案**：老干妈拌面、葱油拌面、酱拌荞麦面、麻油拌面、滕州菜煎饼、茄子肉煎饼、莴笋叶煎饼、番茄鸡蛋面、半成品意面、基础牛奶面包、意式肉酱面、汤面、热干面、煮泡面加蛋、西红柿鸡蛋挂面、陕西油泼面、麻辣减脂荞麦面。

→ **硬过滤会把 R-24 刚救回的东西原封不动删回去，两个需求互相抵消。**
→ **且是静默失败**：28 > `<8` 水位线 → **不触发放宽**（放宽才会捞回这 17 道）→ 用户永远看不到面，J3c 也照不出来。这是三方案里唯一"错了但没人知道"的失败模式。
→ 标注质量也存疑：热干面、陕西油泼面、煮泡面加蛋被标成 `["breakfast","lunch"]`。**`meal_slots` 不只是覆盖低，语义也是错的。**

**硬过滤下四时段放行量（未叠忌口/7天不重复）**：breakfast 313 / lunch 313 / dinner 296 / **late_night 272**。
→ 272 道再叠最狠忌口（~40%）+ 已吃 12 道仍有 ~150 道 ⇒ **「四时段各 20 次决策 `result_count=0` = 0」是恒真命题，不可证伪，信息量为零**。A/B 两方案都会绿，不能用它论证"必须保留硬过滤"。

**替代验收（可证伪，复用 R-07 必需列 `candidate_count`）**：
```
J6' = decision_log.candidate_count 按 meal_slot 分组的 P10     夜宵档 P10 ≥ 8
J7' = candidate_count < 8 的占比，按 meal_slot 分档             ≤5%
```
→ 旧口径夜宵池 16、叠忌口后 4 ⇒ P10 <8 **红灯**；新口径 45→20 ⇒ **绿**。**这条抓得住我们这次修的 bug**，而"0 空结果"抓不住。

**三方案对照**

| | **A · 软惩罚** | **B · 硬过滤** | **C · 硬过滤 + 纯规则回填** |
|---|---|---|---|
| 数据改动 | **零** | 零 | 一次纯规则回填（26 道追加 `late_night`） |
| 夜宵池 | **45** ✅ | **28** 🔴 | **45** ✅ |
| 静默失败 | 否 | **是** | 否 |
| 四时段验收 | 需换成 J6'/J7' | 恒真，无效 | 恒真，无效 |

**C 方案回填规则**（若仍要硬过滤）：`category IN ('主食','面食') AND cook_minutes<=20 AND is_dish=1` → 给 29 道中的 **26 道**（3 道已有，已核实）**追加** `late_night`。纯规则、不涉 LLM、追加语义不影响白天。

> **⚠️ C 已出局（roadmap-planner 的反对理由比我的更强，我接受）**：
> **C 的回填条件与 R-24 的白名单是同一条规则** —— C 是"用一次数据迁移去模拟 R-24 已经在逻辑层实现了的东西"。
> 成本更高、**可逆性更差**（白名单改一行就能回退，回填要再迁移一次），而 R-24 已足够解决"深夜有面"。
> （我原先的理由只是"回填后仍 29.5% < 30% 门槛"，那是在说"还是不够格"；他这条是在说"**这件事根本不需要做第二遍**"。）

**结论：推荐 A（软惩罚），B/C 均出局。**

#### (8) 🔴 `meal_slots` 的标注语义：它基本是 `category` 的一次重新编码（A 方案落地前必读）

把三种取值按 `category` 拆开，`is_dish=1`：

| meal_slots | 道数 | 实际构成 |
|---|---:|---|
| `["breakfast","lunch"]` | 46 | **面食 21 + 主食 19 + 荤菜 6**（主食/面食占 87%） |
| **`["dinner"]`** | 24 | **汤羹 24，100%，零例外** |
| `["dinner","late_night"]` | 5 | — |
| `NULL` | 267 | — |

→ 全库 `is_dish=1` 的汤羹**正好 24 道**，且**全部**被标成 `["dinner"]` —— **`meal_slots` 对汤羹是 100% 冗余于 `category`**。
主食/面食共 70 道，其中 40 道（**57%**）被标 `["breakfast","lunch"]`，余下 27 道 `NULL`、3 道 `dinner/late_night`。

→ **这个字段不是"这道菜适合哪个时段"的判断，而是 `category` 的重新编码，独立信息接近于零。**
这也解释了它做硬过滤为什么危险：**它在做一次隐蔽的、错误的 category 过滤**。

**由此推出 A 方案（软惩罚）的副作用：晚饭档主食/面食被系统性降权**

| | 数量 | 说明 |
|---|---:|---|
| 晚饭档被软惩罚减分（有值且不含 `dinner`） | **46** | 其中 **40 道是主食/面食** |
| 主食/面食总数 | 70 | 自然占比 70/342 = 20.5% |
| **晚饭档被降权的主食/面食** | **40** | **57%** |
| 不受影响（`NULL` 27 + `dinner/late_night` 3） | 30 | 43% |

→ 晚饭吃面/炒饭在中文语境完全正常，但 **57% 的主食/面食会在最大的一餐被降权** → 晚饭推荐系统性偏荤菜/汤羹。
**这比夜宵那 17 道更麻烦**：夜宵池小、可用白名单全豁免；**晚饭是主战场，40 道是结构性偏差，开不了白名单**（给晚饭也开"面食白名单"就等于 R-11 在晚饭完全失效）。

**三条落地约束（已同步 team-lead / roadmap-planner）**：

1. **R-11 软惩罚分值上限 ≤10（建议 8–10）**。
   现有量级参考：加分侧 `score_inventory=25 / cuisine=20 / weather=18 / spice=15 / budget=15`；惩罚侧 `category_penalty_step=25 / main_ingredient_penalty=40 / same_cuisine_penalty=15`。
   给一个 21.9% 覆盖率、且与 `category` 高度冗余的字段 15–25 分不合理 —— **`category` 这个轴已有 `category_penalty_step=25` 在管，R-11 再叠一层是对同一信号二次计价**。
2. **加一条晚饭档回归验收**（可证伪，零新增埋点，`decision_log` 已有 `category` 列）：
   ```sql
   -- R-11 回归: 晚饭档出餐中 主食/面食 占比 ≥ 15%
   -- 自然占比 = 70/342 = 20.5%, 允许软惩罚压低不超过 1/4
   SELECT SUM(category IN ('主食','面食')) / COUNT(*) AS staple_share
   FROM decision_log WHERE meal_slot = 'dinner';
   -- 期望 ≥ 0.15；低于 15% 说明标注偏差通过软惩罚泄漏进了排序
   ```
3. **夜宵豁免照旧**：LATE_NIGHT 命中 `LATE_NIGHT_EXTRA_CATEGORIES` 的候选跳过 R-11 软惩罚（17 道面）。
   两条不冲突 —— 夜宵全豁免，晚饭靠"分值 ≤10 + 回归验收"控住。

**技术债（本期不动）**：`meal_slots` 对汤羹 100% 冗余、对主食/面食 57% 冗余，**独立价值很低**。建议记债评估「该字段是否还有存在必要，还是可由 `category` + 规则派生」。

#### (9) 🔴🔴 通则：`|减分| > random_band` 即为准硬过滤（2026-09-23，代码已落地后复核）

**R-10 / R-11 / R-24 已落地**（dev-engine-relax 实现，本文作者未改任何代码）。复核结果：

| 项 | 位置 | 状态 |
|---|---|---|
| `LATE_NIGHT_EXTRA_CATEGORIES = ("主食","面食")` | L85 | ✅ |
| `POOL_MIN = 8`（水位线） | L91 | ✅ |
| `MAX_RELAX_LEVEL = 4`（**5 档 ladder 0–4**） | L94 | ✅ |
| 夜宵白名单跳过软惩罚 | L750 | ✅ |
| `relaxed_level` + `candidate_count` 落库（记放宽**前**池子） | L280-282 | ✅ |
| **`MEAL_SLOT_MISMATCH_PENALTY = -20.0`** | L101 | 🔴 **有问题，见下** |

**推导**（`_random_band` L683-695，`config.py:137` `random_band = 5.0`）：

设被罚菜原始分 `r`、罚 `P`，池内最优菜未受罚时最优分 `best_raw`。
```
被罚菜进带 ⇔ r - P >= best_raw - band
           ⇔ r     >= best_raw + P - band
而 r <= best_raw 恒成立  ⇒  必须 P <= band
```
→ **任何 `P > 5.0` 的减分，被罚菜 100% 进不了抽签带（唯一例外：最优菜自己也被罚）。**

**晚饭档实况**：342 道中 46 道被罚（有值且不含 `dinner`），296 道不罚 ⇒ 最优分来自未罚的 ⇒ **46 道一次都进不了带**，其中 **40 道是主食/面食**（全库 70 道）⇒ **晚饭档 57% 的主食/面食被实质排除**。

→ **R-11 从硬过滤改成软惩罚，但 `-20` 让它以软惩罚之名行硬过滤之实。**
→ L97-99 注释的判断（"判死就只剩那 81 道——这正是夜宵池上吃过的亏"）完全正确，**只是尺度锚点选错了**：应锚 `random_band`（决定"能不能进带"），不是 `category_penalty_step`（只决定排序先后）。

**⚠️ 我自己给的窗口 `[8,10]` 同样作废**："下限 >5 才能突破随机带"与"上限 ≤10 不足以一票否决"在**减分制下互斥**——"突破随机带"恰好就是"变成硬过滤"。所以 [8,10] 与 -20 只是程度差别，不是性质差别。

**修法：换机制，不是调数字 —— 只加分、不减分**
```python
MEAL_SLOT_MATCH_BONUS = 8.0       # 匹配的菜抬升; +8 > band=5 → 足以改变带的构成（有感知）
MEAL_SLOT_MISMATCH_PENALTY = 0.0  # 不匹配的菜永不排除, 只是相对劣势（软惩罚）
```
→ 不需要窗口，天然规避。

**两条通则（建议写进常量注释）**：
1. **在 `random_band` 抽签机制下，`|减分| > random_band` ⇒ 准硬过滤。** 任何新增减分项先对 `random_band` 自检。
2. **"软偏好"用加分表达，"排除"才用减分表达。**

**现有减分项自检（均 > 5.0，即均为准硬排除）**：

| 减分项 | 位置 | 幅度 | 是否本意即排除 |
|---|---|---:|---|
| `category_penalty_step × count` | L814 | 25 × count（最高 **75**） | 「打散」可能是；但 `count=1` 即 -25 ⇒ **吃过一次荤菜后 179 道荤菜（52%）整类出局**，需确认是否需求本意 |
| `main_ingredient_penalty` | L821 | 40 | 「连续两餐不重样」可能是 |
| `same_cuisine_penalty` | L816 | 15 | cuisine 已归零，基本不触发 |

#### (10) ⚠️ `candidate_count` 会高估可用池 —— J6'/J7' 需要 `band_size`

`candidate_count` 记的是**通过 `_passes` 的池子**（晚饭档 296 道），但打分后真正进入 `random_band` 的只是最高分那一小撮。
→ **J6'/J7' 用 `candidate_count` 会系统性乐观。**
→ 建议 `_random_band` 把 **`band_size`**（返回列表长度）一并落库或至少 debug；它是唯一反映"用户实际在这几道里抽"的数，应列为 R-07 必需列（与 `candidate_count` 同）。

#### (11) 占比类判据的样本量：n=100 不够，且"样本从哪来"要前置

`晚饭档主食/面食占比 ≥15%`（自然占比 20.5%）这条：

| 样本量 | 最小可检出偏移（95%/80%） | 能否检出 20.5%→15% |
|---:|---:|---|
| 100 | ≈ **10pp** | ❌ 5.5pp 落在噪声里，判了等于没判 |
| 300 | ≈ 5.8pp | 勉强 |
| **300–600** | ≈ 4pp 以内 | ✅ |

→ 样本量下限应写 **300**（保守 600），不是 100。

**但更根本的问题**：本阶段**没有流量**（requirement-analyst 已指出），300 条晚饭决策短期内攒不出来。
→ 该判据应走**离线蒙特卡洛**而不是等线上流量 —— 见 §5.2(12)，**实测后该阈值本身已作废**。

→ **通则（与"验收必须可证伪"并列）**：占比类判据要同时满足三条 —— **① 可证伪 ② 样本够 ③ 样本有来源**。缺任何一条都等于没判。

#### (12) 🔴🔴 离线蒙特卡洛实测：**任何二元打分 `|Δ| > random_band` 都会让抽签带塌缩**（减分与加分同罪）

应 roadmap-planner 要求为 O2 定值，跑了离线蒙特卡洛。**结果推翻了我上一轮"只加分不减分"的修法**——加分只是把塌缩方向翻了个面。

**方法（只读，不写库）**：
- 只调 `load_candidates()` / `_score()` / `_random_band()`，**不调 `decide()`**；
  ⚠️ `decide()` 会往 `decision_log` 写行 —— 连续跑 500 次会把 500 行合成数据灌进 J3/J6'/J7' 的分母，
  **重演 190 行压测数据的污染**。这是本方法最重要的一个约束。
- **每次采样从同一份固定历史出发、不写回** → 保证 i.i.d.（roadmap-planner 提出，正确）。
- N = **500**（roadmap 的 ≥200 是下限；要分辨 O1 侧 6pp 的差异需 500）。
- 固定历史两种变体：空历史 / `category_counts={"荤菜":1}`。

**实测（`random_band=5.0`，pool=342，slot=dinner，N=500）**：

| BONUS | PEN | 汤羹%(空历史) | 主面%(空历史) | band | 汤羹%(荤菜x1) | 主面%(荤菜x1) | band | 判定 |
|---:|---:|---:|---:|---:|---:|---:|---:|---|
| **0** | 0 | **5.6%** | **12.8%** | 116 | **14.2%** | **40.0%** | 42 | 基线（R-11 关闭） |
| 2 | 0 | 9.4% | 12.2% | 60 | 23.6% | 33.2% | 25 | 软偏好 ✅ |
| **3** | **0** | **9.4%** | **12.2%** | **60** | **23.8%** | **34.0%** | **25** | **软偏好 ✅ 推荐值** |
| 4 | 0 | 10.8% | 10.6% | 60 | 22.4% | 31.2% | 25 | 软偏好 ✅ |
| **5** | 0 | 10.8% | 10.6% | 60 | 22.4% | 31.2% | 25 | 软偏好（临界） |
| **6** | 0 | **64.8%** | 23.2% | **9** | **77.0%** | 23.0% | **8** | 🔴 **塌缩** |
| 8 | 0 | 64.8% | 23.2% | 9 | 77.0% | 23.0% | 8 | 🔴 塌缩 |
| **12** | **−20** | **64.8%** | 23.2% | **9** | **77.0%** | 23.0% | **8** | 🔴 **当前落地值** |

**塌缩点 = `random_band + 1`（已证明，不是巧合）**：
把 `random_band` 从 5.0 改成 10.0 重跑，塌缩点跟着从 BONUS=6 移到 **BONUS=11**（band 136 → 29，汤羹 32.7% → 83.7%）。
→ **机制确认**：`band = [score >= best - random_band]` ⇒ 任何二元 `±Δ`，只要 `|Δ| > random_band`，
  就会把候选切成「抽得到」和「抽不到」两半。**减分把被罚的一半切掉，加分把没奖的一半切掉——同罪。**

**🔴 当前落地代码（`BONUS=12, PENALTY=-20`）的实测后果：晚饭档 65%–77% 概率出汤。**
（band 从 116 塌到 9，其中 24/29 是汤羹。）

**修正后的通则（替换我上一轮那条）**：

> **二元型打分（有/无直接 ±X）的幅度必须 ≤ `random_band`（当前 5.0）。**
> **连续型打分（按比率缩放，如 `score_inventory = 25 × ratio`）不受此限** —— 它产生连续分布，band=116 那条基线正是这么来的。
> 判别方法：**看 band_size 有没有塌**（塌缩时 band 从三位数掉到个位数，比看占比更灵敏、更直接）。

**推荐值：`MEAL_SLOT_MATCH_BONUS = 3.0`，`MEAL_SLOT_MISMATCH_PENALTY = 0.0`**
→ 汤羹 9.4%/23.8%（基线 5.6%/14.2%，提升约 1.7×，可感知）｜主面 12.2%/34.0%（基线 12.8%/40.0%，仅轻微下降）｜band 60/25 不塌。

**⚠️ 顺带自检 `intent.bonus()`**（`intent_service.py` L156-163）：`cuisine` 匹配 **+15.0**、`prefer_fridge` **+6.0**，两个都 > 5.0。
- `prefer_fridge` 对"有食材的菜"**全体 +6**，是**均匀平移**，不改变相对排序 → 无害；
- `cuisine` 匹配现在是**死信号**（`recipe.cuisine` 几乎全 NULL）→ 也不触发；
- **但这是一颗定时炸弹**：一旦 `cuisine` 字段被修好，+15 会**立刻塌缩**成"只出该菜系的菜"。
  → 建议：**`cuisine` 修复上线时，必须同步把 `intent.bonus` 的 cuisine 项降到 ≤5.0。**

#### (13) O1 / O2 定值（基于上表实测）

| | 判据 | 定值 | 依据 |
|---|---|---|---|
| **O2** | 晚饭档 `category='汤羹'` 占比 | **≤ 30%**（线上观测，样本下限 300） | 正常区间 5.6%–23.8%，塌缩区间 64.8%–77.0%；**30% 是干净的分界线，两侧余量都很大**。它的职责是**抓塌缩**，不是调味 |
| **O1** | 晚饭档 `category IN ('主食','面食')` 占比 | **改为离线断言：≥ 基线 × 0.75**（线上不做） | 实测 12.2/12.8 = 0.95 ✅、34.0/40.0 = 0.85 ✅ |

**🔴 两个原本提的阈值都会在基线上误报，必须作废**：
- **roadmap 的 O2 ≈ 14%**（`P0 × 2`）：基线在「荤菜x1」历史下已经是 **14.2%**，**阈值会被基线自己击穿**。
- **我提的 O1 ≥ 15%**：基线在「空历史」下只有 **12.8%**，同样**在基线上就误报**。

→ **教训（第三次）**：**占比阈值不能由"池子里自然占比"推导**（我用了 70/342 = 20.5%，roadmap 用了汤羹 24/342 = 7.0%）。
**打分后的抽签带分布 ≠ 池子分布** —— 实测空历史下主面只有 12.8%（池子占比 20.5%）、荤菜却占 65.8%（池子占比 52%）。
**占比类阈值必须由离线蒙特卡洛实测 P0 得出，不能由池子占比推算。**

**另：O1 不建议上线。** 基线本身随历史漂移（12.8% ↔ 40.0%，差 3 倍），线上无法归一化，**只会误报**。它的职责（防止主面被压低）在 `PENALTY=0.0` 后已经没有对象了——纯加分不会造成降权。

#### (14) A22 存量审计：`_score()` 里哪些项实际是硬分区（2026-09-23，N=200 实测）

**方法**：只调 `load_candidates()` / `_score()` / `_random_band()`，**不调 `decide()`**（避免写 `decision_log`），零写入。
**判据（修正版）**：原提法 `band < 10` / `占比 > 60%` 是**绝对阈值，会误判**——夜宵池只有 45 道（band 11 不等于塌缩）、荤菜池内就占 52%（band 内 63% 不等于垄断）。改用两条相对量：
- **塌缩比 `band / 池`** < 5% ⇒ 塌缩
- **占比差 `band 内占比 − 池内占比`** > +30pp ⇒ 垄断

**PART 1 · 四时段基线**

| slot | 池 | band | band/池 | 主面% vs 池% | Δ | 荤菜% vs 池% | Δ | 判定 |
|---|---:|---:|---:|---|---:|---|---:|---|
| **breakfast** | 342 | **14** | **4.1%** | 100.0% vs 20.5% | **+79.5** | 0.0% vs 52.3% | **−52.3** | 🔴 **意外硬分区** |
| lunch | 342 | 59 | 17.3% | 20.0% vs 20.5% | −0.5 | 63.5% vs 52.3% | +11.2 | ✅ 软 |
| dinner | 342 | 60 | 17.5% | 15.5% vs 20.5% | −5.0 | 57.5% vs 52.3% | +5.2 | ✅ 软 |
| late_night | 45 | 11 | 24.4% | 65.5% vs 64.4% | +1.1 | 0.0% vs 6.7% | −6.7 | ✅ 软 |

→ 🔴 **早餐 100% 出主食/面食，荤菜/汤羹出餐率为 0**。成因：`_score()` 里两条**硬编码**二元加分叠加 —— `category in (主食,面食) +12.0` 与 `cook_minutes<=15 +8.0`，最高 **+20 ≫ random_band 5.0**。

**PART 2 · 逐项关断（dinner，各自激活场景）**

| 打分项 | 激活场景 | 开 band | 关 band | band/池 | 判定 |
|---|---|---:|---:|---:|---|
| **`score_inventory`** | 库存=真实高频 TOP3 | **3** | 60 | **0.9%** | 🔴 **意外硬分区** |
| `category_penalty_step` | 荤菜×1 | 25 | 60 | 7.3% | ⚪ **有意硬排除**（荤菜 Δ −52.3pp，整类出局）——「打散」本意，不改 |
| `score_weather` | weather=cold | 56 | 56 | 16.4% | ⚠️ **此结论已于 2026-09-23 推翻，见 §5.2(18)③** —— 当时只测了 cold（**唯一健康的一支**）；rain / snow / hot 三支 **natural_band 塌到 3–29** |
| `score_budget` | meal_budget=20 | 54 | 60 | 15.8% | ✅ 软 |
| `same_cuisine_penalty` | last_cuisine=家常菜 | 60 | 60 | 17.5% | ✅ 软（cuisine 全 NULL，死信号） |
| `main_ingredient_penalty` | last_main=鸡蛋 | 57 | 60 | 16.7% | ✅ 软 |
| `score_spice`（连续型） | spice=2 | 60 | **342** | 17.5% | ✅ 软（连续型不受通则约束） |
| `MEAL_SLOT`（R-11 已修 3.0/0.0） | — | 60 | 116 | 17.5% | ✅ 软 |

→ **⚠️ 附带发现（第二个"假装在打分"）**：`score_spice` 关掉后 **band = 342 = 全池**。
即**默认场景（无库存/无天气/无预算）下 `_score()` 实际只有 `score_spice` 一项在工作**；
`score_cuisine`（已归零）、`score_weather`（condition=None）、`score_budget`（`cost` 常为 None）、`same_cuisine_penalty`（cuisine 为 NULL）**全部静默失效**。
这与 §2.4 的 `score_cuisine` 是同一类病：**权重占着，信号是空的。**

**PART 3 · `score_inventory` 深挖（R-09「家里有啥」真实场景，dinner，池 342）**

| 录入食材数 | band | band/池 | 命中菜池内% | 命中菜 band 内% | **非命中菜 band 内%** | 判定 |
|---:|---:|---:|---:|---:|---:|---|
| 0 | 60 | 17.5% | — | — | 100.0% | ✅ |
| **1** | **3** | **0.9%** | 21.6% | **100.0%** | **0.0%** | 🔴 |
| **2** | **3** | 0.9% | 28.7% | **100.0%** | **0.0%** | 🔴 |
| **3** | **3** | 0.9% | 33.0% | **100.0%** | **0.0%** | 🔴 |
| 5 | 3 | 0.9% | 40.4% | **100.0%** | **0.0%** | 🔴 |
| 12 | 4 | 1.2% | 58.8% | **100.0%** | **0.0%** | 🔴 |

（录入 3 样 = 鸡蛋/土豆/白砂糖；12 样见附录 F 脚本输出）

→ **roadmap 的 M5 完成定义三条，两条红、一条踩线**：

| M5 判据 | 要求 | 实测 | 结果 |
|---|---|---:|---|
| ① 录入 3 样后 band ≥ 3 | ≥3 | **3** | 🟡 踩线（正好等于 `random_min_choices=3` 的兜底值，说明带根本不够，是靠"不足 3 道按分数补齐"逻辑兜住的） |
| ② band ≥ 无库存时的 50% | ≥30 | **3** | 🔴 **红** |
| ③ 非库存命中菜占比 > 0 | >0 | **0.0%** | 🔴 **红** |

→ **R-09 的上线闸门是红的。**

**🔴 根因不是幅度，是归一化（诊断已确认）**：
`_inventory_ratio(c, inventory) = hits / len(need)`，其中 `need` = 该菜自己的非调味料食材数。
→ **按菜品自身的食材数归一化**，导致：
- 紫菜蛋花汤 `need=2`，你只有鸡蛋 ⇒ `ratio = 1.0` ⇒ **+25 满分**
- 可乐炒饭 `need=11`，你只有 1 样 ⇒ `ratio = 0.111` ⇒ +2.78

→ **`score_inventory` 实际奖励的是"食材少的简单菜"，不是"你家有的菜"。**
只要录入 1 样食材，所有 2-食材菜立刻满分 +25 ≫ `random_band=5.0` ⇒ 塌缩。

→ ⚠️ **因此 A23 只调幅度治不了本**：即使把 `score_inventory` 从 25 降到 5，
"紫菜蛋花汤永远第一"的偏差**依然存在**（只是不再排除别人）。**必须同时改归一化**：

```python
# 建议: 分母取 max(len(need), K), K ≈ 4~5 —— 简单菜不再白拿满分
ratio = hits / max(len(need), 4)
# 或改为命中计数: score_inventory * min(1.0, hits / 3)
```
改完归一化后，再叠加"二元/准二元项幅度 ≤ `random_band`"的通则。

**处置范围（与 roadmap 一致）**：本版只动 `score_inventory`（R-09 是本版 P0，数据源是我们自己引进来的）；
`category_penalty_step` 的整类排除是**有意设计**（需求 5 打散），**不改**；
早餐硬编码 +12/+8 排 V1.3（用户可见但非本版范围）。

**⚠️ 脚本复现**：`/tmp/mp_a22_v2.py`（只读；venv `backend/.venv/bin/python`）。
脚本中高频食材的调味料黑名单必须**远宽于** `_inventory_ratio()` 内置的 10 项 `staples`——
第一版用内置黑名单拿到了 `['鸡蛋','白糖','姜']`（2 个调味料），不是 R-09 的真实场景，已修正。

#### (15) R-09 快选词表定稿 + R-11 = 3.0/0.0 的验收基线（2026-09-23）

**⚠️ 先一条会推翻常见假设的发现**：`ingredient.category` **91.6% 为 NULL**（705/771，仅 66 条有分类）。
→ **不能用 `category='调味品'` 排除调味料**：生抽/老抽/大蒜/水/鸡精/生姜/干辣椒/香叶 全是 NULL。
→ 且 `_inventory_ratio()` 内置的 10 项 `staples` 远远不够。**必须走显式黑名单**（见附录 G）。

**定稿 12 词**（**必须双分母并列写**，只写百分比后面一定会对不上 —— 2026-09-23 requirement-analyst 口径）：

| 分母 | 分母值 | 覆盖 | 覆盖率 |
|---|---:|---:|---:|
| **D1 候选池** `COALESCE(is_dish,1)=1` | 342 | **164** | **48.0%** |
| **D2 有食材行的菜**（`recipe_ingredient` 去重 recipe_id，不限 is_dish） | 373 | **175** | **46.9%** |

> **两个分母都不是"算错"，是问的问题不同**：
> - **D1=342** 是真实候选池 → 回答「用户勾了食材，**有多少比例的候选菜可能被命中**」，用于**效果评估**。
> - **D2=373** 是"有食材行"的菜（含 52 道非菜品）→ 回答「**词表本身覆盖多少菜谱**」，用于**词表质量评估**。
> 引用时必须标明是哪个分母。PRD v1.6 的 `175/373=46.9%` 与本文原写的 `164/342=48.0%` **是同一张词表的两个口径，不矛盾**。

🔴 **本次实跑新发现 —— R-09 覆盖率存在 93.9% 的天花板**：

| 项 | 值 | 含义 |
|---|---:|---|
| 候选池（`is_dish=1`） | 342 | |
| **其中没有任何 `recipe_ingredient` 行** | **21** | 🔴 **这 21 道菜勾任何食材都命中不了** |
| R-09 理论可达上限 | **321 / 342 = 93.9%** | 词表加到无限大也到不了 100% |

→ **影响**：`score_inventory` 的命中率上限就是 93.9%；这 21 道菜在 R-09 场景下永远是 0 命中，
**它们只能靠别的打分项进 band**。若 V1.3 要继续提 R-09 覆盖率，第一步不是加词，是**补这 21 道菜的食材行**（补数收益一次性 +6.1pt，比加任何单词都大）。
→ **与 §1 的数字对齐**：§1 报的「23 道无食材行」是 **396 全表**分母；落到 `is_dish=1` 候选池后是 **21 道**（另 2 道属非菜品）。两个数不矛盾，是同一批菜的两种分母。

| # | 食材 | 覆盖菜数 | 占比 | | # | 食材 | 覆盖菜数 | 占比 |
|---:|---|---:|---:|---|---:|---|---:|---:|
| 1 | 鸡蛋 | 67 | 19.6% | | 7 | 面粉 | 13 | 3.8% |
| 2 | 土豆 | 21 | 6.1% | | 8 | 番茄 | 12 | 3.5% |
| 3 | 青椒 | 17 | 5.0% | | 9 | 排骨 | 11 | 3.2% |
| 4 | 胡萝卜 | 16 | 4.7% | | 10 | 猪肉 | 8 | 2.3% |
| 5 | 五花肉 | 15 | 4.4% | | 11 | 黄瓜 | 8 | 2.3% |
| 6 | 香菜 | 13 | 3.8% | | 12 | 豆腐 | 7 | 2.0% |

**⚠️ 同义词未归一会吃掉 R-09 的效果**（`_inventory_ratio` 是子串匹配，同义词无子串关系即互不相通）：

| 同义词组 | 各自覆盖 | 合计去重 | 选一个的后果 |
|---|---:|---:|---|
| **番茄 12 / 西红柿 9** | 12 / 9 | **21** | 选"番茄"只拿到 12 道，**丢 9 道** |
| 豆腐 7 / 老豆腐 2 / 嫩豆腐 1 | — | 10 | 丢 3 道 |
| 白菜 1 / 娃娃菜 4 / 大白菜 1 | — | 6 | "白菜"基本没用 |
| 土豆 21 / 马铃薯 0 | — | 21 | 无影响 |

**🔴 西红柿缺口的定性更正（2026-09-23，采纳 requirement-analyst）**：
把「西红柿」补进 12 词 → **13 词覆盖 166**（D1 分母 342 = 48.5%），**净新增只有 2 道 = +0.6pt**。
（13 词 D2 分母 373 = 177 = 47.5%。）

→ **所以「西红柿」不是"覆盖率缺口"，是"词面不匹配导致的信任缺口"**：
9 道里 **7 道已被其余 12 味覆盖**，用户勾「西红柿」拿到 12 道时，**丢的 9 道里 7 道本来也会出来**，
真实损失只有 2 道。但用户的**感知**是「我勾了西红柿，出来一堆没有西红柿的菜」——**这是信任问题，不是召回问题。**

→ **排期定性（务必写进 V1.3 立项材料）**：
| 按什么算 | 结论 |
|---|---|
| 按覆盖率（+0.6pt） | **排不进 V1.3**，会被"合理地砍掉" |
| 按信任（勾了不生效） | **必须排进 V1.3** |
→ **用覆盖率口径给它排序，它必死；用信任口径，它是 P1。** 建议定性写「信任缺口」，避免被覆盖率指标误杀。

→ 同义词归一（番茄↔西红柿、豆腐↔嫩/老豆腐、白菜↔娃娃菜/大白菜/小白菜）建议随 A23 一起在 `ingredient` 层做，成本极低。

**R-11 = 3.0 / 0.0 的验收基线（N=500，dinner，池 342）**

| 历史变体 | band 中位（开） | band/池 | 汤羹% | 95%CI | 主面% | band 中位（关） |
|---|---:|---:|---:|---|---:|---:|
| 空历史 | 60 | 17.5% | 9.4% | [6.8%, 12.0%] | 12.2% | 116 |
| **荤菜×1 / ×2** | **25** | 7.3% | 23.8% | [20.1%, 27.5%] | 34.0% | 42 |
| 素菜×1 | 53 | 15.5% | 10.4% | [7.7%, 13.1%] | 14.4% | 105 |
| last_main=鸡蛋 | 57 | 16.7% | 10.0% | [7.4%, 12.6%] | 12.8% | 107 |

**🔴 据此修正 PRD 验收⑦**：`band_size 中位数 ≥ 50` **不鲁棒** —— 荤菜占池子 52%，"最近吃过荤菜"是常态，
一旦发生 `category_penalty_step` 就把 179 道荤菜整类压下去，band 只剩 25（**基线本身也只有 42**），
**≥50 会把"正常"判成"不通过"，而它红的原因根本不是 R-11**。

→ **改用相对判据**：
```
⑦ 晚饭档蒙特卡洛 N≥500：band_size 中位数 / 候选池 ≥ 5%（342 池即 ≥17）；且 汤羹占比 ≤35%
```
（正常 7.3%–17.5%，塌缩 9/342 = 2.6%，两侧余量充足，且与 A22 判据口径一致、不需要对照组。）
备选：`band_size 中位数 ≥ 基线（R-11 关闭）× 0.45`（实测 52%/60%/50%/53%，全过）。
**汤羹 ≤35% 确认可行**：实测 9.4%–23.8%，CI 上限 27.5%；塌缩时 64.8%–77.0%。

**样本量补充**：J3-夜宵（目标 ≤20%）—— n=60 的 CI 是 [9.9%, 30.1%]、n=100 是 [12.2%, 27.8%]、**n=200 是 [14.5%, 25.5%]**。
→ **夜宵也定 ≥200，与 J6'/J7' 一致，不要为夜宵开口子**（夜宵是最薄的一档，给更低下限等于给它最宽的置信区间）。
→ **J3 主口径（≤8%）同样建议 ≥200**：n=100 时 CI [2.7%, 13.3%] 跨过 8% 阈值，判不动。

#### (14) 🆕 门禁脚本已入库 + 它立刻抓出第二个同类缺陷：**早餐档也是硬分区**

应 roadmap-planner 要求，O2 的离线蒙特卡洛已固化为回归门禁：
**`backend/scripts/band_regression.py`**（只读、零写入、退出码可接 CI）
```bash
cd backend && .venv/bin/python scripts/band_regression.py            # 默认 N=500
.venv/bin/python scripts/band_regression.py --samples 200 --json     # 机器可读
```
三项检查：**① 静态自检**（二元打分常量幅度 ≤ `random_band`）+ **② `band` 中位数 ≥ 下限**（下限 = `max(12, ceil(0.05×池子))`，342 池即 **18**）+ **③ 晚饭汤羹占比 ≤ 30%**（O2）；另加「品类数 ≤ 2」「单品类 ≥90%」两条告警。
**跑法约束已写进脚本文档：不能调 `decide()`**（会写 `decision_log`，500 次 = 500 行合成数据污染分母）。

**② 为什么从绝对值 12 改成相对值 5%**（2026-09-23 修订）：绝对阈值**会随池子增长而变松**
—— 342 池时 12 = 3.5%，2000 池时 12 = 0.6%，越录菜越漏判。改为相对判据后与 PRD 验收⑦ 同口径
（342 池 `ceil(0.05×342)=18`；实测 lunch/荤菜×1 = 22、dinner/荤菜×1 = 25，均在红线之上，不会误杀）。

**已知豁免（xfail）机制**：早餐档在相对阈值下必然失败（band=14 < 18），若直接判 FAIL 会阻塞 CI，
若静默放过又会丢失信号。脚本内置 `KNOWN_XFAIL` 白名单，豁免项单独以 `[XFAIL]` 打印并附
**「豁免理由 + 摘掉条件」**，非白名单的槽位照常 FAIL。当前只豁免 `breakfast` 一项，
摘掉条件是「早餐 +12.0/+8.0 提取为常量且 `|Δ| <= random_band`」。
→ **原则：豁免必须显式、必须带摘掉条件、不得静默通过。**

**它一上来就抓出第二个同类缺陷 —— 早餐档**：

| slot | band 中位 | 主面% | 品类数 | 判定 |
|---|---:|---:|---:|---|
| **breakfast** | **14** | **100.0%** | **2** | 🔴 零多样性 |
| lunch | 59 / 22 | 20.0% / 49.5% | 6 / 5 | 正常 |
| dinner | 60 / 25 | 15.5% / 34.5% | 7 / 6 | 正常 |
| late_night | 53 / 42 | 11.5% / 36.0% | 6 / 6 | 正常 |

**成因**：`_score()` L800-805 的早餐偏好是**硬编码的二元加分**
—— `category in ("主食","面食") → +12.0`、`cook_minutes <= 15 → +8.0`，**合计最高 +20，远超 `random_band=5.0`**。

**后果比数字更糟**：被排除的恰恰是真正的早餐食品 ——
**牛奶燕麦、鸡蛋三明治、金枪鱼酱三明治、微波炉荷包蛋** 都被 `category` 标注成了「**荤菜**」，
早餐偏好按 `category` 加分，**它们永远抽不到**。早餐 100% 是面/饭，没有燕麦和三明治。

**这不是调个常数就能修的 —— 它是机制层面的矛盾**：

| `random_band` | 早餐主面% | band |
|---:|---:|---:|
| 5.0（现状） | **100.0%** | 14 |
| 10.0 | 100.0% | 26 |
| **15.0** | 83.3% | 70 |
| 20.0 | 42.7%（= 基础分布） | 186 |

基础分布被荤菜主导（52%），**要"让早餐像早餐"就必须用超过 `random_band` 的加分，而代价就是垄断**。
→ **在 `random_band=5.0` 下，"纠正分布"与"保持多样性"不可兼得。** 需要产品侧拍板：
(a) 接受早餐 100% 面/饭（但**先修 `category` 标注**，让燕麦/三明治归到主食）；
(b) 早餐档单独放大 `random_band`（≥15）；
(c) 把早餐的约束下沉到过滤层显式表达（诚实且可控）。
**我倾向 (a)+(c)**：先修标注，再把"早餐吃什么"写成显式过滤而不是伪装成偏好。

**⚠️ 静态自检的覆盖盲区**（已写进脚本文档）：自检只能扫【模块级常量】。
目前有两组二元加分**硬编码在 `_score()` 里**，扫不到，只能靠蒙特卡洛兜住：
- L800-805 早餐偏好 +12 / +8
- `intent.bonus()` 的 `cuisine` 匹配 **+15.0**（现在是死信号，`cuisine` 几乎全 NULL；**字段一旦修好会立刻塌缩成"只出该菜系"**）

→ **建议把这两组也提取成模块级常量**，才能纳入静态自检。

**复核**：脚本跑完后 `decision_log` 仍 **190** 行、`recipe` 仍 **396** 行 ⇒ **全程零写入已验证**。

#### (12) 🔴🔴 离线蒙特卡洛实测：二元型打分幅度必须 `≤ random_band`（O1/O2 定值依据）

**执行方式（只读）**：只调 `_score` + `_random_band`（纯函数，不碰库），候选用 `load_candidates()`。
**严禁调用 `decide()`** —— 它会往 `decision_log` 写行，N 次采样 = N 行合成数据，**直接污染 J3/J6'/J7' 的分母**（即 190 行压测数据那件事重演）。
每次采样从同一份固定历史出发、**不写回**（保证 i.i.d.），固定随机种子可复现。

**参数**：晚饭档，`is_dish=1` 342 道，N=500，两种固定历史（空历史 / 荤菜×1）。

| R-11 分值 | 汤羹%（空历史） | 主面% | band 中位 | 汤羹%（荤菜×1） | 主面% | band 中位 | 判定 |
|---|---:|---:|---:|---:|---:|---:|---|
| **0 / 0（基线）** | 5.6% | 12.8% | **116** | 14.2% | 40.0% | **42** | 正常 |
| **+3 / 0** ← 建议 | 9.4% | 12.2% | 60 | 23.8% | 34.0% | 25 | ✅ 正常 |
| +5 / 0 | 10.8% | 10.6% | 60 | 22.4% | 31.2% | 25 | ✅ 正常 |
| **+6 / 0** | **64.8%** | 23.2% | **9** | **77.0%** | 23.0% | **8** | 🔴 塌缩 |
| +8 / 0 | 64.8% | 23.2% | **9** | 77.0% | 23.0% | **8** | 🔴 塌缩 |
| **当前落地 +12 / −20** | **64.8%** | 23.2% | **9** | **77.0%** | 23.0% | **8** | 🔴 塌缩 |

**塌缩点精确落在 `random_band = 5.0`：≤5 正常，≥6 塌缩。**
**机制证明**（非巧合）：把 `random_band` 改成 10.0 重跑，**塌缩点跟着移到 11**（band 136→29，汤羹 32.7%→83.7%）。

**为什么加分也会塌缩**：band = `score >= best - random_band`。给 29 道 dinner 匹配菜 +8 后，`best` 来自这 29 道，未匹配的菜低 8 > 5 ⇒ **全部掉出抽签带**，band 从 116 塌到 9，晚饭变成"只在 29 道里抽"。

**→ 通则（取代第 (9) 条中"软偏好用加分表达"的说法）**：
> **在 `random_band` 抽签机制下，二元型打分的幅度必须 `≤ random_band`（当前 5.0）。**
> `|Δ| > random_band` 时：**减分 ⇒ 整类排除被罚的菜；加分 ⇒ 被奖的菜垄断抽签带。两个方向都是硬分区。**

（我先前说"软偏好用加分表达"只对了一半：加分确实不再排除任何菜，但幅度一大就**反过来垄断**。这一半是模拟抓出来的。）

**🔴 当前已落地代码是 P0**：`+12 / −20` ⇒ 晚饭 **65–77% 是汤**，band 只有 8–9 道。
这是**静默失败的第三种形态**：不是池子空（J3 不报）、不是被减分排除（O1 不报），而是**被加分垄断**。

**→ 建议值：`MEAL_SLOT_MATCH_BONUS = 3.0`、`MEAL_SLOT_MISMATCH_PENALTY = 0.0`**
（+3 时汤羹是基线的 **1.68×**，主面几乎不动：12.2 vs 12.8、34.0 vs 40.0。）

**O1 / O2 最终定值**：

| | 结论 | 依据 |
|---|---|---|
| **O2（线上观测）** | 晚饭档 `category='汤羹'` 占比 **≤ 30%**，样本下限 300 | 正常区间 5.6–23.8%，塌缩区间 64.8–77.0%，分离度极大。**职责是抓塌缩，不是调味** |
| **O1（离线断言）** | `主面占比 ≥ 基线 × 0.75`（+3 时 0.95 / 0.85 ✅） | **线上不设** —— 基线随历史漂移（12.8% ↔ 40.0%），无法在线归一化 |

**🔴 撤回我自己先前给的 O1 ≥15%**：那是拿**原始池**占比 20.5% 推的，但**打分后 band 内的分布 ≠ 原始池分布**（实测空历史基线只有 12.8%），≥15% 会在基线误报。

**🔴 撤回 roadmap-planner 的 `(random_band, 10]` 窗口**：方向反了，应为 **`(0, random_band]`**；8 不是默认值而是越界值。

**⚠️ 方法必须写死的两个参数**（否则不可复现）：
1. **固定历史**：空历史（近 7 天无记录）+ 荤菜×1（`category_counts={"荤菜":1}`）。
   若固定历史含 1 次汤羹 ⇒ `category_penalty_step=25` 让 24 道汤羹整类出局 ⇒ **P0 = P1 = 0，定值直接崩**。
2. **N = 500**：O2 抓塌缩 200 够；但 O1 要分辨 40.0→34.0 这 6pp，200 的差分 SE ~5pp 判不了 ⇒ **500 是 O1 的下限**。

**同类风险（不阻塞）**：`intent.bonus()` 的 cuisine 匹配是 **+15.0**，二元且 > 5.0。当前 cuisine 覆盖率极低基本不触发，**但日后修好 cuisine 就会引爆同样的塌缩**。建议纳入"二元打分 ≤ random_band"自检清单。

**脚本**：`/tmp/mp_o2_sim.py`（主跑）、`/tmp/mp_o2_sweep.py`（分值扫描）、`/tmp/mp_o2_bandproof.py`（改 `random_band` 验证机制）。只读、未落库、未进仓库。

#### (15) 🔴 补漏：`score_cuisine` 归零只覆盖了 1/4 条打分链路（2026-09-23 全仓 grep 复核）

`fix-cuisine-weight` 把 `backend/app/config.py` L148 与 `config/default.yaml` L71 的 `score_cuisine` 改成 `0.0` —— **这一步是对的**。但 `score_cuisine` 只是 `DecideSettings` 的一个字段，**只作用于 `decision_service` 这一条链路**。全仓 grep 发现另外 **3 处模块级硬编码**仍在用同一个死信号：

| 文件 | 常量 | 定义 → 使用 | 用途 | 是否走 `DecideSettings` |
|---|---:|---|---|---|
| `replacement_service.py` | `SCORE_CUISINE = 20.0` | L65 → L382-383 | **「换一换」（首页结果卡）** | ❌ 硬编码 |
| `generation_service.py` | `SCORE_CUISINE = 20.0` | L66 → L684-685 | 周菜单本地编排打分 | ❌ 硬编码 |
| `fridge_menu_service.py` | `SCORE_CUISINE = 5.0` | L46 → L312-313 | 冰箱菜单打分 | ❌ 硬编码 |

三处判据**字面完全相同**：`if cuisines and recipe.cuisine and recipe.cuisine in cuisines: score += SCORE_CUISINE`
—— 就是 §2.4 那个对不上的死信号（`recipe.cuisine`=荤菜/主食/早餐 vs `profile.cuisines`=粤菜/川菜/江浙），命中 **2/396 ≈ 0.5%**。

**为什么现在"看起来没事"**：命中率 ≈ 0 ⇒ 20 分几乎永不加上 ⇒ 不塌缩、不报错，只是**静默占着权重位**（与 §2.4 同一类病：权重占着，信号是空的）。
**为什么它是个雷**：`config.py` L146-147 写了恢复路径 ——「`cuisine` 由凌晨 LLM 富集标注回填后恢复成 20.0」。
**但回填那一天，`replacement_service` 的 20 分不需要任何人改代码就会自动生效**，而它的抽签机制与 `decision_service` 是同一套（`replacement_service.py` L334-338）：

```python
scored.sort(key=lambda pair: pair[0], reverse=True)
top = scored[:LOCAL_TOP_K]                                                    # = 3
best = top[0][0]
candidates = [r for s, r in top if s >= best - LOCAL_RANDOM_BAND]             # = 5.0
return random.choice(candidates or [top[0][1]])
```

`|Δ| = 20 > LOCAL_RANDOM_BAND = 5.0`，且它是**先截 top3 再切带**（比 decision 的"全池切带"更陡）⇒ 按 §5.2(12) 通则，**回填当天「换一换」会直接塌缩成"只在命中菜系的菜里换"**。

**定级**：**不是本版 P0**（当前命中率 0.5%，用户无感，且 `换一换` 不在 J1–J7 观测口径内）。但建议本版**顺手做两件不改变任何现有行为的事**：
1. 三处 `SCORE_CUISINE` 同步改成 `0.0`，并各写一行注释指向 `config.py` L142-147（口径唯一真源 = `DecideSettings`）；
2. 在 `config.py` 的恢复注释里**补全清单**：恢复 20.0 时要同时改 **6 处** —— `config.py` / `config/default.yaml` / `shared/decide.ts` / `replacement_service.py` / `generation_service.py` / `fridge_menu_service.py`。否则会出现「`decision` 归零、`换一换` 塌缩」的口径分叉。

**优先级**：`replacement_service`（首页「换一换」，用户可见）> `generation_service`（20 分，非首页但同口径）> `fridge_menu_service`（仅 5.0，且库存 60+20 是绝对主角，影响最小）。

**归属**：均为 backend service 文件，**我不改**（所有权冻结，报主理人派单）。

**附带双端一致性复核（只读 grep）**：决策链路已对齐 ——
`shared/decide.ts` L117 `cuisine: 0` ✅（与 `config.py` 一致）；L169-170 `MEAL_SLOT_MATCH_BONUS = 3` / `MEAL_SLOT_MISMATCH_PENALTY = 0` ✅（与 `decision_service.py` L121/124 一致）；L126 `randomBand: 5` ✅。**决策链路双端无分叉，分叉只在这三条旁路。**

---

## 附录 C：应 PRD（R-09 / R-13）要求补跑的两条 SQL

### C-1 R-09 「家里有啥」快选词表（首页 12 个 chip）

> ⚠️ PRD 原稿的 SQL 有误：`recipe_ingredient` **没有 `ingredient_name` 列**，只有 `ingredient_id`，必须 JOIN `ingredient`。
> ⚠️ 更关键：**按原始词频取前 12 会拿到 9 个调味料**（生抽116/盐111/料酒68/白糖59/老抽59/姜53/大蒜46/蚝油46/水40/葱39/蒜34）。
> 而 `decision_service._inventory_ratio()` 里写死了 `staples = {"盐","食用油","糖","生抽","老抽","香油","淀粉","料酒","白胡椒","黑胡椒"}`，**调味料被显式排除在库存命中打分之外**——用户勾了「生抽」一分不加，快选列表会变成纯装饰。

```sql
SELECT i.name AS ingredient_name, COUNT(DISTINCT ri.recipe_id) AS recipes
FROM recipe_ingredient ri JOIN ingredient i ON i.id = ri.ingredient_id
WHERE i.name NOT IN ('盐','食盐','食用油','油','糖','白糖','白砂糖','冰糖','生抽','老抽','酱油','香油',
  '淀粉','料酒','白胡椒','黑胡椒','胡椒粉','白胡椒粉','鸡精','味精','蚝油','醋','香醋','白醋','蒜','大蒜',
  '姜','生姜','葱','小葱','大葱','十三香','花椒','八角','干辣椒','豆瓣酱','番茄酱','沙拉酱','芝麻','孜然',
  '五香粉','水','香叶','桂皮','小米辣')
GROUP BY i.name ORDER BY recipes DESC LIMIT 12;
```

**定稿 12 词**：鸡蛋75 / 洋葱31 / 土豆21 / 胡萝卜18 / 青椒17 / 五花肉15 / 面粉15 / 牛奶14 / 排骨11 / 西红柿9 / 黄瓜8 / 豆腐7

| 词数 | 触达菜数 | 占比 |
|---:|---:|---:|
| 前 8 | 154 | 38.9% |
| **前 12** | **176** | **44.4%** |
| 前 16 | 188 | 47.5%（+4 词仅 +12 道，边际递减） |

→ **12 个是合理档位**。但「排除调味料」必须写成硬约束，且黑名单应**直接复用 `_inventory_ratio` 的 staples 集合**，两边口径不一致会造成又一处静默失效。
→ `ingredient.category` 有 **705/771 为 NULL**，不能靠 category 过滤，只能用名称黑名单。

### C-2 R-13 `tools` 接线的准入门槛：≥50% 达不到，且方向是反的

| 回填口径 | 命中 | 覆盖率 |
|---|---:|---:|
| **现状**（DB 已有值） | 72 | 18.2% |
| ① 现有 `guess_tools()` 严格版（**仅菜名**：蒸/烤/焗/空气炸/煲/炖） | **47** | **11.9%** ← 比现状**更低** |
| ② 菜名 + 加「炸/微波」 | 58 | 14.6% |
| ③ 菜名 + `steps` + `quick_steps` + 加「炸/微波」 | 180 | 45.5% |
| ④ 宽泛口径（再含 炒/煮/煎/焖/卤…） | 394 | 99.5% ← 语义错误 |
| ⑤ **严格「必须有特殊厨具」** | **123** | **31.1%** ← 语义正确的天花板 |

**三条结论**：

1. **只改规则不扩字段来源是倒退**：现状 72 道里只有 47 道能被菜名规则复现，说明现有 72 道有一部分并非 `guess_tools()` 产出。
2. **≥50% 在语义正确的前提下永远达不到**。要够 50% 只能走口径④（把"炒/煮"也算成需要厨具），语义完全错误。
3. **低覆盖率是设计意图，不是缺陷**。`dish_rules.guess_tools()` docstring 原文：「炒锅是默认, 不写; 只记"**没有就做不了**"的那些」。**tools 覆盖率越高说明标得越错**，所以"覆盖率 ≥50%"这个门把指标设反了，它会奖励错误标注。

**建议把门槛换成**：

| 门槛 | 实测 | 判定 |
|---|---|---|
| A. 可拦截量增量 | 现状 72 → 严格口径 **123**，**净增 51 道（+71%）** | ✅ |
| B. 单厨具绝对数 | pot 67 / steamer 47 / oven 40 / **microwave 21** / 压力锅 19 / 电饭煲 19 / **air_fryer 11** | ⚠️ 现状枚举**没有 microwave**，而 21 道菜需要它、2 个用户有微波炉 → 加 microwave 是净收益 |
| C. **用户侧覆盖率** | `household.kitchen_equipments` **仅 3/8 家庭有值** | 🔴 **真正的瓶颈**；菜侧 31.1% × 用户侧 37.5% ≈ **交集仅约 12%** |

**最终建议（按推荐度）**：
1. **本版不接线 tools，改为结果卡上展示「需烤箱」标签**——展示不需要数据闭环，零风险，且直接命中 user-researcher 描述的"用户看到'烤箱'这个词才想起来"场景。接线推 V1.3。
2. 若必须接线：门槛改为「严格口径 ≥100 道 且 单厨具 ≥15 道」，**不要用百分比**，并同步做用户侧回填入口。
3. 折中：只做**反向软惩罚**（"没有的厨具往后排"），不做正向硬过滤——**误杀 324 道无标注的菜，比漏拦 11 道 air_fryer 菜严重得多**。

### C-3 附带：非菜品剔除的三档清单（供实现参考）

- **A 档必删 33 道**：调味品/调料 9 道（油泼辣子、油酥、炸串酱料、简易版炒糖色、糖醋汁、草莓酱、葱油、蒜香酱油、蔗糖糖浆）+ 饮品 23 道（B52轰炸机、金汤力、长岛冰茶、Mojito、酸梅汤等）+ 牛油火锅底料
- **B 档建议删 19 道**：甜品（提拉米苏、奥利奥冰淇淋、雪花酥、龟苓膏等）
- **C 档建议保留 9 道**：半成品加工里的 速冻水饺(10min)/速冻馄饨/凉皮/半成品意面/空气炸锅羊排/空气炸锅鸡翅中/炸薯条 —— **「半成品加工」描述的是加工程度不是"是不是菜"**，删掉会缩小本已只有 132 道的 ≤15min 快手池
- ⚠️ **别误伤**：`早餐` 25 道、`水产` 28 道、`汤与粥` 18 道都是**正常菜品**
- 建议加 `is_dish` 布尔列而非物理删除（`decision_log` 有 18 条外键指向它们，物理删会触发 `ON DELETE SET NULL` 让历史日志丢菜名）

---

#### (16) 🔴 R-09 改动前基线快照：`_inventory_ratio` 三个消费点（2026-09-23）

**为什么必须在改动前拍**：`_inventory_ratio()`（`hits / len(need)`）有三个消费方，本次修复**只拆消费点、不改它本身**，
所以 ②③ 的触发率必须**一个数都不变**：

| 消费点 | 位置 | 逻辑 |
|---|---|---|
| ① `_score()` | 排序打分 | `score += score_inventory * ratio` |
| ② `_weather_score()` | 雨天 | `ratio ≥ 0.3 → +18.0`；`0.1 ≤ ratio < 0.3 → +9.0`；另有 tags 的 `+10.8` |
| ③ `_build_result()` | 文案 | `is_bad and ratio < 0.3 → "这种天出门不值当，交给外卖吧"` |

**基线快照锚点（缺一不可）**：

| 锚点 | 值 |
|---|---|
| 候选集 | `load_candidates()` = **342**（`is_dish=1`） |
| inventory 快照 | **S1 = {鸡蛋, 土豆, 青椒}**（主锚点）；对照 S0 = ∅、S2 = 12 词全量 |
| 天气 / 时段 | `condition="rain"`（`is_bad=True`）/ `slot = dinner` |
| 实现口径 | `_inventory_ratio = hits / len(need)`，`staples` 为内置 10 项 |
| 常量 | `random_band=5.0`、`score_weather=18.0`、`score_inventory=25.0` |
| 跑批日期 | **2026-09-23** |
| 复现脚本 | `/tmp/mp_baseline_inventory.py`（**零写入，严禁 `decide()`**） |

**实测（全量精算 342 道，确定性 —— 这是主锚点，不依赖随机种子）**：

| 快照 | ② 天气加分触发 | ├ ratio≥0.3 | ├ 0.1~0.3 | └ 仅 tags（**与 ratio 无关，不该被改动碰**） | ③ 外卖文案触发 |
|---|---:|---:|---:|---:|---:|
| S0 空 | 77/342 = **22.5%** | 0 | 0 | 77 (22.5%) | **342/342 = 100.0%** |
| **S1 TOP3** | 150/342 = **43.9%** | 26 (7.6%) | 68 (19.9%) | 56 (16.4%) | **316/342 = 92.4%** |
| S2 12词 | 217/342 = **63.5%** | 57 (16.7%) | 126 (36.8%) | 34 (9.9%) | **285/342 = 83.3%** |

**菜名集合指纹（sorted+sha256，集合对不上也是回归）**：

| 快照 | ② 指纹 (n) | ③ 指纹 (n) |
|---|---|---|
| S0 | `7eb1f1dfd16c8c31` (77) | `fa7d13cec53bee7a` (342) |
| **S1** | **`cce814943b1e1280` (150)** | **`24b820fe0900974d` (316)** |
| S2 | `3abd59c6914d6181` (217) | `c852439ca50f9cfc` (285) |

> **用法**：dev-engine-relax 改完重跑 `/tmp/mp_baseline_inventory.py`，三组快照的 ②③ 触发率与两个指纹**必须全等**。
> 不等 = 误动了 `_inventory_ratio` 本身，或改了阈值 0.3 / 0.1。

##### 🔴 顺带拍到的：基线本身就已经塌缩了（band = 3）

拍基线时发现一个**不属于本次改动、但必须现在说**的问题：

| 快照 | band_size | band 内菜名 | band 外下一个 | 落差 |
|---:|---:|---|---:|---:|
| S0 空库存 | 20 | 卤菜/印度焖饭/可乐炒饭/… | 22.05 | 1.75 |
| **S1 TOP3** | **3** | 紫菜蛋花汤 / 蒸箱鸡蛋羹 / 鸡蛋羹 | 51.38 | **7.92** |
| **S2 12词** | **3** | 紫菜蛋花汤 / 罗宋汤 / 蒸箱鸡蛋羹 | 52.55 | **6.75** |

**S1/S2 的自然 band 只有 2 道**（64.3 分并列），第 3 道是 `random_min_choices=3` 补齐进来的 —— 它比 band 下沿低了 7.9 分。

→ **用户一旦录入食材，雨天晚饭就只剩 2–3 道菜可抽，而且全是汤。**
→ 这正是 ② 触发率 100% / ③ 触发率 0% 的原因（抽到的 3 道全是 ratio 高的）。
→ **不是 R-09 上线才塌，是基线就塌。** 修复的目标就是把 band 从 3 拉回来。

##### 落差口径澄清（与 dev-engine-relax 对齐，2026-09-23）

dev-engine-relax 复跑后报 S1 落差 **12.92** / S2 **11.75**，与我上表的 7.92 / 6.75 差 **整好 5.0**。
核对后确认：**两个数都对，差的就是 `random_band`，是定义分歧不是数据分歧。**

| 口径 | 定义 | S1 | S2 |
|---|---|---:|---:|
| **我的（门槛口径）** | `(best − random_band) − 带外第一道` | **7.92** | **6.75** |
| **他的（总落差口径）** | `best − 带外第一道` | 12.92 | 11.75 |

验算（两边用的是**同一个**"带外第一道"分数 51.38 / 52.55，`best` 同为 64.30）：
`64.30 − 5.0 = 59.30`；`59.30 − 51.38 = 7.92` ✓；`59.30 − 52.55 = 6.75` ✓
恒等式：**`总落差 = 门槛落差 + random_band`**，两个快照都成立。

> **结论：两个口径都保留，但必须改名**，否则改 R-09 时会拿着两个数互相以为对方错了。
> - `gap_to_threshold`（门槛口径）—— 回答"**补齐机制有没有被激活**"，是判塌缩的主口径
> - `spread_to_next`（总落差口径）—— 回答"头部和第三名差多少"，作辅助记录

**🔴 顺带一个比口径更重要的结论 —— `band_size` 这个数本身会骗人：**

S1/S2 的 `band_size = 3` **恰好等于 `random_min_choices`**，说明真带（`score >= best − random_band`）只有 **2 道**，
第 3 道是 `decision_service._random_band` 的**不足 3 道按分数补齐**逻辑硬塞进来的 —— 它比门槛低了 7.9 分。

→ **所以 R-09 的验收判据绝不能写成 `band_size ≥ 3`**（在 `random_min_choices=3` 下**恒真**，padding 会把塌缩完全掩盖）。
→ 必须写成 **`band_size > random_min_choices`**，或让脚本额外输出 `natural_band_size`（只数 `score >= best − random_band` 的个数）并以它为准。
→ 这一条同样适用于 J3 / 验收⑦ / 门禁脚本：**凡是拿 `band_size` 当判据的地方，都要先减去 padding 的影响。**

##### `hits` 分布 —— 给 `INVENTORY_HITS_FULL` 定值用的预备数据

新结构 `score += score_inventory * min(1.0, hits / INVENTORY_HITS_FULL)` 的初值是 `FULL=3` / `score_inventory=5.0`。
实测 hits 分布（**注意这是预备数据，不是正式复跑判定**）：

| hits | S1 菜数 | S2 菜数 |
|---:|---:|---:|
| 0 | 234 (68.4%) | 148 (43.3%) |
| 1 | 99 (28.9%) | 125 (36.5%) |
| 2 | 8 (2.3%) | 54 (15.8%) |
| 3 | 1 (0.3%) | 11 (3.2%) |
| 4 | 0 | 4 (1.2%) |

**取各 FULL 值时「拿满分」的菜占比**：

| FULL | S1 拿满 | S2 拿满 |
|---:|---:|---:|
| 1 | 108 (31.6%) | 194 (56.7%) |
| 2 | 9 (2.6%) | 69 (20.2%) |
| **3（初值）** | **1 (0.3%)** | **15 (4.4%)** |
| 4 | 0 | 4 (1.2%) |

⚠️ **一个必须现在提出的矛盾**（否则 dev-engine-relax 按 `FULL=3` 写完要返工）：

- **`FULL=3` 在真实小冰箱（S1）下只有 1 道菜能拿满 = 0.3%** → `score_inventory` 几乎恒为 0，**R-09 等于没接线**。
- **`FULL=1` 才有效**（S1 31.6% / S2 56.7% 拿满），但它会让加分变成**二元型 `+5.0`** ——
  而 `5.0 == random_band`，**正好踩在塌缩临界点上，没有任何余量**，且 `_weather_score` 还会往上叠。

→ 建议在落地前就把这个权衡摆到桌面上：**要么 `FULL` 取 1–2 并接受它是二元加分（需把幅度压到 <5.0，比如 3.0）；
要么保留连续型，但改用 `hits / min(len(need), K)` 这类仍连续的分母。** 正式判定等落地后复跑，
**这条只是避免返工的预警**。

## 附录 A：本次实跑的全部 SQL

```sql
-- A1 覆盖率主查询
SELECT COUNT(*) total, COUNT(cook_minutes), COUNT(NULLIF(meal_slots,'')), COUNT(NULLIF(meat_type,'')),
  COUNT(NULLIF(tools,'')), COUNT(NULLIF(season,'')), COUNT(spice_level), COUNT(is_light),
  COUNT(NULLIF(tags,'')), COUNT(NULLIF(flavor_tags,'')), COUNT(NULLIF(category,'')),
  COUNT(NULLIF(main_ingredient,'')), COUNT(calories), COUNT(protein_g), COUNT(carb_g), COUNT(fat_g),
  COUNT(NULLIF(steps,'')), COUNT(NULLIF(quick_steps,'')), COUNT(NULLIF(cover_text,'')),
  COUNT(NULLIF(cuisine,'')), COUNT(difficulty) FROM recipe;

-- A2 空数组剔除（对 meal_slots/tools/season/tags/flavor_tags/quick_steps 各跑一次）
SELECT 'meal_slots' f, COUNT(*) total,
  SUM(meal_slots IS NULL OR meal_slots='' OR meal_slots='[]') n_empty,
  SUM(meal_slots IS NOT NULL AND meal_slots<>'' AND meal_slots<>'[]') n_usable FROM recipe;

-- A3 JSON 数组取值分布
SELECT j.v val, COUNT(*) c FROM recipe r,
  JSON_TABLE(r.meal_slots,'$[*]' COLUMNS(v VARCHAR(30) PATH '$')) j
WHERE r.meal_slots IS NOT NULL AND r.meal_slots<>'[]' GROUP BY j.v ORDER BY c DESC;

-- A4 富集状态
SELECT enrich_status, COUNT(*) FROM recipe GROUP BY enrich_status;          -- done 52 / partial 337 / pending 7
SELECT enrich_source, COUNT(*) FROM recipe GROUP BY enrich_source;          -- rule 389 / NULL 7  (llm 0)
SELECT steps_source, COUNT(*) FROM recipe GROUP BY steps_source;            -- NULL 396

-- A5 候选池压力测试
SELECT COUNT(*) FROM recipe WHERE meal_slots LIKE '%breakfast%' AND cook_minutes<=15;                    -- 7
SELECT COUNT(*) FROM recipe WHERE meal_slots LIKE '%lunch%' AND cook_minutes<=30 AND category='荤菜';     -- 6
SELECT COUNT(*) FROM recipe WHERE (is_light=1 OR meal_slots LIKE '%late_night%') AND cook_minutes<=20;   -- 19
SELECT COUNT(*) FROM recipe WHERE season LIKE '%spring%';                                                -- 0
SELECT COUNT(*) FROM recipe WHERE season LIKE '%autumn%';                                                -- 0
SELECT COUNT(*) FROM recipe WHERE tools IS NOT NULL AND tools<>'[]'
  AND season IS NOT NULL AND season<>'[]' AND meal_slots IS NOT NULL AND meal_slots<>'[]';               -- 3

-- A6 词表错位验证
SELECT cuisine, COUNT(*) c FROM recipe GROUP BY cuisine ORDER BY c DESC;
SELECT id, user_id, cuisines FROM diet_preference;
SELECT COUNT(*) FROM recipe WHERE cuisine IN ('川湘','粤菜','江浙','家常','日料','西北','西餐','川菜','日韩');  -- 2

-- A7 厨具词表错位验证
SELECT j.v equip, COUNT(*) c FROM household h,
  JSON_TABLE(h.kitchen_equipments,'$[*]' COLUMNS(v VARCHAR(50) PATH '$')) j
WHERE h.kitchen_equipments IS NOT NULL AND h.kitchen_equipments<>'[]' GROUP BY j.v;
-- 灶台2 微波炉2 空气炸锅2 蒸锅1 烤箱1 电饭煲1 压力锅1   (vs recipe.tools: pot/steamer/oven/air_fryer)

-- A8 派生能力
SELECT COUNT(*) rows, COUNT(DISTINCT recipe_id) recipes_covered FROM recipe_ingredient;   -- 2776 / 373
SELECT COUNT(*) ingredients, COUNT(reference_price) has_price FROM ingredient;            -- 771 / 66
SELECT COUNT(*) FROM fridge_inventory;      -- 0
SELECT COUNT(*) FROM consumption_record;   -- 0
SELECT COUNT(*) FROM decision_feedback;    -- 0

-- A9 决策日志
SELECT COUNT(*) n, COUNT(DISTINCT recipe_id) dishes, COUNT(DISTINCT user_id) users FROM decision_log;  -- 190/127/8
SELECT SUM(payload LIKE '%"relaxed": true%') relaxed_true, COUNT(*) total FROM decision_log;           -- 36/190
SELECT meal_slot, SUM(payload LIKE '%"relaxed": true%'), COUNT(*) FROM decision_log GROUP BY meal_slot;
SELECT accepted, COUNT(*) FROM decision_log GROUP BY accepted;                                         -- NULL 162 / 1 → 28
SELECT reason, COUNT(*) c FROM decision_log GROUP BY reason ORDER BY c DESC LIMIT 12;

-- A10 列错位 / 非菜品污染验证
SELECT source, COUNT(*) c FROM recipe GROUP BY source ORDER BY c DESC;   -- proj_kitchen 338 / howtocook 34 / ai_generated 24
SELECT source, cuisine, COUNT(*) c FROM recipe GROUP BY source, cuisine ORDER BY source, c DESC;
SELECT COUNT(*) FROM recipe WHERE cuisine IN ('饮品','甜品','调味品','半成品加工','半成品','调料');  -- 61
SELECT d.dish_name, r.cuisine, r.category, COUNT(*) times FROM decision_log d
  JOIN recipe r ON r.id=d.recipe_id
  WHERE r.cuisine IN ('饮品','甜品','调味品','半成品加工','半成品','调料','早餐')
  GROUP BY d.dish_name, r.cuisine, r.category ORDER BY times DESC;        -- 已推荐 18 次
SELECT COUNT(*) FROM recipe WHERE cook_minutes=22;                        -- 119 (= CATEGORY_MINUTES['荤菜'])

-- A11 压测数据识别
SELECT user_id, decision_date, COUNT(*) decisions, MIN(created_at), MAX(created_at),
       TIMESTAMPDIFF(SECOND, MIN(created_at), MAX(created_at)) span_sec
FROM decision_log GROUP BY user_id, decision_date ORDER BY decision_date, user_id;
-- 单用户单日最高 58 次 / 246 秒；2026-09-22 id186-190 在 4 秒内连出 5 条 → 联调/压测，非真实行为
```

## 附录 D：夜宵口径修正 —— 验收 SQL + 极限压测 SQL（可整段复制执行）

```sql
-- ============================================================
-- D1 验收断言集（只读。改前/改后各跑一次，逐条对照）
-- ============================================================

-- A. 改后池（期望 45）
SELECT COUNT(*) AS pool_after FROM recipe
WHERE is_dish = 1
  AND ( is_light = 1 OR category IN ('主食','面食') )
  AND COALESCE(cook_minutes, 0) <= 20;

-- A2. 改前池（期望 16）
SELECT COUNT(*) AS pool_before FROM recipe
WHERE is_dish = 1 AND is_light = 1 AND COALESCE(cook_minutes, 0) <= 20;

-- A3. 增量拆解（期望 16 / 29 / 45）
SELECT SUM(is_light = 1) AS by_is_light,
       SUM(is_light <> 1 OR is_light IS NULL) AS by_whitelist,
       COUNT(*) AS total
FROM recipe
WHERE is_dish = 1
  AND ( is_light = 1 OR category IN ('主食','面食') )
  AND COALESCE(cook_minutes, 0) <= 20;

-- A4. ≤15min 收紧口径（期望 34 / 45）—— 证明 R-22 收紧不会击穿夜宵池
SELECT SUM(COALESCE(cook_minutes,0) <= 15) AS le15,
       SUM(COALESCE(cook_minutes,0) <= 20) AS le20
FROM recipe
WHERE is_dish = 1 AND ( is_light = 1 OR category IN ('主食','面食') );

-- B. 会被 R-11 meal_slots 软惩罚吃掉多少（期望 NULL 25 / 含 late_night 3 / 只有早午 17）
SELECT CASE
         WHEN meal_slots IS NULL OR meal_slots='' OR meal_slots='[]' THEN '1_NULL'
         WHEN meal_slots LIKE '%late_night%'                          THEN '2_含late_night'
         WHEN meal_slots LIKE '%dinner%'                              THEN '3_含dinner'
         ELSE                                                              '4_只有早/午'
       END AS bucket, COUNT(*) AS n
FROM recipe
WHERE is_dish = 1
  AND ( is_light = 1 OR category IN ('主食','面食') )
  AND COALESCE(cook_minutes, 0) <= 20
GROUP BY bucket ORDER BY bucket;

-- B2. 只看被白名单救回的 29 道（期望 9 / 3 / 17）
SELECT CASE
         WHEN meal_slots IS NULL OR meal_slots='' OR meal_slots='[]' THEN '1_NULL'
         WHEN meal_slots LIKE '%late_night%'                          THEN '2_含late_night'
         WHEN meal_slots LIKE '%dinner%'                              THEN '3_含dinner'
         ELSE                                                              '4_只有早/午'
       END AS bucket, COUNT(*) AS n
FROM recipe
WHERE is_dish = 1 AND ( is_light <> 1 OR is_light IS NULL )
  AND category IN ('主食','面食') AND COALESCE(cook_minutes, 0) <= 20
GROUP BY bucket ORDER BY bucket;

-- C. ⚠️ 修订版回归护栏（不是"恒为 0"，是"≤20min 口径下恒为 0"）
SELECT COUNT(*) FROM recipe WHERE is_light=1 AND category IN ('主食','面食');                                  -- 基线 3（3 道粥，合法）
SELECT COUNT(*) FROM recipe WHERE is_light=1 AND category IN ('主食','面食') AND COALESCE(cook_minutes,0)<=20;  -- 必须 0，且不得增加

-- C2. 反向护栏：不得把重口味荤菜放进夜宵池（期望 0）
SELECT COUNT(*) FROM recipe
WHERE is_dish = 1 AND ( is_light = 1 OR category IN ('主食','面食') )
  AND COALESCE(cook_minutes, 0) <= 20 AND category = '荤菜' AND is_light <> 1;

-- D. 分类构成（期望 面食20/主食9/凉菜7/素菜6/荤菜3）
SELECT category, COUNT(*) n, SUM(is_light = 1) light_n
FROM recipe
WHERE is_dish = 1 AND ( is_light = 1 OR category IN ('主食','面食') )
  AND COALESCE(cook_minutes, 0) <= 20
GROUP BY category ORDER BY n DESC;

-- E. 人工抽查：改后池前 20 道
SELECT name, category, cook_minutes, is_light, COALESCE(meal_slots,'NULL') meal_slots
FROM recipe
WHERE is_dish = 1 AND ( is_light = 1 OR category IN ('主食','面食') )
  AND COALESCE(cook_minutes, 0) <= 20
ORDER BY is_light DESC, cook_minutes ASC, name LIMIT 20;

-- ============================================================
-- D2 极限压测：真实用户池 = 口径 ∩ 忌口 ∩ 近7天不重复
-- ============================================================

-- I. 单个忌口词杀伤力（近似 c.haystack 子串匹配）
SELECT w.word AS avoid_word, COUNT(*) AS hit_in_45, ROUND(COUNT(*)/45*100,1) AS pct, 45-COUNT(*) AS survivors
FROM (SELECT '辣' AS word UNION ALL SELECT '花生' UNION ALL SELECT '香菜' UNION ALL SELECT '葱'
      UNION ALL SELECT '蒜' UNION ALL SELECT '鸡蛋' UNION ALL SELECT '蛋' UNION ALL SELECT '牛奶'
      UNION ALL SELECT '虾' UNION ALL SELECT '豆腐' UNION ALL SELECT '木耳' UNION ALL SELECT '猪肉'
      UNION ALL SELECT '牛肉' UNION ALL SELECT '鸡') w
JOIN recipe r
  ON r.is_dish = 1
 AND ( r.is_light = 1 OR r.category IN ('主食','面食') )
 AND COALESCE(r.cook_minutes, 0) <= 20
 AND CONCAT_WS('|', r.name, COALESCE(r.main_ingredient,''), COALESCE(r.tags,''),
                    COALESCE(r.flavor_tags,''), COALESCE(r.cuisine,'')) LIKE CONCAT('%', w.word, '%')
GROUP BY w.word ORDER BY hit_in_45 DESC;
-- 实跑：辣 11 / 鸡 7 / 蛋 7 / 鸡蛋 6 / 蒜 3 / 葱 2 / 木耳 2 / 豆腐 1 / 牛奶 1 / 猪肉 1

-- I4. 极限：忌 辣+鸡+蛋 且 近 7 天已吃 12 道 → 新口径 20，旧口径 4
SELECT COUNT(*) AS survivors_new FROM recipe
WHERE is_dish = 1 AND ( is_light = 1 OR category IN ('主食','面食') ) AND COALESCE(cook_minutes,0) <= 20
  AND CONCAT_WS('|', name, COALESCE(main_ingredient,''), COALESCE(tags,''), COALESCE(flavor_tags,''), COALESCE(cuisine,'')) NOT LIKE '%辣%'
  AND CONCAT_WS('|', name, COALESCE(main_ingredient,''), COALESCE(tags,''), COALESCE(flavor_tags,''), COALESCE(cuisine,'')) NOT LIKE '%鸡%'
  AND CONCAT_WS('|', name, COALESCE(main_ingredient,''), COALESCE(tags,''), COALESCE(flavor_tags,''), COALESCE(cuisine,'')) NOT LIKE '%蛋%'
  AND name NOT IN (SELECT name FROM (SELECT name FROM recipe
        WHERE is_dish = 1 AND ( is_light = 1 OR category IN ('主食','面食') ) AND COALESCE(cook_minutes,0) <= 20
        ORDER BY cook_minutes ASC LIMIT 12) t);                                          -- 20

SELECT COUNT(*) AS survivors_old FROM recipe
WHERE is_dish = 1 AND is_light = 1 AND COALESCE(cook_minutes,0) <= 20
  AND CONCAT_WS('|', name, COALESCE(main_ingredient,''), COALESCE(tags,''), COALESCE(flavor_tags,''), COALESCE(cuisine,'')) NOT LIKE '%辣%'
  AND CONCAT_WS('|', name, COALESCE(main_ingredient,''), COALESCE(tags,''), COALESCE(flavor_tags,''), COALESCE(cuisine,'')) NOT LIKE '%鸡%'
  AND CONCAT_WS('|', name, COALESCE(main_ingredient,''), COALESCE(tags,''), COALESCE(flavor_tags,''), COALESCE(cuisine,'')) NOT LIKE '%蛋%'
  AND name NOT IN (SELECT name FROM (SELECT name FROM recipe
        WHERE is_dish = 1 AND is_light = 1 AND COALESCE(cook_minutes,0) <= 20
        ORDER BY cook_minutes ASC LIMIT 12) t);                                          -- 4  🔴

-- ============================================================
-- D3 tags "夜宵" 是死标签（增量 0，全部超时）
-- ============================================================
SELECT COUNT(*) tagged, SUM(is_dish=1) is_dish_1,
       SUM(is_dish=1 AND COALESCE(cook_minutes,0)<=20) enters_20,
       SUM(is_dish=1 AND COALESCE(cook_minutes,0)<=25) enters_25,
       SUM(is_light=1) also_light, SUM(category IN ('主食','面食')) also_staple
FROM recipe WHERE tags LIKE '%夜宵%';   -- 13 / 12 / 0 / 3 / 13 / 3  → 增量 0，别加进白名单

SELECT COALESCE(cook_minutes,0) minutes, COUNT(*) n,
       SUM(is_light=1) by_light, SUM(category IN ('主食','面食') AND is_light=0) by_whitelist
FROM recipe WHERE is_dish=1 AND ( is_light=1 OR category IN ('主食','面食') ) AND COALESCE(cook_minutes,0) <= 30
GROUP BY COALESCE(cook_minutes,0) ORDER BY minutes;
-- 8:1 / 10:15 / 12:4 / 15:14 / 20:11 / 22:3 / 25:29 / 30:1  ← 25min 那一档有 29 道，是 CATEGORY_MINUTES['主食']=25 的基准值堆积
```

-- ============================================================
-- D4 meal_slots 硬过滤 vs 软惩罚（决定 ladder 档数）
-- ============================================================
SELECT COALESCE(meal_slots,'NULL') AS meal_slots, COUNT(*) AS n
FROM recipe WHERE is_dish = 1 GROUP BY COALESCE(meal_slots,'NULL') ORDER BY n DESC;
-- 267 / 46 / 24 / 5  → 有值 75 = 21.9%

-- 硬过滤下四时段放行量（空值放行）
SELECT 'breakfast'  AS slot, COUNT(*) FROM recipe WHERE is_dish=1 AND (meal_slots IS NULL OR meal_slots='' OR meal_slots='[]' OR meal_slots LIKE '%breakfast%')
UNION ALL SELECT 'lunch',      COUNT(*) FROM recipe WHERE is_dish=1 AND (meal_slots IS NULL OR meal_slots='' OR meal_slots='[]' OR meal_slots LIKE '%lunch%')
UNION ALL SELECT 'dinner',     COUNT(*) FROM recipe WHERE is_dish=1 AND (meal_slots IS NULL OR meal_slots='' OR meal_slots='[]' OR meal_slots LIKE '%dinner%')
UNION ALL SELECT 'late_night', COUNT(*) FROM recipe WHERE is_dish=1 AND (meal_slots IS NULL OR meal_slots='' OR meal_slots='[]' OR meal_slots LIKE '%late_night%');
-- 313 / 313 / 296 / 272   → "0 空结果" 恒真，不可证伪

-- 🔴 决定性：夜宵池在硬过滤下 45 → 28
SELECT COUNT(*) FROM recipe
WHERE is_dish=1 AND ( is_light=1 OR category IN ('主食','面食') ) AND COALESCE(cook_minutes,0)<=20
  AND ( meal_slots IS NULL OR meal_slots='' OR meal_slots='[]' OR meal_slots LIKE '%late_night%' );   -- 28

-- 被删的 17 道（正是白名单救回的面）
SELECT name, category, cook_minutes, meal_slots FROM recipe
WHERE is_dish=1 AND ( is_light=1 OR category IN ('主食','面食') ) AND COALESCE(cook_minutes,0)<=20
  AND meal_slots IS NOT NULL AND meal_slots<>'' AND meal_slots<>'[]' AND meal_slots NOT LIKE '%late_night%'
ORDER BY cook_minutes;

-- C 方案回填目标集（26 道需追加 late_night，3 道已有）
SELECT COUNT(*) FROM recipe
WHERE is_dish=1 AND category IN ('主食','面食') AND COALESCE(cook_minutes,0)<=20
  AND COALESCE(meal_slots,'') NOT LIKE '%late_night%';                                                -- 26

## 附录 E：定稿指标 SQL（ladder 5 档 0–4，2026-09-23 team-lead 裁决后）

> **本节是唯一可引用的定稿版本。** 附录 A / D 中若有按 6 档、7 档写的数字，一律以本节为准。
> **铁律：所有阈值按常量名引用，禁止写字面量。**

```sql
-- ============================================================
-- E0 常量（前后端同源，test_decide_parity.py 钉死双端相等）
-- ============================================================
-- RELAX_LEVEL_NONE            = 0
-- RELAX_LEVEL_COOK_CAP        = 1
-- RELAX_LEVEL_CATEGORY_SPREAD = 2   ← J3 起算点
-- RELAX_LEVEL_MAIN_INGREDIENT = 3
-- RELAX_LEVEL_NO_REPEAT       = 4   ← J3c 红线

-- ============================================================
-- E1 J3 / J3b / J3c（替换旧的 "relaxed=true 占比"）
-- ============================================================
SELECT
    COUNT(*)                                                          AS total,
    SUM(relaxed_level >= 2)                                           AS j3_n,      -- RELAX_LEVEL_CATEGORY_SPREAD
    SUM(relaxed_level >= 2) / COUNT(*)                                AS j3_rate,   -- 目标 ≤ 8%
    SUM(relaxed_level >= 1)                                           AS j3b_n,     -- 观测，不设目标
    SUM(relaxed_level >= 4)                                           AS j3c_n,     -- RELAX_LEVEL_NO_REPEAT
    SUM(relaxed_level >= 4) / COUNT(*)                                AS j3c_rate   -- 目标 ≤ 1%
FROM decision_log
WHERE created_at >= :from AND created_at < :to;

-- J3-夜宵降档 ≤20%
SELECT SUM(relaxed_level >= 2) / COUNT(*) AS j3_night_rate
FROM decision_log
WHERE meal_slot = 'late_night'
  AND created_at >= :from AND created_at < :to;

-- J3c 单日红线：任一单日 >0 立即告警
SELECT decision_date,
       SUM(relaxed_level >= 4) AS breach_n
FROM decision_log
GROUP BY decision_date
HAVING breach_n > 0;

-- ============================================================
-- E2 J6' / J7'（替换已作废的「四时段 0 空结果」——那条是恒真的）
-- ============================================================
-- J6' = candidate_count 按 meal_slot 分组的 P10，夜宵档 ≥ 8
--   注意 candidate_count 必须是【放宽之前】的池子大小，否则会被阶梯撑大、判据失效
SELECT meal_slot,
       MIN(cc) AS p10_approx,                          -- 精确 P10 建议在应用层算，这里给近似
       AVG(cc) AS mean_cc
FROM (
    SELECT meal_slot, candidate_count AS cc,
           ROW_NUMBER() OVER (PARTITION BY meal_slot ORDER BY candidate_count) AS rn,
           COUNT(*)    OVER (PARTITION BY meal_slot)                           AS n
    FROM decision_log
    WHERE created_at >= :from AND created_at < :to
) t
WHERE rn <= CEIL(n * 0.10)
GROUP BY meal_slot;
-- 期望: late_night 的 P10 ≥ 8

-- J7' = candidate_count < 8 的占比，按 meal_slot 分档 ≤ 5%
SELECT meal_slot,
       SUM(candidate_count < 8) / COUNT(*) AS below_waterline_rate
FROM decision_log
WHERE created_at >= :from AND created_at < :to
GROUP BY meal_slot;
-- 期望: 各档 ≤ 5%

-- ============================================================
-- E3 可比性兜底：用 candidate_count 事后重算 "=0" 旧口径
-- ============================================================
SELECT COUNT(*) AS would_relax_under_old_rule
FROM decision_log
WHERE candidate_count = 0
  AND created_at >= :from AND created_at < :to;
-- 这样旧口径(relaxed=true)与新口径(relaxed_level>=1)永远可以对齐，不需要靠约定

-- ============================================================
-- E4 R-24 夜宵口径修正 —— 数据侧验收（纯 SQL，不依赖 R-10，现在可跑）
-- ============================================================
SELECT COUNT(*) AS pool_after FROM recipe
WHERE is_dish = 1 AND ( is_light = 1 OR category IN ('主食','面食') )
  AND COALESCE(cook_minutes,0) <= 20;                                   -- 期望 45

SELECT COUNT(*) AS pool_before FROM recipe
WHERE is_dish = 1 AND is_light = 1 AND COALESCE(cook_minutes,0) <= 20;  -- 期望 16（改前）

-- 回归护栏（修订版：不加时间条件是 3，加 ≤20min 必须 0 且不得增加）
SELECT COUNT(*) FROM recipe WHERE is_light=1 AND category IN ('主食','面食');                                   -- 基线 3（3 道粥，合法）
SELECT COUNT(*) FROM recipe WHERE is_light=1 AND category IN ('主食','面食') AND COALESCE(cook_minutes,0)<=20;   -- 必须 0

-- ============================================================
-- ============================================================
-- E5 O2（线上观测，唯一下限明确的一条）与 O1（离线断言，线上不设）
--    定值依据见 §5.2(12) 的离线蒙特卡洛（N=500，只读）
-- ============================================================

-- O2 = 晚饭档 汤羹 占比 ≤ 30%，样本下限 300
--   正常区间 5.6%–23.8%，塌缩区间 64.8%–77.0% —— 职责是抓塌缩，不是调味
SELECT COUNT(*) AS n,                                    -- 必须 ≥ 300，否则输出"样本不足、暂不判定"
       SUM(category = '汤羹') / COUNT(*) AS soup_share
FROM decision_log
WHERE meal_slot = 'dinner'
  AND created_at >= :from AND created_at < :to;
-- 期望 ≤ 0.30；> 0.30 说明二元打分幅度超过 random_band，抽签带被垄断

-- O1（离线断言）：主面占比 ≥ 基线 × 0.75
--   线上不设 —— 基线随历史漂移（实测空历史 12.8% ↔ 荤菜×1 40.0%），无法在线归一化
--   离线用固定历史（空历史 / 荤菜×1）跑 N=500，断言 ≥ 基线 × 0.75
--   实测 +3/0 时：0.95（空历史）、0.85（荤菜×1）✅

-- ⚠️ 已作废：本文早先给的 "晚饭档主面占比 ≥15%" —— 那是拿原始池占比 20.5% 推的，
--    但打分后 band 内分布 ≠ 原始池分布（实测基线仅 12.8%），会在基线误报。
```

## 附录 G：R-09 快选词表定稿 SQL（可直接贴 PRD）

```sql
-- 前提: ingredient.category 91.6% 为 NULL, 不能用来排除调味料, 必须走显式黑名单。
-- 分母: is_dish = 1 (342 道)

SELECT i.name,
       COUNT(DISTINCT ri.recipe_id)                       AS dishes,
       ROUND(COUNT(DISTINCT ri.recipe_id) / 342 * 100, 1) AS pct
FROM recipe_ingredient ri
JOIN ingredient i ON i.id = ri.ingredient_id
JOIN recipe r     ON r.id = ri.recipe_id
WHERE COALESCE(r.is_dish, 1) = 1
  AND i.name NOT IN (   -- 调味料/辅料黑名单（不含洋葱: 洋葱是真蔬菜且覆盖 29 道）
    '盐','食盐','食用油','油','糖','白糖','冰糖','白砂糖','生抽','老抽','酱油',
    '香油','淀粉','水淀粉','生粉','料酒','黄酒','白酒','白胡椒','黑胡椒','胡椒','胡椒粉',
    '白胡椒粉','蚝油','姜','生姜','姜片','姜末','姜丝','蒜','大蒜','蒜瓣','蒜头','蒜末','蒜片',
    '葱','大葱','小葱','香葱','葱花','葱段','葱白','葱姜',
    '水','清水','温水','开水','冷水','热水','冰水','饮用水','高汤','骨头汤',
    '鸡精','味精','八角','桂皮','香叶','花椒','干辣椒','辣椒','辣椒面','小米辣','小米椒',
    '醋','陈醋','白醋','香醋','米醋','豆瓣酱','番茄酱','沙拉酱','芝麻','芝麻油','黄油',
    '五香粉','孜然','孜然粉','十三香','蜂蜜','芥末','咖喱粉'
  )
GROUP BY i.name
ORDER BY dishes DESC
LIMIT 12;
-- 结果: 鸡蛋67 / 土豆21 / 青椒17 / 胡萝卜16 / 五花肉15 / 香菜13 / 面粉13
--       番茄12 / 排骨11 / 猪肉8 / 黄瓜8 / 豆腐7

-- 累计覆盖 —— 双分母并列（2026-09-23 定稿口径，只报一个百分比一定会打架）
-- D1 候选池口径（效果评估用）
SELECT 'D1' AS denom, 342 AS denom_n,
       COUNT(DISTINCT ri.recipe_id) AS covered          -- 164
FROM recipe_ingredient ri
JOIN ingredient i ON i.id = ri.ingredient_id
JOIN recipe r     ON r.id = ri.recipe_id
WHERE COALESCE(r.is_dish, 1) = 1
  AND i.name IN ('鸡蛋','土豆','青椒','胡萝卜','五花肉','香菜','面粉','番茄','排骨','猪肉','黄瓜','豆腐');
-- → 164 / 342 = 48.0%

-- D2 词表质量口径（不限 is_dish，分母 = 有食材行的菜 373）
SELECT 'D2' AS denom, 373 AS denom_n,
       COUNT(DISTINCT ri.recipe_id) AS covered          -- 175
FROM recipe_ingredient ri
JOIN ingredient i ON i.id = ri.ingredient_id
WHERE i.name IN ('鸡蛋','土豆','青椒','胡萝卜','五花肉','香菜','面粉','番茄','排骨','猪肉','黄瓜','豆腐');
-- → 175 / 373 = 46.9%

-- 两个分母的本体
SELECT COUNT(*) FROM recipe WHERE COALESCE(is_dish,1)=1;               -- 342
SELECT COUNT(DISTINCT recipe_id) FROM recipe_ingredient;               -- 373

-- 🔴 R-09 覆盖率天花板：候选池里没有任何食材行的菜（勾什么都不会命中）
SELECT COUNT(*) AS no_ingredient_row                                   -- 21
FROM recipe r
WHERE COALESCE(r.is_dish,1)=1
  AND NOT EXISTS (SELECT 1 FROM recipe_ingredient ri WHERE ri.recipe_id = r.id);
-- → 可达上限 = (342-21)/342 = 321/342 = 93.9%

-- 补「西红柿」后的 13 词（净新增只有 2 道 → 信任缺口，不是覆盖率缺口）
SELECT COUNT(DISTINCT ri.recipe_id) AS covered_13                      -- 166
FROM recipe_ingredient ri
JOIN ingredient i ON i.id = ri.ingredient_id
JOIN recipe r     ON r.id = ri.recipe_id
WHERE COALESCE(r.is_dish, 1) = 1
  AND i.name IN ('鸡蛋','土豆','青椒','胡萝卜','五花肉','香菜','面粉','番茄','排骨','猪肉','黄瓜','豆腐','西红柿');
-- → 166 - 164 = 净新增 2 道 = +0.6pt

-- 同义词未归一核查（会吃掉命中率）
SELECT i.name, COUNT(DISTINCT ri.recipe_id) AS dishes
FROM recipe_ingredient ri
JOIN ingredient i ON i.id = ri.ingredient_id
JOIN recipe r     ON r.id = ri.recipe_id
WHERE COALESCE(r.is_dish, 1) = 1
  AND i.name IN ('番茄','西红柿','土豆','马铃薯','青椒','柿子椒','灯笼椒',
                 '猪肉','五花肉','瘦肉','豆腐','嫩豆腐','老豆腐','白菜','娃娃菜','小白菜','大白菜')
GROUP BY i.name ORDER BY dishes DESC;
-- 番茄 12 / 西红柿 9 → 合计去重 21, 但子串匹配互不相通, 选一个只拿一半
```

## 附录 B：数据来源与可信度声明

| 项 | 说明 |
|---|---|
| 数据库 | MySQL 8.0.46，本机 :3306，库 `meal_planner`，连接串取自项目根 `.env` 的 `APP__DATABASE__URL` |
| 操作类型 | **全程只读**：`SELECT` / `SHOW` / `COUNT`。**未执行任何 INSERT/UPDATE/ALTER/DROP** |
| 样本量 | recipe 396 道（全表，非抽样）；decision_log 190 行（全表） |
| 代码依据 | `backend/app/services/decision_service.py`(945行)、`dish_rules.py`(180行)、`intent_service.py`(458行)、`today_service.py`(384行)、`backend/app/config.py` `DecideSettings`(L119-160)、`backend/app/api/decide.py`、`frontend/src/components/DecideBoard.tsx`(208行) |
| ⚠️ 可信度警告 | `decision_log` 的 190 条为**联调/压测数据**（单用户单日 58 次决策、4 秒内连出 5 条），**不可用作用户行为基线**。其中 `accepted` 字段 85.3% 为 NULL，原因是前端「换一个」从不调 `feedback(false)`，属**埋点缺失**而非用户行为 |
| ⚠️ 未做 | 未连 LLM、未跑任何富集脚本、未修改任何数据 |

---

#### (17) 🔴 `score_cuisine` 归零**只覆盖了一条链路**：另外三条打分路径仍挂着同一枚死信号（2026-09-23 复核）

复盘 fix-cuisine-weight 的落地范围时发现的**覆盖缺口**。这不是返工指控，是"改了 A 没改 B"的完整性问题。

**已改对的（决策链路）**：

| 文件 | 现状 |
|---|---|
| `backend/app/config.py` L148 | `score_cuisine: float = 0.0` ✅（注释写明了归零理由与恢复条件） |
| `config/default.yaml` L71 | `score_cuisine: 0.0` ✅ |
| `shared/decide.ts` / `reason_service.py` | 文案侧 `GENERIC_CUISINE_LABELS` 白名单 ✅ |

**没改的（另外三条打分路径，用的是模块级硬编码常量，不走 `DecideSettings`，所以改 `default.yaml` 对它们无效）**：

| 文件 | 常量 | 幅度 | 用到的消费点 | 谁会看到 |
|---|---|---:|---|---|
| `backend/app/services/replacement_service.py` L65 | `SCORE_CUISINE` | **20.0** | L382 `recipe.cuisine in ctx.cuisines` | 🔴 **首页结果卡的「换一换」** |
| `backend/app/services/generation_service.py` L66 | `SCORE_CUISINE` | **20.0** | L684 本地编排打分（mixed 模式喂 LLM 短名单前 30） | 周菜单生成 |
| `backend/app/services/fridge_menu_service.py` L46 | `SCORE_CUISINE` | **5.0** | L312 冰箱菜单打分 | 冰箱菜单页 |

**危害分两层，当下的和未来的：**

**① 当下 —— 三条链路都在"假装在打分"**（与 §2.4 同一类病：权重占着，信号是空的）。
命中率 ≈ 0（`recipe.cuisine` = 荤菜/素菜/主食/早餐 vs `ctx.cuisines` = 粤菜/川菜/江浙…），20 分几乎永不加上。
`generation_service` L63 与 `replacement_service` L62 的注释还写着"与 decision_service 口径一致"——**现在不一致了**。

**② 未来 —— 这是个定时炸弹，不是死代码。**
`config.py` L146-147 写死了恢复路径："真菜系由凌晨 LLM 富集任务标注，回填后把这里恢复成 20.0"。
**但回填那一天，`replacement_service` 的 +20 会立刻从"永不触发"变成"命中即塌缩"**：

- `replacement_service.py` L76 有 `LOCAL_RANDOM_BAND = 5.0`，L334-338 是**和 `decision_service._random_band` 一模一样的机制**（`sort → top3 → [score >= best − band] → random.choice`）；
- `+20 >> 5.0` ⇒ 命中的那批菜**整批垄断抽签带**，与 §5.2(12) 通则完全同构；
- 而且它比 `decision_service` 更狠：**它只在 `LOCAL_TOP_K = 3` 里再切带**，池子本来就只有 3 道。

→ **即：cuisine 数据清洗上线的那天，「换一换」会当场塌缩，而决策链路因为权重从 0 起调反而是安全的。**
→ 这是典型的"修复本身制造了不对称"。

**建议（我不动手，等派单）：**

| 优先级 | 动作 |
|---|---|
| P1 | `replacement_service.SCORE_CUISINE` **20.0 → 0.0**（与 `config.py` 对齐），注释里挂上同一条恢复条件 |
| P2 | `generation_service.SCORE_CUISINE` **20.0 → 0.0**（无 random_band，不会塌缩，但口径要一致） |
| P3 | `fridge_menu_service.SCORE_CUISINE` **5.0 → 0.0**（幅度最小，但同为死信号） |
| P0（配套） | 三个常量的注释里**都必须写明"恢复条件 = cuisine 由 LLM 富集回填"**，否则下次清洗完只恢复 `config.py`，三条链路再次分叉 |
| 备选 | 若不想归零：至少把 `replacement_service` 的幅度压到 `< LOCAL_RANDOM_BAND`（建议 3.0，与 R-11 同值） |

**三条链路的调用链与选择机制（逐条核实，给 PRD 定"是否扩 R-08"用）**：

| 链路 | 入口证据 | 选择机制 | 有无 band |
|---|---|---|---|
| **换一换** | `api/menus.py:329` → `ReplacementService.replace()` → `_auto()` L201 → **L203 先走 `_pick_local`**，L204-207 命中即返回，AI(L212) 只是兜底 | L334-338 `sort → top[:3] → [score >= best − LOCAL_RANDOM_BAND] → random.choice` | ✅ **有，5.0** |
| **周菜单** | `api/menus.py:23`；`main.py:19` / `scheduler/jobs.py:38` 挂 `GenerationWorker` | `_score_recipe` L664 ← `_pick_for_slot` L411/L430 ← `compose_from_local` L439；另 L475 取前 `LOCAL_HINT_LIMIT=30` 喂 LLM | ❌ 无 |
| **冰箱菜单** | `api/menus.py:154` → `FridgeMenuService.rebuild` | `_pick_best` L254/L280，L267 注释原文"**取分最高的那一道 —— 重排要可预期，所以这里刻意不做随机**" | ❌ 无（argmax） |

**🔴 关键定性：三条全部用户可见，没有一条是"纯内部排序"。** 区别只在危害形态：

| 链路 | 用户可见 | 回填 cuisine 当天会不会塌缩 |
|---|---|---|
| 换一换 | ✅ **主路径** | 🔴 **会**（+20 >> band 5.0，且只在 top3 里再切带） |
| 周菜单 | ✅ | ❌ 不会，但会污染喂 LLM 的 hint 短名单 |
| 冰箱菜单 | ✅ | ❌ 不会，但会**确定性地**把命中菜系的菜顶到第一 |

**两个附带事实：**

1. `decision_service.py` L5-8 注释自己写明「不复用 `generation_service` 的任何打分 —— 那边的权重(热量50/库存30/菜系20)」，
   即**决策链路与生成链路本就是两套打分**。所以 `generation_service` L63 那句"与 replacement_service 口径一致"
   **从来只指 gen↔replacement，不包括 decision**；**但在 `SCORE_CUISINE` 这一项上它现在也已失效**（decision=0，gen/replacement=20）。
2. `backend/tests/test_decide_parity.py` L101-102 只断言 `DecideSettings().score_cuisine == 0` 与 `YAML_DECIDE["score_cuisine"] == 0`
   —— **双端一致性测试只守护 decision 链路，另外三条没有任何测试覆盖**。

> ⚠️ **本报告只做只读复核，未修改上述任何文件。** 这四个文件都不在我的所有权范围内，
> 按 team-lead 的冻结纪律，**报给你，不自己改**。

---

#### (18) A22 定标：`INVENTORY_HITS_FULL` 取值 + 两个连带发现（2026-09-23，真库 342 道实测）

R-09 落地后 `INVENTORY_HITS_FULL` 由 A22 定标。方法：构造 `Candidate`（真库 342 道 `is_dish=1`）→ 调 `DecisionService._score()` / `_random_band()`，**不调 `decide()`、零写入**。

##### ① `hits` 分布（决定"录几样算够"的取值区间）

`_inventory_hits` = 非 `_STAPLES` 食材中命中了几样。`_STAPLES` 只有 10 项（盐/食用油/糖/生抽/老抽/香油/淀粉/料酒/白胡椒/黑胡椒）。

| 库存集 | hits=0 | 1 | 2 | 3 | ≥4 | 命中≥1 |
|---|---:|---:|---:|---:|---:|---:|
| S1 鸡蛋/土豆/青椒（3 样） | **234** | 99 | 8 | 1 | 0 | 108 (31.6%) |
| S2 R-09 词表 12 词 | 148 | 125 | 54 | 11 | 4 | 194 (56.7%) |
| S3 S1+胡萝卜/五花肉/葱/姜/蒜（8 样） | 87 | 93 | 69 | 57 | 26 | 255 (74.6%) |

→ **真实小冰箱（3 样）下 `hits ≥ 2` 只有 9 道（2.6%），`hits ≥ 3` 只有 1 道。** 这是定 FULL 的关键约束。

##### ② FULL 扫描（dinner / clear / 空历史，342 池）

| 库存 | FULL | 加分档位 | 非零 | 拿满 | natural_band | 品类数 |
|---|---|---|---:|---:|---:|---:|
| S1 | **1** | 0 / 5.0 | 108 (31.6%) | 108 (31.6%) | **75** | 7 |
| S1 | **2** | 0 / 2.5 / 5.0 | 108 (31.6%) | 9 (2.6%) | 54 | 6 |
| S1 | **3** | 0 / 1.67 / 3.33 / 5.0 | 108 (31.6%) | **1 (0.3%)** | 54 | 6 |
| S1 | 4+ | 0 / 1.25 / 2.5 / 3.75 | 108 | **0** | 75 | 7 |
| S2 | 1 | 0 / 5.0 | 194 (56.7%) | 194 (56.7%) | 93 | 7 |
| S2 | **2** | 0 / 2.5 / 5.0 | 194 (56.7%) | 69 (20.2%) | 70 | 7 |
| S2 | 3 | 0 / 1.67 / 3.33 / 5.0 | 194 (56.7%) | 15 (4.4%) | 57 | 7 |
| S3 | 1 | 0 / 5.0 | 255 (74.6%) | **255 (74.6%)** | 109 | 7 |
| S3 | **2** | 0 / 2.5 / 5.0 | 255 (74.6%) | 162 (47.4%) | 95 | 7 |
| S3 | 3 | 0 / 1.67 / 3.33 / 5.0 | 255 (74.6%) | 93 (27.2%) | 79 | 7 |

**定标结论：`INVENTORY_HITS_FULL = 2`**

| 候选 | 为什么选/不选 |
|---|---|
| **FULL=2 ✅** | 小冰箱主流拿 **2.5/5（半档）**而非 33%；保留"1 样 < 2 样"的区分；大冰箱不会像 FULL=1 那样 74.6% 同分；三个库存集 natural_band 54/70/95 全健康 |
| FULL=1 ✗ | 完全二元，**S3 下 74.6% 的菜同分** → 大冰箱时库存信号区分度归零 |
| FULL=3 ✗ | 小冰箱只有 **1 道（0.3%）**拿满、8 道拿 3.33 → **R-09 在真实小冰箱下等于没接线** |
| FULL≥4 ✗ | 小冰箱/中冰箱拿满皆为 0，档位上限被压到 3.75 以下 → 库存信号整体缩水 |

> ⚠️ **FULL 的选择对 band 不敏感**（54–109 全在健康区），真正让"总是那几道菜"的是下面 ③，**不是 R-09**。

##### ③ 🔴🔴 连带发现：`_weather_score` 在 rain / snow / hot 三支**全部是硬分区**（与 R-09 无关，是存量问题）

`_weather_score` 是分档型打分：`ratio≥0.3 → +18.0`、`0.1≤ratio<0.3 → +9.0`、tags∩{汤羹,炖煮,一锅出,雨天} → `+10.8`（**单菜最高 28.8**）。
**每一档间距 9–10.8 分，是 `random_band=5.0` 的 2 倍。**

雨天加分命中面（S1，342 道）：`28.80 → 7 道 / 19.80 → 14 / 18.00 → 19 / 10.80 → 56 / 9.00 → 54 / **0.00 → 192 道（56.1%）**`
→ **0 分那 192 道在雨天整批出局。**

`natural_band`（dinner，FULL=2，342 池，空历史）：

| 库存 | clear | **rain** | **snow** | cold | **hot** |
|---|---:|---:|---:|---:|---:|
| S0 空 | 116 | **29** | **29** | 82 | **4** |
| S1 TOP3 | 54 | **9** | **9** | 50 | **4** |
| S2 12词 | 70 | **4** | **4** | 57 | **3** |

→ **S0 空库存 + rain 就已经塌到 29** ⇒ **与库存完全无关，`_weather_score` 自己的锅，R-09 之前就在。**
→ **hot 更狠：只剩 3–4 道**（且 `凉菜` 品类拿不到分 —— 减 20 只写在 **cold** 分支，`hot` 分支只认 tags 里的「清爽/凉拌」，不认「凉菜」品类，**方向写反了**）。
→ **cold 是唯一健康的一支**（82/50/57）。我 §5.2(14) 那次审计正是**只测了 cold 就标了"✅软"** —— 这是我第二次犯"用单一场景代表整个打分项"的错（第一次是 A22 v1 用内置 10 项 staples）。已在上表更正。

**早餐档同测**：`natural_band = 3`（= `random_min_choices`，即 padding 撑出来的），所有 FULL 一致 —— 与 §5.2(16) 的早餐硬分区是同一个问题。

**修法方向（我不动手）**：`_weather_score` 的三支都是**分档型**，按通则必须把档间距压到 `≤ random_band(5.0)`，或**改成连续型**（如 `score_weather × 命中信号强度`，强度 ∈[0,1]）。直接把 18.0 降到 5.0 会让天气几乎无感，**建议走连续型**。另 `hot` 分支的「凉菜」品类漏判需要单独修。

##### ④ 🔴 连带发现：葱姜蒜是"假命中"污染源

| 库存集 | 命中≥1 的菜数 | 占比 |
|---|---:|---:|
| 仅「葱」1 项 | 136 | **39.8%** |
| 仅「姜」1 项 | 111 | 32.5% |
| 仅「蒜」1 项 | 128 | 37.4% |
| 仅葱姜蒜 3 项 | 205 | **59.9%** |
| S1 + 葱姜蒜（6 样） | 252 | 73.7% |

→ **用户往冰箱里录「葱姜蒜」，等于让六成菜凭空获得库存加分。** 根因：`_STAPLES` 只有调味料 10 项，**葱/姜/蒜不在其中**，而它们几乎出现在每一道中式菜里。

⚠️ **但绝不能顺手改 `_STAPLES`**：`_inventory_ratio = hits / len(need)`，`need` 正是 `_needed_ingredients`（依赖 `_STAPLES`）的结果。
**改 `_STAPLES` 会同时改变分子和分母 → 直接击穿 dev-engine-relax 刚验证过的"天气加分 / 外卖文案触发率逐菜一致"基线。**
→ 若要修，**必须单独立项 + 重拍基线**，不能挂在 R-09 里。

##### ⑤ `FULL=2` 的重新定标触发线（dev-engine-relax 请求入库）

`FULL=2` 只有 `0 / 2.5 / 5.0` 三档，**命中 2 样与命中 3 样及以上同分**。所以一旦"命中≥2 的菜"占比过高，区分度会归零（与 FULL=1 在大冰箱下的毛病同形）。

**定触发线：`命中≥2 的菜占池比 ≥ 50% 即触发重新定标。`**

实测（342 道，库存按真实频次词表递增取样）：

| 冰箱规模 | 不含葱姜蒜 | 含葱姜蒜 |
|---|---|---|
| 3 样 | 2.6% ✅ | — |
| 5–6 样 | 7.0% ✅ | **43.6%** 🟠 |
| 8 样 | 15.5% ✅ | **47.4%** 🟠 |
| 11–12 样 | 20.2% ✅ | **52.3%** 🔴 |
| 15–16 样 | 28.7% ✅ | **55.8%** 🔴 |
| 20–23 样 | 31.0% ✅ | **59.1%** 🔴 |

🔴 **关键：这条线会不会被触发，几乎不由"用户录了多少样"决定，而由"用户录的东西里有没有葱姜蒜"决定。**
- 不含葱姜蒜：3 样 2.6% → 20 样 31.0%，**全程健康，永远不会触发**；
- 含葱姜蒜：**6 样就到 43.6%，11 样过半**。加葱姜蒜凭空多出的命中菜：3 样 +144 道（+42.1pp）、12 样 +75 道（+21.9pp）。

→ **所以「FULL=2 提前饱和」和「葱姜蒜假命中」是同一个根因的两副面孔，不是两件事。**
→ **扩 `_STAPLES`（把葱/姜/蒜纳入）同时解决两者**：不含葱姜蒜那一列就是扩完之后的预期形态（2.6%–31.0%，全程健康）。
→ 也就是说：**在 `_STAPLES` 修好之前，FULL=2 的"过半触发线"在真实中式冰箱下是上线即可能触发的，不是远期风险。**
→ 修 `_STAPLES` 的代价仍是 §5.2(18)④ 那条：会同时动 `_inventory_ratio` 的分子分母，必须重拍基线。

**看板建议**：把"命中≥2 占比"和"命中≥1 占比"两个指标按周观测，**并按"库存是否含 `_STAPLES` 外通用项"分层看**；只看总数会被 clear/大冰箱样本平均掉。

---

#### (18) J3 / J6' / J7' 起点值：线上数据算不出来，只能用离线基线（2026-09-23 实测）

##### (a) 🔴 `decision_log` 现有 190 行给不出起点值

`SHOW COLUMNS FROM decision_log` 实测：

| 列 | 类型 | Null | Default | 190 行实际值 |
|---|---|---|---|---|
| `relaxed_level` | int | **NO** | **0** | **全 0** |
| `candidate_count` | int | **NO** | **0** | **全 0**（min = max = 0） |
| `band_size` | int | YES | NULL | **全 NULL** |
| `natural_band_size` | int | YES | NULL | **全 NULL** |

→ 现有 J3 / J6' / J7' 三条判据在真实数据上的取值：`relaxed_level>=2` = **0%**、`candidate_count` P10 = **0**、`<8` 占比 = **100%**。
→ **这三个数不是信号，是"列从未被填充"。**

**🔴 由此引出一个比"算不出基线"更危险的设计问题**：

`candidate_count` 是 **`NOT NULL DEFAULT 0`**。这意味着「埋点没接好」与「池子真的空了」在判据上**完全不可区分** —— 两者都表现为 `candidate_count = 0`，J6' 判失败、J7' 判 100% 失败。

→ V1.2.0 上线当天，如果 R-07 任何一条链路没写进 `candidate_count`，**J6'/J7' 会全红，而值班的人会以为是"池子塌了"**。
→ 建议给 J6'/J7' 加**数据可用性前置断言**：`candidate_count > 0` 的行占比必须 ≥ 阈值才认为判据**可评估**；否则输出"不可评估（埋点未接通）"，与"判失败"分开。
→ 顺带建议：这三个 `NOT NULL DEFAULT 0` 的列改成 **nullable / 或用 −1 表示未采集**，让"未采集"和"采集到 0"可区分。

##### (b) 离线基线（342 池，N=500，seed=20260923，`_pick()` 只读，未调 `decide()`）

场景 =（`cook_cap` / 近 N 天已吃菜数）：

| 场景 | slot | `cc` P10 | `cc` P50 | `<8` 占比 | `relax>=2` | `relax>=4` | `band` P50 | `natural` P50 | padding 生效% |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 常规 cap30/5餐 | breakfast | 269 | 270 | 0.0% | 0.0% | 0.0% | 7 | 7 | 0.0% |
| 常规 cap30/5餐 | lunch | 269 | 270 | 0.0% | 0.0% | 0.0% | 13 | 13 | 0.0% |
| 常规 cap30/5餐 | dinner | 269 | 270 | 0.0% | 0.0% | 0.0% | 14 | 14 | 0.0% |
| 常规 cap30/5餐 | **late_night** | **44** | 45 | 0.0% | 0.0% | 0.0% | 8 | 8 | 0.0% |
| 压测 cap20/12餐 | breakfast | 120 | 122 | 0.0% | 0.0% | 0.0% | 5 | 5 | 6.6% |
| 压测 cap20/12餐 | lunch | 120 | 122 | 0.0% | 0.0% | 0.0% | 5 | 5 | 0.0% |
| 压测 cap20/12餐 | dinner | 120 | 122 | 0.0% | 0.0% | 0.0% | 5 | 5 | 4.8% |
| 压测 cap20/12餐 | **late_night** | **42** | 44 | 0.0% | 0.0% | 0.0% | 4 | 4 | 0.0% |
| 极限 cap15/20餐 | breakfast | 93 | 96 | 0.0% | 0.0% | 0.0% | 4 | 4 | **35.8%** |
| 极限 cap15/20餐 | lunch | 93 | 96 | 0.0% | 0.0% | 0.0% | 4 | 4 | **35.8%** |
| 极限 cap15/20餐 | dinner | 93 | 96 | 0.0% | 0.0% | 0.0% | 4 | 4 | **35.8%** |
| 极限 cap15/20餐 | **late_night** | **31** | 32 | 0.0% | 0.0% | 0.0% | 4 | 4 | 0.0% |

**结论三条：**

1. **J6' / J7' 在所有场景下都是绿的**：`cc` P10 最低 **28**（极限夜宵），`<8` 占比 **恒 0%**。
2. **J3 在所有场景下都是 0%** —— 放宽阶梯**从不触发**（池子 93 ≫ `POOL_MIN=8`）。
   → **J3 / J7' 是「回归型判据」不是「健康型判据」**：基线为 0，只有当某次改动把池子打塌时才会红。PRD 里应写明这一点，否则会被误读成"当前健康度 0% 很好"。
3. **padding 在严约束场景下不是边缘情况**：极限场景 **35.8%** 的采样出现 `band_size > natural_band_size`。
   但 **J6' 阈值 8 > `random_min_choices`(3)，padding 垫不动它** —— 见下条。

##### (c) `band_size` 与 `natural_band_size` 的等价性（回答 12u）

`band_size = max(natural_band_size, random_min_choices)`（padding 只在 `natural < 3` 时补齐到 3）。所以：

- **差值不是分布，是确定性函数**：`band_size − natural_band_size = max(0, 3 − natural)`，**最大值 = `random_min_choices − 1` = 2**。
- **只要判据阈值 > `random_min_choices`(3)，两者逐条判定完全等价**（`band ≥ T ⟺ natural ≥ T` 当 `T > 3`）。
- 分位数同理：`band ≥ natural` 逐元素成立 ⇒ `P10(band) ≥ P10(natural)`，`T > 3` 时结论一致。

→ **切换触发线：当 J6'/J7' 的阈值被下调到 `≤ random_min_choices`(3) 时，必须改用 `natural_band_size`。** 阈值 >3 时换不换都不影响结论。**主口径不必换。**

##### (d) 🔴 自曝：`band` 中位数对「历史丰富度」极度敏感，我自己的门禁阈值标定得太乐观

同一个 dinner 档、同一套代码，`band` 中位数随历史变化：

| 历史口径 | `band` P50 |
|---|---:|
| 空历史（`band_regression.py` 用） | **60** |
| 荤菜×1（`band_regression.py` 用） | **25** |
| **随机 5 餐（本次实测）** | **14** |
| 压测 12 餐 | **5** |
| 极限 20 餐 | **4** |

→ **门禁 `check-band` 之所以 PASS，是因为它只用「空历史 / 荤菜×1」两种极轻的历史。换成真实 5 餐历史，dinner = 14 < 阈值 18，门禁会红。**

**而这个红是假红**：`band` 变窄的主因是 `category_penalty_step=25` 的品类打散惩罚在起作用 —— **band 小 ≠ 塌缩**。塌缩的定义是"某个二元打分项把池子切成两半"，与"打散惩罚让分数离散度变大"是两回事，我的门禁把它们混为一谈了。

→ **修正结论：`band` 只能做「固定历史口径下的相对回归」（同一口径前后对比），不能做绝对健康度指标。**
→ 若要用 `band` 中位数做健康度判据，**阈值必须在同一历史口径下实测标定**，不能拿空历史的 60 去定一个 50 的线。

---

#### (18) 🔴 早餐塌缩的**机制性根因**：`category` 枚举里根本没有「早餐」（2026-09-23，双实现互证）

##### 先给结论：这不是"标注不准"，是一条完整的因果链

> **`字段语义缺失 → 用硬编码补偿 → 补偿本身制造硬分区`**

**不用跑数就能断言的一步**：`recipe.category` 的标准枚举是 **`荤菜 / 素菜 / 主食 / 面食 / 汤羹 / 凉菜 / 小吃`（7 值，迁移 0014 规则生成）** ——
**里面没有「早餐」**。而 `recipe.cuisine` 的取值里有 **早餐 25 道**。
⇒ 这 25 道**必然**被塞进那 7 个 category 之一（牛奶燕麦、鸡蛋三明治这类大概率落进"荤菜"或"素菜"）。

**链条**：

| 步 | 事实 | 后果 |
|---|---|---|
| 1 | `category` 枚举无「早餐」 | 早餐食品在 `category` 轴上**不可识别** |
| 2 | `_score()` 早餐硬编码：`category in (主食,面食) → +12.0`；`≤15min → +8.0` | 只能拿 `category` 当代理 —— **这是补偿** |
| 3 | 真正的早餐食品 category 不是主食/面食 | **拿不到 +12** |
| 4 | `+12 +8 = +20 ≫ random_band=5.0` | 拿不到就**进不了 `best − 5` 的带** ⇒ 恒被排除 |
| 5 | 能抽到的只剩 category 恰好是主食/面食的菜 | **品类数恒 2、主面占比恒 100%** |

→ **第 2 步的"补偿"正是第 5 步"硬分区"的直接原因。** 这与 §5.2(12) 的二元打分塌缩通则是同一枚硬币：
**当一个字段在语义上缺失，人们会拿另一个字段硬编码去补，而硬编码的幅度从来没人拿 `random_band` 校过。**

##### 双实现互证：结论对池子构成和样本量都不敏感

| | 数析（真库 342，N=500） | dev-engine-relax（合成池 330，N=200） |
|---|---|---|
| breakfast band | 14 | 6 |
| **品类数** | **2** | **2** |
| **主面占比** | **100%** | **100%** |

两个**完全独立**的实现（不同池子、不同 N、一个连库一个不连库）跑出**同一个定性结论**。
band 绝对值 14 vs 6 的差异来自池子 category 分布不同；但"品类数恒 2、主面 100%"**不依赖分布**。

→ **这条可以定案：早餐塌缩是结构性的，不是采样噪声，也不是某一次数据快照的偶然。**

**⚠️ 待补（本机 shell 当前不可用，连不上 MySQL）**：`cuisine='早餐'` 的 25 道菜 → 其 `category` 分布实跑表，用来坐实第 3 步。

---

#### (19) 门禁脚本在 CI 上的策略：无 DB 时**绝不降级到合成池**（2026-09-23）

`backend/scripts/band_regression.py` 的蒙特卡洛走 `load_candidates()`（连真库），CI 上无 DB 的机器拿不到数。
dev-engine-relax 提出"是否降级到合成池"，**数据侧反对，理由就是上面那张表**：

> 真库 14 vs 合成池 6，**同一判据差 2.3 倍**。降级到合成池 = 拿一个已知会漂移的基线做判定，
> 绿灯的含义会从"线上不会塌"变成"合成池没塌" —— **门禁变成装饰品，比没有更危险**（假绿会让人放心）。

**建议三段式**：

| DB 状态 | 跑什么 | 输出 | 退出码 |
|---|---|---|---|
| 有 | 静态自检 + 蒙特卡洛 | `[PASS]` / `[FAIL]` | 0 / 1 |
| **无** | **只跑静态自检**（纯静态，不需 DB） | **`[PARTIAL] Monte Carlo skipped: no DB`** | 0 |
| 无 | ~~降级到合成池~~ | — | — |

**铁律：无 DB 时绝不打印 `[PASS]`。** 静态自检单独就能抓住 P0 那类量级问题（`+12/-20` 一眼可见），蒙特卡洛跳过就明写跳过。

##### 静态自检的判据要写**严格小于**

```
二元型 Δ_max = 最高档 − 最低档 = 该项幅度（最低档恒为 0）
判据：幅度 < random_band      ← 严格 <，不是 <=
```

`幅度 == random_band` 时最高档与最低档正好差一个 band，`best` 来自最高档则最低档**恰好压在门槛上**，
是零余量的边界态，浮点与并列都会让它翻车。**这也是反对 `FULL=1 + score_inventory=5.0` 的同一个理由。**

R-09 四方案在静态自检下的判定：A（连续型）豁免 / **B `4.0` 通过** / C `3.0` 通过 / **D `5.0` 不通过**。

---

#### (20) 🔴 早餐档有**两个独立的加分源**：裁定后的 `+3.0/+1.5` 叠上 `meal_slots` 的 3.0 仍过带（2026-09-23，代码静态事实）

team-lead 裁定早餐硬编码降到 `+3.0 / +1.5`（合计 4.5 < `random_band` 5.0，治症状）。**这个 4.5 漏算了一项。**

两条加分**都在 `_score()` 里、都会生效**：

| 位置 | 加分 | 条件 | 现行幅度 |
|---|---|---:|---|
| `decision_service.py` **L950-954** | 硬编码补偿 | `slot==BREAKFAST and category in (主食,面食)` → +12.0；`≤15min` → +8.0 | 12.0 / 8.0 |
| `decision_service.py` **L957** → `_meal_slot_score` L907 | `MEAL_SLOT_MATCH_BONUS`（R-11） | `slot in c.meal_slots` | **3.0** |

```
叠满（现行）   = 3.0 + 12.0 + 8.0 = 23.0
叠满（裁定后） = 3.0 + 3.0  + 1.5 =  7.5  >  random_band 5.0   ❌
```

`meal_slots` 含 breakfast 的有 48 道，且与"主食/面食"大概率高度重叠 ⇒ **叠加不是小概率事件**。

→ 这是 §5.2(12) 通则的**必要非充分**性质再次生效（dev-engine-relax 上一轮在雨天 inventory 叠 weather 上先指出）：
**单项幅度 ≤ band 不能推出"不塌缩"，要看命中组 vs 未命中组的总 Δ。**

**两个解法（已报 team-lead，待裁定）**：

| 方案 | 做法 | 总 Δ |
|---|---|---:|
| **A（推荐）** | **两者互斥**（命中 `meal_slots` 就不再吃硬编码补偿，或反之） | 3.0 或 4.5，均 < 5.0 ✅ |
| B | 硬编码再降到 1.0 / 0.5 | 3.0 + 1.5 = 4.5 < 5.0 ✅（但补偿已接近噪声，等于事实上放弃补偿） |

A 的理由与 §5.2(7) 拒绝"给 `category` 二次计价"同源：**`meal_slots` 与 `category in (主食,面食)` 表达的是同一件事（这一顿合不合适），叠着算即对同一信号二次计价。**

**配套验收**：改后复跑除 band 大小外，必须报**叠满组的总 Δ**；若 `Δ > random_band`，说明叠加未处理、症状仍在。
（team-lead 已给门禁加 `band 品类数` 与 `最大单品类占比` 两个输出 —— 这两个正是该症状的真度量，"恒 2 / 100%"只看 band 大小看不出来。）

---

#### (21) 数字口径分类：**实测数** vs **代码静态事实**（2026-09-23）

本机 shell 与 MySQL 连接本轮多次中断（dev-offline-pool-slots 同样受影响）。team-lead 要求"环境恢复后全部重跑"。
同意，但建议先分类，避免把不需要重跑的也划进"待重跑"而误伤结论：

| 类别 | 定义 | 例子 | 环境恢复后 |
|---|---|---|---|
| **实测数** | 依赖 DB / 采样 | band 大小、品类占比、覆盖率、命中数（723 / 846 / 860 等） | ✅ **必须重跑** |
| **代码静态事实** | grep 即得，与运行环境无关 | `category` 7 值枚举无「早餐」；`_score()` L950-954 与 L957 两个加分源并存；`SCORE_CUISINE = 20.0` 硬编码；`LOCAL_RANDOM_BAND = 5.0` | ❌ **不需要重跑**，也不会变 |

本节 (20) 的叠加结论属后者 —— **不依赖环境，可直接采信**。

---

#### (20) 🔴 早餐降幅度的**失效反例**：`MEAL_SLOT_MATCH_BONUS` 会把 3.0/1.5 叠穿到 7.5（2026-09-23）

team-lead 裁定早餐硬编码 `+12.0/+8.0` → **`+3.0/+1.5`**（治症状，病根排 V1.3）。裁定本身成立，
**但落地后会失效** —— 这是"单项幅度 ≤ band 是必要非充分"的直接推论。

##### 叠加证据（`decision_service.py`）

```python
# L950-954  时段: 早餐偏好主食与快手
if slot == MealSlot.BREAKFAST:
    if c.category in ("主食", "面食"):  score += 12.0   # → 裁定为 3.0
    if (c.minutes or 0) <= 15:          score += 8.0    # → 裁定为 1.5

# L957      餐次贴合 (R-11)
score += self._meal_slot_score(c, slot)   # 命中给 MEAL_SLOT_MATCH_BONUS = 3.0
```

**两条都在 `_score()` 里，无条件相加。** 同时满足 ①`category∈(主食,面食)` ②`≤15min` ③`meal_slots` 含 breakfast ⇒
**`3.0 + 1.5 + 3.0 = 7.5 > random_band = 5.0`** ⇒ 硬分区照旧，品类数大概率仍恒 2。

**且这不是边角，是早餐档主路径**：`meal_slots` 里 breakfast **48 道**，而被标 breakfast 的菜恰恰最可能就是
`category`=主食/面食 —— **两者高度重叠**。

> ⚠️ **这是同一类错误的第二次复发**：我当初反对 R-11 用 15–25 分的理由是
> 「`category` 轴已有 `category_penalty_step` 在管，再叠一层是对同一信号二次计价」。
> **`meal_slots` 与 `category∈(主食,面食)` 都是"这道菜适不适合早餐"，是同一信号的两个来源。**

##### 三个解法

| 方案 | 叠满总 Δ | 判定 |
|---|---:|---|
| **① 两条互斥**（有显式标注就不再叠加 category 补偿） | 3.0 | ✅ **唯一干净解**。显式标注覆盖补偿，且堵死"将来有人再调其中一个"的复燃路径 |
| ② 压到 `+1.2 / +0.6`（合计 1.8）+ 3.0 | 4.8 < 5.0 | ⚠️ 数学上过，但早餐信号被压到近乎为零，症状病根两头落空 |
| ③ 不管，按 3.0/1.5 直接落地 | 7.5 | ❌ 门禁红，症状不消失 |

**建议 ①**，且 `BREAKFAST_CATEGORY_BONUS` / `BREAKFAST_QUICK_BONUS` 必须**提为模块级常量**
（现为 `_score()` 内的字面量，静态自检扫不到 —— 又回到"硬编码的幅度从来没人拿 `random_band` 校过"）。

---

#### (21) 门禁登记 inventory 档位后立刻抓出：`INVENTORY_SCORE_CAP = 5.0` 不合规（2026-09-23）

dev-engine-relax 把 inventory 按**每一档摊开**登记进 `static_check()` 后，门禁当场失败：

```
[FAIL] INVENTORY_SCORE_CAP = 5.0  跨度=5.0  档间距=2.5  vs random_band=5.0
       # 库存命中档位 0 / 2.5 / 5 (FULL=2, 单位分=5)
```

即 R-09 当前落地配置 = 本报告判死的**方案 D**。**跨度恰等于 `random_band`，靠"闭区间恰好留在带内"侥幸活着，零余量**
—— 与 `FULL=1 + 5.0` 是同一种赌法。

**建议：降到 4.0（方案 B），不要登记成"已知豁免"。**
- 档位 `0 / 2.0 / 4.0`，跨度 4.0、档间距 2.0，两个判据都过，留 1.0 余量；
- **登记成豁免 = 门禁长期挂红或被人静音**，与 §5.2(19) 联手堵掉的"用看起来绿替代真的验过"是同一种病的另一个入口；
- 只动幅度，不动 R-09 语义（`FULL=2`、按命中数分档均不变）。

> **判据改进（dev-engine-relax 提出，采纳）**：原只有"跨度"一个判据，现补"档间距"。
> **跨度管"会不会整档切掉"，档间距管"相邻档之间会不会也塌"** —— 两个都要。

---

#### (22) J6'/J7' 的前置过滤：`candidate_count > 0`（2026-09-23）

`decision_log.candidate_count` 是 `NOT NULL DEFAULT 0`，而**存量 190 行的 `candidate_count` 全是 0**
（R-07 上线前落的历史行，那时没有这个列）。

⇒ J6'/J7'（夜宵 `candidate_count` P10 ≥8）不加过滤的话，**190 个 0 会把 P10 直接拉到 0，判据恒失败，
且失败原因与产品完全无关。**

```sql
AND candidate_count > 0      -- 必需
```

判据文字须写明：**「统计口径仅包含 R-07 上线后、且 `candidate_count > 0` 的决策」**。
不加 → 上线首日必红且误导排查；加了不写明 → 复用 SQL 的人会漏掉。

> 这与 §5.6「判据不能被'最差实现'满足」互为镜像：那条防"什么都不做也能通过"，这条防"什么都不做会一直失败"。

---

#### (23) 🔴🔴 **通则修正**：`|Δ| > random_band` 是**最坏情况判据，不是点预测**（2026-09-23，实测推翻我的预判）

##### 我预判错了

§5.2(20) 我断言：早餐 A 方案（3.0/1.5 与餐次 3.0 叠加 = 7.5）会导致"硬分区照旧、品类数大概率仍恒 2"。
dev-engine-relax 用真库实跑（**不改源码，用 `_score` 反推**），结果：

| 方案 | band | 品类数 | 主面占比 | band 内品类分布 |
|---|---:|---:|---:|---|
| 现状 12.0/8.0 叠加 | 14 | 2 | 100% | 面食8 / 主食6 |
| **A 3.0/1.5 叠加（叠满 7.5）** | **24** | **5** | **46%** | 主食6 / 素菜6 / 面食5 / 荤菜5 / 凉菜2 |
| B 3.0/1.5 与餐次**互斥** | 54 | 6 | 15% | **荤菜35** / 素菜7 / 主食5 / 面食3 / 凉菜3 / 小吃1 |

**"品类数恒 2"是错的，实测 5。撤回。**

**错因**：我按"`meal_slots` 含 breakfast 的 48 道都叠满"估算，**实际三项全中（主/面 ∩ ≤15min ∩ 含早餐）只有 7 道**；
且 base 分本身有方差，5 分带里还装得下 24 道。

##### 修正后的通则（比数字本身重要）

> **`|Δ| > random_band` ⇒ 塌缩，是「最坏情况判据」，不是点预测。**
>
> 它断言的是：**存在一种数据分布，会让未命中组整组出局**。
> 它**不**断言：当前分布下一定出局。
>
> 未命中组要真的整组出局，还需要它们的 base 分足够接近命中组。
> 命中组只有 7 道、且它们 base 分本来就高时，带里还装得下别人。

⇒ **A 仍然该否决，但理由必须说准**：
> **不是"现在会塌"，是"它在最坏情况下会塌，我们现在只是运气好（重叠面只有 7 道）"。**

这与 §5.6「判据不能被『最差实现』满足」是同一个道理 —— **该盯的是最坏情况，不是当前快照。**
现在不塌是**数据侥幸**，不是设计对；`meal_slots` 一旦补标、重叠面变大，同样的代码立刻塌。

##### 🔴 但 B（互斥）也不能直接用 —— 互斥会制造**反向激励**

dev-engine-relax 指出、经我复核确认：互斥后 **代理分（4.5）> 显式标注分（3.0）**。

⇒ **每补一道 breakfast 标注，那道菜反而少拿 1.5 分。**
⇒ 现有 48 道标注全部受影响，将来富集补标越多吃亏越多 —— **系统在惩罚补标注的人。**

这不是口味问题，是**计价方向反了**。B 的实测也印证：早餐档出 **荤菜 35/54 = 65%**，早餐味基本消失。

##### 方案 C（推荐）：**叠加 + 早餐相关加分合计封顶 4.5**

| | 原理合规 | 保留早餐味 | 激励方向 | 依赖数据侥幸 |
|---|---|---|---|---|
| A 叠加 | ❌ 叠满 7.5 | ✅ 主面 46% / 品类 5 | ✅ | ❌ **是** |
| B 互斥 | ✅ | ❌ 主面 15% / 荤菜 65% | ❌ **反向** | ✅ |
| **C 叠加 + 封顶 4.5** | ✅ | ✅（预期接近 A） | ✅ | ✅ |

```python
BREAKFAST_BONUS_CAP = 4.5   # < random_band=5.0；与 inventory 的 min(1.0, hits/FULL) 同一手法

bonus = 0.0
if slot == MealSlot.BREAKFAST:
    if c.category in ("主食", "面食"):  bonus += BREAKFAST_CATEGORY_BONUS   # 3.0
    if (c.minutes or 0) <= 15:          bonus += BREAKFAST_QUICK_BONUS      # 1.5
bonus += self._meal_slot_score(c, slot)                                     # 3.0
score += min(bonus, BREAKFAST_BONUS_CAP)
```

- **合规不靠侥幸**：单项都过静态自检，合计封顶 4.5 < 5.0 —— 补标到 200 道 C 仍合规，A 会塌
- **保留早餐味**：只把那 7 道全中的从 7.5 拉到 4.5，其余不变
- **激励方向正确**：标注仍加分，全中的拿满，**补标注永远不吃亏**
- **手法有先例**：封顶即 inventory 已在用的 `min(1.0, hits/FULL)`

**封顶值**：建议 **4.5**（余量 0.5）；可退到 **4.0**（余量 1.0，与 inventory 同余量），早餐味再淡一点。
**不建议 5.0**（= band，零余量 —— 就是 §5.2(21) inventory 现在那个毛病）。

##### ⚠️ 分母疑点

dev-engine-relax 跑的是**真库 343 道**，本报告的基数是 **342**（`is_dish=1`，迁移 0017）。差 1 道。
若是真进了 1 道新菜（富集落库），则：① 撞上 TaskList **无归属的 #33**（富集落库时对新菜做 `is_dish` 判定）；
② **本报告的 342 基数需重算**。已请其跑两行 SQL 确认来源，待回。

---

#### (23) 🔴 **通则修正**：`|Δ| > random_band` 是**最坏情况判据**，不是点预测（2026-09-23，实测反例后的自我修正）

##### 反例：我说 A 会"品类数仍恒 2"，实测是 5

dev-engine-relax 用真库把早餐三方案实测了一遍（**不改源码**，用 `_score` 反推 base 再加回）：

| 方案 | band | 品类数 | 主面占比 | band 内品类分布 |
|---|---:|---:|---:|---|
| 现状 `12.0/8.0` 叠加 | 14 | 2 | 100% | 面食8 / 主食6 |
| **A `3.0/1.5` 叠加**（我预判"恒 2"） | **24** | **5** | **46%** | 主食6 / 素菜6 / 面食5 / 荤菜5 / 凉菜2 |
| B `3.0/1.5` 与餐次互斥 | 54 | 6 | 15% | **荤菜35** / 素菜7 / 主食5 / 面食3 / 凉菜3 / 小吃1 |

**我的预判错了，撤回。** 错因：我按"48 道 breakfast 标注都叠满"估，**实际三项全中只有 7 道**；
且 base 分本身有方差，5 分带里装得下 24 道。

##### 修正后的通则（重要）

> **`|Δ| > random_band` ⇒ 塌缩：是「最坏情况判据」，不是点预测。**
> 它断言的是"**存在一种数据分布**会让未命中组整组出局"，**不是**"当前分布下一定出局"。
> 未命中组要整组出局，还需其 base 分足够接近命中组；命中组小（7 道）且 base 分本身高时，带仍装得下别人。

⇒ **A 仍然该否决，但理由要说准：不是"现在会塌"，是"它在最坏情况下会塌，现在只是运气好（重叠面只有 7 道）"。**
⇒ 与 §5.6「判据不能被"最差实现"满足」同源：**该盯最坏情况，不是当前快照。**

##### 但 B（互斥）也不能直接用 —— 反向激励

互斥后：**代理分 4.5 > 显式标注分 3.0** ⇒ **每补一道 `breakfast` 标注，那道菜反而少拿 1.5 分。**
⇒ 现有 48 道标注全部受影响，将来富集补标越多吃亏越多 —— **系统在惩罚补标注的人。**
B 的实测也印证：早餐档出 **荤菜 35/54 = 65%**，早餐味基本消失。

##### 方案 C：叠加 + 早餐相关加分合计封顶（本报告推荐）

| | 原理合规 | 保留早餐味 | 激励方向 | 依赖数据侥幸 |
|---|---|---|---|---|
| A 叠加 | ❌ 叠满 7.5 | ✅ 主面 46% / 品类 5 | ✅ | ❌ **是** |
| B 互斥 | ✅ | ❌ 主面 15% | ❌ **反向** | ✅ |
| **C 叠加 + 封顶 4.5** | ✅ | ✅（预期≈A） | ✅ | ✅ |

```python
BREAKFAST_BONUS_CAP = 4.5   # < random_band=5.0；与 inventory 的 min(1.0, hits/FULL) 同一手法

bonus = 0.0
if slot == MealSlot.BREAKFAST:
    if c.category in ("主食", "面食"):  bonus += BREAKFAST_CATEGORY_BONUS   # 3.0
    if (c.minutes or 0) <= 15:          bonus += BREAKFAST_QUICK_BONUS      # 1.5
bonus += self._meal_slot_score(c, slot)                                     # 3.0
score += min(bonus, BREAKFAST_BONUS_CAP)
```

- **合规不靠侥幸**：合计封顶 4.5 < 5.0，将来 `meal_slots` 补标到 200 道照样合规（A 会塌）
- **保留早餐味**：只把那 7 道全中的从 7.5 拉到 4.5
- **激励方向正确**：标注仍加分，全中的拿满，补标注永不吃亏
- 封顶值：4.5（余量 0.5）/ 4.0（余量 1.0，与 inventory 同）。**不取 5.0**（= band，零余量）

---

#### (24) J6'/J7' 的 `COALESCE(band_size, candidate_count)` 有语义问题（2026-09-23）

12u 裁定 J6'/J7' 主口径保持 `COALESCE(band_size, candidate_count)`。**数据侧认为该拆不该 COALESCE**，
理由与"换不换 `natural_band_size`"无关，是语义问题：

1. **两个量回答的是两个不同的失败**：`candidate_count` = 放宽**前**的池子（"会不会筛不出菜"）；
   `band_size` = 最终抽签带（"用户实际在几道里抽"）。COALESCE 之后判据**名义未改、实际换了问题**。
2. **阈值 8 只对其中一个量有语义**：8 = `POOL_MIN`（放宽触发线，来源明确）；对 `band_size` 而言
   **8 没有语义来源** —— band 自然量级 14–60，早餐档正常才 14。**同一个 8 用在两个量级不同的量上是错的。**
3. **COALESCE 在 `band_size` 有值时完全丢弃 `candidate_count`** ⇒ "池子够但抽签带塌了"这一种失败
   在 J6'/J7' 里**根本看不见** —— 而那正是 padding 那类病的形状。

**建议拆成两条**：

| 判据 | 口径 | 阈值 |
|---|---|---|
| J6'/J7' | `candidate_count` P10 | **≥ 8**（= `POOL_MIN`，语义明确，不动） |
| 新增 | `natural_band_size` P10 | **待实测**（改前基线：夜宵正常 11 / 塌缩 <5；dinner 空历史 60、荤菜×1 25） |

**另**：`candidate_count > 0` 的过滤**必须写在裸列上**，不能写成 `COALESCE(band_size, candidate_count) > 0`
—— 后者会把 `band_size = 0`（真·抽签带空）的行一并滤掉，而那是 J7' 唯一要抓的信号。
（requirement-analyst 指出，我确认自己按字面加就会写错。）

---

#### (25) 🔴🔴 **架构级结论**：`random_band` 是"随机性"与"偏好强度上限"的同一个旋钮 —— 并修正本报告的「只能加分」档（2026-09-23）

##### 实测（dev-engine-relax，真库 343，早餐档，不改源码，用 `_score` 反推 base 再加回）

| 方案 | band | 真带 | 品类数 | 主面% | 荤菜% | **主面相对自然占比** |
|---|---:|---:|---:|---:|---:|---:|
| 现状 `12.0/8.0` 叠加 | 14 | 14 | 2 | 100% | 0% | **4.90x** |
| A `3.0/1.5` 叠加 | 24 | 24 | 5 | 46% | 21% | **2.25x** |
| B `3.0/1.5` 与餐次互斥 | 54 | 54 | 6 | 15% | 65% | **0.73x ← 反向** |
| **C 叠加 + 封顶 4.5** | 58 | 58 | 6 | 21% | 60% | **1.01x** |
| C 叠加 + 封顶 4.0 | 65 | 65 | 6 | 26% | 57% | 1.28x |
| （池子自然占比） | — | — | — | 20.4% | 52.2% | 1.00x |

（真带 == band，五方案都没被 padding 掩盖，均远 > `random_min_choices=3`）

**两处自我修正**：
1. 我预判 A"品类数仍恒 2"，实测 5 → **已撤回**（见 §5.2(23)）
2. 我预判 C"预期接近 A"（2.25x），实测 **1.01x ≈ 无偏好** → **再撤回**。
   原因：封顶削掉的正是那 7 道全中菜的领先量，而正是这点领先把主面推到带顶；削掉后带变宽（58），主面被自然分布稀释回去。
3. **B 比"信号没了"更糟**：0.73x **低于自然占比** = **反向倾斜**。互斥后拿到 3.0 的是 48 道 breakfast 标注菜，
   而它们多数**不是**主面（粥/小吃/素菜）—— **B 是拿餐次标注把非主面抬起来了。**

##### 精确刻度：幅度决定"能影响什么"

| 打分项幅度 | 能影响 | 不能影响 |
|---|---|---|
| **≤ random_band** | **谁排第一**（头部排序） | **带里有哪些品类** |
| **> random_band** | **品类构成**（现状 4.90x） | —（代价：未命中组整组出局 = 塌缩） |

⇒ **中间没有过渡地带。** 这就是"**合规**"与"**有品类倾向**"不可兼得的精确含义。
⇒ 五组数正好落在两侧（20 分 → 4.90x 但 band=14；4.5 分 → 1.01x 但 band=58），**没有第三个落点**。

##### 根因是架构性的

**`random_band` 同时是两件互相冲突的事的唯一旋钮**：
- 它是"**随机性**"旋钮（band 越大越随机 —— 这是产品要的：避免"这个 App 就这几道菜"）
- 它同时是"**任何单一偏好信号的强度上限**"（幅度 ≤ band 才不塌缩）

⇒ **不动架构，就不可能既保留随机性、又让某个偏好真正生效。**

##### 🔴 这条反过来修正了本报告 §1.3「覆盖率阈值法则」的一档

原法则有一档：**30–70% 覆盖率 →「只能加分」**。
按上表实测，**「只能加分」在当前架构下 ≈「加了也推不动用户看到什么品类」**。受影响的**不止早餐**：

| 受影响项 | 说明 |
|---|---|
| R-11 `meal_slots` +3.0 | 我当初主张的软惩罚 —— 同理，推不动品类构成 |
| `INVENTORY_SCORE_CAP` 4.0（本报告建议值） | 同理 |
| §1.3 里所有判为"只能加分"的字段（`meat_type` 71% 等一批 30–70%） | 同理 |

**修正后措辞（全文生效）**：
> ~~「只能加分」~~
> → **「只能影响排序头部，不能影响品类构成；若需求目标是品类构成，必须走硬过滤 + 放宽兜底，否则不上」**

##### 对 V1.2.0 首页的直接含义

**首页上"我想吃点清淡的""来点下饭的"这类偏好型格子，本版即使接上也不会有可感知效果** ——
不是数据不够，是**架构上 ≤ band 的偏好推不动品类构成**。
⇒ 偏好型格子要么改成**硬过滤 + 放宽兜底**，要么**本版不摆**。已同步 requirement-analyst 与 team-lead。

##### 待补（本机 shell 连不上 MySQL，不跑不猜）

1. **各方案「第一名」的品类分布**（N=500）—— 用户首先看到的是第一道，带的构成只影响"连点几次换一个"之后。
   判定：若 C 的第一名主面占比仍 ≥35% ⇒ C 足够；若接近自然分布 ⇒ 确认软偏好在本架构下完全无效。
2. `random_band = 8 / 10` 时早餐档的 band / 品类数 / 主面占比 —— 给"提高 band"这个选项定价。
   （早前在别的场景已实测 `random_band=10` 会让塌缩点移到 11，即放宽合规上限；代价是随机性增大，需看品类构成的改善幅度才知道值不值。）

---

#### (25) 🔴🔴 结构性发现：**"偏好生效"与"抽签带不塌"是同一个旋钮的两端**（2026-09-23）

这是本轮比"早餐选哪个方案"更值钱的一条。

##### 机制

> **加分幅度 ↑ ⇒ `best` ↑ ⇒ 带下沿（`best − random_band`）↑ ⇒ 带变窄 ⇒ 偏好对品类的控制力 ↑、可抽道数 ↓。**

⇒ **"偏好生效"和"抽签带不塌"不是有冲突，是本来就是一回事。**
现状 `12.0/8.0` 之所以能做出 4.90x 的早餐倾向，**就是因为它把带压到 14 才换来 100% 主面**。

##### 实测（真库 343，早餐档，dev-engine-relax 只读脚本；本报告作者的两个预判均被推翻）

| 方案 | band | 真带 | 品类数 | 主面% | 荤菜% | **最大单品类** | 主面相对自然占比 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 现状 `12/8` 叠加 | 14 | 14 | 2 | 100% | 0% | **100%**（主面） | 4.90x |
| **A `3.0/1.5` 叠加** | 24 | 24 | 5 | 46% | 21% | **46%**（主面） | 2.25x |
| B `3.0/1.5` 互斥 | 54 | 54 | 6 | 15% | 65% | **65%**（荤菜） | **0.73x 反向** |
| C 叠加+封顶 4.5 | 58 | 58 | 6 | 21% | 60% | **60%**（荤菜） | 1.01x |
| C 叠加+封顶 4.0 | 65 | 65 | 6 | 26% | 57% | **57%**（荤菜） | 1.28x |

池子自然占比：主面 20.4% / 荤菜 52.2%。五方案真带均 = band，**未被 padding 掩盖**。

##### 三条结论

1. **C 没保住早餐味**（本报告作者原预期"接近 A"，**实测推翻，撤回**）：1.01x ≈ 无偏好。
   原因：封顶削掉的正是那 7 道全中菜的领先量，而正是这点领先把主面推到带顶；削掉后带变宽（58），主面被自然分布稀释回去。
2. **按"最大单品类占比"排序与按"品类数"相反**：A 品类数 5（少）但集中度 **46%（最低）**；
   C 品类数 6（多）却更集中（**60% 荤菜**）。⇒ **C 只是把单调从"主面"换成"荤菜"，并没有真的更多样。**
   B 是 65% 荤菜 —— **又反向又更单调**，比"信号没了"更糟。
3. **`random_band=5` 下，所有合规方案的偏好倍数必然 ≈ 1.0x** ⇒ **"偏好倍数"不能当验收判据**
   （会把所有合规方案判死，逼人回头选那个必然塌带的 `12/8`）。**只做观测，不设阈值。**

##### 🔴 本报告作者的第二次方法论错误（记录在案）

前一次用 `|Δ| > random_band` 当**点预测**否决 A（实测不塌），后一次又当点预测推 C（实测不接近 A）。
**同一封里刚写完"这是最坏情况判据不是点预测"，转头就又犯。**

⇒ **正确定位**：静态自检的幅度约束是**便宜的事前代理**，真判据是**实测** `natural_band_size` + 品类数 + 最大单品类占比。
⇒ **正确顺序**：不因为越过代理线就否决 A，而是**在最坏情况下（模拟 `meal_slots` 补标完成，重叠面从 7 道拉到接近满）重测 A/C**。
   补标是既定方向（覆盖率 20.5% 明确待补），不是假想场景。

##### 连带推论（影响 PRD 措辞）

**R-11 的 `meal_slots` 软惩罚（`+3.0/0.0`）本质上做不到"让这一顿更像这一顿"，只能轻微偏移。**
这是 `random_band` 机制决定的，不是参数没调好。PRD 若写"让结果更贴合餐次"，上线后会被当 bug 报上来。

##### 兜底方案 D（本版大概率吃不下，记档）

既然两者是同一旋钮，**唯一解法是让刻度跟打分量级匹配**：**`random_band` 按餐次取**（早餐档单独放大到 ~12）。
餐次信号既生效、带也不会被压到 14。代价：早餐档抽签更随机。
若产品最终要求"早餐必须明显像早餐"，**D 是唯一能同时满足的路**（A 只是"现在不塌"，C 根本做不到）。

---

#### (26) 口径修正：早餐的问题**不是"枯竭"，是"单调"**（2026-09-23）

| 度量 | 现状 | 判定 |
|---|---:|---|
| `natural_band_size` | 14 | **不枯竭**（> `POOL_MIN`=8，远 > `random_min_choices`=3） |
| 品类数 | **2** | 极单调 |
| 最大单品类占比 | **100%** | 完全被一个品类垄断 |

⇒ **若判据写成"band 不再枯竭"，现状（14 > 8）直接通过，把真正要治的东西放过去。**

**判据形态（不含数字，数字待补标后最坏情况实测）**：

1. `band` 内**品类数 ≥ N**（现状 2）
2. `band` 内**最大单品类占比 ≤ M**（现状 100%）—— **与 1 必须同时写**：只看一个会得出相反结论（C 品类数赢、A 集中度赢）
3. `natural_band_size > random_min_choices`(3) —— 防 padding 掩盖
4. 取 **P10 而非均值** —— 均值会被"大部分时候很宽"掩盖"少数时候塌了"

---

#### (27) 分母快照约定 + #33 已有真实案例（2026-09-23）

**343 vs 342 的差 1 已定位**：`id=397「纯 AI 菜」`，**2026-09-23 20:30 落库**，`is_dish=1`，**未经 is_dish 判定**
（`recipe` 总数 397 / `is_dish=1` 343 / `is_dish=0` 54）。

⇒ **TaskList #33（富集落库时对新菜做 `is_dish` 判定，只观测不拦截）不再是"以防万一"，是已经发生了一次。**

**约定（本报告后续一律遵守）**：所有覆盖率类指标**必须带上当时的分母快照**一起记录：

```sql
SELECT COUNT(*) FROM recipe WHERE is_dish=1;   -- 记录当时的值，与覆盖率并列
```

理由：基线会自己漂移。本报告 342 基数本身没错（是基线之后进了 1 道），但下次对不上还得查一遍。

---

#### (28) §5.2(17) 后续：三条旁路归零已落地，但**恢复条件有两处缺口**（2026-09-23）

三条 `SCORE_CUISINE` 已归零（`replacement` / `generation` / `fridge_menu` L50 = 0.0 ✅，本报告只读复核确认）。
requirement-analyst 逐条读了注释原文，**恢复条件已写**（最坏情况"只写归零不写恢复条件"未发生），但有两个残留缺口：

##### 缺口① 🔴 恢复目标值没写在任何一处 —— `fridge_menu` 原值是 **5.0 不是 20.0**

`fridge_menu_service.py` L42-50 的权重结构：

```
SCORE_STOCK         = 60.0   # 这道菜用到的食材，冰箱里已经有了多少
COVERAGE_FULL_BONUS = 20.0   # 食材全齐 → 现在就能做，额外重奖
SCORE_TASTE         = 10.0
SCORE_CUISINE       = 0.0    # ← 原值 5.0（不是 20.0）
SCORE_BUDGET        = 10.0
```

L10 文件头注释写明了设计意图：**"这里 `SCORE_STOCK` 一家独大，这也是『按冰箱重排』"**。

⇒ 若恢复时与另两处统一填 20.0，`SCORE_CUISINE` 会**从最小权重一跃成为与 `COVERAGE_FULL_BONUS` 并列的第二权重**
（是 `SCORE_TASTE`/`SCORE_BUDGET` 的两倍），**开始对抗"按冰箱重排"的核心设计意图**。
这不是"翻 4 倍"的幅度问题，**是改掉这条链路的排序逻辑**。

##### 缺口② 恢复条件只写了动作，没写效果

现写"真菜系回填"。但**只要有人跑了一次富集、回填 10 道，也会被当成"回填完成"然后恢复 20.0** ——
而 20.0 在低命中率下只会放大偏差。建议绑定效果：

> 恢复条件 = 凌晨 LLM 富集任务对 `recipe.cuisine` 完成标注回填（`enrich_source` 由 `rule` 变为 LLM），
> **且回填后 `recipe.cuisine` 与用户侧 `cuisines` 词表命中率 ≥ 60%**。
> 现状命中率 **0.5%**（唯一交集「川菜」2 道 / 396），所以这个门槛是有效的闸门。

##### 三条链路的风险性质不同，不能写成同一句话

| 链路 | 有无 band | 20.0 的后果 |
|---|---|---|
| `replacement_service` | **有** `LOCAL_RANDOM_BAND = 5.0`（L76），且只在 `LOCAL_TOP_K=3` 里切带 | 🔴 **会塌缩**，比决策链路更狠 |
| `generation_service` | 无 band，排序取前 30 喂 LLM | 🟠 把命中菜顶进短名单前排 |
| `fridge_menu_service` | **无 band**（grep 确认无 `RANDOM`/`BAND`/`choice`） | 🟠 **不会塌缩**，但会改写排序、对抗 `SCORE_STOCK` 独大 |

---

#### (29) 早餐定案：**方案 C + 封顶 4.0**；以及一条**判据量的自我撤回**（2026-09-23，team-lead 裁定）

##### 裁定

| 项 | 裁定 |
|---|---|
| 早餐 | **C（叠加 + 早餐相关加分合计封顶）**，封顶值 **4.0** |
| `INVENTORY_SCORE_CAP` | **5.0 → 4.0**（§5.2(21) 已批，不登记豁免） |

**否决 A**：`|Δ| > random_band` 是最坏情况判据；A 现在的"品类数 5 / 主面 46%"靠的是重叠只有 7 道 —— **是运气，不是机制，不能拿来做定案依据。**
**否决 B**：代理分 4.5 > 显式标注分 3.0 ⇒ 补一道标注少拿 1.5 分，**系统在惩罚补标注的人**（B 实测荤菜 65% 即为后果）。
**封顶取 4.0 不取 4.5**：4.5 只留 0.5 余量 ⇒ 未命中组要 base 落在 0.5 分内才进得来，**那已经是准硬过滤**；
4.0 与 `INVENTORY_SCORE_CAP` 同余量，**两套加分一条规矩，将来调 `random_band` 只算一次**。

> **"余量"的准确含义**：未命中组还能靠 base 分挤进抽签带的窗口大小。0.5 分的窗口等于没有。

##### 🔴 自我撤回：判据量「最大单品类占比 ≤ M」不能用

本报告曾向 PRD 建议判据含"band 内最大单品类占比 ≤ M"。**撤回。**

C-4.0 实测：**band=65 / 品类数 6 / 主面 26% / 荤菜 57%** ⇒ 若 M=50%，**C-4.0 不通过**。
但错不在 C，在这个量：

> **池子自然分布就是荤菜 52.2%。任何"不加偏好"的方案，最大单品类必然是荤菜、且必然 >50%。**
> ⇒ 设 M=50% 等于要求系统**主动压制池子第一大品类** —— 会把所有合规方案判死。
> 这正是 §5.2(25) 警告过的"用不合适的量把合规方案判死"，本报告自己造了一个。

**替换为「被加分扶持的那个品类」**：早餐关心的是**主面**（`主食+面食`，被 `+3.0/+1.5` 扶持的品类）。

| | 现状 | **C-4.0** | A（已否决） |
|---|---:|---:|---:|
| 主面占比 | 100% | **26%** | 46% |
| 主面相对池子自然占比 | 4.90x | **1.28x** | 2.25x |

**两种写法**：占比（直观，但阈值随池子自然分布漂移）/ 倍数（阈值稳定，不随池子漂移）。
**倾向倍数** —— 符合 §5.2(27)"基线会自己漂移"的教训。

##### 更新后的早餐判据形态（数字待实测）

1. `band` 内**品类数 ≥ N**（现状 2，C-4.0 = 6）
2. **主面占比 ≤ M** 或 **主面倍数 ≤ K**（替换"最大单品类占比"）
3. `natural_band_size > random_min_choices`(3) —— 防 padding 掩盖
4. 取 **P10 而非均值**

##### 需写进 PRD 让产品知情的两条

1. **C-4.0 之后早餐档基本等于"不施加餐次偏好"**（主面 1.28x ≈ 自然分布，荤菜 57%）。
   这是"本版治症状、V1.3 治病根"的既定代价。**不写明的话，上线后必然有人报"早餐怎么还是出荤菜"，而那不是 bug。**
2. **R-11 的 `meal_slots` 软惩罚只能"轻微偏移餐次构成"，做不到"让这一顿更像这一顿"** —— 机制决定（§5.2(25)），不是参数没调好。

##### 分母：343 的来源已查清（不必再等）

`id=397「纯 AI 菜」`，**2026-09-23 20:30 落库**，`is_dish=1`，**未经 is_dish 判定**。
⇒ 本报告 342 基数本身没错（基线之后进了 1 道），**不影响任何既有结论**；
⇒ 但 **TaskList #33 已有真实案例**，不再是"以防万一"。

---

#### (30) 🔴 软偏好包上线后暴露的 P0：`prefer_fridge` 是全量加分，会把整包顶满（2026-09-23 复核）

##### 背景：软偏好包的设计是对的

`decision_service.py` L1011-1038 把"倾向类"加分合成一个包再整体封顶：

```python
soft = 0.0                                        # L1013
soft += max(slot_score, breakfast_comp)           # L1028  餐次 / 早餐补偿，取 max
soft += self._inventory_score(...)                # L1031  库存（≤ INVENTORY_SCORE_CAP）
if intent is not None: soft += intent.bonus(c)    # L1036  口语诉求
score += min(soft, SOFT_PREFERENCE_CAP)           # L1038
```

L1012 的注释说得准确：**"单项各自 `<= random_band` 挡不住它们叠起来穿"** —— 这正是 §5.2(12) 通则的补丁。
**但从"单项各自合规"进到"整包封顶"，会引入一个单项时代不存在的新失败形态：包内挤占。**

##### 🔴 P0：`prefer_fridge` 对全池所有菜都加分

```python
# intent_service.py L170-171
if self.prefer_fridge and candidate.ingredients:
    s += 6.0          # candidate.ingredients 非空 ⇒ 全池成立
```

`SOFT_PREFERENCE_CAP = 5.0`，而 `prefer_fridge` 单独就是 **6.0 > 5.0** ⇒
**用户一说"用冰箱里的菜做"，每道菜的 `soft` 都 ≥ 6.0，`min(..., 5.0)` 全部 = 5.0 ⇒ 软偏好包变成常数。**

⇒ **早餐补偿、`meal_slots` 餐次贴合、`inventory` 库存命中，三者同时失去区分度。**

> **最讽刺的一点**：`prefer_fridge` 的语义是"想用冰箱食材"，**被它挤掉的正是 `inventory`（库存命中）** ——
> **用户最想用冰箱食材的时候，库存信号正好失效。方向完全相反。**

**补一条容易漏的**：`prefer_fridge` 在包封顶之前**也从来没有过区分度** —— 全量同加 6 分，相对排序不变，本来就是 no-op。
**是包封顶把它从"无用"变成了"有害"**：它吃掉了 5.0 的全部预算。

**修法（按偏好排序）**：
1. 移出软包，改成对 `inventory` 的**放大系数**（`inventory × 1.5` 再走 `INVENTORY_SCORE_CAP`）—— 才真正表达"想用冰箱食材"，且不吃别人预算
2. 或只对库存命中的菜加（`prefer_fridge and hits > 0`）
3. ❌ **压小幅度无效** —— 只要它是全量的，压到多小都是常数；压到 5.0 以内反而更糟（吃掉预算却不表达任何东西）

##### 挤占源不是 inventory（口径数据）

S1（3 项库存）下 `hits` 分布：**hits=0 68.4% / hits=1 28.9% / hits≥2 2.6%**
⇒ 库存拿满只影响 **2.6%** 的菜，**"两个封顶互相挤占"的实际风险很低**。
⇒ **真正的挤占源是 `prefer_fridge`（全量 6.0）和 `cuisine`（15.0）**，修的时候别盯着 inventory。

##### 另两处数值（已报 team-lead 追认）

**① `SOFT_PREFERENCE_CAP = 5.0` 恰好 = `random_band = 5.0` ⇒ 零余量。**
与 `INVENTORY_SCORE_CAP = 5.0` 是同一个毛病（"靠闭区间侥幸活着"）。**建议降到 4.0**。
⚠️ **顺序**：必须先修 `prefer_fridge`，否则降包后顶满问题原样复现。

**② 早餐实现是 `max(3.0, 4.5)`，不是裁定的"叠加 + 封顶 4.0"。**
`max` 一次性解决了两个问题：既不叠加到 7.5，又不会让显式标注分(3.0)低于代理分(4.5) ⇒ **不惩罚补标注的人**。
**但数值 4.5 ≠ 裁定的 4.0**（实测：4.0 → 主面 26% / 1.28x；4.5 → 主面 21% / 1.01x），需追认。

##### 附：`intent_service.cuisine +15.0` 的状态

它**不在 requirement-analyst 的"6 处恢复清单"里，但已安全** —— 被 `SOFT_PREFERENCE_CAP` 罩住，塌缩不了；
L164-167 注释已写明"修 cuisine 时必须一起把这里的幅度带上"。
**但恢复那天它会独占整包（15 > 5），把早餐/餐次/库存全部挤成 0** ——
这是**"包内挤占"，不是"塌缩"**，两种风险形态不同，PRD 里不得混写成一句。

---

#### (31) 🔴 C 方案的实测比"没早餐味"更严重：**主面 15.0% < 池子自然 20.4%**（2026-09-23）

##### 一、先接受一个纠正：用户看到的第一道 ≠ 排序第一名

`_pick()` 是 `band = _random_band(scored)` 之后 **`random.choice(band)` 均匀抽**。
⇒ **用户看到的第一道就是在带里随机抽的那道，不是 argmax。**
⇒ 本报告此前"带的构成只影响连点几次之后"的说法**作废**（dev-engine-relax 指出）—— **带的构成恰恰决定第一道。**

连带修正 §1.3 措辞：**"只能加分"不是"只能影响排序头部"，而是只能改变"用户从哪个分布里抽"。**
且在 `|Δ| <= random_band` 约束下这个影响很弱 —— **弱到可能连"回到自然分布"都做不到**（见下）。

##### 二、🔴 C-4.5 的主面占比低于"什么都不做"

| | band | 品类数 | 主面% | 荤菜% |
|---|---:|---:|---:|---:|
| 现状 `12/8` | 13 | 2 | **100.0** | 0.0 |
| A 叠加（已否决） | 23 | 5 | 42.4 | 23.8 |
| **C 封顶 4.5** | **54** | **6** | **15.0** | **65.8** |
| **池子自然分布** | — | 8 | **20.4** | **52.2** |

⇒ **C 不只是"约等于没偏好"——它是"加了早餐偏好之后，用户看到主食/面食的概率比什么都不做还低"。**
⇒ 荤菜 **65.8%**（自然 52.2%，**1.26x**）⇒ **C 治掉了"主面单调"，换来一个新的"荤菜偏斜"。**

**原因**：主面菜的**基线分系统性偏低**，`+4.5` 只把它们抬到抽签带下沿；
带（距榜首 5 分 = 14.5~19.5 的窗口）里其余位置被**基线本来就在 15~19 分**的荤菜/凉菜占满。
**4.5 分连基线差距都补不平。**

##### 三、反直觉：**提 `random_band` 会让主面占比上升**（不是下降）

| `random_band` | band | 主面% | 荤菜% |
|---:|---:|---:|---:|
| 5.0（现状） | 54 | 15.0 | 65.8 |
| **8.0** | 89 | **29.4** | 54.2 |
| **10.0** | 172 | **42.6** | 42.4 |

确定性复算（不靠采样）：top54 = 14.8% / top89 = 32.6% / top172 = 40.1%，与采样一致。

**机制**：**窄带被"基线分本来就高的菜"占满；宽带才装得下"靠加分进来的菜"。**

> ⚠️ 这与 §5.2(25)「幅度↑ ⇒ 带变窄 ⇒ 偏好控制力↑」是**两个不同的旋钮**：
> **改幅度**是 §5.2(25) 那条；**改 `random_band`** 是这条，**方向相反**。

⇒ **若产品要"早餐像早餐"，提 `random_band` 比提加分幅度更有效，而且更安全**
（`|Δ|=4.5` 相对 `band=10` 余量 5.5 分，不再是零余量）。
⇒ 代价：band 54 → 172，**用户几乎等于在 172 道里瞎抽**。

**`random_band=8` 那组在三个维度上都最健康**：主面 29.4%（> 自然 20.4%）、荤菜 54.2%（≈ 自然 52.2%）、band 89。

##### 四、⚠️ 待复核：同一方案前后两轮数不一致

| 轮次 | band | 主面% | 荤菜% |
|---|---:|---:|---:|
| 上一轮 | 58 | 21% | 60% |
| 本轮 | 54 | 15.0% | 65.8% |

差 6pp，超出采样误差（N=500 的 SE ≈ 1.8pp）。**在 dev-engine-relax 确认哪组是当前实现的真值之前，
本节所有数字均为"待复核"，不得写入 PRD。**

---

#### (31) 口径纠正 + 🔴 C 实测**反向**（0.74x），与被否决的 B 同一点（2026-09-23）

##### 口径纠正：**用户看到的第一道 ≠ 排序第一名**

`_pick()`（L803-806）是 `band = _random_band(scored)` 之后 **`random.choice(band)` 均匀抽**。
⇒ **argmax（榜首）对用户无意义**，本报告一律改用「**用户实际看到的第一道」= band 构成**。

**但由此推出"加分幅度影响不到用户所见"是过头的** —— 幅度 4.5 → 7.5，用户所见从 15.0% 跳到 42.4%，显然影响。

> **准确机制**：加分幅度**不是通过"排到前面"影响用户**（带内均匀抽，排序无意义），
> 而是**通过抬高 `best` ⇒ 抬高带下沿 ⇒ 改变带的边界 ⇒ 改变带的构成**。
> ⇒ **幅度仍是唯一旋钮，只是作用点不在排序上。**
> ⇒ §1.3 措辞订正为：**"只能加分 ⇒ 只能经由『带的边界』影响构成，不能经由『带内排序』影响。"**

##### 实测（真库 343，N=500，seed 固定；附确定性复算）

| 方案 | band | 品类数 | **主面%（用户第一道）** | 荤菜% | 相对池子自然(20.4%) |
|---|---:|---:|---:|---:|---:|
| 现状 `12/8` | 13 | 2 | **100.0** | 0.0 | 4.90x |
| **A `3.0/1.5` 叠加** | 23 | 5 | **42.4** | 23.8 | **2.08x** |
| **C（当前实现）** | **54** | 6 | **15.0** | **65.8** | **0.74x ← 反向** |
| （已否决的）B 互斥 | — | — | 15.0 | — | **0.73x** |

确定性复算：C 方案 top54 主面 **14.8%**（与采样 15.0% 一致，非抖动）。

##### 🔴 关键结论：C 是"反向"，不是"没味道"

- 上一轮测的 **C-4.0（叠加 + 封顶 4.0）= 主面 26% / 1.28x（中性）**
- **当前实现 `max(slot_score, breakfast_comp)`（L1028）= 主面 15.0% / 0.74x（反向）**

⇒ **实现方式从"叠加+封顶"改成 `max()` 之后，效果从 +1.28x 翻成 −0.74x。**
⇒ **C 与被否决的 B 落在几乎同一个点上（0.74x vs 0.73x）。**

**机制（待 dev-engine-relax 证实）**：`max()` 让**全部 48 道 breakfast 标注菜都拿到 3.0**，而这批菜多数**不是**主面（粥/凉菜/小吃/素菜）；同时新条件 `not c.meal_slots or slot in c.meal_slots` 把"标注成别的餐次"的主面菜排除在早餐补偿之外 ⇒ **非主面被抬起来，主面掉到自然分布以下。**

⇒ **PRD 里"产品知情事实：1.28x，基本不施加餐次偏好"与当前实现不符，须改。**
（1.28x = 中性；0.74x = 反向。产品是基于 1.28x 确认"可接受"的。）

##### 提 `random_band` 换品类分布 —— 建议否掉

| random_band | band | 主面% |
|---:|---:|---:|
| 5.0 | 54 | 15.0 |
| 8.0 | 89 | 29.4 |
| **10.0** | **172** | 42.6 |

**band=172 / 343 = 半个菜谱库** ⇒ "推荐"名存实亡，用户等于在半个库里瞎抽，**"饭决"的核心价值（替你决定）归零**。
⇒ **用提 `random_band` 换品类分布，是卖掉产品核心价值换一个中间指标，不划算。**

##### 当前唯一该做的动作：跑补标后的 A

A 在"用户看到什么"口径下是**唯一合理的**（42.4% 主面 / 23.8% 荤菜 / band=23 仍是个像样的决定）。
A 唯一的罪是越过代理线（7.5 > 5.0）⇒ **把最坏情况跑掉，不要在 A/C/D 之间猜**：
给所有 `category∈(主食,面食)` 且 `≤15min` 的菜人为补上 breakfast 标注（重叠 7 道 → 接近满），再测 A。
- 补标后不塌 ⇒ **A 就是答案**（真判据是实测，不是代理线）
- 补标后塌 ⇒ 回来谈"接受 C 的 0.74x"还是"接受现状 100%"

##### 附：实测数值入档须带"当时实现口径"

1.28x 这条**在上周是正确的**（叠加口径实测），**是实现改成 `max()` 之后才过期的**。
⇒ **正确结论 + 实现变更 = 文档里最难发现的一类错误。**
⇒ 凡"实测数值"入档，**一律带上当时的实现口径**（与 §5.2(27) 覆盖率带 `COUNT(*)` 分母快照同理）。

---

#### (31) 🔴🔴 口径纠正：**用户看到的第一道 ≠ argmax**；据此 C 是**反向**的（2026-09-23）

##### 我们之前共用的前提是错的

`_pick()` 是 `band = _random_band(scored)` 之后 **`random.choice(band)` 均匀抽**。

⇒ **用户看到的第一道 = 带里随机一道，不是排序第一名。**
⇒ 本报告此前"带的构成只影响连点几次之后"的说法**作废** —— **带的构成恰恰决定第一道。**

**三个口径必须分开**（dev-engine-relax 提出，本报告采纳）：

| 口径 | 含义 | 能否作产品结论 |
|---|---|---|
| **用户第一道概率** | = 带内占比（均匀抽带） | ✅ **主口径** |
| 带内占比 | 同上（两者同源） | ✅ |
| `argmax` 榜首 / 前 5 | 确定性副产品，**用户从来看不到** | ❌ **不得作为产品结论** |

> ⚠️ C 的 `argmax` 榜首是「红芸豆拌饭 主食 19.5」、前 5 全是主面 ——
> **若拿它说"早餐味很足"就完全错了**，用户根本看不到 argmax。

##### 用正确口径重看：C 是反向的

| 方案 | 主面%（**用户第一道**） | 品类数 | 荤菜% | 池子自然（主面） |
|---|---:|---:|---:|---:|
| 现状 `12/8` | 100.0% | 2 | 0.0 | 20.4% |
| A `3.0/1.5` 叠加 | 42.4% | 5 | 23.8% | 20.4% |
| **C 封顶 4.5** | **15.0%** | 6 | 65.8% | **20.4%** |

**C 的主面概率 15.0% 低于池子自然占比 20.4% —— C 比"什么都不做"还要不像早餐。**

**根因**（上榜首表可见）：`凉拌豆腐 16.5 凉菜`、`凉拌金针菇 16.5 凉菜` 靠 **`meal_slots` 含早餐**拿 +3.0。
⇒ **`meal_slots` 标成 breakfast 的 48 道，多数不是主/面**（粥/小吃/素菜/凉菜），给它们加分反而抬高非主面，**压低主面占比**。

> ##### ⚠️ 撤回：「C 反向」**只适用于 `max()` 实现**，不适用于裁定的 ①
>
> 本报告曾据上表判"C 反向（15.0% < 自然 20.4%）"。**该结论已撤回** —— 它只对现行的
> `max(slot, comp)` 成立；**裁定的 ① 是 `min(slot + comp, CAP)`，两者数学上不等价。**
>
> | 实现 | band | 主面%（用户第一道） |
> |---|---:|---:|
> | `max(slot, comp)`（现行，已被裁定替换） | 54 | **15.0%** |
> | ① `min(slot+comp, 4.5)` | 57 | **20.0%** |
> | **① `min(slot+comp, 4.0)`（裁定值）** | **65** | **26%** |
>
> 池子自然 20.4% ⇒ **① + 4.0 = 26% > 自然**，是"略高于自然、不垄断"，**不是反向**。
>
> **等价性反例（dev-engine-relax 提供，本报告原判断错误）**：差异落在**已标注**的那批菜上 ——
> `max` 给 3.0、叠加后封顶给 4.5，差 1.5 分；而**标了 breakfast 的 46 道里 40 道是主/面**，
> 正是最该出早餐的那批，这 1.5 分把它们挪进挪出带下沿 —— **就是那 5pp 的来源。**
>
> **裁定（C + 封顶 4.0 + ①）成立。** 保留不阻断的数据侧备注：
> A 在用户第一道口径下 42.4%（≈2.1x）优于 C-4.0 的 26%，A 的否决理由仍需补标后实测证实/证伪。

##### ⚠️ 本节上述"根因"已撤回 —— 见下

**本报告此前写的根因「`meal_slots` 标 breakfast 的菜多数不是主/面」是错的，撤回。**
dev-engine-relax 实测：**46 道标了 breakfast，其中 40 道是主食/面食（87%）**。

**错误来源**：本报告作者从榜首表里 `凉拌豆腐 16.5 凉菜`、`凉拌金针菇 16.5 凉菜` **两行**推断整体分布 ——
**拿 2 个可见样本概括 46 道**。这正是本报告一直警告他人的错（"给断言前先实跑一遍"），本次犯在作者自己身上。

##### 真实机制：被压的是"双命中"的那批

`comp = 3.0(主/面) + [1.5 if ≤15min]`，`slot = 3.0`：

| 这道菜 | `max(slot, comp)` | `min(slot+comp, 4.5)` |
|---|---:|---:|
| **已标注 + 主面 + 慢(>15min)** | **3.0** | **4.5** |
| 已标注 + 主面 + 快手 | 4.5 | 4.5 |
| 未标注 + 主面 + 慢 | 3.0 | 3.0 |

⇒ **`max` 压制的是"已标注 + 主面但不快手"这一批：两个来源都命中却只拿一份。**
⇒ 这批是 46 道里的多数 ⇒ 少拿 1.5 分 ⇒ 掉出抽签带 ⇒ 主面% 20.0 → 15.0。

**⇒ "反向"限定对象是 `max` 实现，不是裁定方案本身**（team-lead 已将 `max` 改回 ①）：

| 实现 | 主面%（用户第一道） | 判定 |
|---|---:|---|
| `max(slot, comp)`（当时线上） | **15.0%** | ❌ 低于自然 20.4% = 反向 |
| `min(slot+comp, 4.5)`（叠加后封顶） | **20.0%** | ✅ = 自然占比 |
| **① 叠加 + 封顶 4.0（裁定）** | **待实测，预期 18–20%** | 预期"不反向，但也没早餐味"（中性结果，不是"修好了"） |

##### 两个"封顶 4.5"数学上不等价（同一池 343、同一 seed）

| 公式 | band | 品类数 | 主面% | 荤菜% |
|---|---:|---:|---:|---:|
| `max(slot, comp)` | **54** | 6 | **15.0** | 65.8 |
| `min(slot+comp, 4.5)` | 57 | 6 | **20.0** | 61.2 |

⇒ 前一版本报告中的 58 / 21% / 60% 应按"叠加后封顶"这一列理解；**现行 `max` 实现的真值是 54 / 15.0% / 65.8%。**

##### 判定线按"用户第一道"口径重定

> **理想 = 主面概率略高于自然占比（1.5–2x）且不垄断。**
> **低于自然占比（< 20.4%）= 反向，不可接受。**

⇒ **A（42.4% ≈ 2.1x，品类 5）是唯一落在理想区间的方案。**
⇒ **A 的否决理由（最坏情况会塌）必须用补标后实测证实或证伪**，不能靠代理线直接判死。
   （若补标后 A 不塌，本报告建议选 A 而非 C —— C 有确凿实测缺陷，A 的缺陷未被证实。）

##### 方案 D（提 `random_band`）的实测代价 —— 方向与直觉相反

| `random_band` | band | 品类数 | 主面% | 荤菜% | 汤羹% |
|---:|---:|---:|---:|---:|---:|
| 5.0（现状） | 54 | 6 | 15.0 | 65.8 | 0.0 |
| 8.0 | 89 | 6 | **29.4** | 54.2 | 0.0 |
| 10.0 | 172 | 7 | **42.6** | 42.4 | 3.0 |

**加宽 band 反而让主面占比上升**（主面加分后集中在窗口下沿，窗口往下开放进来的主面比例更高；确定性复算 top54 14.8% / top89 32.6% / top172 40.1%，与采样一致，不是抖动）。

⇒ **这笔交易 = 随机性大幅上升（54 → 172，用户几乎在 172 道里瞎抽），换来主面 15% → 42%。** 需产品定价。

##### 三个旋钮是独立的三件事（dev-engine-relax 拆解，本报告采纳）

| 旋钮 | 主面%（用户第一道） | 代价 | 状态 |
|---|---:|---|---|
| **① 公式**（`max` / 叠加后封顶） | 15.0 ↔ 20.0 | **0 随机性代价** | team-lead 已裁 ①（叠加+封顶 4.0） |
| **② `random_band`**（5 / 8 / 10） | 15.0 / **29.4** / **42.6** | 随机性同步放大（band 54→89→172） | 待产品定价 |
| **③ `meal_slots` 硬过滤 + 放宽兜底** | 唯一能真正做出品类构成的路子 | 之前被否过 | 待定 |

⇒ **只有 ② 能在不动语义的前提下把主面% 拉到有意义的位置**，代价是随机性；
⇒ **③ 是唯一能把"早餐真像早餐"做成结构性结果的路子**（§5.2(25)：加分幅度这条路在 `random_band` 机制下走不通）。

---

#### (32) `prefer_fridge` 确诊：命中面 **93.9%**，整包恒等于 `SOFT_PREFERENCE_CAP`（2026-09-23）

```python
# intent_service.py L170-171
if self.prefer_fridge and candidate.ingredients:
    s += 6.0
```

**命中面 = 322/343 = 93.9%**（只要菜有食材行就给满）。

⇒ 进包后 `min(inventory + max(slot,comp) + 6.0, SOFT_PREFERENCE_CAP=5.0)` **恒等于 5.0**。
⇒ 这不是"失去区分度"，而是**一道零余量的二元硬分区**：93.9% 的菜整包拿 5.0、6.1% 拿不到，而 **5.0 == `random_band`**。
⇒ 用户说"用冰箱里的菜"⇒ **早餐补偿 / 餐次贴合 / 库存命中三笔全部失效**，决策退化成"有没有食材行"这一个二元判断。

**状态：已确诊、未修、等指派**（`intent_service.py` 不在 dev-engine-relax 所有权内，已报 team-lead）。

> **是 `SOFT_PREFERENCE_CAP` 上线把它从"幅度偏大"放大成 P0 的** —— 之前 6.0 只是单项越界，现在它直接顶满整包。

**修法（优先序）**：
1. **改成按命中数给档**（像 `_inventory_score` 那样 0/2/4）—— 既符合"冰箱优先"的语义，又天然 ≤ band，且不必在 PRD 上重新定义它是"倾向"还是"硬规则" ✅ 推荐
2. 压到 2.0–3.0，给早餐/餐次留位置
3. 挪出软偏好包 —— 但这等于承认"冰箱优先"是硬规则，需先在 PRD 上写清楚

##### 对 §1.3 措辞的再推进（dev-engine-relax 补充，本报告采纳）

原："只能加分 ⇒ 只能影响排序头部"。
**改为**：在均匀抽带机制下，**连"谁排第一"都影响不到用户看到什么**；
影响用户所见的唯一旋钮是"带里有哪些菜"，而带由 `random_band` 与各打分项的**基线分布**共同决定，**加分幅度只是入场券**。

⇒ **本条对 §1.3 中所有"只能加分"的结论同等适用**（R-11 / `INVENTORY_SCORE_CAP` / `meat_type` / 未来任何软偏好）。

---

#### (32) 🔴🔴 补标后最坏情况实测：**A 没塌 / C 会失效**；通则补上「命中组规模」（2026-09-23）

##### 先撤回：本报告的一个方法错误

曾断言"`meal_slots` 标成 breakfast 的 48 道多数不是主/面"，依据是榜首表里的 `凉拌豆腐`、`凉拌金针菇` 两道凉菜。
**实测：标注 breakfast 的 46 道，主面 40 道 = 87.0%**（面食 21 + 主食 19），非主面仅 6 道。**断言错误，撤回。**

> **教训（方法层面）**：**榜首表是极值样本**（能上榜首的恰恰是拿满加分的异常菜），
> **从榜首表推断分布 = 从极值推断总体。要看分布就得要分布。**

##### 补标后最坏情况（模拟"所有主面 / ≤15min 都补 breakfast"，新补 113 道，共 159/343 = 46% 拿到加分）

| 方案 | band | 品类数 | 主面% | 相对自然 | 最大品类 |
|---|---:|---:|---:|---:|---|
| **A 叠加不封顶** | **22** | 5 | **40.4%** | **1.98x** | 素菜 27.0% |
| ③ 叠加+封顶 4.0（C-4.0） | 77 | 6 | 19.8% | **0.97x** | — |
| ④ 叠加+封顶 5.0 | 75 | 6 | 20.8% | 1.02x | — |
| ① 当前 `max()` | 55 | 6 | 14.8% | 0.73x | 荤菜 64.2% |

**两条结论**：

1. **否决 A 的唯一理由（"补标后会塌"）实测不成立** —— A 补标后 band=22 > 下限 18、品类 5、最大品类 27%。
2. 🔴 **补标会毁掉 C-4.0**：现在 27.6%（1.35x）→ **补标后 19.8%（0.97x），跌回自然分布以下**。
   原因：补标规则是"主面 **或** ≤15min"，而 ≤15min 覆盖大量非主面 ⇒ **补标稀释了早餐信号**。

> **选 C = 选一个"现在有效、补标后失效"的方案，而补标是既定方向。**
> 这就是本报告追了一整轮的静默失效：**上线看着有效，数据改善后悄悄失效，没人回头查。**

##### 🔴 通则修正：`|Δ| ≤ random_band` 是**充分不必要**的安全条件（dev-engine-relax 提出，共同确认）

> **塌缩风险 = f(幅度, 命中组规模)。**
> 幅度 > `random_band` **且命中组小** ⇒ 塌；幅度 > band **但命中组大** ⇒ 不塌。

原通则的推导里有个**没写出来的假设：命中组是少数**（少数菜独占加分 ⇒ 抬高 `best` ⇒ 把别人挤出带）。
A 的命中组 **46%** —— 带里本来主要就是这批菜，加分不产生独占。

三案例一次讲清：

| 案例 | 幅度 | 命中组占比 | 结果 |
|---|---:|---:|---|
| `meal_slots` `+12/-20` | 32 | 13% | 塌 |
| 早餐 A（叠加 7.5） | 7.5 | **46%（补标后）** | **不塌** |
| `score_inventory` 归一化 | 25 | 0.9% | 塌 |

**落地成两层（静态自检仍能活）**：

> **第一层（静态自检，便宜的代理）**：单项二元幅度 `≤ random_band`。
> 不通过 ⇒ 必须实测补标后场景才放行；通过 ⇒ 也不免除实测（仅优先级低）。
> **第二层（真判据）**：在**最坏情况**（命中组规模按补标完成后取值）实测
> `natural_band_size` + 品类数 + 最大单品类占比。
> **门禁须直接输出「命中组占比 = 拿到该加分的菜数 / 池子大小」**，否则第二层不可执行。

##### 为什么 `max()` 会把主面压低 1.0 分（真因，非本报告原猜测）

`max()`：主面快手 = max(3.0, 4.5) = 4.5；**主面不快手 = max(3.0, 3.0) = 3.0**；非主面标早餐 = 3.0
⇒ "主面不快手"与"非主面标早餐"**合并到同一档**，主面整体被压低 1.0 分。

> **`max()` 与封顶是两把锁，第二把把第一把的效果抵消了。**
> 论证 `max()` 时的前提是"叠加会拿 7.5"，但叠加后再封顶 4.0，7.5 早被吃掉 —— 该前提在 ① 里不存在。

##### 三个旋钮彼此独立，不得混谈

| 旋钮 | 效果（早餐档主面%） | 代价 |
|---|---|---|
| **公式**（`max` / 叠加后封顶） | 15.0 ↔ 27.6 | 0 随机性代价；牵涉"要不要奖励补标注" |
| **`random_band`**（5 / 8 / 10） | 15.0 ↔ 29.4 ↔ 42.6 | 随机性同步放大（band 54 → 89 → 172） |
| `meal_slots` 硬过滤 + 放宽兜底 | 唯一能真正决定品类构成 | 覆盖率 20.5%，本版撑不住 |

##### 机制表述（最终版）

> 加分幅度**不是**通过"排到前面"影响用户（带内均匀抽），而是**抬高 `best` ⇒ 抬高带下沿 ⇒ 改变带的边界 ⇒ 改变带的构成**。
> 效果大小取决于**命中组在带边界附近的密度**。

⇒ 解释了 ①/③/A 的 15% / 27.6% / 44.2% 全部差异，也解释了**为何提 `random_band` 会升主面占比**
（窗口往下开，边界掠过主面密集区）。

---

#### (32) 🔴 「交给外卖吧」阈值：per-dish ≠ per-decision，且**"还原到改前"这个目标本身是错的**（2026-09-23）

##### 背景

`_STAPLES` 剔除葱姜蒜后，外卖文案（③ `is_bad and ratio < 0.3`）的 per-dish 触发率跳升：

| 库存集 | 改前 → 改后（per-dish, `ratio<0.3`） | Δ |
|---|---|---:|
| S1 只有葱姜蒜(5) | 64.3% → 89.8% | +25.5pp |
| S2 家常(9) | 55.6% → 83.5% | +28.0pp |
| S3 大冰箱(13) | 52.8% → 80.1% | +27.3pp |

dev-engine-relax 给的阈值表显示 **T=0.10 时三个集与改前差 ≤1.8pp**，据此建议 `0.3 → 0.1`。

##### 一、T=0.10 的"还原"只在 per-dish 口径下成立

**per-decision（用户看到的）≠ per-dish，且偏差同向叠加**，三个机制：

1. 推荐从 band 抽，band 是高分段的截断 ⇒ 系统性偏向高 ratio（ratio 经 `_weather_score` 进 `score`）
2. **文案只在 `is_bad` 时触发**，而坏天气**恰恰是 `_weather_score` 生效的场景** ⇒ 偏差在我们要测的这群决策上被**放大**，不是被平均掉
3. `_weather_score` 的分档（0.3 / 0.1）**没跟着改** ⇒ 改后 ratio 分布整体下移 ⇒ `≥0.3` 档命中组变小 ⇒
   按 §5.2(31) 通则（**塌缩风险 = f(幅度, 命中组规模)**），`+18` 幅度大 + 命中组变小 ⇒ **该档可能变成硬分区**

⇒ **净效应方向无法从现有数据推断**（ratio 下移 ⇒ 触发率↑；命中组变小 ⇒ band 被高 ratio 垄断 ⇒ 触发率↓，两个效应相反）。
⇒ **本报告不给猜测方向，只给口径规格**（见下）。

##### 二、🔴 "还原到改前"这个目标本身是错的

±5pp 原则的原文是「**排序**修复不得让文案触发率变化超过 ±5pp」。
**但这次改的不是排序，是"什么算有料"的语义定义**（`_STAPLES` 剔除葱姜蒜）。

⇒ **改前的 64.3% 恰恰是错的** —— 它把"冰箱里只有葱姜蒜"当成了"有料"。
⇒ **把触发率强行压回改前 = 把这个 bug 修完再装回去。**

与 §5.2(14) A22 的结论同一条：**"调味料不算『家里有』，否则几乎每道菜都满分。"**

##### 三、同一个 T 在 S1 上正确、在 S3 上错误

| 库存集 | 改后触发率 | 语义判定 |
|---|---:|---|
| S1 只有葱姜蒜(5) | 89.8% | ✅ **对** —— 确实没料，该弹外卖 |
| S3 大冰箱(13) | **80.1%** | 🔴 **不对** —— 有 13 样还说"交给外卖" |

⇒ **真正要处理的对象是 S3，不是 S1；"统一还原"做不到，也不该做。**

##### 四、S3 的 80.1% 根因不是阈值，是分母

`ratio = hits / len(need)`：**一道菜标 10 种食材、用户冰箱 13 样命中 2 样 ⇒ ratio = 0.2 ⇒ 触发文案。**
⇒ 与 §5.2(14) 定位的 `score_inventory` 根因**同一个**：**归一化分母随菜剧烈变化**（A23 已排 V1.3）。
⇒ **T 从 0.3 挪到 0.1，是在错误分母上挪阈值，治标。**

**必须在 PRD 写明**：
> 本阈值是在 `ratio = hits / len(need)` 这个错误分母上的补丁；**V1.3 改分母后必须重定，否则静默失效。**

##### 五、本报告结论

1. **T 现在不拍** —— 判据必须用 per-decision，现有数全是 per-dish
2. **"维持 0.3 还是改 0.1"不是正确问法** —— 正确问法是"**S3 大冰箱 80% 弹外卖能不能接受**"（本报告判断：不能，但这是分母问题不是 T 问题）
3. **S1 不要动** —— 89.8% 是对的
4. **若本版必须拿一个数**：倾向**维持 0.3 不动**，把 S3 的 80% 记为已知缺陷 + V1.3 改分母后重定。
   理由：**为治 S3 而把 T 压到 0.1，会连带把 S1 那个"刚修对"的 89.8% 压回 66.1%（错的）。**

##### 六、补跑口径规格（交 dev-engine-relax，本报告不跑）

> **per-decision 口径 = band 内 `ratio < T` 的占比**（`random.choice` 均匀抽带 ⇒ 等价于 per-decision 触发率的期望值）

| 项 | 要求 |
|---|---|
| 场景 | `condition` = **坏天气**（`is_bad=True`）—— 文案只在此条件下触发 |
| 库存集 | S1 / S2 / S3 |
| 代码状态 | **改前（旧 `_STAPLES`）与改后各跑一遍** —— 没有改前就没有 Δ |
| 输出 1 | band 内 `ratio < T` 占比，T = 0.05/0.10/0.15/0.20/0.30 全列 |
| 输出 2 | `natural_band_size` + **band 内 ratio 的 P10/P50/P90**（看 band 是否被 `+18` 档垄断） |
| 输出 3 | **命中组占比** = 拿到 `+18`（ratio≥0.3）的菜数 / 池子（验"命中组变小 ⇒ 塌缩"） |

**判定**：per-decision 下改前→改后 Δ ≤5pp 才算"没变"；**T 取让 S2/S3 的 per-decision Δ 最小的那个值（S1 不参与选 T）**。

---

#### (32) 早餐四个变体的完整实测 + 两处**反直觉**结论（2026-09-23，真库 343，N=500，用户第一道口径）

| 变体 | band | 品类数 | 主面% | 荤菜% | 榜首 |
|---|---:|---:|---:|---:|---|
| **现行 `max(slot, comp)`** | 54 | 6 | **15.0** | 65.8 | 主食 |
| 叠加 + 早餐项顶 **4.5** | 57 | 6 | **20.0** | 61.2 | 面食 |
| **叠加 + 早餐项顶 4.0**（= 裁定 ①） | 64 | 6 | **23.4** | 60.4 | 面食 |
| **A 叠加不封顶**（7.5） | 23 | 5 | **42.4** | 23.8 | 面食 |
| 池子自然 | — | 8 | **20.4** | 52.2 | — |

##### 反直觉一：**封顶压得越低，主面% 反而越高**（20.0 → 23.4，band 还变宽 57 → 64）

机制：封顶越低 ⇒ 榜首那道"快手主食"的优势被削得越多 ⇒ 窗口下移 ⇒ 更多"主面但**不快手**"的菜进来。
⇒ **"封顶值越大越偏主面"是错的，别按直觉调。**

##### 反直觉二：`max()` 与封顶是**两把锁，第二把抵消第一把**

`max()` 的论证前提是"叠加会拿 7.5 > band"。但**叠加之后再封顶，7.5 早被吃掉** —— 该前提在 ① 中不存在。
⇒ **现行 `max()` 是四个变体里最差的（15.0%，低于自然 20.4%）**。

`max()` 的真实机制（dev-engine-relax 定位）：
- 主面快手 = `max(3.0, 4.5)` = 4.5
- **主面不快手 = `max(3.0, 3.0)` = 3.0** ← 被压低 1.0
- 非主面标早餐 = 3.0
⇒ "主面不快手"与"非主面标早餐"合并到同一档，**主面整体被压低 1.0 分**。

##### 🔴 `E40`（整包顶 4.0）与 `D40`（早餐项顶 4.0）**在有冰箱时不是同一个方案**

两者在**库存为空**时数值相同（23.4%），dev-engine-relax 已注明"真有冰箱时会分叉"。

| | 早餐项封顶 4.0（D40） | 整包封顶 4.0（E40） |
|---|---|---|
| 库存为空 | 23.4% | 23.4%（等价） |
| **有冰箱时** | 早餐 ≤4.0，库存**另算** | 早餐+库存+intent **合计** ≤4.0 ⇒ **互相挤占** |

⇒ **"有冰箱"是首页主场景**（R-09 是首页核心），**空库存下测出的等价在主场景不成立**。
⇒ 叠加 §5.2(30) 的 P0（`prefer_fridge` 命中面 93.9%、单项 6.0）：**E40 会被 `prefer_fridge` 单独顶满，早餐与库存全归零**；D40 不受此挤占。
⇒ **这是"抗挤占" vs "抗叠加"的取舍**，需 team-lead 裁定。

##### 补标注的收益只有 20% —— 两面都堵死

```
标了 breakfast 的菜 46（其中主面 40 = 87.0%，非主面 6）
进带的标注主面：C 现行 max = 5/40，D45 = 8/40，D40 = 8/40
```

- 补标注收益 **8/40 = 20%** ⇒ **不能拿"补标后就好了"当缓兵之计**
- 而补标对 C 是**净伤害**（23.4% → **19.8%**，跌破自然分布 20.4%）⇒ **也不能说"补标无害"**

⇒ **补标既救不了 C，还会伤 C。**

##### A 在补标后**不塌**（最坏情况实测）

模拟"所有主面 / ≤15min 都补 breakfast 标注"（新补 113 道，共 **159/343 = 46%** 拿到加分）：

| 方案 | band | 品类数 | 主面% | 相对自然 | 最大品类 |
|---|---:|---:|---:|---:|---:|
| **A 叠加不封顶** | **22** | 5 | **40.4%** | 1.98x | 素菜 27.0% |
| ③ 叠加+封顶 4.0 | 77 | 6 | 19.8% | **0.97x** | — |
| ① 现行 `max()` | 55 | 6 | 14.8% | 0.73x | 荤菜 64.2% |

⇒ **否决 A 的唯一理由（补标后会塌）实测不成立。**
⇒ A 补标前后稳定（42.4% → 40.4%）；C 补标后跌破自然分布。

##### 通则再修正：**塌缩风险 = f(幅度, 命中组规模)**（dev-engine-relax 提出，共同确认）

原通则的推导漏了一个隐含假设：**命中组是少数**（少数菜独占加分 ⇒ 抬高 `best` ⇒ 把别人挤出带）。

> 幅度 > `random_band` **且命中组小** ⇒ 塌；幅度 > band **但命中组大** ⇒ 不塌。
> ⇒ **`|Δ| ≤ random_band` 是充分不必要的安全条件，真判据是最坏情况下的实测。**

| 案例 | 幅度 | 命中组 | 结果 |
|---|---:|---:|---|
| `meal_slots` `+12/-20` | 32 | 13% | 塌 |
| inventory 归一化 | 25 | 0.9% | 塌 |
| **早餐 A（叠加 7.5）** | 7.5 | **46%（补标后）** | **不塌** |

**两层判据（可落进门禁）**：
1. **静态自检（便宜的代理）**：单项二元幅度 `≤ random_band`；不通过 ⇒ 必须实测补标后场景才放行
2. **真判据**：在最坏情况（命中组按补标完成后取值）实测 `natural_band_size` + 品类数 + 最大单品类占比
   ⇒ 门禁需额外输出 **命中组占比 = 拿到该加分的菜数 / 池子大小**，否则第二层不可执行

##### ⚠️ 方法论教训（本报告作者，第二次同型错误）

曾从榜首表的 `凉拌豆腐`、`凉拌金针菇`（2 道凉菜）推断"46/48 道标注菜多数不是主面"，
实测 **87.0% 是主面**（面食 21 + 主食 19）。

> **榜首表是加分机制的产物，不是池子的抽样。** 用它反推池子构成 = 用模型输出验证模型输入。
> **纪律：给任何人看榜首表，必须同时给池子自然占比。**

---

#### (32) 两种"空"不是一回事：**0 值 ⇒ 恒假，NULL ⇒ 恒真**（2026-09-23）

顺着"判据不能被最差实现满足"往下推时发现：**我们把两类空值混着处理了，而它们的失败方向相反。**

| 字段 | 存量的"空" | 风险形态 | 正确处理 |
|---|---|---|---|
| `candidate_count` | **0**（有值但无意义；R-07 前的历史行 **190 条**） | **恒假** —— 把 P10 拉到 0，判据永远失败 | `AND candidate_count > 0` |
| `natural_band_size` / `band_size` | **NULL**（当时没测） | **恒真** —— 告警遇不可计算的行最常见实现是"跳过检查"，**什么都不做就自动通过** | 门禁不得使用；**只在非 NULL 行统计** |

⇒ **同一份判据里，"0"和"NULL"必须分开写，不能合成一句"排除空值"。**
⇒ 与 §5.6 第三条护栏配成一对：**恒假（0 值）与恒真（NULL）是两种失败，处理方式相反，混写必然漏一个。**

**推论：`COALESCE` 是这两类失效的共同载体。**
`COALESCE(a, b)` 的语义是"取第一个非 NULL" ⇒ 它把 **`NULL = 没测` 静默伪装成 `有值 = 测了`**。
⇒ `COALESCE(band_size, candidate_count)` 与 `COALESCE(natural_band_size, candidate_count)` 是**同一失效形态**，一律禁用。

**裁定（12y 终裁）**：J6'/J7' 门禁 = `candidate_count`；新增 **J8 = `natural_band_size`，诊断非门禁，只在非 NULL 行统计**。
理由（比本报告此前给的语义论据更硬）：`natural_band_size` 存量 **192 行只有 2 行有值 = 99% NULL** ⇒
**一个字段能不能当门禁，先过失效层（缺数会不会静默通过），再谈语义层（两个量可不可比）。**

---

#### (33) 早餐方案实测汇总（真库 343，N=500，**用户第一道口径**，dev-engine-relax 只读脚本）

##### 未补标

| 变体 | band | 品类数 | 主面% | 荤菜% | 相对自然 |
|---|---:|---:|---:|---:|---:|
| 现状 `12/8` 叠加 | 13 | 2 | 100.0 | 0.0 | 4.90x |
| **A 叠加不封顶（3.0+1.5+3.0=7.5）** | 23 | 5 | **42.4** | 23.8 | 2.08x |
| 叠加 + 早餐顶 4.5 | 57 | 6 | 20.0 | 61.2 | 0.98x |
| **③ 叠加 + 早餐顶 4.0（= 裁定 ①）** | 64 | 6 | **23.4** | 60.4 | 1.15x |
| **① 现行 `max(slot, comp)`** | 54 | 6 | **15.0** | 65.8 | **0.73x** |
| 池子自然 | — | 8 | 20.4 | 52.2 | 1.00x |

##### 补标后最坏情况（模拟"所有主面 / ≤15min 补 breakfast"，共 159/343 = 46% 拿到加分）

| 方案 | band | 品类数 | 主面% | 相对自然 | 最大品类 |
|---|---:|---:|---:|---:|---:|
| **A 叠加不封顶** | **22** | 5 | **40.4** | **1.98x** | 素菜 27.0% |
| ③ 叠加 + 顶 4.0 | 77 | 6 | 19.8 | **0.97x** | — |
| 叠加 + 顶 5.0 | 75 | 6 | 20.8 | 1.02x | — |
| ① 现行 `max()` | 55 | 6 | 14.8 | 0.73x | 荤菜 64.2% |

##### 六条结论

1. **否决 A 的唯一理由（"补标后会塌"）实测不成立** —— A 补标后 band=22 > 下限 18，品类 5，最大品类 27%。
2. **补标会毁掉 ③** —— 23.4%（1.15x）→ 19.8%（**0.97x，跌破自然**）。补标规则"主面 **或** ≤15min"覆盖了大量非主面 ⇒ **补标稀释早餐信号**。
   ⇒ 选 ③ = 选一个"现在有效、补标后失效"的方案，而补标是既定方向 —— **正是本报告追了一整轮的静默失效**。
3. **现行 `max()` 是四个变体里最差的**（15.0% < 自然 20.4%）。
   `max()` 与封顶是两把锁：**叠加之后再封顶，7.5 早被吃掉**，第二把锁把第一把的效果抵消了。
4. **🔴 反直觉：封顶压得越低，主面% 反而越高**（4.5 → 20.0%；4.0 → 23.4%），band 也变宽（57 → 64）。
   机制：封顶越低 ⇒ 榜首那道快手主食的优势被削越多 ⇒ 窗口下移 ⇒ 放进更多"主面但不快手"的菜。
   ⇒ **"封顶值越大越偏主面"是错的，别写反。**
5. **补标注的收益只有 20%**：进带的标注主面 —— `max()` 5/40、叠加 8/40 ⇒ **即便改成叠加，80% 补了标注的早餐主面菜仍进不了带**。
   ⇒ 补标**既救不了 ③，还会伤 ③**。
6. **`max()` 与"叠加后封顶"数学上不等价**（本报告曾误判为等价）。反例在**已标注**的菜上：
   `max` 给 3.0、叠加后封顶给 4.5，差 1.5；而**标了 breakfast 的 46 道里 40 道是主面**，正是最该出早餐的那批。

##### 🔴 一个会在主场景分叉的陷阱

| | 早餐项封顶 4.0 | 整包封顶 4.0 |
|---|---|---|
| **库存为空** | 23.4% | 23.4%（等价） |
| **有冰箱时** | 早餐 ≤4.0，库存**另算** | 早餐+库存+intent **合计** ≤4.0 ⇒ **互相挤占** |

⇒ **在空库存下测出来的等价，在主场景（有冰箱）下不成立。**
⇒ 叠加 §5.2(30) 的 P0（`prefer_fridge` 命中面 93.9%、单项 6.0）：**整包封顶会被它单独顶满 ⇒ 早餐与库存全归零**。
⇒ **"抗挤占"（早餐项封顶）与"抗叠加"（整包封顶）是两种取舍，不是同一个方案。**

##### 通则修正（dev-engine-relax 提出，本报告共同确认）

> **塌缩风险 = f(幅度, 命中组规模)。**
> 幅度 > `random_band` **且命中组小** ⇒ 塌；幅度 > band **但命中组大** ⇒ 不塌。
> ⇒ **`|Δ| ≤ random_band` 是充分不必要的安全条件，真判据是最坏情况下的实测。**

| 案例 | 幅度 | 命中组 | 结果 |
|---|---:|---:|---|
| `meal_slots` `+12/-20` | 32 | 13% | 塌 |
| 早餐 A（叠加 7.5） | 7.5 | **46%（补标后）** | **不塌** |
| inventory 归一化 | 25 | 0.9% | 塌 |

**落地为两层**（静态自检仍能活）：
1. **代理层**：单项二元幅度 `≤ random_band`；不通过 ⇒ 必须实测补标后场景才能放行
2. **真判据层**：在最坏情况下实测 `natural_band_size` + 品类数 + 最大单品类占比
   —— 且门禁须**输出"命中组占比 = 拿到该加分的菜数 / 池子"**，否则第二层不可执行

##### 方法教训（本报告作者）

- **不得从榜首表推断分布**：榜首表是**加分机制的产物，不是池子的抽样**。
  本报告曾据榜首表里的 2 道凉菜推断"48 道标注菜多数不是主/面"，实测是 **87% 主面** —— 结论整条因果链作废。
  ⇒ **给任何人看榜首表，必须同时给池子自然占比。**
- **不得把"转述 + 推断"合成肯定句**：本报告曾对 PRD 说"已拍 C-4.0，可以定稿"，其中"可以定稿"是推断。
  ⇒ 凡涉及未闭合实测，一律标"待实测"，并区分"他人原话"与"本人建议"。

---

#### (33) 🔴 第三种缺数形态：**空池决策根本不落库**（2026-09-23，12y 终裁后的代码核对）

##### 一、三列的缺数形态确实不同（终裁成立）

`backend/app/models/decision.py`：

| 列 | 行 | 定义 | 缺数形态 |
|---|---|---|---|
| `candidate_count` | L134-136 | `nullable=False, server_default=0` | **0**（不是 NULL） |
| `band_size` | L145-147 | `nullable=True`，注释「NULL=当时没测」 | **NULL** |
| `natural_band_size` | L159-161 | `nullable=True`，注释「NULL=当时没测」 | **NULL** |

⇒ J8' 用 `IS NOT NULL`（防**假绿**）与 J6'/J7' 用 `> 0`（防**假红**）都是对的，**两者方向相反但同源**。
⇒ **代码里两句话可直接引用**：
- L143-144「NULL 表示"当时没测"，**不能当成 0 道**；0 是缺陷信号，由缺值伪造的 0 会污染告警」
- L151-154「`band_size` 被 padding 保底，`band_size >= random_min_choices` **恒真**」
  ⇒ **J8' 阈值必须 > `random_min_choices`(3)**，否则 padding 令其恒真。

##### 二、🔴 终裁未覆盖：空池不落库

`decision_service.py` L421-424：

```python
if picked is None:
    logger.error("决策候选用尽: user_id=%s slot=%s", user_id, slot)
    raise RuntimeError("没有可推荐的菜，请先在设置里放宽忌口或时间预算")
```

⇒ **池子彻底空时直接抛错，不进 `_persist()`** ⇒ `decision_log` 里**永远没有"池子=0"的行**。

三条连带结论：

1. **`band_size = 0` 不会出现**（空池不落库）⇒ J8' 的 100% 非空前置判据安全，不必担心"0 被当成抽签带空"。
2. **`candidate_count = 0` 的行只可能是 R-07 上线前的老数据** ⇒ `candidate_count > 0` **实际等价于"排除老数据"**，正确且无需为老数据开口子。
3. 🔴 **"池子彻底枯竭"这个事件，任何基于 `decision_log` 的判据都测不到** —— 只由 R-10 的 `decide_empty_pool` 告警（日志/事件侧）覆盖。
   ⇒ **J6'/J7' 测的是"池子接近枯竭"，不是"枯竭"。** 不写明这句，将来有人会拿 J6'/J7' 全绿去论证"没有空池问题"，而那份数据根本不在 `decision_log` 里。

##### 三、由此补一条护栏（与 §5.6 第五条配套）

> **缺数形态不止 NULL 和 0 两种，还有"事件根本没落库"这第三种。**
> 它最隐蔽 —— **表里干干净净、判据全绿**，因为要测的事件从未进入这张表。
> ⇒ 立任何判据前必须回答：**我要测的那个事件，会不会根本不落在这张表里？**

---

#### (34) 「100% NOT NULL」类判据的窗口陷阱 + 自锚定解法（2026-09-23）

##### 事实：三个字段是**三次迁移**上线的

已 grep `backend/alembic/versions/` 确认：

```
0018_decision_analytics          → candidate_count 等 8 列
0020_decision_band_size          → band_size            (L37-40 op.add_column)
0021_decision_natural_band_size  → natural_band_size
```

⇒ **存量行的空值分层**（"两种空"在同一张表里并存）：

| 行产生时间 | `candidate_count` | `band_size` | `natural_band_size` |
|---|---|---|---|
| < 0018 | **0**（默认值，非 NULL） | NULL | NULL |
| 0018 ~ 0020 | >0 | **NULL** | NULL |
| 0020 ~ 0021 | >0 | 有值 | **NULL** |
| ≥ 0021 | >0 | 有值 | 有值 |

##### 🔴 陷阱

J8' 前置判据「窗口内 `band_size IS NOT NULL` 比例 = 100%，不满足判红、原因写**埋点缺失**」：

⇒ **窗口只要跨过 0020 上线时刻，对 0018~0020 之间的行恒失败。**
⇒ **真实原因是"窗口包含列上线前的行"，不是"埋点缺失"** —— 两者排查方向相反
（一个去查 `_persist()` 为什么没写 = 代码问题；一个去查窗口下界 = 配置问题）。

> **判据本身没错，缺的是窗口下界的定义。** 「100%」这个数的语义来源必须写清"相对哪批数据"。

##### 解法：用同批数据的另一个字段**自锚定**（不依赖时间戳）

`natural_band_size`（0021）晚于 `band_size`（0020）⇒ 凡有 `natural_band_size` 的行必然已有 `band_size`。

```sql
-- 恒为 0；非 0 即为真问题，而非"窗口选错"
SELECT COUNT(*) FROM decision_log
WHERE natural_band_size IS NOT NULL AND band_size IS NULL;
```

优点：**不依赖迁移时间戳、不维护 `since` 常量、可证伪、可复用**（将来加新字段，同样"用最新字段界定窗口"）。

##### 附：支持"`band_size` 保留门禁地位"的一条证据

`decision_service.py` L421-424 **空池直接 `raise`、不进 `_persist()`** ⇒
**`decision_log` 里永远不会有"池子 = 0"的行** ⇒
**`band_size = 0` / `natural_band_size = 0` 一旦出现即为真缺陷信号（真带空了），不是"没测"。**

**但同一事实的另一面（必须一起看）**：
⇒ **不得拿 J6'/J7'/J8' 全绿去论证"没有空池问题"** —— 那份数据根本不在 `decision_log` 里。
（requirement-analyst 已将其写成**禁令**而非说明。理由：**描述挡不住误用**，下一个人看到三张判据全绿，
最自然的推论就是"没空池问题"，而那份数据不在他查的那张表里 —— 形状是"查对了表、问错了问题"。）

---

#### (35) 两项补跑实跑结果（2026-09-23，真库只读）

##### Q1 川菜 2 道的 `is_dish` 归属 —— **地基干净**

```sql
SELECT id, name, is_dish, category FROM recipe WHERE cuisine='川菜';
```

| id | 菜名 | `is_dish` | `category` | `cook_minutes` |
|---:|---|---:|---|---:|
| 79 | 宫保鸡丁（鸡胸肉版） | **1** | 荤菜 | 22 |
| 377 | 麻婆豆腐（豆瓣酱版） | **1** | 素菜 | 12 |

词表放宽到 12 个（粤菜/川菜/江浙/湘菜/鲁菜/轻食/日料/西餐/东南亚/东北菜/川湘/家常）重跑 —— **全库仍只有这 2 道**
（"家常"匹配 0，因库里存的是"家常菜"）。

⇒ **§2.4 "396 道只命中 2 道"成立（342 分母下 2/342 = 0.58%），且两道都在决策池内。**
⇒ **所有"命中率≈0 ⇒ 当下无害"的推论，地基是干净的**（此前 requirement-analyst 担心"2 道里有非菜品 ⇒ 命中数脏"——**不成立**）。

##### 🔴 Q2 `cuisine='早餐'` 25 道的 `category` 分布 —— **数据里没有一致的"早餐"概念**

```sql
SELECT category, COUNT(*) FROM recipe WHERE cuisine='早餐' GROUP BY category;
```

| `category` | 道数 | 占比 | `is_dish` |
|---|---:|---:|---|
| **荤菜** | **17** | **68.0%** | 全部 =1 |
| 素菜 | 4 | 16.0% | 全部 =1 |
| 主食 | 3 | 12.0% | 全部 =1 |
| 面食 | 1 | 4.0% | 全部 =1 |

⇒ **主面（主食+面食）只有 4 道 = 16%，荤菜 17 道 = 68%。**

**与 `meal_slots` 的"早餐"几乎相反：**

| 标注来源 | 道数 | 主面占比 | 荤菜占比 |
|---|---:|---:|---:|
| `category` 枚举 | — | **无"早餐"这个值** | — |
| **`meal_slots` 含 breakfast** | 46 | **87%** | 13% |
| **`cuisine` = '早餐'** | **25** | **16%** | **68%** |

##### 由此修正：早餐病根比"缺一个枚举值"更深一层

> **不是 `category` 枚举里缺"早餐"，是数据里根本没有一致的"早餐"概念** ——
> 三个字段给出三种互不重叠的答案，而现有加分只建在 `meal_slots` 那一个答案上，
> **另外 25 道 `cuisine='早餐'` 的菜（68% 荤菜）完全不在射程内**（拿不到"主/面"加分）。

⇒ **V1.3 根治方向建议改写**：不是"扩 `category` 枚举"，而是**"先统一早餐的标注口径"** ——
不先统一，扩了枚举也不知道该往里填什么。
⇒ **判据必须声明它覆盖的是哪个"早餐"概念**，否则将来用 `cuisine='早餐'` 那 25 道去验判据会得出相反结论，而两边数据都是真的。

##### 本报告作者的一处归因错误（已定位）

曾断言"`meal_slots` 标成 breakfast 的多数不是主/面"，实测是 87% 主面，已被证伪。
**现在定位：该观察为真，但它属于 `cuisine='早餐'`（68% 荤菜），被本报告安到了 `meal_slots` 上。**
⇒ 教训：**看到的现象存在，但没有核它是哪个字段的现象。**

##### 基线快照

```
recipe_total = 396    is_dish=1 → 342
```
⚠️ 与 dev-engine-relax 同轮的 **343** 不同 —— 他那轮多出的 1 道是当天 20:30 新进池的"纯 AI 菜"，
**本轮它已不在 `is_dish=1` 内**。⇒ 再次印证：**覆盖率类指标必须带分母快照**（§5.2(27)），也佐证 **#33 确已发生**。

---

#### (35) 🔴🔴 早餐根因链条补完：**两个"早餐"字段根本在说两批菜**（2026-09-23 实跑）

**分母快照**：`recipe` 396 / `is_dish=1` **342**（本轮实测；dev-engine-relax 那轮量到 343，
中间那道当天新进池的 AI 菜已不在 `is_dish=1` —— **两个数都没错，是基线自己在动**）。

##### 实测

| 集 | 定义 | 道数 | 主面占比 |
|---|---|---:|---:|
| **A** | `cuisine = '早餐'`（**源数据标注**） | **25** | **16%**（主食 3 + 面食 1） |
| **B** | `meal_slots` 含 breakfast（**规则派生**） | **48**（`is_dish=1` 是 46） | **87.5%**（面食 22 + 主食 20） |
| **C** | **两者交集** | **8** | — |
| D | 只在 A | 17 | — |
| E | 只在 B | 40 | — |

**category 分布完全相反**：

| `cuisine='早餐'`（25） | 道数 | `meal_slots` 含 breakfast（48） | 道数 |
|---|---:|---|---:|
| **荤菜** | **17** | 面食 | 22 |
| 素菜 | 4 | 主食 | 20 |
| 主食 | 3 | 荤菜 | 6 |
| 面食 | 1 | | |

⇒ **Jaccard = 8 / 65 = 12.3%。88% 不重叠；一个 68% 荤菜，一个 87.5% 主面。**

##### 那 8 道交集 = "两边都认"的真早餐食品

```
微波炉荷包蛋(荤菜) / 手抓饼(主食) / 桂圆红枣粥(主食) / 燕麦鸡蛋饼(主食)
牛奶燕麦(荤菜) / 空气炸锅面包片(面食) / 金枪鱼酱三明治(荤菜) / 鸡蛋三明治(荤菜)
```

**其中 4 道被 `category` 标成了「荤菜」** —— 牛奶燕麦、鸡蛋三明治、金枪鱼酱三明治、微波炉荷包蛋。

##### 完整根因链条

> **`category` 枚举没有「早餐」
> ⇒ 真正的早餐食品（牛奶燕麦/鸡蛋三明治/桂圆红枣粥）被塞进「荤菜」
> ⇒ 基于 `category` 的派生规则（`meal_slots` 的 breakfast、早餐硬编码 `+3.0/+1.5`）抓不到它们
> ⇒ 只能拿「主食/面食」当代理
> ⇒ 而代理指向的菜与真早餐食品 88% 不重叠
> ⇒ 补偿方向反了。**

一次性解释了三件事：**早餐档品类恒 2 / 主面 100%**；**`cuisine='早餐'` 68% 荤菜**；**以及那个反直觉的 15.0%**。

> **也解释了本报告作者此前的错误形状**：作者看到榜首表里的凉拌豆腐/凉拌金针菇（属 **B 集**），
> 却当成 **A 集**的现象 —— **两批菜都叫"早餐"，谁都会以为是一批。**

##### 对 V1.3 根治的估工结论

**交集只有 8 道 ⇒ 不是"改个字段就行"，是"得重新标注"。且两项必须一起做，只做一项没用：**

1. **以 `cuisine='早餐'`（源标注）为真值集重建 breakfast 信号** —— 需补标 **17 道**（D 集）
2. **同时修 `category` 的错误标注** —— 至少 4 道早餐食品被标成"荤菜"。
   **光加 `breakfast` 字段不改 `category`，它们在 `category` 轴上仍是荤菜，
   所有基于 `category` 的逻辑（同品类打散、早餐硬编码补偿）照旧抓不到。**

⇒ **V1.3 估工按"重建 + 修错"两项算，不是"统一口径"一项。**

##### 附：两个分母差异均已定位（非矛盾）

| 数 | 全库 | `is_dish=1` | 说明 |
|---|---:|---:|---|
| `meal_slots` 含 breakfast | **48** | **46** | dev-engine-relax 报 46 正确（按 `is_dish=1`） |
| `is_dish=1` | — | **342** | 他那轮 343，中间新增的 AI 菜已不在 `is_dish=1` |

⇒ **凡引用这类数，一律带 `is_dish` 标注 + 分母快照。**

---

#### (36) 早餐口径选型：**本版以 `meal_slots` 为准**（数据侧排序，非产品裁决）+ 根治最小路径（2026-09-23）

##### 三个候选口径的池子大小（分母 `is_dish=1` = 342）

| 口径 | 道数 | 占池 | 构成 |
|---|---:|---:|---|
| A `cuisine='早餐'` | 25 | 7.3% | 燕麦 / 三明治 / 荷包蛋（**真早餐食品**，但 68% 被标成荤菜） |
| **B `meal_slots` 含 breakfast** | **46** | 13.5% | 面食 22 / 主食 20 / 荤菜 6 |
| **并集** | **63** | 18.4% | — |

##### 本版选 B 的三条数据理由

1. **池子**：以 A 为准仅 25 道，叠 `cook_cap` + 忌口 + 近 7 天不重复后极可能跌破 `POOL_MIN=8` ⇒ **直接触发放宽阶梯**。
   旁证：早餐档 ∩ ≤15min 实测 **7 道**，已在 `POOL_MIN` 之下。
2. **打散冲突**：A 集 68% 是 `category`=荤菜 ⇒ 早餐连出会被 `category_penalty_step=25` 整类压下去 ⇒ 反复降权。
3. **前置成本**：A 集里 17 道"荤菜"是**被误标的**（牛奶燕麦/鸡蛋三明治/金枪鱼三明治/微波炉荷包蛋）⇒
   **选 A = 必须先修 `category`**；选 B 可在现有数据上直接跑。

> ⇒ **A 是更贴近用户心智的早餐，但本版用不起。这是数据给出的排序，不是产品裁决。**

##### 🔴 根治最小路径：**给 17 道补 `meal_slots` 标注**（比"扩 `category` 枚举"便宜一个量级）

```
A 25 + B 46 − 交集 8 = 并集 63 道
其中「只在 A」= 17 道 —— 缺 meal_slots 标注
```

- 收益：早餐档池子 **46 → 63（+37%）**，且把真正的早餐食品纳入
- 成本：**只加标注，不动 `category`、不动枚举、不重建信号**

**但两件事必须都做，不能只做一件**：那 17 道里至少 4 道 `category` 是错的（早餐食品标成"荤菜"）。
只补 `meal_slots` 不修 `category` ⇒ 它们在同品类打散里仍是荤菜 ⇒ 上面第 2 条的问题会带进并集。
⇒ **① 补 17 道标注（便宜，先做）② 修 `category` 误标（可与 V1.3 其它标注工作合并）**，异步但不省略。

##### 未解决（需产品/用研裁定）

"早餐 = 主食面食，还是早上吃的菜"是**产品心智问题**，非数据问题。
建议查 `user-research-decision-mind.md` 的【语料】（`data/utterance_corpus.json` 106 条中文口语）是否有早餐相关说法 —— **那是一手证据**。
本报告可提供对照（A → 燕麦/三明治/荷包蛋；B → 面/饼/饭），让产品**对着真实菜单选，而不是对着字段名选**。

##### 待补（shell 不可用未跑成）

**早餐档历史实际出过什么 `category`**（`decision_log` 按 `meal_slot` 切片）—— 真实用户所见，比池子构成更直接。
SQL 已写好待跑：**`/tmp/mp_breakfast_actual.sql`**（含 4 段：早餐档行数分母 / category 分布 / 其它餐次对照 / 主面占比，并附三条读数纪律）。

---

#### (37) 🔴🔴 `meal_slots=breakfast` 循环信号核查：**合取证伪，拆开后「category 那一笔」坐实**（2026-09-23 实跑，真库 342，只读）

team-lead 怀疑：`meal_slots` 是 0016 之后用规则回填的，若 46 道里
`category ∈ (主食,面食) 且 cook_minutes <= 15` 占比接近 100%，则 `meal_slots=breakfast`
就是"主面 + 快手"启发式本身 ⇒ **A 方案那笔 `BREAKFAST_CATEGORY_BONUS` 是把同一条启发式加了两次**。

##### 实跑结果：**合取只有 15.2%，字面假设证伪；但拆开看一半坐实、一半反向**

| 口径（分母 = 标了 breakfast 的 **46** 道） | 道数 | 占比 | 全库 342 自然占比 | 判定 |
|---|---:|---:|---:|---|
| `category ∈ (主食,面食)` | **40** | **87.0%** | 20.5% | 🔴 **富集 4.2 倍 ⇒ 重复计价**（⚠️ 性质经 §(40) 修正：**不是**循环自证，理由见该节） |
| `cook_minutes <= 15` | **7** | **15.2%** | 29.5% | 🟢 **低于全库 ⇒ 反向，不是循环** |
| **两者同时满足（team-lead 的合取）** | **7** | **15.2%** | 5.3% | ❌ **远不是 100% ⇒ 字面假设证伪** |

`cook_minutes` 分档对照（46 道 vs 全库 342）：

| 档 | 46 道 | 全库 342 |
|---|---:|---:|
| ≤10 | 8.7% | 5.8% |
| 11–15 | 6.5% | 23.7% |
| **21–25** | **43.5%** | 42.4% |
| 31–60 | 17.4% | 19.9% |

⇒ **被标成早餐的菜反而更慢**（11–15 分钟档 6.5% < 全库 23.7%）。
⇒ `meal_slots=breakfast` 的回填规则里**只有 category 那一半生效**，时间那一半根本没参与。

##### ⇒ 这句必须写准（否则会被当成"A 的两笔都循环"）

> **循环的是 `BREAKFAST_CATEGORY_BONUS`（3.0），不是 `BREAKFAST_QUICK_BONUS`（1.5）。**
> 前者与 `meal_slots=breakfast` 重合 87%；后者重合 15.2%，**且方向相反** —— 它是唯一的独立维度。

##### 副作用（顺手确认，重要）

`cook_minutes` 全库只有 **13 个离散取值**（8/10/12/15/18/20/22/25/28/30/40/45/60），
其中 22 分钟 108 道（31.6%）、25 分钟 37 道 ⇒ **这是规则生成的桶，不是真实出餐时间**。
`<=15` 这条线切的是"哪些菜被赋了 10/12/15 这几个桶"，不是"哪些菜真的快手"。
⇒ **`BREAKFAST_QUICK_BONUS` 的命中面（98 道）本身带系统性偏差**，根治时不能只改标注口径，要连 `cook_minutes` 一起看。

---

#### (38) 🔴🔴 A / A+ 两个变体实测：**A 的数不稳定，56.5% 的抽签带只靠 0.5 分边界侥幸撑着**（2026-09-23 实跑，真库 342，只读、零写入、不改源码）

按 team-lead 定的口径实跑：**A = 叠加不封顶、不进软偏好包、不受 `SOFT_PREFERENCE_CAP` 约束**。
分母快照 `load_candidates = 342`、`random_band = 5.0`、`SOFT_PREFERENCE_CAP = 4.0`（现行）。

##### 命中面（先给分母，否则百分比不可读）

| 项 | 道数 |
|---|---:|
| 显式标 `breakfast` | 46 |
| 无 `meal_slots` 标注 | 267 |
| **可吃补偿（无标注 或 标了 breakfast）** | **313** |
| 其中 主面 | 67 |
| 其中 快手 ≤15min | 98 |
| 其中 两者全中 | 15 |

> 注意：**"标了 breakfast 的 46 道里两者全中"只有 7 道**（§37），
> "可吃补偿的 313 道里两者全中"是 15 道 —— 两个 7/15 别混用，它们的分母不同。

##### 两个要报的数（用户第一道口径 = 带内均匀抽，N=500，seed=20260923）

| 变体 | 真带 | band | 品类 | **带内主面%** | **MC 第一道主面%** | 倍数 | 最大品类 |
|---|---:|---:|---:|---:|---:|---:|---|
| **A 叠加不封顶**（slot 3.0 + cat 3.0 + quick 1.5） | **23** | 23 | 5 | **43.5%** | **42.4%** | **2.12x** | 素菜 26.1% |
| **A+ 叠加 + 封顶 4.0**（= 原方案 C） | **64** | 64 | 6 | **25.0%** | **23.2%** | **1.22x** | 荤菜 57.8% |
| （参照）V0 现行 `min(max(slot,comp),4.0)` | 64 | 64 | 6 | 25.0% | 22.8% | 1.22x | 荤菜 57.8% |
| （诊断）A− 去掉循环的 cat 那笔：`slot + quick` | 59 | 59 | 6 | 18.6% | 19.0% | 0.91x | 荤菜 62.7% |
| （诊断）A= 去掉 quick 那笔：`slot + cat` | **10** | 10 | **2** | **100%** | 100% | 4.89x | 面食 50% |
| （诊断）C0 只靠标注 `slot` | 59 | 59 | 6 | 18.6% | 19.2% | 0.91x | 荤菜 62.7% |
| （诊断）N 完全不给 | 116 | 116 | 7 | 14.7% | 12.8% | 0.72x | 荤菜 63.8% |

##### 与 dev-engine-relax 那轮 40.4% 的差异（不要当同一个数用）

他那轮是 **343 道**、且当时 `SOFT_PREFERENCE_CAP = 5.0`、`max()` 与封顶的接线状态与现在不同。
本轮严格按 team-lead 的 A 定义（**叠加不封顶、不进包、不受 CAP 约束**）在 **342 道 / CAP=4.0** 下重跑 = **42.4%**。
⇒ 两个数差异 2pp，**同源不同口径**。引用时必须带"342 还是 343、CAP 是 4.0 还是 5.0"。

##### 口径自检（未省）

- `_inventory_score(空冰箱, intent=None)` 取值集合 = `{0.0}` ⇒ 软偏好包在本次场景下**只有**餐次 + 早餐两笔
- 逐道复算 `base + min(max(slot,comp), CAP)` 与 `_score()` 原分**完全相等** ⇒ base 还原成立（不是近似）

> **A+ 与 V0 现行数值几乎相同**（64/6/25.0% vs 23.2%）：差别只在
> `comp=1.5` 那一档（V0 给 3.0、A+ 给 4.0），影响 < 1pp。
> ⇒ **若 team-lead 的 A+ 指的是"叠加 + 封顶"，那它与 dev-engine-relax 已落地的现行版等效**；
> team-lead 要改的其实只有一处：**`max()` 改成叠加**（解决"标得越全分越低"的反向激励），封顶保持不动。

##### 🔴 但 A 的 43.5% 不能按字面理解 —— 机制与 team-lead 猜的不同

不是"同一启发式加了两次"（那会让带里**全是**主面），而是：

```
best = 21.00（主面 + 标了 breakfast）  →  cutoff = 16.00
  主面菜（67 道里 base 够高的 10 道）被 cat 3.0 抬到带顶，独占
  base = 15.00 的快手非主面菜 + quick 1.5 = 16.50 ≥ 16.00  ⇒ 被"救回"带里 13 道
```

⇒ **43.5% = 10 道主面 /（10 道主面 + 13 道被救回的快手菜）**。
**分子来自循环加成，分母来自边界侥幸 —— 两个数都不是设计出来的。**

##### 🔴 边界体检（决定性）

`best = 21.00`、`cutoff = 16.00`、真带 23 道，其中 **13 道（56.5%）距 cutoff 只有 +0.50 分**：

```
+0.50 凉拌豆腐(凉菜) / 凉拌金针菇(凉菜) / 利提巧卡(素菜) / 印度土豆花菜(素菜)
+0.50 干煸仔鸡(荤菜) / 炒凉粉(素菜) / 炒馍(荤菜) / 蚂蚁上树(素菜)
+0.50 辣椒炒肉(荤菜) / 酸辣土豆丝(素菜) / 酸辣蕨根粉(素菜) / 香干芹菜炒肉(荤菜) / 香煎翘嘴鱼(荤菜)
```

⇒ **这 13 道的进带与否只取决于 0.5 分。base 分布一动，它们全部出局，A 立刻退化成 A=（带 10 道、品类 2、主面 100%）。**

##### 🔴 稳定性检验（换 profile / 换历史，A 剧烈跳动，A+ 不跳）

| 场景 | A 真带 | A 主面% | A 品类 | A+ 真带 | A+ 主面% | A+ 品类 |
|---|---:|---:|---:|---:|---:|---:|
| P0 默认（spice=0, 空历史） | 23 | 43.5% | 5 | 64 | 25.0% | 6 |
| P1 spice=1 | **15** | **93.3%** | **3** | 102 | 63.7% | 6 |
| P2 spice=2 | 23 | 43.5% | 5 | 64 | 25.0% | 6 |
| P3 昨天荤菜×1 | 18 | 55.6% | 4 | 27 | 59.3% | 5 |
| P4 昨天荤菜×2 | 18 | 55.6% | 4 | 27 | 59.3% | 5 |
| **P5 昨天主食×2 + spice=1** | **7** | **85.7%** | **2** | 62 | 40.3% | 5 |

- **A：真带 7 ~ 23、主面 43.5% ~ 93.3%、品类 2 ~ 5** ⇒ **没有稳定值**
- **A+：真带 27 ~ 102、品类恒 ≥ 5** ⇒ 稳定
- **P5 下 A 的真带 = 7 < `POOL_MIN`(8)** ⇒ 早餐实际选择空间跌破放宽触发线的量级

> 根因是 R-14 已指出的那条：**默认场景下 `_score()` 只有 `score_spice` 一个维度在工作**。
> base 分高度并列 ⇒ 任何 ≥3.0 的加成都会**重新定义整条带**，而不是"影响排序"。

##### ⇒ 数据侧的排序建议

1. **A 与 A+ 的差别不是"早餐味浓淡"，是"稳定 vs 不稳定"。** A 换一个用户画像就换一个结果。
2. **A 不可上**：它的 43.5% 里有 56.5% 的带成员只差 0.5 分，且 P5 下真带 7 道 < `POOL_MIN`。
3. **A+（叠加 + 封顶 4.0）可用**，且与现行仅差 `max()` → 叠加这一处改动。
4. **A−（去循环）不可上**：主面 18.6% < 池子自然 20.5%（0.91x），早餐味反向消失 ——
   **说明"去掉循环"不能靠删 cat 那笔实现，只能靠 §(36) 的统一标注口径根治。**
5. **V1.3 根治方向不变**：统一早餐标注口径（12z-c 两项：补 17 道 `meal_slots` + 修 `category` 误标），
   **并连 `cook_minutes` 的离散桶一起重新定标**。

---

#### (39) 343 ↔ 342 那 1 道：**是被 DELETE，不是改 `is_dish`**（2026-09-23 实跑）

| 查询 | 结果 |
|---|---|
| `SELECT ... FROM recipe WHERE id = 397` | **空** |
| `COUNT(*) / MIN(id) / MAX(id)` | **396 / 1 / 396**（id 完全连续，无缺口） |
| **`AUTO_INCREMENT`** | **398** |
| 2026-09-23 新建的行 | **0 条** |
| 最晚 `updated_at` | 2026-09-23 18:21:53 |
| `enrich_source` 分布 | `rule` 389（含 is_dish=0 的 54）+ `NULL` 7，**无任何 ai/llm/generation 来源** |

⇒ **结论：`id=397「纯 AI 菜」被删除了，不是 `is_dish` 被翻转。**
（若只是翻转，`id=397` 仍应在表里且 `is_dish=0`；它被分配过 id 是因为 `AUTO_INCREMENT` 已推进到 398。）
⇒ **`enrich_source` 随行消失，无法追溯** —— 想查"它是怎么进来的"只能翻当时会话/日志。
⇒ **342 口径当前自洽**（396 行 / is_dish=1 → 342），dev-engine-relax 那轮的 343 是**含了一道临时行**。

##### ⚠️ 顺带一条告警（与 git 零 commit 不矛盾，但必须记一笔）

`AUTO_INCREMENT = 398 > MAX(id) = 396` ⇒ **09-23 20:30 前后库确实被写入过一次并回删**。
git 零 commit 只说明代码没动；**数据库不是只读的**。
建议确认写入方（疑似 dev-engine-relax 的真库验证，或 fix-non-dish 的 #33「富集落库时对新菜做 `is_dish` 判定」观测任务），
并确认这次删除是**回滚**而不是误删 —— 两者在库里留下的痕迹一模一样，只能靠当事人确认。

##### 覆盖率快照纪律（再次印证）

同一份数据在一小时内出现过 **342 → 343 → 342**。
⇒ **所有覆盖率类数字必须带当天 `COUNT(*) WHERE is_dish=1` 快照**，
否则三个月后没人能分辨"7.3%"用的是哪个分母。本节所有百分比分母均为 **342**（2026-09-23 21:30 复核）。

---

#### (40) 🔴🔴 撤回 §(37) 的「循环坐实」：`meal_slots=breakfast` 与「主面 + 快手」**构造上无关**（2026-09-23，读代码 + 实跑）

> **这是我自己上一条结论的撤回。** §(37) 我写了「87% 重合 ⇒ `BREAKFAST_CATEGORY_BONUS` 循环坐实」。
> **这条错了。** 我当时只看了相关性，没去看**生成规则** —— 相关性 87% 既可能是"循环"，
> 也可能是"两路独立规则指向同一批真菜"，**不查生成规则就分不开这两种**。

##### 三条证据（按强度排序，全部第一手）

**证据 1（最强 —— 读代码）**：`backend/app/services/dish_rules.py` L238-253

```python
def guess_meal_slots(recipe) -> Optional[List[str]]:
    name = recipe.name or ""
    slots: List[str] = []
    if any(w in name for w in BREAKFAST_WORDS) and "炒" not in name:
        slots.append("breakfast")
    ...
# BREAKFAST_WORDS = ("粥", "馒头", "豆浆", "油条", "煎蛋", "三明治", "燕麦")   # L182
```

⇒ breakfast ⟺ **菜名里含粥/馒头/豆浆/油条/煎蛋/三明治/燕麦，且菜名不含"炒"**。
函数体**不读 `category`、不读 `cook_minutes`** ⇒ **构造上不可能由「主面 + 快手」生成**。

**证据 2（集合论反证 —— 实跑，真库 342）**：

| 集合 | 道数 |
|---|---:|
| 全库 `category ∈ (主食,面食) AND cook_minutes <= 15` | **18** |
| 全库 `meal_slots` 含 breakfast（is_dish=1） | **46** |
| 两者交集 | **7** |

⇒ 若标注由该 AND 启发式生成，46 必须是 18 的子集。**46 > 18 ⇒ 不可能。**
这条与相关性无关，是纯集合大小的反证。

**证据 3（写入方确认 —— 实跑）**：`meal_slots` 全库只有两个写入点 ——
`scripts/backfill_dish_scene_fields.py`（→ `guess_meal_slots`）与
`recipe_enrich_service.py` L90-93（同样 → `guess_meal_slots`）。
LLM 那条（L208 `_clean_str_list(payload.get("meal_slots"))`）**从未执行过**：
`enrich_source` 分布 = `rule` 389 + `NULL` 7，**无 llm / ai / generation 任何一行**
（且 `.env` 中 GLM4/QWEN/DEEPSEEK 三个 key 全空、`APP__LLM__DEMO=true`）。
⇒ **库里的 `meal_slots` 100% 来自上面那条菜名关键词规则。**

##### ⇒ 修正后的结论

| 说法 | 判定 |
|---|---|
| team-lead 的合取假设（46 道里 主面 ∧ ≤15 接近 100%） | ❌ **证伪**：**15.2%（7/46）**，且被证据 2 集合论反证 |
| `BREAKFAST_CATEGORY_BONUS`（3.0）是"把同一条启发式加两次" | ❌ **否证**：slot 来自**菜名**，category 来自**品类**，是两路独立规则 |
| 87% 重合怎么解释 | 🟢 **两路独立规则指向同一批真菜**（粥/馒头/油条/面条本来就是主食）⇒ 是**印证**，不是**翻倍** |
| **A 的 43.5% 能不能按字面理解** | ✅ **能**（但必须同时读 §(38) 的稳定性警告 —— 能理解 ≠ 能上线） |

##### 但是：**真正的同源在别处 —— `cook_minutes` 是 `category` 的确定性函数**

`dish_rules.guess_minutes()` L202-213 的三级回退：
① 菜名里写了「N 分钟」→ 用它；
② 菜名含做法词 → `METHOD_MINUTES`（拌/拍/腌 10，炒/爆/熘/煸/煎 15，煮/汆/涮 20，蒸 25，烤/焗/炸 40，煲/炖/煨/卤/焖 60）；
③ **否则 `CATEGORY_MINUTES[category]`（凉菜 10 / 素菜 12 / 主食 25 / 面食 20 / 荤菜 22 / 小吃 25 / 汤羹 40）**。

**实跑印证**：全库 342 道的 `cook_minutes` 只有 **13 个离散取值**
（8/10/12/15/18/20/22/25/28/30/40/45/60），22 分钟 108 道、25 分钟 37 道 ——
**全是上面两张表的枚举值，没有一个是真实测量值。**

⇒ 三点后果（比"循环"更值得修）：

1. **`cook_minutes <= 15` 与 `category ∈ (主食,面食)` 在规则层面就互斥**：
   主面只能拿到 20/25 分钟，**> 15** ⇒ 主面菜**拿不到** `BREAKFAST_QUICK_BONUS`
   （除非名字里带拌/炒/拍/腌或显式写了分钟）。全库同时满足的只有 18 道。
2. **`BREAKFAST_QUICK_BONUS`（1.5）是早餐方案里的反向项**：它扶持的是凉菜/素菜/炒菜，
   **稀释**主面。这正是 §(38) 里 A−（只留 slot + quick）实测 **18.6% < 自然 20.5%（0.91x 反向）** 的根因。
3. **两条规则公开打架**：`guess_meal_slots` 明确**排除含"炒"的菜**标 breakfast；
   `guess_minutes` 却给"炒" = 15 ⇒ **炒菜拿到早餐快手加分，而它恰恰是早餐标注规则排除的那一批**。

##### ⇒ 修法建议（替代 §(37) 原来的提法）

- 「统一早餐标注口径」的方向仍对，但**真正要先统一的是 `cook_minutes` 的生成口径**：
  摘掉 `CATEGORY_MINUTES` 这条回退（判不出就留空，别用品类**编**一个时间），V1.3 换真实值。
- 在那之前，**`BREAKFAST_QUICK_BONUS` 的 1.5 不能按"快手"理解** ——
  它实际是"菜名里有拌/炒/煮等做法词"的代理，与"早餐要不要快"是两件事。
- **本版不动**：改 `guess_minutes` 会同时改动「交给外卖吧」文案与雨天门槛的触发率
  （§5.2(32) 已证明二者共用 `_needed_ingredients`，动一个必动另一个）⇒ **排 V1.3**。

---

#### (41) 🔴 B 的 P0–P5 补跑：**B 自己也被否决**（2026-09-23 实跑，真库 342，只读）

触发：user-researcher 指出我此前只给了 A 的敏感性数据，**「我们正准备选的那个（B），
恰恰是没被压力测试过的那个」** —— 单边敏感性测试。这条质疑成立，本节补跑。

| 场景 | B1（池=46，无早餐加分）真带/品类/主面% | B2（池=46，现行 A 加分）真带/品类/主面% |
|---|---|---|
| P0 默认 | 10 / 3 / 80.0% | 8 / 2 / 100.0% |
| P1 spice=1 | 44 / 3 / 88.6% | 11 / 3 / 90.9% |
| P2 spice=2 | 10 / 3 / 80.0% | 8 / 2 / 100.0% |
| P3 昨天荤菜×1 | 8 / 2 / 100.0% | 8 / 2 / 100.0% |
| P4 昨天荤菜×2 | 8 / 2 / 100.0% | 8 / 2 / 100.0% |
| **P5 昨天主食×2 + spice=1** | 25 / 2 / 80.0% | **7 / 2 / 85.7%** ← **< `POOL_MIN`(8)** |

⇒ **B2 在 P5 下真带 7 < `POOL_MIN`，与 A 是同一个毛病，不是 A 独有的。**
⇒ **B 的品类数全程只有 2 ~ 3**（A 是 2~5、A+ 是 5~6）⇒ **多样性这一维 B 比 A 更差**。
⇒ B1 在 P1 下真带 44（46 道池子里 44 道进带）不是"健康"，是**打分失去区分度的塌平**。

##### ⇒ 结论（回应闸门）

按 user-researcher 与要求分析师定的闸门 —— **池子大小只能否决、不能选中**：

> **B 的 46 道只让它"存活"，补跑之后它自己也在 P5 被否决。**
> **"选 B"不能由"A 不稳定"推出** —— 这是单边敏感性测试，两边都跑完的结论是**两个都踩线**，
> 而不是"B 顶上"。

---

#### (42) 🔴 「场景层封顶」档位扫描：**4.0 / 5.5 / 7.5(现行 A) 三档，非单调**（2026-09-23 实跑）

A 与 A+ 不是二选一，中间还有档。真库 342，同一组 P0/P1/P3/P5：

| 场景层封顶 | P0 真带/品类/主面% | P1 | P3 | P5 | 最差真带 | 最差品类 | 最差倍数 |
|---|---|---|---|---|---:|---:|---:|
| **4.0（= A+）** | 64/6/25.0% (1.22x) | 102/6/63.7% | 27/5/59.3% | 62/5/40.3% | **27** | **5** | 1.22x |
| 4.5 | 57/6/19.3% (**0.94x 反向**) | 84/6/60.7% | 22/5/50.0% | 57/5/42.1% | 22 | 5 | **0.94x** |
| 5.0 | 同 4.5 | 同 4.5 | 同 4.5 | 同 4.5 | 22 | 5 | 0.94x |
| **5.5** | 23/5/43.5% (2.12x) | 56/3/89.3% | 18/4/55.6% | **30/2/80.0%** | 18 | 2 | 2.12x |
| 6.0 | 23/5/43.5% (2.12x) | 49/3/87.8% | 18/4/55.6% | 26/2/76.9% | 18 | 2 | 2.12x |
| **7.5（= 现行 A，不封顶）** | 23/5/43.5% (2.12x) | 15/3/93.3% | 18/4/55.6% | **7/2/85.7%** | **7** ❌ | 2 | 2.12x |

##### 三条读法

1. **非单调，且 4.5/5.0 是坑**：封顶压到 4.5/5.0 时，被削掉的正是"早餐标注菜相对普通主面菜的优势"
   （slot 3.0 + cat 3.0 = 6.0 → 封到 4.5，而普通主面只拿 3.0 不受影响）⇒ **主面掉到 0.94x，反向**。
   这推翻了 §5.2(32) 记的"封顶越低主面越高" —— 那条是在**另一组常量**下测的，不可跨配置引用。
2. **5.5 严格优于现行 7.5**：P0/P3 与 A **完全相同**（23/5/43.5%、18/4/55.6%，效果一分别丢），
   但 P1 真带 15 → 56、**P5 真带 7 → 30（越过 `POOL_MIN`）** ⇒ 唯一踩线的场景被修好。
   代价：P5/P1 品类降到 2/3（与 A 的 2/3 相同，**不更差**）。
3. **4.0 是唯一全程品类 ≥ 5 的档**，但 P0 效果只有 1.22x。

##### ⇒ 给 team-lead 的三个数（拍板用）

| 选项 | P0 效果 | 全场景真带 ≥ 8 | 全场景品类 ≥ 4 | 一句话 |
|---|---|---|---|---|
| **A（现行 7.5，不封顶）** | **2.12x** | ❌ P5 = 7 | ❌ P5 = 2 | 效果最强，**P5 踩线** |
| **5.5** | **2.12x** | ✅ 最差 18 | ❌ P5 = 2 | 效果与 A 相同，**把 P5 修好** |
| **A+（4.0）** | 1.22x | ✅ 最差 27 | ✅ 最差 5 | 最稳，**效果只剩一半** |

> **没有一档三条件全绿。** 要"早餐味"选 5.5，要"多样性/稳"选 4.0，维持现状（7.5）在 P5 是明确缺陷。
> 我不替产品拍板 —— 这三个数是同一脚本同一 seed（20260923）跑出来的，可直接比。

##### ⚠️ 方法论备注（这次差点又栽）

上一版脚本我用 `base = s0 - min(max(slot, comp), CAP)` **反推**"没有早餐分"的基准分，
但现行代码**已经是 A（叠加不封顶）**，根本没加 `min(max(...), CAP)` 这一笔 ⇒
对 slot=3.0 / comp=4.5 的菜凭空多算了 3.5 分，把 A 算成"真带 9 / 主面 100%"的**假塌缩**。
v2 改成**把三个常量临时置 0 后重跑 `_score`**，并加自检：
`max|base + 场景层 − 现行 _score| = 0.000000` ⇒ 口径对齐后才敢报数。
**教训：不要反推 base，要置零重跑 —— 反推要求你比代码更懂代码。**

---

#### (43) 顺手确认：`is_dish=0` 里的 2 道早餐菜**剔对了**，早餐地基干净（2026-09-23 实跑）

| id | 菜名 | category | cuisine | cook_minutes | meal_slots | is_dish |
|---|---|---|---|---:|---|---:|
| 121 | 无厨师机蜂蜜面包 | 面食 | 甜品 | 20 | ["breakfast","lunch"] | 0 |
| 200 | 玛格丽特饼干 | 主食 | 甜品 | 25 | ["breakfast","lunch"] | 0 |

⇒ 全库标 breakfast 的共 **48** 道，其中 **2 道 `is_dish=0`**、**46 道 `is_dish=1`**（复核 §(35) 的 46）。
⇒ 这 2 道 `cuisine='甜品'`、**确实**该被剔 ⇒ **`is_dish` 过滤没有误伤早餐，反而精确剔掉了早餐里的甜品**。

---

#### (40) §(37) 的性质修正：**87% 是「重复计价」，不是「循环自证」**（2026-09-23，代码层第一手证据 + shell 失效记录）

##### 一、代码层证据：`meal_slots=breakfast` 的回填规则**根本不读 `category` / `cook_minutes`**

`backend/app/services/dish_rules.py` L238-253：

```python
BREAKFAST_WORDS = ("粥", "馒头", "豆浆", "油条", "煎蛋", "三明治", "燕麦")   # L182

def guess_meal_slots(recipe):
    name = recipe.name or ""
    if any(w in name for w in BREAKFAST_WORDS) and "炒" not in name:
        slots.append("breakfast")
    ...
```

- 判据是**菜名关键词**，与 `category` 字段、与 `cook_minutes` **完全无关**；
- 全仓只有**两个写入方**，且都调同一个 `guess_meal_slots()`：
  `scripts/backfill_dish_scene_fields.py` L69-70、`recipe_enrich_service.py` L90-93（都只在字段为空时填）；
- LLM 那条旁路（`recipe_enrich_service.py` L208-210，从 payload 写 `meal_slots`）**从未真正跑过**：
  `.env` 里 `GLM4_API_KEY` / `QWEN_API_KEY` / `DEEPSEEK_API_KEY` **全空**、`APP__LLM__DEMO=true`；
  实跑 `enrich_source` 分布 = `rule` 389 + `NULL` 7，**无任何 ai/llm/generation 来源**（§(39)）。

> ⇒ 那 46 道被标成 breakfast，是因为**名字里带粥/馒头/豆浆/油条/煎蛋/三明治/燕麦**。
> ⇒ 它们同时 87% 是 `category ∈ (主食,面食)`，是因为**粥/馒头/油条本来就是主食**。

##### 二、因此 §(37) 的定性要改一个字（结论方向不变，但理由不同，且理由决定修法）

| | 循环自证（原措辞） | **重复计价（修正后）** |
|---|---|---|
| 两个信号的关系 | 一个是由另一个算出来的 | **两个独立推导（菜名 vs category 字段），碰巧指向同一批真菜** |
| 一致性高说明什么 | 说明其中一个是废信号 | 说明**两路都对**，正常且应该 |
| 能不能叠 3.0 + 3.0 | 不能（等于自己加自己） | **不能**（等于把同一条事实记两遍），但**错的理由不同** |
| 修法 | 删掉其中一个 | **不是删，是承认它不提供新信息、只提供杠杆** ⇒ 靠封顶/幅度管理，不靠删除 |

⇒ **对打分的影响与 team-lead 担心的一致，但对"该怎么修"的指引不同**：
   - `BREAKFAST_CATEGORY_BONUS`(3.0) 与标注重合 87% ⇒ **这 3.0 分不携带新信息，只是把同一条事实再计一遍**；
   - `BREAKFAST_QUICK_BONUS`(1.5) 重合 15.2% 且方向相反 ⇒ **这才是唯一真正独立的维度**；
   - 所以 §(38) 的 `A−`（删掉 cat 那笔）实测主面 **18.6% < 池子自然 20.5%（0.91x）** ——
     **"去掉重复计价"不能靠删 cat 实现**，删了早餐味反向消失。

##### 三、顺带坐实另一处**真同源**：`cook_minutes` 的兜底是 `category` 的确定性函数

`dish_rules.py` L202-213 `guess_minutes()` 的兜底：`CATEGORY_MINUTES[category]`（L29-32）
—— **凉菜 10 / 素菜 12 / 主食 25 / 面食 20 / 荤菜 22 / 小吃 25 / 汤羹 40**。

⇒ 对"名字里既没写分钟数、也没写做法词"的菜，**`cook_minutes` 就是 `category` 的查表结果，两者同源**。
⇒ 但方向是**负相关**：主食 25、面食 20 **都 > 15** ⇒ **主面菜拿不到 `BREAKFAST_QUICK_BONUS`**。

这一条同时解释了两件此前只能"实测看到、说不清为什么"的事：
1. §(37) 的"**被标成早餐的菜反而更慢**"（11–15 分钟档 6.5% < 全库 23.7%）：
   粥/馒头走 `CATEGORY_MINUTES[主食] = 25`，被规则赋成 25 分钟，不是它们真的慢；
2. §(38) 的 **A=（slot+cat）塌到带 10 道 / 品类 2 / 主面 100%**，而 **A 靠 quick 救回 13 道非主面菜**：
   cat 那一笔只打主面（独占），quick 那一笔只打非主面的快手菜（稀释）—— **两个命中组几乎不重叠**。

⇒ **A 的 43.5% 是"cat 的塌缩"被"quick 的稀释"偶然抵消**，两个毛病互相掩盖。
  掩盖失效时（P5：昨天主食×2 + spice=1）真带 **7 道 < `POOL_MIN` 8**。

##### 四、V1.3 根治因此要改成三件事（原为两件）

1. 统一早餐标注口径（补 17 道 `meal_slots` + 修 `category` 误标）；
2. **`cook_minutes` 重新定标** —— 现在全库只有 **13 个离散取值**（8/10/12/15/18/20/22/25/28/30/40/45/60），
   22 分钟 108 道（31.6%）。它是**规则生成的桶，不是真实出餐时间**；只要它还由 `CATEGORY_MINUTES` 兜底，
   "≤15min"就永远与 `category` 耦合，`BREAKFAST_QUICK_BONUS` 的独立性就是假的；
3. 之后才谈得上把早餐的两笔加成合并成"一个信号、一个幅度"。

##### 五、⚠️ 环境记录：本轮 shell 在 (39) 之后彻底失效

自 2026-09-23 约 20:40 起，所有 shell 调用（含 `echo` / `true`）均以
`SIGTERM(137)` / `resource temporarily unavailable` 失败，判断为**无法 fork 子进程**。

- §(37)(38)(39) 三节的数字是**失效前真库实跑**所得，结论有效，可引用；
- 失效后**未跑成**的只有一项：§(36) 末尾「早餐档历史实际出过什么 `category`」，
  SQL 已备好为 `/tmp/mp_breakfast_actual.sql`，沙箱恢复后一条命令即可补；
- 未跑成的部分**没有用估算填** —— 本报告不出现估算数。

---

#### (40) 🔴 循环信号假设 —— **否证**（2026-09-23 实跑，342 口径）

**team-lead 的假设**：`meal_slots` 是 0016 之后用规则回填的；若那 46 道里 `category ∈ (主食,面食) 且 cook_minutes ≤ 15` 的占比接近 100%，
则 `meal_slots=breakfast` 本身就是「主面 + 快手」启发式的产物 ⇒ 早餐加分建在一个**循环信号**上 ⇒ A 的带内主面占比不能按字面理解。

> ⚠️ **编号冲突说明**：本文已有另一节 **(40)**（上一节，标题「§(37) 的性质修正：87% 是**重复计价**，不是**循环自证**」）。
> 两节是同一天、同一问题的两次独立论证，**结论一致、互为补充**（那节从"两个信号是否同源"切入，本节从"回填规则是否就是那条启发式"切入）。
> 为避免改编号导致已经发出的引用失效，**保留重号并在此说明**，不删改任何一节。

**结论：假设不成立。三重证据，两条独立、一条决定性。**

##### ① 代码层 —— ⚠️ **本节原结论已部分撤回，见下面 (40b)**

> **撤回说明（2026-09-23 22:20 实跑）**：我原先写的是「46 道**全部**来自当前 `guess_meal_slots()` 的菜名关键词规则」。
> **这是错的**：实跑复现，当前规则只能复现 **11 / 46**，**35 道复现不出来**。
> 撤回后**循环信号的总结论不变**（仍是否证），但**支撑理由换了一条**，且挖出一个比循环更严重的问题。
> 详见 **(40b)**。以下保留原文，不删，以便追溯。

```python
BREAKFAST_WORDS = ("粥", "馒头", "豆浆", "油条", "煎蛋", "三明治", "燕麦")   # L182
...
def guess_meal_slots(recipe):                                                # L238
    name = recipe.name or ""
    if any(w in name for w in BREAKFAST_WORDS) and "炒" not in name:
        slots.append("breakfast")
```

规则**只读菜名**，**不读 `category`，不读 `cook_minutes`** ⇒ **不是**「主面 + 快手」启发式（这一层仍然成立）。

`meal_slots` 全库只有两个写入方，且**共用同一个函数**：
- `scripts/backfill_dish_scene_fields.py` L69-70
- `backend/app/services/recipe_enrich_service.py` L90-93

第三路（LLM 直接给 `meal_slots`，L208）**从未跑过**：三个 API Key 全空、`APP__LLM__DEMO=true`；
(39) 实跑的 `enrich_source` 分布是 `rule` 389 + `NULL` 7，**零 ai/llm/generation**。

⚠️ **但这只能证明"当前规则长这样"，不能证明"库里的 46 道是它标的"** —— 回填脚本只填空着的字段
（`if force or not recipe.meal_slots`），**规则改窄之后，旧规则标过的行不会被重算**。这正是 (40b) 的洞。

##### ② 集合大小矛盾（决定性，不需要看比例）

若 46 道真由「主面 **且** ≤15min」生成，它至多等于全库该启发式的命中面。
实跑：全库 342 道里 `category ∈ (主食,面食) AND cook_minutes ≤ 15` = **18 道**。

**18 道生成不出 46 道。** 集合大小直接矛盾 —— 这条比任何比例都硬，比例还能用"分布碰巧"解释，数量不能。

##### ③ 交叉表（实跑，`is_dish=1`）

| | 道数 | 占 46 道 |
|---|---:|---:|
| 标了 breakfast | 46 | 100% |
| `category ∈ (主食,面食)` | 40 | **87.0%** |
| `cook_minutes ≤ 15` | 7 | **15.2%** |
| **两者全中**（team-lead 猜的那组） | **7** | **15.2%** |
| 反例（不全中） | 39 | 84.8% |

`both_hit = 15.2%` —— **不是"接近 100%"，而是远低于**。**循环坐实的条件不成立。**
（46 道的 category 分布：面食 21 / 主食 19 / 荤菜 6；cook 分档：≤10 有 4、11-15 有 3、16-20 有 10、**21-25 有 20**、26-30 有 1、31-60 有 8。）

##### ⇒ 但 87% 主面是真的，它是"两路独立信号互相印证"，不是自我循环

`BREAKFAST_WORDS` 里的粥 / 馒头 / 油条 / 豆浆**本来就是主食**。
所以「菜名像早餐」与「品类是主面」是**两个来源不同、恰好指向同一批真菜**的信号。

⇒ **A 的带内主面占比可以按字面理解**：那 3.0 + 3.0 不是同一条启发式算了两遍，是两路证据各投一票。
⇒ **(38) 的稳定性结论不受影响** —— 它否决 A 用的是「换 profile 后真带 7~23 跳」这条**独立的**理由，与本条无关。

| 对照 | 全库 342 | 标 breakfast 的 46 | 倍数 |
|---|---:|---:|---:|
| 主面占比 | 20.5% | **87.0%** | **4.24x** |
| `≤15min` 占比 | 29.5% | **15.2%** | **0.51x（反向）** |

##### ⚠️ 核查过程挖出的真问题：`cook_minutes` 是「品类的确定性函数」，不是测量值

`guess_minutes()` L202-213 的兜底是 `CATEGORY_MINUTES[category]`：
凉菜 10 / 素菜 12 / **主食 25** / **面食 20** / 荤菜 22 / 小吃 25 / 汤羹 40。

实跑 `cook_minutes` 取值去重（342 道）——**只有 13 个取值**：

```
8(1) 10(19) 12(27) 15(54) 18(2) 20(23) 22(108) 25(37) 28(2) 30(1) 40(39) 45(2) 60(27)
```

全部落在 `CATEGORY_MINUTES ∪ METHOD_MINUTES` 的枚举里 + 2 个显式分钟。**没有一道菜有真实耗时。**

三个后果：

1. **`≤15min` ≠ 做得快**，它实际选的是「凉菜 / 素菜 / 拌拍腌 / 炒爆熘煸煎」——**按名字里的字选的**。
   ⇒ **「炒」类菜拿 `BREAKFAST_QUICK_BONUS` +1.5，而早餐标注规则恰恰用 `and "炒" not in name` 把炒排除** —— 两条规则互相矛盾（同一道「炒面」，标注规则说它不是早餐，加分规则说它够快该奖）。
2. **主面与快手在结构上互斥**：主食 = 25、面食 = 20，**都 > 15**。
   ⇒ 一道没有显式分钟、名字里没有做法词的纯主面菜，**永远拿不到 quick 1.5**。
   实测 46 道早餐菜里 21-25min 占 43.5%，`≤15min` 只占 15.2% —— **低于全库自然值 29.5%（0.51x，反向）**。
3. ⇒ **早餐那两笔代理分打在两拨不同的人身上**：3.0 打主面（粥/馒头/面条），1.5 打凉菜/素菜/炒菜。
   **A 里那 1.5 是在稀释主面占比的，不是加强它。** 这与 (38) 实测到的「13 道距 cutoff 只有 +0.50 分的快手非主面菜被救回带里」完全对上 —— 那 13 道就是被 1.5 抬进来的凉菜/素菜/炒菜。

---

#### (40b) 🔴 自查推翻自己的①：**当前规则只能复现 46 道里的 11 道**（2026-09-23 22:20 实跑）

写 (40) 时我用代码断言「46 道全部来自当前 `guess_meal_slots()`」。
**B1 的带里出现了「肉饼炖蛋」（60 分钟、名字里没有 `BREAKFAST_WORDS` 任何一个词）**，说明这个断言站不住 —— 于是实跑复现。

| | 道数 |
|---|---:|
| 标了 breakfast（`is_dish=1`） | **46** |
| **能被当前规则复现** | **11** |
| **复现不出来** | **35（76%）** |
| 反向：名字命中当前规则但没标（漏标） | **0** |

⇒ **当前规则 ⊆ 库中标注**；库中标注 = 当前规则（11）+ **旧规则残留（35）**。
⇒ 根因：回填脚本只填空着的字段（`if force or not recipe.meal_slots`），**规则改窄之后旧标注不会被重算**，
且 `enrich_source` 仍记 `rule` —— **来源标签是真的，但它指的是"曾经被某个版本的规则标过"，不是"被当前规则标过"**。
（这又是一个「**标注生命周期要绑到生效而非写了**」的实例。）

⚠️ **更准确地说，`enrich_source='rule'` 连"meal_slots 是被规则标的"都不能证明**：
`backfill_dish_scene_fields.py` L112-113 是**只要这次 patch 了任意一个字段**（哪怕只补了 `cook_minutes`）
就把整行 `enrich_source` 置成 `RULE`。⇒ 一行 `meal_slots` 来自种子数据、只被补了 `cook_minutes` 的菜，
`enrich_source` 同样是 `rule`。
⇒ **§(40) 第三节的"库里 `meal_slots` 100% 来自当前规则"应据此修正**：能证明的只有"当前规则不读
`category`/`cook_minutes`"，**不能证明"库里 46 道都是它标的"**（实跑只有 11 道）。

##### 那 35 道里有什么（决定性）

旧规则显然比现在宽 —— 命中形状是「**饼 / 面 / 包 / 饭**」这类子串：

```
60min×4  肉饼炖蛋 / 羊排焖面 / 蒸卤面 / 豆角焖面
40min×4  鹰嘴豆炸饼 / 印度烤饼 / 空气炸锅面包片 / 炸酱面
25min×14 烙饼 / 手抓饼 / 芝麻烧饼 / 蛋包饭 / 披萨饼皮 / 河南蒸面条 / 中式馅饼 …
22min×6  手撕包菜 / 老式锅包肉 / 微波炉荷包蛋 / 牛奶燕麦 / 鸡蛋三明治 / 金枪鱼酱三明治
20min×10 热干面 / 汤面 / 炸酱面系 / 意式肉酱面 / 半成品意面 / 麻辣减脂荞麦面 …
15min×3  滕州菜煎饼 / 茄子肉煎饼 / 莴笋叶煎饼
10min×4  老干妈拌面 / 葱油拌面 / 酱拌荞麦面 / 麻油拌面
```

**误标的实锤**：「**手撕包菜**」（22min、荤菜）和「**老式锅包肉**」（22min、荤菜）被标成早餐 ——
只能是某个版本的规则拿「**包**」当早餐词（"包子"的"包"）做子串匹配。

> ⚠️ **"旧规则"这个定性是推断（第一手：实跑复现 + 形状归纳），不是查证。**
> 另一个同样可能的来源是**种子数据自带 `meal_slots`**（`data/sql/recipes_seed.sql`）——
> 区分两者需要读种子文件，**沙箱失效未跑成，标为待核实**。
> **无论哪个来源，结论一致**：这 35 道**不是当前规则标出来的**，也不会被 `--force` 之外的任何流程重算。
⇒ **46 道早餐池里有 8 道 ≥40 分钟**（4 道 60min + 4 道 40min），还有锅包肉和手撕包菜。

##### ⇒ 循环信号的**总结论不变**，但支撑理由换成这两条

1. **集合大小矛盾**（不受影响，仍然是决定性的）：全库「主面 且 ≤15min」只有 **18 道 < 46**。
2. **两个版本的规则都是菜名关键词规则**（粥/馒头/… 与 饼/面/包/饭），**都不读 `category`、不读 `cook_minutes`**。
   ⇒ 无论按哪一版，`meal_slots=breakfast` 都**不是**「主面 + 快手」启发式的产物。

⇒ **"A 的带内主面占比不能按字面理解"这个推论，仍然不成立。**

##### 🔴 但代价是挖出一个比循环严重得多的问题：**早餐池本身是脏的**

⇒ **B（硬过滤到 46 道）的池子里有 60 分钟的炖菜、40 分钟的炸物、锅包肉和手撕包菜。**
⇒ 实测 B1 的 P0 真带 8 道里，**4 道是 ≥40 分钟的**（炸酱面 40 / 鹰嘴豆炸饼 40 / 肉饼炖蛋 60 / 蒸卤面 60）—— **一半**。

**这是"定 B"的致命反例**：B 的池子不是"46 道早餐菜"，是"46 道被某个旧版本规则标成早餐的菜"。

---

#### (40c) ⚠️ 撤回「`BREAKFAST_QUICK_BONUS` 置 0」的建议 —— 实跑证明它在**救多样性**

(40) 里我建议「本版把 `BREAKFAST_QUICK_BONUS` 置 0 不接线」，理由是它表达的"快"是假的（名字里有炒/拌/煮）。
**实跑撤回**：去掉 quick 那一笔（`A= = slot + cat`）之后 ——

| 变体 | 真带 | 品类 | 带内主面% | MC 第一道主面% |
|---|---:|---:|---:|---:|
| **A** = slot + cat + quick | 23 | **5** | 43.5% | 42.4% |
| **A=** = slot + cat（去 quick） | **10** | **2** | **100.0%** | **100.0%** |

⇒ **去掉 1.5 之后，真带从 23 掉到 10、品类从 5 掉到 2、带内全是主面。**
⇒ 那 1.5 的**名义语义**（出餐快）是假的，但它的**客观作用**是往带里注入凉菜/素菜，**是 A 唯一的多样性来源**。
⇒ **不能简单置 0。**(这是我自己第二次犯"给断言前先实跑"的错 —— 与 SQL-C 那次同型。)

**修正后的建议**：不动 `BREAKFAST_QUICK_BONUS` 的值；把它的**注释改成实话** ——
「这不是"出餐快"，是"名字里带快做法词"；它在客观上是本档唯一的品类多样性来源，删它要同时补多样性」。

##### ⇒ V1.3 根治项扩充（并入 12z-c）

从「统一早餐标注口径」扩到**三条**：

1. **统一早餐标注口径**（不变）
2. **`cook_minutes` 重新定标** —— 现在是 13 个枚举桶，**不支持「快手」这种连续语义**；
   且它与 `category` 同源，拿它当「第二个独立信号」是假的独立。
3. **🔴 `meal_slots` 必须 `--force` 全量重算 + 清 35 道旧规则残留** ——
   当前库里 76% 的早餐标注**不是当前规则标出来的**，且含锅包肉/手撕包菜级误标。
   ⇒ **在这一条做完之前，任何以 `meal_slots` 为前提的方案（含 B）都不能上** —— 池子本身不可信。

---

#### (41) ✅ B（硬过滤 46 道）在 P0–P5 下的真带 —— **已跑，且与既有 §(41) 独立复核一致**

> ⚠️ **编号冲突 + 状态更正说明（2026-09-23 22:30）**
> 本文已有另一节 **(41)**（上一节「B 的 P0–P5 补跑：B 自己也被否决」）。
> **那节是真的，本节不取代它 —— 本节是它的独立复核。**
> 我（数析）曾误判那节"未实跑"并要求撤下，**该判断已撤回**：两条独立路径（那节的脚本 / 本节脚本）
> 在同一真库 342、同一 seed 20260923 下跑出**逐格相同**的结果，只是 **B1/B2 命名相反**：
> 那节 B1 = 池46 无早餐加分、B2 = 池46 现行 A 加分；**本节 B1 = 保留 A 加分、B2 = 纯 base**。
> ⇒ **引用时务必写明用的是哪套命名**，否则"P5 真带 7"会被挂到错误的变体上。
> 教训：**证据缺失 ≠ 证据为反**；且**共享文件是并发写的，读到的快照不代表当前状态。**

**为什么必须有这条**（user-researcher + requirement-analyst 各自独立提出，我确认成立）：

现有敏感性数据只挂在 A 上（真带 7~23 跳、主面 43.5%~93.3%、品类 2~5、P5 下 7 < `POOL_MIN`）。
它证明了 **A 不稳定**，但**推不出「选 B」** —— 因为 B 恰恰是没被压力测试过的那个。

> 🔴 **已入档的通用纪律**：「否决一方 ≠ 选中另一方；要做选择，两边得有同构的证据。」
> 本条属于**证据结构不对称**，比归属/出处错误更隐蔽 —— 每一步看起来都合规：A 确实测了、B 确实没被否掉、结论确实有数。

**另外要防一个同形陷阱**：B "存活"用的那个 46 是**候选池**，不是**抽签带**。
这与 (33) 的教训同源 —— **池子大小只能否决，不能选中**；判据一律用 `natural_band_size`，不用池子数。

**脚本已就绪**（`/tmp/mp_B_stability.py`，只读、零写入），一次跑出 A / A+ / B1 / B2 四个口径 × P0–P5 六场景：

| 变体 | 定义 |
|---|---|
| A | 全池 342，叠加不封顶（现行实现） |
| A+ | 全池 342，叠加后封顶 `SOFT_PREFERENCE_CAP` |
| **B1** | **硬过滤到 46 道 + 保留现行 A 的加分** |
| **B2** | **硬过滤到 46 道 + 去掉代理补偿（只留 base）** |

输出：池 / 真带 / band / 品类数 / 带内主面% / **用户第一道主面%（N=500 蒙特卡洛，主口径）** / 最大单品类 / 是否跌破 `POOL_MIN`(8)。

##### ✅ 已跑（2026-09-23 22:20，真库 342，`random_band=5.0`，`POOL_MIN=8`，seed=20260923，N=500）

| 场景 | A 真带 | A 品类 | A 第一道主面% | A+ 真带 | A+ 品类 | A+ 第一道主面% | **B1 真带** | **B1 品类** | **B1 第一道主面%** | **B2 真带** | **B2 品类** | **B2 第一道主面%** |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P0 默认 | 23 | 5 | 42.4% | 64 | 6 | 23.2% | **8** | **2** ✗ | 100.0% | 10 | 3 | 78.0% |
| P1 spice=1 | 15 | 3 | 93.4% | 102 | 6 | 61.2% | 11 | 3 | 89.2% | 44 | 3 | 90.2% |
| P2 spice=2 | 23 | 5 | 42.4% | 64 | 6 | 23.2% | **8** | **2** ✗ | 100.0% | 10 | 3 | 78.0% |
| P3 昨天荤菜×1 | 18 | 4 | 55.2% | 27 | 5 | 57.8% | **8** | **2** ✗ | 100.0% | **8** | **2** ✗ | 100.0% |
| P4 昨天荤菜×2 | 18 | 4 | 55.2% | 27 | 5 | 57.8% | **8** | **2** ✗ | 100.0% | **8** | **2** ✗ | 100.0% |
| **P5 昨天主食×2+spice1** | **7** ✗ | **2** ✗ | 87.0% | 62 | 5 | 40.6% | **7** ✗ | **2** ✗ | 87.0% | 25 | **2** ✗ | 79.4% |

（✗ = 未过门禁：真带 < `POOL_MIN`(8) 或 品类数 ≤ 2）

##### ⇒ 结论：**A、B1、B2 三方都没过；A+ 是唯一六场景全绿的**

| 变体 | 真带区间 | 品类数 | 判定 |
|---|---|---|---|
| A 叠加不封顶 | **7 ~ 23** | 2 ~ 5 | ❌ P5 跌破 `POOL_MIN`、品类 2 |
| **A+** 叠加封顶 4.0 | **27 ~ 102** | **恒 ≥ 5** | ✅ **六场景全绿** |
| **B1** 硬过滤 + 保留 A 加分 | **7 ~ 11** | **2 ~ 3**（4/6 场景 = 2） | ❌ P5 跌破；品类数恒 ≤3 |
| **B2** 硬过滤 + 纯 base | **8 ~ 44** | **2 ~ 3** | ❌ 品类数恒 ≤3（P3/P4/P5 = 2） |

**三条硬结论：**

1. **"选 B"不成立 —— B 自己也没过。** 这补上了瑞思/要求分析师指出的那个洞，**而且结论是否定的**：
   - B1 在 **P5 真带 7 < `POOL_MIN`(8)**，与 A 同一个失败点；
   - B1/B2 **品类数恒 ≤ 3**（多数场景 = 2），**多样性是四个变体里最差的**。
   ⇒ 直觉上"B 的池子 87% 主面 ⇒ 早餐味最浓"，代价是**用户只在 8 道、2 个品类里抽** ——
   这正是这一整版在治的"总是同一批菜"。
2. **B 的失败形态与 A 不同**：A 是"真带 7~23 跳"（不稳定）；**B 是"品类数恒 ≤3"（多样性塌）**。
   ⇒ 所以"用 B 换掉 A"并不能解决 A 的问题，只是**换一种失败**。
3. **(40b) 的叠加判决**：B 的池子里有 60min 炖菜、40min 炸物、锅包肉、手撕包菜
   （B1 的 P0 真带 8 道里 **4 道 ≥40 分钟**）⇒ **B 的"存活"资格本身也该重新审**（池子脏）。

##### ⇒ PRD 措辞（与要求分析师 12z-g 对齐）

> 🔄 **2026-09-23 22:35 更正**：下面前两条措辞建议**已作废**，起因是我误判"B 未实跑"并要求撤下
> （详见本节开头的编号冲突说明）。**B 跑过了**，所以"未经压力测试"这句**不能再用来描述 B**。
> 我原来的"取稳的那句"反而把**已实测的事实**降格成了**证据缺失** —— 稳 ≠ 弱。

- ❌ ~~"B 未经压力测试，不足当选"~~ —— **已作废**：B 已实跑，这句不再成立
- ❌ "B 被否决" —— 这是**判断**，留给主理人；数据侧不替产品下判决
- ✅ **写实测事实，不写判断**：
  「**B1/B2 品类数恒 ≤ 3（多数场景 = 2）；B1 在 P5 真带 7 < `POOL_MIN`(8)**」
  —— 可复核、可复现（`/tmp/mp_B_stability.py` + `/tmp/mp_breakfast_v2.py`，两套命名相反，引用时标清）
- ⚠️ **两套 §(41) 的 B1/B2 命名相反**（前一节 B1=无早餐加分 / B2=现行 A 加分；本节 B1=保留 A 加分 / B2=纯 base），
  **"P5 真带 7" 属于哪一节口径不同会挂到不同变体上**，引用时必须带节号。

##### ⚠️ 同一条纪律的反面：拍板用的两个候选，指标也得同构

team-lead 要求"测 A 与 A+ 两个数报我拍板"。现状**不齐构**：

✅ **已补齐（22:20 实跑）。** 并更正一处此前流传的口径混淆：

| 变体 | 带内主面% | 用户第一道主面% | 真带区间 | 品类数 |
|---|---:|---:|---|---|
| A 叠加不封顶 | **43.5%** | **42.4%** | 7 ~ 23 | 2 ~ 5 |
| A+ 叠加封顶 4.0 | 25.0% | 23.2% | 27 ~ 102 | 恒 ≥ 5 |

> ⚠️ **口径更正**：此前队内流传的「A = 42.4%」是**用户第一道**口径；**带内是 43.5%**。
> 两个数都对，是**两列** —— 引用时必须标清是哪一列，否则下次复核会对不上。

⇒ **"否决一方 ≠ 选中另一方"的反面是"拍板用的两个候选，指标口径必须一样"** —— 同一个纪律的两个方向。
⇒ 现在两边同构了，**可以拍**。数据侧的排序：**A+ 是唯一六场景全绿的**；A 在 P5 判红（真带 7 < `POOL_MIN`、品类 2）。

---

#### (44) 🔴🔴 补标后最坏情况 × 封顶扫描：**5.5 是唯一两个时点都不出红字的档**；且补标口径本身会**制造**循环（2026-09-23 实跑）

补标口径与 `backend/scripts/band_regression.py` `_relabeled_for_breakfast`（L272-290）逐字一致：
给 `category ∈ (主食,面食) OR minutes <= 15` 的菜补 breakfast。

##### 补标前后命中组

| | 标 breakfast | 其中主面 | 其中快手 | 主面 ∧ 快手 |
|---|---:|---:|---:|---:|
| 现状 | **46** | 40 (87.0%) | 7 (15.2%) | 7 (15.2%) |
| 补标后 | **159** | 70 (44.0%) | 101 (63.5%) | 18 (11.3%) |

（159 = 46 ∪ {主面 ∨ 快手}，其中 |主面 ∨ 快手| = 70 + 101 − 18 = 153，加上现状 46 里那 6 道既非主面也非快手 ⇒ 153 + 6 = 159 ✓）

##### 补标后 × 三档封顶（真库 342，同 seed）

| 封顶 | P0 | P1 | P3 | P5 | 最差真带 | 最差品类 | 最差倍数 |
|---|---|---|---|---|---:|---:|---:|
| 4.0（A+） | 77/6/22.1% (1.08x) | 174/8/38.5% | 32/5/53.1% | **132/7/18.9% (0.93x)** | 32 | 5 | **0.93x 反向** ❌ |
| **5.5** | 42/5/40.5% (1.98x) | 143/6/46.9% | 29/4/58.6% | 101/5/24.8% (1.21x) | 29 | **4** | 1.21x |
| 7.5（现行 A） | 22/5/40.9% (2.00x) | 30/3/80.0% | 17/4/52.9% | 16/2/62.5% | **16** | 2 | 2.00x |

##### 四条读法

1. **现行 A（7.5）补标后不塌**：P0 40.9%（2.00x）、P5 真带 16 ≥ `POOL_MIN` ⇒
   与 dev-engine-relax 记录的"补标后最坏 40.4%（1.98x）"一致（差 0.5pp，分母 342 vs 343）。
   **A 的红字只出现在"现状标注"的 P5（真带 7），补标后反而好了。**
2. **A+（4.0）补标后翻车**：P5 主面 18.9% → **0.93x 反向**。原因：补标让命中组 46 → 159（46%），
   slot 那 3.0 变成"几乎所有主面菜都拿"，封顶 4.0 把它压成常数 ⇒ **加分退化为无加分**。
3. ⇒ **§(42) 我给 A+ 的"最稳"评价只在现状标注下成立。补标后 A+ 是三档里唯一反向的。**
4. **5.5 是两个时点都不出红字的唯一档**：现状 2.12x / 最差真带 18 / 品类 2；补标后 1.21~2.86x / 最差真带 29 / 品类 4。
   ⇒ **若要在"现在能用"和"补标后还能用"之间只选一个值，选 5.5。**

##### ⚠️ 更要紧的一条：**补标口径本身会制造 team-lead 担心的那个循环**

`_relabeled_for_breakfast` 用的正是 `主面 OR ≤15min` 这条启发式。一旦照它补标注：

> **`meal_slots=breakfast` 就从「菜名信号」（§(40) 证据 1，独立于 category/cook_minutes）
> 退化成「主面 或 快手」信号本身 —— team-lead 怀疑的循环，会从未来时变成现在时。**
> 那时 slot 3.0 与 `BREAKFAST_CATEGORY_BONUS` 3.0 的**独立性归零**，§(40) 的全部论证作废。

⇒ **数据侧的修法建议（替代 §(40) 原提法）**：补标注**不要**用 `主面 OR ≤15` 这条口径补。
`meal_slots` 现在唯一的资产是"它来自菜名，与品类正交"；用品类去补它，等于**用已有的信号覆盖唯一的独立信号**，
补完覆盖率上去了、信息量反而归零。V1.3 补标注应走**菜名词表扩充 + 人工/LLM 判定**，
或至少把补标来源记进 `enrich_source`（现在只有 `rule`/`NULL` 两值，分不清是原规则还是补标规则）。

---

#### (41) 判据选型：**硬过滤禁用带内占比；软加分的"倍数"必须配真带下限**（2026-09-23，应 user-researcher 附录 E 提案的数据侧复核）

user-researcher 提出按方案类型分别选指标（软加分用**相对自然分布的倍数** + 抽签空间；硬过滤用**抽签空间 + 品类数**，❌ 禁用带内占比）。
**数据侧全部同意，但倍数口径有一条会选错方案的实证反例，必须补。**

##### 一、硬过滤禁用带内占比 —— 数据侧的理由是"分辨力 ≈ 0"，不是"口径偏好"

`带内占比 ≈ 池子占比 × 打分的边际影响`。
当硬过滤的池子本身 **87% 是主面**（§37：46 道里 40 道）时，任何方案的带内占比都落在 80%+ ⇒
**换任何打分方案，这个数都几乎不动** ⇒ 它**区分不了"方案好"和"池子本来就这样"**。

> 判据的第一性是**能区分候选方案**。分辨力 ≈ 0 的指标，哪怕算得再准也不该进判据集。

##### 二、🔴 但"倍数"单独用会**选出塌缩最严重的方案**（实证反例）

§(38) 诊断行 `A=（slot + cat，去掉 quick）`：

| 变体 | 真带 | 品类 | 带内主面% | **倍数** | 实际定性 |
|---|---:|---:|---:|---:|---|
| **A= `slot+cat`** | **10** | **2** | **100%** | **4.89x** | 🔴 **塌缩最严重**（品类只剩 2） |
| A 叠加不封顶 | 23 | 5 | 43.5% | 2.12x | 🟡 不稳（56.5% 靠 0.5 分） |
| A+ 叠加+封顶 | 64 | 6 | 25.0% | 1.22x | 🟢 稳 |

⇒ **按"倍数越高越好"，A=（4.89x）是全场第一；按"塌没塌"，A= 是全场最差。**

根因：**倍数随真带变小而系统性虚高** —— 真带越小，留在带里的越是"被加分命中的那一批"，占比自然冲高。
实证：A 的真带 23 → 7（P5 场景），倍数同步 **2.12x → 4.18x**。这是**系统性偏差，不是噪声**。

##### ⇒ 建议改成**双门槛**（顺序不能反）

```
第一道（硬前置，先过）：natural_band_size >= 下限  ∧  品类数 >= 3
第二道（后比，只在过了第一道的方案之间比）：相对自然分布的倍数
```
- 下限取 **门禁下限 18**（`band_regression.py` 的 `eff_band_min` = `ceil(0.05 × 342)`，防绝对阈值随池子变松）；
- 绝对底线 **`POOL_MIN = 8`**（低于此值触发放宽阶梯，说明方案已经改变产品行为而不只是排序）；
- **没过第一道的方案，不许拿倍数出来比。**

##### 三、`natural_band_size` 判据里 NULL 的两个方向都要防（§(33) 两种空的具体写法）

| 写法 | NULL 行的行为 | 后果 |
|---|---|---|
| `SUM(CASE WHEN natural_band_size >= X ...)/COUNT(*)` ≥ Y% | NULL 行进分母、不满足条件 | **判据偏严 ⇒ 假红** |
| `NOT EXISTS (... natural_band_size < X)` | NULL 行不触发 | **判据偏松 ⇒ 假绿** |

⇒ **必须显式写 `natural_band_size IS NOT NULL`**，两种写法都不安全（这是"0 恒假 / NULL 恒真"同一条通则的第三个实例）。
⇒ 另：空池决策**根本不落库**（L421-424 `raise RuntimeError`）⇒ **抽签空间全绿不能论证"没有空池问题"**，那份数据不在表里。

##### 四、12z-f 交互的实数：离线池 62 道里**只有 4 道**标了 breakfast（6.5%）

`data/local_dish_pool.json` 实测：62 道全部有 `slots` 字段，其中含 `breakfast` 的 **4 道**（6.5%）。
对照真库 342 道：**46 道（13.5%）** ⇒ **两个池子的早餐标注密度不同源**。

且离线池是**人工标注**，不是规则生成 —— 证据：`手撕包菜` 被标成 `["breakfast","lunch"]`，
而真库规则（`BREAKFAST_WORDS` = 粥/馒头/豆浆/油条/煎蛋/三明治/燕麦）**绝不会把"手撕包菜"标成早餐**。

⇒ 与 12z-f（DB 候选 < 20 时本地池 62 道无条件追加、**不过任何硬过滤**）叠加后的后果是可量化的：
**追加的 62 道里 58 道不是早餐菜，且绕过过滤全进池** ⇒ 早餐硬过滤的池子被稀释到 `46/(46+62) = 42.6%`，**且不报错**。

⇒ 两条建议（V1.3 若走硬过滤）：
1. **本地池 62 道要么一起过过滤，要么明确豁免并登记**（不能靠"忘了写"默认豁免）；
2. **统一早餐标注口径时，离线池 62 道必须一并纳入** —— 否则又是 `shared/decide.ts` 与 `decision_service.py` 的口径分叉。

##### 五、中式早餐口径（与 user-researcher 的判断同向，附实数）

| 口径 | 池子 | 形态 | 问题 |
|---|---:|---|---|
| **B `meal_slots` 含 breakfast** | **46** | 面食 22 + 主食 20 + 荤菜 6 ⇒ **95.7% 主面**（粥/面/饼/馒头） | 少，但形态对 |
| A `cuisine='早餐'` | 25 | 燕麦 / 三明治 / 荷包蛋 | **68% 被标成 `category`=荤菜（标错）**；叠硬过滤后实测 **∩ ≤15min 只有 7 道 < `POOL_MIN` 8** |

⇒ **B 更贴近中国用户的真实早餐，且是数据给出的排序（不是产品裁决）** —— 见 §(36)。

> ⚠️ **与 §(41) 的分工别混读**（2026-09-23 22:20 补）：
> 本节说的是**池子构成**（B 的 46 道形态对不对）；§(41) 实测的是**抽签带健康度**
> （B1 真带 7~11、B1/B2 **品类数恒 ≤3**、B1 在 P5 真带 7 < `POOL_MIN` 8）。
> ⇒ **形态对 ≠ 可上线。** 两节不矛盾：B 的池子确实是早餐菜，但用户实际只在 **8 道、2 个品类**里抽。
> ⇒ 另见 §(40b)：这 46 道里有 8 道 ≥40 分钟、还有锅包肉和手撕包菜（旧规则残留），**池子本身也待清**。

##### 六、对 §(40) 的一句补充（别把"独立性"说满）

`BREAKFAST_QUICK_BONUS`（1.5）虽是"唯一独立维度"（与标注重合仅 15.2%），
但它**也带着 `category` 的血统**：`cook_minutes` 的兜底是 `CATEGORY_MINUTES[category]`（主食 25 / 面食 20），
⇒ 主食/面食**永远**拿不到这 1.5。它的独立性是**打折的独立**，不是纯净的第二维度。
⇒ V1.3 三件事（补 17 道标注 / 修 `category` 误标 / **`cook_minutes` 重新定标**）一件都不能省，
   否则"两个独立代理"这件事在数据上永远不成立。

##### 七、本节未跑成的一项（shell 失效）

**早餐档历史实际出过什么 `category`**（`decision_log` 按 `meal_slot` 切片）—— 它是**真实曝光分布**，
正是软加分基线倍数最该对的那个"自然分布"的线上版本。SQL 已备 `/tmp/mp_breakfast_actual.sql`，
沙箱恢复后第一时间补。**未用估算填。**

---

#### (45) `tools` 值分布：两组"对不上 2 道"是**口径混用**，不是数据矛盾（2026-09-23 同一次运行实跑）

触发：要求分析师核 PRD §5.1 时发现 `tools` 那格同时挂着两组分布 ——
342 下 `pot 39 / steamer 13 / oven 9 / air_fryer 5 / pot+steamer 1`（有值 67），
396 下 `pot 43 / steamer 14 / oven 11 / air_fryer 5`（有值 72）。
有值之差 = 5，逐值相减 = 7，**差 2 对不上**。

SQL：`/tmp/mp_tools_dist.sql`（一条语句同时出三口径，含自校验列）。分母快照 **396 / 342 / 54**。

##### 结论：**两组各自都正确，且同一次运行内自洽**；差 2 来自**两套口径混用**

| tools 取值 | 342 | 396 | 非菜品(54) |
|---|---:|---:|---:|
| `["pot"]` | 39 | 42 | 3 |
| `["steamer"]` | 13 | 13 | 0 |
| `["oven"]` | 9 | 11 | 2 |
| `["air_fryer"]` | 5 | 5 | 0 |
| `["pot","steamer"]` | **1** | **1** | 0 |
| **有值合计** | **67** | **72** | **5** |
| NULL | 275 | 324 | 49 |
| **覆盖率** | **19.6%** | **18.2%** | **9.3%** |

- **口径 A（上表）= 组合独立成行**：多值菜只在自己那一行计一次 ⇒ **各行相加 = 有值道数**，可用于覆盖率；
- **口径 B = 单值 LIKE 计数**：一道 `["pot","steamer"]` 在 pot / steamer 里**各计一次** ⇒ 行和 ≠ 有值道数。
  PRD 里 396 那组（pot 43 / steamer 14）就是口径 B —— 43 = 42 + 1（组合菜）、14 = 13 + 1（同一道）。
- 342 换成口径 B 是 **pot 40 / steamer 14 / oven 9 / air_fryer 5**，与 396 逐值相减 = **3+0+2+0 = 5** ✅
- 自校验：`(has_396 − has_342) − has_非菜品 = 0` ✅

##### 非菜品里有 `tools` 值的 5 道（回答"到底是 5 还是 7"）

| id | 菜名 | category | tools |
|---|---|---|---|
| 180 | 烤箱版巴斯克芝士蛋糕 | 荤菜 | `["oven"]` |
| 182 | 烤蛋挞 | 荤菜 | `["oven"]` |
| 333 | 酸梅汤 | 汤羹 | `["pot"]` |
| 334 | 酸梅汤（半成品加工） | 汤羹 | `["pot"]` |
| 340 | 金汤力 | 汤羹 | `["pot"]` |

⇒ **"非菜品里 tools 覆盖率 5/54 = 9.3%，剔非菜品会抬升覆盖率"这个解释成立**（18.2% → 19.6%，+1.4pp），
与 §5.4 档位判定共用同一套推理没问题。

##### 🔴 通用纪律（超出 `tools` 一处）

> **覆盖率一律用"组合独立成行"口径；单值 LIKE 计数会重复计数，不能用来算覆盖率。**
> 更一般地：**两组数并列时，先问它们是不是同一口径**，而不是先问谁错了。
> 这次的"差 2"是**口径差**，不是**数据差** —— 如果直接判其中一组错，就会去改一个本来正确的数。

---

#### (46) 🔴🔴 方法论：**别用"我没找到"当否证**（2026-09-23，我自己犯的，代价最大）

##### 事件

我曾对外发出「B 的 P0–P5 **没跑过**，要求撤下」，依据是三条：

| # | 我的"证据" | 实际 |
|---|---|---|
| ① | `/tmp` 里没有 B 的脚本 | ❌ **有** —— `/tmp/mp_breakfast_v2.py`，**文件名里没有 B**（docstring 第一行写着"早餐 A / A+ / B 变体实测 v2"，L117 就是 `pool_b`） |
| ② | 报告结尾在 §(39)，没有 §(41) | ❌ **读到的是过期快照** —— 文件当时已写到 §(43)，还有三个 (40) 重号段 |
| ③ | 沙箱失效，跑不了 | ✅ 真 —— 但**推不出"没跑"**，B 是在失效之前/之间跑完的 |

⇒ 后果：差点让 PRD v1.28 撤下一组**真实**数据；两位同事各白改一轮。

##### 纪律

> **要翻转一个已发出的结论，必须先找到原结论的产出物（脚本 / 原始输出 / 报告段）。**
> **找不到就按"我记不清"处理，请对方出示原文 —— 不能直接判它不存在。**

##### 三条派生规矩

1. **共享文件是并发写的，读到的快照不代表当前状态** ⇒ 引用报告段落**带节号，不带行号**（行号会漂）。
2. **按名字搜不到 ≠ 不存在** ⇒ 找产出物要**按内容搜**（`pool_b`、"B 的池子"、`POOL_MIN`），不能只按文件名里的关键字。
3. **证据缺失 ≠ 证据为反** —— 这条我在 §(33) 就写过（J6'/J7' 的 NULL 恒真），
   这一轮又在"**我自己的产出物**"上原样犯了一遍。
   ⇒ 说明它**不能只当 SQL 纪律记**：同样适用于"我记得我没跑过"这类**关于自身状态的断言**。
   ⇒ 更一般地说：**"我没找到 / 我没跑过 / 我没发过"都是关于自身的负向断言，同样需要产出物支撑，不能凭记忆。**

##### ⚠️ 追加发现：`/tmp` 会被清空 —— **脚本路径不能作为长期可复现依据**

2026-09-23 22:40 复核：`/tmp` 下**只剩本次新写的一个文件**，此前所有 `mp_*.sql` / `mp_*.py`
（含 §(41) 的 `mp_breakfast_v2.py`、本节引用的 `mp_B_stability.py`）**全部不可再访问**。

⇒ 三层后果：
1. **我给出去的"可复现脚本 `/tmp/mp_breakfast_v2.py`"现在是空指针** —— 已另行通知要求分析师
   把 PRD 引用改成 **`data-readiness-metrics.md §(41)` + 口径描述**（不引 /tmp 路径）。
2. **这也反向削弱了我那条误判的第 ① 条依据**：我当时说"/tmp 里没有 B 脚本"。
   现在看，**"按 /tmp 路径找产出物"这件事本身就不可靠**（视图会变、内容会清）——
   就算我搜到了也不能作为否证，搜不到更不能。
3. ⇒ **产出物必须落在报告里，不能只落在临时目录**：数 + 口径 + 关键常量写全，
   别人照着能重跑出来；只留一个路径，三个月后就是死链。

**§(41) 的可复现口径（照此可重跑，不依赖任何临时文件）**：
真库 `is_dish=1`（342 道）/ `slot=breakfast` / 空冰箱、空历史、无 intent、默认天气 /
`random_band=5.0` / `POOL_MIN=8` / 蒙特卡洛 N=500、seed=20260923；
**真带 = `natural_band_size`（不含 padding）**；B = 硬过滤到 `meal_slots` 含 breakfast 的 46 道。

##### 与既有两条的关系（三条是一组，逐层加深）

| 纪律 | 管的是什么 |
|---|---|
| 给断言前先实跑一遍（SQL-C 那次） | 别给**没验的**数 |
| 证据缺失 ≠ 证据为反（§33 NULL） | 别把**没测**当**没发生** |
| **别用"我没找到"当否证（本节）** | 别把**没找到产出物**当**产出物不存在** —— 尤其当它指向**自己**时 |

---

#### (47) 🔴 补跑结果不是"分布"，是**早餐档零线上样本**（2026-09-23 实跑，只读）

§(36) 挂着的待补跑项「早餐档历史实际出过什么 `category`」，原 SQL 随 `/tmp` 丢失，本次重写并重跑。

**结果：不是"跑出一个分布"，是 `decision_log` 里 `meal_slot='breakfast'` 的行数 = 0。**

| `meal_slot` | 行数 | 占比 |
|---|---:|---:|
| dinner | **169** | **88.0%** |
| late_night | 15 | 7.8% |
| lunch | 8 | 4.2% |
| **breakfast** | **0** | **0%** |
| **合计** | **192** | 100% |

（时间跨度 2026-09-17 15:05 ~ 2026-09-23 20:30，共 192 行。
对照全餐次 `dish_category` 分布：荤菜 42 / 面食 39 / 汤羹 36 / 小吃 19 / 凉菜 18 / 素菜 17 / 主食 13 / 空串 8。）

##### ⇒ 三条必须写进结论的话

1. **本轮所有早餐实测（A / A+ / B1 / B2 × P0–P5、封顶扫描 4.0~7.5）都是离线仿真，没有任何一条线上行为数据能支撑它。**
   ⇒ 早餐方案选哪个档，**证据强度是"离线仿真"，不是"用户行为"**。这句话必须进 PRD，否则上线后验收会拿不出对照基线。
2. **任何以 `decision_log` 为分母的早餐判据（J6' / J7' / J8'）在早餐档上是零样本。**
   ⇒ "早餐判据全绿"**不能**解读为"早餐没问题" —— 与 §(33)「空池不落库」是同一类：**表里的空 ≠ 现实的空**，这里是**表里没样本 ≠ 现实没用户**。

> 🔄 **措辞收紧（2026-09-23，team-lead 〇 区分 + 我加一层防过度作废）**
>
> ⚠️ **"离线仿真" ≠ "无效"。** 必须分两层，否则会走到另一个极端 —— 把明明有效的东西一起扔掉
> （本轮已在 42.4%/43.5% 上犯过一次"过度作废"，代价是把可推导的真数据丢了）：
>
> | 类别 | 依赖线上流量？ | 早餐档零样本下的效力 |
> |---|---|---|
> | **band 回归门禁**（AC-1 / AC-4） | ❌ 不依赖 —— 拿 342 道菜的池子问"代码会怎么选" | ✅ **仍然有效**，"早餐档 8 格全过"这句话本身没错 |
> | **J6' / J7' / J8'**（以 `decision_log` 为分母） | ✅ 依赖 | ⛔ **零样本，不可判定** —— 禁写"通过" |
>
> ⇒ **精确表述**：「早餐档全部实测的证据等级是离线仿真 —— **可用于代码回归判据，不可用于任何用户行为结论**。」
> ⇒ 与 §(33) 同型但**方向相反**：那条是"表里的空 ≠ 现实的空"，本条是"**表里没样本 ≠ 仿真不能用于回归**"。
>   两条合起来才是完整的一对，只记一条一定会被误用。
>
> 📌 **team-lead 原话，留档**：*「在拿不出对照基线的情况下做决策侧改动，是拿用户试错。」*
> ⇒ 这是 V1.2.0 **早餐零改动**裁定的**第二层独立支撑**：不只是"改了没好处"，
>   而是**"我们没有能力验证改了有没有好处"**。
3. **`decision_log` 整体只有 192 行、且 dinner 占 88%** ⇒ 连"晚餐"之外的餐次都谈不上样本量。
   ⇒ 一级指标里凡是按餐次拆分的（§4 漏斗），**早餐/午餐目前无法验**，只能记"待积累"。

##### 给埋点方案的一条硬修正

§4 的事件体系**必须等早餐档有真实流量之后才能判早餐**。在那之前：
- 早餐相关的判据一律标 **"零样本，不可判定"**，不是"通过"；
- 若要提前验证，**最快的办法不是等自然流量，是做一次早餐档的定向灰度**（哪怕 20~30 条），
  否则 V1.3 定早餐口径时仍然只有仿真、没有行为。

---

#### (48) 与门禁脚本的交叉验证：**两套场景集，重合两格逐格相同**；以及一条门禁覆盖不到的缺口（2026-09-23）

team-lead 用 `backend/scripts/band_regression.py` 实跑 4.0 得「现状 64/27/68/81、补标后 77/32/78/90，8 格全过」，
与 §(44) 我的「4.0 补标后 0.93x 反向 ❌」看似冲突。核查结论：**不冲突，是两套场景集。**

##### 一、场景集对照

| 门禁 4 场景（`band_regression.py` L297-307） | 我的 4 场景 | 现状 / 补标后（他） | 现状 / 补标后（我） |
|---|---|---|---|
| 空偏好 | ↔ **P0 默认** | **64 / 77** | **64 / 77** ✅ |
| 荤菜x1 | ↔ **P3 昨天荤菜×1** | **27 / 32** | **27 / 32** ✅ |
| 有库存（{鸡蛋,土豆,青椒}） | — | 68 / 78 | （未跑） |
| prefer_fridge | — | 81 / 90 | （未跑） |
| — | P1 spice=1 | （未跑） | 102 / 174 |
| — | **P5 昨天主食×2 + spice=1** | （未跑） | 62 / **132** |

⇒ **四个重合数字逐格相同** ⇒ 两套脚本同口径、互相印证可信。
⇒ 这正是 §(45) 那条纪律的实例：**两组数并列，先问是不是同一口径**。这次答案是"同一口径、不同场景集"。

##### 二、我的 ❌ 挂在**效果指标**，band 与品类数都不红

§(44) 补标后 4.0：最差真带 **32**（≥ 门禁下限 18、≥ `POOL_MIN` 8）、最差品类 **5**（≥ `BREAKFAST_MIN_CATEGORIES` 4）—— **两列全绿**；
唯一的 ❌ 在「最差倍数 **0.93x 反向**」—— 那是**效果指标**（主面倍数）。

⇒ 按 **AC-3（先看带内道数与品类数，再看效果指标）**，**4.0 判过**。与 team-lead 裁定一致。

##### 三、⚠️ 但有一条真实缺口：**0.93x 反向，门禁永远看不见**

**它只出现在 P5（昨天主食×2 + spice=1），而 P5 不在门禁的 4 个场景里。**

而 P5 是本轮抓出问题最多的场景：
- **A 的真带 7 < `POOL_MIN`** —— 只有 P5 抓得到（空偏好 23 / 荤菜x1 18 / 有库存、prefer_fridge 均全绿）；
- **4.0 的 0.93x 反向** —— 同样只有 P5 抓得到。

⇒ **建议把「昨天主食×2 + spice=1」加进 `BREAKFAST_SCENARIOS`。**
按 AC-3 它排第二、不判红 —— 但**"连看都看不到"和"看了判定不红"是两回事**：
现在 4.0 的效果反向根本不会出现在门禁输出里，哪天有人问"早餐怎么不出主食了"，门禁日志查不到。

##### 四、5.5 被否：性质澄清 + 一条给 V1.3 的规矩

- 我那个 5.5 是**场景层封顶**（`min(slot+cat+quick, CAP)`，新构造），**不是 `SOFT_PREFERENCE_CAP`**；
- 静态约束 `SOFT_PREFERENCE_CAP <= random_band` 判它越界**成立**（5.5 > 5.0）；
  且 `decision_service.py` 注释「封顶 5.0 = 随机 band 时**零余量**」比约束本身更硬 —— **5.5 比零余量还糟**，接受否决、不需补跑；
- ⇒ **给 V1.3 的规矩**：将来引入任何新的封顶常量，**必须登记进 `static_const_check`** ——
  新常量不登记就是新盲区（门禁注释自己就是这么写的）。5.5 这次是侥幸在裁定前被拦下的。

---

*报告完*
