# 饭决：这一餐

## 产品入口

- `/`：自动读取当前餐次，没有方案时发起快速推荐。人数、做饭/外卖、预算目标、参考用时、辣度和临时忌口可调整。
- `/kitchen`：可选库存，支持增、改、删、搜索和保质期；空库存不会阻止推荐。
- `/history`：最近 50 份建议，区分待决定、已换掉、已选定与已吃过。
- `/me`：偏好、系统深浅色、可撤销的助手连接，以及旧菜单入口。
- `/preferences`：逐步设置家庭人数、辣度、过敏与长期忌口；不是首次使用的必填流程。

主流程：建议 → 选定 → 查看做法或点单要求 → 记录吃过。换方案没有强制锁定次数。外卖只提供品类、备注与搜索链接，不提供虚构商家、实价或送达时间。

## 领域结构

```text
轻网页 → WorkBuddy OAuth → 本地助手的两阶段回执
   | 用户会话                         饭决 Skill + Python CLI
   |                                  | 可撤销的作用域凭据
   +-------------- MealService -------+
                  |
       MealCatalog：真实菜谱候选、过滤、整餐校验
                  |
       session / proposal / event / stock_movement
```

- `MealSession`：用户、日期、餐次唯一；保存条件、当前方案和递增 revision。
- `MealProposal`：完整一餐的菜品快照，明确标注 `quick` 或 `assistant` 来源。
- `MealEvent`：分别记录 proposed、viewed、rejected、accepted、eaten、undone；看过和计划过不计入已吃历史。
- `MealStockMovement`：独立扣库收据，保留批次、原保质期和数量；撤销吃过时恢复库存。即使原批次已被删除也能恢复已消费部分。
- `AssistantGrant`：仅存凭据 SHA256，90 天有效，可随时撤销，只有 `meal:read` 与 `meal:propose`。
- `WorkBuddyConnection`：逐用户保存加密的 OAuth 凭据，单次授权 state、防重放、自动刷新和本地断开；不暴露 OAuth token 给网页或模型。
- `AssistantAdjustment`：持久化发送和等待状态、用户要求、版本与方案回执，支持刷新恢复、幂等请求、超时和取消。

新页面和 Skill 都调用同一个服务。旧 `/api/decide`、周菜单、采购等接口保持兼容，旧数据未搬移或删除。小程序没有新增功能。

## 约束与数据边界

- 服务器以当前用户过滤所有读写；助手凭据不能作为普通网页 JWT 使用。
- 修改方案需要 `expected_revision`。MySQL 用户行锁串行化同一账号的变更，锁定读取保证拿到最新版本；过期提交返回 409。
- 接受、完成、撤销可重复提交，不重复写吃过事件或扣库存。选定不扣库；“吃过”默认也不扣库，只有用户勾选才尝试精确扣减。
- 家庭餐为完整主食餐加蔬菜，或主菜、蔬菜和主食。显式忌口、辣度、餐次和已知厨具条件在服务端再次校验，不能被 AI 覆盖。
- 新推荐池排除把人数、泛称主料或厨具误导入食材的旧记录；不把未知小吃当蔬菜，也不把纯粥或面包当完整一餐。常见食材别名与零辣度的明确辣味配料另行校验，不仅依赖旧标签。
- “避开近期”只读取新用餐已吃记录和旧系统明确标记已做的记录。未选定或只展示过的菜不进入七日饮食历史。
- 无可靠原始份数就不推测用量；无完整参考价格或不能换算单位就不显示整餐成本。预算为目标，未核验时明确提示。
- 食材匹配及菜谱信息不能保证商家配料、交叉接触或实际制作过程，外卖需向商家确认。不能可靠理解的旧长期文字限制会阻止推荐并要求明确，不静默忽略。
- 快速推荐不调用模型。Skill 使用宿主助手理解自然语言，只从服务返回的候选 key 组织方案。
- AI reason 作为独立建议保存，不覆盖服务端基于真实数据生成的解释。

## 迁移与启动

已配置 MySQL 和 JWT 的已有环境：

```sh
cd backend
../.venv/bin/alembic upgrade head
../.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

另一个终端：

```sh
cd frontend
npm run dev -- --host 127.0.0.1
```

`0024_meal_workspace` 新建 5 张表并增加 `recipe.base_servings` 可空字段，不删除旧数据。开发服务器已用端口需要换一个；代理默认连接 8000。

`0025_assistant_bridge` 增加 `workbuddy_connection`、`assistant_adjustment` 两张表。更新代码后同样执行 `alembic upgrade head`，不修改既有用餐记录。

当前本地库存在此前控制台扩展表、字段、索引等与 ORM 不一致的历史结构，因此全库 `alembic check` 不是干净基线。本次新增的 5 张表及 `recipe.base_servings` 已单独比对；没有自动生成迁移去覆盖既有结构。

生产环境部署须一并包含根目录 `skills/fandecide`，供已登录用户下载。全新环境仍按 `docs/local-setup.md` 配置登录方式与数据库。开发登录不可暴露到公网。

## 网页直连 WorkBuddy

设置页统一为“助手连接”，通过“连接助手”在同一弹窗内选择“网页直发”或“Skill 连接”。未配置 WorkBuddy 应用时默认进入可用的 Skill 流程，连接入口不会因后台状态检查而禁用。连接状态、凭据创建及授权请求最多等待 15 秒，超时后可重试或刷新确认；凭据创建响应丢失时不自动重发，应撤销未取得密钥的凭据后重建。

网页直发是主动调用通道，安全授权仍与 Skill 访问凭据分开。只安装 Skill 或创建饭决凭据并不代表网页获得了 WorkBuddy 调用权限；有效凭据也不代表宿主助手在线。状态检查失败不会阻止 Skill 连接。

1. 在 [WorkBuddy 开放平台](https://open.workbuddy.cn/docs/openapi) 创建应用，取得 `clientId`、`clientSecret`，为应用开启 `user.localassistant.readable` 和 `user.localassistant.invokable`。
2. 仅在服务端配置以下环境变量，密钥不要放进前端、聊天或代码：

```dotenv
APP__WORKBUDDY__CLIENT_ID=应用的clientId
APP__WORKBUDDY__CLIENT_SECRET=应用的clientSecret
APP__WORKBUDDY__REDIRECT_URI=http://127.0.0.1:5173/api/assistant/workbuddy/callback
```

回调必须与开放平台登记地址逐字一致；生产用 HTTPS。本地回环 HTTP 是否被应用配置接受仍需使用真实开发者账号核验。前后端分域部署时，回调的 `/me` 应通过同源反向代理回到前端。

3. 重启后端后，在网页“偏好与设置 → 助手连接 → 连接助手 → 网页直发”点击“授权 WorkBuddy”，完成官方 OAuth 授权。保持电脑上的 WorkBuddy 在线。此流程无需另建 Skill 凭据。
4. 点击“交给 AI 调整”，编辑自然语言要求并发送。服务先要求助手返回条件补丁，再读取符合这些条件的候选，让助手返回组合。饭决再次校验候选、完整一餐、硬忌口及原始 revision 后保存；不会自动接受、记吃过或扣库存。
5. 网页自动轮询回显。可关闭弹窗继续等待，刷新后恢复正在处理的任务。取消等待或断开连接后不再保存迟到的回执；本地断开会删除饭决保存的 OAuth 凭据，但不是 WorkBuddy 平台级撤销，平台级权限需在 WorkBuddy 授权管理中撤销。

实现使用官方 `/openapi/v2/authorize`、`/token`、`/localassistant` 和 `/localassistant/message`，回复按发送时的 `message_id` 增量查询。只接受匹配随机 `request_id` 与阶段的完整 JSON 回执，不读取或展示用户的其他助手对话，也不代替用户回答宿主工具审批。网页直连使用完整任务内的回执协议，不依赖本地 CLI 的凭据配置；独立 Skill 对话继续使用 CLI。

OAuth 凭据使用 Fernet 认证加密；可配置 `APP__WORKBUDDY__ENCRYPTION_KEY`（至少 32 字符）作为稳定专用密钥，未设置时从 JWT 密钥以独立域派生。加密密钥变更后重新授权。默认总等待 300 秒、轮询 3 秒；429 或暂时网络故障退避，发送状态不明确时不自动重发。进程重启后未确认的发送会终止为可恢复失败，绝不盲目补发。

没有配置应用、未授权或助手离线时，输入仍可编辑并复制为完整任务；规则快速推荐完全不受影响。本项目不提供虚构应用凭据，也未声称真实 WorkBuddy 账号已完成联调。

## 独立 Skill 连接

1. 在网页“偏好与设置 → 助手连接 → 连接助手 → Skill 连接”中下载 `fandecide.zip`，按宿主助手的本地 Skill 安装方式导入。项目提供可移植 Skill 目录，不自动修改全局助手配置，也未发布到技能市场。
2. 点击“创建 Skill 凭据”，在同一弹窗中复制凭据。凭据只显示一次，不发到聊天或公共日志。已有凭据无需重复创建；已过期、已撤销与有效状态分别展示，可在“助手连接”统一撤销。此流程不要求配置 WorkBuddy 开放平台应用，但不会启用网页自动发送。
3. 在 Skill 所在目录的可信本地终端运行：

```sh
python3 scripts/fandecide.py connect --url http://127.0.0.1:5173
```

凭据在隐藏输入中录入，保存到 `~/.config/fandecide/connection.json`（0600）。远程服务要求 HTTPS，本机回环地址允许 HTTP。客户端拒绝重定向，不把凭据放在参数、任务文本或错误输出里。

4. 网页“交给 AI 调整”输入要求后复制任务。助手先 `context`，按真实候选和最新 revision 组织方案，再 `save --file proposal.json`。网页回到前台或等待至多约 15 秒便读取同一餐。
5. 在网页撤销连接后，后续助手请求返回 401。凭据不含确认吃过、扣库存、下单或撤销记录的权限。

CLI 支持 `status`、`context`、`save`。完整流程和请求字段在 `skills/fandecide/SKILL.md`。尚未代替用户在 WorkBuddy 客户端执行安装；宿主模型的自然语言理解质量需要家庭试用验证。

## 双向唤醒模块（2.9.0）

这是与上述网页直连、Skill 连接**并存的独立特性**，定位是「补门不换桥」：新增一组入站端点与信任中心，不改变既有通道。模块**默认关闭**。

**九端点**（统一挂 `/api/inbound/bridge/*` 前缀，路径单真源是 `shared/endpoints.ts` 的 `ENDPOINTS.inboundBridge*`）：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/events` | 网页侧入站事件 |
| POST | `/receipts` | 助手侧回执 |
| GET | `/status?task_id=` | 任务状态查询 |
| GET | `/poll` | 助手侧降级拉取（签名 envelope 放 `X-Inbound-Envelope` 头） |
| POST | `/pair` | 颁发双向令牌对 |
| POST | `/pair/{id}/rotate?side=` | 单端轮换 |
| DELETE | `/pair/{id}?side=` | 单端撤销 |
| GET | `/allowlist` | 事件白名单枚举 |
| GET | `/audit?limit=` | 审计查询（仅安全字段） |

**双层开关**：L0 是 `APP__INBOUND_BRIDGE__ENABLED`（默认 `false`，进程启动读取），L1 是 `inbound_bridge_config.enabled`（默认 `0`，请求级读取）；两层同时为真才放行，关闭时端点返回 503，快速推荐、既有 `/api/assistant/adjustments` 旧桥与 Skill 连接完全不受影响。

**信任与生命周期**：令牌对库内只存 SHA256 哈希与 Fernet 密文，明文仅颁发时显示一次；会话有效期 12h（`pair_ttl_seconds=43200`）、7d 强制轮换（`rotation_days=7`），审计保留 90d（`audit_retention_days=90`）。事件白名单默认拒绝，版本 `ib-1.0`；事件枚举、版本、状态文案与错误码的单真源是 `shared/inboundBridge.ts`，端点路径单真源是 `shared/endpoints.ts`。

**唯一写入口**：`backend/app/services/inbound_bridge/validator.py` 的 `ReceiptValidator.commit()` 是全模块唯一调用 `MealService.propose()` 的位置，只保存建议（`source='assistant'` / `status='proposed'`），不自动下单、确认吃过、扣库存或发外部消息。

**验收口径**：**真实 WorkBuddy 账号未完成平台级联调，模拟验收不等于真实联调**。上述能力目前仅经本地模拟与自动化测试验证，不代表真实平台授权、在线发送或宿主模型质量已通过。

## 验证与家庭试用

```sh
# 独立行为测试，无需 MySQL
.venv/bin/python -m pytest backend/tests/test_meal_workspace.py backend/tests/unit/test_fandecide_cli.py

# 真 MySQL 测试，TEST_DATABASE_URL 必须指向专用的 *_test 库
# 测试会清空该测试库，不能指向实际使用的数据库。
APP__AUTH__DEV_LOGIN=false APP__LLM__DEMO=false \
  .venv/bin/python -m pytest backend/tests/

cd frontend
npm test
npm run build
```

真实 CLI 闭环验证（仅限已开启开发登录的本地服务，必须指定独立验收昵称）：

```sh
.venv/bin/python scripts/smoke_meal_skill.py --name 饭决验收账号
```

这会创建临时助手连接、保存晚餐建议、核对网页当前方案并撤销凭据，不确认用餐或扣库。

建议连续两周观察：首次展示到接受的耗时、每餐换方案数、建议到选定比例、实际吃过情况与家庭口头反馈。基础事件已落库，但没有凭空给出采纳率预测，也没有启用主动提醒、自动下单或自动跟踪任务。

### 验收原则与联调状态

- 后端与前端改动须分别通过完整单测 / 集成测试、生产构建、Lint 与 Ruff 检查；
  涉及授权、并发与撤销的场景在真实 MySQL 上验证，不依赖内存库近似。
- 浏览器侧覆盖 360×800 / 768×1024 / 1440×1000 三档视口，检查横向溢出、
  深色与减少动态效果；凭据截图只允许出现密码掩码，验收创建的凭据与临时数据必须撤销清理。
- 助手链路的自动化脚本按官方协议模拟 OAuth 与消息响应。
  **真实 WorkBuddy 账号未完成平台级联调**：真实授权、在线发送与宿主模型质量均未验收，
  模拟测试通过不等于真实平台联调完成。
