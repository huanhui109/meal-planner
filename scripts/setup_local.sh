#!/usr/bin/env bash
# ============================================================================
#  AI 每周营养菜谱工具 - 本地一键初始化
#
#  用法:  bash scripts/setup_local.sh
#
#  这个脚本会做完整套本地环境 (可重复执行, 已完成的步骤会自动跳过):
#    1. 检查/安装 MySQL 8.0 与 Python 3.12
#    2. 启动 MySQL, 创建 meal_planner / meal_planner_test 两个库与应用账号
#    3. 创建 .venv 并安装后端依赖
#    4. 生成 .env (自动填写随机 JWT 密钥、本地数据库地址、开发登录开关)
#    5. 执行数据库迁移并导入食材种子数据
#    6. 安装前端依赖
#    7. 跑一遍后端测试
#
#  可通过环境变量覆盖默认值:
#    DB_USER=meal_planner DB_PASSWORD=xxx DB_HOST=127.0.0.1 DB_PORT=3306 \
#    bash scripts/setup_local.sh
#
#  MySQL 端口约定: 统一使用 **3306** 的系统 MySQL 8.0 实例。
#  只有当系统实例不可用 (例如数据目录被更高版本 MySQL 建过, 8.0 拒绝降级打开)
#  时才退到 MYSQL_PORT (默认 3307) 的项目专用实例, 并且会用醒目的提示说明原因。
# ============================================================================
set -euo pipefail

# 输���函数必须在变量区之前定义: 下面解析 .env 复��密码时会用到 info
info() { printf "\033[1;34m▸ %s\033[0m\n" "$*"; }
ok()   { printf "\033[1;32m✓ %s\033[0m\n" "$*"; }
warn() { printf "\033[1;33m! %s\033[0m\n" "$*"; }
die()  { printf "\033[1;31m✗ %s\033[0m\n" "$*" >&2; exit 1; }
step() { printf "\n\033[1;36m==== %s ====\033[0m\n" "$*"; }

DB_NAME="${DB_NAME:-meal_planner}"
DB_TEST_NAME="${DB_TEST_NAME:-meal_planner_test}"
DB_USER="${DB_USER:-meal_planner}"
DB_PASSWORD="${DB_PASSWORD:-}"
DB_HOST="${DB_HOST:-127.0.0.1}"
# 生产与本地一致用 3306; 只有专用实例 fallback 时才会被改写成 MYSQL_PORT
DB_PORT="${DB_PORT:-3306}"
WITH_TESTS="${WITH_TESTS:-1}"

# 已经生成过 .env 时, 复用里面那套账号密码, 不要把它重置成默认值。
# 之前的行为是: .env 存在 -> 只改端口 -> 但 ALTER USER 又把密码改回了默认值,
# 结果 .env 里的旧密码失效, 报 1045 Access denied, 且报错指向的方向完全不对。
if [ -z "$DB_PASSWORD" ] && [ -f .env ]; then
  _existing_user="$(
    sed -n 's|^APP__DATABASE__URL=mysql[^:]*://\([^:]*\):.*|\1|p' .env | head -1
  )"
  _existing_pw="$(
    sed -n 's|^APP__DATABASE__URL=mysql[^:]*://[^:]*:\([^@]*\)@.*|\1|p' .env | head -1
  )"
  if [ -n "$_existing_pw" ]; then
    DB_PASSWORD="$_existing_pw"
    [ -n "$_existing_user" ] && DB_USER="$_existing_user"
    info "复用 .env 里已有的数据库账号 ($DB_USER)"
  fi
fi
DB_PASSWORD="${DB_PASSWORD:-meal_planner}"
# 生产要求 8.0; 若 Homebrew 已停用 8.0 (官方计划 2027-04-30), 自动退到 8.4 LTS
MYSQL_FORMULAS=("mysql@8.0" "mysql@8.4" "mysql")

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
[ -f backend/app/main.py ] || die "请在项目根目录执行: bash scripts/setup_local.sh"
[ -f frontend/package.json ] || die "缺少 frontend/package.json, 仓库似乎不完整"

OS="$(uname -s)"
case "$OS" in
  Darwin) PLATFORM="macos" ;;
  Linux)  PLATFORM="linux" ;;
  *)      die "仅支持 macOS 与 Linux, 当前系统: $OS" ;;
esac
info "平台: $PLATFORM   项目目录: $ROOT_DIR"

# ============================================================================
step "1/7  检查 MySQL 8.0 与 Python 3.12"
# ============================================================================
MYSQL_BIN_DIR=""
MYSQL_FORMULA=""
USE_SUDO_MYSQL="0"
MYSQL_SERVICE=""

install_mysql() {
  if [ "$PLATFORM" = "macos" ]; then
    command -v brew >/dev/null 2>&1 || die "未找到 Homebrew, 请先安装: https://brew.sh"
    for formula in "${MYSQL_FORMULAS[@]}"; do
      info "使用 Homebrew 安装 $formula (可能需要几分钟)"
      if brew install "$formula"; then
        MYSQL_FORMULA="$formula"
        return 0
      fi
      warn "$formula 安装失败, 尝试下一个候选"
    done
    die "mysql@8.0 / mysql@8.4 / mysql 均安装失败, 请手动安装 MySQL 后重跑本脚本"
  else
    info "使用 apt 安装 mysql-server"
    sudo apt-get update -qq
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y mysql-server
  fi
}

if [ "$PLATFORM" = "macos" ]; then
  BREW_PREFIX="$(brew --prefix 2>/dev/null || echo /opt/homebrew)"
  for formula in "${MYSQL_FORMULAS[@]}"; do
    if [ -x "$BREW_PREFIX/opt/$formula/bin/mysql" ]; then
      MYSQL_BIN_DIR="$BREW_PREFIX/opt/$formula/bin"
      MYSQL_SERVICE="$formula"
      MYSQL_FORMULA="$formula"
      break
    fi
  done
  if [ -z "$MYSQL_BIN_DIR" ] && command -v mysql >/dev/null 2>&1; then
    MYSQL_BIN_DIR="$(dirname "$(command -v mysql)")"
  fi
  if [ -z "$MYSQL_BIN_DIR" ]; then
    install_mysql
    MYSQL_BIN_DIR="$BREW_PREFIX/opt/$MYSQL_FORMULA/bin"
    MYSQL_SERVICE="$MYSQL_FORMULA"
  fi
  export PATH="$MYSQL_BIN_DIR:$PATH"
else
  if command -v mysql >/dev/null 2>&1; then
    MYSQL_BIN_DIR="$(dirname "$(command -v mysql)")"
  else
    install_mysql
    MYSQL_BIN_DIR="/usr/bin"
  fi
  MYSQL_SERVICE="mysql"
  USE_SUDO_MYSQL="1"
fi
[ -x "$MYSQL_BIN_DIR/mysql" ] || die "找不到 $MYSQL_BIN_DIR/mysql, 请手动安装 MySQL 8.0"
case "$MYSQL_SERVICE" in
  mysql@8.4|mysql) warn "使用 $MYSQL_SERVICE: 本地可用, 但生产建议安装 MySQL 8.0 保持一致" ;;
esac
ok "MySQL 客户端: $MYSQL_BIN_DIR/mysql  ($("$MYSQL_BIN_DIR/mysql" --version 2>/dev/null | head -1))"

# ---------- Python 3.12 ----------
PYTHON_BIN=""
if [ "$PLATFORM" = "macos" ]; then
  for candidate in "$(brew --prefix)/opt/python@3.12/bin/python3.12" python3.12 python3.13 python3.11; do
    if command -v "$candidate" >/dev/null 2>&1; then PYTHON_BIN="$(command -v "$candidate")"; break; fi
  done
  if [ -z "$PYTHON_BIN" ]; then
    info "使用 Homebrew 安装 python@3.12"
    brew install python@3.12
    PYTHON_BIN="$(brew --prefix)/opt/python@3.12/bin/python3.12"
  fi
else
  for candidate in python3.12 python3.11 python3.13; do
    if command -v "$candidate" >/dev/null 2>&1; then PYTHON_BIN="$(command -v "$candidate")"; break; fi
  done
  if [ -z "$PYTHON_BIN" ]; then
    info "使用 apt 安装 python3.12"
    sudo apt-get update -qq
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y python3.12 python3.12-venv python3-pip
    PYTHON_BIN="$(command -v python3.12)"
  fi
fi
"$PYTHON_BIN" - <<'PY' || die "Python 版本过低, 需要 >= 3.11"
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
ok "Python: $PYTHON_BIN  ($("$PYTHON_BIN" --version))"
# ============================================================================
step "2/7  启动 MySQL 并创建数据库"
# ============================================================================
BREW_PREFIX="$(brew --prefix 2>/dev/null || echo /opt/homebrew)"
LEGACY_DATADIR="$BREW_PREFIX/var/mysql"
DEDICATED_DATADIR="${MYSQL_DATADIR:-$BREW_PREFIX/var/mysql80}"
# 专用实例端口只是 **兜底**: 3306 的系统实例能用就绝不起第二个 mysqld。
# 3307 这个号来自早期「躲开系统 MySQL」的做法, 现在系统实例就是 8.0 了, 没必要躲。
DEDICATED_PORT="${MYSQL_PORT:-3307}"
DEDICATED_SOCKET="${MYSQL_SOCKET:-/tmp/meal-planner-mysql.sock}"
MYSQL_MODE=""
MYSQL_SOCKET_PATH=""
MYSQL_ROOT_PW="${MYSQL_ROOT_PASSWORD:-}"
ROOT_ARGS=()
if [ -n "$MYSQL_ROOT_PW" ]; then ROOT_ARGS=(-p"$MYSQL_ROOT_PW"); fi

# 按照连接方式跑一条 mysql 命令:
#   socket:<路径>  -> 指定 socket; socket:default -> 默认 socket (系统实例)
#   tcp:<端口>     -> 本地 TCP;     sudo-socket / sudo-tcp -> Ubuntu 用 sudo 连
run_mysql() {
  local spec="$1"; shift
  case "$spec" in
    sudo-socket)   sudo mysql --protocol=socket "$@" ;;
    sudo-tcp)      sudo mysql -h 127.0.0.1 -P 3306 --protocol=tcp "$@" ;;
    socket:default) "$MYSQL_BIN_DIR/mysql" -u root --protocol=socket ${ROOT_ARGS[@]+"${ROOT_ARGS[@]}"} "$@" ;;
    socket:*)      "$MYSQL_BIN_DIR/mysql" -u root --protocol=socket --socket="${spec#socket:}" ${ROOT_ARGS[@]+"${ROOT_ARGS[@]}"} "$@" ;;
    tcp:*)         "$MYSQL_BIN_DIR/mysql" -u root --protocol=tcp -h 127.0.0.1 -P "${spec#tcp:}" ${ROOT_ARGS[@]+"${ROOT_ARGS[@]}"} "$@" ;;
    *)             return 1 ;;
  esac
}

# 依次尝试各个候选连接方式, 第一个能连上的就是它。
#
# 顺序很重要: 先系统 3306 (socket -> tcp), 再专用实例。
# 早期版本把专用实例排在最前面, 结果机器上明明跑着 8.0 的 3306,
# 脚本却偏要再起一个 3307 的 mysqld 出来 —— 两套实例各有一份数据,
# 用 Navicat 连 3306 看到的表, 和应用写的根本不是同一个库。
probe_mysql() {
  local spec
  for spec in socket:default "tcp:$DB_PORT" "socket:$DEDICATED_SOCKET" "tcp:$DEDICATED_PORT"; do
    if run_mysql "$spec" -e "SELECT 1" >/dev/null 2>&1; then
      MYSQL_MODE="$spec"
      case "$spec" in
        socket:default) MYSQL_SOCKET_PATH=""; DB_PORT="3306" ;;
        socket:*)       MYSQL_SOCKET_PATH="${spec#socket:}"; DB_PORT="$DEDICATED_PORT" ;;
        tcp:*)          MYSQL_SOCKET_PATH=""; DB_PORT="${spec#tcp:}" ;;
      esac
      return 0
    fi
  done
  if [ "$USE_SUDO_MYSQL" = "1" ]; then
    for spec in sudo-socket sudo-tcp; do
      if run_mysql "$spec" -e "SELECT 1" >/dev/null 2>&1; then
        MYSQL_MODE="$spec"; DB_PORT="3306"; MYSQL_SOCKET_PATH=""; return 0
      fi
    done
  fi
  return 1
}

mysql_root() { run_mysql "$MYSQL_MODE" "$@"; }

mysql_diagnostics() {
  echo
  warn "MySQL 连不上的排查信息:"
  local errlog
  errlog="$(ls -t "$LEGACY_DATADIR"/*.err "$DEDICATED_DATADIR"/*.err 2>/dev/null | head -1 || true)"
  if [ -n "$errlog" ]; then
    echo "  1) 错误日志最后 25 行 ($errlog):"
    tail -25 "$errlog" 2>/dev/null | sed 's/^/     /'
  else
    echo "  1) 没找到错误日志 ($LEGACY_DATADIR/*.err 与 $DEDICATED_DATADIR/*.err)"
  fi
  echo "  2) 连接的真实报错:"
  "$MYSQL_BIN_DIR/mysql" -u root --protocol=socket -e "SELECT 1" 2>&1 | sed 's/^/     /'
  echo
  echo "  常见修法:"
  echo "    root 有密码  -> MYSQL_ROOT_PASSWORD=你的密码 bash scripts/setup_local.sh"
  echo "    换数据目录   -> MYSQL_DATADIR=\$HOME/mysql80 bash scripts/setup_local.sh"
  echo "    单独看数据库 -> bash scripts/mysql_local.sh status"
  echo "    彻底重来     -> bash scripts/mysql_local.sh destroy && bash scripts/setup_local.sh"
  echo
}

wait_for_mysql() {
  local seconds="$1" i
  for i in $(seq 1 "$seconds"); do
    if probe_mysql; then return 0; fi
    sleep 1
  done
  return 1
}

# ---------- 1) 已经有能连上的 MySQL 就直接复用 ----------
if probe_mysql; then
  ok "复用正在运行的 MySQL ($MYSQL_MODE, 端口 $DB_PORT)"
fi

# ---------- 2) 先判断旧数据目录是不是更高版本建的 ----------
# MySQL 不支持降级: 如果 /opt/homebrew/var/mysql 是 9.x 建的, 8.0 打开它会直接崩溃,
# brew services 会以 KeepAlive 无限重启。这种时候完全不要走 brew services, 直接开专用实例。
LEGACY_CONFLICT=0
if [ -z "$MYSQL_MODE" ] && [ "$PLATFORM" = "macos" ]; then
  LEGACY_ERRLOG="$(ls -t "$LEGACY_DATADIR"/*.err 2>/dev/null | head -1 || true)"
  if [ -n "$LEGACY_ERRLOG" ] && tail -200 "$LEGACY_ERRLOG" 2>/dev/null | grep -q "Cannot downgrade from"; then
    LEGACY_CONFLICT=1
  fi
fi

if [ "$LEGACY_CONFLICT" = "1" ]; then
  echo
  warn "检测到旧数据目录版本冲突 (这个目录里可能有你别的数据, 脚本不会碰它):"
  tail -200 "$LEGACY_ERRLOG" 2>/dev/null | grep -m1 "Cannot downgrade from" | sed 's/^/     /'
  echo "     $LEGACY_DATADIR 是更高版本 MySQL 建的, 8.0 读不了它 (MySQL 不支持降级)。"
  echo "     所以本项目不再使用系统 MySQL, 改为单独跑一个实例:"
  echo "       数据目录 $DEDICATED_DATADIR"
  echo "       端口     $DEDICATED_PORT   (避开系统 MySQL 的 3306, 两者可以同时跑)"
  echo "       socket   $DEDICATED_SOCKET"
  echo
  if brew services list 2>/dev/null | grep -qE "^$MYSQL_SERVICE[[:space:]]+started"; then
    if brew services stop "$MYSQL_SERVICE" >/dev/null 2>&1; then
      ok "已停止一直在崩溃重启的 $MYSQL_SERVICE"
    else
      warn "建议手动执行: brew services stop $MYSQL_SERVICE"
    fi
  fi
fi

# ---------- 3) macOS: 尝试 Homebrew 自带服务 (仅在无冲突时) ----------
if [ -z "$MYSQL_MODE" ] && [ "$PLATFORM" = "macos" ] && [ "$LEGACY_CONFLICT" = "0" ]; then
  info "尝试启动 Homebrew 服务: $MYSQL_SERVICE"
  brew services start "$MYSQL_SERVICE" >/dev/null 2>&1 || true
  wait_for_mysql 20 || true

  if [ -z "$MYSQL_MODE" ]; then
    _errlog="$(ls -t "$LEGACY_DATADIR"/*.err 2>/dev/null | head -1 || true)"
    if [ -n "$_errlog" ] && tail -200 "$_errlog" 2>/dev/null | grep -q "Cannot downgrade from"; then
      LEGACY_CONFLICT=1
      LEGACY_ERRLOG="$_errlog"
      echo
      warn "检测到旧数据目录版本冲突:"
      tail -200 "$_errlog" 2>/dev/null | grep -m1 "Cannot downgrade from" | sed 's/^/     /'
      echo "     为保护里面已有的数据, 本脚本不会动它, 改为给本项目单独开一个实例。"
      echo
      brew services stop "$MYSQL_SERVICE" >/dev/null 2>&1 \
        && ok "已停止崩溃重启中的 $MYSQL_SERVICE" \
        || warn "建议手动执行: brew services stop $MYSQL_SERVICE"
      launchctl bootout "gui/$(id -u)/sh.brew.$MYSQL_SERVICE" >/dev/null 2>&1 || true
    fi
  fi
fi

# ---------- 4) Linux: systemd ----------
if [ -z "$MYSQL_MODE" ] && [ "$PLATFORM" = "linux" ]; then
  info "启动 systemd 服务: mysql"
  sudo systemctl enable --now mysql >/dev/null 2>&1 || warn "无法通过 systemctl 启动 mysql"
  wait_for_mysql 30 || true
fi

# ---------- 5) 仍然连不上: 给本项目单独跑一个实例 ----------
if [ -z "$MYSQL_MODE" ] && [ "$PLATFORM" = "macos" ]; then
  warn "使用项目专用 MySQL 实例 (不碰系统 MySQL, 数据目录 $DEDICATED_DATADIR)"
  if ! MP_MYSQL_DATADIR="$DEDICATED_DATADIR" \
       MP_MYSQL_PORT="$DEDICATED_PORT" \
       MP_MYSQL_SOCKET="$DEDICATED_SOCKET" \
       MP_MYSQL_FORMULA="$MYSQL_FORMULA" \
       bash "$ROOT_DIR/scripts/mysql_local.sh" start; then
    mysql_diagnostics
    die "专用 MySQL 实例启动失败, 请把上面的信息发出来定位"
  fi
  probe_mysql || true
fi

if [ -z "$MYSQL_MODE" ]; then
  mysql_diagnostics
  die "MySQL 未就绪。请按上面的排查结果处理后重跑本脚本"
fi
ok "root 连接方式: $MYSQL_MODE   (端口 $DB_PORT)"

for db in "$DB_NAME" "$DB_TEST_NAME"; do
  mysql_root <<SQL
CREATE DATABASE IF NOT EXISTS \`$db\`
  DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
SQL
done

# 应用账号: 只给这两个库的权限, 不用 root 跑应用
mysql_root <<SQL
CREATE USER IF NOT EXISTS '$DB_USER'@'127.0.0.1' IDENTIFIED BY '$DB_PASSWORD';
ALTER USER '$DB_USER'@'127.0.0.1' IDENTIFIED BY '$DB_PASSWORD';
CREATE USER IF NOT EXISTS '$DB_USER'@'localhost' IDENTIFIED BY '$DB_PASSWORD';
ALTER USER '$DB_USER'@'localhost' IDENTIFIED BY '$DB_PASSWORD';
GRANT ALL PRIVILEGES ON \`$DB_NAME\`.* TO '$DB_USER'@'127.0.0.1';
GRANT ALL PRIVILEGES ON \`$DB_TEST_NAME\`.* TO '$DB_USER'@'127.0.0.1';
GRANT ALL PRIVILEGES ON \`$DB_NAME\`.* TO '$DB_USER'@'localhost';
GRANT ALL PRIVILEGES ON \`$DB_TEST_NAME\`.* TO '$DB_USER'@'localhost';
FLUSH PRIVILEGES;
SQL
ok "数据库就绪: $DB_NAME / $DB_TEST_NAME (端口 $DB_PORT), 应用账号: $DB_USER"


# ============================================================================
step "3/7  创建虚拟环境并安装后端依赖"
# ============================================================================
VENV_PY="$ROOT_DIR/.venv/bin/python"
if [ -x "$VENV_PY" ] && "$VENV_PY" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
  ok ".venv 可复用 ($("$VENV_PY" --version))"
else
  if [ -d .venv ]; then
    warn ".venv 不可用或 Python 版本低于 3.11, 重新创建"
  else
    info "创建 .venv"
  fi
  "$PYTHON_BIN" -m venv --clear .venv
fi
VENV_PY="$ROOT_DIR/.venv/bin/python"
info "安装后端依赖 (pip install -e \".[dev]\")"
"$VENV_PY" -m pip install --quiet --upgrade pip || warn "升级 pip 失败 (通常是网络问题), 继续尝试安装依赖"
if ! "$VENV_PY" -m pip install -e ".[dev]"; then
  die "后端依赖安装失败。常见原因: 网络不通 / 代理未配置 / 镜像源不可用。
   重试命令:  .venv/bin/pip install -e \".[dev]\"
   切换镜像:  .venv/bin/pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e \".[dev]\""
fi
ok "后端依赖安装完成"

# ============================================================================
step "4/7  生成 .env"
# ============================================================================
ENV_FILE="$ROOT_DIR/.env"
if [ -f "$ENV_FILE" ]; then
  warn ".env 已存在, 保留其中的密钥与其他自定义配置"

  # 数据库这一段是唯一会被改写的部分。
  # 之前只 port 一处一处地打补丁 (3306 -> 3307), 结果账号/密码/库名与 MySQL 里
  # 实际授予的不一致时没人管, 应用连上来就是 1045 或 1044, 报错位置离根因很远。
  # 现在整条 URL 按当前脚本参数重写, 保证 .env 与真实授权状态始终一致。
  _target_url="mysql+aiomysql://$DB_USER:$DB_PASSWORD@$DB_HOST:$DB_PORT/$DB_NAME?charset=utf8mb4"
  _current_url="$(sed -n 's|^APP__DATABASE__URL=\(.*\)$|\1|p' "$ENV_FILE" | head -1)"
  if [ -n "$_current_url" ] && [ "$_current_url" != "$_target_url" ]; then
    # 用 python 做替换, 避免密码里的 & / \ 等特殊字符把 sed 的替换串搅乱
    APP__DATABASE__URL="$_target_url" "$VENV_PY" - "$ENV_FILE" <<'PY'
import os, pathlib, sys
path = pathlib.Path(sys.argv[1])
target = os.environ["APP__DATABASE__URL"]
out = []
changed = False
for line in path.read_text(encoding="utf-8").splitlines():
    if line.startswith("APP__DATABASE__URL="):
        out.append(f"APP__DATABASE__URL={target}")
        changed = True
    else:
        out.append(line)
if changed:
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
PY
    ok ".env 的 APP__DATABASE__URL 已同步 (库: $DB_NAME@$DB_HOST:$DB_PORT)"
  else
    ok ".env 里的数据库连接串已是最新"
  fi
else
  JWT_SECRET="$("$VENV_PY" -c 'import secrets; print(secrets.token_urlsafe(48))')"
  cat > "$ENV_FILE" <<ENVEOF
# 由 scripts/setup_local.sh 自动生成 (本地开发配置)
# 完整字段说明见 .env.example 与 docs/local-setup.md

# ===== 数据库 =====
APP__DATABASE__URL=mysql+aiomysql://$DB_USER:$DB_PASSWORD@$DB_HOST:$DB_PORT/$DB_NAME?charset=utf8mb4
APP__DATABASE__ECHO=false

# ===== 应用 =====
APP__APP__DEBUG=true
APP__APP__BASE_URL=http://127.0.0.1:8000

# ===== 认证 =====
APP__AUTH__JWT_SECRET=$JWT_SECRET
# 本地是 http, 必须关掉 Secure 否则浏览器不会保存登录 Cookie
APP__AUTH__COOKIE_SECURE=false
# 本地没有飞书应用时, 用「本地开发登录」进入应用; 生产必须改为 false
APP__AUTH__DEV_LOGIN=true

# ===== 飞书扫码登录 (本地留空即可, 留空时登录页只显示本地开发登录) =====
FEISHU_APP_ID=
FEISHU_APP_SECRET=
APP__FEISHU__REDIRECT_URI=

# ===== LLM =====
# 正式生成菜单需要至少一个 Key; 一个都没有时可临时用演示模式
GLM4_API_KEY=
QWEN_API_KEY=
DEEPSEEK_API_KEY=
APP__LLM__DEMO=true
ENVEOF
  chmod 600 "$ENV_FILE"
  ok ".env 已生成 (含随机 JWT 密钥), 权限 600"
fi

# ============================================================================
step "5/7  执行数据库迁移并导入种子数据"
# ============================================================================
info "alembic upgrade head"
(cd backend && "$VENV_PY" -m alembic upgrade head)
info "导入食材与参考价"
"$VENV_PY" scripts/seed_data.py
ok "数据库结构与种子数据就绪"

# ============================================================================
step "6/7  安装前端依赖"
# ============================================================================
if command -v npm >/dev/null 2>&1; then
  (cd frontend && npm install --no-fund --no-audit)
  ok "前端依赖安装完成"
else
  warn "未找到 npm, 跳过前端依赖安装 (请安装 Node.js 18+ 后执行: cd frontend && npm install)"
fi

# ============================================================================
step "7/7  运行后端测试"
# ============================================================================
if [ "$WITH_TESTS" = "1" ]; then
  export TEST_DATABASE_URL="mysql+aiomysql://$DB_USER:$DB_PASSWORD@$DB_HOST:$DB_PORT/$DB_TEST_NAME?charset=utf8mb4"
  if (cd backend && "$VENV_PY" -m pytest tests/ -q); then
    ok "测试全部通过"
  else
    warn "测试未全部通过, 请把上面的输出发给我"
  fi
else
  warn "已跳过测试 (WITH_TESTS=0)"
fi

# ============================================================================
printf "\n\033[1;32m%s\033[0m\n" "=============================================="
printf "\033[1;32m%s\033[0m\n" "  初始化完成! 现在这样启动本地服务"
printf "\033[1;32m%s\033[0m\n" "=============================================="
cat <<'NEXT'

在项目根目录执行 (推荐第一条, 后台跑不占终端):

  make ops        # 交互式运维台: 菜单里选 1 启动全部, 带实时状态和排障提示
  make up         # 或者不用菜单, 直接后台启动 数据库 + 后端 + 前端
  make status     # 看状态
  make logs       # 跟后端日志 (Ctrl+C 退出)
  make down       # 停掉后端 + 前端 (数据库不动)

想看 uvicorn / vite 的实时输出 (调试用) 就开两个终端:

  终端 1 (后端):   make dev-backend
  终端 2 (前端):   make dev-frontend

然后浏览器打开:  http://localhost:5173

登录页会显示「本地开发登录」, 输入任意昵称点一下就能进去
(想再开一个用户验证数据隔离, 换个昵称再登录一次即可)。

以后拉到新代码:   bash scripts/setup_local.sh   (幂等, 会顺手升级表结构)
                  或只要升级表结构:  make migrate
想连真实飞书扫码:  见 docs/local-setup.md 的「接入真实飞书登录」小节
想用真模型生成菜单: 在 .env 里填 GLM4_API_KEY / QWEN_API_KEY / DEEPSEEK_API_KEY
                    并把 APP__LLM__DEMO 改成 false

NEXT
