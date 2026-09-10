# 本地部署指南（傻瓜版）

从零到浏览器里看到能用的菜谱应用，全程大约 **10～15 分钟**，其中大部分时间在等下载。

---

## 0. 开始之前

你只需要一台 Mac（或 Ubuntu）和一个能联网的网络环境。脚本会自动装好：

| 需要的东西 | 脚本会怎么处理 |
|------------|----------------|
| Homebrew | **不会自动装**，没有的话请先看下面「附录 A」 |
| MySQL 8.0 | 自动 `brew install mysql@8.0`（Ubuntu 用 apt） |
| Python 3.12 | 自动 `brew install python@3.12`（Ubuntu 用 apt） |
| Node.js 18+ | **不会自动装**，建议 `brew install node` |
| 项目依赖 | 自动建 `.venv`、装后端与前端依赖 |

确认一下 Node 在不在：

```bash
node --version    # 需要 v18 或更高，没有就 brew install node
```

---

## 1. 一条命令装完

进入项目目录，执行：

```bash
cd /Users/jason/Documents/project/meal-planner
bash scripts/setup_local.sh
```

脚本会依次打印 `1/7` 到 `7/7` 的进度，中间**可能需要输入你的 Mac 开机密码**（安装软件时）。

它一共做 7 件事：

1. 检查/安装 MySQL 8.0 与 Python 3.12
2. 启动 MySQL，建 `meal_planner`、`meal_planner_test` 两个库和 `meal_planner` 账号
3. 建 `.venv` 并 `pip install -e ".[dev]"`
4. 生成 `.env`（自动填随机 JWT 密钥、本地库地址、打开本地开发登录）
5. `alembic upgrade head` 建 17 张表 + 导入 66 条食材种子
6. `npm install` 装前端依赖
7. 跑一遍后端测试，打印结果

看到下面这段就成功了：

```
==============================================
  初始化完成! 现在这样启动本地服务
==============================================
```

> 脚本可以重复执行，已经做过的步骤会自动跳过。
> 想跳过测试：`WITH_TESTS=0 bash scripts/setup_local.sh`

---

## 2. 启动（开两个终端）

**终端 1 —— 后端：**

```bash
cd /Users/jason/Documents/project/meal-planner
make dev-backend
```

看到 `Uvicorn running on http://0.0.0.0:8000` 就算起来了。
顺手验证一下：浏览器打开 <http://localhost:8000/api/health>，
应该返回 `{"status":"ok", ..., "database":"ok", ...}`。

**终端 2 —— 前端：**

```bash
cd /Users/jason/Documents/project/meal-planner
make dev-frontend
```

然后浏览器打开：**<http://localhost:5173>**

---

## 3. 第一次进去干什么

本地默认没有配置飞书应用，所以登录页会显示 **「本地开发登录」**：

1. 用户名随便填（例如 `小明`），点「本地开发登录」→ 直接进入应用
2. 左侧/底部进入 **偏好** 页，把 5 个表单都填一遍（家庭人数、口味、过敏源、营养目标、预算）
3. 回到 **首页**，点「生成本周菜单」
4. 生成中会显示进度，**可以切走页面**，2.5 秒轮询一次状态
5. 生成完成后进入 **周菜单**：7 天 × 餐次卡片
   - 「换一道」替换单个餐次
   - 「锁定」后该餐次不会被后续重新生成覆盖
   - 「标记已做」会按菜谱用量扣减冰箱库存
6. **采购清单** 页显示「冰箱已有 / 需要买」的差集，可一键复制
7. **库存** 页可以手动入库，临期食材会高亮

> 想验证多用户数据隔离：退出登录，换一个昵称再登录一次。两个人看到的数据完全隔离。

---

## 4. 本地默认开启了「演示模式」

`.env` 里生成的是：

```env
APP__LLM__DEMO=true
```

意思是**不调用任何外部大模型**，直接返回一份固定的 7 天菜单。
除了「模型输出」这一步是假的，后面的落库、计价、营养校验、预算校验、多样性校验、
采购清单、库存扣减**全部真实执行**——所以用来演示和联调完全够用，而且不花一分钱。

### 换成真模型

在 `.env` 里填**任意一个** Key，并把演示模式关掉：

```env
GLM4_API_KEY=你的智谱key
APP__LLM__DEMO=false
```

然后重启后端（终端 1 按 `Ctrl+C`，再 `make dev-backend`）。

支持的三个 Key（按优先级降级）：

| 变量 | 模型 |
|------|------|
| `GLM4_API_KEY` | 智谱 GLM-4（首选） |
| `QWEN_API_KEY` | 通义千问 Qwen-Max |
| `DEEPSEEK_API_KEY` | DeepSeek Chat |

一个都没配也不会 500，而是返回可读错误：*「未配置任何 LLM 提供商…」*。

---

## 5. 接入真实飞书扫码登录

本地默认用的是「本地开发登录」。想测真实飞书扫码，需要把飞书回调穿透到本机：

**第一步：装内网穿透工具并拿到 https 地址**

```bash
brew install ngrok
ngrok http 8000
# 记下形如 https://xxxx-xx-xx.ngrok-free.app 的地址
```

**第二步：在飞书开放平台配置**

1. <https://open.feishu.cn/app> → 创建「企业自建应用」→ 应用形态选 **网页应用**
2. 权限管理里开通：`contact:user.base:readonly`、`authen:user.id:readonly`
3. 安全设置 → 重定向 URL 填：
   ```
   https://xxxx-xx-xx.ngrok-free.app/api/auth/feishu/callback
   ```
   （必须和你 `.env` 里的 `APP__FEISHU__REDIRECT_URI` **逐字符一致**）

**第三步：改 `.env`**

```env
FEISHU_APP_ID=cli_xxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxx
APP__FEISHU__REDIRECT_URI=https://xxxx-xx-xx.ngrok-free.app/api/auth/feishu/callback
```

重启后端，登录页就会多出「使用飞书扫码登录」按钮。
详细说明见 [feishu-setup.md](feishu-setup.md)。

---

## 6. 出问题了怎么办

| 现象 | 原因与解决办法 |
|------|----------------|
| `✗ 未找到 Homebrew` | 先看「附录 A」装 Homebrew |
| `MySQL 未就绪` | 手动跑 `brew services list` 看 mysql@8.0 是否 started；Ubuntu 看 `sudo systemctl status mysql` |
| 迁移报 `Access denied for user 'meal_planner'` | 数据库账号没建好，重跑 `bash scripts/setup_local.sh`；或按第 7 节手动执行建库 SQL |
| 后端启动报 `APP__AUTH__JWT_SECRET 未配置或长度不足` | `.env` 丢了或密钥被改短，删掉 `.env` 重跑初始化脚本 |
| 登录后立刻跳回登录页 | `.env` 里 `APP__AUTH__COOKIE_SECURE` 必须是 `false`（本地是 http） |
| 登录页显示「没有可用的登录方式」 | `.env` 里 `APP__AUTH__DEV_LOGIN=true`，改完重启后端 |
| 生成任务一直 `pending` | 后端日志里应有一行「菜单生成 worker 已启动」；没有就是启动时崩了，看报错 |
| 生成失败，提示未配置 LLM | 填一个 Key 或把 `APP__LLM__DEMO` 设回 `true` |
| 前端 5173 打不开 | 前端终端有没有报错；先确认 `frontend/node_modules` 存在，否则 `cd frontend && npm install` |
| 接口全部 404 / 跨域报错 | 前端必须用 <http://localhost:5173>，它会把 `/api` 代理到 8000 |
| 端口被占用 | `lsof -nP -iTCP:8000 -sTCP:LISTEN` 找到进程杀掉，或改 `make dev-backend` 的端口 |

---

## 7. 脚本失败时的手动分步（兜底）

如果一键脚本卡在某一节，按顺序手动执行这几段即可。

```bash
# ---- 1. 装软件 ----
brew install mysql@8.0 python@3.12

# ---- 2. 启动 MySQL ----
brew services start mysql@8.0
export PATH="$(brew --prefix)/opt/mysql@8.0/bin:$PATH"

# ---- 3. 建库建号 (root 默认无密码) ----
mysql -u root <<'SQL'
CREATE DATABASE IF NOT EXISTS meal_planner DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS meal_planner_test DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'meal_planner'@'127.0.0.1' IDENTIFIED BY 'meal_planner';
GRANT ALL PRIVILEGES ON meal_planner.* TO 'meal_planner'@'127.0.0.1';
GRANT ALL PRIVILEGES ON meal_planner_test.* TO 'meal_planner'@'127.0.0.1';
FLUSH PRIVILEGES;
SQL

# ---- 4. 虚拟环境与依赖 ----
cd /Users/jason/Documents/project/meal-planner
python3.12 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -e ".[dev]"

# ---- 5. 生成 .env ----
cp .env.example .env
# 手工编辑 .env, 至少保证这四项:
#   APP__DATABASE__URL=mysql+aiomysql://meal_planner:meal_planner@127.0.0.1:3306/meal_planner?charset=utf8mb4
#   APP__AUTH__JWT_SECRET=<粘贴 python3 -c "import secrets;print(secrets.token_urlsafe(48))" 的输出>
#   APP__AUTH__COOKIE_SECURE=false
#   APP__AUTH__DEV_LOGIN=true
#   APP__LLM__DEMO=true

# ---- 6. 建表 + 种子数据 ----
cd backend && ../.venv/bin/python -m alembic upgrade head && cd ..
.venv/bin/python scripts/seed_data.py

# ---- 7. 前端依赖 ----
cd frontend && npm install && cd ..

# ---- 8. 测试 ----
export TEST_DATABASE_URL="mysql+aiomysql://meal_planner:meal_planner@127.0.0.1:3306/meal_planner_test?charset=utf8mb4"
cd backend && ../.venv/bin/python -m pytest tests/ -q
```

> 注意：`make dev-backend` / `make migrate` 用的是 `python`，
> 走上面手动流程时请先 `source .venv/bin/activate`，或者直接用 `.venv/bin/python`。

---

## 8. 常用命令速查

| 目的 | 命令 |
|------|------|
| 一键初始化（可重复跑） | `bash scripts/setup_local.sh` |
| 启动后端 | `make dev-backend` |
| 启动前端 | `make dev-frontend` |
| 建表 / 升级表结构 | `make migrate` |
| 重置食材种子数据 | `make seed` |
| 跑后端测试 | `make test` |
| 后端静态检查 | `make lint` |
| 前端代码检查 | `make lint-frontend` |
| 前端类型检查 | `cd frontend && npm run typecheck` |
| 全套 CI（lint + 测试 + 构建） | `make ci` |
| 连上 MySQL 看看 | `$(brew --prefix)/opt/mysql@8.0/bin/mysql -u meal_planner -pmeal_planner meal_planner` |
| 打开交互式 API 文档 | <http://localhost:8000/docs> |

---

## 附录 A：安装 Homebrew

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

装完后按提示把 `brew` 加进 PATH（Apple Silicon 通常是）：

```bash
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
eval "$(/opt/homebrew/bin/brew shellenv)"
```

## 附录 B：彻底重来

```bash
# 停服务
brew services stop mysql@8.0

# 清掉依赖与配置 (数据库本身还在, 想清库见下)
rm -rf .venv .env frontend/node_modules

# 清库重建
$(brew --prefix)/opt/mysql@8.0/bin/mysql -u root -e "DROP DATABASE IF EXISTS meal_planner; DROP DATABASE IF EXISTS meal_planner_test;"

# 重新初始化
bash scripts/setup_local.sh
```

## 相关文档

- [生产上线手册](../deploy/README.md) —— 单机 Linux + nginx + systemd + HTTPS
- [架构设计](architecture.md)
- [飞书扫码登录配置](feishu-setup.md)
