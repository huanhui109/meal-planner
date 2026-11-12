# CHANGELOG

本仓库采用 **语义化版本（SemVer）** 作为唯一权威版本号，当前版本 **2.9.0**。
版本号在以下 6 处机器可读位置保持一致，修改时须同步更新：

- `pyproject.toml`（`[project].version`）
- `backend/app/main.py`（`FastAPI(version=)`）
- `frontend/package.json` / `miniapp/package.json` / `shared/package.json`（`version`）
- `frontend/src/lib/app-version.ts`（`APP_VERSION`，由 `frontend/tests/app-version.test.ts` 钉住与 `frontend/package.json` 一致）

另有 3 处文档字面量需同步：`README.md`、`README_EN.md` 与本文件顶部；两个
`package-lock.json` 的 `version` / `packages[""].version` 也须跟随。

> **关于 `V2.x` / `V3.0` 标签**：历史提交信息使用 `Vx.x` 作为**产品规划里程碑**编号，
> 不代表已发布的 SemVer 版本。自 2.6.0 起，代码版本号与规划里程碑不再强绑定——
> 里程碑的落地以本文件的 SemVer 为准。

## [未发布 / Unreleased]（仍为 2.9.0，不升版本）

把 2.9.0 里并行的两套助手链路（WorkBuddy 官方 OAuth「网页直发 / 两阶段回执」与默认关闭的「双向唤醒」九端点）**合并为一套统一模式**：由网页应用直接发起模型请求。版本号保持 **2.9.0 不变**，不引入新技术栈；新增迁移 `0028_recipe_provenance`（仅加两列，不改既有表结构与数据）。

- **应用内直接发起模型请求**：网页点「交给 AI 调整」后，由应用后端在**本机已授权的助手连接**可用时
  直接发起一次流式模型请求；刷新后的凭据只留在进程内存，请求本身不携带刷新凭据。模型可由
  设置页目录（含倍率与免费标记）选择，或用 `APP__WORKBUDDY__MODEL` 指定。连接不可用时如实降级，
  不影响规则推荐。
- **单一入口与状态**：设置页一张融合「助手连接」卡（直连模型状态 + 旧 Skill 凭据），这一餐页
  一个「交给 AI 调整」按钮；新增 `GET /api/assistant/model` → `{available, region, model, message}`。
  任务状态新增 `calling`：`sending → calling → completed | failed | cancelled`。
  `/api/assistant/adjustments*` 对外不变，`start` 建任务、`poll` 在单事务内完成
  「直连模型 → 解析 JSON → 服务端二次校验 → `MealService.propose()`」（`source='assistant'` /
  `status='proposed'`）；失败以可读中文终止、0 次自动重发、原方案不变，不自动接受／扣库存／发外部消息。
- **应用内 WorkBuddy 技能 `fandecide-candidates`（低延迟候选菜品）**：新增
  `skills/fandecide-candidates/SKILL.md` + `contract.json`，把**触发条件、输入内容、输出字段、
  默认候选数量（4 个，范围 3–5）、低延迟约束**写成规格；可执行真源在
  `backend/app/services/dish_candidate_skill.py`（常量、独立 system contract、短 prompt、
  严格解析与「不得杜撰」校验，含字段到 `recipe` 列的反向映射）。调用入口
  `dish_candidate_service.py` + `POST /api/assistant/candidates`：单跳、一次模型请求、
  20s 硬超时、不追问／不重试／不展开分析，返回结构一致、可反向落库的候选；
  `persist=true` 时仍由服务端按同一个 `write_dish()` 裁决入池（证据列 +
  `recipe_enrich_log(expand)`）。旧「交给 AI 调整」的补全改为委托同一份契约，
  数量口径统一为默认 4、范围 3–5，两条入口不再漂移。`skill.zip` 附带
  `fandecide/candidates/{SKILL.md,contract.json}`；`shared/meal.ts`（`DishCandidate*` 类型
  并补齐 `AssistantAdjustment.source / generation_note`）、`shared/endpoints.ts`
  （`assistantCandidates`）、`frontend/src/api/meals.ts`（`requestDishCandidates()`）同步接入。
- **AI 调整链路低延迟优化**：`WorkBuddyModelClient.chat()` 对**所有**应用内模型请求下发
  `max_tokens`（默认 1200）/ `temperature`（默认 0.0），两者可按配置关闭；
  并按 prompt 固定首行 `PROMPT_LEAD` 把 system contract 自动路由到候选技能，
  修掉「给生成候选的任务发送选菜契约（不得新增候选）」这一自相矛盾的指令；
  「交给 AI 调整」里的补全调用也套上同一 20s 短超时（`asyncio.wait_for`，超时即降级、
  不写库、原方案不变），不再可能等满外层 90s。新增可选配置
  `APP__WORKBUDDY__CHAT_MAX_TOKENS` / `CHAT_TEMPERATURE` / `CANDIDATE_TIMEOUT_SECONDS`（默认 20s）。
- **测试**：新增契约／服务／真端点冒烟用例，含注入已知违规的反向验证（假菜名／
  无依据／空话步骤／散文回复必须被拒）、`contract.json` 与 Python 常量一致性断言、
  端点 401 / 422 / 降级 / `persist` 落库 / `skill.zip` 打包验证。
- **「禁止杜撰」的定义化例外：按需求补全候选**（迁移 `0028_recipe_provenance`，新增
  `recipe.reality_basis` / `recipe.generated_for` 两列）：用户**只描述大致需求**（未点名具体菜）
  且现有候选不足以组织这一餐时，允许 AI 提名默认 4 道（3–5 道）**现实中确实存在**的菜写入候选池。
  触发三条件：未点名具体菜（保守意图判定）、候选确实不足、AI 判定值得补。生成六道校验：
  菜名形态（2–20 字、无句读/量词/价格/营销词/泛称）、现实依据（12–200 字且含菜系/做法/配料等
  具体信息）、可执行做法（3–12 步、禁止「适量/若干/买现成」）、与库内去重、落库前再跑
  `guess_is_dish`、默认 4 道且范围 3–5。写入带 `source='ai_generated'` + 两列证据 + 一条
  `recipe_enrich_log(expand)`，任务 `view()` 带 `generation_note` 可追溯。与选菜 skill 的作用域
  互斥：选菜 skill 无权新增候选，补全 skill 能否入池由服务端决定，**两者都不放宽禁止编造**。
  生成失败不致命（限流/超时/JSON 非法只记 note，继续用现有候选）。
- **修复**：`WorkBuddyModelClient._http_failure` 在流式响应未读取时调用 `response.json()` 会抛
  `ResponseNotRead`，把干净的上游 4xx 变成意外异常；现在先 `aread()` 并吞掉任何解析错误。
- **点名菜品的近似匹配 + 缺菜时生成补全**：用户说「西蓝花」而池里是「蒜蓉西兰花」时不再误报
  「没有这道菜」——新增 `match_candidates` 三档匹配（同名/去烹饪手法同核心名/包含），并在
  `ALIAS_PAIRS` 补 `西蓝花→西兰花`、`花椰菜→西兰花`、`大白菜→白菜`；命中后把 key 作为
  `named_matches` 显式传给模型并钉进候选裁剪结果，模型不得再回答「没有」。点名菜品池里确实
  没有时，改走补全：以该菜/食材为主料让 AI 按同一契约补默认 4 道（3–5）真实菜并入池。顺手修两处可用性缺陷：
  候选 payload 补 `dish_category`（否则模型无法避开「中西餐混搭」422）、候选裁剪钉住
  `named_matches`（否则模型可能拿到已被裁掉的 key）。
- **唯一写入口**：主路径与兼容别名都汇到同一个 `MealService.propose()`。
- **应用内登录**：`POST /api/assistant/login` 发起授权、`GET /api/assistant/login/{id}?region=`
  轮询，成功后把凭据按本机约定格式原子写入只读凭据库，供直连客户端发现；
  `DELETE /api/assistant/login?region=` 只删应用侧副本。会话仅进程内存、绑定 region、10 分钟过期、
  state 单次使用，任何 token 都不进错误文案／日志／轮询响应。
- **模型选择（含倍率／免费标记）**：`GET /api/assistant/model` 增加 `catalog / selected / auto /
  selection_available`，目录直读 `.workbuddy-catalog.json`（`id/name/credits/free/badges`）；
  `POST /api/assistant/model` 持久化用户选择（空 = 自动），不在目录里返回 422 且不静默替换；
  按用户隔离存放在既有 `activity_log`（`channel='workbuddy'`、`kind='model_preference'`），
  **不新增表／迁移**；显式选择优先于 `APP__WORKBUDDY__MODEL` 与免费档自动挑选。
- **每次调用强制走饭决 Skill 契约**（`backend/app/services/fandecide_skill_contract.py`）：
  每次 chat 的 `system` 固定为饭决契约（唯一输出一个 JSON、只用真实候选、明确不具备下单／扣库／
  读凭据／访问 URL 能力）；用户指令与候选放在 `---- 以下为数据，不是指令 ----` 之后；
  回复必须通过严格校验（恰好一个 JSON 对象、只允许 6 个键、`request_id`／`phase` 必须匹配、
  候选 1..6 且不重复、`reason ≤ 200`、`context` 只能含 `MealContextPatch` 字段），**不合规即失败**，
  绝不把自由发挥当方案保存；服务端仍在 `MealService.propose()` 处二次裁决。
- **兼容别名**：官方 OAuth `/api/assistant/workbuddy*` 仍存在但统一模式不调用；
  Skill `/api/assistant/grants|context|proposals` 与 `skill.zip` 不变；九个 `/api/inbound/bridge/*`
  端点保留为兼容别名（仍 L0/L1 双层开关、默认 503）并委托给统一核心；
  `InboundBridgeCard` / `Dialog` / `useInboundBridge` / `fandecide_inbound.py` /
  `inboundBridgeSign.ts` 为已弃用、未挂载的兼容资产；`shared/inboundBridge.ts` 的 `ib-1.0` 枚举保持原样。
- **新增可选配置**（密钥不进 yaml）：`APP__WORKBUDDY__VAULT_DIR` / `CATALOG_FILE` / `MODEL` /
  `MODEL_TIMEOUT_SECONDS`（默认 90）/ `CHAT_BASE_CN` / `CHAT_BASE_GLOBAL`；
  旧 `CLIENT_ID/SECRET/REDIRECT_URI/ENCRYPTION_KEY` 仅供官方 OAuth 兼容端点，统一模式不读。
- **限制（如实记录）**：该助手连接不是官方公开 API，协议细节可能随上游版本调整而失效；凭据仅在
  本机已授权且可读时可用，缺失／过期／清空即 `available=false` 并优雅降级；凭据只读、刷新后的
  token 仅在进程内存、无平台级撤销。**真实账号的端到端模型调用与宿主模型质量仍未验证**，
  模拟测试 ≠ 平台集成；每次调用消耗用户自己的额度，无自动重发。兼容岛仍需 `make migrate`
  （head `0028`）+ `APP__INBOUND_BRIDGE__ENABLED=true` + L1 打开，统一主路径不依赖该开关。

## [2.9.0] - 2026-11-06

以「这一餐」为核心的用餐工作台首次发布，并将此前未提交的 2.9.0 实现一次性纳入版本库。
旧 `/api/decide`、周菜单、采购等接口保持兼容，旧数据未搬移或删除；小程序端暂停新增功能。

- **这一餐工作台**：新增 `/`、`/kitchen`、`/history`、`/me` 页面与迁移 `0024_meal_workspace`；
  自动给出完整一餐，支持家庭人数、做饭/外卖、预算、参考用时、辣度与临时忌口；
  展示 / 拒绝 / 选定 / 吃过四态分离，默认不扣库存、主动扣库可撤销（独立扣库收据）。
- **饭决 Skill**：`skills/fandecide/`（Skill 说明 + 本机 CLI），由 `/api/assistant/skill.zip` 分发；
  仅有 `meal:read` / `meal:propose` 作用域，凭据只存 SHA256、可撤销，
  候选 key 一律由服务端校验。
- **可选直连 WorkBuddy + 统一助手连接**：网页编辑要求后直接发送并回显新方案，支持刷新恢复、
  取消与离线复制；OAuth 凭据加密存储，单次授权 state 防重放、自动刷新。
  头像设置合并网页直发与 Skill 凭据管理。新增迁移 `0025_assistant_bridge`。
- **双向唤醒模块（独立特性，默认关闭）**：新增迁移 `0026_inbound_bridge`，
  本次只补齐入站能力，不替换既有通道：
  - 九端点入站网关统一挂在 `/api/inbound/bridge/*`；事件白名单默认拒绝，
    命中永久禁止清单（如下单、支付、确认吃过、扣库存、发外部消息）一律 403。
  - 双向令牌对：库内只存 SHA256 哈希与 Fernet 密文，明文仅颁发时显示一次；支持单端
    轮换 / 撤销、时间窗与 `event_id` 防重放、归属隔离与四元回执匹配。
  - L0（`APP__INBOUND_BRIDGE__ENABLED`，默认 `false`）与 L1
    （`inbound_bridge_config.enabled`，默认 `0`）双层开关；关闭时入站端点返回 503，
    快速推荐、既有 `/api/assistant/adjustments` 旧桥与 Skill 连接完全不受影响
    （**补门不换桥，旧桥共存**）。
  - 全模块唯一写入口是 `MealService.propose()`，只保存建议（`source='assistant'` /
    `status='proposed'`），不自动确认吃过、扣库存或发外部消息。
- **公开仓库整理与脱敏**：移出内部数据库快照、本地工作台原型与过程文档（本地保留）；
  小程序 AppID、个人绝对路径、局域网 IP 与内部链接改为占位或移除；
  中英文 README 与本文档按当前代码口径重写，修正表数、路由模块数与依赖版本漂移。
- **修复迁移 0026 的 downgrade（MySQL 1553）**：`inbound_task.pair_id` 的外键落在复合索引
  `ix_inbound_task_pair_status` 的 `pair_id` 前缀上，直接 `DROP INDEX` 会被外键约束挡住，
  而先删父表又会被子表外键挡住。改为不单独删索引、按「先子表后父表」直接删表
  （索引随表消失）；已在干净 MySQL 8.0 上验证 `upgrade head → downgrade base → upgrade head`
  全链通过。该缺陷由 CI 的迁移往返检查首次暴露，本地库因历史结构不同没有触发。

> **联调状态**：真实 WorkBuddy 账号未完成平台级联调（真实 OAuth 授权、在线发送、
> 宿主模型质量）。本次验收均为本地模拟与自动化测试，模拟通过不等于线上可用。

## 代码整理与开源化 - 2026-10-12（2.8.0 期间，未单独发版）

本节记录 2.8.0 发布之后的仓库整理：本次无功能变更，只修缺陷、补文档、换许可证，
**版本号保持 2.8.0 不变**，不构成 SemVer 的 minor/patch 发布；2.8.0 的功能变更见下一节。

- **修复两个运行时 Bug**
  - `backend/app/api/decide.py`：`status.HTTP_404_NOT_FOUND` 用到的 `status` **未导入** →
    `/decide/{id}/cook` 查不到记录时 NameError → 500
  - `backend/app/services/inventory_service.py`：`delete_item` 参数是 `user_id`，代码却写
    `user.id` → 删除库存接口必崩
- **修复 CI 门禁失效（这两个 Bug 能活到主线的根因）**
  - `.github/workflows/ci.yml` 补上 `TEST_DATABASE_URL`。此前**142 条集成用例全部 skip**，
    线上实际只跑 759 条 —— skip 是 absence 不是 presence
  - 同一 workflow 的 ruff 步骤去掉 `|| true`。正是它让 lint 永远"看起来是绿的"
- **修复迁移 0023 的 downgrade**（MySQL 1828）：`decision_id` 带外键却在 downgrade 里
  直接 `drop_column`，MySQL 报"needed in a foreign key constraint"。
  根因是该外键**没命名**（MySQL 自动生成 `consumption_record_ibfk_3`）—— 0023 是仓库里
  唯一没遵守 `fk_*` 命名约定的迁移。已显式命名 `fk_consumption_decision`，
  downgrade 改为先删约束与索引再删列（并兼容已跑过旧版、约束仍是 `ibfk_N` 的库）
- **修复小程序设计令牌漂移**：Demo 视觉变量原本**手写在自动生成**的
  `miniapp/src/styles/_tokens.scss` 里，导致 `check-tokens` 长期报警；已迁出到独立的
  `_demo-tokens.scss`（H5 一直把 Demo 变量放在手写的 `demo.css`，与之对齐）。
  ⚠ 教训：`gen_tokens --check` **通过 ≠ 文件完整** —— 直接 `make gen-tokens` 会清掉
  生成文件里的手写内容，生成物里不要手写
- **修复锁文件漂移（`npm ci` 其实是失败的）**
  - `miniapp/package-lock.json` 缺 `ajv` / `ajv-keywords` / `json-schema-traverse`；
    `frontend/package-lock.json` 里 vite 是 6.x、vitest 是 2.x，而 package.json 要 7.x / 3.x。
    两个 `npm ci` 都会在 CI 上报错，但被 `npm ci || npm install` 兜底抹平 ——
    **兜底重新解析出一个和锁文件完全不同的依赖树**，本地复现不出来。两个锁文件已重新生成，
    CI 与 deploy 的 `|| npm install` 一律摘掉：锁文件漂移必须红
  - **miniapp 的 webpack 收敛到 `~5.104.0`**。这不是随手锁版本，是一个三方死锁：
    - Taro 4.2.1 的 `peerDependencies` 把 webpack 钉在 **5.91.0**，`webpackbar@5`
      又会把自己那份 options（`name`/`color`/`reporters`/…）**覆写**到继承来的
      `this.options` 上
    - webpack **< 5.94 有已知漏洞**，不能降
    - webpack **≥ 5.106** 把 `ProgressPlugin` 的 options 校验从构造函数挪到了 `apply()`，
      正好校验到被 webpackbar 覆写后的 `this.options` → `ValidationError`，
      `build:weapp` 直接崩
    - 所以唯一可行区间是 `5.94.0 ≤ version < 5.106.0`，取 `~5.104.0`
    - （webpackbar 升 6 同样有覆写问题；升 7 修好了 options，但删掉了 Taro 子类依赖的
      `callReporters` / `updateProgress`，走不通）
- **补上测试依赖 `aiosqlite`**：`tests/test_decision_context_real_chain.py` 刻意自建
  SQLite 内存库跑真链路（理由见该文件头注释），但 `aiosqlite` 只装在本地 venv、
  没写进 `pyproject.toml` 的 `[dev]`，于是 CI 上以 `ModuleNotFoundError` 报 error。
  同时删掉 CI 里手写的 `pip install pytest pytest-asyncio httpx` —— 手写清单会和
  pyproject 漂移（aiosqlite 就是这么漏的）。测试依赖的唯一真源是 `pyproject.toml`
- **新增**：`docs/codebase-audit.md`（全项目代码分析）、`README_EN.md`（英文说明）、`LICENSE`
- **开源化**：仓库由私有转为公开，采用 MIT 许可证；README 移除"私有/不开放源代码"声明

## [2.8.0] - 2026-10-08

把 2.7.0 里新增、但当时没有任何消费方的「孤儿端点」接到两个真实交付面（H5 + 小程序），
让「今日做完了」真正按后端返回扣库存。

- **今日「做完了」改成真扣库存**（本次核心）
  2.7.0 之前 `cookDone()` 只打点 —— 那时后端确实没有"按决策扣库存"的接口，前端做一个
  假的"已扣库存"提示是在骗用户。现在 `POST /decide/{id}/cook` 已上线且幂等，H5
  （`stores/useDecideStore.ts`）与小程序（`components/decide-board.tsx`）都改调它，
  并把结果逐档如实告知，不再一律说"已扣减"：
  - `no_recipe`（离线/本地菜）→「没法精确扣库存」
  - `already_cooked`（幂等命中）→「这顿已经做完并扣过」
  - `missing > 0` →「已扣库存，N 样没扣到」
  - 离线兜底结果（`id === 0`）→ 服务端没有决策记录，明确说没扣，不假装有结果
  - 请求失败 → 不阻断主流程，提示可到冰箱手动调整
  ⚠ 顺序约定：**先 await 后端结果、后切 done 态**。反过来会先把"完成"演完再告诉用户没扣成。
- **补齐共享接口契约**：`shared/endpoints.ts` 新增 `decideCook` / `inventoryBulk`；
  两端 API 客户端新增 `cookDecision` / `searchInventory` / `bulkAddInventory` /
  `updateInventoryItem`（对应 2.7.0 的 `/decide/{id}/cook`、`GET /inventory?q=`、
  `POST /inventory/bulk`、`PUT /inventory/{id}`）
- **仓库卫生**：清理仓库内 ~146 个 macOS `「 2」` 重复垃圾文件
  （原文件移至 `/tmp/mealplanner-trash/` 可恢复；它们会让 `tsc` 直接报错）

## [2.7.0] - 2026-10-08

饭决极简屏 `fandecide/` 五大模块重构（UI + 后端联调），版本号 2.0.0 → 2.7.0 与仓库统一。

- **今日页**：以「饭决」大按钮为核心，点击生成结果卡；支持「换一道」切换菜品；状态推进
  「就这个 → 开始做 → 做完了」，做完了调用 `POST /api/decide/{id}/cook`（幂等，依赖
  `decision_log.is_cooked`）自动扣减冰箱库存
- **周菜单**：7 天网格重排，按天查看与调整；支持锁定 / 换菜 / 标记做过（做过后自动扣库存）；
  新增「重新排一周」（按冰箱现有食材 `fridge-rebuild`，保留锁定餐次）；菜单响应新增 `budget` 字段
- **采购清单**：按库存自动汇总缺料（`GET /api/shopping/{menu_id}`），支持勾选与一键复制
- **冰箱**：食材搜索（`GET /api/inventory?q=`）、新增、删除、快速入库
  （`POST /api/inventory/bulk`、`PUT /api/inventory/{id}`）
- **我的/偏好**：抽屉式入口，五组偏好（家庭/口味/忌口/目标预算）可编辑，外观主题切换
  （auto/light/dark，持久化到 localStorage）
- 新增后端迁移 `0023_decision_cooked`：`decision_log.is_cooked` + `consumption_record.decision_id`，
  打通「今日决策 → 扣库存」链路

## [2.6.0] - 2026-09-29

统一版本号并补全文档（本次整理）。

- 引导系统重构（V2.6）：`shouldAutoShowGuideNow()` 纯读判断与 `markGuideAutoShown()`
  显式标记分离，修复 `reLaunch` 不重建 JS 上下文导致的回弹死循环
- 多端交付面补齐：饭决极简屏 `fandecide/`（Vite + React + TS，仅前端，复用 `/api/decide`）
  接入说明写入 README
- 文档修正：README 移除 `MIT` 开源协议声明（本仓库为私有仓库）、补 `fandecide/` 结构与功能、
  新增本 CHANGELOG

## [2.5.0] - 已落地（规划里程碑，未单独发版）

- 真·深色主题 + 命名收敛 + `auto` 跟随系统
- 主题宿主类 `gen_tokens.mjs` 输出全量 58 个设计令牌

## [2.4.0] - 已整合（规划里程碑，未单独发版）

- `feat/v2.4-merge-and-theme` 分支：决策引擎定稿 + 主题系统整合

## [1.2.0] - 上一正式发布

- 本地菜谱库优先（proj.kitchen + HowToCook）的决策引擎定稿
- 对外道数口径：342 道（`is_dish=1` 的真菜）

## Roadmap / 规划中（非发布版本）

规划里程碑 V3.0，以下子项**尚未完成**：

- 真实数据采集链路
- 法务签字 / 服务条款落地
- ICP 备案
- 真机实测

因此 3.0.0 暂不作为发布版本。
