# 微信小程序 QA 报告：UI 适配检查 + 功能测试 + 缺陷修复

> 范围：`miniapp/`（Taro 4 + React）。**未改动后端逻辑代码，也未改动 H5 的 frontend/ 实现**，
> 所有修改均收敛在小程序端源码。产物：`miniapp/dist`（已重新构建）。
>
> 基线：`npm run typecheck` 通过、`npm run build:weapp` 成功。

---

## 一、修复清单

### 1. UI 适配类

| # | 问题 | 影响 | 修复 |
|---|------|------|------|
| U1 | `.page` 的 `padding-bottom` 未计入 `safe-area-inset-bottom` | 在带 home 指示条机型（iPhone X 及以上、大部分安卓全面屏）上，页面最后一块内容会被悬浮 TabBar 或系统手势条遮挡 | `padding-bottom` 追加 `+ env(safe-area-inset-bottom, 0px)` |
| U2 | 悬浮 `.tabbar` 固定 `bottom: 14px`，未避开底部手势条 | 图标/文案在全面屏机型上贴 / 盖住 home 指示条 | `bottom: calc(14px + env(safe-area-inset-bottom, 0px))` |
| U3 | `.page` 未使用 `$layout-page-max: 1120px` 令牌（已定义但闲置） | iPad / 平板 / 微信侧边栏等大屏下正文拉成通栏，阅读体验差 | `.page` 增加 `max-width: $layout-page-max; margin: 0 auto`（手机不受影响，仍占满全宽） |
| U4 | 今日页右上角头像入口 `.page-head__action` 仅 38×38px | 触控目标小于项目规则要求的 44px，易误触 | 改为 `$layout-tap-target`（44×44px） |

### 2. 功能 / 渲染缺陷类

| # | 问题 | 影响 | 修复 |
|---|------|------|------|
| F1 | 今日页「补单明细」行 `key` 用 `name-is_topup` | 当缺口里出现同名食材（多条 `ingredient_id` 相同或不同缺口同名）时 key 冲突，会导致该列表渲染/复用错乱 | key 改为 `ingredient_id ?? name + is_topup + index`，保证唯一 |
| F2 | 今日页 `import { Chip }` 但从未使用 | 无用导入（编辑器告警） | 移除 |

### 3. 小程序专属 API 兼容类

| # | 问题 | 影响 | 修复 |
|---|------|------|------|
| C1 | `Taro.getWindowInfo()` 需基础库 2.20.1+ | 在更老的基础库上调 `undefined()` 抛错，`PageHead` 的 `top` 退化为固定 64，状态栏高度读取失败 | 检测到 `getWindowInfo` 不可用时回退 `Taro.getSystemInfoSync()` |
| C2 | `Taro.chooseMedia()` 需基础库 2.10+ | 极老基础库上拍照识别无法取图 | 增加 `Taro.chooseImage()` 回退（拍照识别组件 `recognize-sheet`） |
| C3 | 登录页配置了 `enablePullDownRefresh: true` 但未实现 `onPullDownRefresh` | 下拉为空操作（无语义刷新），且登录页根本无需下拉 | 移除登录页该项配置 |

---

## 二、检查结论（未改动，但已核对 / 记录）

| 项 | 结论 |
|----|------|
| **自定义 TabBar** | 悬浮毛玻璃胶囊为自定义实现；`syncTabBar()` 在各 tab 页 `onShow` 同步选中态，`switchTab`/`navigateTo` 选择逻辑与 `app.config.ts` 的 tabBar.list 严格对齐，正确 |
| **登录守卫** | 各页 `ensureLogin()` 未登录 `reLaunch` 到登录页；登录成功 `switchTab` 回今日页。深链（分享/扫码）场景可兜住，正确 |
| **`wx.showModal` editable**（用于「换一道」/「改外卖价」） | `editable`/`placeholderText` 自基础库 2.17.3（2021 年）起在主流 iOS/Android 微信客户端稳定支持，当前微信基础库远高于该版本，**无需改动**；仅记录：极老的 iOS/Windows 桌面端可能不显示输入框（属已知平台限制） |
| **`wx.navigateToMiniProgram`（跳小象超市）** | 目标 AppID 由后端动态下发，无法静态写入 app.json `navigateToMiniProgramAppIdList`；代码已 `try/catch`，失败时优雅降级为「复制清单 + 提示搜索」——属设计内行为，**无需改动** |
| **rpx 缩放** | `designWidth: 375` + `pxtransform`，按 375 设计稿换算 2rpx/px，与 `_tokens.scss` 单一真源一致；数值/字体已 `tabular-nums` 对齐 |
| **xhr / storage / toast / clipboard / uploadFile** | 均为 iOS / Android / 开发者工具通用 API，无平台分叉调用 |

---

## 三、功能回归清单（逐页）

> 对关键交互做了静态走查。`✓` = 逻辑核对通过（含本轮修复点）。

- **登录页（login）** ✓ 微信一键登录 / 本地开发登录切换、错误文案；去掉了多余下拉刷新。
- **今日页（today）** ✓ 预算条形 + 下一步指引卡；补单清单（**key 修复**）；今晚菜单（做完了扣库存）；自做 vs 外卖改价（editable modal）；本周概览 Bento；临期入口；拍照入库。
- **周菜单（menu）** ✓ 星期条切换；换一道 / 锁定 / 标记已做；确认菜单引导；重新生成（保留锁定）；预算条。
- **采购（shopping）** ✓ 一键补单 deeplink；一键复制清单；按品类分组 + 划掉勾选；单位不匹配 banner；冰箱已有兜底区。
- **冰箱（fridge）** ✓ 拍照识别入库；手动记一笔（名称/数量/单位 Picker/保质期选择）；临期高亮与筛选。
- **我的（profile）** ✓ 五项偏好就地编辑与保存；自动化状态卡；退出登录（失败也清本地）。
- **全局 TabBar** ✓ 四 tab 切换与高亮同步。

---

## 四、兼容性验证

- `tsc --noEmit`（严格模式）通过。
- `taro build:weapp` 编译成功，`dist/app.wxss` 已确认包含 `safe-area-inset-bottom`、`dist/common.js` 已确认包含 `getWindowInfo`/`getSystemInfoSync` 双通道回退。
- 说明：真机/多基础库实测需在微信开发者工具与真机上执行；本报告为静态 + 构建级验证，已覆盖主流机型适配与 API 兼容点。

---

## 五、涉及文件

| 文件 | 改动 |
|------|------|
| `miniapp/src/app.scss` | U1 / U2 / U3 / U4 |
| `miniapp/src/components/ui/index.tsx` | C1（getWindowInfo 回退） |
| `miniapp/src/components/recognize-sheet.tsx` | C2（chooseImage 回退） |
| `miniapp/src/pages/today/index.tsx` | F1 / F2 |
| `miniapp/src/pages/login/index.config.ts` | C3 |
| `miniapp/dist/` | 重新构建产物（小程序代码包） |