# V2.4 需求说明 —— 合并与外观收口

> | 项 | 值 |
> |---|---|
> | 版本 | `0.5.0` |
> | 分支 | `feat/v2.4-merge-and-theme` |
> | 基线提交 | `06fae1b`（`main`） |
> | 合并来源 | `codex/menu-replace-local-first`（V2.1）+ `feat/recipe-library`（V2.3） |
> | 总案 | [`docs/master-plan.md`](master-plan.md) |

---

## 一、背景

仓库里有两条基于 V2.0 的本地版本分支，长期未合入 `main`：

- **`codex/menu-replace-local-first`** —— V2.1 的「换一道本地优先 + AI 降级」(R-29 / R-30)，配套有「冰箱列表按 `items` 解包」修复与版本台账记录
- **`feat/recipe-library`** —— V2.3 的「开源菜谱库 + 整周本地优先」(R-31 ~ R-34)，包含数据库文档生成器、`data/sql/recipes_seed.sql` 种子 SQL、本地编排打分与来源标注

两条分支都已通过 `make ci`，功能可用，但留在本地分支意味着：

1. 新装的开发机拿不到这些能力；
2. 任何后续工作要么 rebase 到老分支（高风险），要么从 `main` 重写（高浪费）；
3. 两套版本号（`pyproject.toml` 0.4.0 vs `package.json` 0.2.0）口径不一致越来越乱。

V2.4 的目标就是「**把两条分支合到 main 上、版本号统一、再把合并过程中暴露的外观回归修干净**」。

合并之外，本期还顺手修了一组 **V2.3 引入的外观系统回归**——这是用户在验收过程中发现的，单独提一组合并版次中处理：

- **gen_tokens.mjs 退化**：V2.3 把生成脚本改成「只输出 `--color-*`」双调色板，导致 `var(--font-*)` / `var(--shadow-*)` / `var(--layout-*)` / `var(--brand-*)` 全部失效——切换明亮主题后页面字号 / 圆角 / 阴影回到浏览器默认；
- **Logo 颜色映射反掉**：V2.3 的 LogoMark 把「明亮主题 → 深色容框」，导致明亮（奶油底）上显示了一个黑方块，跟品牌「Logo 与背景融为一体」的设想反掉；
- **菜单栏奶油底 / 暖橙色不生效**：受上面两点共同影响——色变量没生成出来 + Logo 颜色错了——视觉上「切换主题」好像没起作用；
- **外观切换入口冗余**：H5「我的」/ 小程序 profile 上的两行说明（"深色·黑色胶囊 / 明亮·暖色奶油"）信息密度过低，且描述带有营销文案；
- **小程序主题同步不到位**：H5 切换 `html[data-theme]` 即可，小程序只能在 `page.theme-light{}` 覆盖 + 顶部导航条颜色上做同步，部分场景下不一致。

---

## 二、目标

- **G1 主线合并**：V2.1 + V2.3 全部功能落入 `main`，生成单一的 `feat/v2.4-merge-and-theme` 合并分支，迭代到产品版本 V2.4 / 内部版本 `0.5.0`；
- **G2 外观系统稳**：让「切换主题」这件事在 H5 / 小程序上都真实可见——背景变奶油、按钮变黑胶囊、Logo 变白底容框——而不是只切了 `--color-bg` 别的都没变；
- **G3 极简化外观切换**：把 "外观" 这个分组从「带描述的两行」改成「两枚胶囊按钮」，与 Apple 的胶囊审美对齐。

---

## 三、功能点

### R-35 主线合并 + 版本号统一

| 项 | 内容 |
|---|---|
| 需求 | 把 `codex/menu-replace-local-first`（V2.1）和 `feat/recipe-library`（V2.3）依次合入 `main`，新建 `feat/v2.4-merge-and-theme` 合并分支；版本号统一为 `0.5.0`（`pyproject.toml` / `frontend/package.json` / `miniapp/package.json` / `shared/package.json`），`FastAPI(app.version)` 也跟着改 |
| 关键设计 | ① 用 `git merge --no-ff` 保留两条分支各自的拓扑，便于追溯；② 不重写历史；③ 版本号口径对齐产品版本 V2.4 |
| 证据 | 合并提交 `a7923bd` / `3eeeb24`、分支 `feat/v2.4-merge-and-theme`、`pyproject.toml:3`、`backend/app/main.py:68`、三处 `package.json` |
| 验收 | `git log main..feat/v2.4-merge-and-theme --no-merges` 包含 V2.1 的 4 条 + V2.3 的 3 条新功能提交；`/api/health` 返回 `"version":"0.5.0"` |

### R-36 修复外观系统回归：`gen_tokens.mjs` 重新输出全令牌

| 项 | 内容 |
|---|---|
| 需求 | `scripts/gen_tokens.mjs` 改为同时输出**全令牌**（`color` + `radius` + `font` + `shadow` + `motion` + `layout` + `brand`，共 58 个）+ **双调色板颜色覆盖**（`:root` 默认 + `:root[data-theme="light"]` 覆盖） |
| 关键设计 | ① 颜色令牌走双调色板；② 静态令牌（圆角/字号/阴影/动效/布局/品牌色）只一份，不分主题——它们在两套主题下保持不变；③ 默认主题的 `:root` 块与 V2.0 逐字节相同，老用户升级零感知 |
| 证据 | `scripts/gen_tokens.mjs`、`frontend/src/styles/tokens.css`（82 行 / 58 令牌）、`miniapp/src/styles/_tokens.scss`（102 行 / 58 令牌）、`node scripts/gen_tokens.mjs --check` 通过 |
| 验收 | 生成后 `tokens.css` 行数 ≥ 80 且包含 `--font-family` / `--shadow-float` / `--layout-tabbar-height` 等关键变量；`--check` 模式退出码 0；H5 切换明亮主题后 `var(--font-body)` 仍然是 `15px`（不退回浏览器默认） |

### R-37 修 Logo 颜色映射：明亮主题用白底容框

| 项 | 内容 |
|---|---|
| 需求 | `frontend/src/components/ui/logo.tsx` 的 LogoMark 主题推断改为：**明亮主题 → `logo-mark-inverse.svg`（白底容框）+ 深色主题 → `logo-mark.svg`（深色容框）**。`inverse` / `lightFrame` 显式 prop 优先级不变 |
| 关键设计 | ① 主题推断改为 `useInverse = inverse ?? (lightFrame ? false : theme === 'light')`；② 注释同步更新两版 SVG 的适用场景；③ 显式 `inverse` prop（用于启动封面/分享卡等硬性深色场景）继续生效 |
| 证据 | `frontend/src/components/ui/logo.tsx` |
| 验收 | H5 切到明亮主题，LogoLockup 上的 Logo 容框立即变为白色（与奶油背景融为一体），不出现"黑方块"；切回深色主题恢复深色容框；`NextStepCard` 上的 `<LogoMark inverse>` 仍为白底（深色卡片背景） |

### R-38 外观切换极简化：两枚胶囊按钮

| 项 | 内容 |
|---|---|
| 需求 | H5「我的」面板与小程序 profile 里的"外观"分组，从「两行带描述的 set-row（深色·黑色胶囊 / 明亮·暖色奶油）」改为**两枚水平排列的胶囊按钮**：未选中态 `PillButton variant="gray"`（灰底），选中态 `PillButton variant="ink"`（黑底白字） |
| 关键设计 | ① 用 `PillButton size="sm"` 复用现有的 Apple 风格胶囊样式，不另写一组按钮；② 去掉 `Chip tone="gray">两套随时可切` 的辅助描述，与极简化目标一致；③ 小程序侧用 `gap: px(10)` 的横向 flex 容器；④ H5 侧在 `frontend/src/global.css` 加 `.theme-switch { display: flex; gap: 10px; }` + `.theme-switch .pill { flex: 1; }` 让两个按钮等分宽度 |
| 证据 | `frontend/src/pages/Me/index.tsx`（`AppearanceCard`）、`frontend/src/global.css`（`.theme-switch`）、`miniapp/src/pages/profile/index.tsx` |
| 验收 | H5 / 小程序 profile 切到"外观"分组只看到两枚胶囊按钮（深色 / 明亮），无任何文案描述；点击切换 → `useThemeStore` / `useTheme` 立即更新 → `applyTheme` 写 `data-theme` → 整页背景 + Logo 颜色同步变化 |

### R-39 小程序主题切换与 H5 对齐

| 项 | 内容 |
|---|---|
| 需求 | `miniapp/src/lib/theme.ts` 的 `applyTheme()` 在 H5 构建目标下写 `document.documentElement.setAttribute('data-theme', value)`，让 `:root[data-theme="light"]` 覆盖块生效；顶部导航条颜色通过 `Taro.setNavigationBarColor` 同步；自定义 TabBar 通过已有的 `subscribeTheme` 强制重渲染 |
| 关键设计 | ① `applyTheme` 三端覆盖：H5 → `documentElement[data-theme]`、微信小程序 → 仅顶部导航条 + 持久化（page 元素 class 无法运行时写）；② `NAVBAR_COLOR` 仍然按主题切换 background / frontColor；③ custom-tab-bar 已在 V2.3 中订阅主题，无需改动 |
| 证据 | `miniapp/src/lib/theme.ts`、`miniapp/src/custom-tab-bar/index.tsx`、`miniapp/src/styles/_tokens.scss`（`page{}` / `page.theme-light{}`） |
| 验收 | `taro build --type h5` 后切换主题可看到背景变奶油；`taro build --type weapp` 后切换主题可看到顶部导航条颜色变奶油；custom-tab-bar 颜色随主题变 |

---

## 四、交付物

- 代码：`feat/v2.4-merge-and-theme` 分支（含 2 个 merge commit + 5 个修复提交）
- 文档：本文件（`docs/requirements-v2.4.md`）+ `docs/master-plan.md` 增加 V2.4 版本台账
- 验证：`make ci` 等价的 5 道门禁（`gen_tokens --check`、`gen_logo --check`、后端 pytest、前端 typecheck/build、shared 校验）
- 同步：TAPD workspace `43478791` 新增迭代 `V2.4 合并与外观收口` 与 5 条 Story（R-35 ~ R-39）

---

## 五、明确不做

- 暗色主题评估（D4）—— 仍按 master-plan 规划归入 V2.2，本期不动
- 小程序 page 元素 class 运行时改写 —— Taro 当前没有稳定 API，留作未来课题
- 二期小象超市采集（D1）—— 仍归入 V3.0
- 任何主题第三态（如「自动跟随系统」）—— 留作 V2.5 评估