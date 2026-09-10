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
│  │ MySQL 8.0 / utf8mb4 / 19 张表                            │  │
│  └──────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────┘
                                │  HTTP /api
┌───────────────────────────────▼────────────────────────────────┐
│                      客户端 (两端同一套功能)                     │
├────────────────────────────────────────────────────────────────┤
│  H5: React 18 + Vite + TypeScript + Ant Design 5               │
│      底部胶囊 TabBar (<1024px) / 左侧导航 (>=1024px)            │
├────────────────────────────────────────────────────────────────┤
│  小程序: Taro 4 + React (miniapp/)                              │
│      自定义胶囊 TabBar, 视觉与 H5 一致                          │
└───────────────────────────────┬────────────────────────────────┘
                                │  @shared/*  (纯 TS, 零框架依赖)
┌───────────────────────────────▼────────────────────────────────┐
│  shared/  类型 · 格式化 · 下一步规则 · 接口路径 · 设计令牌       │
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
| 认证 | 飞书扫码 / 微信小程序一键登录 + 自签 JWT | H5 走 httpOnly + Secure + SameSite=Lax Cookie；小程序走 `Authorization: Bearer` |
| LLM | OpenAI 兼容 SDK | GLM-4 → Qwen-Max → DeepSeek → 本地可选 |
| 定时 | APScheduler | 菜单/缺料/临期推送；默认关闭，多 worker 用 MySQL `GET_LOCK` 保证只有一个进程注册 |
| 前端 | React 18 + Vite 6 + Ant Design 5 | 移动优先自适应 |
| 状态 | Zustand + React Query | 轻量高效 |

## 数据模型 (18 表)

- **用户侧 (6)**：`user`、`household`、`diet_preference`、`allergy_restriction`、`health_goal`、`budget`
- **内容 (3)**：`ingredient`(含 `reference_price`)、`recipe`、`recipe_ingredient`(含 `amount_text`)
- **外部 (2)**：`product`、`product_mapping`
- **运行 (7)**：`fridge_inventory`、`consumption_record`、`menu`、`menu_item`、`menu_generation_task`、`purchase_record`、`activity_log`

> 单一字段 `user_id` 贯穿所有用户侧数据；所有查询都带 `user_id` 过滤，越权一律 404。

### 身份命名空间

`user.open_id` 存的是"第三方身份字符串"，用前缀区分来源，**因此新增登录方式不需要加表或加列**：

| 前缀 | 来源 | 写入方 |
|------|------|--------|
| `ou_...` | 飞书 open_id | `POST /api/auth/feishu/callback` |
| `wechat:` | 微信小程序 openid | `POST /api/auth/wechat/mini-login` |
| `dev:` | 本地开发登录的昵称 | `POST /api/auth/dev-login`（仅 `APP__AUTH__DEV_LOGIN=true`） |

三种账号**并存且互相隔离**：同一个自然人用微信和飞书登录会得到两个互不可见的账号，
本期不做账号合并。`UserService.upsert_from_identity()` 是唯一的落库入口，
`upsert_from_feishu` / `upsert_from_wechat` 都是它的薄封装。

## 核心链路：生成 → 编辑 → 采购 → 库存

1. `POST /api/menus/generate`
   - 同一周已有 `draft/confirmed` 时直接复用（`force=false`），不消耗 LLM 额度。
   - 否则按用户当日 `menu_generation_task` 计数，超过上限返回 429。
   - 配额分两档（`is_regeneration` 区分）：首次生成 `menu.daily_generation_limit`（默认 3），
     重新生成同一周 `menu.daily_regenerate_limit`（默认 10）。两者互不占用 —— 重生成是常规编辑动作，
     不该被探索额度卡住。
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
   缺料不阻断，返回 `missing` 明细。撤销（`DELETE .../cooked`）反向执行：批次行还在就加回原行，
   已被扣空删除的按流水里的 `ingredient_id`/`unit` 重建，然后删掉这批流水。
6. 今日聚合：`GET /api/today` 一次返回餐次 + 预算 + 采购缺口 + 补单建议 + 自做/外卖 + 临期 + 时间线，
   任何一块缺失都不让整页失败（没菜单就返回 `ready.has_menu=false`，由前端渲染空状态）。

## V2.0 新增接口

| 接口 | 说明 |
|------|------|
| `GET /api/today` | 今日页一次拿全（`TodayOverview`） |
| `POST /api/today/takeout-price` | 记住外卖参考价，写回 `budget.takeout_reference_price` |
| `GET /api/menus/{id}/order-suggestion` | 补单建议（缺口 + 起送价凑单 + 预算判定 + deeplink） |
| `DELETE /api/menus/{id}/items/{item_id}/cooked` | 撤销「标记已做」，回滚库存与消耗流水 |
| `POST /api/inventory/recognize` | 拍照识别（multipart），只返回候选清单，受 `llm.vision.daily_limit` 限流 |
| `GET /api/automation/status` | 飞书连接 / 调度器 / 提醒时间 / 最近推送记录 |
| `GET/PUT/DELETE /api/automation/feishu` | 用户自己的飞书应用凭证（App Secret 加密存储、只写、只回掩码） |
| `POST /api/automation/feishu/test` | 用当前凭证发一条测试消息，立刻验证参数对不对 |

**不依赖爬虫**：补单价格用 `ingredient.reference_price` 估算，外卖价用用户参考价（默认 ¥26），
起送价走配置；`deeplink_service` 只做模板化跳转。`scraper/matching/product` 三个服务保持占位（二期）。

## 共享层 (shared/)

`shared/` 是纯 TS、零框架依赖的目录，被 H5（Vite alias）与小程序（Taro alias + `mini.compile.include`）
同时引用，避免两端各写一份导致行为漂移：

| 文件 | 内容 |
|------|------|
| `types.ts` | 全部接口类型（含 `ApiEnvelope`） |
| `format.ts` | 金额/数量/热量/日期/进度的统一格式化 |
| `labels.ts` | 周几、餐次、品类、状态的中文文案 |
| `next-step.ts` | "下一步该做什么"的决策函数（两端同源） |
| `today.ts` | 今日页展示映射：时间线三态、补单文案、外卖结论、预算百分比 |
| `brand.ts` | 品牌名/副标/本地数据说明，两端唯一文案源 |
| `endpoints.ts` | 接口路径常量 |
| `tokens.ts` | 设计令牌唯一真源，由脚本生成两端的样式文件 |

`node scripts/gen_tokens.mjs` 生成 `frontend/src/styles/tokens.css` 与
`miniapp/src/styles/_tokens.scss`；`make ci` 会跑 `--check`，生成物一旦与源不一致就失败。
详见 [docs/design-system.md](design-system.md)。

## 关键设计决策

1. **多用户**：无 `DEFAULT_USER_ID`，所有查询以 token 中的 `user_id` 为准；越权返回 404 而非 403，避免探测。
2. **异步生成**：生成耗时数秒到数十秒，接口不阻塞；前端 2.5s 轮询任务状态，可离开页面。
3. **成本真实化**：`ingredient.reference_price`（元/标准单位）为唯一价格来源，单位为 `None` 时计入
   `unpriced_items` 而不是臆造价格；预算超支只告警不阻断。
4. **状态机**：`menu.status` 走 `draft → confirmed → active → completed`；`draft/confirmed` 可编辑可复用。
5. **单一方言测试**：集成测试跑 MySQL（与生产同方言），避免「SQLite 上能过」的假绿。
6. **安全收口**：`debug=false`、`DATABASE_ECHO=false`、CORS 收紧到自有域名、日志不打印密钥与 token。
7. **全局生成状态**：生成任务的状态放在 `useGenerationStore`（Zustand）而不是页面组件里，
   页面切走不中断轮询，TabBar/头像上的进度点也据此渲染。
8. **可撤销优先于二次确认**：换一道、标记已做都是"先做完再给后悔窗口"——
   二次确认会打断所有人，后悔窗口只影响真的点错的人。撤销必须真实回滚数据，不能只改界面。
### 飞书机器人凭证为什么按用户存

飞书应用凭证决定「消息以谁的身份发出去」，而 `tenant_access_token` 只能发给该应用
可用范围内的人。一个家庭里每个人的飞书租户不同，部署方配一份覆盖不到所有人 ——
所以做了 `user_feishu_config`（一人一份，按 `user_id` 隔离），解析顺序是
**用户自己的配置 → 部署默认配置（`feishu.*` / `APP__FEISHU__*`）→ 视为未配置**。

* App Secret 用 `app/services/secret_box.py` 加密后入库（密钥由 `APP__AUTH__JWT_SECRET`
  经 HKDF 派生），接口只回掩码，提交时留空表示沿用原值。
* 没配飞书的用户照常使用全部功能，只是收不到推送 —— `_send_all` 会直接跳过他们，
  不写失败流水（「没配」不是错误）。

9. **诚实的降级**：没配视觉模型就置灰并引导手动添加；没配飞书就显示"未配置"而不是假装已连接；
   外卖没有实价就用用户参考价，并把"这是参考价"写在界面上。
