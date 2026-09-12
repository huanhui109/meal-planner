# 内测灰度发布 Runbook（30-50 种子用户）

> 阶段：Week 4 收口
> 前置：Week 1-3 全部 done + V3.0 脚手架 + 内测部署 + 法务 review
> 部署细节见 `deploy/internal-test.md`；上线总清单见 `launch-checklist.md`

---

## 0. 一句话目标

用微信**测试号**（免 ICP 备案）拉 30-50 个种子用户跑 7 天，
验证「登录 → 生成菜单 → 标记已做 → 拍照识别 → 退登」5 条核心路径零 P0 闪退，
并把 DAU / 生成成功率 / 识别修正率 / 反馈量拿回来，作为正式上线的决策依据。

---

## 1. 发布前 Gate（全部打勾才发）

### 代码

- [ ] `make ci` 全绿（ruff + pytest + check-tokens + check-logo + test-frontend + build-frontend + check-miniapp）
- [ ] `npm --prefix miniapp run build:weapp` 成功，`miniapp/dist/app.json` 存在
- [ ] 后端 `alembic current` == `alembic heads`（迁移链无分叉）
- [ ] `GET /api/health` 返回 `{status, version, database, scheduler_running, last_event_at, last_menu_generate_at}`

### 功能（30 条审查发现）

- [ ] Week 1 P0：启动主题初始化 / 删 backgroundColor 硬编码 / 隐私条款 / 关于页 / 反馈 / 分享 / deeplink 兜底
- [ ] Week 2 P1：onboarding / 订阅消息 / 客服 / 版本号强制更新 / AbortSignal / 埋点
- [ ] Week 3 P2：邀请裂变 / 菜谱详情 / 历史菜单 / 搜索（Logo SVG 化已延后）
- [ ] Week 4：V3.0 脚手架（`scraping.enabled=false`）/ 内测部署 / 法务 / CI / health

### 合规

- [ ] `docs/legal/privacy.md` / `terms.md` 已放入小程序（关于页可访问）
- [ ] `docs/legal/REVIEW.md` 第五节模板已发给法务
- [ ] 内测期豁免项已登记（`REVIEW.md` 第六节）

### 配置

- [ ] `APP__AUTH__JWT_SECRET` 已换成随机 32 字节
- [ ] `APP__APP__BASE_URL` = 隧道域名
- [ ] `APP__AUTH__DEV_LOGIN=true`（内测期；正式上线必须关）
- [ ] 小程序构建时 `MP_API_BASE=<隧道域名>/api`

---

## 2. 灰度步骤

### Step 1 — 后端 + 隧道（30 min）

```bash
ngrok http 8000                       # 记下 https://<子域名>.ngrok.io
curl https://<子域名>/api/health       # 期望 200
```

### Step 2 — 小程序产物（10 min）

```bash
make deploy-internal-test MP_API_BASE=https://<子域名>.ngrok.io/api
```

微信开发者工具 → 导入项目 → 目录选 **`miniapp/`**（不是 `dist/`）→ 预览 / 真机调试。

### Step 3 — 微信后台配置（15 min，一次性）

1. 开发设置 → 服务器域名 → request 合法域名填 `https://<子域名>.ngrok.io`
2. 开发设置 → socket 合法域名（如用到）
3. 成员管理 → 体验成员 → 拉 30-50 人白名单

### Step 4 — 种子用户招募（1 d）

| 来源 | 目标人数 | 说明 |
|---|---|---|
| 开发 / 产品 / 设计团队 | 5-8 | 自己人，跑最快路径 |
| 亲友团 | 10-15 | 真实做饭场景 |
| 早期 H5 用户 | 15-25 | 有对比参照，反馈最有价值 |

招募文案要点：**说明是内测、数据可能被重置、反馈入口在哪**。

### Step 5 — 发布（Day 0 下午）

体验版发布 → 群里丢小程序码 → 附 3 行上手指引（选人数 → 选菜系 → 生成菜单）。

---

## 3. 观察指标（首 7 天）

### 3.1 必看（每天 10:00 看一次）

| 指标 | 来源 | 健康线 |
|---|---|---|
| DAU | `event` 表 `login` 去重 user_id | ≥ 20（按 40 人白名单 50%） |
| 启动次数 | `event` 表总量 | ≥ DAU × 2 |
| 菜单生成成功率 | `generate_menu` 成功 / 尝试 | ≥ 90% |
| 反馈提交数 | `feedback` 表 | 有量即好（0 条也是信号） |
| P0 闪退 | 群内反馈 + `App.onError` | **0**（>0 立即修） |

### 3.2 查询 SQL

```sql
-- DAU
SELECT DATE(ts) AS d, COUNT(DISTINCT user_id) AS dau
FROM event WHERE event_name = 'login' AND ts >= NOW() - INTERVAL 7 DAY
GROUP BY d ORDER BY d;

-- 事件分布
SELECT event_name, COUNT(*) FROM event
WHERE ts >= NOW() - INTERVAL 7 DAY GROUP BY event_name ORDER BY 2 DESC;

-- 反馈类型分布
SELECT category, COUNT(*) FROM feedback
WHERE created_at >= NOW() - INTERVAL 7 DAY GROUP BY category;

-- 菜单生成成功率（按天）
SELECT DATE(created_at) AS d,
       SUM(status = 'completed') / COUNT(*) AS success_rate
FROM menu_generation_task
WHERE created_at >= NOW() - INTERVAL 7 DAY GROUP BY d;
```

### 3.3 主观信号（群内收集）

- 生成出来的菜「想吃吗」—— 比成功率更重要
- 拍照识别后改了几个食材 —— 识别修正率
- 有没有人第二次打开 —— 留存的第一信号

---

## 4. 分级响应

| 等级 | 判定 | 响应 |
|---|---|---|
| P0 | 闪退 / 登录不了 / 菜单生成不出来 | 当天修 + 发体验版 |
| P1 | 某个页面白屏 / 数据错乱 | 48h 内修 |
| P2 | UI 错位 / 文案不通 | 记 backlog，Week 5 统一修 |
| 反馈 | 任何用户提的 | 3 天内给回复（哪怕只是"收到了"） |

⏱️ **7 天内零 P0 = 通过**；出现 ≥1 个 P0 则修完重新计时 7 天。

---

## 5. 退出标准（决定能否正式上线）

- [ ] 7 天零 P0
- [ ] DAU ≥ 白名单的 50%
- [ ] 菜单生成成功率 ≥ 90%
- [ ] 反馈全部回复完，P1 清零
- [ ] 法务签字到位（`docs/legal/REVIEW.md` 第四节）
- [ ] ICP 备案 + 正式 AppID + 客服号 就位
- [ ] `APP__AUTH__DEV_LOGIN` 关闭

---

## 6. 回滚

| 场景 | 动作 |
|---|---|
| 后端挂了 | 切回上一个 commit，`alembic downgrade -1`，重启 uvicorn |
| 小程序白屏 | 开发者工具回退版本重新发布体验版 |
| 隧道不稳 | cloudflared 兜底（`cloudflared tunnel --url http://localhost:8000`） |
| 数据被玩坏 | `make backup` 的 SQL 恢复；内测期允许清库重来（提前告知用户） |

---

## 7. 时间线

| 天 | 事 |
|---|---|
| D-2 | Gate 检查 + 法务文件定稿 |
| D-1 | 隧道 + 后台域名配置 + 体验版构建 |
| D0 | 发布，拉群，丢小程序码 |
| D1-D6 | 每天 10:00 看指标，群内收反馈 |
| D7 | 出灰度报告 → 决定上 / 修 / 砍 |
