# AI 每周营养菜谱工具

> 多用户 AI 菜谱助手：飞书扫码登录 → 填偏好 → 生成一周菜单 → 周视图编辑 → 采购清单 → 库存扣减，形成闭环。

## 功能概览

**本期已实现**

- **飞书扫码登录**：网页应用形态，PC 展示二维码 / 手机唤起飞书；httpOnly Cookie 会话（access 2h / refresh 30d）
- **多用户隔离**：所有数据按登录用户过滤，越权访问返回 404；每用户每日 3 次生成配额
- **智能菜谱生成**：异步任务（`202 + task_id`，前端轮询，可关页面）；同一周已有草稿直接复用不重复消耗额度
- **营养均衡校验**：按日汇总热量与三大营养素供能比，偏差写进告警
- **预算控制**：按 `ingredient.reference_price` 真实计价，超支告警而不阻断生成
- **多样性控制**：与近 4 周历史菜名做 Jaccard 比对，冲突自动重生成一次
- **过敏源防线**：命中过敏源的菜品从落库前剔除并在响应中告警
- **周菜单可视化编辑**：7 天 × 餐次卡片，支持换一道、锁定/解锁（锁定餐次不被重生成覆盖）、标记已做
- **采购清单**：菜单所需 vs 冰箱库存的差集，含缺口数量与单位换算，支持一键复制
- **库存闭环**：标记已做 → 临期优先扣减库存 → 写 `consumption_record`；缺料不阻断并返回明细
- **响应式前端**：<1024px 底部 TabBar，≥1024px 左侧导航

**二期（未启用，不影响上线）**

- 小象超市采集（Playwright 登录态、商品库、价格快照、食材-商品匹配、deeplink 补单）
- 飞书 Bot 推送（签名校验、消息回复、定时任务）

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python 3.12 / FastAPI / SQLAlchemy 2.0 async / aiomysql |
| 数据库 | MySQL 8.0 (utf8mb4) / Alembic 迁移 |
| 任务 | DB 表 + 进程内 worker (`SELECT ... FOR UPDATE SKIP LOCKED`) |
| 认证 | 飞书网页应用扫码 + 自签 JWT (httpOnly Cookie) |
| LLM | GLM-4 → Qwen-Max → DeepSeek（本地模型可选降级） |
| 前端 | React 18 / Vite 6 / TypeScript / Ant Design 5 |
| 部署 | nginx + systemd + certbot（见 `deploy/README.md`） |

## 快速启动

### 方式一：一条命令（推荐）

```bash
bash scripts/setup_local.sh
```

脚本会自动装 MySQL 8.0 / Python 3.12、建库建号、生成 `.env`、建表、导入种子数据、
装前端依赖并跑一遍测试。完成后开两个终端：

```bash
make dev-backend    # 终端 1
make dev-frontend   # 终端 2 -> http://localhost:5173
```

本地默认开启「本地开发登录」（免飞书）与「演示模式」（免 LLM Key），开箱即用。
完整步骤、排障表与手动兜底流程见 **[docs/local-setup.md](docs/local-setup.md)**。

### 方式二：手动分步

环境已经就绪时：

```bash
make setup      # 后端 pip install -e ".[dev]" + 前端 npm install
cp .env.example .env   # 填 APP__DATABASE__URL / APP__AUTH__JWT_SECRET / LLM Key
make migrate    # alembic upgrade head, 建 17 张表
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
│   │   ├── models/       # 17 张表的 ORM 定义
│   │   ├── schemas/      # Pydantic 请求/响应模型与序列化
│   │   └── services/     # 生成流水线、菜单、库存、采购、营养、预算、多样性
│   ├── alembic/          # 迁移脚本 (0001_init 为基线)
│   └── tests/            # unit / integration / e2e
├── frontend/             # React + Vite 前端
├── config/               # default.yaml 与 Prompt 模板
├── deploy/               # nginx / systemd / MySQL 初始化 / 上线手册
├── docs/                 # 本地部署、架构、上线、飞书配置
└── scripts/              # 种子数据与备份脚本
```

## 文档

- [架构设计](docs/architecture.md)
- [本地部署指南（傻瓜版）](docs/local-setup.md)
- [部署指南](docs/deployment.md)
- [上线手册（生产）](deploy/README.md)
- [飞书扫码登录配置](docs/feishu-setup.md)

## 免责声明

本工具仅供个人学习与家庭使用。二期涉及的小象超市数据采集为非官方实现，可能违反平台服务条款，
使用者需自行承担相关风险；本期功能不包含任何采集行为。

## License

MIT
