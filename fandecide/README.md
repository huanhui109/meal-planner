# 饭决 · 极简决策屏（fandecide-h5）

围绕「今天吃啥」一个核心命题的**全栈极简应用**：一屏、一个按钮、一个答案。

## 定位

- 不背周菜单 / 库存 / 外卖等模块，**只解决「这一顿吃什么」的决策难题**。
- UI 走「少文字 + 大留白 + 图标化」：默认只露 `餐次 + 菜名 + 一句话理由`，
  耗时/热量/菜系用图标 chip 呈现，做法藏在底部 sheet。
- 后端**零新增**：直接复用 meal-planner 的 `/api/decide` 决策引擎（≤2s、纯规则理由、
  近 7 天去重、离线同构），决策记录持久化在 `decision_log` 表。

## 架构

```
fandecide/ (Vite + React + TS, 仅前端)
   └─ /api/*  ──dev proxy──>  meal-planner :8000 (FastAPI + MySQL)
                                  └─ /api/decide 写入 decision_log
```

本地用 `vite preview` 的 `server.proxy` 把 `/api` 转发到 `:8000`，
因此**完全不碰 CORS**，且后端 Set-Cookie 自然落在 127.0.0.1 上。

## 运行

```bash
npm install
npm run dev        # :5188，浏览器开 http://127.0.0.1:5188
# 上游 meal-planner 后端要在 :8000 跑着，且 APP__AUTH__DEV_LOGIN=true 才能本地免密登录
```

生产：用 nginx 把 `/api` 反代到 meal-planner 即可，前端路径不变。

## 数据流

1. 首屏 `GET /api/auth/me` 试探会话 → 没有就弹昵称登录门（`POST /api/auth/dev-login`）。
2. 进入后 `GET /api/decide/last` 秒开上一次结果；`GET /api/decide/recent` 拉一条轻历史。
3. 按「饭决」→ `POST /api/decide`（带本次已拒绝的菜名去重）→ 结果卡。
4. 「换一个」再次调用并带 `exclude`；「就这个」调 `POST /api/decide/{id}/feedback`。

## 文件

```
src/
  api/        client.ts（统一信封+错误码）· auth.ts · decide.ts
  components/ LoginGate · DecideScreen · ResultCard · StepsSheet · Icon（内联 SVG）
  styles.css  暖色克制排版，一屏垂直居中
```
