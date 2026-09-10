# 每周鲜 V2.0 产品迭代方案

> 本文是 V2.0 的产品真源：命名与 Logo、信息架构、首页层级、各模块交互，以及
> 参考稿功能点 → 落地实现的完整映射。代码实现见 `frontend/`、`miniapp/`、`backend/`。

## 一、参考稿拆解结论

参考稿（`workbuddy.link/p/Oy8hOLKscfJdUe8EBrA0kl`）的产品定位是
**"把一周吃饭这件事交给 AI 排好"** 的闭环工具：

```
偏好即约束 → 生成周菜单 → 校验营养预算 → 补单 → 做饭扣库存
```

它的信息架构是 4 个 Tab：

| Tab | 承载概念点 | 核心内容 |
|---|---|---|
| 今日 | F4 自做 vs 外卖、F6 补单决策 | 日期/工作日/晚餐预算头 → 补单卡 → 今晚菜单卡 → 自做 vs 外卖 → 今日流程时间线 |
| 周菜单 | F2 生成与校验 | 周日期 + AI 生成时间 → 本周预算进度 → 周均营养目标 → 重新生成（锁定保留） |
| 冰箱 | F5 库存与临期 | 件数 + 自动入库/扣减说明 → 临期 banner → 按到期排序 → 拍照识别 / 手动添加 |
| 我的 | F1 偏好、F7 机器人 | 家庭与厨房 / 口味与安全 / 目标与预算 / 自动化 四组，右侧当前值 + 状态点 |

**交互约定**：实心黑胶囊主按钮（一屏一个）、浅灰胶囊次按钮、按压 `scale(.965)`、
Tab 浅灰底 + 毛玻璃悬浮、中性灰承载 95% 面积、颜色只表语义。

### 与本产品的缺口（V2.0 要补的）

补单决策卡、自做 vs 外卖、今日流程时间线、拍照识别、机器人状态卡——
V2.0 之前全部未实现；`scraper/matching/product` 服务是空壳。

**关键取舍**：V2.0 **不依赖任何爬虫**，用"采购缺口 + 起送价凑单 + deeplink 跳转"
替代抓取，用"用户参考价"替代外卖实价，用"视觉大模型"替代自研识别。
这让所有参考稿功能都能真跑起来，同时不触碰平台条款风险。

## 二、命名与 Logo

### 命名

**每周鲜 · AI 营养菜谱**（副标 `AI 营养菜谱`，短称 `每周鲜`）。

- "每周" 直指产品的时间尺度（一周一次生成、一周一次采购）。
- "鲜" 同时覆盖「新鲜食材」与「现做」两层意思，比"菜谱工具"更有画面感。
- 唯一文案源在 `shared/brand.ts`，H5 标题、小程序 `navigationBarTitleText`、
  登录页、飞书卡片全部从这里取，避免各处叫法不一致。

### Logo

矢量唯一源 `assets/logo/*.svg`，几何由 `scripts/gen_logo.mjs` 生成，只用现有令牌三色
（`ink` / `ink-2` / `accent`），不引新色：

```
    ●  ●            ← 外圈 7 个圆点 = 一周 7 天, "今天"那点是绿色实心
   ╭────╮
   │  🍃 │          ← 碗口上方两片叶子 (叶脉断线) = "鲜"
   │ ╰──╯ │         ← 碗的侧剖轮廓 (半圆 + 底弧)
   ╰──────╯
```

- 主图形：28px 圆角方底。深色版 `ink` 底 + 白色图形；浅色版 `fill` 底 + `ink` 图形。
- 变体：`logo-mark.svg`（仅图形，用于头像/图标）、`logo-full.svg`（图形 + 名称 + 副标）、
  `logo-mono.svg`（单色，用于飞书卡片与深色底）。
- 交付物：`frontend/public/{logo-mark.svg,favicon.svg,favicon.png,logo-mark@2x.png}`、
  `miniapp/src/assets/{logo-mark.png,share-icon.png}`、`miniapp/src/lib/logo.ts`（data URI）。
- 规范：安全区 = 图形高度 25%；最小使用 24px；禁止拉伸、换色、加投影。
  详细规则见 `docs/design-system.md`。

## 三、信息架构重构

```
TabBar(4)   今日  /  周菜单  /  采购  /  冰箱
                     └─ 头像 → 我的（抽屉/独立页）→ 偏好四组（二级表单）
周菜单 → 日卡 → 做法与食材（折叠） / 换一道（弹层）
采购 → 一键复制 / 补单跳转
```

- 旧 5 Tab（首页/菜单/采购/库存/设置）→ **4 Tab**，「我的」从 TabBar 摘除。
- H5 路由：`/` = 今日、`/menus` = 周菜单、`/shopping` = 采购、`/inventory` = 冰箱；
  `/me` 是「我的」的直连入口，实际交互由右上角头像打开抽屉（≥1024px 右侧抽屉，
  <1024px 底部 sheet）；`/preferences?focus=<key>` 是二级页，进入后自动滚到对应分组。
- 小程序：`tabBar.list` 收敛为 `today|menu|shopping|fridge`，
  `pages/profile` 保留但移出 TabBar，由今日页右上角头像 `navigateTo` 打开。
- 「我的」抽屉压一条 history 记录，所以手机返回手势可以直接关掉，不丢失原本的页面与滚动位置。

## 四、首页（今日）信息层级

从上到下，**一屏只有一个黑胶囊主按钮**：

| 顺序 | 区块 | 用户价值 | 数据来源 |
|---|---|---|---|
| 1 | 问候 + 日期/星期/工作日 | 确认"我在看今天" | `TodayOverview.date` |
| 2 | 今日预算条 | 今天还能花多少，一眼看到 | `budget.remaining_today` |
| 3 | 下一步卡（仅未就绪时） | 3 秒内知道该干嘛 | `shared/next-step.ts` |
| 4 | 补单决策卡 | 缺几样、够不够起送价、直接下单 | `GET /api/today` 的 `order` |
| 5 | 今晚菜单卡 | 做什么、多久、消耗哪些临期、多少热量 | `today.tonight` |
| 6 | 自做 vs 外卖 | 今天到底该动手还是点外卖 | `takeout_service` |
| 7 | 本周概览磁贴 | 预算/营养/临期/进度四块 | `today.week` |
| 8 | 今日流程时间线 | 自动流程到哪一步了 | `activity_log` + `consumption_record` |

**为什么把"下一步卡"做成条件渲染**：菜单就绪后，真正的下一步就是补单或做饭，
这两件事已经有自己的卡片了。再挂一张"下一步"卡只会稀释主行动。

**Bento Grid**：窄屏 2 列、≥1024px 6 列，卡片按重要性跨列（预算 2×1、营养 1×1、临期 1×1、进度 2×1）。

## 五、「周菜单」与「今日」的功能布局

### 周菜单

- **周头卡**：日期区间 + `由 AI 于 M月D日 HH:mm 生成`（来自 `menu.created_at`）+
  状态胶囊（待确认/已确认）+ 预算进度条 + 周均营养（日均 kcal、蛋白/碳水/脂肪占比）
  + 「重新生成（锁定的餐次原样保留）」。
- **星期条**：选中黑底白字，今天多一个绿点；从今日页跳进来会自动定位到今天。
- **日卡**：餐次行 = 菜名 + 已锁定/已做胶囊 + 时长/热量/成本 + 行内胶囊操作
  （换一道 / 锁定 / 做完了）；食材与做法收在折叠里，默认不展开，避免一屏全是字。
- **整周日列表**：一眼扫完整周，点任意一天跳到对应日卡。

### 今日（与周菜单的分工）

- 今日只回答"**今天**"的问题：吃什么、缺什么、自己做还是点外卖。
- 需要"改菜单"时，从今日跳到周菜单，而不是在今日页里重复一遍编辑能力。
- 补单卡提供「调整菜单」按钮直达周菜单，避免用户自己去找。

## 六、参考稿功能点 → 落地实现

| 概念稿元素 | 落点 | 数据来源 / 降级 |
|---|---|---|
| 周菜单头（日期 + 生成时间） | 周菜单页 | `menu.created_at` + `scheduler.weekly_generation` |
| 本周预算进度条 | 周菜单 / 今日概览 | `BudgetSummary`（`weekly_cap` 或 工作日×5+周末×2） |
| 周均营养目标 | 周菜单页 | `HealthGoal` + `NutritionSummary` |
| 重新生成（锁定保留） | 周菜单页 | `POST /api/menus/generate`，文案说明锁定餐次不被覆盖 |
| **补单决策卡** | 今日页 / 采购页 | `GET /api/today`、`GET /api/menus/{id}/order-suggestion` |
| **今晚菜单卡** | 今日页 | `MenuDetail` + 临期食材 ∩ 今晚菜谱 |
| **自做 vs 外卖** | 今日页 | `takeout_service`：自做价 = `menu_item.estimated_cost`，外卖价 = `budget.takeout_reference_price` |
| **今日流程时间线** | 今日页 | `activity_log` + `consumption_record` |
| 冰箱件数 + 自动入库/扣减说明 | 冰箱页 | `GET /api/inventory` + 静态说明 |
| 临期 banner（已排入今晚菜单） | 冰箱页 | 临期食材 ∩ 今晚菜谱 |
| **拍照识别** | 冰箱页 / 今日页 | `POST /api/inventory/recognize` → 视觉大模型 → 候选清单 → 用户确认 |
| 我的 4 分组 + 当前值 + 状态点 | 我的抽屉 | 5 张偏好表重排为 4 组，新增「外卖参考价」 |
| **机器人状态卡** | 我的抽屉 | `GET /api/automation/status` |
| "数据仅存储在本地" | 我的抽屉底部 | `brand.localDataNote` + 当前部署域名 |

参考稿里的**外卖对比细节、补单下单、拍照识别、机器人状态**全部实现；
参考稿里本产品没有的功能（多平台比价、积分、社区）不实现，只借用其视觉与信息层级。

### 关键交互细节

- **补单卡**：【立即下单】在小程序里优先 `navigateToMiniProgram`（配置了 `miniapp_app_id` 时），
  否则复制缺口清单并提示去小象超市搜索；H5 新标签打开 deeplink。
  【调整菜单】跳周菜单。
- **自做 vs 外卖**：卡片上改价后立即重算结论，失焦静默写回 `budget.takeout_reference_price`
  并提示"已记住，下次默认 ¥31"。结论三档——`homemade`（今晚推荐）/`takeout`（时间紧）/
  `either`，并给出"点外卖占当日预算，还能剩 ¥9"。
- **拍照识别**：拍照/相册 → 上传（≤6MB，服务端等比缩到 1280px）→ 识别中骨架 →
  候选卡逐条可编辑（名称/数量/单位/保质期）→【全部入库】。
  未配 Key 时提示"配置视觉模型后可拍照入库，也可以手动添加"，不阻塞任何既有流程。
- **今日流程时间线三态**：`sent`（绿点）/ `pending`（灰点，"待触发"）/
  `skipped`（灰字，"推送未开启"）/ `failed`（红点），点击跳到对应页面。
- **可撤销**：换一道、标记已做都是"先做完，再给后悔窗口"——换一道用 Toast（5 秒内可换回上一道），
  标记已做用 Toast 撤销（H5）或餐次行内的「撤销」（小程序），撤销会真的还原库存与消耗流水。
- **重新生成**：页面上明确写"锁定的餐次原样保留"，生成中可以离开页面，
  TabBar/头像上的橙点全局提示进度。

## 七、人机交互优化建议（按优先级）

### P0 —— 不做闭环就断

1. **一屏一主行动**：每页最多一个黑胶囊按钮，来源统一 `shared/next-step.ts`，
   禁止页面自行发明 CTA。
2. **生成可离开 + 全局可见**：生成中在 TabBar/头像显示进度点，任意页可回看任务状态，不阻塞导航。
3. **消耗与破坏性动作可撤销**：换一道 / 标记已做 / 重新生成 都给后悔窗口，
   撤销要真的回滚库存与流水，不能只是"界面变回去"。
4. **分级反馈替代 `alert`**：首屏 Skeleton → 动作内 loading → 失败 ErrorState + 重试；
   错误文案用户可读，不出现堆栈。
5. **移动端硬指标**：触摸目标 ≥44px、输入框 `font-size:16px`、`env(safe-area-inset-bottom)`、
   `100dvh`、`-webkit-tap-highlight-color:transparent`。

### P1 —— 决定"顺手不顺手"

6. **数字亲近感**：全程 `tabular-nums`；金额 1 位小数；热量/分钟取整；
   进度 `12/14 餐`；单位小号灰字跟在数字后。
7. **空状态即教学**：每张空卡 = 一句状态 + 唯一 CTA + 为什么（"填完生成结果会准很多"）。
8. **乐观更新 + 失败回滚**：标记已做、入库、锁定先改 UI 再补网络。
9. **选择优于输入**：份数/辣度/预算用 stepper 与 chip，键盘只在必要处出现；
   表单保存态明确（"已保存"文字而非弹窗）。
10. **语义色纪律**：绿=完成/充足，橙=注意，红=错误；颜色不用于装饰，两端同一语义同一色。
11. **路径可预期**：从今日→周菜单自动定位今天；从采购缺口→冰箱高亮对应食材；
    抽屉关闭回原页面原滚动位置。

### P2 —— 打磨

12. **微动效**：按压 `scale(.965)`、页面切换 `opacity + translateY(10px) + scale(.99)`、
    进度条数字滚动、生成中进度点呼吸。
13. **桌面增强**：≥1024px 左导航 + 主区（+ 我的右侧抽屉），次级操作 hover 才出现。
14. **无障碍与降级**：`prefers-reduced-motion` 关闭位移与呼吸动画、对比度 ≥4.5:1、
    暗色令牌预留但不启用。
15. **分享与复制**：采购清单一键复制为文本、小程序分享卡图标随 Logo 交付。

## 八、接口与数据模型变更

**新增接口**

- `GET /api/today` → `TodayOverview`（餐次 + 预算 + 采购缺口 + 补单建议 + 自做/外卖 + 临期 + 时间线）
- `POST /api/today/takeout-price` → 记住外卖参考价
- `POST /api/inventory/recognize`（multipart）→ 候选清单，受 `llm.vision.daily_limit` 限制（默认 20 次/日/人）
- `GET /api/automation/status` → 飞书连接 / 调度器 / 提醒 / 最近推送
- `GET /api/menus/{id}/order-suggestion` → 补单建议（采购页复用）
- `DELETE /api/menus/{id}/items/{item_id}/cooked` → 撤销标记已做

**数据模型（迁移 `0003_v2_today_and_brand` + `0004_consumption_identity`，17 → 18 张表）**

- `budget.takeout_reference_price: Float NOT NULL DEFAULT 26.0`
- 新表 `activity_log`：`user_id / channel / kind / title / detail / status / occurred_at`，
  索引 `(user_id, kind, occurred_at)`；推送、库存监测、拍照识别都写一条
- `consumption_record.ingredient_id / unit`：让流水自解释，撤销时能按原样补回库存行

**配置新增**：`app.name`、`llm.vision{enabled,model,max_image_mb,max_edge_px,daily_limit}`、
`platforms.*{search_template,miniapp_app_id,min_order_amount,delivery_note}`。

**占位服务处置**：`deeplink_service` 与 `order_service` 已填实；
`scraper_service` / `matching_service` / `product_service` 保持占位并在 docstring 标注"二期"，
不接进任何链路。

## 九、验收口径

- `make ci` 全绿（ruff + 273 项后端测试 + 令牌/Logo 校验 + 47 项前端测试 + 两端构建）。
- 端到端人工：登录 → 填偏好（含外卖参考价）→ 生成（可离开）→ 周菜单 7 天与总成本 →
  换一道/锁定 → 采购清单与补单卡 → 立即下单跳转 → 拍照识别入库 → 标记已做 → 撤销 →
  库存与今日时间线同步变化。
- iPhone SE / Pro Max / 桌面 1440px 无遮挡；对比度与触摸目标抽查。

## 十、明确不做（V2.0 范围外）

小象超市 Playwright 采集、微信/支付宝支付、多语言、SSE 流式输出、
法定节假日与调休表（推送简化为"周末不推送"）、暗色主题。
