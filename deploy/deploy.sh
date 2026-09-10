#!/usr/bin/env bash
# 发布脚本: 在本地执行, 把构建产物与代码同步到服务器并完成迁移/重启。
#
# 用法:
#   ./deploy/deploy.sh user@meal.example.com /srv/meal-planner
#
# 前置:
#   1. 服务器已按 deploy/README.md 完成首次初始化 (MySQL/venv/.env/nginx/systemd)
#   2. 本地可 ssh 到目标机器
set -euo pipefail

REMOTE_HOST="${1:?用法: deploy.sh user@host [远程目录]}"
REMOTE_DIR="${2:-/srv/meal-planner}"
LOCAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> 1/5 构建前端"
# 服务器上 package-lock.json 与 package.json 不同步时 npm ci 会直接失败,
# 这里回退到 npm install 并提示把 lock 文件提交上来。
if ! (cd "$LOCAL_DIR/frontend" && npm ci); then
  echo "   ! npm ci 失败 (通常是 package-lock.json 未同步), 回退到 npm install"
  echo "   ! 请本地执行 cd frontend && npm install 并提交 package-lock.json"
  (cd "$LOCAL_DIR/frontend" && npm install --no-fund --no-audit)
fi
(cd "$LOCAL_DIR/frontend" && npm run build)

echo "==> 2/5 同步代码 (排除 .env / 虚拟环境 / node_modules)"
rsync -az --delete \
  --exclude '.git' \
  --exclude '.env' \
  --exclude '.venv' \
  --exclude 'node_modules' \
  --exclude 'frontend/node_modules' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude 'logs/*' \
  --exclude '/data/' \
  --exclude '/backend/data/' \
  --exclude '/backups/' \
  --exclude '/dist/' \
  "$LOCAL_DIR/" "$REMOTE_HOST:$REMOTE_DIR/"

echo "==> 3/5 安装后端依赖"
ssh "$REMOTE_HOST" "cd $REMOTE_DIR && .venv/bin/pip install -q -e ."

echo "==> 4/5 执行数据库迁移"
ssh "$REMOTE_HOST" "cd $REMOTE_DIR/backend && APP_ENV=production ../.venv/bin/python -m alembic upgrade head"

echo "==> 5/5 重启服务"
ssh "$REMOTE_HOST" "sudo systemctl restart meal-planner-api && sudo systemctl reload nginx"

echo "完成。健康检查:"
ssh "$REMOTE_HOST" "curl -fsS https://\$(hostname -f)/api/health || true"
