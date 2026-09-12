# 微信小程序全面审查报告

> 审查对象: `miniapp/`（Taro 4.2.1 + React 18 + TypeScript，编译产物为微信小程序）
> 审查时间: 2026-09-12
> 审查工程师视角: WeChatMiniProgramDeveloper
> 配套文档: `docs/miniapp-troubleshooting.md` / `miniapp/BUILD.md` / `shared/tokens.ts`

---

## 摘要

**整体评价**：项目功能闭环完整、视觉系统统一、代码质量在中等偏上水平，处于"可演示、可内测"阶段。距离"正式上线获客"还差 **P0 类的合规与增长基建**（隐私协议 / 反馈入口 / 分享引导 / 启动引导 / 订阅消息 / 启动期初始化）。

**致命问题 0 个**，**高风险问题 4 个**（启动期主题没初始化 / app.ts 完全空 / 反馈入口缺失 / 分享 hook 缺失），**中等问题 12 个**，**建议项 14 个**。

按维度统计：

| 维度 | 高 | 中 | 建议 |
| --- | --- | --- | --- |
| 1. 功能完整性 | 1 | 3 | 4 |
| 2. UI/UX 体验 | 1 | 3 | 3 |
| 3. 主题与视觉 | 0 | 1 | 3 |
| 4. 性能与体验 | 1 | 2 | 3 |
| 5. 缺陷排查 | 1 | 2 | 1 |
| 6. 上线与获客 | 5 | 4 | 2 |

---

## 1. 功能完整性

### ✅ 已实现（核心闭环 OK）

- 4 个 Tab 页：**今日 / 周菜单 / 采购 / 冰箱**
- 我的（profile，5 项偏好：家庭与厨房 / 口味与安全 / 过敏源 / 健康目标 / 预算）
- 登录：微信一键登录 + 本地开发登录（后端 `APP__AUTH__DEV_LOGIN` 开关）
- 菜单生成（异步 task + 3s 轮询 + 5min timeout）
- 餐次级操作：**换一道**（本地优先 + force_ai + 换回上一道）/ **锁定 / 解锁** / **标记已做 / 撤销**
- **拍照识别入库**（基础库 2.10+ 用 `chooseMedia`，老版本回退 `chooseImage`）
- **库存管理**（增 / 删 / 查 / 临期标记）
- **一键补单**（deep link 降级链：miniappAppId → order_link → 复制清单）
- **自动化状态**（飞书机器人连接 / 推送开关 / 最近推送记录，只读）
- **主题 4 态切换**（cool / cream / dark / auto，含命名收敛 + storage `:v2` 迁移）
- **一键复制清单**（按品类分组 + Markdown 文本）
- 退出登录（带二次确认 modal）

### ❌ 高风险缺失（影响上线）

**F1.【高】无任何反馈/客服入口** — 严重度 **P0**

- 现象：用户遇到「识别错了」「菜单不符合口味」「崩溃」只能去微信群吐槽，开发者无法收敛。
- 现状：`lib/api.ts` 没有 `feedback`/`issue`/`contact` 接口；`pages/profile/index.tsx` 没有任何反馈 set-row；后端 `app/api/` 也没有对应 router。
- 修复：
  1. 后端加 `POST /api/feedback`（接受 `category: 'bug' | 'suggestion' | 'recipe' | 'other'`、`content`、`contact?`、`device_info`）
  2. `lib/api.ts` 暴露 `submitFeedback()`
  3. profile 增加「意见反馈」SetGroup，弹起自定义 sheet（避免直接打开客服窗口失败）
  4. 接入 `Taro.openCustomerServiceChat`（小程序原生客服，需先在微信后台绑定客服微信号）

**F2.【高】无订阅消息** — 严重度 **P0**

- 现象：菜单生成好了、临期食材、生成失败这些关键时刻没有任何触达，用户回来率低。
- 现状：项目没有任何 `Taro.requestSubscribeMessage` 调用。
- 修复：
  1. 微信后台申请 1 个「长期订阅」模板（小程序类目：工具 → 效率；推荐场景：定时提醒）
  2. 关键节点埋点：菜单生成成功 / 临期 3 天 / 库存不足 / 推送失败
  3. 「我的」增加「消息订阅」SetGroup，列出现有可订阅模板 + 一键授权

**F3.【高】无分享 hook（onShareAppMessage / onShareTimeline）** — 严重度 **P0**

- 现象：从今日 / 周菜单转发给好友，对方打开是空白页面（无法登录 + 没有菜单）。
- 现状：6 个页面都没配置 `useShareAppMessage` / `useShareTimeline`，转发按钮虽然存在但转发内容空。
- 修复：
  1. 周菜单页配置 `useShareAppMessage`：标题 = 「这周打算做 XX」；path = `/pages/menu/index?share_from=xxx`
  2. 今日页配置「转发给家人」快捷入口（家人可能是同一个账号的多设备）
  3. 监听 query 参数 `share_from`，落地后展示「这是 XX 转给你的」Banner
  4. （可选）朋友圈支持 `useShareTimeline` —— 周菜单适合晒

### ⚠️ 中等问题

**F4.【中】无新用户引导（Onboarding）** — P1

- 首启动直接进今日页，但「填偏好」「生成菜单」都要用户主动探索。
- 修复：新增 `pages/onboarding/index.tsx`，3 步卡片：
  1. 选家庭人数 / 餐次
  2. 选 3 个偏好菜系
  3. 一键生成第一份菜单
- 启动后检测 `localStorage.getItem('mp_onboarded')` 决定是否路由到 onboarding

**F5.【中】无搜索能力** — P2

- 周菜单只能滚动浏览；菜谱库 9000+ 道没有搜索入口。
- 修复：周菜单顶部加 search bar（输入即过滤），菜谱库入口先放冰箱页的「按食材搜」。

**F6.【中】无版本号 / 更新提示** — P1

- 微信后台强制升级场景没有 UI 提示。
- 修复：
  1. 后端 `GET /api/build-info` 返回 `{ min_version, latest_version, force_update }`
  2. `app.ts` 启动调一次；`force_update=true` 时 `Taro.showModal` + `Taro.reLaunch` 到更新页
  3. profile 显示当前版本号

### 💡 建议项

- F7. **菜谱详情页**（点菜单行看完整做法 + 食材清单），目前只能看名字 + 食材列表，没步骤。
- F8. **历史菜单**（查看上周做了什么、可一键复用），需后端加 `GET /api/menus/history`。
- F9. **家庭成员**（多人一户场景：每人偏好独立 + 共同预算），目前一户一偏好。
- F10. **多周规划**（一次生成 2-4 周，月度备菜）。

---

## 2. UI 人机交互体验

### ✅ 优点

- 自定义 TabBar 悬浮毛玻璃（参考稿设计感）
- 极简图标（CSS View 画的，零图片资源）
- 全套 UI 组件统一（Card / BentoGrid / PillButton / Chip / Bar / StatTile / Banner / EmptyState / LoadingStack / SetRow / SetGroup / NextStepCard）
- 触控反馈：`.tap:active { transform: scale(0.965) }`，全 44px 触控目标
- Pull-down refresh + loading skeleton + error banner 三态齐全
- Toast 统一封装（`nav.ts` 的 `toast(title, icon)`）

### ❌ 高风险问题

**U1.【高】首次启动今日页空白感强** — P0（体验）

- 现状：未登录直接 reLaunch 到登录页（OK）；登录后立刻显示今日页，但若 `nextStep.isGenerateAction=true`（即还没生成菜单），会卡在「下一步」卡 + 「正在读取」骨架屏，新用户不知道下一步该干嘛。
- 修复：
  1. 骨架屏换成「带图标的引导骨架」：头部 OK、下一步卡显示「先生成菜单」预览
  2. 首次启动跳过骨架屏，直接显示空状态卡片（首屏 < 800ms 必须出可见元素）

### ⚠️ 中等问题

**U2.【中】profile 页 611 行 / 单卡片折叠式** — P1

- 折叠交互（点 set-row 展开表单）节省跳转，但首屏需要 3-4 次点击才能完成所有偏好。
- 修复：
  1. 把 5 个偏好拆成 5 个 SetGroup + 顶部进度条 `（3/5 已填）`
  2. 「完成度 → 100%」时整个 set-group 显示绿色对勾（视觉奖励）
  3. 折叠 / 展开时给 200ms 高度过渡（避免突然的版面跳动）

**U3.【中】page-head__action 头像过于隐晦** — P1

- 现状：今日页右上角 `<View className="page-head__action">` 显示用户名首字。新用户可能不知道它是「我的」入口。
- 修复：图标化（小人形 SVG）+ tooltip hover（不可用则 tooltip）：hover 不可用，至少首次点击有 toast 提示「点这里看我的偏好」

**U4.【中】删除/危险操作无二次确认** — P1

- 现状：删除库存项、退出登录有确认 modal；但**撤销标记已做**没有二次确认（OK，撤销本身可被再次撤销）。
- 建议：把「删食材」「重置偏好」等不可逆操作都加 `Taro.showModal`。

### 💡 建议项

- U5. **键盘体验**：`<Input>` 没看到 `confirm-type="search"` / `confirm-type="done"` 配置；输入「菜谱关键词」按搜索应直接触发搜索。
- U6. **loading 反馈**：`recognize-sheet.tsx` 拍照后识别期间没有进度提示（只能看到「正在识别…」按钮文字），超过 10s 用户会以为卡死。加 Taro.showLoading 或骨架屏。
- U7. **空状态**：fridge 页空状态（用户没添加任何食材）应展示「拍照入库 / 手动添加」两个入口，目前只展示「手动添加」。

---

## 3. 主题与视觉设计

### ✅ 优点

- 三套调色板（cool / cream / dark）+ auto，跟随系统
- `gen_tokens.mjs` 输出**全令牌**（58+）+ 双调色板（修复了 V2.3 字体/阴影/布局令牌失效问题）
- Logo 自动切换：cool / cream → 深容框，dark → 白底容框
- 全套 UI 组件 + 全局样式 1107 行统一管理
- 数字 `tabular-nums`，金额/进度对齐后才「亲近」（这是细节加分）

### ❌ 中等问题

**V1.【中】Logo 用 base64 PNG，体积大** — P1

- 现状：`lib/logo.ts` 暴露两个 `data:image/png;base64,...`，单张约 4KB（两套共 8KB 全部进 bundle）。
- 微信小程序从基础库 2.13+ 已支持 SVG，且 SVG 矢量缩放清晰。
- 修复：保留 fallback（极老基础库），但主路径切 `<Image src="/assets/logo-mark.svg">`（与 H5 一致），减小 bundle 体积约 60%。

### 💡 建议项

- V2. **图标库缺失**：所有图标都是 CSS View 拼的几何形，缺少「确认打勾 / 分享 / 设置 / 消息 / 删除 / 编辑 / 关闭 / 箭头」等通用图标。可引一个轻量图标库（如 `lucide-react` 经 taro alias 兼容），或自画 SVG 集合（22 个左右够用）。
- V3. **品牌故事**：profile 页底部只显示「数据本地存储」+ 域名，没有品牌 slogan / 团队介绍 / Logo 大图，留白过多。可加 1 张品牌卡。
- V4. **数字字体**：当前 `font-family: $font-family` 走系统字体，没有专属字体（中文数字 / 英文）。可考虑 `font-family: -apple-system, "PingFang SC", "Helvetica Neue"` 标准化。

---

## 4. 性能与体验优化

### ✅ 优点

- browserslist 压到 ES5（小程序兼容）
- 401 自动续期（refresh 一次 + 共享 Promise 防重入）
- 重复请求保护（`refreshing` 共享 Promise）
- skeleton / loading 状态
- pull-down refresh
- useMemo 缓存（shopping 分组、today nextStep）
- 异步生成走 task 轮询（3 秒一次，5 分钟 timeout）

### ❌ 高风险问题

**P1.【高】app.ts 完全空 — 启动期主题未初始化** — P0（功能）

- 现状：
  ```ts
  function App({ children }: PropsWithChildren) {
    return children
  }
  ```
  `lib/theme.ts` 的 `initTheme()` **从未被调用**，意味着：
  - storage `mp-theme:v2` 没被读取
  - 旧 `mp-theme` 迁移逻辑没跑（dark → cool）
  - `setNavigationBarColor` 启动期没调（首屏导航条颜色可能与主题不符）
- 修复：改 `app.ts`：
  ```ts
  import { initTheme } from './lib/theme'
  function App({ children }: PropsWithChildren) {
    useEffect(() => initTheme(), [])
    return children
  }
  ```
  （注意 Taro 的 `useEffect` 等价于 React，且需要在挂载后跑）

### ⚠️ 中等问题

**P2.【中】无请求 abort 机制** — P1

- 现状：`request.ts` 的 `send()` 没有 abort signal；用户在「今日」页发起 `getToday()` 后立刻切到「周菜单」，前一个请求回来时仍会 `setData`——React 18 会警告「set state on unmounted」。
- 修复：
  1. `send(path, options, retry, signal?: AbortSignal)`
  2. 页面 useEffect cleanup 创建 `AbortController`，传 `signal` 进 send
  3. Taro 4.x 用 `AbortController`，React 18 的 useEffect 也支持

**P3.【中】无埋点** — P1

- 现状：登录 / 生成菜单 / 拍照识别 / 换一道 / 标记已做 / 退出登录这些关键行为没有任何统计。
- 修复：
  1. 接入小程序原生 `wx.reportMonitor` / 自建埋点 endpoint
  2. 关键指标：DAU、菜单生成成功率、识别准确率（用户修正率）、换一道触发率
  3. 后端 `POST /api/events` 接收 batch 上报

### 💡 建议项

- P4. **onShow 全量 fetch**：today/shopping/fridge 三个 Tab 每次 onShow 都全量拉，没有 stale-while-revalidate。可加 30s 缓存（swr 模式：命中缓存先 render，后台静默刷新）。
- P5. **分包加载**：主包 700KB+ 含 6 个页面 + 11 个 lib + 2 个业务组件。pages/login 和 pages/profile 可分包（login 用户不一定走到，profile 偶尔进入）。
- P6. **首屏骨架**：today 页首次加载的 LoadingStack 是 5 行通用骨架，看不到头部 / 卡片轮廓，对首屏 LCP 不友好。建议渲染一个「模拟 layout」的骨架（带头部 + 卡片轮廓）。

---

## 5. 缺陷排查与修复

### ❌ 高风险缺陷

**B1.【高】app.ts 完全空** — 同 P1，影响：启动期主题错、storage 迁移失效、首屏 nav bar 颜色错。**P0 必修**。

**B2.【高】deeplink 永远走复制清单** — P1

- 现状：`openPurchaseLink()` 第一选择是 `navigateToMiniProgram(appId)`，但 `data.order.miniapp_app_id` 后端从未配置（属于二期数据源 V3.0），实际永远走第三条：复制清单 + showModal。
- 影响：用户点「立即下单」要经历 3 步（toast → modal → 知道），期望的「一键跳转小象超市」不存在。
- 修复：
  1. 加埋点：每次走清单降级都上报，统计降级率
  2. 若配置了 appId 但 `navigateToMiniProgram` 失败（未在 `app.json` 的 `navigateToMiniProgramAppIdList` 登记），给具体提示「去开发者后台加 appid 白名单」
  3. 短期：把按钮文案改成「复制清单，去小象超市」更直观

### ⚠️ 中等缺陷

**B3.【中】app.config.ts backgroundColor 写死** — P1

- 现状：`window.backgroundColor: '#e9e9ee'` 硬编码冷灰色。
- 影响：深色模式下，用户下拉刷新时背景闪一下冷灰，体验不连贯。
- 修复：动态设置 `Taro.setBackgroundColor`（需要基础库支持），或干脆去掉 backgroundColor 让 page 颜色接管。

**B4.【中】today 页 handleCook 类型强转** — P2

- 现状：
  ```ts
  const menuLike = { id: data.menu_id } as never
  await markCooked(menuLike as never, data.tonight.meal_id)
  ```
- 影响：跳过类型检查，如果 `markCooked` 改成读 `menu.week_start_date`，运行时炸。
- 修复：让 `markCooked` 接受 `{ id: number }` 子类型而非 `MenuDetail`。

**B5.【中】profile 解构 useTheme 丢弃第三个返回值** — P2

- 现状：
  ```ts
  const [theme, setTheme] = useTheme()
  ```
  实际签名是 `[ThemeName, setter, PaletteName]`，第三个 `applied` 被丢弃。
- 修复：要么只取两个并改 useTheme 签名，要么明确 `const [theme, setTheme, applied] = useTheme()`（将来需要时再用）。

### 💡 兼容性缺陷

- B6. **iOS 14 以下不支持 `showModal editable:true`**：今日页「外卖参考价」用 `Taro.showModal({ editable: true })`，老 iOS 微信会忽略 editable。**修复**：改用自绘 sheet（已有 RecognizeSheet 可复用模式）。
- B7. **Taro.chooseMedia 在某些 Android 厂商内核（OPPO ColorOS 11 之前的某些版本）不支持**：已 fallback chooseImage，正确。
- B8. **base library 3.17.1 vs libVersion**：package.json `browserslist` 写压 ES5，但 `libVersion` 字段写 3.17.1（2026 年当前最新稳定在 3.x）。建议提升到 3.x.x latest。

---

## 6. 上线与获客建议

### 🎯 MVP 优先级排序（按"上线即用"和"获客效率"双轴）

| 优先级 | 项 | 估时 | 关键产出 |
| --- | --- | --- | --- |
| **P0** | 隐私政策 / 服务条款 / 关于页 | 0.5 人天 | 微信审核必备 |
| **P0** | 意见反馈入口（F1） | 1 人天 | 用户问题收敛 |
| **P0** | 分享 hook（F3） | 0.5 人天 | 增长入口 |
| **P0** | 启动期初始化（修复 P1） | 0.5 人天 | 首屏体验 |
| **P0** | 新用户引导（F4） | 1 人天 | 激活转化 |
| **P1** | 订阅消息（F2） | 1 人天 | 留存触达 |
| **P1** | 客服入口（F1 子项） | 0.5 人天 | 客服 chat |
| **P1** | 版本号 + 更新检测（F6） | 0.5 人天 | 强制更新 |
| **P2** | 邀请好友裂变（注册各得一次 AI） | 2 人天 | 拉新 |
| **P2** | 菜谱详情页（F7） | 2 人天 | 内容厚度 |
| **P2** | 历史菜单（F8） | 1 人天 | 数据复用 |
| **P3** | 搜索（F5） | 2 人天 | 体验优化 |

### 📈 增长与运营配置

1. **小程序码 + 海报生成**
   - `Taro.saveImageToPhotosAlbum` + 后端 `POST /api/share/poster` 生成「我的本周菜单」海报
   - 朋友圈传播路径

2. **公众号关联**
   - 同一主体下关联公众号，菜单生成后给公众号推模板消息
   - 公众号菜单挂小程序入口

3. **首次启动权益**
   - 新用户注册自动送 5 次 AI 生成额度（本地菜谱无限）
   - 7 天后未用完推送提醒

4. **基础运营配置（上线前必做）**
   - [ ] 微信小程序后台：备案（已 ICP 的域名 + HTTPS）
   - [ ] 客服微信号绑定
   - [ ] 用户隐私协议 URL（指向 docs/legal/）
   - [ ] 业务域名配置（`request合法域名`）
   - [ ] 小程序类目选择（工具 → 效率 或 医疗 → 健康管理）
   - [ ] 测试号 / 体验号 / 正式号切换

5. **数据看板**
   - 后端 `GET /api/admin/metrics` 给运营后台
   - 指标：DAU / 菜单生成成功率 / 识别修正率 / 7 日留存

---

## 附录 A：修复方案汇总（按代码量排序）

| # | 文件 | 改动 | 行数估计 |
| --- | --- | --- | --- |
| 1 | `miniapp/src/app.ts` | `useEffect(() => initTheme(), [])` | +3 |
| 2 | `miniapp/src/app.config.ts` | 删 window.backgroundColor 写死 | -3 |
| 3 | `miniapp/src/lib/api.ts` | 加 `submitFeedback()` | +15 |
| 4 | `miniapp/src/pages/profile/index.tsx` | 加反馈 / 版本号 / 客服入口 set-group | +60 |
| 5 | `miniapp/src/pages/onboarding/index.tsx` | 新建（3 步引导） | +200 |
| 6 | `miniapp/src/pages/menu/index.tsx` | 加 `useShareAppMessage` | +10 |
| 7 | `miniapp/src/pages/today/index.tsx` | 加 `useShareAppMessage`、错误提示 | +20 |
| 8 | `backend/app/api/feedback.py` | 新建 `POST /api/feedback` | +60 |
| 9 | `backend/app/api/build.py` | 新建 `GET /api/build-info` | +25 |
| 10 | `miniapp/src/lib/request.ts` | 加 AbortSignal 支持 | +15 |
| 11 | `miniapp/src/lib/events.ts` | 新建埋点 SDK | +80 |

---

## 附录 B：风险地图

```
                    紧急度（用户感知）
                低                 高
            ┌────────┬────────┐
      高    │ F1反馈 │ F3分享 │  ← 用户增长
            │ B1启动 │ U1首屏 │
   影响     ├────────┼────────┤
      中    │ F4引导 │ F2订阅 │
            │ V1图标 │ P1缓存 │
            ├────────┼────────┤
      低    │ B6兼容 │ F8历史 │
            │ V3字体 │ P5分包 │
            └────────┴────────┘
```

优先攻克右上象限（F1/F3/B1/U1），同时推进左上象限（F4/F2）做留存。