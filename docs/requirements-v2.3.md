# V2.3 需求说明 —— 菜谱库与本地优先生成

> | 项 | 值 |
> |---|---|
> | 版本 | `0.4.0` |
> | 分支 | `feat/recipe-library` |
> | 基线提交 | `61d6220`（建分支 + 版本号 + 数据库文档生成器） |
> | 承接 | V2.1「换一道本地优先」的单菜本地化（R-29 / R-30），本期把同一思路扩展到**整周生成** |
> | 总案 | [`docs/master-plan.md`](master-plan.md) |

---

## 一、背景

V2.0 的一周菜单完全由 LLM 现场生成：每次都要联网、要等待、要花额度，且结果不可复现、
无法离线。一旦模型不稳定或 Key 缺失，整条链路就空转。

而「一周吃什么」这件事，绝大多数菜品其实来自**稳定、可离线、可解释**的常见菜谱。
把它们沉淀成本地菜谱库，让**本地优先、AI 兜底**，可以同时拿到三个好处：

1. **省**：本地能拼齐就不调模型，直接省下模型成本与延迟；
2. **稳**：本地结果是确定性的，不受模型波动影响；
3. **可解释**：每道菜按「热量贴合 / 库存命中 / 偏好菜系」打分选出，能说清为什么是它。

V2.1 已经证明了单菜维度（R-29）可行，本期把它做成**整周维度的编排**，并补齐菜谱库的
采集、清洗、落库与来源标注。

---

## 二、目标

- **G1 菜谱库**：从两个开源数据源采集、清洗、合并、去重，产出**幂等可执行**的 SQL，
  一键落库，形成可复用的本地菜谱库。
- **G2 本地优先**：整周生成时先用本地库编排；拼得够满（默认 ≥80% 餐次）就直接落库，
  不调模型；不足时把**候选短名单**交给模型兜底。
- **G3 模式可控**：调用方可通过 `mode` 选择 `auto`（默认，本地优先+AI兜底）、
  `local`（显式偏好本地）、`ai`（纯模型）。
- **G4 来源可见**：菜单与「换一道」都标注来源（`local` / `mixed` / `ai`），
  用户知道这顿饭是本地挑的还是模型 generated。

---

## 三、功能点

### R-31 数据库结构与字段说明文档

| 项 | 内容 |
|---|---|
| 需求 | 由数据库**反向生成**结构说明文档，覆盖全部表、索引、外键、枚举与字段含义，并支持 `--check` 防漂移 |
| 价值 | 文档随 schema 走，杜绝「代码改了文档没改」的口径漂移（对应 V2.1 的 D8 类问题） |
| 证据 | `scripts/gen_db_doc.py`、`docs/database.md`（20 表 + Mermaid ER + 枚举）、`Makefile` 的 `db-doc` 目标 |
| 验收 | `make db-doc` 生成成功；`./scripts/gen_db_doc.py --check` 退出码 0（无漂移） |

### R-32 开源菜谱导入与可执行 SQL

| 项 | 内容 |
|---|---|
| 需求 | 采集 `proj.kitchen`（MIT）与 `HowToCook`（Unlicense）两源菜谱，归一化为统一模型，按菜名合并去重，产出**外键安全、可重复执行不产生重复行**的种子 SQL |
| 数据源 | proj.kitchen 结构化 JSON（含分类/难度/食材/步骤/小贴士）；HowToCook markdown（含用量、卡路里、烹饪时间、难度） |
| 关键设计 | ① 食材名称清洗（去用量/单位/备注/选项/厨具，拒绝说明性句子）；② `merge_records` 按菜名合并，proj.kitchen 优先、HowToCook 补营养与时间；③ SQL 幂等：`ingredient` 用 `INSERT IGNORE`，`recipe` 用 `WHERE NOT EXISTS`，`recipe_ingredient` 以「该菜谱尚无用量」为闸门 |
| 证据 | `scripts/import_recipes/{sources,normalize,build_sql,load_db,cli}.py`、`data/sql/recipes_seed.sql`、`scripts/backfill_recipe_nutrition.py` |
| 验收 | 生成 SQL 含 300+ 道菜谱；重复执行两次行数不翻倍；食材名无用量/单位混入；`make import-recipes` / 裸 SQL 落库后数量合理 |

### R-33 本地优先菜单生成与 AI 兜底

| 项 | 内容 |
|---|---|
| 需求 | 整周生成时先由本地菜谱库编排：7 天 × 每日餐次逐格挑菜，硬过滤过敏源/忌口/超时长/本周与近期重复，按打分择优；填充率达标即落库（`source=local`），不足则把候选短名单作为提示交给 LLM 兜底（`source=mixed`）；`mode=ai` 完全跳过本地（`source=ai`） |
| 打分口径 | 热量贴合 50 + 库存命中 30 + 偏好菜系 20（与「换一道」R-29 一致） |
| 关键设计 | ① `compose_from_local` 与 `persist(source=...)` 解耦；② 本地候选池要求 `calories / cook_minutes / steps` 非空且至少一个食材；③ 兜底时给模型的短名单长度上限 30；④ 硬约束（过敏源）始终保持红线 |
| 证据 | `backend/app/services/generation_service.py`（`MODE_*`、`compose_from_local`、`_pick_for_slot`、`_score_recipe`、`run`）、`backend/app/schemas/recipe.py`（`MenuGenerateRequest.mode`）、`backend/app/api/menus.py`、迁移 `0007_menu_source.py`、`backend/app/models/menu.py`（`menu.source`） |
| 验收 | 本地够满时**不调用模型**且 `menu.source=local`；本地不足时 `source=mixed` 且模型收到候选短名单；`mode=ai` 时本地编排零调用且 `source=ai`；`menu.source` 落库并在菜单详情中序列化输出 |

### R-34 小程序来源标注与 AI 换一道入口

| 项 | 内容 |
|---|---|
| 需求 | 两端界面展示菜单来源（本地菜谱库 / 本地+AI / AI 生成）；「换一道」改为 action sheet，本地换来的结果额外提供「让 AI 再换一道」（`force_ai=true`），并可「换回上一道」 |
| 交互 | 小程序 `Taro.showActionSheet`（就它了 / 让 AI 再换一道 / 换回上一道，第二项仅当来源为本地时出现）；H5 在替换弹框底部给出同款入口，「换回上一道」沿用 5 秒 Toast 撤销 |
| 证据 | `shared/types.ts`（`MenuSource` / `GenerationMode` / `MenuDetail.source`）、`miniapp/src/lib/{api,menu,meal-actions}.ts`、`miniapp/src/pages/menu/index.tsx`、`frontend/src/api/menu.ts`、`frontend/src/pages/Menus/WeeklyView.tsx` |
| 验收 | 菜单总览显示来源 chip；`source=mixed` 时给出「本地库不足」提示；本地来源的换一道结果出现「让 AI 再换一道」且点击后 `replacement.source=ai`；两端 `typecheck` 与 `build` 通过 |

---

## 四、数据与实现要点

### 4.1 采集与归一化

| 源 | 形态 | 贡献 |
|---|---|---|
| proj.kitchen | 结构化 JSON（`/api/recipes` 列表 + 详情） | 分类、难度、食材、步骤、小贴士 |
| HowToCook | GitHub 仓库 markdown（`## 计算` / `## 操作`） | 用量、卡路里、烹饪时间、难度，用于补齐 |

- 归一化 `normalize_amount` 把「200 克 / 2-3 个 / 适量」拆成「数量 + 单位」，`amount_text` 保留原文；
- 食材名清洗是本期重点之一：源数据 `name` 字段混入 `'肋排 ='`、`'里脊肉 200g'`、
  `'食用油（炸丸子用）500ml'` 等脏值，统一由 `_core_ingredient_name` + `_finalize_name` 收敛成名词短语，
  并拒绝说明性句子与厨具；
- 合并去重按菜名，`proj.kitchen` 为基底（结构更整齐），HowToCook 只补缺失字段，不覆盖已有值。

### 4.2 幂等落库

- `ingredient`：`INSERT IGNORE`（按 `name` 唯一）；
- `recipe`：`INSERT ... SELECT ... WHERE NOT EXISTS (SELECT 1 FROM recipe WHERE name = ...)`；
- `recipe_ingredient`：以「该菜谱尚无用量」为闸门，避免重复执行叠加；
- 实测：连续执行两次种子 SQL，`recipe` / `recipe_ingredient` 行数不翻倍。

### 4.3 营养回填策略

- 本地优先编排要求 `calories` 非空才可入选（`cook_minutes` / `steps` 同理）；
- `scripts/backfill_recipe_nutrition.py` 复用 LLM 降级链分批补 `calories / 蛋白 / 碳水 / 脂肪 / 时长`，
  **只填 NULL、不覆盖**，可中断重跑；
- 无 LLM Key 时脚本**记录为「跳过」**：本地编排只覆盖 HowToCook 自带卡路里的菜谱，
  本地库不足的部分自动走 AI 兜底，链路仍可用。

---

## 五、验收标准（DoD）

- [x] `docs/database.md` 由脚本生成且 `--check` 无漂移（R-31）
- [x] 两源合并生成 `data/sql/recipes_seed.sql`，落库后本地菜谱库可用（R-32）
- [x] 种子 SQL 幂等：重复执行不产生重复行（R-32）
- [x] 本地够满时整周生成不调模型，`menu.source=local`（R-33）
- [x] 本地不足时回落 AI 并携带候选短名单，`menu.source=mixed`（R-33）
- [x] `mode=ai` 跳过本地，`menu.source=ai`（R-33）
- [x] `menu.source` 落库并在菜单详情序列化（R-33）
- [x] 两端展示来源 chip，「换一道」提供「让 AI 再换一道」入口（R-34）
- [x] 新增单元测试（归一化 / SQL 生成 / 区间校验）与 MySQL 集成测试（本地优先三条路径）
- [x] `make ci` 全绿（ruff + pytest + 令牌/Logo 校验 + vitest + 两端构建）

---

## 六、风险与遗留

| 风险 | 处置 |
|---|---|
| HowToCook 少量 markdown 抓取失败（索引 369 / 实际 366） | 回退不影响主流程；需要时重跑 `make fetch-recipes` 补齐 |
| 无 LLM Key 时营养字段不全 | 已按「跳过」处理；本地编排仍覆盖带卡路里的菜谱，缺口走 AI 兜底 |
| 工作区含他人并行改动（`demo_client.py` 菜池、品牌位图等） | 提交时按文件白名单暂存，只提交本任务文件 |
| 本地候选池若长期不更新会「吃到腻」 | 打分层已含「本周与近 4 周重复」硬过滤；后续可在 V2.2 口味学习中继续优化 |
