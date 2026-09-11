# 每周鲜 · AI 营养菜谱

> 把一周吃饭这件事交给 AI 排好：飞书扫码 / 微信一键登录 → 填偏好 → 生成一周菜单 →
> 补单下单 → 做饭扣库存，形成闭环。H5 与微信小程序两个端共用同一套业务层与设计系统。
>
> 产品方案（命名/Logo、信息架构、交互优先级）见 [docs/product-v2.md](docs/product-v2.md)。

## 功能概览

**本期已实现**

- **飞书扫码登录**：网页应用形态，PC 展示二维码 / 手机唤起飞书；httpOnly Cookie 会话（access 2h / refresh 30d）
- **多用户隔离**：所有数据按登录用户过滤，越权访问返回 404；生成配额分两档 —— 首次生成 3 次/日、重新生成 10 次/日，互不占用
- **飞书机器人可自助配置**：在「我的 → 自动化」填写自己的 App ID / App Secret / 接收人，保存后可一键发测试消息；App Secret 加密存储且只回掩码
- **智能菜谱生成**：异步任务（`202 + task_id`，前端轮询，可关页面）；同一周已有草稿直接复用不重复消耗额度
- **营养均衡校验**：按日汇总热量与三大营养素供能比，偏差写进告警
- **预算控制**：按 `ingredient.reference_price` 真实计价，超支告警而不阻断生成
- **多样性控制**：与近 4 周历史菜名做 Jaccard 比对，冲突自动重生成一次
- **过敏源防线**：命中过敏源的菜品从落库前剔除并在响应中告警
- **周菜单可视化编辑**：7 天 × 餐次卡片，支持换一道、锁定/解锁（锁定餐次不被重生成覆盖）、标记已做
- **采购清单**：菜单所需 vs 冰箱库存的差集，含缺口数量与单位换算，支持一键复制
- **库存闭环**：标记已做 → 临期优先扣减库存 → 写 `consumption_record`；缺料不阻断并返回明细
- **今日页（一次请求拿全）**：`GET /api/today` 返回今日预算、餐次、采购缺口、补单建议、
  自做 vs 外卖对比、临期食材与今日自动流程时间线，任何一块缺失都不让整页失败
- **补单决策**：缺口按 `ingredient.reference_price` 估算合计，不够起送价时从"本周迟早要买"的
  缺料里凑单，给出 deeplink 直接下单；小程序优先跳小程序、否则复制清单
- **自做 vs 外卖**：自做价来自菜单成本，外卖价用用户参考价（卡片上改价会记住），
  结论分 `homemade / takeout / either` 三档并说明预算占用
- **拍照识别入库**：拍照 → 视觉大模型 → 候选清单逐条可编辑 → 确认后入库；
  受 `llm.vision.daily_limit` 限流，未配置时降级为手动添加
- **可撤销**：换一道（换回上一道）、标记已做（回滚库存与消耗流水）都有后悔窗口
- **机器人状态卡**：`GET /api/automation/status` 如实显示飞书连接、调度开关、下次运行与最近推送
- **4 Tab 信息架构**：今日 / 周菜单 / 采购 / 冰箱，「我的」挂在右上角头像的抽屉里
- **响应式 H5**：Bento 首页，<1024px 悬浮胶囊 TabBar，≥1024px 左侧导航 + 右侧「我的」抽屉
- **微信小程序**：独立 `miniapp/`（Taro 4 + React），功能与 H5 完全一致；微信一键登录自动建号，
  与飞书账号并存不绑定；与 H5 共用 `shared/` 的类型、格式化、下一步指引与设计令牌
- **设计系统**：中性灰 + 语义色（绿=完成/橙=注意）+ 黑胶囊主按钮；令牌单一真源，两端零漂移，
  见 [docs/design-system.md](docs/design-system.md)
- **飞书 Bot**：事件回调（签名校验 + AES 解密 + `event_id` 去重 + 1 秒内响应）；指令「菜单 / 库存 /
  添加库存 / 完成某餐 / 帮助」直接查库并回复；定时推送菜单、缺料与临期提醒（默认关闭，多 worker 用
  MySQL `GET_LOCK` 抢锁保证只推一次）

**二期（未启用，不影响上线）**

- 小象超市采集（Playwright 登录态、商品库、价格快照、食材-商品匹配）
  —— V2.0 的补单链路已用"参考价 + deeplink"打通，采集只用于把估算换成实价

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python 3.12 / FastAPI / SQLAlchemy 2.0 async / aiomysql |
| 数据库 | MySQL 8.0 (utf8mb4) / Alembic 迁移 |
| 任务 | DB 表 + 进程内 worker (`SELECT ... FOR UPDATE SKIP LOCKED`) |
| 定时 | APScheduler（默认关闭，跨 worker 用 MySQL `GET_LOCK` 抢锁） |
| 认证 | 飞书扫码 / 微信小程序一键登录 + 自签 JWT（H5 走 httpOnly Cookie，小程序走 Bearer） |
| LLM | GLM-4 → Qwen-Max → DeepSeek（本地模型可选降级） |
| H5 | React 18 / Vite 6 / TypeScript / Ant Design 5 |
| 小程序 | Taro 4.2 / React 18 / TypeScript / SCSS（自研轻组件，不引 UI 库） |
| 共享层 | `shared/` 纯 TS（类型 / 格式化 / 下一步规则 / 设计令牌） |
| 部署 | nginx + systemd + certbot（见 `deploy/README.md`） |

## 快速启动

### 方式一：一条命令（推荐）

```bash
bash scripts/setup_local.sh
```

脚本会自动装 MySQL 8.0 / Python 3.12、建库建号、生成 `.env`、建表、导入种子数据、
装前端依赖并跑一遍测试。然后一条命令把服务拉起来（后台运行，不占终端）：

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

> 机器上已经装过别的 MySQL？脚本会自己判断。如果系统的 MySQL 数据目录是更高版本
> （例如 9.x）建的、8.0 打不开，脚本**不会动那份数据**，而是给本项目单独起一个实例
> （端口 `3307`），用 `make db-status` / `make db-start` / `make db-stop` 管理。
> 详见 [docs/local-setup.md 附录 C](docs/local-setup.md)。

### 方式二：手动分步

环境已经就绪时：

```bash
make setup      # 后端 pip install -e ".[dev]" + 前端 npm install
cp .env.example .env   # 填 APP__DATABASE__URL / APP__AUTH__JWT_SECRET / LLM Key
make migrate    # alembic upgrade head, 建 19 张表
make seed       # 导入 66 条食材与参考价
make test       # 需先 export TEST_DATABASE_URL
```

## 项目结构

```
meal-planner/
├── backend/
│   ├── app/
│   │   ├── api/          # 路由: auth / preferences / menus / inventory / products
│   │   ├── auth/         # JWT 令牌与飞书 OAuth 客户端
│   │   ├── models/       # 19 张表的 ORM 定义
│   │   ├── schemas/      # Pydantic 请求/响应模型与序列化
│   │   └── services/     # 生成流水线、菜单、库存、采购、营养、预算、多样性
│   ├── alembic/          # 迁移脚本 (0001_init 为基线)
│   └── tests/            # unit / integration / e2e
├── frontend/             # React + Vite 的 H5 端 (Bento 首页 + 设计系统)
├── miniapp/              # 微信小程序 (Taro 4 + React), 与 H5 同功能
├── shared/               # H5 与小程序共享的纯 TS 层 (类型/格式化/下一步/设计令牌)
├── config/               # default.yaml 与 Prompt 模板
├── deploy/               # nginx / systemd / MySQL 初始化 / 上线手册
├── docs/                 # 本地部署、架构、上线、飞书配置
├── logs/                 # 后台服务日志与 PID (git 忽略)
└── scripts/
    ├── setup_local.sh    # 一键初始化本地环境
    ├── service.sh        # 服务运维台: 启停/重启/日志/自检
    ├── mysql_local.sh    # 项目专用 MySQL 实例管理
    ├── seed_data.py      # 食材与参考价种子数据
    └── backup_db.py      # 数据库备份
```

## 文档

- [**全项目总案**](docs/master-plan.md) —— 模块结构与规划、需求 × 版本台账、差异对齐、路线图、TAPD 落地映射
- [项目审计](docs/project-audit.md) —— 模块划分 / 依赖关系 / 业务流程 / 历史进度还原
- [产品方案 V2.0](docs/product-v2.md)
- [架构设计](docs/architecture.md)
- [数据库说明文档](docs/database.md) —— 表结构 / 索引 / 外键 / ER 关系图 / 字段含义（`make db-doc` 生成）
- [设计系统](docs/design-system.md)
- [微信小程序配置与调试](docs/miniapp-setup.md)
- [本地部署指南（傻瓜版）](docs/local-setup.md)
- [部署指南](docs/deployment.md)
- [上线手册（生产）](deploy/README.md)
- [飞书扫码登录配置](docs/feishu-setup.md)

## 免责声明

本工具仅供个人学习与家庭使用。二期涉及的小象超市数据采集为非官方实现，可能违反平台服务条款，
使用者需自行承担相关风险；本期功能不包含任何采集行为。

## License

MIT
