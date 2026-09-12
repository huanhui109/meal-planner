# 内测灰度部署 (V3.0 + 微信小程序)

> 面向「微信小程序 + H5 + 后端」三端同时跑通最低配置, 不需要域名备案。

## 0. 形态

```
ngrok / cloudflared (HTTPS 隧道)
        │
        ▼
   ┌─────────────────────────────────────────────┐
   │  https://<临时子域名>.ngrok.io                 │
   │                                              │
   │   ┌─ /api/  ─────────► uvicorn :8000  (FastAPI) │
   │   │                                          │
   │   └─ /      ────────► frontend/dist (Vite H5) │
   └─────────────────────────────────────────────┘

   微信小程序 (miniapp/dist) 不走 HTTP:
   开发者工具「导入项目」选 miniapp/ 目录 → 预览 / 真机调试
   小程序请求的 API 基址 = MP_API_BASE (构建期注入)
```

唯一对外 URL: 临时 ngrok / cloudflared 域名, **不需要 ICP 备案**:
- 微信小程序后台 → 开发设置 → 服务器域名 → 填这个 URL 的域名部分
- 飞书开放平台 → 重定向 URL 也要带上这个 URL

## 1. 启动顺序

```bash
# 0) 一键构建两端产物 (H5 + 小程序)
make deploy-internal-test MP_API_BASE=https://<隧道域名>/api

# 1) 后端
cd backend
APP__APP__BASE_URL=https://<临时域名> \
APP__AUTH__JWT_SECRET=$(openssl rand -hex 32) \
uvicorn app.main:app --host 0.0.0.0 --port 8000

# 2) 前端 (H5 构建产物, 用 nginx 或 python http server 都能托管)
cd frontend/dist && python3 -m http.server 5173

# 3) 隧道 (暴露后端 8000)
ngrok http 8000

# 4) 微信小程序: 开发者工具导入 miniapp/ → 预览
```

> ⚠️ `miniapp/dist/` 是微信小程序产物 (WXML/WXSS/JS), **不能用浏览器打开**,
> 也不是给 nginx 托管的静态站点。需要浏览器验证时跑 `npm run build:h5`
> (产物在 `miniapp/dist-h5/`)。

## 2. 环境变量模板

`.env.internal-test`:

```ini
# 数据库
APP__DATABASE__URL=mysql+aiomysql://meal:<password>@127.0.0.1:3306/meal_planner

# 隧道 URL (微信后台服务器域名也要填这个)
APP__APP__BASE_URL=https://<你的ngrok子域名>.ngrok.io

# 跨域 (前端域名 + 小程序开发设置里填的 origin)
APP__APP__CORS_ORIGINS=["https://<ngrok子域名>"]

# 鉴权
APP__AUTH__JWT_SECRET=<32字节随机>
APP__AUTH__DEV_LOGIN=true   # 内测期允许昵称直接登录

# 飞书 (临时回调地址)
APP__FEISHU__REDIRECT_URI=https://<ngrok子域名>/api/auth/feishu/callback

# 调度器 (内测开启: 让用户收到推送)
APP__SCHEDULER__ENABLED=true
```

## 3. 验收清单

> 标记说明：✅ = 本机已实测通过（2026-09-12）；未标记 = 需要隧道 / 真机环境才能验。

- [ ] 浏览器访问 `https://<ngrok域名>/` 看到 H5 首页, 200
- [ ] H5 登录成功跳转回首页
- [x] `GET /api/health` 返回 `{status:"ok", version:"0.5.0", database:"ok", ...}` ✅（本机 uvicorn 实测）
- [x] `POST /api/feedback` 提交一条, 状态 201 ✅
- [x] `GET /api/build-info` 返回版本信息 (默认兜底 0.5.0 / 0.5.0 / 不强制) ✅
- [x] `GET /api/subscribe/templates` 返回 3 个模板 ✅
- [ ] 开发者工具导入 `miniapp/`, 编译通过, 真机扫码能跑到主页
      （编译已验证：`npm run build:weapp` 通过 + `miniapp/dist/app.json` 生成；真机待验）
- [ ] 5 个核心路径冒烟 (登录 → 生成菜单 → 标记已做 → 拍照识别 → 退登)

## 4. 已知限制

- ngrok 免费版每次启动换域名, 微信后台 + 飞书回调要重填 (一次性工作)
- 内测期匿名 feedback 是最大写入路径, 上线前接 OAuth 后再开公网
- 订阅消息长期模板 (`persistent: true`) 需要在微信后台单独申请, 当前三个模板都是一次性
- V3.0 scraper 默认 `enabled=false`, 真机「查实价」按钮会显示 "V3.0 即将上线"
- 不含 Certbot / systemd - 那些走生产模式 (见 deploy/README.md)

## 5. 上线 V1.0 时要补的事

1. 买真实域名 + ICP 备案 (3-7 工作日)
2. 用 Certbot 替换 ngrok, 永久 https
3. 微信小程序后台服务器域名改填真实域名
4. 飞书回调地址同步改
5. 关闭 `APP__AUTH__DEV_LOGIN=true` (必须 OAuth)
6. 打开 V3.0 scraper (每个平台在 ScraperRegistry 加一行, 真实接入)
7. 开始报名正式审核 (微信审核工作日 1-3 天)
