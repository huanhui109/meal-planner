# 飞书扫码登录配置指南

本期只做**网页应用扫码登录**：PC 上展示二维码，手机上扫码后直接唤起飞书 App，
回调换取 `user_access_token` 并拉取用户资料，随后签发本系统自己的 JWT。

飞书 Bot 消息推送属于二期，配置方式见文末。

## 1. 创建应用

1. 登录 [飞书开放平台](https://open.feishu.cn/app) → 创建「**企业自建应用**」→ 选择「**网页应用**」形态。
2. 在「凭证与基础信息」记录 `App ID` 与 `App Secret`。

> 个人版飞书账号同样可以创建自建应用，但可见范围仅限自己，用于验证流程没有问题。

## 2. 权限配置

在「权限管理」中开通：

| 权限 | 用途 |
|------|------|
| `contact:user.base:readonly` | 读取登录用户昵称与头像 |
| `authen:user.id:readonly` | 通过授权码换取用户身份（扫码登录必需） |

开通后需要**发布版本**并等待生效，否则回调会返回权限错误。

## 3. 安全设置（回调地址）

在「安全设置」→「重定向 URL」中填写：

```
https://meal.example.com/api/auth/feishu/callback
```

要求：

- 必须是 **HTTPS**，且与 `.env` 里的 `APP__FEISHU__REDIRECT_URI` **逐字符一致**（含结尾斜杠的有无）。
- 本地开发用内网穿透：`https://xxx.ngrok.io/api/auth/feishu/callback`。
- 同时把站点域名加入「网页应用域名」白名单。

## 4. 配置 .env

```env
FEISHU_APP_ID=cli_xxxxxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxx
APP__FEISHU__REDIRECT_URI=https://meal.example.com/api/auth/feishu/callback
APP__FEISHU__LOGIN_SUCCESS_REDIRECT=/
```

- `LOGIN_SUCCESS_REDIRECT` 是登录成功后前端应回落的路径（默认 `/`）。前端发起登录时会带上
  `?redirect=`，优先级高于该默认值。

## 5. 登录流程

```
前端点击「飞书扫码登录」
        │ GET /api/auth/feishu/login-url?redirect=/menus
        ▼
后端签发 10 分钟有效期的 state, 返回飞书授权页 URL
        │ 浏览器跳转 open.feishu.cn/.../authen/v1/index
        ▼
用户扫码授权
        │ 飞书回调 /api/auth/feishu/callback?code=...&state=...
        ▼
后端: code -> app_access_token -> user_access_token -> 用户资料
        │ upsert user (open_id 唯一) + 写 last_login_at
        ▼
签发自有 JWT, 写入 httpOnly Cookie, 307 跳回前端
```

Token 规格：access 2 小时 / refresh 30 天，Cookie 为
`httpOnly + Secure + SameSite=Lax`。前后端同源部署，因此不需要额外的 CSRF token。

## 6. 验证

```bash
# 未登录访问受保护接口应返回 401
curl -i https://meal.example.com/api/auth/me

# 登录后应返回当前用户
curl -i -b cookies.txt https://meal.example.com/api/auth/me
```

## 二期: Bot 消息推送（当前未启用）

> 现状：`app/bot/webhook_routes.py` 的 `verify_webhook` 尚未被调用，handler 返回值也无人消费，
> `SchedulerManager` 未挂进 lifespan。上线前请不要依赖 Bot 功能。

启用时需要：

1. 订阅 `im.message.receive_v1` 事件，请求地址填 `https://meal.example.com/feishu/webhook`。
2. 配置 `FEISHU_VERIFICATION_TOKEN` / `FEISHU_ENCRYPT_KEY` / `FEISHU_DEFAULT_CHAT_ID`。
3. 开通 `im:message`、`im:message:send_as_bot` 权限。
