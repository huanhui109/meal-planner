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

### 这台 Mac 上已经装过 MySQL？

不用管，直接往下走。脚本会自己判断：

- 已经有一个**能连上**的 MySQL 8.0（默认就是 `127.0.0.1:3306`）→ 直接复用，什么都不动
- 系统 MySQL 的数据目录是**更高版本**（例如 MySQL 9.x）建的 → 8.0 打不开它（MySQL 不支持降级），
  脚本会**原封不动保留那台实例的数据**，另外给本项目单独起一个实例（**兜底**）：
  端口 `3307`、socket `/tmp/meal-planner-mysql.sock`、数据目录 `$(brew --prefix)/var/mysql80`。
  这样两个 MySQL 可以同时跑，互不影响。

> 项目数据库端口的**唯一真源**是 `.env` 里的 `APP__DATABASE__URL`，默认 `3306`。
> `3307` 只是「系统实例不可用时的专用实例兜底」，不是应用的目标端口。
> 详见 [docs/database-config.md](database-config.md)。

细节见「附录 C」。

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
5. `alembic upgrade head` 建 19 张表 + 导入 66 条食材种子
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
>
> 如果这台机器上的系统 MySQL 因为版本冲突起不来，脚本**不会**去动它，
> 而是自动给本项目单独起一个实例（兜底端口 `3307`），并在生成 `.env` 时写上正确的端口。
> 中途你会看到一段「检测到旧数据目录版本冲突」的说明，那是正常的，不是报错。
>
> **注意**：`.env` 已存在时脚本会把**端口与密码一起**同步（早期版本只改端口、不同步密码，
> 切实例后必然连不上，已修复）。

**装完之后，数据库归谁管：**

| 情况 | 用哪个命令 |
|------|-----------|
| 复用了系统 MySQL（正常情况，端口 `3306`） | `brew services list` / `brew services start mysql@8.0` |
| 用了项目专用实例（版本冲突时的兜底，端口 `3307`） | `make db-status`、`make db-start`、`make db-stop`、`make db-logs` |

`make db-status` 会直接告诉你现在是哪种情况。

---

## 2. 启动服务

### 一条命令全起来（后台运行，不占终端）

```bash
cd /Users/jason/Documents/project/meal-planner
make up
```

它会依次拉起 **数据库 → 后端 → 前端**，然后打印状态和访问地址：

```
✓ 数据库已启动 (127.0.0.1:3306)
✓ 后端已启动: http://127.0.0.1:8000/docs   (健康检查 200)
✓ 前端已启动: http://127.0.0.1:5173

全部就绪
  后端         ● 运行中   http://127.0.0.1:8000  健康检查 200
  前端         ● 运行中   http://127.0.0.1:5173
  数据库       ● 运行中   127.0.0.1:3306
```

常用命令：

```bash
make status      # 看后端/前端/数据库状态
make logs        # 实时看后端日志 (Ctrl+C 退出)
make logs SVC=frontend
make restart     # 重启后端 + 前端
make down        # 停掉后端 + 前端 (数据库不动)
```

### 交互式运维台（不想记命令就用这个）

不想记命令就敲这个，它会显示实时状态并给出菜单：

```bash
make ops
# 等价于  bash scripts/service.sh
```

```
============================================
  AI 每周营养菜谱工具 · 本地运维台
============================================
  后端         ● 运行中   http://127.0.0.1:8000  健康检查 200
  前端         ● 运行中   http://127.0.0.1:5173
  数据库       ● 运行中   127.0.0.1:3307

  1) 启动全部 (数据库 + 后端 + 前端)
  2) 停止全部 (后端 + 前端)
  3) 重启全部
  4) 只操作后端
  5) 只操作前端
  6) 实时日志
  7) 环境自检 (doctor)
  8) 后端健康检查
  9) 数据库迁移 (改了模型/新增迁移文件之后来一下)
  q) 退出
请选择:
```

出问题时先选 `7)`，它会逐项检查 `.venv`、`.env`、后端依赖、前端依赖、
数据库连通性、Alembic 版本与端口占用，并直接给出修复命令。
拉到新代码后如果表结构有变化，选 `9)` 或跑 `make migrate` 升级表结构。

### 也可以直接调脚本（写脚本/CI 用）

```bash
bash scripts/service.sh status                 # 状态
bash scripts/service.sh start                  # 启动全部
bash scripts/service.sh restart backend        # 只重启后端
bash scripts/service.sh stop frontend          # 只停前端
bash scripts/service.sh logs backend           # 跟日志
bash scripts/service.sh health                 # 后端健康检查
bash scripts/service.sh doctor                 # 环境自检
bash scripts/service.sh migrate                # 升级数据库表结构
```

日志落在 `logs/backend.log` 与 `logs/frontend.log`，PID 在 `logs/*.pid`。

> 想让手机在同一 wifi 下访问：`FRONTEND_HOST=0.0.0.0 make restart`

---

## 2.1 前端热调试（可选，占一个终端）

运维台是把服务挂在后台跑的，日常开发够用。想看 uvicorn / vite 的实时输出、
或者要打断点调试，就用前台模式：

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

### 5.1 可选：飞书 Bot（消息指令与定时推送）

同一个应用就能当机器人用，做完上面三步后：

1. 「事件与回调」→ 请求地址填 `https://xxxx-xx-xx.ngrok-free.app/feishu/webhook`
   （**不带 `/api`**），订阅事件 `im.message.receive_v1`。
2. 追加权限：`im:message`、`im:message:send_as_bot`。
3. `.env` 里补上开放平台给的 `FEISHU_VERIFICATION_TOKEN` 与 `FEISHU_ENCRYPT_KEY`，重启后端。
4. 在飞书里给应用发「帮助」应能收到回复（前提是这个飞书账号已在网页版登录过一次）。

想开定时推送再打开开关（本地默认关）：

```env
APP__SCHEDULER__ENABLED=true
APP__SCHEDULER__TIMEZONE=Asia/Shanghai
```

完整指令表、时间写法与多 worker 抢锁说明见 [feishu-setup.md](feishu-setup.md) 第 7 节。

---

## 6. 出问题了怎么办

| 现象 | 原因与解决办法 |
|------|----------------|
| `✗ 未找到 Homebrew` | 先看「附录 A」装 Homebrew |
| `Bootstrap failed: 5: Input/output error` | 这是 launchd 拒绝注册 `brew services` 的服务。**先看「附录 C」**：多数情况下根因是系统 MySQL 的数据目录版本冲突，脚本会自动改用项目专用实例，不用管这个错 |
| `MySQL 未就绪` | 先跑 `make db-status`。若显示「未运行」且用的是专用实例，执行 `make db-start` 并把日志发出来；Ubuntu 看 `sudo systemctl status mysql` |
| `make db-shell` 提示「socket 不存在」 | macOS 会定期清理 `/tmp`，专用实例的 socket 文件可能被删掉。脚本已自动退回 TCP `127.0.0.1:3307`，功能不受影响（后端本来就走 TCP）；想去掉这条提示就 `make db-stop && make db-start` |
| `Can't connect ... through socket '/tmp/mysql.sock'` | 说明连的是系统实例，但本项目用的是专用实例。检查 `.env` 里 `APP__DATABASE__URL` 的端口是不是 `3307`，跑一次 `bash scripts/setup_local.sh` 会自动校正 |
| 日志里出现 `Cannot downgrade from 90500 to 80046` | 见下面「附录 C：机器上已经有别的 MySQL」 |
| 迁移报 `Access denied for user 'meal_planner'` | 数据库账号没建好，重跑 `bash scripts/setup_local.sh`；或按第 7 节手动执行建库 SQL |
| 后端启动报 `APP__AUTH__JWT_SECRET 未配置或长度不足` | `.env` 丢了或密钥被改短，删掉 `.env` 重跑初始化脚本 |
| 登录后立刻跳回登录页 | `.env` 里 `APP__AUTH__COOKIE_SECURE` 必须是 `false`（本地是 http） |
| 登录页显示「没有可用的登录方式」 | `.env` 里 `APP__AUTH__DEV_LOGIN=true`，**改完必须重启后端**（配置只在启动时读一次） |
| 登录页显示「无法获取登录方式」 | 后端没起来或 500：先 `bash scripts/service.sh health` 看真实原因 |
| 改了自己的配置但不生效 | 变量名拼错了。后端启动日志里会有「以下配置项没有对应字段, 已被忽略: APP__XXX」告警，按告警改；变量名规则是 `APP__<配置段>__<字段名>`，字段名看 `backend/app/config.py`（例：`APP__LLM__DEMO`、`APP__AUTH__DEV_LOGIN`） |
| 生成任务一直 `pending` | 后端日志里应有一行「菜单生成 worker 已启动」；没有就是启动时崩了，看报错 |
| 生成失败，提示未配置 LLM | 填一个 Key 或把 `APP__LLM__DEMO` 设回 `true` |
| 前端 5173 打不开 | 前端终端有没有报错；先确认 `frontend/node_modules` 存在，否则 `cd frontend && npm install` |
| 接口全部 404 / 跨域报错 | 前端必须用 <http://localhost:5173>，它会把 `/api` 代理到 8000 |
| 端口被占用 | `lsof -nP -iTCP:8000 -sTCP:LISTEN` 找到进程杀掉，或改 `make dev-backend` 的端口 |
| 拉到新代码后报 `Unknown column` / 少了新字段 | 表结构没跟着代码升级，跑 `make migrate`（或运维台选 `9)`） |
| 测试里提示某个字段不存在 | 同上；测试库也由 `alembic upgrade head` 建表 |
| 改了 `backend/app/models/*` 之后本地库没反应 | 模型改了必须写迁移再 `make migrate`，本地测试库由 `pytest` 自动重建，不用手动处理 |

---

## 7. 脚本失败时的手动分步（兜底）

如果一键脚本卡在某一节，按顺序手动执行这几段即可。

```bash
# ---- 1. 装软件 ----
brew install mysql@8.0 python@3.12

# ---- 2. 启动 MySQL ----
# 先看一眼是哪种情况 (会直接打印端口和状态)
make db-status

# 情况 A: 系统 MySQL 能用
brew services start mysql@8.0
export PATH="$(brew --prefix)/opt/mysql@8.0/bin:$PATH"

# 情况 B: 系统 MySQL 数据目录是更高版本建的 (见附录 C), 用项目专用实例
make db-start
export PATH="$(brew --prefix)/opt/mysql@8.0/bin:$PATH"
alias mp-mysql='/opt/homebrew/opt/mysql@8.0/bin/mysql --socket=/tmp/meal-planner-mysql.sock -u root'
# 下面所有 mysql 命令都改成 mp-mysql

# ---- 3. 建库建号 (root 默认无密码; 情况 B 请把 mysql 换成 mp-mysql) ----
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
#       (情况 B 用专用实例时端口写 3307, 不要写 3306)
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
# 情况 B (专用实例) 把端口改成 3307
cd backend && ../.venv/bin/python -m pytest tests/ -q
```

> 注意：`make dev-backend` / `make migrate` 用的是 `python`，
> 走上面手动流程时请先 `source .venv/bin/activate`，或者直接用 `.venv/bin/python`。

---

## 8. 拉到新代码之后要做什么

代码更新（`git pull`）后，按下面三行走，基本不会漏东西：

```bash
bash scripts/setup_local.sh   # 幂等：补依赖、确认库在跑、升级表结构、跑测试
make restart                  # 重启后端 + 前端
bash scripts/service.sh health
```

只想快速同步表结构（不动依赖）：

```bash
make migrate                  # alembic upgrade head
```

> **V2.0 更新提示**：本次包含两个新迁移（`0003_v2_today_and_brand`、`0004_consumption_identity`）。
> 升级后 `budget` 会多出 `takeout_reference_price`（老数据自动回填 26.0），并新建 `activity_log` 表。
> 另外后端新增依赖 `pillow`（拍照识别前把图片等比缩放到 1280px），`setup_local.sh` 会自动装上；
> 手动升级的话记得跑一次 `make install-backend`。

为什么需要它：本项目**没有**在启动时自动建表，表结构只由 `backend/alembic/versions/`
下的迁移文件管理。模型（`backend/app/models/*.py`）改了却忘了写迁移，就会出现
「代码新、表结构旧」的错位，典型症状是接口报 `Unknown column`。

手动新增一个迁移文件的标准流程：

```bash
# 1. 改模型 backend/app/models/xxx.py
# 2. 生成迁移（会和你当前数据库对比）
make migration MSG="add xxx column"
# 3. 看一眼生成的 backend/alembic/versions/xxxx_*.py 是否正确
# 4. 应用到数据库
make migrate
```

---

## 9. 常用命令速查

| 目的 | 命令 |
|------|------|
| 一键初始化（可重复跑） | `bash scripts/setup_local.sh` |
| 打开交互式运维台 | `make ops` |
| 后台启动全部 | `make up` |
| 停止后端+前端 | `make down` |
| 重启后端+前端 | `make restart` |
| 看服务状态 | `make status` |
| 跟日志 | `make logs` / `make logs SVC=frontend` |
| 环境自检 | `bash scripts/service.sh doctor` |
| 后端健康检查 | `bash scripts/service.sh health` |
| 前台启动后端（调试用） | `make dev-backend` |
| 前台启动前端（调试用） | `make dev-frontend` |
| 建表 / 升级表结构（拉完新代码先跑这个） | `make migrate` |
| 重置食材种子数据 | `make seed` |
| 跑后端测试 | `make test` |
| 后端静态检查 | `make lint` |
| 前端代码检查 | `make lint-frontend` |
| 前端类型检查 | `cd frontend && npm run typecheck` |
| 全套 CI（lint + 测试 + 构建） | `make ci` |
| 看数据库状态（先跑这个） | `make db-status` |
| 连上 MySQL 看看（系统实例） | `$(brew --prefix)/opt/mysql@8.0/bin/mysql -u meal_planner -pmeal_planner meal_planner` |
| 连上 MySQL 看看（专用实例） | `$(brew --prefix)/opt/mysql@8.0/bin/mysql --socket=/tmp/meal-planner-mysql.sock -u meal_planner -pmeal_planner meal_planner` |
| 打开交互式 API 文档 | <http://localhost:8000/docs> |

### 项目专用 MySQL 实例的命令

只有走到「附录 C」那种情况时才会用到（此时项目用的是独立实例，不是 `brew services`）。
**日常用 `make` 就好，下面这些命令是它的底层实现，方便你排查问题：**

| 目的 | 命令 |
|------|------|
| 启动 | `make db-start` |
| 停止 | `make db-stop` |
| 看状态 | `make db-status` |
| 看日志 | `make db-logs` |
| 连进去（root） | `make db-shell` |
| 删除实例数据重来 | `make db-destroy` |
| 换数据目录 / 端口 | `MP_MYSQL_DATADIR=$HOME/mysql80 MP_MYSQL_PORT=3308 make db-start` |
| 直接调底层脚本 | `bash scripts/mysql_local.sh {start\|stop\|status\|logs\|shell\|destroy}` |

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
# 1. 停掉服务与数据库
make down                         # 停后端 + 前端
brew services stop mysql@8.0      # 系统实例
make db-stop                      # 项目专用实例 (报「本来就没在运行」是正常的)

# 2. 清掉依赖与配置
rm -rf .venv .env frontend/node_modules logs/*.pid

# 3. 清库重建 (密码按 .env 里的来)
make db-shell <<'SQL'
DROP DATABASE IF EXISTS meal_planner;
DROP DATABASE IF EXISTS meal_planner_test;
SQL

# 4. 重新初始化
bash scripts/setup_local.sh
```

想连数据目录一起清掉（**只影响本项目实例**，不会碰系统 MySQL 的 `/opt/homebrew/var/mysql`）：

```bash
make db-destroy        # 会先要求输入 yes 确认
bash scripts/setup_local.sh
```

---

## 附录 C：机器上已经有别的 MySQL（数据目录版本冲突）

### 症状

`brew services start mysql@8.0` 报：

```
Bootstrap failed: 5: Input/output error
```

或者数据库日志 `$(brew --prefix)/var/mysql/*.err` 里出现：

```
[ERROR] [InnoDB] Invalid MySQL server downgrade: Cannot downgrade from 90500 to 80046.
mysqld: Can't open file: 'mysql.ibd' (errno: 0 - )
[ERROR] [MY-010334] [Server] Failed to initialize DD Storage Engine
```

### 原因

`/opt/homebrew/var/mysql` 这个数据目录是**更高版本**的 MySQL（例如 9.5）建的。
MySQL 只允许同主版本内升级、**不支持降级**，所以 8.0 打不开它，一启动就退出。
`brew services` 的 plist 里 `KeepAlive = true`，于是它会每 10 秒重启一次、刷满日志，
launchd 反复 bootstrap/bootout，最终就可能抛出那个 `Input/output error`。

**这个错误本身不是「MySQL 坏了」，而是「版本对不上 + 系统里有另一个版本的遗留数据」。**

### 脚本怎么处理

`bash scripts/setup_local.sh` 会**先**读一遍错误日志：

- 发现 `Cannot downgrade from` → 立刻**跳过** `brew services` 这条路（所以不会再看到 `Bootstrap failed: 5`）
- 顺手把一直崩溃重启的那个服务停掉
- 改为给本项目**单独起一个实例**，与系统那份数据完全隔离：

| | 值 |
|---|---|
| 数据目录 | `$(brew --prefix)/var/mysql80` |
| 端口 | `3307`（系统 MySQL 是 3306，两者能同时跑） |
| socket | `/tmp/meal-planner-mysql.sock` |
| 错误日志 | `$(brew --prefix)/var/mysql80/error.log` |
| 开机自启 | `~/Library/LaunchAgents/com.mealplanner.mysql80.plist` |
| 管理命令 | `make db-start` / `db-stop` / `db-status` / `db-logs` / `db-shell` |

系统那份 `/opt/homebrew/var/mysql` **一个字节都不会动**，里面的库（例如 `lobster_monitor`）都还在。

> 如果这台机器的 launchd 连新实例也注册不上，`make db-start` 会自动退化成后台进程启动，
> 并提示你「重启电脑后需要重新执行 `make db-start`」。功能不受影响。

### 想把原来那个 MySQL（含旧数据）也恢复起来

旧数据需要**同版本或更高版本**的 MySQL 才能打开，所以要装回 9.x：

```bash
brew install mysql          # 装 9.x
brew services start mysql   # 它会用 /opt/homebrew/var/mysql
```

9.x 用 3306 端口，本项目的专用实例用 3307，**两个可以同时跑**，互不干扰。
想验证一下这两件事：

```bash
make db-status                                      # 本项目实例 (3307)
mysql -u root -e "SHOW DATABASES"                   # 系统实例 (3306)
```

需要再确认一下：`lobster_monitor` 若是重要数据，建议先单独 `mysqldump` 备份一份再折腾。

## 相关文档

- [生产上线手册](../deploy/README.md) —— 单机 Linux + nginx + systemd + HTTPS
- [架构设计](architecture.md)
- [飞书扫码登录配置](feishu-setup.md)
