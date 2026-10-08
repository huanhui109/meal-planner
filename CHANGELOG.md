# CHANGELOG

本仓库采用 **语义化版本（SemVer）** 作为唯一权威版本号，当前版本 **2.7.0**。
版本号在以下 4 处保持一致，修改时须同步更新：

- `pyproject.toml`（`[project].version`）
- `backend/app/main.py`（`FastAPI(version=)`）
- `frontend/package.json` / `miniapp/package.json` / `shared/package.json`（`version`）

> **关于 `V2.x` / `V3.0` 标签**：历史提交信息与 `docs/` 下的规划文档（如
> `requirements-v2.3.md`、`requirements-v2.5-dark-mode.md`、`v3.0-scraper-spec.md`、
> `product-v2.md`）使用 `Vx.x` 作为**产品规划里程碑**编号，不代表已发布的 SemVer 版本。
> 自 2.6.0 起，代码版本号与规划里程碑不再强绑定——里程碑的落地以本文件的 SemVer 为准。

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
