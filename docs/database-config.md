# 数据库配置治理（MySQL 8.0 / 3306）

> 目标：全项目只有**一处**数据库配置真源，端口统一 3306，账号密码只存在于 `.env`（不进版本库），
> 应用启动、迁移、运维脚本、CI 全部从同一处读取。

## 1. 配置优先级

```
环境变量 (APP__<段>__<字段>)  >  .env  >  config/default.yaml  >  代码默认值
```

- 环境变量与 `.env` 使用**双下划线**分层：`APP__DATABASE__URL`、`APP__DATABASE__ECHO`
- `config/default.yaml` 只放**非敏感**的默认值，**不得**写账号密码
- `.env` 在 `.gitignore` 中，不会被提交

## 2. 唯一必填项

```bash
APP__DATABASE__URL=mysql+aiomysql://<用户>:<密码>@127.0.0.1:3306/meal_planner?charset=utf8mb4
```

派生项（不需要单独配）：`scheduler.db_url` 在 `Settings.apply_derived_defaults()` 里自动继承
`database.url`，改一处即可。

## 3. 启动期校验（新增）

`backend/app/config.py` 提供三个入口，任何一处不合法都会**快速失败**，而不是等第一次查询才炸：

| 入口 | 行为 |
|---|---|
| `Settings.validate_for_runtime()` | 拒绝占位密码（`change-me` / `changeme` / `your_password` / `<password>`）、拒绝非 MySQL（如 SQLite）、端口非 3306 时告警 |
| `Settings.describe_database()` | 打印**脱敏**连接串（密码打码），用于日志，避免凭据泄漏 |
| `looks_like_placeholder_url()` | 供脚本与 CI 复用同一套占位串判定 |

接入点：

- `backend/app/main.py` —— lifespan 启动时调用 `validate_for_runtime()`，不合法直接拒绝启动
- `backend/alembic/env.py` —— 迁移前调用，防止拿着占位密码建表
- `deploy/mysql/create-database.sh` —— 建库建号前校验密码不是占位值、长度 ≥ 8

## 4. 文件清单与改动要点

| 文件 | 改动要点 |
|---|---|
| `backend/app/config.py` | 新增 `looks_like_placeholder_url()` / `describe_database()` / `validate_for_runtime()`；`scheduler.db_url` 派生；默认串改为 3306 占位 |
| `backend/app/main.py` | lifespan 启动校验数据库配置 |
| `backend/alembic/env.py` | 迁移入口复用应用配置并校验 |
| `config/default.yaml` | 清除明文凭据，改为占位串；统一 3306 |
| `.env.example` | 数据库段重写：占位串 + 3306 + 说明；补充 `TEST_DATABASE_URL` 说明 |
| `.gitignore` | 忽略 `.env` / `.env.*` / `config/user.yaml` / `deploy/*.env`，**保留** `.env.example` 与 `*.example` |
| `scripts/setup_local.sh` | 默认端口 3306；探测顺序改为「3306 系统实例 → 专用实例」；`.env` 已存在时**同步改端口+密码**（原缺陷：只改端口不同步密码，导致切实例后连不上） |
| `scripts/mysql_local.sh` | 定位改写为「3306 不可用时的专用实例兜底」，不再被误当作应用端口 |
| `deploy/mysql/01-create-database.sql` | 改为占位符 `${MP_DB_USER}` / `${MP_DB_PASSWORD}`，不再出现明文密码 |
| `deploy/mysql/create-database.sh` | 新增：渲染占位符并执行，密码走 stdin/环境变量，占位与弱密码拒绝执行 |
| `deploy/README.md` / `docs/deployment.md` | 建库、环境变量说明改为占位符写法 |
| `deploy/systemd/*.service` | 描述更新为「饭决 FAN·DECIDE」 |
| `.github/workflows/ci.yml` | 服务容器统一 3306；新增「真实 MySQL 上跑 `alembic upgrade head`」步骤防迁移链回归 |
| `backend/alembic/versions/0008/0009/0010/0012/0013/0014` | 修复 MySQL 1553 回滚缺陷（见第 6 节） |
| `backend/tests/conftest.py` | 清库时先 `SET FOREIGN_KEY_CHECKS=0`，修复 MySQL 3730（见第 6 节） |
| `backend/app/models/product_price.py` | `source` 列补 `String(50)`，修复 MySQL 建表失败（见第 6 节） |

## 5. 验证数据库可用的四种方法

**① 应用自检（最快）**

```bash
cd backend && PYTHONPATH=. ../.venv/bin/python -m uvicorn app.main:app --port 8131
curl -s http://127.0.0.1:8131/api/health
# {"status":"ok","app":"饭决 FAN·DECIDE","database":"ok", ...}
```

`database` 字段为 `ok` 即表示连接池已真实握手成功；配置不合法时服务会**拒绝启动**并打印脱敏原因。

**② 配置读取校验（不启服务）**

```bash
cd backend && PYTHONPATH=. ../.venv/bin/python -c "
from app.config import get_settings
s = get_settings(); s.validate_for_runtime(); print(s.describe_database())
"
```

**③ 命令行直连**

```bash
/opt/homebrew/bin/mysql -h 127.0.0.1 -P 3306 --protocol=tcp -u meal_planner -p -e "SELECT VERSION(), DATABASE();"
```

**④ 集成测试（真实 MySQL）**

```bash
export TEST_DATABASE_URL="mysql+aiomysql://<用户>:<密码>@127.0.0.1:3306/meal_planner_test?charset=utf8mb4"
cd backend && PYTHONPATH=. ../.venv/bin/python -m pytest tests/ -q
```

未设置 `TEST_DATABASE_URL` 时集成测试自动跳过；设置后必须全部通过（当前 **411 passed**）。

## 6. 本次顺带修掉的三个「SQLite 能过、MySQL 必炸」缺陷

1. **迁移无法回滚（MySQL 1553）**：`downgrade()` 里先 `drop_index` 再 `drop_table`，而索引被外键依赖时
   MySQL 禁止单独删除。涉及 0008 / 0009 / 0010 / 0012 / 0013 / 0014，**回滚链路此前一直是坏的**。
   修法：只 `drop_table`（MySQL 会连带删索引与外键），并加注释说明原因。
2. **测试夹具清库失败（MySQL 3730）**：`metadata.drop_all()` 逐表 DROP 撞外键依赖。
   修法：`SET FOREIGN_KEY_CHECKS=0` → drop → create → 恢复。
3. **模型与迁移不一致**：`product_price.source` 模型漏了 `String(50)`（迁移里写了），
   MySQL 下 VARCHAR 无长度直接建表失败。

## 7. 存量菜谱决策字段回填

迁移 0014 只加列不回灌数据，存量菜谱的决策字段原本全空（「同品类打散」「连续两餐不重样」
两条硬规则形同失效）。回填脚本：

```bash
make backfill-decide-fields ARGS="--dry-run --preview 30"   # 先看效果
make backfill-decide-fields                                 # 正式回填
```

`scripts/backfill_recipe_decision_fields.py` 是纯规则推断（不调 LLM）：
主料按「菜名点名 + 大类权重 + 主料归一化」打分，判荤时剔除配料级肉末与乳制品，
极简做法按标点拆成 3-5 步（每步 ≤20 字）。口径与 `data/local_dish_pool.json` 保持一致，
这样服务端菜谱与离线候选池的决策表现一致。**只填空、可重跑**（第二条命令再跑一次应扫描 0 道）。

## 8. 已知遗留

- 存量库里混进 5 条饮品（Mojito莫吉托、冬瓜茶、柠檬水、酸梅汤、酸梅汤（半成品加工）），
  回填脚本会告警但不自动删。建议后续加 `is_drink` 标记并在决策候选里排除。
