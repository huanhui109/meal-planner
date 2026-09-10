# AI 每周营养菜谱工具 - 架构设计

## 系统架构

```
                        浏览器 (手机 H5 / 桌面)
                                │ HTTPS 同源
┌───────────────────────────────▼────────────────────────────────┐
│                        nginx (443)                             │
│  托管 frontend/dist  ──  /api/* (limit_req)  ──  /feishu/*      │
└───────────────────────────────┬────────────────────────────────┘
                                │ 127.0.0.1:8000
┌───────────────────────────────▼────────────────────────────────┐
│                    FastAPI 后端 (Python 3.12)                   │
│                                                                │
│  API 层   auth / preferences / menus / inventory / products    │
│      │          get_current_user (JWT httpOnly Cookie)          │
│  ┌───▼──────────────────────────────────────────────────────┐  │
│  │  服务层                                                  │  │
│  │  MenuService       读取/编辑/成本/营养/预算/序列化        │  │
│  │  GenerationPipeline 上下文 → LLM → 落库 → 校验            │  │
│  │  RecipeService     菜谱与用量归一化落库                   │  │
│  │  Nutrition / Budget / Diversity / Pricing  四项校验       │  │
│  │  Inventory / Shopping      库存扣减与采购差集             │  │
│  └───┬──────────────────────────────────────────────────────┘  │
│      │                                                         │
│  ┌───▼──────────────────┐   ┌──────────────────────────────┐   │
│  │ GenerationWorker     │   │ LLM 降级链                    │   │
│  │ (lifespan 内常驻)     │──▶│ GLM-4 → Qwen-Max → DeepSeek   │   │
│  │ FOR UPDATE SKIP LOCKED│   │ → (可选) 本地 mlx_lm          │   │
│  └───┬──────────────────┘   └──────────────────────────────┘   │
│      │                                                         │
│  ┌───▼──────────────────────────────────────────────────────┐  │
│  │ SQLAlchemy 2.0 async + aiomysql + Alembic                │  │
│  │ MySQL 8.0 / utf8mb4 / 17 张表                            │  │
│  └──────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────┘
                                │
┌───────────────────────────────▼────────────────────────────────┐
│              React 18 + Vite + TypeScript + Ant Design 5       │
│  底部 TabBar (<1024px) / 左侧导航 (>=1024px)                    │
│  登录 · Dashboard · 周菜单 · 采购清单 · 库存 · 偏好             │
└────────────────────────────────────────────────────────────────┘
```

## 技术选型

| 组件 | 技术 | 说明 |
|------|------|------|
| 后端框架 | FastAPI 0.115+ | 异步, 自动 OpenAPI |
| ORM | SQLAlchemy 2.0 (async) | `aiomysql` 驱动；`asyncmy` 作为可选加速 |
| 数据库 | MySQL 8.0 / utf8mb4 | 多用户 + `SKIP LOCKED` 任务队列 |
| 迁移 | Alembic | 唯一建表方式, `alembic upgrade head` |
| 任务队列 | DB 表 + 进程内 worker | 单机无 Redis, `SELECT ... FOR UPDATE SKIP LOCKED` |
| 认证 | 飞书扫码 + 自签 JWT | httpOnly + Secure + SameSite=Lax Cookie |
| LLM | OpenAI 兼容 SDK | GLM-4 → Qwen-Max → DeepSeek → 本地可选 |
| 定时 | APScheduler | 二期推送任务使用 |
| 前端 | React 18 + Vite 6 + Ant Design 5 | 移动优先自适应 |
| 状态 | Zustand + React Query | 轻量高效 |

## 数据模型 (17 表)

- **用户侧 (6)**：`user`、`household`、`diet_preference`、`allergy_restriction`、`health_goal`、`budget`
- **内容 (3)**：`ingredient`(含 `reference_price`)、`recipe`、`recipe_ingredient`(含 `amount_text`)
- **外部 (2)**：`product`、`product_mapping`
- **运行 (6)**：`fridge_inventory`、`consumption_record`、`menu`、`menu_item`、`menu_generation_task`、`purchase_record`

> 单一字段 `user_id` 贯穿所有用户侧数据；所有查询都带 `user_id` 过滤，越权一律 404。

## 核心链路：生成 → 编辑 → 采购 → 库存

1. `POST /api/menus/generate`
   - 同一周已有 `draft/confirmed` 时直接复用（`force=false`），不消耗 LLM 额度。
   - 否则按用户当日 `menu_generation_task` 计数，超过 3 次返回 429。
   - 通过校验后写入 `pending` 任务，接口立刻返回 `202 + task_id`。
2. `GenerationWorker`（进程内，并发 2）
   - `_claim()` 用 `FOR UPDATE SKIP LOCKED` 抢占一条 `pending`，置为 `running`。
   - 启动时 `recover_stale_tasks()` 把超时的 `running` 扫回 `failed`，用户可重试。
   - LLM 调用阶段**不持有数据库连接**；一次生成只调一次 LLM，多样性不达标再补一次。
   - 落库：`recipe` + `recipe_ingredient`（数量归一化，原文存 `amount_text`）→
     `menu_item.estimated_cost = Σ(数量 × reference_price)` → 营养/预算/多样性校验。
   - 命中过敏源的菜品直接剔除并写入 `warnings`。
3. 编辑：换一道 / 锁定 / 解锁 / 标记已做；锁定餐次在重生成时被保留，不会被覆盖。
4. 采购清单：`GET /api/menus/{id}/shopping-list` 输出「冰箱已有 / 需买」差集（含缺口与单位换算）。
5. 库存闭环：标记已做 → 按 `recipe_ingredient` 扣减 `fridge_inventory`（临期优先）→ 写 `consumption_record`；
   缺料不阻断，返回 `missing` 明细。

## 关键设计决策

1. **多用户**：无 `DEFAULT_USER_ID`，所有查询以 token 中的 `user_id` 为准；越权返回 404 而非 403，避免探测。
2. **异步生成**：生成耗时数秒到数十秒，接口不阻塞；前端 2.5s 轮询任务状态，可离开页面。
3. **成本真实化**：`ingredient.reference_price`（元/标准单位）为唯一价格来源，单位为 `None` 时计入
   `unpriced_items` 而不是臆造价格；预算超支只告警不阻断。
4. **状态机**：`menu.status` 走 `draft → confirmed → active → completed`；`draft/confirmed` 可编辑可复用。
5. **单一方言测试**：集成测试跑 MySQL（与生产同方言），避免「SQLite 上能过」的假绿。
6. **安全收口**：`debug=false`、`DATABASE_ECHO=false`、CORS 收紧到自有域名、日志不打印密钥与 token。
