# 每周鲜 · AI 营养菜谱 —— 项目审计与 TAPD 落地蓝图

> 本文由对本地仓库 `/Users/jason/Documents/project/meal-planner` 的全量代码走查产出，
> 覆盖：模块划分、依赖关系、业务流程、数据模型、开发与管理流程反写、历史进度还原、
> 新进度规划，以及可直接写入 TAPD 的落地清单。
>
> **规划与需求台账见总案 [`docs/master-plan.md`](master-plan.md)**（本文为其结构取证部分）。
>
> 审计基线：`main` 分支，最后提交 `4318890`（2026-09-10 23:00），版本 `0.3.0`。
> TAPD 项目：workspace_id `43478791`。

---

## 一、项目本体

| 项 | 内容 |
|---|---|
| 产品名 | 每周鲜 · AI 营养菜谱（短称「每周鲜」，副标「AI 营养菜谱」） |
| 工程名 / 版本 | `ai-meal-planner` / `0.3.0`（前端、小程序、shared 均为 `0.2.0`） |
| 一句话定位 | 把一周吃饭这件事交给 AI：偏好即约束 → 生成周菜单 → 校验营养预算 → 补单 → 做饭扣库存 |
| 交付形态 | 一套后端 + 三个交付面：H5、微信小程序、飞书机器人（自动化触达） |
| 代码规模 | 后端 `backend/app` ≈ 9,427 行 Python；前端 `frontend/src` ≈ 4,734 行 TS/TSX；另含 `miniapp/`、`shared/` |
| 质量基线 | 后端测试 225 项（unit 121 / integration 103 / e2e 1）、前端测试 47 项、Alembic 迁移 6 个、数据表 19 张 |
| 版本节奏 | V1（多用户闭环 + 本地一键部署）→ V2.0（今日页 / 补单 / 自动化 / 拍照识别） |
| 分支策略 | `main` 单线推进，6 个提交，作者 `think`，时间跨度 2026-09-10 15:59 → 23:00 |

---

## 二、目录结构与模块划分

### 2.1 顶层目录

| 目录 | 职责 | 关键内容 |
|---|---|---|
| `backend/` | 后端服务（FastAPI + SQLAlchemy async + Alembic） | `app/` 9 个包、`alembic/` 6 个迁移、`tests/` 225 项 |
| `frontend/` | H5 端（React 18 + Vite 6 + Ant Design 5） | 6 个页面、3 个 Zustand store、8 个 API 模块 |
| `miniapp/` | 微信小程序（Taro 4.2 + React 18 + SCSS） | 6 个页面 + 自定义 TabBar，功能与 H5 对齐 |
| `shared/` | 两端共享的纯 TS 层（零框架依赖） | 类型 / 格式化 / 下一步规则 / 设计令牌 / 品牌 / 接口路径 |
| `config/` | 运行时配置与 Prompt 模板 | `default.yaml`（app/db/auth/menu/scheduler/llm/feishu/wechat/platforms/scraping） |
| `deploy/` | 生产部署资产 | `nginx/`、`systemd/`、`mysql/`、`deploy.sh`、上线手册 `README.md` |
| `docs/` | 工程文档 | 架构、设计系统、本地部署、部署、飞书配置、小程序配置、产品 V2、QA 报告 |
| `scripts/` | 运维与生成脚本 | `setup_local.sh`、`service.sh`、`mysql_local.sh`、`seed_data.py`、`backup_db.py`、`gen_tokens.mjs`、`gen_logo.mjs` |
| `assets/` | 品牌矢量源 | `logo/` 4 个 SVG + PNG，几何由脚本生成 |
| `logs/` / `data/` | 运行期产物（git 忽略） | 服务日志与 PID、数据目录 |

### 2.2 后端分层（`backend/app`）

```
api/ ──► services/ ──► models/ + database.py
 │            │
 │            └──► llm/ (降级链)
 ├──► auth/  (JWT + 飞书 OAuth + 微信 OAuth)
 └──► schemas/ (Pydantic 请求/响应)
scheduler/ ──► services/    bot/ ──► services/
```

| 包 | 文件数 | 职责 |
|---|---|---|
| `api/` | 9 | 路由层：`auth` `preferences` `menus` `today` `inventory` `products` `automation` + `router` 汇总，共 **44 个端点** |
| `services/` | 25 | 业务层：菜单、生成流水线、库存、采购、营养、预算、多样性、定价、配方、外卖、补单、今日聚合、视觉识别、加密箱、飞书配置、自动化等 |
| `models/` | 15 | ORM 定义，映射 **19 张表**（含 `base.py` 的时间戳混入） |
| `schemas/` | 8 | Pydantic 模型与序列化（`serializers.py` 统一出参） |
| `auth/` | 3 | 自签 JWT（`tokens.py`）、飞书 OAuth、微信小程序 OAuth |
| `llm/` | 5 | `base` 抽象 + `openai_client` + `fallback_chain`（GLM-4 → Qwen-Max → DeepSeek）+ `local_client` + `demo_client` |
| `scheduler/` | 3 | `scheduler_manager` 生命周期 + `jobs` 任务 + `scheduler_lock`（MySQL `GET_LOCK` 抢锁） |
| `bot/` | 5 | 飞书事件回调：`webhook_routes` / `webhook_security`（签名 + AES 解密 + 去重）/ `command_handler` / `card_builder` / `feishu_client` |
| `utils/` | 1 | 结构化日志（structlog） |
| 根级 | 5 | `main.py`（lifespan 装配）、`config.py`、`database.py`、`dependencies.py`（`get_current_user`） |

### 2.3 前端（`frontend/src`）

- `pages/`：`Today/`（今日页，V2 主入口）、`Menus/`（`WeeklyView` + `ShoppingList`）、`Inventory/`、`Preferences/`（5 个子表单 + 索引）、`Me/`（抽屉 + `FeishuConfigCard`）、`Login.tsx`
- `stores/`：`useAppStore`、`usePreferenceStore`、`useGenerationStore`（生成状态全局化，切页不中断轮询）
- `api/`：`client` `auth` `today` `menu` `inventory` `preferences` `automation`
- `components/`：`Layout`、`MeSheet`、`RecognizePanel`、`ui/`（设计系统组件）
- `lib/undo.tsx`、`hooks/useMenuGeneration.ts`、`styles/tokens.css`（脚本生成）

### 2.4 小程序（`miniapp/src`）

- `pages/`：`today` `menu` `shopping` `fridge` `profile` `login` + `custom-tab-bar/`（悬浮毛玻璃胶囊）
- `lib/`：`api` `request` `session` `deeplink` `nav` `menu` `meal-actions` `config` `logo`
- `components/`：`ui/index.tsx`、`ui/form.tsx`、`recognize-sheet.tsx`、`automation-card.tsx`

### 2.5 共享层（`shared/`，8 个模块）

| 文件 | 内容 |
|---|---|
| `types.ts` | 全部接口类型（含 `ApiEnvelope`） |
| `format.ts` | 金额 / 数量 / 热量 / 日期 / 进度的统一格式化 |
| `labels.ts` | 周几、餐次、品类、状态的中文文案 |
| `next-step.ts` | 「下一步该做什么」决策函数（两端同源） |
| `today.ts` | 今日页展示映射：时间线三态、补单文案、外卖结论、预算百分比 |
| `brand.ts` | 品牌名 / 副标 / 本地数据说明，两端唯一文案源 |
| `endpoints.ts` | 接口路径常量 |
| `tokens.ts` | 设计令牌唯一真源，脚本生成两端样式 |

---

## 三、依赖关系

### 3.1 后端运行时依赖（`pyproject.toml` → `requires-python >=3.11`）

| 依赖 | 用途 |
|---|---|
| `fastapi` / `uvicorn[standard]` | Web 框架与 ASGI 服务 |
| `sqlalchemy[asyncio]` / `aiomysql` / `cryptography` | 异步 ORM 与 MySQL 驱动（`caching_sha2_password` 需要） |
| `alembic` | 数据库迁移唯一入口 |
| `pydantic` / `pydantic-settings` / `pyyaml` | 配置与校验 |
| `pyjwt` | 自签 JWT 会话 |
| `structlog` | 结构化日志 |
| `openai` | LLM 统一 SDK（兼容 GLM / Qwen / DeepSeek） |
| `apscheduler` | 定时推送 |
| `httpx` | 出网 HTTP |
| `lark-oapi` | 飞书开放平台 SDK |
| `python-dotenv` / `python-multipart` | 环境变量与文件上传 |
| `pillow` | 拍照识别前的等比缩放 |
| **可选** `pytest*` / `ruff`（dev）、`asyncmy`（performance）、`playwright`（scraping，二期） | — |

### 3.2 前端与小程序依赖

- 前端：`react` / `react-dom` 18、`react-router-dom` 7、`antd` 5 + `@ant-design/icons` + `@ant-design/pro-components`、`@tanstack/react-query` 5、`zustand` 5、`axios`、`dayjs`；构建 `vite` 6 + `typescript` 5.6 + `vitest` 2。
- 小程序：`@tarojs/*` 4.2.1 全家桶 + `react` 18 + `sass` + `webpack` 5（自研轻组件，不引 UI 库）。
- **两端都通过 alias 引用 `shared/`**：H5 走 Vite alias，小程序走 Taro alias + `mini.compile.include`。

### 3.3 构建期依赖（单一真源）

- `scripts/gen_tokens.mjs`：`shared/tokens.ts` → `frontend/src/styles/tokens.css` + `miniapp/src/styles/_tokens.scss`
- `scripts/gen_logo.mjs`：几何 → `assets/logo/*.svg` + 两端品牌资源
- `make ci` 会以 `--check` 运行两者，生成物漂移即失败。

### 3.4 依赖方向约定

`api → services → models`，`services → llm`，`bot → services`；`shared` 只被两端引用、不反向依赖任何框架。
`scraper_service` / `matching_service` / `product_service` 为二期占位，未接入任何链路。

---

## 四、核心业务流程

### 4.1 生成闭环（异步任务）

```
POST /api/menus/generate
  ├─ 同周已有 draft/confirmed 且 force=false → 直接复用（不耗额度）
  ├─ 按当日 menu_generation_task 计数，超限 → 429（首生成 3/日、重新生成 10/日，互不占用）
  └─ 写 pending 任务 → 立即返回 202 + task_id（前端 2.5s 轮询，可关页面）
GenerationWorker（进程内并发 2）
  ├─ _claim(): SELECT ... FOR UPDATE SKIP LOCKED 抢占 → running
  ├─ 启动时 recover_stale_tasks() 把超时 running 扫回 failed
  ├─ LLM 调用不持有数据库连接；一次生成调一次，多样性不达标再补一次
  └─ 落库 recipe + recipe_ingredient（数量归一化，原文存 amount_text）
       → menu_item.estimated_cost = Σ(数量 × reference_price)
       → 营养 / 预算 / 多样性校验；命中过敏源的菜品直接剔除并写 warnings
```

### 4.2 编辑与撤销

- 换一道 / 锁定 / 解锁 / 标记已做；**锁定餐次在重新生成时保留，不被覆盖**。
- 可撤销优先于二次确认：换一道、标记已做均给「后悔窗口」，撤销会真实回滚库存与消耗流水。

### 4.3 采购与补单

- `GET /api/menus/{id}/shopping-list`：菜单所需 vs 冰箱库存的差集（含缺口与单位换算）。
- `GET /api/menus/{id}/order-suggestion`：缺口按 `reference_price` 估算，不够起送价时从「本周迟早要买」的缺料凑单，给出 deeplink。
- **不依赖爬虫**：价格用 `ingredient.reference_price` 估算，外卖价用用户参考价（默认 ¥26）。

### 4.4 库存闭环

标记已做 → 按 `recipe_ingredient` 扣减 `fridge_inventory`（临期优先）→ 写 `consumption_record`；
缺料不阻断并返回 `missing` 明细。撤销（`DELETE .../cooked`）反向执行：批次行还在就加回原行，
已被扣空删除的按流水里的 `ingredient_id`/`unit` 重建，然后删掉这批流水。

### 4.5 今日聚合（一次请求拿全）

`GET /api/today` 返回今日预算、餐次、采购缺口、补单建议、自做 vs 外卖对比、临期食材、今日自动流程时间线；
**任何一块缺失都不让整页失败**（无菜单则返回 `ready.has_menu=false`，由前端渲染空状态）。

### 4.6 自动化（飞书 Bot + 定时）

- 事件回调：签名校验 + AES 解密 + `event_id` 去重 + 1 秒内响应；指令「菜单 / 库存 / 添加库存 / 完成某餐 / 帮助」直接查库回复。
- 定时推送：菜单、缺料与临期提醒，**默认关闭**；多 worker 用 MySQL `GET_LOCK` 抢锁保证只推一次。
- 用户可自助配置自己的飞书应用凭证（App Secret 加密存储、只回掩码、可发测试消息）。

---

## 五、数据模型（19 张表）

| 分组 | 表 |
|---|---|
| 用户侧（6） | `user`、`household`、`diet_preference`、`allergy_restriction`、`health_goal`、`budget` |
| 内容（3） | `ingredient`（含 `reference_price`）、`recipe`、`recipe_ingredient`（含 `amount_text`） |
| 外部（2） | `product`、`product_mapping` |
| 运行（7） | `fridge_inventory`、`consumption_record`、`menu`、`menu_item`、`menu_generation_task`、`purchase_record`、`activity_log` |
| 配置（1） | `user_feishu_config` |

> 单一字段 `user_id` 贯穿所有用户侧数据；所有查询都带 `user_id` 过滤，**越权一律 404**（不返回 403，避免探测）。

**身份命名空间**：`user.open_id` 用前缀区分来源，新增登录方式不需要加表加列 ——
`ou_...`（飞书）、`wechat:`（微信小程序）、`dev:`（仅本地开发登录）。
唯一落库入口是 `UserService.upsert_from_identity()`。

**迁移链**：`0001_init` → `0002_consumption_record_keeps_history` → `0003_v2_today_and_brand`
→ `0004_consumption_record_identity` → `0005_generation_task_regeneration` → `0006_user_feishu_config`。

---

## 六、关键设计决策（从代码与架构文档提炼）

1. **多用户为默认**：无 `DEFAULT_USER_ID`，一律以 token 中的 `user_id` 为准。
2. **异步生成**：接口不阻塞，前端全局 store 轮询，导航不被生成阻塞。
3. **成本真实化**：单位为 `None` 时计入 `unpriced_items` 而不是臆造价格；预算超支只告警不阻断。
4. **状态机**：`menu.status` 走 `draft → confirmed → active → completed`。
5. **单一方言测试**：集成测试跑 MySQL（与生产同方言），避免「SQLite 上能过」的假绿。
6. **安全收口**：`debug=false`、`DATABASE_ECHO=false`、CORS 收紧、日志不打印密钥与 token。
7. **共享层单一真源**：令牌 / Logo 由脚本生成，CI 校验漂移。
8. **诚实的降级**：没配视觉模型就置灰并引导手动添加；没配飞书就显示「未配置」而不是假装已连接。
9. **凭证按用户存**：一个家庭每人飞书租户不同，`user_feishu_config` 按 `user_id` 隔离，
   解析顺序为「用户自己的配置 → 部署默认配置 → 视为未配置」。

---

## 七、开发与管理流程反写（TAPD 流程模板的依据）

### 7.1 环境与启动

| 环节 | 命令 / 资产 |
|---|---|
| 一键初始化 | `bash scripts/setup_local.sh`（装 MySQL 8 / Python 3.12、建库建号、生成 `.env`、建表、导种子、装前端依赖、跑测试） |
| 日常启停 | `make up` / `make down` / `make restart` / `make status` / `make logs` |
| 交互式运维台 | `make ops`（`scripts/service.sh`，带实时状态与菜单） |
| 项目专用 MySQL | `make db-start` / `db-stop` / `db-status` / `db-shell`（macOS 独立实例，端口 3307） |

### 7.2 质量门禁（`make ci`）

```
lint(ruff) → test(pytest 225) → check-tokens → check-logo → test-frontend(vitest 47)
→ build-frontend → check-miniapp(typecheck + build:weapp)
```

### 7.3 数据库变更流程

唯一入口：`make migration MSG="..."`（Alembic autogenerate）→ 人工审阅 → `make migrate`。
**禁止手工建表**，`alembic upgrade head` 是唯一建表方式。

### 7.4 测试策略

| 层级 | 数量 | 说明 |
|---|---|---|
| unit | 121 | 纯函数与单服务（预算、营养、多样性、定价、加密箱、Bot 解析等） |
| integration | 103 | 走 MySQL 同方言，覆盖 auth / 生成 / 编辑 / 撤销 / 采购 / 今日 / 调度锁 / Webhook |
| e2e | 1 | 端到端主链路 |

### 7.5 部署与运维

`nginx`（443，托管 `frontend/dist` + 反代 `/api/*`、`/feishu/*`）+ `systemd` 守护 + `certbot` 证书；
`deploy/README.md` 为生产上线手册；`make backup` 备份 MySQL 并清理 14 天前备份。

### 7.6 文档规范

`docs/` 7 篇 + `deploy/README.md`：架构、设计系统、本地部署、部署、飞书配置、小程序配置、产品 V2、QA 报告。
**产品方案（`docs/product-v2.md`）是产品真源**，命名 / Logo / 信息架构 / 交互优先级以它为准。

---

## 八、历史进度还原（已完成部分）

依据 Git 提交时间线、Alembic 迁移、测试资产与 QA 报告，把历史还原为 **4 个里程碑**：

| 迭代 | 时间 | 交付内容 | 完成证据 |
|---|---|---|---|
| **M1 基础闭环** | 2026-09-10 15:59 | 多用户闭环（飞书扫码登录、用户隔离、越权 404）+ 本地一键部署（setup/ops/MySQL 独立实例） | `09b8fc7`、`0001_init` 19 表、`scripts/setup_local.sh` |
| **M2 多端与共享层** | 2026-09-10 22:57 | 微信小程序（Taro 4 + React）+ `shared/` 共享层入库，含 UI / 功能 QA 修复 | `05bf213`、`docs/miniapp-qa-report.md`、`miniapp/dist` |
| **M3 V2.0 功能闭环** | 2026-09-10 22:59 | 后端：今日页 / 补单 / 自动化 / 飞书配置 / 微信登录 / 拍照识别 / 撤销；前端：今日页 / 我的抽屉 / 拍照识别 / 自动化 | `0e509e5`、`c96c458`、`0003` + `0004` 迁移 |
| **M4 工程收口** | 2026-09-10 22:59–23:00 | 产品方案 / 设计系统 / 小程序配置 / 架构部署文档同步；工具、配置、品牌资源落地 | `0128742`、`4318890`、`docs/*`、`assets/logo/*` |

> 归档差异记录：`0005_generation_task_regeneration`（首生成与重生成额度分离）与
> `0006_user_feishu_config`（凭证按用户存）补齐了 V2.0 的配额与多租户飞书细节。

---

## 九、新开发进度规划

### 9.1 规划总览

| 迭代 | 主题 | 目标 | 范围 |
|---|---|---|---|
| **V2.1** | 体验与稳定 | 把 V2.0 的闭环做「顺手且稳」 | 移动端硬指标复核、错误分级、性能与可观测、小程序真机回归 |
| **V2.2** | 数据与智能 | 让结果更准、更省心 | 视觉识别准确率与限流优化、菜单口味学习、预算与营养个性化、多周菜单 |
| **V3.0** | 二期数据源 | 把「估算」换成「实价」 | 小象超市采集（Playwright 登录态、商品库、价格快照、食材-商品匹配） |

### 9.2 明确不做（沿用 V2.0 边界）

微信 / 支付宝支付、多语言、SSE 流式输出、法定节假日与调休表、暗色主题。

### 9.3 建议排期（相对周）

- 迭代 V2.1：第 1–2 周
- 迭代 V2.2：第 3–5 周
- 迭代 V3.0：第 6–9 周

---

## 十、TAPD 落地清单（待写入）

> 说明：TAPD 开放接口**不支持创建项目**，需要先在 TAPD 网页端建好项目；拿到项目 ID（`workspace_id`）后，
> 以下内容可一次性写入，TAPD 原生看板与迭代视图即刻可用。

### 10.1 迭代（7 个）

| 迭代名 | 周期 | 状态 |
|---|---|---|
| M1 基础闭环 | 历史 | 已关闭 |
| M2 多端与共享层 | 历史 | 已关闭 |
| M3 V2.0 功能闭环 | 历史 | 已关闭 |
| M4 工程收口 | 历史 | 已关闭 |
| V2.1 体验与稳定 | 规划 | 开启 |
| V2.2 数据与智能 | 规划 | 开启 |
| V3.0 二期数据源 | 规划 | 开启 |

### 10.2 需求（Story，按模块）

- 基础平台：账号与登录（飞书 / 微信 / 本地开发）、多用户数据隔离、配置与降级策略
- 菜单生成：异步生成流水线、营养 / 预算 / 多样性校验、菜单编辑与撤销
- 采购与库存：采购清单、补单决策与 deeplink、库存扣减与临期管理、拍照识别入库
- 触达与自动化：飞书 Bot 指令、定时推送、用户自助凭证
- 多端：H5（Bento 首页 + 设计系统）、微信小程序、shared 共享层单一真源
- 工程：一键本地部署与运维台、CI 门禁、部署与上线手册

### 10.3 任务（Task）

按上述 Story 拆解为可执行任务（每 Story 2–4 条），状态沿用 TAPD 的 `未开始 / 进行中 / 已完成`。

### 10.4 缺陷（Bug，来自小程序 QA 报告）

| 编号 | 标题 | 类别 | 现状 |
|---|---|---|---|
| U1 | 页面底部未计入 safe-area-inset-bottom，内容被 TabBar / 手势条遮挡 | 适配 | 已修复 |
| U2 | 悬浮 TabBar 未避让底部手势条 | 适配 | 已修复 |
| U3 | `.page` 未使用页面最大宽度令牌，大屏通栏 | 适配 | 已修复 |
| U4 | 今日页头像触控目标 38px < 44px 规范 | 适配 | 已修复 |
| F1 | 补单明细行 key 冲突导致列表渲染错乱 | 功能 | 已修复 |
| F2 | 今日页无用导入 `Chip` | 代码质量 | 已修复 |
| C1 | `getWindowInfo` 基础库兼容缺失，状态栏高度读取失败 | 兼容 | 已修复 |
| C2 | `chooseMedia` 基础库兼容缺失，拍照识别无法取图 | 兼容 | 已修复 |
| C3 | 登录页配置下拉刷新但未实现 | 配置 | 已修复 |

### 10.5 Wiki（3 篇）

1. **项目档案**：定位、技术栈、模块划分、数据模型
2. **架构与依赖**：分层图、依赖方向、共享层单一真源、部署拓扑
3. **开发与管理流程**：环境搭建、质量门禁、迁移流程、测试策略、发布与上线
