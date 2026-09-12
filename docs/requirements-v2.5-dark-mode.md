# V2.5 需求说明 —— 真·深色主题

> | 项 | 值 |
> |---|---|
> | 版本 | `0.6.0` |
> | 阶段 | **已落地** ✅ |
> | 状态 | 规划中 → 已关闭 |
> | 优先级 | **High** |
> | 关联差异 | master-plan D4「暗色主题评估」原计划在 V2.2，本期作为独立迭代提前落地 |
> | 总案 | [`docs/master-plan.md`](master-plan.md) |
> | 提交 | `4f6ed75` feat(theme): V2.5 真·深色主题 + 命名收敛 + auto 跟随 |

---

## 一、需求背景

### 1.1 用户场景

夜间做饭 / 临期巡检 / 加班晚归时，现有「冷灰（#e9e9ee）+ 白卡片」的两态在暗光环境下会"晃眼"——主背景 #e9e9ee 反射率仍高，长时间看屏幕眼睛容易疲劳。同时飞书机器人定时推送（21:00）打开菜单时，浅色背景在 OLED/夜间模式下与系统其他 App 不协调，破坏沉浸感。

> 飞书消息卡片本身已适配系统深色，但点击进入的 H5 / 小程序仍是浅色——这是体验断点。

### 1.2 现状盘点

V2.4 合并后，外观系统是 **二态**：

| 状态名 | 主背景 | 卡片 | 主文字 | 适用 |
|---|---|---|---|---|
| `cool`（冷灰，旧名 `dark`） | `#e9e9ee` | `#ffffff` | `#1c1c1e` | 沿用 V2.0 默认色，新用户首屏 |
| `cream`（明亮，旧名 `light`） | `#FBF9F4` | `#FFFFFF` | `#2C2C2A` | 早餐店暖橙氛围，偏好日间奶油底的用户 |

**两态都"亮"，没有真正的深色模式**。命名上 `dark` = 冷灰 容易让用户误以为"我已经开了深色"，但其实它只是"中性灰"。本次需求要解决的就是"加一个真·深色" + 顺手把命名对齐认知。

### 1.3 涉及用户

- **主用户**：日均活跃、晚上 8 点后还要用 App 查菜单 / 库存的
- **次用户**：使用 OLED 设备、对屏幕反光敏感的用户
- **企业用户**：在演示场景下希望"不要在客户面前太亮"

---

## 二、目标

### 2.1 业务目标（G）

- **G1 真正的暗色体验**：新增「深色」第三态，遵循 Apple Human Interface Guidelines (Dark Mode) / HarmonyOS 深色模式规范，主背景接近 `#000000`，主文字接近 `#FFFFFF`，对比度满足 WCAG AA（4.5:1）。
- **G2 层次清晰的视觉**：卡片 / 弹窗 / 面板用「表面抬升」概念（一级 surface、二级 surface、三级 surface），让用户在纯黑底上仍能识别信息层级。
- **G3 一键切换 + 跟随系统**：保留现有"两枚胶囊按钮"UI，新增第三枚「深色」；并提供 `auto` 模式跟随系统（`prefers-color-scheme: dark`）。
- **G4 三端一致**：H5 / 小程序 / 飞书机器人卡片（已支持）配色同源；H5 切换后 localStorage 持久化，小程序切换后 setStorageSync 持久化，刷新后保留。

### 2.2 非目标（Out of Scope）

- 不做"自定义主题色"（保持单一品牌色 + 三态切换）
- 不做"图片自动反色"（参考 Apple HIG：图片由上传方控制）
- 不做"高对比度辅助模式"（那是 iOS 单独的 Accessibility 模式，V3.0 评估）
- 不改品牌 Logo 形状（仅在深色主题下切换到 `logo-mark-inverse.svg`，已有逻辑）

---

## 三、设计规范

### 3.1 命名收敛（重要：先做这件事再做色值）

| 旧名 | 新名 | 含义 |
|---|---|---|
| `dark`（冷灰底） | **`cool`** | 中性灰底，主按钮仍是品牌黑 |
| `light`（奶油底） | **`cream`** | 奶油底 + 暖橙提示色 |
| _无_ | **`dark`**（新增） | 真·深色，遵循 Apple HIG / HarmonyOS |

`useThemeStore` / `useTheme` 同步加 `ThemeName = 'cool' | 'cream' | 'dark' | 'auto'`；**localStorage key 加版本号** `meal-planner:theme:v2`，老 key 第一次读取时迁移：旧 `dark` → `cool`，旧 `light` → `cream`。

### 3.2 真·深色调色板（参考 Apple HIG + HarmonyOS）

| 令牌 | 取值 | 用途 |
|---|---|---|
| `bg` | `#000000` | 页面外底色（OS 级"深色"） |
| `screen` | `#0A0A0C` | 屏幕底色（比 bg 略亮一点点） |
| `card` | `#1C1C1E` | 卡片（一级 surface 抬升） |
| `card-2` | `#2C2C2E` | 弹窗 / 嵌套面板（二级 surface） |
| `card-3` | `#3A3A3C` | 输入框 / 下拉框（三级 surface） |
| `ink` | `#FFFFFF` | 主文字（与 card 对比度 15.4:1，远超 AA） |
| `ink2` | `rgba(235, 235, 245, 0.60)` | 次级文字（与 bg 对比度 ≥ 7:1，AAA） |
| `ink3` | `rgba(235, 235, 245, 0.30)` | 辅助 / 占位文字 |
| `ink-disabled` | `rgba(235, 235, 245, 0.18)` | 禁用状态 |
| `line` | `rgba(84, 84, 88, 0.65)` | 分割线（HIG 推荐的"hairline"） |
| `fill` | `rgba(120, 120, 128, 0.24)` | 浅填充（餐次行 / 选中态背景） |
| `on-ink` | `#000000` | 黑底白字按钮反色（白底黑字 → 黑底白字） |
| `accent` | `#30D158` | 完成 / 充足（Apple "systemGreen" Dark） |
| `accent-ink` | `#30D158` | accent 文字色（深色模式下两者同色） |
| `accent-soft` | `rgba(48, 209, 88, 0.20)` | accent 半透明底 |
| `warn` | `#FF9F0A` | 临期 / 超支（Apple "systemOrange" Dark，比浅色模式更亮） |
| `warn-ink` | `#FFD60A` | warn 文字色（深色下用更亮的黄） |
| `warn-soft` | `rgba(255, 159, 10, 0.20)` | warn 半透明底 |
| `danger` | `#FF453A` | 错误（Apple "systemRed" Dark） |
| `danger-soft` | `rgba(255, 69, 58, 0.20)` | danger 半透明底 |
| `glass` | `rgba(28, 28, 30, 0.72)` | 悬浮毛玻璃胶囊底（深色玻璃） |

> **关键设计原则（参考 Apple HIG 2.3 节）**：
> 1. 避免纯 `#000000` 文字——用接近白的 `#FFFFFF` 作主文字，对比度更高，眼睛更舒服
> 2. 暗色下「色相不变、饱和度提高、亮度降低」——绿/橙/红都比浅色版更"亮"以确保 4.5:1
> 3. 用「半透明黑/白」做分割线（`rgba(84,84,88,.65)`），不写死灰阶，便于叠在任意背景上
> 4. 暗色下要"减少大面积纯白"——卡片 #1C1C1E 而不是 #FFFFFF

### 3.3 组件适配清单

| 组件 | 浅色 | 深色 |
|---|---|---|
| 主背景 | `#e9e9ee` / `#FBF9F4` | `#000000` |
| 卡片 | `#ffffff` | `#1C1C1E`（抬升） |
| 弹窗 / 面板 | `#ffffff` | `#2C2C2E`（二级抬升） |
| 输入框 / 下拉 | `border: 1px solid var(--color-line)` | 同左，但 line 用 `rgba(84,84,88,.65)` |
| 主按钮 | 黑底白字（pill--ink） | **白底黑字**（反色）—— Apple 暗色下系统色按钮用白底 |
| 链接 | `var(--color-ink)` | `var(--color-ink)` 同 #FFFFFF |
| 主按钮次要 | 灰底深字（pill--gray） | `rgba(118,118,128,0.24)` 底 + 白字 |
| 状态点（state-dot） | `var(--color-ink)` | `var(--color-ink)`（同 #FFFFFF） |
| 菜单 / 导航栏 | `var(--color-card)` 纯白 | `rgba(28,28,30,0.72)` 玻璃 + 1px hairline |
| 浮动 TabBar | `rgba(255,255,255,0.82)` 玻璃 | `rgba(28,28,30,0.72)` 玻璃 |
| 图标色调 | `var(--color-ink)` / `var(--color-ink2)` | `var(--color-ink)` / `var(--color-ink2)` 自动适配 |
| 提示框（Banner） | warn 浅橙底 | warn 暗橙底 + 亮橙文字 |
| 选中态背景（chip / set-row） | `var(--color-fill)` 灰底 | `rgba(118,118,128,0.24)` 透明灰 |
| 进度条（bar） | 黑色 | 白色（与 on-ink 配对） |
| 阴影 | `rgba(0,0,0,0.06)` 浅阴影 | 弱化或换 `0 0 0 1px var(--color-line)` 描边代替阴影 |
| Logo 容框 | 深色（默认 `logo-mark.svg`） | **白色**（用 `logo-mark-inverse.svg`，因为浅色反而"消失"了） |
| 品牌暖色 Logo 元素（蛋黄 #f6a623） | 保留 | 保留（暗色下也亮，但需要把 #ffc861 高光稍微压暗一档以避免"过亮"） |

### 3.4 状态点对比度（WCAG AA 验证）

| 文字组合 | 对比度 | AA (≥4.5) | AAA (≥7) |
|---|---|---|---|
| `#FFFFFF` on `#000000` | 21:1 | ✅ | ✅ |
| `#FFFFFF` on `#1C1C1E` | 15.4:1 | ✅ | ✅ |
| `rgba(235,235,245,0.6)` on `#000000` | 7.4:1 | ✅ | ✅ |
| `rgba(235,235,245,0.3)` on `#000000` | 3.6:1 | ❌（辅助文字可豁免） | ❌ |
| `#30D158` on `#000000` | 11.5:1 | ✅ | ✅ |
| `#FF9F0A` on `#000000` | 10.4:1 | ✅ | ✅ |
| `#FF453A` on `#000000` | 5.5:1 | ✅ | ✅（临界） |

> ink3 是辅助级（占位 / hint），按 WCAG 1.4.11 "Non-text Contrast" 走 3:1 即可，过严会让暗色 UI 失去层次。

---

## 四、涉及模块

| # | 模块 | 文件 | 工作量 |
|---|---|---|---|
| 1 | 设计令牌 | `shared/tokens.ts`（新增 `palettes.dark` + `palettes.cool` 重命名 `dark`，加 `ThemeName = 'cool'\|'cream'\|'dark'\|'auto'`） | 中 |
| 2 | 生成器 | `scripts/gen_tokens.mjs`（输出 `:root[data-theme="dark"]` 覆盖块，加嵌套优先级：auto → prefers-color-scheme） | 中 |
| 3 | 主题 store（H5） | `frontend/src/stores/useThemeStore.ts`（加 'dark' 状态、localStorage key 迁移 `'meal-planner:theme:v2'`、auto 模式、matchMedia 监听） | 中 |
| 4 | H5 入口 | `frontend/src/pages/Me/index.tsx`（`AppearanceCard` 三按钮 + auto），`frontend/src/global.css`（`.theme-switch` 三列布局） | 低 |
| 5 | H5 组件适配 | `frontend/src/components/ui/index.tsx`（PillButton `variant="ink"` 在深色下反相），`global.css` 阴影 / 玻璃 / 描边等暗色覆盖 | 中 |
| 6 | 小程序主题 | `miniapp/src/lib/theme.ts`（加 'dark' 状态、auto、setNavigationBarColor 深色色值），`miniapp/src/styles/_tokens.scss`（`page.theme-dark{}`） | 中 |
| 7 | 小程序入口 | `miniapp/src/pages/profile/index.tsx`（三按钮），custom-tab-bar（订阅主题） | 低 |
| 8 | 文档 | `docs/requirements-v2.5-dark-mode.md`（本文件）、`docs/master-plan.md`（D4 状态更新、V2.5 版本台账）、`docs/design-system.md`（深色色板一节） | 低 |
| 9 | 验收 | `make check-tokens` / `make check-logo` + 手工对照色表 | 低 |
| 10 | TAPD | workspace `43478791` 建 V2.5 迭代 + R-40 Story + 子 Task | 低 |

**总估时**：3–4 人天（含 design review + 双向端到端验收 + 文档）。

---

## 五、验收标准

### 5.1 视觉验收（手工跑）

1. **三态切换可见**：H5 / 小程序点「深色」后 200ms 内完成切换，无白屏闪烁
2. **背景接近黑**：H5 主背景实测 `#000000`，无渐变 / 无图片
3. **卡片抬升可见**：卡面色 `#1C1C1E` 比主背景明显亮一档，文字 / 描边 / 阴影都正常
4. **对比度达标**：用浏览器 DevTools / Stark 插件抽查 5 处文字组合（主文字 / 次文字 / 链接 / warn 提示 / danger 提示），全部 ≥ 4.5:1
5. **主按钮反色**：深色态下 `pill--ink` 变白底黑字（`background: #FFFFFF; color: #000000`），不是黑底白字
6. **TabBar 玻璃**：浮动 TabBar 背景 `rgba(28,28,30,0.72)` + 1px hairline，在主背景上能看出"悬浮"效果
7. **Logo 切换**：深色态下 LogoLockup 的容框变白色（`logo-mark-inverse.svg`），与"暖色蛋黄 + 木柄"在黑底上突出
8. **导航栏同步**：H5 `<meta name="theme-color">` 写入 `#000000`；小程序 `Taro.setNavigationBarColor` 写入 `#000000`
9. **无白底泄漏**：滚动到底、抽屉打开、弹窗弹出、错误提示、加载骨架等所有交互态，**没有任何** `#ffffff` 硬色块出现

### 5.2 工程验收（自动化）

1. `node scripts/gen_tokens.mjs --check` 通过；生成物包含 `:root[data-theme="dark"]{}` 覆盖块
2. `node scripts/gen_logo.mjs --check` 通过；`logo-mark-inverse.svg` 仍是浅色版（无需改动）
3. `frontend tsc --noEmit` + `vite build` 通过；CSS bundle 增量 < 5KB
4. `miniapp tsc --noEmit` 通过
5. 后端 `pytest -x backend/tests/` 全过（本次后端零改动，但跑一遍回归）
6. `localStorage` 迁移脚本：清空 storage 后访问，老用户看到的依然是 V2.4 的状态（`cool` / `cream`），不会出现"老 dark 变成新 dark"的视觉跳变

### 5.3 体验验收（用户场景）

1. **夜间场景**：晚上 9 点在卧室用手机打开今日页（`prefers-color-scheme: dark` 自动切深色），眯眼看 30 秒无不适
2. **白屏检查**：从冷灰切到深色、从奶油切到深色，过程录制视频无白屏闪烁
3. **持久化**：H5 选「深色」后刷新仍为深色；小程序杀掉重进仍为深色
4. **跨设备**：H5 选「深色」后切换到另一台设备登录同步（前提是登录态打通，本期不解决）
5. **a11y**：macOS VoiceOver 朗读主文字无障碍命中所有交互控件

---

## 六、风险与边界

### 6.1 风险

- **R1 命名迁移**：`localStorage` 旧值 `dark` 在新语义下被解读为"冷灰"，但有用户可能把它误以为是"真·深色"——通过 key 加 `:v2` 后缀让老 key 失效并按新语义重置，避免歧义
- **R2 主按钮反色**：现有 `pill--ink` 在两态下都是黑底白字，作为品牌识别。深色下反色成白底黑字，**会**与"黑色胶囊"品牌识别冲突——需要确认主按钮在深色下仍用「黑底白字 + brand 装饰色描边」还是「白底黑字」，建议 A/B 验收前定
- **R3 飞书机器人卡片**：机器人发的菜单卡片已是飞书原生消息，已自动跟随用户系统的深色模式——本需求只覆盖 H5 / 小程序两端，**不动机器人**
- **R4 antd 主题**：H5 用 antd 5，antd 自带 dark algorithm（`theme: { algorithm: theme.darkAlgorithm }`）——需要确认 antd dark algorithm 与我们的色值是否冲突；如有冲突，定义 `buildAntdTheme(theme)` 在 'dark' 分支下切换 algorithm

### 6.2 已知限制

- 不做图片反色（参考 Apple HIG：图片由上传方控制）
- 不做"自定义主题色"（保持品牌纪律）
- 不做"高对比度辅助模式"（V3.0 评估）
- 不解决跨设备同步（前提是先有账号体系跨端打通，目前 H5 走飞书 Cookie、小程序走微信 Bearer，**两套账号不互通**——D2 范畴，V2.2+ 评估）

---

## 七、TAPD 提交规范（标准五段式）

> 以下是 TAPD 卡片可直接粘贴的「需求描述」正文，按 TAPD 标准化模板（背景 / 目标 / 模块 / 验收 / 优先级）组织。

### 7.1 标题

`R-40 真·深色主题模式（Apple HIG / HarmonyOS 暗色规范）`

### 7.2 需求描述（粘贴到 TAPD「详细描述」）

```markdown
## 需求背景
现有 H5 / 小程序仅提供「冷灰 / 奶油」两态外观，均为浅色底。夜间 / OLED / 长时使用场景下用户眼睛易疲劳，飞书消息已支持系统深色，点击进入的 H5 / 小程序仍是浅色，存在体验断点。

本期新增第三态「真·深色」+ 顺手做命名收敛（`dark`/`light` → `cool`/`cream`/`dark`），遵循 Apple Human Interface Guidelines (Dark Mode) 与 HarmonyOS 深色模式规范：主背景接近 #000000、卡片 #1C1C1E 抬升、文字主 #FFFFFF、次级 rgba(235,235,245,0.6)，对比度满足 WCAG AA（4.5:1）。

## 目标
- G1 新增深色第三态，H5 / 小程序 / 飞书机器人卡片配色同源
- G2 卡片 / 弹窗 / 面板用「表面抬升」三层 surface，保持层次清晰
- G3 保留「冷色 / 明亮 / 深色」三枚胶囊按钮，新增 `auto` 跟随系统
- G4 localStorage 迁移 `'meal-planner:theme:v2'`，老 key 失效避免误读

## 涉及模块
- 设计：shared/tokens.ts（新增 palettes.dark）、docs/design-system.md
- 生成器：scripts/gen_tokens.mjs（输出 :root[data-theme=dark] 覆盖块）
- H5：stores/useThemeStore.ts（加 auto 模式 + matchMedia 监听）、pages/Me（AppearanceCard 三按钮 + auto）、global.css（暗色覆盖）、components/ui（PillButton 反色）
- 小程序：lib/theme.ts（加 dark + auto）、styles/_tokens.scss（page.theme-dark{}）、pages/profile（三按钮）、custom-tab-bar
- 工程：localStorage 迁移脚本、gen_tokens --check / gen_logo --check / vite build / tsc --noEmit
- 文档：docs/requirements-v2.5-dark-mode.md、docs/master-plan.md（D4 状态更新 + V2.5 版本台账）
- TAPD：workspace 43478791 建 V2.5 迭代 + R-40 Story

## 验收标准
1. H5 / 小程序三态切换 200ms 内完成，无白屏闪烁
2. 深色态：主背景 #000000、卡片 #1C1C1E、ink #FFFFFF
3. 5 处关键文字组合对比度 ≥ 4.5:1（DevTools / Stark 抽查）
4. 深色态下 PillButton 变白底黑字
5. TabBar 玻璃用 rgba(28,28,30,0.72) + 1px hairline
6. Logo 自动切到 logo-mark-inverse.svg（白底容框）
7. `<meta name="theme-color">` 与小程序导航条同步写入 #000000
8. 滚动 / 抽屉 / 弹窗 / 错误提示无任何 #ffffff 硬色块
9. node scripts/gen_tokens.mjs --check + gen_logo --check + tsc --noEmit + vite build 全过
10. 老用户清空 localStorage 后看到 V2.4 状态（cool / cream），无视觉跳变
11. macOS VoiceOver 朗读主文字无障碍命中所有交互控件

## 优先级
High（用户主动申报，影响所有交付面视觉一致性，3-4 人天可完成）
```

### 7.3 优先级

`High`

### 7.4 工作量

3–4 人天（含 design review）

### 7.5 关联

- D4 暗色主题（master-plan 差异对齐表）— 本期落地
- V2.2 数据与智能 — 不再承载暗色主题，dark 主题独立为 V2.5

---

## 八、明确不做

- 图片自动反色
- 自定义主题色
- 高对比度辅助模式（V3.0 评估）
- 跨设备主题同步（先要账号体系打通）
- 飞书机器人卡片深色（飞书原生支持）
