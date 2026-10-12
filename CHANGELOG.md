# CHANGELOG

本仓库采用 **语义化版本（SemVer）** 作为唯一权威版本号，当前版本 **2.8.0**。
版本号在以下 4 处保持一致，修改时须同步更新：

- `pyproject.toml`（`[project].version`）
- `backend/app/main.py`（`FastAPI(version=)`）
- `frontend/package.json` / `miniapp/package.json` / `shared/package.json`（`version`）

> **关于 `V2.x` / `V3.0` 标签**：历史提交信息与 `docs/` 下的规划文档（如
> `requirements-v2.3.md`、`requirements-v2.5-dark-mode.md`、`v3.0-scraper-spec.md`、
> `product-v2.md`）使用 `Vx.x` 作为**产品规划里程碑**编号，不代表已发布的 SemVer 版本。
> 自 2.6.0 起，代码版本号与规划里程碑不再强绑定——里程碑的落地以本文件的 SemVer 为准。

## [Unreleased] - 2026-10-12

代码整理与开源化。**版本号保持 2.8.0 不变** —— 本次无功能变更，只修缺陷、补文档、换许可证，
不构成 SemVer 的 minor/patch 发布。完整分析见 [docs/codebase-audit.md](docs/codebase-audit.md)。

- **修复两个运行时 Bug**
  - `backend/app/api/decide.py`：`status.HTTP_404_NOT_FOUND` 用到的 `status` **未导入** →
    `/decide/{id}/cook` 查不到记录时 NameError → 500
  - `backend/app/services/inventory_service.py`：`delete_item` 参数是 `user_id`，代码却写
    `user.id` → 删除库存接口必崩
- **修复 CI 门禁失效（这两个 Bug 能活到主线的根因）**
  - `.github/workflows/ci.yml` 补上 `TEST_DATABASE_URL`。此前**142 条集成用例全部 skip**，
    线上实际只跑 759 条 —— skip 是 absence 不是 presence
  - 同一 workflow 的 ruff 步骤去掉 `|| true`。正是它让 lint 永远"看起来是绿的"
- **修复小程序设计令牌漂移**：Demo 视觉变量原本**手写在自动生成**的
  `miniapp/src/styles/_tokens.scss` 里，导致 `check-tokens` 长期报警；已迁出到独立的
  `_demo-tokens.scss`（H5 一直把 Demo 变量放在手写的 `demo.css`，与之对齐）。
  ⚠ 教训：`gen_tokens --check` **通过 ≠ 文件完整** —— 直接 `make gen-tokens` 会清掉
  生成文件里的手写内容，生成物里不要手写
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

## [3.0.0] - 规划中（未完成，勿据此发版）

规划里程碑 `v3.0-scraper-spec.md`，以下子项**尚未完成**：

- 真实数据采集链路
- 法务签字 / 服务条款落地
- ICP 备案
- 真机实测

因此 3.0.0 暂不作为发布版本。
