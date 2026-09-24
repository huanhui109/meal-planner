# 小程序审查报告 — 交互 & 主题（2026-09-15）

范围：`miniapp/`（Taro 4.2.1 + React 18 + TS），涉及 `shared/`、`frontend/` 的对齐改动。

两部分：
- **A. UI 问题排查与修复**（本次已改代码）
- **B. 代码与交互审查**（本次只出方案，未改代码）

---

## A. UI 问题排查与修复

### A-1 主题切换失效（P0，已修）

**现象**：在「我的 → 外观」里切冷色/明亮/深色，导航条和 TabBar 会变，页面主体颜色完全不变。

**根因**：两个问题叠加。

1. **主题类挂在永远匹配不上的选择器上。**
   小程序的 `page` 节点由框架生成，JS 既拿不到引用也写不了它的 `class`。
   `_tokens.scss` 里三套调色板挂在 `page.theme-cream` / `page.theme-dark` 上，而
   `lib/theme.ts` 里也确实**没有任何代码**去写这个 class（文件注释里自己都写了"如果 page
   元素 class 写不了，至少 nav bar 颜色能立即变"）。结果：变量永远取默认那套。
   这也是为什么 `--check` 过、构建过、CI 过，但功能就是没有 —— 生成的 CSS 从来没被命中过。

2. **23 处 CSS 变量括号写错，运行期被整条丢弃。**
   `app.scss` 里写成 `var(--color-on)-ink`（应为 `var(--color-on-ink)`），
   同理 `var(--color-accent)-soft`、`var(--color-warn)-ink`、`var(--color-danger)-soft`。
   CSS 解析失败 → 该声明失效 → 徽标文字、标签底色在深色下变成默认黑/透明。

**修复**：把变量宿主从 `page` 挪到 React 可控的包裹类。

| 位置 | 改动 | 原因 |
|---|---|---|
| `scripts/gen_tokens.mjs` | 新增 `DEFAULT_PALETTE='cream'`；SCSS 端输出 `page,.theme-root,.theme-vars{}` 作默认块，覆盖块改为 `.theme-root.theme-cool/cream/dark` 与 `.theme-vars.theme-*`（并列选择器）；CSS 端补 `:root[data-theme="cool"]` | `page` 只能当兜底，真正的宿主必须是 React 能写 class 的节点 |
| `miniapp/src/styles/_tokens.scss`、`frontend/src/styles/tokens.css` | 重新生成（**未手改**，是生成物） | 保持与 `shared/tokens.ts` 一致，CI 有 `--check` |
| `miniapp/src/app.scss` | 23 处畸形变量全部修正；新增 `.theme-root { min-height:100vh; background:var(--color-bg); color:var(--color-ink) }` | 变量修好 + 给包裹类兜底底色 |
| `miniapp/src/lib/theme.ts` | 新增 `getThemeClass()` / `useThemeClass()`；`applyTheme` 注释更新 | 页面根节点靠它拿 `theme-root theme-<palette>` |
| `miniapp/src/app.ts` | `initTheme()` 从 `useEffect` 移到**模块顶层同步调用** | 放 useEffect 时首帧已经渲染完，深色用户会闪一帧浅色 |
| 12 个页面的根 `<View>` | `className={`page ${themeClass}`}`（login 页是 `login-page`） | 不挂就取不到当前主题的变量 |
| `miniapp/src/custom-tab-bar/index.tsx` | 根节点自挂 `theme-vars theme-<applied>` | 自定义 TabBar **不在页面根节点内**，拿不到 `.theme-root` 的变量；用 `.theme-vars`（纯变量宿主，无 `min-height/background` 副作用）避免撑高布局 |
| `shared/tokens.ts` | `resolveAutoTheme(systemTheme?)` 加可选入参；更新过时注释 | 小程序没有 `window.matchMedia`，不传参就永远回落 `cool` |

**验证方式**：
```bash
node scripts/gen_tokens.mjs && node scripts/gen_tokens.mjs --check   # 两个 ✓
cd miniapp && npx tsc --noEmit                                        # 0 error
npx taro build --type weapp                                           # Compiled successfully
grep -o '\.theme-root\.theme-dark{--color-bg:[^;]*' dist/app.wxss     # 必须命中
grep -oE 'className:"(page|login-page) "\.concat' dist/pages/*/index.js | wc -l  # 每页 ≥1
grep -c 'var(--color-on)-ink' dist/app.wxss                           # 应为 0
```
真机验证：我的 → 外观，依次切 冷色/明亮/深色/自动，页面底色、卡片、文字、TabBar、导航条
应同步变化；杀掉小程序重进，主题保持。

### A-2 首页「去确认」按钮消失（P0，已修）

**现象**：AI 生成完菜单后回到首页，用户找不到确认入口，菜单一直停在草稿态。

**根因**：`pages/today/index.tsx`
```ts
const notReady = !data?.ready.has_menu || !data?.ready.has_preferences
```
菜单是 `draft` 时 `has_menu` 已经是 `true`，卡片被藏起来；而 `shared/next-step.ts` 的
`nextStep()` 在 `status === 'draft'` 时返回的正是 `confirm-menu`（「去确认」）。
判断条件和决策函数打架，把最需要引导的那一步给吞了。

**修复**：改为信任决策函数 —— 只有 `relax`（全都安排好了）才不需要卡片：
```ts
const showNextStep = step.key !== 'relax'
```
同时删掉 `handleStepAction` 里手写的路由表，改用 `lib/nav.ts` 的 `goTo()`
（共享层路径 → 小程序路径的映射、以及 tab 页只能 `switchTab` 的分流都已在那里维护，
两处各写一份必然漂移）。

> ⚠ **H5 同款缺陷未修**：`frontend/src/pages/Today/index.tsx:211` 是完全相同的
> `notReady` 判断。本轮范围不含 H5，建议下次一并改（详见 B 部分 P1-3）。

### A-3 主题默认值与 H5 对齐

`DEFAULT_PALETTE='cream'`（生成器）≡ `DEFAULT_THEME='cream'`（小程序 `lib/theme.ts`、
H5 `useThemeStore`）≡ 各页面 `index.config.ts` 里静态写死的 `#FBF9F4`。三者一致，
冷启动不会闪别的底色。另外把 H5 `useThemeStore` 的 `applied` 初值从 `'cool'` 改成
`'cream'`（原值与默认调色板对不上，会让 Logo 这类"按 applied 取色"的组件首帧取错色）。

---

## B. 代码与交互审查

> 本节只做定位与方案，**未改动代码**。每条都给了文件:行号证据与改法。

### B-1 P0（必现缺陷，流程走不下去）

| # | 问题 | 证据 | 影响 | 改法 |
|---|---|---|---|---|
| 1 | **老用户每次冷启动都要重走一遍引导** | `app.config.ts:3` 把 `pages/onboarding/index` 放在 `pages[0]`（= 小程序启动页）；而 `pages/onboarding/index.tsx` 全文没有任何 `isOnboarded()` 判断 | 已完成引导的用户杀掉小程序重进，又看到 3 步引导；走完只是 `setOnboarded(true)` 再 `reLaunch` 到 today，等于每次白点 3 下 | 二选一：① 把 `pages[0]` 改成 `pages/today/index`，由 today 的 `useDidShow` 里已有的 `!isOnboarded() → reLaunch onboarding` 兜住新用户；② 保留启动页，但 onbsoarding 顶部加 `if (isOnboarded()) reLaunch today`。推荐 ① + 在 `app.config.ts` 加 `entryPagePath: 'pages/today/index'` |
| 2 | **「复用历史菜单」是个死功能** | `pages/menu-history/index.tsx:60` 用 `Taro.navigateTo({ url: '/pages/menu/index?reuse_from=...' })` | 三处硬伤叠加：① menu 是 tab 页，`navigateTo` 到 tabbar page 会直接失败；② 即使改 `switchTab`，tab 页 url 不允许带 query；③ 全仓库 grep `reuse_from` 只有这一处写入，**没有任何地方读取**，后端也没有对应参数 | 用 `Taro.setStorageSync('mp:reuse_from', item.id)` 存，然后 `Taro.switchTab({ url: '/pages/menu/index' })`；menu 页在 `useDidShow` 里读一次并清掉。同时后端 `generateMenu` 要真的接受 `reuse_from` 才有意义，需要后端配合；不打算做就把这个按钮先下掉，别留一个点了没反应的入口 |
| 3 | **引导里选的偏好从来没有保存** | `pages/onboarding/index.tsx:58-66` `handleFinish()` 只做 `setOnboarded(true)` + `removeStorageSync(草稿)` + `reLaunch`；整个文件的 import 里没有任何 api 调用 | 用户在引导里选的家庭人数、菜系，点「开始用」后被直接删掉。进首页 `has_preferences` 仍是 false，立刻又被要求「先花 1 分钟填偏好」——引导等于白做 | 走完第 2 步就调 `saveHousehold` / `saveDiet`（`lib/api` 已有），成功后再清草稿；失败要能重试，不能静默丢。注意此时可能还没登录（注释说"完成后再让用户登录"），所以需要：先落 storage → 登录成功后（`login/index.tsx:32` switchTab 之前）补提交一次 |
| 4 | **偏好页下拉刷新永远转圈** | `pages/profile/index.config.ts:8` 开了 `enablePullDownRefresh: true`，但 `pages/profile/index.tsx` 全文没有 `usePullDownRefresh`，也没有任何 `Taro.stopPullDownRefresh()` | 在「我的」页下拉，loading 动画永远不会停，只能杀进程 | 加 `usePullDownRefresh(() => { void load() })`，并在 `load()` 的 `finally` 里 `Taro.stopPullDownRefresh()`（照抄 `pages/shopping/index.tsx:58-73` 的写法：它还用 `aliveRef` 防卸载后 setState） |

### B-2 P1（明显体验问题）

| # | 问题 | 证据 | 改法 |
|---|---|---|---|
| 5 | **二级页没有返回入口** | `app.config.ts:18` 全局 `navigationStyle: custom`；`components/ui/index.tsx:61-90` 的 `PageHead` 只有 title / subtitle / 右上角 action，**没有左侧返回按钮** | 给 `PageHead` 加可选 `back?: boolean`，用 `getCurrentPages().length > 1` 判断是否显示，点击 `Taro.navigateBack()`。about / invite / menu-history / recipe-detail / profile / update 六个二级页统一打开。（iOS 左滑和安卓物理键还能返回，所以是体验问题不是卡死） |
| 6 | **登录后不回跳** | `lib/nav.ts:44-48` `ensureLogin()` 直接 `reLaunch('/pages/login/index')`；`lib/request.ts:47-53` 401 也 `reLaunch` 到 login；而 `pages/login/index.tsx:32` 登录成功后固定 `switchTab('today')` | 用户在「采购」页被踢去登录，登完回到首页而不是原来在做的事。把来源页 route + 参数存进 storage，登录后回跳（tab 页用 switchTab 且丢参数，非 tab 页用 redirectTo） |
| 7 | **邀请闭环断裂** | 后端返回的 `share_path` 形如 `/pages/today/index?invite_code=xxxx`（`pages/invite/index.tsx:152`），但 invite 页读的是 `router.params.code`（`:17,:30,:31`），today 页根本不读 `invite_code` | 统一参数名（建议 `invite_code`）：分享 path 指向 `pages/invite/index`，invite 页 `onLoad` 读到就自动填码并提示；today 页若收到该参数则转存后跳 invite |
| 8 | **分享带来的参数没人消费** | `pages/today/index.tsx:118-125` `useShareAppMessage` 拼了 `share_from` / `share_date`，全仓库无读取方 | 要么在 today 的 `useRouter` 里读出来做归因（`track('share_open', {from, date})`），要么删掉，避免"看起来做了其实没做" |
| 9 | **AI 生成没有进度反馈** | `lib/menu.ts:32-56` 的 `waitForGeneration(taskId, onProgress?)` 支持进度回调，但 `pages/today/index.tsx:148-156` 和 menu 页调用时都没传 | 传 `onProgress`，把 `task.status` 映射成 0/1/2 三档文案（"正在查食材 → 正在配餐 → 正在算预算"），配 `Taro.showLoading` 或页面内进度条；失败给「重试」而不是只 toast |
| 10 | **401 续期失败会打断正在填的表单** | `lib/request.ts:124-131` → `redirectToLogin()` → `reLaunch` | profile 页正在填 5 组偏好时令牌过期，直接被踢走且未保存内容全丢。建议：写操作（PUT/POST）401 时先落本地草稿再跳登录；或在 `onUnload` 里把表单草稿写 storage |
| 11 | **菜谱详情用 URL 传整份 JSON** | `pages/menu/index.tsx:244-246` `navigateTo({ url: '/pages/recipe-detail/index?data=' + encodeURIComponent(JSON.stringify(payload)) })`，payload 含完整食材数组 | 微信 `navigateTo` 的 url 有长度上限，食材多的菜谱 encode 后容易超限 → 跳过去直接落到「数据加载失败」兜底页。改传 `meal_id`，详情页自己按 id 拉；或退一步用 `Taro.setStorageSync` 传大数据 + url 只带 key |
| 12 | **深色用户冷启动闪一帧浅色** | 7 个 `index.config.ts` 里 `backgroundColor` 编译期写死 `#FBF9F4`；`initTheme()` 再快也在首帧之后 | 接入微信官方 darkmode：`app.json` 加 `"darkmode": true` + 根目录 `theme.json` 给 `backgroundColor` 等变量配 light/dark 两套，让框架自己在首帧前决定底色 |

### B-3 P2（优化建议）

- **onboarding 草稿只写不读**：`pages/onboarding/index.tsx:49-56` 每次选择都 `setStorageSync`，但 `:47` 初始化恒为 `DEFAULT_DRAFT`，重进后 storage 里有值也不恢复。改成 `useState(() => 读 storage ?? DEFAULT_DRAFT)`。
- **onboarding 文案与选项不符**：`:115` 写「不选就让 AI 全权发挥」，但 `CUISINE_OPTIONS`（`:36-42`）里没有"不选"这个选项，且「下一步」在 `cuisine == null` 时 disabled。要么补一个 `flexible` 选项，要么改文案。
- **硬编码页面路径绕过 `goTo`**：`pages/profile/index.tsx:681/686/707`、`pages/today/index.tsx:281/351/406/417/518` 等直接写 `'/pages/xxx/index'`。目前功能正确（非 tab 页用 navigateTo、tab 页用 switchTab 都对），但和 `lib/nav.ts` 的 `PAGE_MAP` 两处维护会漂移。建议统一走 `goTo('/menus')` 这种共享层路径。
- **`app.config.ts:27-28` 的 tabBar 色值是 cool 的**：`custom: true` 下原生 tabBar 不渲染，这两个值是死配置，但写的 `#8e8e93/#1c1c1e` 与 cream 默认不一致，回退到原生时会配色错。改成 cream 的 `#6B6B6B/#2C2C2A`。
- **auto 模式非深色解析成 cool 而不是 cream**：`shared/tokens.ts` 的 `resolveAutoTheme()` 在 `!dark` 时返回 `'cool'`。这是既有设计（H5 同款），但它意味着选了「自动」的用户在浅色系统下看不到默认的 cream 主题。如果产品希望 auto ≈ 默认外观，改成返回 `'cream'`。**两端要一起改**。
- **H5 首页同款 `notReady` 缺陷**：`frontend/src/pages/Today/index.tsx:211`，与本轮修的 A-2 完全一样，建议下次一并改。

### B-4 完善功能的优先级建议

| 优先级 | 事项 | 验收标准 |
|---|---|---|
| 先做 | B-1 的 4 条 P0 | 老用户冷启动直达首页；复用按钮要么能用要么下线；引导选的偏好进首页后 `has_preferences=true`；偏好页下拉能正常收起 |
| 再做 | 返回入口（#5）+ 登录回跳（#6） | 六个二级页左上角有返回按钮；从采购页被踢登录，登完回采购页 |
| 再做 | 生成进度（#9）+ 401 不打断填写（#10） | 生成过程有阶段性文案与失败重试；令牌过期后填的内容不丢 |
| 数据闭环 | 邀请（#7）+ 分享归因（#8） | 分享链接打开自动填入邀请码并兑换成功；分享带来的打开能被统计到 |
| 收尾 | 首帧闪色（#12）+ P2 各项 | 深色模式冷启动不闪白；路径统一走 `goTo` |


