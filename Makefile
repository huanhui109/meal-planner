# 有 .venv 就用它, 否则退回系统 python3 (这样不激活虚拟环境也能直接用 make)
ifeq ($(wildcard .venv/bin/python),)
  PYTHON := python3
else
  PYTHON := $(CURDIR)/.venv/bin/python
endif

.PHONY: help ops up down restart status logs dev dev-backend dev-frontend install-backend install-frontend install-miniapp test test-cov test-frontend lint lint-frontend gen-tokens gen-logo ci build-frontend build-miniapp migrate migration seed backup tunnel playwright-install setup setup-local db-start db-stop db-status db-logs db-shell db-destroy

help:
	@echo "make setup-local      - 一键装好本地环境 (MySQL/Python/依赖/迁移/种子/测试)"
	@echo "make setup            - 仅安装后端+前端依赖 (环境已就绪时用)"
	@echo "make migrate          - 执行数据库迁移 (alembic upgrade head)"
	@echo "make seed             - 导入食材与参考价种子数据"
	@echo "make ops              - 打开交互式运维台 (启动/停止/重启/日志/自检)"
	@echo "make up               - 后台启动 数据库 + 后端 + 前端"
	@echo "make down             - 停止 后端 + 前端"
	@echo "make restart          - 重启 后端 + 前端"
	@echo "make status           - 查看后端/前端/数据库状态"
	@echo "make logs SVC=backend - 实时看日志 (SVC=backend|frontend|db)"
	@echo "make dev-backend      - 前台启动后端 (8000, 调试用)"
	@echo "make dev-frontend     - 前台启动前端 (5173, 调试用)"
	@echo "make test             - 运行后端测试"
	@echo "make lint             - ruff 静态检查"
	@echo "make lint-frontend    - eslint 检查前端代码"
	@echo "make test-frontend    - vitest 跑共享层纯函数测试"
	@echo "make gen-tokens       - 由 shared/tokens.ts 重新生成两端设计令牌"
	@echo "make gen-logo         - 由 scripts/gen_logo.mjs 重新生成 Logo (SVG + PNG)"
	@echo "make build-miniapp    - 构建微信小程序 (输出 miniapp/dist)"
	@echo "make ci               - ruff + pytest + 令牌校验 + 前端构建/测试 + 小程序构建"
	@echo "make backup           - 备份 MySQL 并清理 14 天前的备份"
	@echo "make db-start         - 启动项目专用 MySQL (macOS 独立实例)"
	@echo "make db-stop          - 停止项目专用 MySQL"
	@echo "make db-status        - 查看 MySQL 状态与已有数据库"
	@echo "make db-logs          - 跟踪 MySQL 错误日志"
	@echo "make db-shell         - 用 root 连进 MySQL"

# 一键本地环境 (首次部署跑这个)
setup-local:
	bash scripts/setup_local.sh

# 交互式运维台 (启动/停止/重启/日志/自检)
ops:
	bash scripts/service.sh

# 后台启动/停止/重启 (数据库 + 后端 + 前端), 不用占着终端
up:
	bash scripts/service.sh start

down:
	bash scripts/service.sh stop

restart:
	bash scripts/service.sh restart

status:
	bash scripts/service.sh status

SVC ?= backend
logs:
	bash scripts/service.sh logs $(SVC)

# 默认开发模式 (仅后端, 前台运行)
dev: dev-backend

dev-backend:
	cd backend && $(PYTHON) -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --proxy-headers

dev-frontend:
	cd frontend && npm run dev

install-backend:
	$(PYTHON) -m pip install -e ".[dev]"

install-frontend:
	cd frontend && npm install --no-fund --no-audit

install-miniapp:
	cd miniapp && npm install --no-fund --no-audit

setup: install-backend install-frontend
	@echo "Setup complete! 请复制 .env.example 为 .env 并填写密钥"

# 执行数据库迁移 (需先配置 APP__DATABASE__URL)
migrate:
	cd backend && $(PYTHON) -m alembic upgrade head

# 创建新迁移脚本 (用法: make migration MSG="add column xxx")
migration:
	cd backend && $(PYTHON) -m alembic revision --autogenerate -m "$(MSG)"

# 导入种子数据
seed:
	$(PYTHON) scripts/seed_data.py

test:
	cd backend && $(PYTHON) -m pytest tests/ -v --tb=short

test-cov:
	cd backend && $(PYTHON) -m pytest tests/ --cov=app --cov-report=term-missing

lint:
	$(PYTHON) -m ruff check backend scripts

lint-frontend:
	@if [ ! -x frontend/node_modules/.bin/eslint ]; then \
		echo "前端依赖还没装好, 先执行:  cd frontend && npm install"; \
		exit 1; \
	fi
	cd frontend && npm run lint

build-frontend:
	cd frontend && npm run build

build-miniapp:
	cd miniapp && npm run build:weapp

# 由 shared/tokens.ts 生成 frontend/src/styles/tokens.css 与 miniapp/src/styles/_tokens.scss
gen-tokens:
	node scripts/gen_tokens.mjs

# 由 scripts/gen_logo.mjs 生成品牌资源 (assets/logo + 两端引用)
gen-logo:
	node scripts/gen_logo.mjs

test-frontend:
	cd frontend && npm run test

# 共享层是两端唯一真源, 所以 CI 里必须校验生成物没有漂移
check-tokens:
	node scripts/gen_tokens.mjs --check

check-logo:
	node scripts/gen_logo.mjs --check

# 小程序只做类型检查 + 构建 (不引真机自动化)
check-miniapp:
	@if [ ! -d miniapp/node_modules ]; then \
		echo "小程序依赖还没装好, 先执行:  make install-miniapp"; \
		exit 1; \
	fi
	cd miniapp && npm run typecheck && npm run build:weapp

ci: lint test check-tokens check-logo test-frontend build-frontend check-miniapp

backup:
	$(PYTHON) scripts/backup_db.py

# 项目专用 MySQL 实例 (仅 macOS; 系统已有 MySQL 在跑的话这些命令用不上)
db-start:
	bash scripts/mysql_local.sh start

db-stop:
	bash scripts/mysql_local.sh stop

db-status:
	bash scripts/mysql_local.sh status

db-logs:
	bash scripts/mysql_local.sh logs

db-shell:
	bash scripts/mysql_local.sh shell

db-destroy:
	bash scripts/mysql_local.sh destroy

# 内网穿透 (开发期调试飞书回调需要 https, 生产请用真实域名)
tunnel:
	ngrok http 8000

# 初始化 Playwright 浏览器 (二期采集需要)
playwright-install:
	$(PYTHON) -m pip install -e ".[scraping]"
	$(PYTHON) -m playwright install chromium
