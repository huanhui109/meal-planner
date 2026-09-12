# 微信小程序「开发者工具里跑不起来」排查与修复

> 排查对象：`miniapp/`（Taro 4.1.x/4.2 + React 18 + TS）。
> 现象：H5（`frontend/`）功能全部正常，同一套 `shared/` 业务层在小程序端不可用。
> 证据来源：微信开发者工具自身运行日志
> `~/Library/Application Support/微信开发者工具/<hash>/WeappLog/logs/*.log`。

---

## 一、结论先行

**H5 能跑不等于小程序能跑**，差别不在业务代码（业务层是共享的、没有用到任何浏览器专有 API），
而在**产物语法层级**和**小程序工程配置**这两件事上。本次共定位 4 个问题，其中 1 个是硬故障、3 个是配置/流程问题。

| # | 问题 | 严重度 | 状态 |
|---|------|--------|------|
| 1 | 产物含可选链 `?.` / 空值合并 `??`，被微信编译器判为「非法的文件」 | **致命** | ✅ 已修 |
| 2 | `project.config.json` 的 `urlCheck: true`，本地请求 127.0.0.1 被拦 | 高 | ✅ 已修 |
| 3 | 后端地址硬编码 `127.0.0.1:8000`，真机必然连不上 | 高 | ✅ 已修（可配置） |
| 4 | `taro build` 会整体清空 `dist/`，触发工具误报 `app.json 不存在` | 中（自愈） | ✅ 已说明+规避 |
| 5 | 只跑过 `taro build --type h5`，`dist/` 从未完整构建，工具报"未找到 app.json" | 中 | ✅ 已修（V2.5 收口） |

---

## 二、根因与证据

### 根因 1（致命）：产物语法层级过高，`?.` / `??` 没被降级

开发者工具日志中的原始报错：

```
[2026-09-11 10:45:08.742][ERROR] ... wxа-dev/testsource ...
Error: 非法的文件，错误信息：invalid file: common.js, 1:612
SyntaxError: Unexpected token .
"use strict";(wx["webpackJsonp"]=... )... e=n.tempFiles?.[0]?.tempFilePath||""
   ... m(n.items??[]) ...
```

`common.js, 1:612` 指向的代码正是 `src/components/recognize-sheet.tsx:50`
的 `media.tempFiles?.[0]?.tempFilePath` 与 `data.items ?? []`。

**为什么会这样**：`miniapp/package.json` 里写的 browserslist 是

```json
"browserslist": ["defaults and fully supports es6-module", "maintained node versions"]
```

这组目标**全部原生支持可选链与空值合并**，于是 `@babel/preset-env` 判定"无需降级"，
把 `?.` / `??` 原样保留进 `dist/`。

- **H5 端**：现代浏览器直接支持 → 完全正常，所以问题只在小程序暴露。
- **小程序端**：微信开发者工具/服务端的编译器 parser 与部分 Android（X5 / 旧 V8）内核
  不认这套语法，直接把代码包判为非法文件 → 启动超时（`routeTo appLaunch timeout`）、真机白屏。

修复前实测 `dist/` 残留：

```
common.js              ?.×16   ??×12
pages/today/index.js   ?.×40   ??×13
pages/profile/index.js ?.×18   ??×10
pages/menu/index.js    ?.×12   ??×3
```

### 根因 2（高）：域名校验在主配置里是开的

```jsonc
// miniapp/project.config.json（会被提交）
"setting": { "urlCheck": true }
```

它之所以"看起来能用"，是因为 `miniapp/project.private.config.json` 把它覆盖成了 `false`。
但**私有配置在 `.gitignore` 里**（`miniapp/project.private.config.json`），
换机器、清缓存、重新导入项目都会打回 `true` → 所有 `http://127.0.0.1:8000/api` 请求被拦截，
表现为"页面一直在转圈 / 每个接口都失败"。

### 根因 3（高）：真机访问不到电脑的 127.0.0.1

`config/dev.ts` 原来把地址写死：`http://127.0.0.1:8000/api`。
开发者工具的模拟器跑在本机所以能用；**真机预览/真机调试时小程序运行在手机上**，
`127.0.0.1` 是手机自己 → 必然全链路请求失败。

### 根因 4（中）：构建清目录导致工具误报

Taro 每次 `taro build` 启动会先整体删除 `dist/`。开发者工具的文件监听会立刻触发重编译，
于是日志里刷出一大片：

```
hotreload error Error: summer-compiler miss dist/ js file, pages/today/index.js
updateAppCode app.js Error: The file app.json doesn't exist
```

构建写回文件后这些错误会自愈，但期间工具会显示"app.json 不存在 / 白屏"，
容易被误判成"小程序坏了"。

### 根因 5（中）：从未跑过 weapp 构建，`dist/` 是空的

`miniapp/` 的 Taro 配置用 `isH5 = process.argv.includes('h5')` 决定 `outputRoot`
（`dist/` 或 `dist-h5/`）。最近一次开发只跑过 h5，于是 `dist-h5/` 里有完整产物
（`index.html`、`js/`、`css/`），而 `dist/` 里**只有一个 `project.config.json`**
（来自 sourceRoot 的 copy），完全缺 `app.json` / `app.js` / `app.wxss` / `pages/`。

开发者工具按 `miniprogramRoot: "dist/"` 去找 `app.json` → 直接报：

```
根据 project.config.json 中 miniprogramRoot 指定的小程序目录 dist/，
在该目录下未找到 app.json。
```

**修复**：

1. 在 `miniapp/config/index.ts` 改用 `process.env.TARO_ENV === 'h5'` 判断
   （Taro 4 官方约定，CI / 嵌套调用稳定，命令行字符串匹配易误判）；
2. `miniapp/package.json` 补 `build:h5` / `dev:h5` 两个 npm script，
   让构建命令成为**唯一**触发入口；
3. 加 `miniapp/BUILD.md` 一份构建产物地图，避免开发者工具选错导入目录；
4. 跑一次完整的 `npm run build:weapp`，让 `dist/` 恢复全部产物。

**预防**：

- 始终用 `npm run build:h5` / `build:weapp` / `dev:weapp`，不要直接调 `taro build`。
- Taro 会整体清空 `outputRoot`，**两个平台不要共用同一个输出目录**（本项目
  分别用 `dist/` 和 `dist-h5/`）。
- 开发者工具导入项目时目录选 **`miniapp/`**，**不要选 `miniapp/dist/`**——
  工具会读 `project.config.json` 里的 `miniprogramRoot` 自动定位。

---

## 三、已做的修改

| 文件 | 改动 |
|------|------|
| `miniapp/package.json` | `browserslist` 从"现代浏览器"改为 `iOS >= 10 / Android >= 5 / Chrome >= 53 / Safari >= 10`，强制 babel 把 `?.`、`??`、`async/await`、class、解构等全部降级为 ES5 |
| `miniapp/project.config.json` | `urlCheck` → `false`；补 `libVersion: "3.17.1"`（原来只在被 gitignore 的私有配置里）；`packOptions.ignore` 排除 `.DS_Store` |
| `miniapp/config/dev.ts` | 后端地址支持 `MP_API_BASE` 环境变量覆盖，注释里写清真机该填什么 |
| `miniapp/dist/` | 已用新配置重新构建 |

### 修复后校验

```
node --check 全部 13 个产物 JS → 通过
dist/ 残留 ?.  → 0      ??  → 0
dist/ 残留 async/await → 0   let/const → 0   class → 0   展开 → 0
npm run typecheck       → 通过
taro build --type weapp → Compiled successfully
代码包体积               → 532K（远低于 2M 上限）
app.json 6 个页面 + custom-tab-bar + comp 组件引用 → 全部存在
```

---

## 四、还需要你人工确认 / 处理的事

这些我无法在命令行里替代你确认，但**每一件都会直接导致真机不可用**。

### 1. AppID `wxf240348f8cae1d34` 是否属于当前登录的微信账号

- 不属于 / 不存在 → 真机预览、真机调试、上传、微信一键登录**全部不可用**，只能留在模拟器。
- 确认路径：小程序后台 → 开发管理 → 开发设置 → 开发者 ID，与 `miniapp/project.config.json` 的 `appid` 比对。
- 临时方案：用「测试号」导入，先把模拟器跑通。
- 日志里出现过 IDE 内部请求 `gettestpublib?appid=`（appid 为空）返回
  `系统错误，错误码：41002, appid missing`，如果换了正确 AppID 后这条仍出现，就是账号不匹配。

### 2. 后端微信登录配置（影响"微信一键登录"按钮）

当前 `/api/auth/providers` 返回 `{"feishu":false,"wechat":false,"dev_login":true}`，
说明 `.env` 里没有 `WECHAT_APP_ID` / `WECHAT_APP_SECRET`，登录页不会出现"微信一键登录"，
只有"本地开发登录"（能用，可先打通全链路）。生产必须配好并关掉 `APP__AUTH__DEV_LOGIN`。

### 3. 后端默认只监听 127.0.0.1（真机连不上，已修）

实测发现：`scripts/service.sh` 里写的是 `BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"`，
所以默认起来的 uvicorn **只绑回环地址**，手机访问 `http://<电脑IP>:8000` 直接不通
（本机 `127.0.0.1` 一切正常，很容易误判成"后端没问题"）。

启动时显式指定即可，脚本本身支持环境变量覆盖：

```bash
BACKEND_HOST=0.0.0.0 bash scripts/service.sh restart backend
# 或
cd backend && .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

起好后用 `lsof -nP -iTCP:8000 -sTCP:LISTEN` 确认显示的是 `*:8000` 而不是 `127.0.0.1:8000`。
（注意：`config/default.yaml` 的 `app.host: 0.0.0.0` 对这个启动路径**不生效**，别被它误导。）

### 4. 真机预览的域名硬门槛

- 「**真机调试**」（扫码后手机上的调试模式）会自动跳过域名校验，可以用
  `MP_API_BASE=http://192.168.x.x:8000/api npm run dev:weapp`（前提：后端已按上面第 3 条绑到 `0.0.0.0`）。
- 「**预览**」模式**必然**校验：必须 HTTPS + 已完成 ICP 备案的域名，且在小程序后台
  「开发 → 开发管理 → 开发设置 → 服务器域名 → request 合法域名」登记（填域名，不带 `/api`），
  并同步改 `miniapp/config/prod.ts` 的 `API_BASE_URL`。

### 4.5 运行期报错：`s.setSelected is not a function`（自定义 TabBar 高亮）

编译能过、首屏也能出，但控制台反复刷 `MiniProgramError: s.setSelected is not a function`，
Tab 高亮偶尔不动。

**根因**：`miniapp/src/lib/nav.ts` 的 `syncTabBar` 原来调的是**原生** `page.getTabBar()`。
微信原生 `getTabBar()` 返回「原生组件实例」，它上面只有 `$taroInstances`（指向 Taro 的
React 组件实例），**没有** `setSelected`；`setSelected` 定义在 `custom-tab-bar/index.tsx`
的 React 组件实例上。对原生实例调 `setSelected` → 抛 `is not a function`。
（Taro 自己的 `taro.getTabBar(page)` 实现就是 `page.getTabBar().$taroInstances`，恰好返回 React 实例。）

**修法**：`syncTabBar` 改用 `Taro.getTabBar(page)`（返回 React 实例，`setSelected` 在其上），
并保留对原生 `$taroInstances` / `.component` / `.reactComponent` 的兜底，兼容不同 Taro 内部结构。
源码见 `miniapp/src/lib/nav.ts`。

---

## 五、验收清单（按顺序做一遍）

### 开发者工具

1. `cd miniapp && npm run build:weapp`（**先构建完再打开工具**，避免根因 4 的误报）。
2. 微信开发者工具 → 导入项目 → 目录选 **`miniapp/`**（不要选 `miniapp/dist/`）。
3. 详情 → 本地设置 → 确认「不校验合法域名…」已勾选（现在主配置已是 `false`）。
4. 编译后确认：
   - 控制台**没有** `invalid file` / `SyntaxError` / `非法的文件`；
   - 控制台**没有** `s.setSelected is not a function`（自定义 TabBar 高亮报错，见 §4.5）；
   - 首屏落到登录页，出现「用这个昵称进入」（`dev_login` 已开启）；
   - 登录后进今日页，四个 Tab 切换高亮正常；
   - 网络面板里 `http://127.0.0.1:8000/api/...` 返回 200。

### 真机

5. 后端已默认绑到 `0.0.0.0`（`service.sh` 新默认值）；如需确认，跑 `bash scripts/service.sh restart backend`，
   确认 `lsof -nP -iTCP:8000 -sTCP:LISTEN` 显示 `*:8000`。
6. 查电脑局域网 IP（`ipconfig getifaddr en0`，当前是 `192.168.3.83`）。
7. `MP_API_BASE=http://192.168.3.83:8000/api npm run dev:weapp`。
8. 开发者工具 → **真机调试**（不是"预览"）→ 扫码 → 手机上确认能登录、能拉到今日数据。
9. 正式预览前：配 HTTPS 备案域名 + 后台 request 合法域名 + 改 `config/prod.ts`。

### 回归提示

- 改了 `package.json` 的 browserslist 后，如果以后要出 H5（`miniapp` 的 h5 构建），
  产物也会按 ES5 出包，体积会略增——这是为了小程序安全刻意付出的代价，不要改回现代目标。
- 建议把「`dist/` 里不能出现 `?.`」加进 CI：
  `! grep -rn '?\.\|??' miniapp/dist --include=*.js`。
