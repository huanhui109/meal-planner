# 饭决 FAN·DECIDE · 今天吃啥，交给饭决

[English](README_EN.md) | 简体中文

> 围绕「这一餐」的家庭用餐助手：打开看到建议 → 接受或微调 → 做饭或点外卖 → 记录实际吃过。
> 快速推荐不依赖模型 Key，也不要求先录入库存；饭决 Skill 借助宿主助手理解自然语言，
> 与网页共用同一份用餐状态。
>
> **当前版本：2.9.0** · 最近更新 2026-11-06 · 变更见 [CHANGELOG.md](CHANGELOG.md)
>
> 新工作台的领域结构、迁移与约束见 [docs/meal-workspace.md](docs/meal-workspace.md)；
> 命名与信息架构的历史设计依据见 [docs/product-v2.md](docs/product-v2.md)（V2.0 时期文档）。
>
> 网页一级导航为「这一餐 / 厨房 / 记录」。周菜单、采购、冰箱等旧能力作为兼容层保留，
> 小程序端暂停新增功能。

---

## 功能概览

### 2.9.0 · 这一餐工作台

- **自动给出完整一餐**：按家庭人数、做饭/外卖、预算目标、参考用时、辣度和临时忌口生成；
  条件冲突明确说明，不静默忽略。空库存不阻止推荐。
- **四态分离与可撤销**：`viewed / rejected / accepted / eaten` 分别记录，只有「吃过」才进饮食历史；
  默认不扣库存，主动勾选才尝试精确扣减；扣库收据独立保留批次与保质期，撤销吃过可恢复。
- **饭决 Skill**：`skills/fandecide/` 提供 Skill 说明与本机 CLI，可从 `/api/assistant/skill.zip` 下载；
  助手只有 `meal:read` 与 `meal:propose` 作用域，凭据仅存 SHA256、可随时撤销，
  且只从服务端返回的真实候选 key 组织方案。
- **可选直连 WorkBuddy**：网页编辑要求后直接发送，自动等待并回显新方案；
  支持刷新恢复、取消与离线复制；OAuth 凭据加密存储，不暴露给网页或模型。
- **统一「助手连接」入口**：头像设置里同时管理网页直发与 Skill 凭据；
  连接超时可恢复重试，未配置 WorkBuddy 时仍能单独创建 Skill 凭据。
- **双向唤醒模块（独立特性，默认关闭）**：`/api/inbound/bridge/*` 九端点入站网关、
  双向令牌对、事件白名单默认拒绝；L0（环境变量）与 L1（数据库）双层开关，关闭时端点返回 503。
  **「补门不换桥」**：快速推荐、既有 `/api/assistant/adjustments` 旧桥与 Skill 连接完全不受影响。
- **服务端校验不可被模型覆盖**：显式忌口、辣度、餐次、厨具条件与 `expected_revision` 乐观锁
  均在 `MealService` / `MealCatalog` 二次校验；AI 只提建议，不覆盖基于真实数据生成的解释。

> ⚠ **联调状态**：真实 WorkBuddy 账号的平台级联调（真实 OAuth 授权、在线发送、宿主模型质量）
> **尚未完成**。现有验收均为本地模拟与自动化测试，模拟通过不等于线上可用。

### 兼容能力（历史版本，继续可用）

- **登录与隔离**：飞书扫码（httpOnly Cookie，access 2h / refresh 30d）、微信小程序一键登录、
  本地开发登录；三种账号并存且互相隔离，所有查询按用户过滤，越权返回 404。
- **决策引擎**：`shared/decide.ts` 与服务端 `decision_service.py` 离线同构；
  三条硬规则、分差带内软随机抽签、≤20 字纯规则理由；断网/超时时用内置菜池给出「本地答案」。
  对外菜品道数口径为 **342 道**（`is_dish=1`）。
- **周菜单**：异步任务（`202 + task_id`，可关页面轮询）、本地菜谱库优先（凑齐即零模型调用）、
  换一道、锁定/解锁、标记已做；生成配额分首次 3 次/日与重新生成 10 次/日两档，互不占用。
- **营养 / 预算 / 多样性 / 过敏源**：按日汇总热量与三大营养素供能比；
  按 `ingredient.reference_price` 计价、超支告警而不阻断；近 4 周菜名 Jaccard 去重；
  命中过敏源的菜品落库前剔除并在响应中告警。
- **采购与库存闭环**：菜单需求 vs 冰箱库存差集、缺口数量与单位换算、一键复制；
  临期优先扣减并写 `consumption_record`，缺料不阻断并返回明细。
- **今日页 / 补单 / 自做 vs 外卖**：`GET /api/today` 一次请求拿全，任一模块失败不拖垮整页；
  缺口按参考价凑起送价并给 deeplink；结论分 `homemade / takeout / either` 三档。
- **拍照识别入库**、**可撤销**（换一道、标记已做）、**机器人状态卡**如实显示连接与调度状态。
- **飞书 Bot**：事件回调（签名校验 + AES 解密 + `event_id` 去重 + 1 秒内响应），
  指令直接查库回复；定时推送默认关闭，多 worker 用 MySQL `GET_LOCK` 抢锁保证只推一次。
- **多端与设计系统**：H5 响应式（<1024px 悬浮胶囊 TabBar，≥1024px 左侧导航）；
  小程序（Taro 4.2 + React）保留 4 Tab 兼容界面；两端共用 `shared/` 类型、格式化、
  决策规则与设计令牌，见 [docs/design-system.md](docs/design-system.md)。

### 二期（未启用，不影响使用）

- 小象超市采集（Playwright 登录态、商品库、价格快照、食材-商品匹配）。
  补单链路已用「参考价 + deeplink」打通，采集只用于把估算换成实价；
  **当前版本不包含任何采集行为**。

---

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python 3.11+（开发用 3.12） / FastAPI / SQLAlchemy 2.0 async / aiomysql |
| 数据库 | MySQL 8.0 (utf8mb4) / Alembic 迁移（当前 head `0026`；39 张 ORM 业务表） |
| 接口 | `backend/app/api/` 下 17 个业务路由模块 + 飞书 webhook，统一挂 `/api` |
| 任务 | DB 表 + 进程内 worker (`SELECT ... FOR UPDATE SKIP LOCKED`) |
| 定时 | APScheduler（默认关闭，跨 worker 用 MySQL `GET_LOCK`） |
| 认证 | 飞书扫码 / 微信小程序 + 自签 JWT；助手作用域凭据独立 |
| LLM | GLM-4 → Qwen-Max → DeepSeek（本地模型可选降级）；快速推荐不调用模型 |
| H5 | React 18 / Vite 7 / TypeScript / Ant Design 5 / Vitest 3 |
| 小程序 | Taro 4.2 / React 18 / TypeScript / SCSS（自研轻组件，不引 UI 库） |
| 共享层 | `shared/` 纯 TS（类型 / 格式化 / 决策规则 / 端点 / 设计令牌） |
| 部署 | nginx + systemd + certbot（见 [deploy/README.md](deploy/README.md)） |

---

## 快速启动

### 方式一：一条命令（推荐）

```bash
bash scripts/setup_local.sh
```

脚本会自动装 MySQL 8.0 / Python 3.12、建库建号、生成 `.env`、执行全部迁移、
导入种子数据、装前端依赖并跑一遍测试。然后一条命令把服务拉起来（后台运行，不占终端）：

```bash
make up             # 数据库 + 后端 + 前端
make status         # 看状态
make logs           # 跟日志
make down           # 停止
```

不想记命令就打开交互式运维台，带实时状态与操作菜单：

```bash
make ops
```

小程序（可选，独立工程）：

```bash
make install-miniapp   # 装小程序依赖
make build-miniapp     # 构建微信小程序, 产物在 miniapp/dist
```

然后用微信开发者工具导入 `miniapp/` 目录。配置 AppID、合法域名与开发期免微信调试的完整步骤见
**[docs/miniapp-setup.md](docs/miniapp-setup.md)**。

想看 uvicorn / vite 的实时输出（调试用）：`make dev-backend` + `make dev-frontend`。

本地默认开启「本地开发登录」（免飞书）与「演示模式」（免 LLM Key），开箱即用。
完整步骤、排障表与手动兜底流程见 **[docs/local-setup.md](docs/local-setup.md)**。

> 机器上已经装过别的 MySQL？脚本会自己判断：**优先复用 3306 上的系统 MySQL 8.0**。
> 只有在系统实例不可用（例如数据目录是 9.x 建的、8.0 无法降级打开）时，脚本才**不动那份数据**，
> 另外起一个项目专用实例（兜底端口 `3307`），用 `make db-status` / `make db-start` / `make db-stop` 管理。
> 应用连接配置统一在 `.env` 的 `APP__DATABASE__URL`，详见
> [docs/database-config.md](docs/database-config.md) 与 [docs/local-setup.md 附录 C](docs/local-setup.md)。

### 方式二：手动分步

环境已经就绪时：

```bash
make setup                  # 后端 pip install -e ".[dev]" + 前端 npm install
cp .env.example .env        # 填 APP__DATABASE__URL / APP__AUTH__JWT_SECRET / LLM Key
make migrate                # alembic upgrade head（执行全部迁移）
make seed                   # 导入食材与参考价种子数据
make test                   # 需先 export TEST_DATABASE_URL
```

> ⚠ 不设 `TEST_DATABASE_URL` 时集成用例是 **skip 不是 pass**，看到「全绿」先确认它真的跑了。

---

## 项目结构

```
meal-planner/
├── backend/
│   ├── app/
│   │   ├── api/          # 17 个业务路由模块 (auth / decide / menus / meals / assistant / inbound_bridge / ...)
│   │   ├── models/       # 39 张 ORM 业务表
│   │   ├── schemas/      # Pydantic 请求/响应模型与序列化
│   │   └── services/     # 决策、菜单、库存、这一餐工作台、助手桥接、双向唤醒
│   ├── alembic/          # 迁移 0001 → 0026
│   └── tests/            # unit / integration
├── frontend/             # React + Vite 的 H5 端（这一餐 / 厨房 / 记录）
├── miniapp/              # 微信小程序（Taro 4.2 + React），保留兼容界面
├── shared/               # 双端唯一真源：类型 / 格式化 / 决策规则 / 端点 / 设计令牌
├── skills/fandecide/     # 饭决 Skill 说明与本机 CLI（/api/assistant/skill.zip 分发）
├── data/                 # 开源菜谱种子与语料
├── config/               # default.yaml 与 Prompt 模板
├── deploy/               # nginx / systemd / MySQL 初始化 / 上线手册
├── docs/                 # 部署、架构、数据库、设计系统、小程序配置
├── scripts/              # 本地初始化、服务运维、数据回填与校准
├── .github/workflows/    # CI 与部署流水线
├── output/               # 校准产物与测试用 CSV（其余本地产物不入库）
└── logs/                 # 后台服务日志（git 忽略）
```

## 文档

- [这一餐工作台设计](docs/meal-workspace.md) —— 领域结构、数据边界、迁移与约束
- [架构设计](docs/architecture.md) · [数据库配置](docs/database-config.md) · [数据库说明（生成物快照）](docs/database.md)
- [菜品数据设计](docs/dish-data-design.md) · [System One 接入](docs/system-one-integration.md)
- [设计系统](docs/design-system.md) · [小程序品牌资产](docs/miniapp-brand-assets.md)
- [本地部署指南](docs/local-setup.md) · [生产上线手册](deploy/README.md) · [内测灰度](deploy/internal-test.md)
- [小程序配置与调试](docs/miniapp-setup.md) · [小程序排障](docs/miniapp-troubleshooting.md) · [构建说明](miniapp/BUILD.md)
- [飞书扫码登录配置](docs/feishu-setup.md)
- [隐私政策模板](docs/legal/privacy.md) · [服务条款模板](docs/legal/terms.md)（模板草案，非生效法律文本）
- [产品方案 V2.0（历史规划）](docs/product-v2.md)

> `docs/database.md` 由 `make db-doc` 从某一时刻的本地库结构生成，其中的表数量是**快照值**；
> 当前设计值以 `backend/app/models/` 与 alembic 迁移为准。

## 免责声明

本工具仅供个人学习与家庭使用。二期涉及的小象超市数据采集为非官方实现，可能违反平台服务条款，
使用者需自行承担相关风险；本期功能不包含任何采集行为。

## 许可证与分发

本项目采用 **MIT 许可证**开源，详见 [LICENSE](LICENSE)。

内置菜谱数据来源于开源项目，其原始许可优先于本仓库许可：
HowToCook（[Anduin2017/HowToCook](https://github.com/Anduin2017/HowToCook)，Unlicense）
与 proj.kitchen，来源标注见 `data/` 与 `scripts/import_recipes/`。

> 2026-10-12 起本仓库由私有转为公开。在此之前 README 中「私有仓库、不开放源代码」的声明
> 已随该次变更作废。

---

最后更新：2026-11-06
