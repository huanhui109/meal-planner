# 上线部署手册 (单机 Linux)

目标形态：一台 Linux 服务器跑 `nginx` + `uvicorn` + `MySQL 8.0`，
`nginx` 托管前端 `dist` 并把 `/api` 反代到后端，HTTPS 由 certbot 签发续期，
后端由 systemd 守护。前后端同源，认证走 httpOnly Cookie。

---

## 0. 需要你手动完成的前置动作

这些动作无法由代码替代，必须先在控制台完成：

1. **域名解析**：把 `meal.example.com` 的 A 记录指向服务器公网 IP。
2. **MySQL 8.0**：服务器安装并启动 `mysql-server`，确认 `mysql -u root -p` 可登录。
3. **Python 3.12**：服务器安装 `python3.12` / `python3.12-venv`（`pyproject.toml` 要求 `>=3.11`）。
4. **飞书开放平台**：
   - 创建「网页应用」（不是机器人应用），记录 `App ID` / `App Secret`。
   - 开通权限 `contact:user.base:readonly`（拉取登录用户昵称与头像）。
   - 重定向 URL 必须填 `https://meal.example.com/api/auth/feishu/callback`（必须 HTTPS，且与 `.env` 中
     `APP__FEISHU__REDIRECT_URI` 完全一致，否则飞书会报 `redirect_uri` 不匹配）。
   - 安全设置里把 `https://meal.example.com` 加入网页应用域名白名单。

---

## 1. 首次初始化

```bash
# 1) 建系统账号与目录
sudo useradd --system --create-home --shell /usr/sbin/nologin meal
sudo mkdir -p /srv/meal-planner /var/backups/meal-planner
sudo chown -R meal:meal /srv/meal-planner /var/backups/meal-planner

# 2) 拉代码 (或本地 rsync 上传后跳过)
sudo -u meal git clone <repo-url> /srv/meal-planner

# 3) 建库建账号
mysql -u root -p < /srv/meal-planner/deploy/mysql/01-create-database.sql

# 4) 虚拟环境与依赖
cd /srv/meal-planner
sudo -u meal python3.12 -m venv .venv
sudo -u meal .venv/bin/pip install -U pip
sudo -u meal .venv/bin/pip install -e .

# 5) 配置环境变量
sudo -u meal cp .env.example .env
sudo -u meal chmod 600 .env
sudo -u meal vi .env          # 填 DB 密码 / JWT_SECRET / 飞书 / LLM Key
```

`.env` 里必须确认的字段：

| 变量 | 说明 |
|------|------|
| `APP__DATABASE__URL` | `mysql+aiomysql://meal_planner:<密码>@127.0.0.1:3306/meal_planner?charset=utf8mb4` |
| `APP__AUTH__JWT_SECRET` | ≥32 字符随机串；缺失或过短服务会拒绝启动 |
| `APP__AUTH__COOKIE_SECURE` | 生产必须 `true` |
| `APP__APP__BASE_URL` | `https://meal.example.com` |
| `APP__FEISHU__REDIRECT_URI` | `https://meal.example.com/api/auth/feishu/callback` |
| `GLM4_API_KEY` / `QWEN_API_KEY` / `DEEPSEEK_API_KEY` | 至少一个 |
| `APP__APP__DEBUG` | 生产必须 `false` |
| `APP__DATABASE__ECHO` | 生产必须 `false`（避免日志打印 SQL 与参数） |

生成密钥：

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

## 2. 数据库初始化

```bash
cd /srv/meal-planner/backend
sudo -u meal ../.venv/bin/python -m alembic upgrade head   # 建 17 张表
cd /srv/meal-planner
sudo -u meal .venv/bin/python scripts/seed_data.py          # 导入 66 条食材与参考价
```

`alembic upgrade head` 是唯一的建表方式，应用不会自动 `create_all`。

## 3. 前端构建

```bash
cd /srv/meal-planner/frontend
sudo -u meal npm ci
sudo -u meal npm run build     # 产物在 frontend/dist, nginx 直接托管
```

## 4. nginx

```bash
sudo cp deploy/nginx/meal_planner_proxy.conf /etc/nginx/snippets/
sudo cp deploy/nginx/meal-planner.conf /etc/nginx/sites-available/
sudo ln -s /etc/nginx/sites-available/meal-planner.conf /etc/nginx/sites-enabled/
sudo sed -i 's/meal.example.com/真实域名/g' /etc/nginx/sites-available/meal-planner.conf
sudo nginx -t && sudo systemctl reload nginx
```

## 5. HTTPS

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d meal.example.com --redirect
sudo systemctl status certbot.timer   # 到期前自动续期
```

## 6. systemd

```bash
sudo cp deploy/systemd/meal-planner-api.service /etc/systemd/system/
sudo cp deploy/systemd/meal-planner-backup.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now meal-planner-api
sudo systemctl enable --now meal-planner-backup.timer
sudo systemctl status meal-planner-api
```

## 7. 验收检查

```bash
curl -sS https://meal.example.com/api/health
# => {"status":"ok","app":"AI 每周营养菜谱工具","database":"ok","version":"0.2.0"}
```

浏览器打开 `https://meal.example.com` → 应跳转登录页 → 点「飞书扫码登录」→ PC 显示二维码，
手机扫码后回到周视图。

---

## 日常运维

```bash
# 发布新版本
./deploy/deploy.sh meal@服务器IP /srv/meal-planner

# 日志
sudo journalctl -u meal-planner-api -f --since "10 min ago"

# 手动备份 / 验证备份
sudo systemctl start meal-planner-backup.service
ls -lh /var/backups/meal-planner/

# 迁移到新版本
cd /srv/meal-planner/backend && sudo -u meal ../.venv/bin/python -m alembic upgrade head
```

**备份策略**：`meal-planner-backup.timer` 每天 03:30 执行 `mysqldump`（`--single-transaction`），
写入 `/var/backups/meal-planner`，自动清理 14 天前的文件。
如需异地留存，请自行加 `rclone`/`scp` 到对象存储。

## 排障

| 现象 | 排查方向 |
|------|----------|
| 服务启动即退出 | `journalctl -u meal-planner-api`；多为 `JWT_SECRET` 缺失或 DB 连不上 |
| 登录后跳回登录页 | Cookie 未写入：确认 HTTPS、`COOKIE_SECURE=true`、域名与 `COOKIE_DOMAIN` 一致 |
| 飞书报 redirect_uri 不匹配 | 开放平台配置的 URL 与 `APP__FEISHU__REDIRECT_URI` 必须逐字符一致（含 `https://`） |
| 生成一直 pending | 检查 worker 是否启动（日志有「菜单生成 worker 已启动」）、LLM Key 是否可用 |
| `/api/health` 返回 503 | `database` 字段为 `error`，MySQL 挂了或账号密码错 |
| 429 生成次数已用尽 | 每用户每日 3 次配额，按 `menu_generation_task` 当日计数 |
