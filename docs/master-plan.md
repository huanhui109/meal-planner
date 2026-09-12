# 每周鲜 · AI 营养菜谱 —— 全项目总案（Master Plan）

> 本文是项目的**唯一总案**：模块结构与规划、已开发需求 × 版本台账、实现与规划的差异对齐、
> 路线图，以及 TAPD 项目管理落地映射。结构与依赖的取证细节见姊妹文档
> [`docs/project-audit.md`](project-audit.md)（项目审计）。
>
> | 项 | 值 |
> |---|---|
> | 代码库 | `/Users/jason/Documents/project/meal-planner` |
> | TAPD 项目 | workspace_id `43478791` |
> | TAPD 链接 | https://www.tapd.cn/tapd_fe/43478791/story/list |
> | 基线版本 | `0.4.0`（`pyproject.toml`） |
> | 基线提交 | `4318890` @ 2026-09-10 23:00 |

---

## 一、项目定位与现状

**每周鲜 · AI 营养菜谱** —— 把一周吃饭这件事交给 AI 排好：
偏好即约束 → 生成周菜单 → 校验营养预算 → 补单 → 做饭扣库存，形成闭环。

一套后端，三个交付面：**H5**、**微信小程序**、**飞书机器人**（自动化触达）。

| 维度 | 现状 |
|---|---|
| 后端 | Python 3.12 / FastAPI / SQLAlchemy 2.0 async / MySQL 8.0 / Alembic；`backend/app` ≈ 9,427 行，9 个包，44 个 API 端点，25 个服务，20 张表 |
| H5 | React 18 + Vite 6 + TypeScript + Ant Design 5；6 个页面，3 个 Zustand store |
| 小程序 | Taro 4.2 + React 18 + SCSS；6 个页面 + 自定义胶囊 TabBar |
| 共享层 | `shared/` 8 个纯 TS 模块，两端唯一真源 |
| 质量 | 后端测试 375（unit 253 / integration 121 / e2e 1）；前端 vitest 47；`make ci` 七道门禁 |
| 数据库 | 20 张表，7 个 Alembic 迁移（`0001_init` → `0007_menu_source`） |
| 部署 | nginx + systemd + certbot；本地一键 `scripts/setup_local.sh` + `make ops` 运维台 |

---

## 二、模块结构重梳理与规划

### 2.1 分层与依赖方向（已确立，作为架构约束）

```
交付面    H5 端           微信小程序        飞书机器人
             │                 │                │
共享层    shared/ 纯 TS（类型 · 格式化 · 下一步规则 · 设计令牌）—— 仅两端复用
             │                 │                │
接入层    nginx 443 → FastAPI 路由（44 端点）· JWT 会话（httpOnly Cookie / Bearer）
             │
业务层    生成流水线 │ 采购与库存 │ 今日聚合 │ 自动化推送
             │
支撑层    MySQL 19 表 │ LLM 降级链 │ 生成 Worker │ APScheduler
```

**依赖方向约定（硬约束）**

- `api → services → models`，禁止 `models → services` 反向依赖；
- `services → llm`；`bot → services`；跨模块只能经 service 层，禁止直接跨包访问 ORM 会话；
- `shared/` 只被 `frontend` 与 `miniapp` 引用，**零框架依赖、不反向依赖任何后端概念**；
- `scraper_service` / `matching_service` / `product_service` 为二期占位，**不得接入现有链路**。

### 2.2 模块职责矩阵（后端）

| 模块 | 层级 | 职责边界 | 不进这里的东西 |
|---|---|---|---|
| `api/` | 接入 | 路由、鉴权依赖注入、请求/响应编排 | 业务规则、SQL |
| `services/` | 业务 | 领域规则与编排（生成、采购、库存、营养、预算、多样性、定价、外卖、今日、视觉） | HTTP 细节 |
| `models/` | 数据 | 表结构、索引、关系 | 业务判断 |
| `schemas/` | 契约 | Pydantic 入参出参与序列化 | 查询逻辑 |
| `auth/` | 横切 | JWT 签发校验、飞书 / 微信 OAuth | 用户业务数据 |
| `llm/` | 横切 | 降级链、prompt 调用、demo 降级 | 落库 |
| `scheduler/` | 横切 | 任务注册、跨 worker 抢锁 | 推送内容拼装（在 `bot/`） |
| `bot/` | 触达 | 事件回调安全、指令解析、卡片渲染 | 定时策略 |
| `utils/` | 横切 | 结构化日志等无状态工具 | 领域概念 |

### 2.3 模块规划（本次重梳理新增的边界与约定）

| # | 规划项 | 内容 | 落点 |
|---|---|---|---|
| P1 | 契约单一化 | 前端类型全部来自 `shared/types.ts`，禁止在页面里另写一套接口类型 | 已基本达成，V2.1 加 lint 校验 |
| P2 | 令牌单一真源 | 设计令牌只允许从 `shared/tokens.ts` 生成，CI `--check` 阻断漂移 | 已达成 |
| P3 | 版本号统一 | `pyproject.toml`(0.3.0) 与 `frontend`/`miniapp`/`shared`(0.2.0) 口径不一致 → 统一为产品版本 | **待办（V2.1）** |
| P4 | 文档表数统一 | `architecture.md` 的「18 表」与实际 19 表不符 → 本次已修正 | 本次完成 |
| P5 | 二期隔离 | 占位服务加 `# 二期` 标注并禁止被 import | 已达成（docstring 标注），V2.1 加 import 检查 |
| P6 | 覆盖率门禁 | `make ci` 目前只跑测试不卡覆盖率阈值 | **待办（V2.1）** |
| P7 | 可观测性 | 仅有 structlog，无请求级 trace / 指标 | **待办（V2.1）** |

---

## 三、已开发需求 × 版本台账

> 版本口径：**V1.0** = 多用户闭环与本地部署；**V1.1** = 多端与共享层；**V2.0** = 今日页 / 补单 / 自动化 / 拍照识别 / 撤销。
> 「证据」列为代码库内的可验证落点。

### V1.0 —— 基础闭环（提交 `09b8fc7`）

| 需求 ID | 需求 | 模块 | 证据 |
|---|---|---|---|
| R-01 | 飞书扫码登录（网页应用形态，PC 二维码 / 手机唤起），httpOnly Cookie 会话（access 2h / refresh 30d） | 认证 | `app/auth/feishu_oauth.py`、`app/auth/tokens.py`、`api/auth.py` |
| R-02 | 多用户数据隔离：全部查询按登录用户过滤，越权返回 404 | 平台 | `app/dependencies.py`、各 service 的 `user_id` 过滤 |
| R-03 | 本地一键部署与运维台（MySQL 独立实例、建库建表、种子数据、启停/日志/自检） | 工程 | `scripts/setup_local.sh`、`scripts/service.sh`、`scripts/mysql_local.sh`、`Makefile` |

### V1.1 —— 多端与共享层（提交 `05bf213`）

| 需求 ID | 需求 | 模块 | 证据 |
|---|---|---|---|
| R-04 | 微信小程序端（Taro 4 + React），功能与 H5 完全一致 | 小程序 | `miniapp/`、`docs/miniapp-setup.md` |
| R-05 | `shared/` 共享层：类型 / 格式化 / 下一步规则 / 设计令牌，两端零漂移 | 共享层 | `shared/*.ts`、`scripts/gen_tokens.mjs` |
| R-06 | 微信小程序一键登录，自动建号；`wechat:` 身份命名空间，与飞书账号并存不绑定 | 认证 | `app/auth/wechat_oauth.py`、`UserService.upsert_from_wechat` |
| R-07 | 小程序 UI 适配 / 功能 / API 兼容缺陷修复（9 项） | 小程序 | `docs/miniapp-qa-report.md` |

### V2.0 —— 功能闭环（提交 `0e509e5` / `c96c458` / `0128742` / `4318890`）

| 需求 ID | 需求 | 模块 | 证据 |
|---|---|---|---|
| R-08 | 智能菜谱生成：异步任务（`202 + task_id`，前端轮询可关页面）；同周草稿复用；配额分两档（首生成 3/日、重生成 10/日，互不占用） | 生成 | `services/generation_service.py`、`models/menu.py`、迁移 `0005` |
| R-09 | 营养均衡校验：按日汇总热量与三大营养素供能比，偏差写告警 | 校验 | `services/nutrition_service.py` |
| R-10 | 预算控制：按 `ingredient.reference_price` 真实计价，超支告警不阻断；未定价项计入 `unpriced_items` | 校验 | `services/budget_service.py`、`services/pricing_service.py` |
| R-11 | 多样性控制：与近 4 周历史做 Jaccard 比对，冲突自动重生成一次 | 校验 | `services/diversity_service.py` |
| R-12 | 过敏源防线：命中过敏源的菜品落库前剔除并写告警 | 校验 | `api/menus.py`、`services/menu_service.py` |
| R-13 | 周菜单可视化编辑：7 天 × 餐次卡片，换一道 / 锁定 / 解锁 / 标记已做；锁定餐次不被重生成覆盖 | 菜单 | `services/menu_service.py`、`frontend/src/pages/Menus/WeeklyView.tsx` |
| R-14 | 采购清单：菜单所需 vs 冰箱库存差集（含缺口与单位换算），一键复制 | 采购 | `services/shopping_service.py` |
| R-15 | 库存闭环：标记已做 → 临期优先扣减 → 写 `consumption_record`；缺料不阻断并返回明细 | 库存 | `services/inventory_service.py`、迁移 `0002` / `0004` |
| R-16 | 今日页聚合：`GET /api/today` 一次返回预算 / 餐次 / 缺口 / 补单 / 自做外卖 / 临期 / 时间线，任一缺失不整页失败 | 聚合 | `api/today.py`、`services/today_service.py`、迁移 `0003` |
| R-17 | 补单决策：缺口估算合计，不够起送价时从本周缺料凑单，给 deeplink | 采购 | `services/order_service.py`、`services/deeplink_service.py` |
| R-18 | 自做 vs 外卖：自做价取菜单成本、外卖价取用户参考价，结论分三档并说明预算占用 | 决策 | `services/takeout_service.py`、`POST /api/today/takeout-price` |
| R-19 | 拍照识别入库：拍照 → 视觉大模型 → 候选可编辑 → 确认入库；限流 + 未配置时降级手动添加 | 库存 | `services/vision_service.py`、`api/inventory.py` |
| R-20 | 可撤销：换一道（换回上一道）、标记已做（回滚库存与消耗流水） | 交互 | `DELETE /api/menus/{id}/items/{item_id}/cooked`、`frontend/src/lib/undo.tsx` |
| R-21 | 飞书机器人：事件回调（签名校验 + AES 解密 + `event_id` 去重 + 1s 内响应）；指令「菜单 / 库存 / 添加库存 / 完成某餐 / 帮助」；定时推送（默认关闭，多 worker `GET_LOCK` 只推一次） | 自动化 | `app/bot/*`、`app/scheduler/*` |
| R-22 | 飞书凭证自助配置：按用户存 App ID/Secret/接收人，Secret 加密入库、只回掩码、可发测试消息 | 自动化 | `models/user_feishu_config.py`、`services/feishu_config_service.py`、`services/secret_box.py`、迁移 `0006` |
| R-23 | 自动化状态卡：如实显示飞书连接 / 调度开关 / 下次运行 / 最近推送 | 自动化 | `GET /api/automation/status`、`frontend/src/pages/Me/FeishuConfigCard.tsx` |
| R-24 | 4 Tab 信息架构 + 响应式 H5（Bento 首页、悬浮胶囊 TabBar、桌面左导航 + 我的抽屉） | 前端 | `frontend/src/App.tsx`、`components/Layout.tsx`、`MeSheet.tsx` |
| R-25 | 设计系统：令牌单一真源、语义色纪律、两端零漂移 | 设计 | `shared/tokens.ts`、`docs/design-system.md`、`make check-tokens` |
| R-26 | 品牌：命名「每周鲜」+ Logo 矢量源与两端交付物（脚本生成） | 品牌 | `shared/brand.ts`、`scripts/gen_logo.mjs`、`assets/logo/*` |
| R-27 | 部署与上线：nginx / systemd / certbot + MySQL 初始化，Alembic 为唯一建表入口 | 工程 | `deploy/*`、`deploy/README.md`、`docs/deployment.md` |
| R-28 | CI 质量门禁：ruff + pytest + 令牌校验 + Logo 校验 + vitest + 两端构建 | 工程 | `Makefile` 的 `ci` 目标 |

### V2.1 —— 体验与稳定（进行中，提交 `01b9111`）

| 需求 ID | 需求 | 模块 | 证据 |
|---|---|---|---|
| R-29 | 换一道本地优先：点一下自动换 —— 先按当前菜单设定（热量贴合 / 库存命中 / 偏好菜系打分，硬过滤过敏源、忌口、超烹饪时长、本周与近 4 周重复）从本地 `recipe` 表挑一道；无候选再同步调 AI 生成单菜并落库；两条路径都替换同一餐次，响应 `replacement.source` 标注 `local` / `ai`。AI 路径才写 `is_regeneration` 任务（与「重新生成」共用额度），传 `recipe_id` 可直接「换回上一道」且不占额度 | 菜单 | `services/replacement_service.py`、`config/prompts/dish_replacement.txt`、`api/menus.py` |
| R-30 | 换一道交互改造：弹框由「手输菜名 + 热量/时长/做法」改为「加载中 → 新菜名 + 来源 + 就它了 / 换回上一道」，H5 保留 5 秒 Toast 撤销，小程序在弹框内提供撤销 | 交互 | `miniapp/src/lib/meal-actions.ts`、`frontend/src/pages/Menus/WeeklyView.tsx` |

### V2.3 —— 菜谱库与本地优先生成（进行中，分支 `feat/recipe-library`，版本 `0.4.0`）

> 把 V2.1 单菜维度的「换一道本地优先」扩展到**整周生成**：本地菜谱库先行，AI 只补缺口。
> 需求全文见 [`docs/requirements-v2.3.md`](requirements-v2.3.md)。

| 需求 ID | 需求 | 模块 | 证据 |
|---|---|---|---|
| R-31 | 数据库结构与字段说明文档：由数据库反向生成，覆盖全部表 / 索引 / 外键 / 枚举 / 字段含义，支持 `--check` 防漂移 | 工程 | `scripts/gen_db_doc.py`、`docs/database.md`（20 表）、`Makefile` `db-doc` |
| R-32 | 开源菜谱导入与可执行 SQL：采集 proj.kitchen（MIT）+ HowToCook（Unlicense），归一化脏食材名、按菜名合并去重，产出外键安全、**幂等**可重复执行的种子 SQL | 数据 | `scripts/import_recipes/*`、`data/sql/recipes_seed.sql`、`scripts/backfill_recipe_nutrition.py` |
| R-33 | 本地优先菜单生成与 AI 兜底：整周逐格按打分（热量 50 / 库存 30 / 菜系 20）编排，硬过滤过敏源/忌口/超时长/重复；填充率达标即 `source=local`，不足则携带候选短名单交给 LLM（`source=mixed`）；`mode=ai` 完全跳过本地（`source=ai`） | 菜单 | `services/generation_service.py`、`schemas/recipe.py`、`api/menus.py`、迁移 `0007_menu_source.py`、`models/menu.py` |
| R-34 | 小程序来源标注与 AI 换一道入口：两端展示来源 chip（本地 / 本地+AI / AI）；「换一道」改 action sheet，本地换来的结果额外提供「让 AI 再换一道」（`force_ai=true`）与「换回上一道」 | 交互 | `shared/types.ts`、`miniapp/src/lib/{api,menu,meal-actions}.ts`、`miniapp/src/pages/menu/index.tsx`、`frontend/src/api/menu.ts`、`frontend/src/pages/Menus/WeeklyView.tsx` |

### 需求汇总

| 版本 | 需求数 | 状态 |
|---|---|---|
| V1.0 | 3 | 已完成 |
| V1.1 | 4 | 已完成 |
| V2.0 | 21 | 已完成 |
| V2.1 | 2 | 进行中（R-29 / R-30 已落地） |
| V2.3 | 4 | 进行中（R-31 ~ R-34 已落地） |
| **合计** | **34** | V2.0 及以前全部完成 |

---

## 四、现有实现与规划的差异对齐

| # | 规划 / 文档声称 | 现有实现 | 差异性质 | 处置 |
|---|---|---|---|---|
| D1 | 二期小象超市采集（Playwright 登录态、商品库、价格快照、食材-商品匹配） | 三个服务为占位，未接入任何链路 | **规划未实现** | 归入 V3.0；V2.1 起加「占位服务不得被 import」的静态检查 |
| D2 | 补单/外卖使用**实价** | 用 `ingredient.reference_price` 估算 + 用户参考价（默认 ¥26） | 设计内取舍 | 已在界面标注「参考价」；V3.0 用采集价替换 |
| D3 | 定时推送可用 | 默认 `scheduler.enabled=false`，多 worker 需单进程开启 | 部署约束 | V2.1 补「单 worker 调度」部署预设与自检 |
| D4 | 暗色主题 | 令牌预留但未启用 | 规划未启用 | V2.2 评估 |
| D5 | 法定节假日与调休表 | 推送简化为「周末不推送」 | 范围裁剪 | 明确不做；如需再评估 |
| D6 | 小程序适配与兼容 | 仅静态走查 + 构建级验证，未真机/多基础库实测 | **验证缺口** | V2.1 真机回归 |
| D7 | 移动端硬指标（对比度 ≥4.5:1、触摸目标 ≥44px、SE 无遮挡） | 代码已按规范写，未做抽查 | **验证缺口** | V2.1 抽查并出报告 |
| D8 | 文档口径：数据表数 | `architecture.md` 写「18 表」，实际 19 张（含 `user_feishu_config`） | **文档漂移** | 本次已修正为 19 表 |
| D9 | 版本号口径 | `pyproject.toml` = 0.3.0；`frontend` / `miniapp` / `shared` = 0.2.0 | **口径不一致** | V2.1 统一为产品版本（改动 `package.json` 与 lock 文件，需显式确认） |
| D10 | 覆盖率 | `make ci` 跑测试但不卡阈值（`make test-cov` 仅本地用） | 门禁缺口 | V2.1 加阈值 |
| D11 | 可观测性 | 仅 structlog 结构化日志 | 能力缺口 | V2.1 加请求级 trace |
| D12 | SSE 流式输出 / 支付 / 多语言 | 未实现 | 明确不做 | 保持范围外 |

---

## 五、路线图

### V2.1 —— 体验与稳定（第 1–2 周）

**目标**：把 V2.0 的闭环做「顺手且稳」。

- 换一道本地优先 + AI 降级（R-29 / R-30，已落地 `01b9111`）
- 小程序真机 + 多基础库回归，补齐 D6 的验证缺口
- 移动端硬指标抽查（对比度、触摸目标、SE / Pro Max / 桌面 1440px），输出报告
- 错误分级统一：Skeleton → 动作内 loading → ErrorState + 重试，禁止堆栈外露
- CI 加覆盖率阈值（D10）
- 请求级 trace 与关键路径耗时打点（D11）
- 版本号口径统一（D9）、占位服务 import 静态检查（D1）
- 生产部署预设：单 worker 调度开启 + 自检项（D3）

**验收**：`make ci` 全绿且带覆盖率阈值；真机回归报告无 P0/P1；硬指标抽查全部达标。

### V2.2 —— 数据与智能（第 3–5 周）

**目标**：让结果更准、更省心。

- 视觉识别准确率优化 + 限流策略分层（按用户/按日）
- 菜单口味学习：从「换一道 / 标记已做」行为反推偏好，回写 `diet_preference`
- 预算与营养个性化：按家庭人数与目标动态给出额度建议
- 多周菜单：支持连续两周排布与滚动复用
- 暗色主题评估（D4，令牌已预留）

**验收**：口味学习有可解释的推荐命中率指标；多周菜单无状态串扰。

### V2.3 —— 菜谱库与本地优先生成（第 5–6 周）

**目标**：让「一周吃什么」不再每次都求模型，本地能拼就本地拼。

- 菜谱库：两源采集 + 归一化 + 幂等 SQL + 落库（R-31 / R-32）
- 整周本地优先编排 + AI 兜底 + `mode` 三态（R-33）
- 两端来源标注与「让 AI 再换一道」入口（R-34）
- 营养回填策略：有 Key 走 LLM，无 Key 记录「跳过」并保证 AI 兜底可用

**验收**：`make ci` 全绿；本地够满时零模型调用；重复执行种子 SQL 行数不翻倍。

### V3.0 —— 二期数据源（第 6–9 周）

**目标**：把「估算」换成「实价」。

- 小象超市采集：Playwright 登录态、商品库、价格快照、食材-商品匹配
- 用实价替换补单估算价与外卖参考价（D2）
- 新表与迁移（商品库 / 价格快照 / 映射），采集与主链路隔离降级

**验收**：采集失败时主链路自动回落到参考价，用户无感；匹配准确率达标。

### 明确不做

微信 / 支付宝支付、多语言、SSE 流式输出、法定节假日与调休表、社区与积分、多平台比价。

---

## 六、TAPD 项目管理落地映射

### 6.1 迭代（8 个）

| 迭代名 | 对应版本 | 状态 |
|---|---|---|
| M1 基础闭环 | V1.0 | 已关闭 |
| M2 多端与共享层 | V1.1 | 已关闭 |
| M3 V2.0 功能闭环 | V2.0 | 已关闭 |
| M4 工程收口 | V2.0 | 已关闭 |
| V2.1 体验与稳定 | V2.1 | 开启 |
| V2.2 数据与智能 | V2.2 | 开启 |
| V2.3 菜谱库与本地优先生成 | V2.3 | 开启 |
| V3.0 二期数据源 | V3.0 | 开启 |

### 6.2 需求与任务

- **需求（Story）**：按第三章台账建 34 条，命名 `R-xx 需求名`，描述写入「版本 / 模块 / 证据 / 验收」，归属对应迭代。
- **任务（Task）**：每条需求拆 2–3 条任务，状态用 TAPD 的 `未开始 / 进行中 / 已完成`；已开发需求的任务直接置为已完成。

### 6.3 缺陷（Bug）

来自小程序 QA 报告的 9 条：U1–U4（适配）、F1–F2（功能 / 代码质量）、C1–C3（API 兼容）。均已修复 → 状态置为已解决/已关闭，保留记录以沉淀质量基线。

### 6.4 Wiki（3 篇）

1. **项目档案** —— 定位、技术栈、模块划分、数据模型（源：本文第一、二章）
2. **架构与依赖** —— 分层图、依赖方向约束、共享层单一真源、部署拓扑（源：`docs/architecture.md`）
3. **开发与管理流程** —— 环境搭建、质量门禁、迁移流程、测试策略、发布与上线（源：`docs/project-audit.md` 第七章）

### 6.5 看板列设计

TAPD 原生看板按需求状态列呈现：`规划中 → 开发中 → 待测试 → 已完成`。
历史 28 条需求落在「已完成」，V2.1/V2.2/V3.0 的需求落在「规划中」，随进度右移。

---

## 七、执行与治理

| 项 | 约定 |
|---|---|
| 分支 | `main` 单线；功能分支 `feat/<模块>-<短名>` |
| 提交 | 遵循 `feat|fix|docs|chore|refactor(scope): 说明`（现有历史已符合） |
| 数据库变更 | 唯一入口 `make migration MSG="..."` → 人工审阅 → `make migrate`；禁止手工建表 |
| 质量门禁 | 合并前必须 `make ci` 全绿 |
| 契约变更 | 接口变更必须同步 `shared/types.ts` 与 `shared/endpoints.ts`，并在 TAPD 需求上留痕 |
| 文档同步 | 架构 / 设计 / 产品三类文档随对应需求同期更新 |
| 发布 | 迁移先行 → 后端 → 前端 → 小程序审核；上线手册见 `deploy/README.md` |
| 项目追踪 | TAPD workspace `43478791`，需求关联迭代，缺陷关联需求 |
