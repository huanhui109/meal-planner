# 飞书扫码登录配置指南

本期只做**网页应用扫码登录**：PC 上展示二维码，手机上扫码后直接唤起飞书 App，
回调换取 `user_access_token` 并拉取用户资料，随后签发本系统自己的 JWT。

飞书 Bot 消息推送（可选）配置方式见第 7 节。

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

## 7. Bot 消息推送（可选）

同一个飞书应用即可承载 Bot：用户先在网页版扫码登录过一次（这样系统里有他的 `open_id`），
之后就能直接在飞书里给应用发消息，也可以接收定时推送。

### 7.1 订阅事件

在「事件与回调」→「事件订阅」中：

1. 请求地址填 `https://meal.example.com/feishu/webhook`（**不带 `/api` 前缀**）。
2. 添加事件 `im.message.receive_v1`（接收消息）。
3. 复制「Verification Token」与「Encrypt Key」（Encrypt Key 需要自己生成一个随机串并保存）。

> 保存请求地址时飞书会先发一次 `url_verification` 握手，后端会同步回 `challenge`，
> 校验通过才会显示「保存成功」。若提示失败，看后端日志里的「签名校验失败 / token 校验失败」。

### 7.2 权限

在「权限管理」中**追加**开通：

| 权限 | 用途 |
|------|------|
| `im:message` | 读取用户发来的消息 |
| `im:message:send_as_bot` | 以应用身份回复与主动推送 |

修改权限后同样需要**发布版本**。

### 7.3 配置 .env

```env
FEISHU_VERIFICATION_TOKEN=在开放平台复制的 Verification Token
FEISHU_ENCRYPT_KEY=在开放平台配置的 Encrypt Key
# 群机器人推送用; 单聊/群聊回复走 open_id, 可以不配
FEISHU_DEFAULT_CHAT_ID=
```

三者留空时签名为「不校验」、`token` 为「不校验」，**本地能跑通但公网必须配上**，
否则任何人都能伪造回调触发写库。

### 7.4 支持指令

| 指令 | 说明 |
|------|------|
| `菜单` / `查看今天菜单` | 返回今天的菜单卡片 |
| `库存` / `查看库存` | 列出冰箱现有食材，临期会提示 |
| `添加库存 鸡蛋 10个 保质期 2026-01-20` | 写入库存（保质期可省略） |
| `完成 今天晚餐` / `完成 周三午餐` | 标记已做，并按菜谱用量扣减库存 |
| `帮助` | 显示指令列表 |

- 回复通过 `im/v1/messages/{message_id}/reply` 发出，要求用户在 1 小时内发过消息；
  定时推送走 `im/v1/messages`（`receive_id_type=open_id`），不需要用户先拉机器人进群。
- 无法识别身份时统一回复「请先在网页版用飞书扫码登录一次」，不会泄露任何账号信息。
- 飞书要求 1 秒内响应，因此接口只做校验与去重，真正的查库与回复放在后台任务里完成。

### 7.5 定时推送（可选）

推送任务默认关闭，打开后才生效：

```env
APP__SCHEDULER__ENABLED=true
APP__SCHEDULER__TIMEZONE=Asia/Shanghai
```

| 任务 | 默认时间 | 内容 |
|------|----------|------|
| `daily_menu_push` | `08:00` | 当天菜单 |
| `evening_check` | `17:30` | 明天要做的菜缺哪些料（只推缺料的人） |
| `expiry_check` | `10:00` | 3 天内到期的食材 |
| `weekly_generation` | `SUN 20:00` | 给配过偏好的用户入队下周生成任务，占用「首次生成」额度 |
| `daily_scrape` | `09:00` | 商品采集（二期功能，当前只记日志） |

把对应值留空或写 `off` 即可停用单个任务。时间写法：`HH:MM`（每天）、`SUN HH:MM`（每周某天）、
或标准 5 段 crontab，例如 `30 17 * * 1-5`。

> 多 worker 部署：打开 `APP__SCHEDULER__ENABLED` 后，各进程会抢一把 MySQL 调度锁（`SELECT GET_LOCK`），只有抢到的那个进程注册定时任务，其余进程自动跳过并打日志，所以不需要手动区分 worker。持锁进程退出时锁随连接释放，重启后自动重新抢占。

## 8. 在网页里自助配置机器人（推荐）

上面的 `.env` 方式是**部署级默认值**。用户也可以完全不动服务器，在应用内自己配一份：

**「我的」（右上角头像）→ 自动化 → 展开「飞书机器人」**

### 8.1 需要准备的四个参数

| 参数 | 去哪儿拿 | 说明 |
|------|----------|------|
| **App ID** | 飞书开放平台 → 你的应用 →「凭证与基础信息」 | 形如 `cli_xxxxxxxx` |
| **App Secret** | 同上 | 只写字段：保存后界面只显示 `cli_******xxxx`，留空提交表示沿用原值 |
| **接收方类型** | 本页选择 | `open_id`（最稳）/ `email`（最省事）/ `chat_id`（推到群） |
| **接收方 ID** | 见下方对应说明 | 机器人只能发给「应用可用范围内」的人 |

**接收方 ID 怎么拿：**

- **email**：直接填你登录飞书用的邮箱，不需要额外查询 —— 推荐先用这个。
- **open_id**：开放平台「API 调试台」用手机号/邮箱查该应用下的 `open_id`，形如 `ou_xxx`。
- **chat_id**：把应用机器人拉进群，群设置里能看到 `oc_xxx`。

### 8.2 应用侧必须做的三步

1. **建应用**：开放平台 → 开发者后台 → 创建「企业自建应用」（个人版飞书账号也能建）。
2. **开权限**：权限管理里勾选 `im:message` 与 `im:message:send_as_bot`。
3. **发布版本**：版本管理与发布 → 创建版本并发布。**没发布时接口会返回权限错误**，
   这是最常见的失败原因。

### 8.3 保存后怎么验证

点「发送测试消息」。成功会提示「测试消息已发送，请到飞书查看」并记下验证时间；
失败会在卡片上直接显示飞书返回的原因（例如 `invalid app_secret`），
不会只给一个「操作失败」。

### 8.4 与部署默认值的关系

解析顺序是 **用户自己的配置 → 部署默认配置（`FEISHU_APP_ID` 等）→ 未配置**。

- 没配飞书的用户**照常使用全部功能**，只是收不到推送，也不会产生「推送失败」记录。
- 用户点「清除个人配置」后自动回落到部署默认值。
- App Secret 以密文存库（密钥由 `APP__AUTH__JWT_SECRET` 派生），因此**换过 JWT 密钥后
  已保存的 App Secret 会解不开**，需要重新填一次。
