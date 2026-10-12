# 全项目代码分析（2026-10-12）

> 本文是"分析并整理全部项目代码"的产出。方法上沿用 deep-research 的三段式
> （outline → 逐项深挖 → 汇总报告），但把 WebSearch 换成本地静态分析：
> 依赖方向靠 import 图，行为契约靠测试与注释，规模靠计数。

## 1. 规模概览

| 层 | 文件 | 说明 |
|----|------|------|
| `backend/app` | 118 个 .py / 19,257 行 | 35 个 service、21 个 model、14 个 API router |
| `frontend/src` | 52 个 .ts(x) | 13 个页面、9 个组件、5 个 store、14 个测试文件 |
| `miniapp/src` | 62 个 .ts(x) | 13 个页面（含 `fandecide`） |
| `shared/` | 14 个 .ts | H5 与小程序的**唯一真源** |
| 迁移 | 23 个 alembic 版本 | 0001 基线 → 0023 |
| 测试 | 后端 901 例（全绿） | 50 个测试文件，unit / integration / e2e 三层 |

## 2. 模块地图与依赖方向

```
                    ┌──────────────┐
                    │   shared/    │  ← 唯一真源：类型/格式化/令牌/业务规则/引导状态
                    │  纯 TS，零依赖 │
                    └──┬────────┬──┘
                       │        │
            ┌──────────▼──┐  ┌──▼──────────┐
            │  frontend/  │  │   miniapp/  │  两个交付面，各自独立工程
            │ React+Vite  │  │  Taro+React │
            └──────────┬──┘  └──┬──────────┘
                       │        │
                    ┌──▼────────▼──┐
                    │   backend/   │  FastAPI + MySQL
                    └──────┬───────┘
                           │
              ┌────────────▼────────────┐
              │  飞书 Bot / 定时任务      │  另一条入口，共用 service 层
              └─────────────────────────┘
```

**依赖方向是单向的**：`shared` 不依赖任何一侧；两个前端只依赖 `shared` 与后端 HTTP API；
后端不感知前端。这条方向一旦反转（例如把后端类型生成进 `shared`），跨端一致性就会失效。

### 后端 14 个 API router

| 前缀 | 职责 |
|------|------|
| `/decide` | 饭决决策五件套（核心） |
| `/today` | 今日页一次请求拿全 |
| `/menus` | 周菜单生成与编辑 |
| `/inventory` | 冰箱库存闭环 |
| `/recipes` | 菜品库与 LLM 富集 |
| `/preferences` | 偏好 / 忌口 / 预算 |
| `/auth` | 飞书扫码 + 微信一键登录 + JWT |
| `/products`、`/feedback`、`/events`、`/automation`、`/subscribe`、`/invite`、`/build-info` | 二期能力与运维 |

## 3. 决策引擎与离线同构（本项目最关键的契约）

`POST /api/decide` 承诺 **≤2 秒**返回，且**永远有答案**。这两条靠三处共同保证：

1. **服务端** `services/decision_service.py`：三条硬规则 + 纯规则理由（`reason_service.py`），
   决策链路**不调大模型**
2. **客户端** `shared/decide.ts` 的 `decideOffline()`：服务端决策的**同构子集**，
   纯函数、不碰网络与存储，配合 `shared/local-pool.generated.ts`（`LOCAL_DISHES`）在本地出菜
3. **一致性门禁** `backend/tests/test_decide_parity.py`：同一组输入断言两端输出集合一致

触发降级的三条路径（见 `frontend/src/stores/useDecideStore.ts` 的 `roll()` catch）：
断网（秒级失败）、服务端返回空/抛错（显式 `throw new Error('空结果')`）、
超时（`/decide` 单独设 **2500ms**，不是全局 30s —— 30s 是给异步生成任务留的）。

> ⚠ 契约红线：改任一侧的权重（`SCORE.*` / `SOFT_PREFERENCE_CAP` / `randomBand`），
> **必须同步改另一侧并跑 parity 测试**。软偏好包 CAP=4.0、`randomBand`=5.0 是硬约束，
> 幅度超过 5.0 的二元打分会把抽签带切成"抽得到 / 抽不到"两半。

## 4. 数据层

菜品表 `recipe` 是三层结构，每层回答不同问题：

- **基础层**：name / cuisine / steps / nutrition
- **决策层**（迁移 0014）：category / main_ingredient / tags / flavor_tags / spice_level /
  is_light / cover_text / quick_steps → 回答"好不好吃"
- **场景层**（迁移 0016）：meal_slots / meat_type / tools / season / enrich_status /
  enrich_source / steps_source → 回答"这一顿合不合适"

空值语义是**刻意设计**的：`meal_slots=NULL` = 不限制餐次；`meat_type=NULL` = 不知道
（不是"素"，否则忌口用户会吃到肉）。原则是"宁可不生效，不要生效成错的"。

对外道数口径：**342 道**（`is_dish=1` 的真菜）。396 只在写"recipe 全量"时使用且必须带限定词。

## 5. 测试与质量门禁

`make ci` 串起七道门禁：

```
lint(ruff) → pytest(901) → check-tokens → check-logo → check-pool
  → check-band(R-11 抽签带不塌缩) → test-frontend + build-frontend → check-miniapp
```

**本次整理发现并修复的问题**：

| # | 位置 | 问题 | 性质 |
|---|------|------|------|
| 1 | `backend/app/api/decide.py:140` | `status.HTTP_404_NOT_FOUND` 但 `status` **未导入** | **运行时 Bug**：`/decide/{id}/cook` 查不到记录时 NameError → 500。已补导入 |
| 2 | `backend/app/services/inventory_service.py:129` | 参数是 `user_id`，代码写 `user.id` | **运行时 Bug**：删除库存必崩。已改为 `user_id` |
| 3 | `miniapp/src/styles/_tokens.scss` | 与 `shared/tokens.ts` **漂移** | 破坏共享层单一真源。已 `make gen-tokens` 重新对齐（61 个令牌） |
| 4 | `decide.py` / `band_regression.py` | I001 import 未排序 | 已 `ruff --fix` |
| 5 | `.github/workflows/ci.yml` | **未设 `TEST_DATABASE_URL`** | **CI 假绿**：142 条需 MySQL 的用例全部 skip，线上一直只跑 759 例。已补变量 |
| 6 | `.github/workflows/ci.yml` | ruff 步骤带 `\|\| true` | 吞掉 lint 失败。已摘除并改为 `ruff check .` |

### 两个 Bug 为什么能活到主线

不是因为没人写测试，而是**门禁本身失效**了两处：

1. `.github/workflows/ci.yml` 的 ruff 步骤写的是 `ruff check app tests || true` ——
   **`|| true` 让 lint 永远"看起来是绿的"**，而且它只查 `app tests` 不查 `scripts`。
   本地 `make ci` 不带 `|| true`，所以一跑就暴露。
2. 同一个 workflow **没有设 `TEST_DATABASE_URL`**（只设了 `APP__DATABASE__URL`）。
   实测对比：

   | 环境 | 结果 |
   |------|------|
   | 未设 `TEST_DATABASE_URL`（改前的 CI） | **759 passed, 142 skipped** |
   | 设了（本地 `make ci`） | **901 passed, 0 skipped** |

   那 142 条正是整个集成层。**skip 是 absence 不是 presence —— 绿 ≠ 覆盖。**

两处都已修复。原则：CI 与本地 `make ci` 必须是**同一套门禁**，两套口径必然漂移。

## 6. 技术债与孤儿资产

| 项 | 现状 | 建议 |
|----|------|------|
| `fandecide/` 目录 | git 跟踪 **0 个文件**，`src/` 只剩 `.DS_Store`，但 `README.md` 仍把它写进功能清单与项目结构 | 文档层已标注为遗留；**本地目录未删除**，是否清理请作者确认 |
| README 版本漂移 | 写 2.6.0，实际 2.8.0 | 已修正 |
| CI 与 `make ci` 两套门禁 | 口径不一致（见第 5 节） | 统一为 `make ci` |
| 文档口径 | 30 篇文档，多为中文；部分写于 2.6 之前 | 本次补齐中英文 README |

## 7. 结论

代码整体**结构健康**：依赖方向单向、`shared` 单一真源、决策链路不依赖模型、
901 个测试覆盖 unit/integration/e2e 三层。

真正的风险不在架构，而在**门禁失效**——两个真实的运行时 Bug 之所以能活到主线，
不是因为没人写测试，而是因为 CI 里的 `|| true` 让 lint 永远"看起来是绿的"。
这与项目历史上"`/api/decide` 全量 831 测试绿但端点实际 500"是同一类问题：
**绿灯不等于可用**。修掉 `|| true`、让 CI 复用 `make ci`，比新增测试更能防止复发。
