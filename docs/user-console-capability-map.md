# 饭决 · 用户操作台 —— 能力对照表

> 本页说明「用户操作台」这一工作台页面与后端 API 的一一对应关系。
> 操作台页面地址：https://www.workbuddy.cn/space/d/j67kMNQuKeHLMtoORmEzUP
> 源文件：`output/fandecide-user-console.html`（单文件，全内联，零外部依赖）

## 一、定位

| 页面 | 面向 | 是否真实调用后端 |
| --- | --- | --- |
| 项目管理工作台（`fandecide-workspace.html`） | 运维 / 管理 | 否，纯参数配置与文档索引 |
| **用户操作台**（`fandecide-user-console.html`） | **终端用户** | **是，每一项都在页面上真实发起 HTTP 请求** |

操作台把后端 62 个 OpenAPI 路由中的 **61 个**做成可交互卡片（唯一未纳入的是 `POST /feishu/webhook`——飞书服务器回调，由飞书侧发起，不是用户可调用的 API）。

## 二、目录结构

```
饭决 FAN·DECIDE · 项目资料库/
├── 项目管理工作台（在线 page）
├── 15 篇核心文档
└── 用户操作台/                      ← 本次新增
    ├── 饭决 · 用户操作台（实时调用后端）   ← 在线 page
    └── 能力对照表（本文档）
```

## 三、六个工作台分区与后端能力映射

### ① 连接与身份（8 项）

| 操作台能力 | 方法 | 后端接口 | 写操作 |
| --- | --- | --- | --- |
| 健康检查 | GET | `/api/health` | 否 |
| 可用登录方式 | GET | `/api/auth/providers` | 否 |
| 登录（本地开发） | POST | `/api/auth/dev-login` | 否 |
| 我的信息 | GET | `/api/auth/me` | 否 |
| 刷新令牌 | POST | `/api/auth/refresh` | 否 |
| 退出登录 | POST | `/api/auth/logout` | 是 |
| 微信小程序登录 | POST | `/api/auth/wechat/mini-login` | 否 |
| 飞书授权地址 | GET | `/api/auth/feishu/login-url` | 否 |

### ② 今天吃啥（7 项）

| 操作台能力 | 方法 | 后端接口 | 写操作 |
| --- | --- | --- | --- |
| 饭决：决定这一餐 | POST | `/api/decide` | 否 |
| 上一次决策 | GET | `/api/decide/last` | 否 |
| 决策档案 | GET | `/api/decide/profile` | 否 |
| 最近决策历史 | GET | `/api/decide/recent` | 否 |
| 对结果表态 | POST | `/api/decide/{decision_id}/feedback` | 否 |
| 今日聚合 | GET | `/api/today` | 否 |
| 记住外卖参考价 | POST | `/api/today/takeout-price` | 是 |

### ③ 周菜单（14 项）

| 操作台能力 | 方法 | 后端接口 | 写操作 |
| --- | --- | --- | --- |
| 生成一周菜单 | POST | `/api/menus/generate` | 是 |
| 查询生成进度 | GET | `/api/menus/generation-tasks/{task_id}` | 否 |
| 当前周菜单 | GET | `/api/menus/current` | 否 |
| 历史菜单 | GET | `/api/menus/history` | 否 |
| 菜单详情 | GET | `/api/menus/{menu_id}` | 否 |
| 换一道 | PUT | `/api/menus/{menu_id}/items/{item_id}/replace` | 是 |
| 锁定餐次 | PUT | `/api/menus/{menu_id}/items/{item_id}/lock` | 是 |
| 解锁餐次 | PUT | `/api/menus/{menu_id}/items/{item_id}/unlock` | 是 |
| 标记已做 | PUT | `/api/menus/{menu_id}/items/{item_id}/cooked` | 是 |
| 撤销已做 | DELETE | `/api/menus/{menu_id}/items/{item_id}/cooked` | 是 |
| 采购清单 | GET | `/api/menus/{menu_id}/shopping-list` | 否 |
| 补单建议 | GET | `/api/menus/{menu_id}/order-suggestion` | 否 |
| 确认菜单 | POST | `/api/menus/{menu_id}/confirm` | 是 |
| 按冰箱重排 | POST | `/api/menus/fridge-rebuild` | 是 |

### ④ 冰箱库存（5 项）

| 操作台能力 | 方法 | 后端接口 | 写操作 |
| --- | --- | --- | --- |
| 库存列表 | GET | `/api/inventory` | 否 |
| 新增库存 | POST | `/api/inventory` | 是 |
| 删除库存 | DELETE | `/api/inventory/{item_id}` | 是 |
| 临期食材 | GET | `/api/inventory/expiring` | 否 |
| 拍照识别入库 | POST | `/api/inventory/recognize` | 是 |

### ⑤ 我的偏好（11 项）

| 操作台能力 | 方法 | 后端接口 | 写操作 |
| --- | --- | --- | --- |
| 档案总览 | GET | `/api/preferences/summary` | 否 |
| 家庭与做饭能力 | GET | `/api/preferences/household` | 否 |
| 更新家庭信息 | PUT | `/api/preferences/household` | 是 |
| 饮食偏好 | GET | `/api/preferences/diet` | 否 |
| 更新饮食偏好 | PUT | `/api/preferences/diet` | 是 |
| 过敏与忌口 | GET | `/api/preferences/allergy` | 否 |
| 更新过敏源 | PUT | `/api/preferences/allergy` | 是 |
| 健康目标 | GET | `/api/preferences/health-goal` | 否 |
| 更新健康目标 | PUT | `/api/preferences/health-goal` | 是 |
| 预算设定 | GET | `/api/preferences/budget` | 否 |
| 更新预算 | PUT | `/api/preferences/budget` | 是 |

### ⑥ 更多能力（16 项）

| 操作台能力 | 方法 | 后端接口 | 写操作 |
| --- | --- | --- | --- |
| 机器人状态 | GET | `/api/automation/status` | 否 |
| 我的飞书配置 | GET | `/api/automation/feishu` | 否 |
| 保存我的飞书配置 | PUT | `/api/automation/feishu` | 是 |
| 清除我的飞书配置 | DELETE | `/api/automation/feishu` | 是 |
| 发一条测试消息 | POST | `/api/automation/feishu/test` | 是 |
| 提交反馈 | POST | `/api/feedback` | 是 |
| 我的反馈 | GET | `/api/feedback/mine` | 否 |
| 我的邀请码 | GET | `/api/invite/code` | 否 |
| 核销邀请码 | POST | `/api/invite/redeem` | 是 |
| 订阅消息模板 | GET | `/api/subscribe/templates` | 否 |
| 记录订阅授权 | POST | `/api/subscribe/grant` | 是 |
| 订阅授权状态 | GET | `/api/subscribe/status/{template_id}` | 否 |
| 商品列表 | GET | `/api/products` | 否 |
| 按食材搜商品 | GET | `/api/products/search` | 否 |
| 上报埋点 | POST | `/api/events` | 是 |
| 构建信息 | GET | `/api/build-info` | 否 |

## 四、统一的状态处理

操作台对四类状态做了统一处理，所有 61 张卡片走同一套渲染逻辑：

| 状态 | 表现 |
| --- | --- | --- |
| 加载中 | 按钮变 spinner + 「请求中…」，结果区显示骨架屏；20 秒超时自动中断 |
| 空数据 | 结果区给出「接口成功但没有数据」的空态说明，而不是空白 |
| 校验失败 | 未通过校验的字段行标红并给出具体原因，不发请求 |
| 接口异常 | 区分 HTTP 层（4xx/5xx/网络失败）与业务层（code≠0），并展开原始 JSON 供排查；429/503 归为「服务未就绪/限流」 |

写操作（打标 `write:true`，共 25 项）在点击「调用」后会先弹二次确认；删除类还会标红。

## 五、使用前提

1. 后端已在 `http://127.0.0.1:8000` 启动（`make restart` 或 `uvicorn app.main:app`）。
2. `.env` 中 `APP__APP__CORS_ORIGINS` 已包含 `https://www.workbuddy.cn`，否则跨域请求会被浏览器拦截。
3. `APP__AUTH__DEV_LOGIN=true` 时可在页面直接凭昵称登录换取 Bearer token。
4. 页面挂在 https 域下，调用 `http://127.0.0.1:8000` 属「本机可信来源」，浏览器默认放行；若换成局域网 IP 的 http 地址会被混合内容拦截。

## 六、本地存储

连接配置、token、已展开的卡片等保存在浏览器 localStorage，key 前缀 `wb_fandecide_console_v1`。
清理浏览器数据会丢失，但页面内可随时重新连接与登录。