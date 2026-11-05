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
