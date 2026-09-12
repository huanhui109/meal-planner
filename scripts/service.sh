#!/usr/bin/env bash
# ============================================================================
#  AI 每周营养菜谱工具 · 本地服务运维台
#
#  管什么:  后端 (uvicorn) / 前端 (vite) / 数据库 (MySQL)
#  怎么用:  bash scripts/service.sh            # 打开交互式运维台
#           bash scripts/service.sh start      # 启动全部
#           bash scripts/service.sh restart backend
#           bash scripts/service.sh status
#
#  运行环境:  SERVICE_ENV=dev|prod  (缺省 dev, 决定加载哪套参数 / 构建方式)
#    dev  : 后端热重载 + debug 开启; 前端 vite dev + HMR; 详细日志
#    prod : 后端多 worker、无热重载、debug 关闭; 前端构建产物 preview; 端口 4173
#
#  可用环境变量覆盖:
#    SERVICE_ENV=prod  BACKEND_PORT=8000  FRONTEND_HOST=127.0.0.1  DEV_RELOAD=0  BACKEND_WORKERS=2
#    后端默认绑定 0.0.0.0: 这样手机(同一 wifi 下)用电脑 LAN IP 即可访问,
#    小程序真机调试/真机预览才能连上。仅本机开发时想收紧可设 BACKEND_HOST=127.0.0.1。
# ============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

LOGS_DIR="$ROOT_DIR/logs"
BACKEND_PID_FILE="$LOGS_DIR/backend.pid"
FRONTEND_PID_FILE="$LOGS_DIR/frontend.pid"
BACKEND_LOG="$LOGS_DIR/backend.log"
FRONTEND_LOG="$LOGS_DIR/frontend.log"
BACKEND_HOST="${BACKEND_HOST:-0.0.0.0}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
DEV_RELOAD="${DEV_RELOAD:-1}"
START_TIMEOUT="${START_TIMEOUT:-40}"
BACKEND_WORKERS="${BACKEND_WORKERS:-2}"

# ---------- 运行环境 (dev | prod) ----------
SERVICE_ENV="${SERVICE_ENV:-dev}"
case "$SERVICE_ENV" in
  dev|development) SERVICE_ENV="dev" ;;
  prod|production) SERVICE_ENV="prod" ;;
  *) echo "✗ 未知运行环境: $SERVICE_ENV (可选 dev | prod)" >&2; exit 1 ;;
esac
# 生产与开发使用不同默认端口, 便于两者同时并存不打架;
# 显式设置 FRONTEND_PORT 仍会覆盖这里的默认值。
FRONTEND_PORT="${FRONTEND_PORT:-$([ "$SERVICE_ENV" = "prod" ] && echo 4173 || echo 5173)}"

if [ -t 1 ]; then
  C_OK=$'\033[1;32m'; C_INFO=$'\033[1;34m'; C_WARN=$'\033[1;33m'
  C_ERR=$'\033[1;31m'; C_DIM=$'\033[2m'; C_BOLD=$'\033[1m'; C_OFF=$'\033[0m'
else
  C_OK=""; C_INFO=""; C_WARN=""; C_ERR=""; C_DIM=""; C_BOLD=""; C_OFF=""
fi
info() { printf "%s▸ %s%s\n" "$C_INFO" "$*" "$C_OFF"; }
ok()   { printf "%s✓ %s%s\n" "$C_OK" "$*" "$C_OFF"; }
warn() { printf "%s! %s%s\n" "$C_WARN" "$*" "$C_OFF"; }
err()  { printf "%s✗ %s%s\n" "$C_ERR" "$*" "$C_OFF"; }
dim()  { printf "%s  %s%s\n" "$C_DIM" "$*" "$C_OFF"; }
title(){ printf "\n%s%s%s\n" "$C_BOLD" "$*" "$C_OFF"; }

# 当前运行环境的彩色标签 (dev / prod)
env_label() {
  if [ "$SERVICE_ENV" = "prod" ]; then
    printf "%s生产 (prod)%s" "$C_WARN" "$C_OFF"
  else
    printf "%s开发 (dev)%s" "$C_INFO" "$C_OFF"
  fi
}

[ -f backend/app/main.py ] || { err "请在项目根目录执行: bash scripts/service.sh"; exit 1; }
mkdir -p "$LOGS_DIR"

# ---------- 基础工具 ----------
port_pids() {
  lsof -nP -tiTCP:"$1" -sTCP:LISTEN 2>/dev/null | tr '\n' ' ' || true
}

port_busy() {
  if command -v lsof >/dev/null 2>&1; then
    [ -n "$(port_pids "$1")" ]
  else
    tcp_open "127.0.0.1" "$1"
  fi
}

pid_alive() {
  [ -n "${1:-}" ] && kill -0 "$1" 2>/dev/null
}

read_pid() {
  [ -f "$1" ] && cat "$1" 2>/dev/null | tr -d '[:space:]' || true
}

peek_backend() {
  local code
  # 健康检查走 127.0.0.1 永远可达; BACKEND_HOST 可能为 0.0.0.0 不便直接 curl
  code="$(curl -sS -m 3 -o /dev/null -w '%{http_code}' "http://127.0.0.1:$BACKEND_PORT/api/health" 2>/dev/null || true)"
  if [ "$code" = "000" ] || [ "$code" = "" ]; then
    printf ''
  else
    printf '%s' "$code"
  fi
}

wait_port() {
  local port="$1" seconds="$2" i
  for i in $(seq 1 "$seconds"); do
    port_busy "$port" && return 0
    sleep 1
  done
  return 1
}

venv_python() {
  if [ -x "$ROOT_DIR/.venv/bin/python" ]; then
    printf '%s\n' "$ROOT_DIR/.venv/bin/python"
  elif command -v python3 >/dev/null 2>&1; then
    command -v python3
  else
    return 1
  fi
}

env_db_port() {
  local url
  url="$(grep -m1 '^APP__DATABASE__URL=' "$ROOT_DIR/.env" 2>/dev/null || true)"
  if [ -n "$url" ]; then
    printf '%s\n' "$url" | sed -n 's|.*@[^:/]*:\([0-9][0-9]*\)/.*|\1|p' | head -1
  fi
}

tcp_open() {
  local host="$1" port="$2" py
  case "$port" in
    ""|*[!0-9]*) return 1 ;;
  esac
  py="$(venv_python)" || return 1
  "$py" - "$host" "$port" <<'PY' >/dev/null 2>&1
import socket, sys
s = socket.socket()
s.settimeout(1.5)
try:
    s.connect((sys.argv[1], int(sys.argv[2])))
except Exception:
    raise SystemExit(1)
finally:
    s.close()
PY
}

# ---------- 状态 ----------
backend_state() {
  local pid
  pid="$(read_pid "$BACKEND_PID_FILE")"
  if port_busy "$BACKEND_PORT"; then
    if pid_alive "$pid"; then echo "running:$pid"; else echo "running:$(port_pids "$BACKEND_PORT" | awk '{print $1}')"; fi
  elif pid_alive "$pid"; then
    echo "stale:$pid"
  else
    echo "stopped:"
  fi
}

frontend_state() {
  local pid
  pid="$(read_pid "$FRONTEND_PID_FILE")"
  if port_busy "$FRONTEND_PORT"; then
    if pid_alive "$pid"; then echo "running:$pid"; else echo "running:$(port_pids "$FRONTEND_PORT" | awk '{print $1}')"; fi
  elif pid_alive "$pid"; then
    echo "stale:$pid"
  else
    echo "stopped:"
  fi
}

db_state() {
  local port
  port="$(env_db_port)"
  [ -n "$port" ] || port="3306"
  if tcp_open "127.0.0.1" "$port"; then echo "running:$port"; else echo "stopped:$port"; fi
}

dot() {
  case "$1" in
    running) printf "%s● 运行中%s" "$C_OK" "$C_OFF" ;;
    stale)   printf "%s◐ 异常%s" "$C_WARN" "$C_OFF" ;;
    *)       printf "%s○ 未运行%s" "$C_DIM" "$C_OFF" ;;
  esac
}

show_status() {
  local bs fs ds bp fp dp b f d bs_pid fp_pid
  IFS=: read -r b bs_pid <<<"$(backend_state)"; bs="$b"
  IFS=: read -r f fp_pid <<<"$(frontend_state)"; fs="$f"
  IFS=: read -r d dp <<<"$(db_state)"; ds="$d"

  dim "运行环境: $(env_label)"
  local code
  code="$(peek_backend)"
  printf "  %-14s %b   %s\n" "后端" "$(dot "$bs")" \
    "$(if [ "$bs" = "running" ]; then printf "http://%s:%s  健康检查 %s" "$BACKEND_HOST" "$BACKEND_PORT" "${code:-无响应}"; if [ "$BACKEND_HOST" = "0.0.0.0" ]; then printf "  (手机用电脑 LAN IP 访问)"; fi; else printf "端口 %s" "$BACKEND_PORT"; fi)"
  printf "  %-14s %b   %s\n" "前端" "$(dot "$fs")" \
    "$(if [ "$fs" = "running" ]; then printf "http://%s:%s" "$FRONTEND_HOST" "$FRONTEND_PORT"; else printf "端口 %s" "$FRONTEND_PORT"; fi)"
  printf "  %-14s %b   %s\n" "数据库" "$(dot "$ds")" \
    "$(if [ "$ds" = "running" ]; then printf "127.0.0.1:%s" "$dp"; else printf "端口 %s" "$dp"; fi)"
  if [ "$bs" = "running" ] && [ -n "$code" ] && [ "$code" != "200" ]; then
    dim "后端进程在跑但 /api/health 返回 $code, 看日志: bash scripts/service.sh logs backend"
  fi
  if [ "${1:-}" = "hint" ] && [ "$bs" = "stopped" ] && [ "$fs" = "stopped" ]; then
    dim "服务没起? 先跑 doctor 自检:  bash scripts/service.sh doctor"
    dim "或者直接回车进交互式运维台:  bash scripts/service.sh"
  fi
}

# ---------- 前置检查 ----------
check_backend_prereq() {
  if [ ! -f "$ROOT_DIR/.env" ]; then
    err "缺少 .env 配置文件"
    dim "先执行:  bash scripts/setup_local.sh"
    return 1
  fi
  if [ ! -x "$ROOT_DIR/.venv/bin/python" ]; then
    err "缺少 Python 虚拟环境 .venv"
    dim "先执行:  bash scripts/setup_local.sh"
    return 1
  fi
  if ! "$ROOT_DIR/.venv/bin/python" -c 'import uvicorn' >/dev/null 2>&1; then
    err "后端依赖没装好 (.venv 里没有 uvicorn)"
    dim "修复:  .venv/bin/pip install -e \".[dev]\""
    return 1
  fi
  return 0
}

check_frontend_prereq() {
  if [ ! -f "$ROOT_DIR/frontend/package.json" ]; then
    err "缺少 frontend/package.json"
    return 1
  fi
  if [ ! -x "$ROOT_DIR/frontend/node_modules/.bin/vite" ]; then
    err "前端依赖没装好 (frontend/node_modules 里没有 vite)"
    dim "修复:  cd frontend && npm install"
    return 1
  fi
  return 0
}

# ---------- 启停 ----------
start_backend() {
  local state pid code
  state="$(backend_state)"; pid="${state#*:}"
  case "$state" in
    running:*) ok "后端已在运行 (PID $pid, http://$BACKEND_HOST:$BACKEND_PORT)"; return 0 ;;
    stale:*)   warn "发现残留的 PID 文件 (进程 $pid 已不在), 清理后继续"; rm -f "$BACKEND_PID_FILE" ;;
  esac
  check_backend_prereq || return 1

  info "启动后端 (环境: $(env_label), uvicorn, 端口 $BACKEND_PORT, 日志 logs/backend.log)"
  local -a args=( -m uvicorn app.main:app "--host=$BACKEND_HOST" "--port=$BACKEND_PORT" --proxy-headers )
  if [ "$SERVICE_ENV" = "prod" ]; then
    dim "生产参数: ${BACKEND_WORKERS} 个 worker · 无热重载 · debug 关闭"
    args+=( "--workers=$BACKEND_WORKERS" )
  else
    if [ "$DEV_RELOAD" = "1" ]; then
      dim "开发参数: 热重载开启 · debug 开启 (DEV_RELOAD=0 可关热重载)"
      args+=( --reload )
    else
      dim "开发参数: 热重载关闭 (DEV_RELOAD=1 可开) · debug 开启"
    fi
  fi
  (
    cd "$ROOT_DIR/backend" || exit 1
    export APP__APP__DEBUG="$([ "$SERVICE_ENV" = "prod" ] && echo false || echo true)"
    nohup "$ROOT_DIR/.venv/bin/python" "${args[@]}" >>"$BACKEND_LOG" 2>&1 &
    echo $! >"$BACKEND_PID_FILE"
  )

  if wait_port "$BACKEND_PORT" "$START_TIMEOUT"; then
    local i
    for i in 1 2 3 4 5 6 7 8 9 10; do
      code="$(peek_backend)"
      [ "$code" = "200" ] && break
      sleep 1
    done
    if [ "$code" = "200" ]; then
      ok "后端已启动: http://$BACKEND_HOST:$BACKEND_PORT/docs   (健康检查 200)"
      return 0
    fi
    err "后端进程起来了, 但 /api/health 一直返回 ${code:-无响应} —— 服务不正常"
    dim "最常见原因: 数据库没起来 (.env 里配的库连不上)"
    dim "看日志:     bash scripts/service.sh logs backend"
    dim "查数据库:   bash scripts/service.sh status"
    return 1
  fi
  err "后端启动超时 ($START_TIMEOUT 秒), 日志最后 20 行:"
  tail -20 "$BACKEND_LOG" 2>/dev/null | sed "s/^/    /"
  rm -f "$BACKEND_PID_FILE"
  return 1
}

start_frontend() {
  local state pid
  state="$(frontend_state)"; pid="${state#*:}"
  case "$state" in
    running:*) ok "前端已在运行 (PID $pid, http://$FRONTEND_HOST:$FRONTEND_PORT)"; return 0 ;;
    stale:*)   warn "发现残留的 PID 文件 (进程 $pid 已不在), 清理后继续"; rm -f "$FRONTEND_PID_FILE" ;;
  esac
  check_frontend_prereq || return 1
  command -v npm >/dev/null 2>&1 || { err "找不到 npm, 请先安装 Node.js 18+"; return 1; }

  if [ "$SERVICE_ENV" = "prod" ]; then
    info "启动前端 (环境: $(env_label), 构建产物 preview, $FRONTEND_HOST:$FRONTEND_PORT)"
    local dist_dir="$ROOT_DIR/frontend/dist"
    if [ ! -d "$dist_dir" ]; then
      warn "没有找到构建产物 ($dist_dir), 先用生产模式构建一次"
      if ! (cd "$ROOT_DIR/frontend" && npm run build); then
        err "前端构建失败, 看上方 vite 报错"
        return 1
      fi
    else
      dim "使用现有构建产物: $dist_dir  (想重新构建先 rm -rf frontend/dist)"
    fi
    (
      cd "$ROOT_DIR/frontend" || exit 1
      nohup npm run preview -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT" --strictPort >>"$FRONTEND_LOG" 2>&1 &
      echo $! >"$FRONTEND_PID_FILE"
    )
  else
    info "启动前端 (环境: $(env_label), vite dev + HMR, $FRONTEND_HOST:$FRONTEND_PORT)"
    (
      cd "$ROOT_DIR/frontend" || exit 1
      nohup npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT" >>"$FRONTEND_LOG" 2>&1 &
      echo $! >"$FRONTEND_PID_FILE"
    )
  fi

  if wait_port "$FRONTEND_PORT" "$START_TIMEOUT"; then
    ok "前端已启动: http://$FRONTEND_HOST:$FRONTEND_PORT"
    return 0
  fi
  err "前端启动超时 ($START_TIMEOUT 秒), 日志最后 20 行:"
  tail -20 "$FRONTEND_LOG" 2>/dev/null | sed "s/^/    /"
  rm -f "$FRONTEND_PID_FILE"
  return 1
}

start_db() {
  local state port
  state="$(db_state)"; port="${state#*:}"
  if [ "$state" = "running" ]; then
    ok "数据库可达 (127.0.0.1:$port)"
    return 0
  fi
  if [ ! -x "$ROOT_DIR/scripts/mysql_local.sh" ] && [ ! -f "$ROOT_DIR/scripts/mysql_local.sh" ]; then
    err "数据库连不上 (127.0.0.1:$port)"
    dim "先执行:  bash scripts/setup_local.sh"
    return 1
  fi
  info "数据库未运行, 尝试启动项目专用实例 (端口 $port)"
  if bash "$ROOT_DIR/scripts/mysql_local.sh" start; then
    if tcp_open "127.0.0.1" "$port"; then
      ok "数据库已启动 (127.0.0.1:$port)"
      return 0
    fi
  fi
  err "数据库仍未就绪 (127.0.0.1:$port)"
  dim "看状态:  bash scripts/mysql_local.sh status"
  dim "看日志:  bash scripts/mysql_local.sh logs"
  dim "首次搭建或想彻底重来:  bash scripts/setup_local.sh"
  dim "注意: 如果系统 MySQL 的数据目录是更高版本(9.x)建的, brew services start mysql@8.0"
  dim "      只会一直 Bootstrap failed —— 那不是在跑的实例, 别动它 (docs/local-setup.md 附录 C)"
  return 1
}

kill_port() {
  local port="$1" label="$2" pids pid i
  command -v lsof >/dev/null 2>&1 || return 0
  pids="$(port_pids "$port")"
  [ -n "$pids" ] || return 0
  for pid in $pids; do
    kill -TERM "$pid" 2>/dev/null || true
  done
  for i in $(seq 1 10); do
    port_busy "$port" || return 0
    sleep 1
  done
  warn "$label 没有在 10 秒内退出, 强制结束"
  for pid in $(port_pids "$port"); do
    kill -KILL "$pid" 2>/dev/null || true
  done
  sleep 1
}

stop_backend() {
  local state pid
  state="$(backend_state)"; pid="${state#*:}"
  case "$state" in
    stopped:*) ok "后端本来就没在运行"; rm -f "$BACKEND_PID_FILE"; return 0 ;;
  esac
  info "停止后端 (端口 $BACKEND_PORT)"
  if pid_alive "$pid"; then kill -TERM "$pid" 2>/dev/null || true; fi
  kill_port "$BACKEND_PORT" "后端"
  rm -f "$BACKEND_PID_FILE"
  if port_busy "$BACKEND_PORT"; then err "端口 $BACKEND_PORT 仍被占用, 请手动检查"; return 1; fi
  ok "后端已停止"
}

stop_frontend() {
  local state pid
  state="$(frontend_state)"; pid="${state#*:}"
  case "$state" in
    stopped:*) ok "前端本来就没在运行"; rm -f "$FRONTEND_PID_FILE"; return 0 ;;
  esac
  info "停止前端 (端口 $FRONTEND_PORT)"
  if pid_alive "$pid"; then kill -TERM "$pid" 2>/dev/null || true; fi
  kill_port "$FRONTEND_PORT" "前端"
  rm -f "$FRONTEND_PID_FILE"
  if port_busy "$FRONTEND_PORT"; then err "端口 $FRONTEND_PORT 仍被占用, 请手动检查"; return 1; fi
  ok "前端已停止"
}

migrate_db() {
  check_backend_prereq || return 1
  local port
  port="$(env_db_port)"; [ -n "$port" ] || port="3306"
  if ! tcp_open "127.0.0.1" "$port"; then
    err "数据库连不上 (127.0.0.1:$port), 先启动它"
    dim "bash scripts/service.sh start db"
    return 1
  fi
  info "执行数据库迁移 (alembic upgrade head)"
  if (cd "$ROOT_DIR/backend" && "$ROOT_DIR/.venv/bin/python" -m alembic upgrade head); then
    ok "数据库结构已是代码里的最新版本"
    return 0
  fi
  err "迁移失败, 按顺序排查:"
  dim "1) 数据库没起            ->  bash scripts/service.sh start db"
  dim "2) 库/账号不存在         ->  bash scripts/setup_local.sh"
  dim "3) .env 里 APP__DATABASE__URL 的账号密码端口写错"
  dim "4) 想彻底重来            ->  docs/local-setup.md 附录 B"
  return 1
}

# ---------- 日志与自检 ----------
show_logs() {
  local which="$1" file
  case "$which" in
    backend)  file="$BACKEND_LOG" ;;
    frontend) file="$FRONTEND_LOG" ;;
    db|mysql) exec bash "$ROOT_DIR/scripts/mysql_local.sh" logs ;;
    *) err "未知服务: $which (可选 backend | frontend | db)"; return 1 ;;
  esac
  if [ ! -f "$file" ]; then
    warn "还没有日志文件 ($file), 服务可能从未启动过"
    dim "先启动:  bash scripts/service.sh start"
    return 1
  fi
  info "实时日志 $file   (Ctrl+C 退出)"
  tail -n 50 -f "$file"
}

doctor() {
  title "环境自检"
  local fails=0 py
  py="$(venv_python || true)"

  if [ -f "$ROOT_DIR/.env" ]; then ok ".env 存在"; else err ".env 缺失  ->  bash scripts/setup_local.sh"; fails=$((fails+1)); fi

  if [ -x "$ROOT_DIR/.venv/bin/python" ]; then
    ok "Python 虚拟环境: $("$ROOT_DIR/.venv/bin/python" --version 2>&1)"
  else
    err ".venv 缺失  ->  bash scripts/setup_local.sh"; fails=$((fails+1))
  fi

  if [ -n "$py" ] && "$py" -c 'import uvicorn, fastapi' >/dev/null 2>&1; then
    ok "后端依赖已安装"
  else
    err "后端依赖缺失  ->  .venv/bin/pip install -e \".[dev]\""; fails=$((fails+1))
  fi

  if [ -x "$ROOT_DIR/frontend/node_modules/.bin/vite" ]; then
    ok "前端依赖已安装"
  else
    err "前端依赖缺失  ->  cd frontend && npm install"; fails=$((fails+1))
  fi

  if [ -x "$ROOT_DIR/frontend/node_modules/.bin/eslint" ]; then
    ok "eslint 已安装 (make lint-frontend 可用)"
  else
    warn "eslint 未安装  ->  cd frontend && npm install"
  fi

  local dst port
  dst="$(db_state)"; port="${dst#*:}"
  if [ "$dst" = "running" ]; then ok "数据库可达 (127.0.0.1:$port)"; else err "数据库不可达 (127.0.0.1:$port)  ->  bash scripts/service.sh start db"; fails=$((fails+1)); fi

  if [ -f "$ROOT_DIR/backend/alembic.ini" ]; then
    local n_ver
    n_ver="$(ls -1 "$ROOT_DIR/backend/alembic/versions"/*.py 2>/dev/null | grep -cv '__init__' || true)"
    ok "Alembic 迁移配置存在 (${n_ver:-0} 个版本文件)"
  else
    warn "没找到 backend/alembic.ini"
  fi

  for p in "$BACKEND_PORT" "$FRONTEND_PORT"; do
    if port_busy "$p"; then ok "端口 $p 有服务在跑"; else dim "端口 $p 空闲"; fi
  done

  echo
  if [ "$fails" = "0" ]; then ok "自检全部通过, 可以 bash scripts/service.sh start"; else warn "有 $fails 项需要处理, 见上面提示"; fi
  return 0
}

health() {
  local code body
  code="$(peek_backend)"
  if [ -z "$code" ]; then
    err "后端没有响应 (http://$BACKEND_HOST:$BACKEND_PORT)"
    dim "先启动:  bash scripts/service.sh start backend"
    return 1
  fi
  body="$(curl -sS -m 5 "http://$BACKEND_HOST:$BACKEND_PORT/api/health" 2>/dev/null || true)"
  if [ "$code" = "200" ]; then
    ok "后端健康 (HTTP 200)"
    printf '%s\n' "$body" | sed "s/^/    /"
  else
    err "后端返回 HTTP $code"
    printf '%s\n' "$body" | sed "s/^/    /"
    return 1
  fi
}

# ---------- 统一入口 ----------
start_all() {
  local target="${1:-all}" db_ok=1 be_ok=1 fe_ok=1
  case "$target" in
    db)       start_db; return $? ;;
    backend)  start_backend; return $? ;;
    frontend) start_frontend; return $? ;;
    all)      ;;
    *) err "未知服务: $target (可选 all | backend | frontend | db)"; return 1 ;;
  esac

  info "启动全部 · 运行环境: $(env_label)  (前端端口 $FRONTEND_PORT)"

  if start_db;       then db_ok=0; fi
  if start_backend;  then be_ok=0; fi
  if start_frontend; then fe_ok=0; fi

  echo
  if [ "$db_ok" = "0" ] && [ "$be_ok" = "0" ] && [ "$fe_ok" = "0" ]; then
    title "全部就绪"
    show_status
    echo
    ok "浏览器打开:  http://$FRONTEND_HOST:$FRONTEND_PORT"
    dim "接口文档:   http://$BACKEND_HOST:$BACKEND_PORT/docs"
    if [ "$FRONTEND_HOST" = "0.0.0.0" ]; then
      dim "已监听所有网卡, 手机用同一 wifi 下电脑的 IP 就能访问"
    else
      dim "想用手机在局域网访问:  FRONTEND_HOST=0.0.0.0 bash scripts/service.sh restart frontend"
    fi
    dim "看日志:     bash scripts/service.sh logs backend  (或 frontend)"
    dim "关掉服务:   bash scripts/service.sh stop"
    return 0
  fi

  title "启动结果"
  show_status
  echo
  warn "有服务没起来, 按下面这几条排查:"
  if [ "$db_ok" != "0" ]; then
    dim "数据库       ->  bash scripts/mysql_local.sh logs"
    dim "             或  bash scripts/service.sh doctor"
  fi
  if [ "$be_ok" != "0" ]; then
    dim "后端         ->  bash scripts/service.sh logs backend"
    dim "             常见原因: 数据库没起来 / .env 配置不对 / 端口被占用"
  fi
  if [ "$fe_ok" != "0" ]; then
    dim "前端         ->  bash scripts/service.sh logs frontend"
    dim "             常见原因: 前端依赖没装 (cd frontend && npm install)"
  fi
  return 1
}

stop_all() {
  local target="${1:-all}"
  case "$target" in
    db)       warn "数据库需要单独停: bash scripts/mysql_local.sh stop" ;;
    backend)  stop_backend ;;
    frontend) stop_frontend ;;
    all)
      stop_backend || true
      stop_frontend || true
      echo
      show_status
      if tcp_open "127.0.0.1" "$(env_db_port)"; then
        dim "数据库仍在运行; 要停它:  bash scripts/mysql_local.sh stop"
      fi
      ;;
    *) err "未知服务: $target (可选 all | backend | frontend | db)"; return 1 ;;
  esac
}

restart_all() { stop_all "$1"; echo; start_all "$1"; }

# 显示当前环境及如何切换
show_env() {
  title "当前运行环境"
  ok "SERVICE_ENV=$SERVICE_ENV  (env: $(env_label))"
  if [ "$SERVICE_ENV" = "prod" ]; then
    dim "生产模式: 后端 ${BACKEND_WORKERS} worker · 无热重载 · debug 关闭; 前端构建产物 preview"
    dim "前端默认端口 $FRONTEND_PORT, 访问 http://$FRONTEND_HOST:$FRONTEND_PORT"
  else
    dim "开发模式: 后端热重载($([ "$DEV_RELOAD" = "1" ] && echo 开 || echo 关)) · debug 开启; 前端 vite dev + HMR"
    dim "前端默认端口 $FRONTEND_PORT, 访问 http://$FRONTEND_HOST:$FRONTEND_PORT"
  fi
  echo
  dim "切换环境(仅本次运行生效, 临时覆盖):"
  dim "  生产:  SERVICE_ENV=prod bash scripts/service.sh start"
  dim "  开发:  SERVICE_ENV=dev  bash scripts/service.sh start"
  echo
  dim "要长期固定某环境, 在导出或 .env 中写入 SERVICE_ENV=prod 即可。"
}

usage() {
  cat <<USAGE
AI 每周营养菜谱工具 · 本地服务运维台

用法:  bash scripts/service.sh [命令] [服务]

环境:  SERVICE_ENV=dev(默认)|prod  —— 决定开发/生产加载哪套参数与构建方式
       生产: SERVICE_ENV=prod bash scripts/service.sh start   (前端端口 4173)

命令:
  (不带参数)        打开交互式运维台
  status            查看后端/前端/数据库状态
  start   [服务]    启动
  stop    [服务]    停止
  restart [服务]    重启
  logs    <服务>    实时查看日志 (backend | frontend | db)
  health            后端健康检查 (含数据库连通性)
  doctor            环境自检: 依赖/配置/数据库/端口
  migrate           执行数据库迁移 (alembic upgrade head)
  env               显示当前运行环境及切换说明

服务:  all (默认)  |  backend  |  frontend  |  db

常用环境变量:  SERVICE_ENV  BACKEND_PORT  FRONTEND_HOST  FRONTEND_PORT
              BACKEND_WORKERS(prod)        DEV_RELOAD(dev)

例子:
  bash scripts/service.sh env               # 查看当前环境
  SERVICE_ENV=prod bash scripts/service.sh start  # 生产模式启动
  bash scripts/service.sh start             # 开发模式启动(缺省)
  bash scripts/service.sh restart backend   # 只重启后端
  bash scripts/service.sh logs frontend     # 跟踪前端日志
USAGE
}

menu() {
  while true; do
    printf "\n%s============================================%s\n" "$C_BOLD" "$C_OFF"
    printf "%s  AI 每周营养菜谱工具 · 本地运维台%s\n" "$C_BOLD" "$C_OFF"
    printf "%s============================================%s\n" "$C_BOLD" "$C_OFF"
    show_status hint
    cat <<MENU

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
MENU
    printf "请选择: "
    local choice
    read -r choice || { echo; return 0; }
    case "$choice" in
      1) echo; start_all all ;;
      2) echo; stop_all all ;;
      3) echo; restart_all all ;;
      4) submenu backend ;;
      5) submenu frontend ;;
      6)
        printf "看哪个服务的日志? (1=后端 2=前端 3=数据库, 其他取消): "
        local pick; read -r pick || true
        case "$pick" in
          1) show_logs backend ;;
          2) show_logs frontend ;;
          3) show_logs db ;;
          *) dim "已取消" ;;
        esac
        ;;
      7) doctor ;;
      8) health || true ;;
      9) migrate_db || true ;;
      q|Q) echo; ok "再见"; return 0 ;;
      "") ;;
      *) warn "无效选项: $choice" ;;
    esac
    printf "\n%s按回车回到菜单…%s" "$C_DIM" "$C_OFF"
    read -r _ || return 0
  done
}

submenu() {
  local svc="$1" label
  case "$svc" in
    backend)  label="后端" ;;
    frontend) label="前端" ;;
  esac
  printf "\n%s—— %s ——%s\n" "$C_BOLD" "$label" "$C_OFF"
  cat <<SUBMENU
  1) 启动
  2) 停止
  3) 重启
  4) 看日志
  0) 返回
SUBMENU
  printf "请选择: "
  local choice
  read -r choice || return 0
  case "$choice" in
    1) start_"$svc" ;;
    2) stop_"$svc" ;;
    3) restart_all "$svc" ;;
    4) show_logs "$svc" ;;
    0|"") return 0 ;;
    *) warn "无效选项: $choice" ;;
  esac
}

case "${1:-menu}" in
  menu)    menu ;;
  status)  title "服务状态"; show_status hint; echo ;;
  start)   start_all "${2:-all}" ;;
  stop)    stop_all "${2:-all}" ;;
  restart) restart_all "${2:-all}" ;;
  logs)    show_logs "${2:-backend}" ;;
  health)  health ;;
  doctor)  doctor ;;
  migrate) migrate_db ;;
  -h|--help|help) usage ;;
  env)   show_env ;;
  *) err "未知命令: $1"; echo; usage; exit 1 ;;
esac
