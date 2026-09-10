.PHONY: help dev dev-backend dev-frontend install-backend install-frontend test test-cov lint lint-frontend ci build-frontend migrate migration seed backup tunnel playwright-install setup setup-local

help:
	@echo "make setup-local      - 一键装好本地环境 (MySQL/Python/依赖/迁移/种子/测试)"
	@echo "make setup            - 仅安装后端+前端依赖 (环境已就绪时用)"
	@echo "make migrate          - 执行数据库迁移 (alembic upgrade head)"
	@echo "make seed             - 导入食材与参考价种子数据"
	@echo "make dev-backend      - 启动后端 (8000)"
	@echo "make dev-frontend     - 启动前端 (5173)"
	@echo "make test             - 运行后端测试"
	@echo "make lint             - ruff 静态检查"
	@echo "make lint-frontend    - eslint 检查前端代码"
	@echo "make ci               - lint + test + 前端构建"
	@echo "make backup           - 备份 MySQL 并清理 14 天前的备份"

# 一键本地环境 (首次部署跑这个)
setup-local:
	bash scripts/setup_local.sh

# 默认开发模式 (仅后端)
dev: dev-backend

dev-backend:
	cd backend && python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --proxy-headers

dev-frontend:
	cd frontend && npm run dev

install-backend:
	pip install -e ".[dev]"

install-frontend:
	cd frontend && npm install

setup: install-backend install-frontend
	@echo "Setup complete! 请复制 .env.example 为 .env 并填写密钥"

# 执行数据库迁移 (需先配置 APP__DATABASE__URL)
migrate:
	cd backend && python -m alembic upgrade head

# 创建新迁移脚本 (用法: make migration MSG="add column xxx")
migration:
	cd backend && python -m alembic revision --autogenerate -m "$(MSG)"

# 导入种子数据
seed:
	python scripts/seed_data.py

test:
	cd backend && python -m pytest tests/ -v --tb=short

test-cov:
	cd backend && python -m pytest tests/ --cov=app --cov-report=term-missing

lint:
	python -m ruff check backend scripts

lint-frontend:
	cd frontend && npm run lint

build-frontend:
	cd frontend && npm run build

ci: lint test build-frontend

backup:
	python scripts/backup_db.py

# 内网穿透 (开发期调试飞书回调需要 https, 生产请用真实域名)
tunnel:
	ngrok http 8000

# 初始化 Playwright 浏览器 (二期采集需要)
playwright-install:
	pip install -e ".[scraping]"
	python -m playwright install chromium
