# 饭决 FAN·DECIDE

[English](README_EN.md) | 简体中文

> **今天吃啥，交给饭决。** 一个围绕「这一餐」的家用膳食助手：打开就看到建议 → 接受或微调 → 做饭或点外卖 → 记录真正吃了什么。
>
> 推荐由规则引擎驱动，**不需要模型 Key，也不要求先录入库存**；AI 只作为可选的调整手段，所有结论都由服务端按真实数据复核。
>
> **当前版本 2.9.0** · 更新于 2026-11-12 · 变更见 [CHANGELOG.md](CHANGELOG.md)

---

## 它能做什么

| 场景 | 饭决的做法 |
| --- | --- |
| 现在吃什么 | 按家庭人数、做饭/外卖、预算、参考用时、辣度和临时忌口，直接给出一份完整方案；条件冲突明确说明，不静默忽略 |
| 不想被模型绑架 | 决策引擎是纯规则 + 分差带内软随机，断网或超时也能用内置菜池给出「本地答案」 |
| 想用自然语言改 | 点「交给 AI 调整」说一句「想吃暖胃的、别太辣」，一次请求返回结构化建议，服务端复核后才生效 |
| 想吃的菜池里没有 | 应用内的「候选菜品技能」按模糊描述补 3–5 道**真实存在**的菜，附现实依据与做法，校验通过才入池 |
| 吃完之后 | `viewed / rejected / accepted / eaten` 四态分离，只有「吃过」进饮食历史；默认不扣库存，撤销可恢复 |

对外菜品道数口径为 **342 道**（`is_dish=1`）。

## 核心设计

- **规则优先、模型可选**：`shared/decide.ts` 与服务端 `decision_service.py` 离线同构；三条硬规则、理由 ≤20 字且纯规则生成，模型不参与打分排序。
- **禁止杜撰**：候选池只有数据库 `recipe`、[`data/local_dish_pool.json`](data/local_dish_pool.json) 的 62 道本地菜与米饭。AI 不得编造菜名、配料或价格；唯一例外是按需求补全**现实中存在**的菜，且必须带依据、做法与来源标记，由 `write_dish()` 单一入口裁决入池。
- **服务端最终裁决**：AI 只提建议；忌口、辣度、餐次、厨具、乐观锁与候选真实性都在 `MealService.propose()` 复查，不合规即失败，原方案不变。
- **低延迟优先**：AI 调整与候选补全都是单跳请求、短超时、不重试、不追问；信息不足也直接给合理候选，失败即降级为规则推荐，不让用户干等。
- **双端同源**：H5（React + Vite）与小程序（Taro + React）共用 `shared/` 的类型、格式化、决策规则、端点与设计令牌。

## 应用内技能（Skills）

| Skill | 作用域 | 说明 |
| --- | --- | --- |
| [`skills/fandecide/`](skills/fandecide/SKILL.md) | 选菜 | 只能从服务端给的真实候选 key 组织一餐，无权新增候选；提供本机 CLI，运行时由 `/api/assistant/skill.zip` 分发 |
| [`skills/fandecide-candidates/`](skills/fandecide-candidates/SKILL.md) | 补候选 | 接收模糊的口味／场景／食材描述，返回默认 4 道（范围 3–5 道）结构一致的真实菜品，字段可反向落到 `recipe` 表 |

两个技能作用域互斥，且都不放宽「禁止杜撰」底线。候选技能的触发条件、输入、输出字段与默认数量见 [SKILL.md](skills/fandecide-candidates/SKILL.md) 与 [contract.json](skills/fandecide-candidates/contract.json)；工作台的领域结构、迁移与约束见 [docs/meal-workspace.md](docs/meal-workspace.md)。

## 技术栈

| 层 | 技术 |
| --- | --- |
| 后端 | Python 3.11+（开发用 3.12）/ FastAPI / SQLAlchemy 2.0 async / aiomysql |
| 数据库 | MySQL 8.0（utf8mb4）/ Alembic 迁移 `0001 → 0028` |
| 接口 | `backend/app/api/` 下业务路由 + 飞书 webhook，统一挂 `/api` |
| 任务 / 定时 | 数据库任务表 + 进程内 worker（`SELECT ... FOR UPDATE SKIP LOCKED`）；APScheduler 默认关闭 |
| 认证 | 飞书扫码 / 微信小程序 + 自签 JWT；助手作用域凭据独立 |
| 推荐 | 纯规则（默认，不调用模型）；可选 GLM-4 / Qwen / DeepSeek，或本机已授权的助手连接 |
| H5 | React 18 / Vite 7 / TypeScript / Ant Design 5 / Vitest 3 |
| 小程序 | Taro 4.2 / React 18 / TypeScript / SCSS（自研轻组件，不引 UI 库） |
| 共享层 | `shared/` 纯 TS：类型 / 格式化 / 决策规则 / 端点 / 设计令牌 |
| 部署 | nginx + systemd + certbot（见 [deploy/README.md](deploy/README.md)） |

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

真实配置只放在 `.env`（已忽略），仓库内只保留 `.env.example` 与 `config/default.yaml` 这类占位模板。

---

## 项目结构

```
meal-planner/
├── backend/
│   ├── app/
│   │   ├── api/          # 业务路由（auth / decide / menus / meals / assistant / ...）
│   │   ├── models/       # SQLAlchemy ORM 模型
│   │   ├── schemas/      # Pydantic 请求/响应模型与序列化
│   │   └── services/     # 决策、菜单、库存、这一餐工作台、助手桥接、候选补全
│   ├── alembic/          # 迁移 0001 → 0028
│   └── tests/            # unit / integration
├── frontend/             # React + Vite 的 H5 端（这一餐 / 厨房 / 记录）
├── miniapp/              # 微信小程序（Taro 4.2 + React），保留兼容界面
├── shared/               # 双端唯一真源：类型 / 格式化 / 决策规则 / 端点 / 设计令牌
├── skills/
│   ├── fandecide/            # 选菜 Skill 说明与本机 CLI
│   └── fandecide-candidates/ # 候选菜品 Skill 规格与输出契约
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
- [候选菜品技能规格](skills/fandecide-candidates/SKILL.md) · [输出契约](skills/fandecide-candidates/contract.json)
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

## 兼容能力与边界

- 飞书扫码 / 微信小程序 / 本地开发登录三种账号并存且互相隔离，所有查询按用户过滤，越权返回 404。
- 周菜单、采购清单、冰箱库存、营养／预算／多样性／过敏源、拍照识别入库、飞书机器人等早期能力
  作为兼容层继续可用；网页一级导航为「这一餐 / 厨房 / 记录」，小程序端暂停新增功能。
- 「交给 AI 调整」依赖本机已授权的助手连接，**不是官方公开 API**，可能随上游调整而失效；连接缺失或
  过期时应用如实报告不可用并降级为规则推荐，主流程不受影响。该链路目前只经过本地模拟与自动化测试，
  真实账号的端到端效果尚未验证。
- 二期规划中的比价采集能力**未启用**，当前版本不包含任何采集行为。

## 免责声明

本工具面向个人学习与家庭使用，不提供医疗或营养建议。使用者需自行承担部署与第三方服务接入的相关风险。

## 许可证与分发

本项目采用 **MIT 许可证**开源，详见 [LICENSE](LICENSE)。

内置菜谱数据来源于开源项目，其原始许可优先于本仓库许可：
HowToCook（[Anduin2017/HowToCook](https://github.com/Anduin2017/HowToCook)，Unlicense）
与 proj.kitchen，来源标注见 `data/` 与 `scripts/import_recipes/`。

> 2026-10-12 起本仓库由私有转为公开。在此之前 README 中「私有仓库、不开放源代码」的声明
> 已随该次变更作废。

---

最后更新：2026-11-12
