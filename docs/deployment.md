# 部署指南

生产部署（单机 Linux + MySQL + nginx + systemd + HTTPS）请直接看
[`deploy/README.md`](../deploy/README.md)，那里有完整的分步命令、前置人工动作与排障表。

本页只讲本地开发。

## 本地开发

> 一键脚本与排障表请看 **[本地部署指南（傻瓜版）](local-setup.md)**。
> 本页只保留要点速查。

### 1. 环境要求

- Python **3.11+**（生产 3.12）
- Node.js 18+
- MySQL 8.0（本地库即可，集成测试也用它）

最快路径：

```bash
bash scripts/setup_local.sh   # 等价于 make setup-local
```

### 2. 准备数据库

```bash
mysql -u root -p -e "
CREATE DATABASE meal_planner DEFAULT CHARACTER SET utf8mb4;
CREATE DATABASE meal_planner_test DEFAULT CHARACTER SET utf8mb4;
CREATE USER 'meal_planner'@'127.0.0.1' IDENTIFIED BY 'change-me';
GRANT ALL ON meal_planner.* TO 'meal_planner'@'127.0.0.1';
GRANT ALL ON meal_planner_test.* TO 'meal_planner'@'127.0.0.1';"
```

### 3. 安装依赖

```bash
make setup          # 后端 pip install -e ".[dev]" + 前端 npm install
```

### 4. 配置环境变量

```bash
cp .env.example .env
```

至少填写：
- `APP__DATABASE__URL`（指向本地 `meal_planner` 库）
- `APP__AUTH__JWT_SECRET`（≥32 字符，否则应用拒绝启动）
- 飞书 `FEISHU_APP_ID` / `FEISHU_APP_SECRET` / `APP__FEISHU__REDIRECT_URI`
- 一个 LLM Key（`GLM4_API_KEY` / `QWEN_API_KEY` / `DEEPSEEK_API_KEY`）

本地 `APP__AUTH__COOKIE_SECURE` 可设为 `false`（否则 http 下 Cookie 不会写入）。

### 5. 初始化数据库

```bash
make migrate        # alembic upgrade head
make seed           # 导入 66 条食材与参考价
```

### 6. 启动

```bash
make dev-backend    # http://localhost:8000/docs
make dev-frontend   # http://localhost:5173 (已代理 /api)
```

### 7. 本地调试飞书登录

飞书要求 HTTPS 回调，本地可用内网穿透把 `https://xxx.ngrok.io` 映射到 8000，
再把开放平台的重定向 URL 改成 `https://xxx.ngrok.io/api/auth/feishu/callback`。

### 8. 运行测试

```bash
export TEST_DATABASE_URL="mysql+aiomysql://meal_planner:change-me@127.0.0.1:3306/meal_planner_test?charset=utf8mb4"
make test           # 未设置 TEST_DATABASE_URL 时自动跳过集成测试
make ci             # ruff + pytest + 前端构建
```

> 库名必须以 `_test` 结尾，conftest 会拒绝清空非测试库。

## 常见问题

**Q: 服务启动报 “APP__AUTH__JWT_SECRET 未配置或长度不足”**
A: 生成一个 ≥32 字符的随机串填进 `.env`。

**Q: 生成的菜没有成本**
A: 执行 `make seed` 或补充 `ingredient.reference_price`；接口会在 `totals.unpriced_items` 里提示缺价项数。

**Q: 登录成功但立刻跳回登录页**
A: 本地 http 环境下把 `APP__AUTH__COOKIE_SECURE` 设为 `false`。

**Q: 生成任务一直 pending**
A: worker 随应用启动，确认日志里有「菜单生成 worker 已启动」，并检查 LLM Key 是否可用。
