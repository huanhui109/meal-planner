# 菜品数据设计 —— 从「今天吃啥」倒推字段

> 2026-09-23 · 迁移 0016 · 配套 `scripts/backfill_dish_scene_fields.py`
> 与 `app/services/recipe_enrich_service.py`

## 一、先问：决策到底需要什么

「饭决」的核心命题只有一句：**这一顿吃什么**。把用户脑子里过一遍的东西列出来，
就得到了字段清单——不是"菜谱库应该有什么字段"，而是"人在决定吃啥时会想什么"。

| 用户心里的念头 | 需要的字段 | 0016 之前 |
|---|---|---|
| 什么时候吃？早上别给我红烧肉 | `meal_slots` | ❌ 完全没有 |
| 多久能吃上？我赶时间 | `cook_minutes` | ⚠️ 有字段但 **93% 是 NULL** |
| 想吃点啥口味？清淡/辣/酸 | `flavor_tags` / `spice_level` | ✅ 0014 已有 |
| 想吃啥食材？今天想吃鱼 | `main_ingredient` / `meat_type` | ⚠️ 荤素靠菜名字符串猜 |
| 家里能做吗？没烤箱 | `tools` | ❌ 完全没有 |
| 会不会太腻/太重？ | `is_light` / `calories` | ✅ 0014 已有 |
| 这个季节合适吗？ | `season` | ❌ 完全没有 |
| 昨天吃过了没？ | `category` / `main_ingredient` | ✅ 0014 已有 |

结论很直白：**前两层（基础层、决策层）回答的是"好不好吃"，缺的是"合不合适"。**
早上 7 点推红烧肉、家里没烤箱推烤羊排，打分再准也是错的。

## 二、致命项：cook_minutes 缺 93%

这不是"数据不全"，是**硬规则失效**。`decision_service._from_recipe()` 里写的是：

```python
minutes=r.cook_minutes or 30,
```

396 道菜里 368 道没有耗时，于是全部按 30 分钟算。后果：

- `late_night_max_minutes`（深夜只出快手菜）→ 30 分钟一律超标 → 要么全过滤光、要么放宽到失效
- `cook_cap`（用户设定的出餐上限）→ 同理，等于没设
- 「换一个」时的放宽策略第一级就是松时间上限 → 松了个不存在的限制

**这是纯数据问题，不能等 LLM。** 先按规则补（`dish_rules.guess_minutes`），
补完 396/396 全覆盖，两条硬规则立刻恢复。

## 三、新增字段

| 字段 | 类型 | 语义 | 空值含义 |
|---|---|---|---|
| `meal_slots` | JSON 数组 | 适合餐次 `breakfast/lunch/dinner/late_night` | **不限制餐次**（不是"只适合晚餐"） |
| `meat_type` | 枚举 | `none/egg_dairy/poultry/red_meat/seafood/mixed` | 不知道（不是"素"） |
| `tools` | JSON 数组 | 所需厨具 `wok/steamer/oven/air_fryer/...` | 无特殊要求 |
| `season` | JSON 数组 | `spring/summer/autumn/winter` | 四季皆可 |
| `enrich_status` | 枚举 | `pending/partial/done/failed` | — |
| `enriched_at` | datetime | 最近一次富集时间 | — |
| `enrich_source` / `steps_source` | 枚举 | `seed/rule/llm/manual` | — |

**空值的语义是刻意设计的。** `meal_slots=NULL` 表示"不限制"而不是"只适合晚餐"，
`meat_type=NULL` 表示"不知道"而不是"素"——后者会让忌口用户吃到肉。宁可让规则
不生效，也不要生效成错的。

## 四、荤型：从"猜字符串"到"有明确字段"

以前 `intent_service._looks_like_meat()` 拿菜名+食材做字符串匹配，于是：

- 「鸡蛋」含「鸡」→ 判成荤 → 用户说"吃素"却连番茄炒蛋都吃不上
- 「鸡精」含「鸡」→ 判成肉
- 「牛奶」含「牛」→ 判成红肉 → 牛奶粥不能给素食者
- 「鱼香肉丝」→ 判成水产 → 明明是猪肉

前两个靠抠假阳性词打过补丁，但那只治了症状。**数据里就该有明确答案**，
所以加了 `meat_type`，判定顺序固定为：

```
水产 → 禽 → 红肉 → 蛋奶 → 素
```

顺序不能换：把「肉」这个兜底字放在红肉档、且排在禽之后，是因为"鸡肉/鸭肉"
必须先被禽接走；「鱼」要先抠掉假阳性（鱼香肉丝没有鱼）。每一档判之前都先
`_strip()` 掉对应的假阳性词。

## 五、模型分工：谁干什么活

这是本次最关键的定位调整。以前所有模型都往**决策链路**上堆，结果 2s 响应
守不住、离线双端同构也没法复现。现在彻底分开：

```
┌─ 实时决策（2s 内、可离线）────────────────────┐
│  Laya（开源 System One）                       │
│  职责：把一句口语变成结构化意图                │
│  一次前向传播 200ms，只有 choice/score/noul    │
│  绝不进打分排序                                │
└────────────────────────────────────────────────┘

┌─ 离线生产（凌晨跑、可失败、可重试）────────────┐
│  兜底大模型（FallbackChain：GLM → Qwen → ...）│
│  职责：                                        │
│    1. 补缺失字段（meal_slots/meat_type/...）   │
│    2. 写做菜步骤（steps + quick_steps）        │
│    3. 按缺口定向补新菜                         │
│  慢、花钱、输出不稳 —— 所以只生产数据，        │
│  不参与任何实时决策                            │
└────────────────────────────────────────────────┘
```

**这两者不是主备关系，是分工关系。** 模型只生产数据，规则只做决策。

### 三条硬纪律

1. **失败静默降级**：跑挂了最多是字段还缺着，绝不抛异常给调用方。
   LLM 不可用时退到规则层——规则是免费的、确定性的，先堵洞再说。
2. **输出必须校验后才落库**：LLM 会给 `spice_level=9`、给不存在的枚举值。
   `sanitize()` 白名单 + 范围校验，越界一律**丢弃**而不是截断（截断等于替模型编数据）。
   0 和 False 是有效值，不能被当成"缺失"（`0 == False` 这个坑在 intent_service 踩过）。
3. **人工校对过的不许覆盖**：`enrich_source=manual` 的菜直接跳过。

## 六、怎么用

```bash
# 看缺口（也是定时任务"要不要跑"的依据）
GET /api/recipes/gaps

# 手动跑一次（导入新菜后想立刻补齐时用，不用等凌晨）
POST /api/recipes/enrich?kind=fields&limit=20
POST /api/recipes/enrich?kind=steps
POST /api/recipes/enrich?kind=expand

# 查账
GET /api/recipes/enrich/logs

# 纯规则回填（不调模型，随时可跑）
make backfill-dish-scene ARGS="--dry-run"   # 预览
make backfill-dish-scene                    # 正式
```

定时任务：`scheduler.recipe_enrich = "03:30"`，凌晨跑，不占白天的决策响应。

## 七、当前数据健康度（回填后）

| 字段 | 回填前缺 | 回填后缺 | 剩余缺口谁来补 |
|---|---|---|---|
| `cook_minutes` | **368** | **0** | — |
| `meat_type` | 396 | 115 | LLM（规则判不了就留空） |
| `meal_slots` | 396 | 315 | LLM |
| `tools` | 396 | 324 | LLM |
| `season` | 396 | 366 | LLM |

规则剩下填不了的（`meal_slots` 315 道等）是因为菜名里确实看不出餐次——
按保守原则留空，等 LLM 来补，而不是瞎填。

## 八、文件

| 文件 | 职责 |
|---|---|
| `backend/alembic/versions/0016_dish_enrichment.py` | 场景字段 + `recipe_enrich_log` |
| `backend/app/models/recipe.py` | 字段 + `MeatType/CookTool/DishSeason/EnrichStatus/EnrichSource` 常量 |
| `backend/app/services/dish_rules.py` | 规则推断（脚本与服务共用同一份） |
| `backend/app/services/recipe_enrich_service.py` | 富集服务：校验 → 落库 → 记流水 |
| `backend/app/api/recipes.py` | `/gaps` `/enrich` `/enrich/logs` |
| `backend/app/scheduler/jobs.py` | `enrich_recipes()` 凌晨任务 |
| `scripts/backfill_dish_scene_fields.py` | 纯规则回填 |
