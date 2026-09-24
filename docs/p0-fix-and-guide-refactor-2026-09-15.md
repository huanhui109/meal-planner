# P0 修复 + 引导改造（2026-09-15）

本轮两件事：**修掉两端所有 P0**，以及**把引导从写死的强制流程改成用户可配置**。
两端 `tsc --noEmit` 均 0 error，小程序 `taro build --type weapp` 与 H5 `vite build` 均通过。

---

## 一、小程序 P0（4 条）

### P0-1 老用户每次冷启动都要重走引导

**原因**：`app.config.ts` 的 `pages[0]` 是 `pages/onboarding/index`，而小程序的启动页就是
`pages[0]`；onboarding 页面自己又不判断"这是不是老用户"。于是已完成引导的用户杀掉小程序
重进，又得点 3 步才能回到首页。

**改动**

| 文件 | 改动 |
|---|---|
| `miniapp/src/app.config.ts` | `pages[0]` 改为 `pages/today/index`，并加 `entryPagePath: 'pages/today/index'` 显式声明 |
| `miniapp/src/pages/today/index.tsx` | 强制 `reLaunch onboarding` 改为按用户设置判断：`if (shouldAutoShowGuide(getUserSettings()))` |

**验证**：`dist/app.json` 里 `"entryPagePath":"pages/today/index"`、`pages` 第一项是 today；
真机上「已完成引导」的用户冷启动直接进首页；新用户（`guide.completed=false`）仍会先看到引导。

### P0-2 「一键复用」是死功能

**原因**：`menu-history/index.tsx:60` 用 `navigateTo` 跳 `/pages/menu/index?reuse_from=...`。
三处硬伤叠加：① menu 是 tab 页，`navigateTo` 到 tabbar page 必然失败；② 即使改 `switchTab`，
tab 页 url 不允许带 query；③ 全仓库 grep，`reuse_from` 只有这一处写入，**后端也不支持该参数**。

**改动**：`miniapp/src/pages/menu-history/index.tsx` —— 改为 `Taro.switchTab('/pages/menu/index')`，
按钮文案「一键复用」→「去周菜单」，弹窗文案改成诚实的说法，并在注释里留了后端支持后的 TODO。
不留"点了没反应"的入口。

**验证**：点「去周菜单」能正常切到菜单页；不再出现 `navigateTo:fail can not navigateTo a tabbar page`。

### P0-3 引导里选的偏好从来没有保存

**原因**：`onboarding/index.tsx` 的 `handleFinish()` 只做 `setOnboarded(true)` + 删草稿 +
`reLaunch`，整个文件没有任何 api 调用。用户选的家庭人数、菜系被直接丢弃，进首页
`has_preferences` 仍是 false，立刻又被要求「去填偏好」——引导等于白做。

**改动**

| 文件 | 改动 |
|---|---|
| `miniapp/src/lib/guide-draft.ts`（新增） | 引导草稿的落库通道：已登录直接 PUT household + diet；未登录或失败则暂存 storage |
| `miniapp/src/pages/onboarding/index.tsx` | `handleFinish` 改为 async：先 `flushGuideDraft`，再 `markGuideCompleted()`；按钮加 `saving` 态；草稿改为**读** storage（原来只写不读，中途退出重进就丢） |
| `miniapp/src/pages/login/index.tsx` | 登录成功后 `flushPendingGuideDraft()` 补交（失败不阻塞进首页） |

**验证**：走完引导 → 首页 `has_preferences=true`，不再提示"去填偏好"；
未登录走完引导 → 登录后偏好自动补上（storage `mp_guide_pending_preferences` 被清空）。

### P0-4 偏好页下拉刷新永远转圈

**原因**：`pages/profile/index.config.ts` 开了 `enablePullDownRefresh: true`，但 tsx 里既没有
`usePullDownRefresh` 也没有 `stopPullDownRefresh`。下拉后 loading 动画永不停止，只能杀进程。

**改动**：`miniapp/src/pages/profile/index.tsx` —— 加 `usePullDownRefresh(() => void load())`，
并在 `load()` 的 `finally` 里 `Taro.stopPullDownRefresh()`（成功失败都停）。

**验证**：「我的」页下拉 → 数据刷新 → 动画自动收起；断网下拉也不再卡住。

---

## 二、H5 P0（3 条）

### P0-5 登录超过 2 小时后，点任意 Tab 被踢回登录页

**原因**：`api/client.ts:30` 的续期判断是 `!url.includes('/auth/')`，把 `/auth/me` 也排除在
刷新之外。而 `App.tsx` 的 `RequireAuth` 依赖 `location.pathname`，每次切 Tab 都会重跑
`fetchCurrentUser()`。令牌过期（TTL 120 分钟）时拿到 401 → 直接 `redirectToLogin()`，
明明 refresh cookie 还有效却没机会用。加上用的是 `window.location.assign` 整页刷新，
还会把正在轮询的生成任务（1-2 分钟）一起冲掉。

**改动**：`frontend/src/api/client.ts`

- 白名单收窄为 `NO_REFRESH_URLS = ['/auth/refresh', '/auth/login', '/auth/dev-login']`
  （只排除**刷新接口自己**和**登录接口**——登录的 401 是业务结果，不是令牌过期）。
- 新增 `setUnauthorizedHandler()`，由 `App.tsx` 的 `UnauthorizedBridge` 注入 SPA 内 `navigate`，
  401 时走前端路由而不是整页刷新。

**验证**：登录后把 access token 手动改坏（或等 2 小时），切换 Tab → 应自动 refresh 成功、
页面正常；只有在 refresh 也失败时才跳登录页，且是 SPA 内跳转（正在轮询的生成任务不丢）。

### P0-6 「换一道」打开即写库，关掉弹窗无法回退

**原因**：`Menus/WeeklyView.tsx` 的 `openReplace` 一进来就 `await replaceMenuItem(...)`，
替换在**打开弹窗那一刻**已经生效；而 `onCancel` 只 `setReplaceTarget(null)`，
「换回上一道」按钮和撤销 Toast 都只在「就它了」路径上给。用户按 X/遮罩/ESC 关闭后，
上一道菜已经没了且找不回来。

**改动**：新增 `closeReplace()`，关闭前若菜已变（`current.id !== previous.id`）就调
`replaceMenuItem(menuId, id, { recipe_id: previous.id })` 换回上一道；`Modal.onCancel` 改接它。
语义变成：关闭 = 放弃，想留就点「就它了」。

**验证**：换一道 → 按 ESC 关闭 → 菜单恢复成原来那道菜；点「就它了」→ 保留新菜且可撤销。

### P0-7 保存任一偏好卡片，会静默回滚其它卡片未保存的编辑

**原因**：偏好页 5 张表单**同时挂载**（`Preferences/index.tsx:120-130`），
每张都有 `useEffect(..., [summary])` 用服务端值 `setForm`。而 `update*` 每次都会
`set` 一个新的 `summary` 对象引用 → 保存任意一张，另外 4 张正在编辑的内容被一起重置。
叠加风险：`fetchSummary()` 失败时用默认值渲染，此时点保存等于用默认值覆盖真实数据。

**改动**

| 文件 | 改动 |
|---|---|
| `frontend/src/stores/usePreferenceStore.ts` | 新增 `syncToken`：只有 `fetchSummary()` 会 +1，`update*` 不动它 |
| `Preferences/{Allergy,Diet,Household,HealthGoal,Budget}Form.tsx` | 用 `syncedRef` 守卫，只在 `syncToken` 变化时同步一次服务端值 |
| `frontend/src/pages/Preferences/index.tsx` | 加载失败且 `!loaded` 时渲染错误卡 + 「重新加载」，不再用默认值渲染表单 |

**验证**：在「过敏与忌口」加一条未保存 → 去「预算」点保存 → 回来那条还在；
断网进偏好页 → 显示错误卡和重试按钮，不是一堆空表单。

> 另：顺手把 H5 首页与小程序同款的 `notReady` 缺陷也修了
> （`frontend/src/pages/Today/index.tsx:211` → `step.key !== 'relax'`），
> 否则草稿菜单时用户同样找不到「去确认」入口。

---

## 三、引导改造：从写死流程 → 用户信息里的可配置开关

### 为什么要改

原来的引导状态是一个**孤立的布尔标记** `mp_onboarded`（在 `lib/session.ts` 里），
语义被写死在代码中：没走过就必须 `reLaunch` 到引导页，用户没有任何选择权；
而且它和登录凭据混在同一个模块里，`clearSession()` 很容易误伤。

### 数据结构变化

新增 `shared/user-settings.ts`（两端唯一真源）：

```ts
export type GuideShowMode = 'once' | 'always' | 'never'

export interface GuideSettings {
  enabled: boolean      // 总开关
  showMode: GuideShowMode  // 展示时机: 仅首次 / 每次启动 / 不自动展示
  completed: boolean    // 是否已完整走过一次 (once 模式用)
}

export interface UserSettings {
  version: number       // 结构版本, 结构变了 +1
  guide: GuideSettings
}
```

存储 key：小程序 `mp_user_settings:v1`（H5 暂无引导流程，未接入，但结构已就位便于将来共用）。

### 迁移与默认值（保证已有用户不受影响）

| 情况 | 结果 | 是否自动弹引导 |
|---|---|---|
| 有 `mp_user_settings:v1` | 原样读（缺字段用默认补齐，脏数据不会崩） | 按用户自己配的 |
| 无新 key，老 `mp_onboarded = true` | `{ enabled: true, showMode: 'once', completed: true }` | **否**（与老行为一致） |
| 无新 key，无老标记（新用户） | `{ enabled: true, showMode: 'once', completed: false }` | 是 |

老 key 在首次迁移成功后即被删除，不会和新设置打架。
判断逻辑收敛在纯函数 `shouldAutoShowGuide(settings)` 里，已用脚本验证过上表四种分支
（含脏数据回落默认）。

### 涉及文件

| 文件 | 变化 |
|---|---|
| `shared/user-settings.ts` | **新增**：类型 + 默认值 + `migrateUserSettings()` + `shouldAutoShowGuide()` |
| `shared/index.ts` | 导出新模块 |
| `miniapp/src/lib/user-settings.ts` | **新增**：storage 读写、老 key 迁移、`useUserSettings()` 订阅 hook |
| `miniapp/src/lib/session.ts` | **删除** `isOnboarded / setOnboarded / clearOnboarded` 及 `ONBOARDED_KEY`；`clearSession()` 加注释说明不动用户设置 |
| `miniapp/src/lib/guide-draft.ts` | **新增**：引导偏好的落库/暂存/补交 |
| `miniapp/src/pages/onboarding/index.tsx` | 改用 `markGuideCompleted()`；偏好真的落库；草稿可读；保存态 |
| `miniapp/src/pages/today/index.tsx` | 强制跳转 → `shouldAutoShowGuide()` |
| `miniapp/src/pages/login/index.tsx` | 登录后补交引导偏好 |
| `miniapp/src/components/ui/index.tsx` | `SetRow` 新增 `control` 插槽（放 Switch），有 control 时整行不再可点，避免热区打架 |
| `miniapp/src/pages/profile/index.tsx` | 新增「用户信息」分组：新手指引开关、展示时机（点击循环切换）、重新查看引导 |
| `miniapp/src/app.config.ts` | `pages[0]` 与 `entryPagePath` 改为 today |

### 用户可见行为

- 设置路径：**我的 → 用户信息**
- 「新手指引」开关关掉 → 不再自动展示，也不显示下面两项
- 「展示时机」点击在 仅首次 / 每次启动 / 不自动展示 之间循环
- 「重新查看引导」随时手动进入引导页（状态显示 已看过 / 未看完）
- 走完引导记 `completed`，默认（仅首次）下不再打扰

### 验证方式

```bash
node -e "import('./shared/user-settings.ts').then(...)"   # 迁移分支（已跑, 见上表）
cd miniapp   && npx tsc --noEmit && npx taro build --type weapp
cd frontend  && npx tsc --noEmit && npx vite build
```

真机：
1. 老版本已引导的账号升级 → 冷启动直接进首页（不弹引导）
2. 清缓存新装 → 冷启动进引导，走完后进首页且偏好已保存
3. 我的 → 用户信息 → 关掉引导 → 再冷启动不弹；改成「每次启动」→ 每次冷启动都弹
4. 点「重新查看引导」→ 进引导页，物理返回能回到「我的」
