# 微信小程序 (miniapp/) 配置与调试

小程序是独立工程（`miniapp/`，Taro 4 + React 18 + TypeScript + SCSS），与 H5 共用
`shared/` 里的类型、格式化、下一步规则和设计令牌。**功能与 H5 完全一致**，只是入口不同。

```
miniapp/
├── config/            Taro 编译配置（dev 走本机后端，prod 走正式域名）
├── src/
│   ├── app.ts         入口
│   ├── app.config.ts  页面与自定义 TabBar 声明
│   ├── app.scss       全局样式（Design System 的小程序实现）
│   ├── custom-tab-bar/ 悬浮毛玻璃胶囊导航（自绘，不用原生 tabBar）
│   ├── components/ui/  轻组件（不引 NutUI）
│   ├── lib/           请求层 / 登录态 / 业务接口 / 路由守卫
│   └── pages/         today · menu · shopping · fridge · profile · login
├── types/             全局类型与注入常量
└── project.config.json  微信开发者工具工程文件（miniprogramRoot 指向 dist/）
```

---

## 1. 装依赖与构建

```bash
make install-miniapp     # 等价于 cd miniapp && npm install
make build-miniapp       # 等价于 cd miniapp && npm run build:weapp
```

产物在 `miniapp/dist/`。

### 用微信开发者工具打开

1. 打开「微信开发者工具」→ **导入项目**。
2. 目录选 **`miniapp/`**（不是 `miniapp/dist/`，工程文件会自己找到 `dist`）。
3. AppID 填你自己的小程序 AppID；没有的话选「测试号」。
4. 点「编译」。

---

## 2. 后端需要配的两个开关

小程序登录走两条路，**至少有一条可用**：

### 路线 A：微信一键登录（真实用户，上线用）

编辑 `.env`：

```bash
WECHAT_APP_ID=wx0123456789abcdef
WECHAT_APP_SECRET=0123456789abcdef0123456789abcdef
```

- `WECHAT_APP_ID` / `WECHAT_APP_SECRET` 在小程序后台
  「开发 → 开发管理 → 开发设置 → 开发者 ID」里。
- 配好后访问 `GET /api/auth/providers` 会返回 `"wechat": true`，小程序登录页就会出现
  「微信一键登录」按钮。
- 没配时该按钮不显示（而不是点了报错），登录页会提示你先去配 AppID。

改完 `.env` 要重启后端：`make restart`。

### 路线 B：本地开发登录（不需要微信账号，先把全链路跑通）

编辑 `.env`：

```bash
APP__AUTH__DEV_LOGIN=true
```

登录页会出现「用这个昵称进入」。**这是开发专用入口，生产环境必须改回 `false`**，
否则任何人凭一个昵称就能建号。

---

## 3. 服务器域名（真机能联网的硬门槛）

小程序的 `wx.request` 只允许请求后台登记的 HTTPS 域名：

1. 小程序后台 → 「开发 → 开发管理 → 开发设置 → 服务器域名」。
2. 在 **request 合法域名** 里填 `https://你的域名`（**不带路径**，也不要带 `/api`）。
3. 该域名**必须已完成 ICP 备案**。没有备案的小程序真机无法联网，
   只能在开发者工具里勾上「不校验合法域名」调试。

同时把 `miniapp/config/prod.ts` 里的 `API_BASE_URL` 改成你的域名：

```ts
defineConstants: {
  API_BASE_URL: JSON.stringify('https://你的域名/api'),
}
```

### 开发期怎么绕过

微信开发者工具 → 右上角「详情」→「本地设置」→ 勾选
**「不校验合法域名、web-view（业务域名）、TLS 版本以及 HTTPS 证书」**。

这样 `config/dev.ts` 里的 `http://127.0.0.1:8000/api` 就能直连本机后端。
（开发者工具跑在本机，`127.0.0.1` 就是你的电脑；真机预览则不行，必须用 HTTPS 域名或内网穿透。）

---

## 4. 登录流程

```
点「微信一键登录」
   └─ Taro.login() 拿到临时 code
        └─ POST /api/auth/wechat/mini-login  { code }
             └─ 后端调微信 jscode2session 换 openid
                  └─ upsert 用户: open_id = "wechat:<openid>"
                       └─ 返回 { access_token, refresh_token, expires_in, user }
                            └─ 存进 Taro storage, 之后每个请求带 Authorization: Bearer
```

要点：

- **不需要新表**：微信用户复用 `user.open_id`，用 `wechat:` 前缀与飞书的 `ou_*`、
  本地开发的 `dev:` 分命名空间（见 `docs/architecture.md`）。
- **与飞书账号不绑定**：同一个人用微信和飞书登录会得到两个互不可见的账号，本期不做合并。
- **令牌存 storage 而不是 Cookie**：小程序没有可靠的 cookie jar；后端 `_extract_token()`
  同时认 Cookie 和 `Authorization: Bearer`，所以服务端不用改。
- **自动续期**：请求收到 401 时会用 `refresh_token` 打 `POST /api/auth/refresh`（body 传令牌），
  成功后自动重试原请求；失败则 `reLaunch` 回登录页。

---

## 5. 页面与导航

| 页面 | 路径 | 在 TabBar | 对应 H5 |
|------|------|-----------|---------|
| 今日（Bento + 补单卡 + 今晚菜单 + 自做 vs 外卖 + 时间线） | `pages/today/index` | ✅ 0 | `/` |
| 周菜单 | `pages/menu/index` | ✅ 1 | `/menus` |
| 采购清单 | `pages/shopping/index` | ✅ 2 | `/shopping` |
| 冰箱（拍照识别 + 临期） | `pages/fridge/index` | ✅ 3 | `/inventory` |
| 我的（偏好四组 + 机器人状态） | `pages/profile/index` | ❌ | `/me`、`/preferences` |
| 登录 | `pages/login/index` | ❌ | `/login` |

TabBar 用的是 `custom: true` + `src/custom-tab-bar/`（悬浮毛玻璃胶囊）。原生 tabBar 做不出
圆角悬浮与毛玻璃，所以 `app.config.ts` 里仍然声明 4 个 `list` 项（小程序要求），
但实际渲染由自定义组件接管；每个 tab 页在 `useDidShow()` 里调 `syncTabBar(n)` 同步高亮。

**「我的」不在 TabBar 里**：从今日页右上角头像 `navigateTo('/pages/profile/index')` 打开。
它不是 tab 页，所以 `pages/profile` 里**不要**调 `syncTabBar()`（会拿到不存在的 tab 而报错），
`lib/nav.ts` 的 `TAB_PAGES` 也必须与 `app.config.ts` 的 `tabBar.list` 严格一致。

**注意**：`lib/nav.ts` 里的 `PAGE_MAP` 把 `/preferences` 映射到 `pages/profile/index`，
所以共享层 `shared/next-step.ts` 给出的"去填偏好"在小程序里能正确落地。

---

## 6. 常见问题

**点了「立即下单」没反应**
补单的 deeplink 优先 `navigateToMiniProgram`，前提是小程序 AppID 已加进
`app.json` 的 `navigateToMiniProgramAppIdList`（或在后台配置可跳转名单）。没配时会自动降级为
"复制缺口清单 + 弹窗提示去小象超市搜索"，这是预期行为，不是 bug。
目标小程序 AppID 走 `.env` 的 `APP__PLATFORMS__XIAOXIANG__MINIAPP_APP_ID`。

**拍照识别按钮点了提示"服务端还没配置视觉模型"**
后端 `.env` 里没配视觉模型。配置 `APP__LLM__VISION__ENABLED=true` 并确保复用的
`ZHIPU_API_KEY`（GLM-4V）可用即可；也可以先用手动添加入库，功能不受阻。

**编译报 `Cannot find module '@babel/preset-react'`**
`babel-preset-taro` 把它列在 peerDependencies，重跑 `make install-miniapp` 即可。

**编译报 shared/ 里的 TS 语法错误（`Unexpected token`）**
`config/index.ts` 里的 `mini.compile.include` 必须包含 `shared/` 目录，否则 babel 不会编译它。
这个配置已经写好，如果你挪动了目录结构记得同步改。

**真机请求全部失败，开发者工具正常**
99% 是域名没备案 / 没加进 request 合法域名 / 没上 HTTPS。见上面第 3 节。

**登录页没有「微信一键登录」**
`GET /api/auth/providers` 返回的 `wechat` 是 `false`。检查 `WECHAT_APP_ID` /
`WECHAT_APP_SECRET` 有没有进到后端进程（改完 `.env` 要 `make restart`）。

**登录后立刻被踢回登录页**
令牌没存住或已过期。清一下开发者工具的缓存（「清缓存 → 全部清除」）重新登录；
仍然不行就看后端日志里有没有 `微信小程序登录成功`。

**样式尺寸整体偏大或偏小**
`config/index.ts` 的 `designWidth` 必须是 **375**（按 iPhone 逻辑宽度设计，
由 pxtransform 1px → 2rpx）。改成 750 会让所有尺寸缩一半。

---

## 7. 安全检查清单（上线前）

- [ ] `APP__AUTH__DEV_LOGIN=false`
- [ ] `APP__AUTH__COOKIE_SECURE=true`（H5 用；小程序不受影响）
- [ ] `WECHAT_APP_ID` / `WECHAT_APP_SECRET` 只放在 `.env`，不进仓库
- [ ] `config/prod.ts` 的 `API_BASE_URL` 是备案过的 HTTPS 域名
- [ ] 小程序后台已登记 request 合法域名
- [ ] 后端 `APP__APP__DEBUG=false`、`APP__DATABASE__ECHO=false`
