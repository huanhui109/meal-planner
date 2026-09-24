#!/usr/bin/env bash
# ============================================================================
#  饭决 FAN·DECIDE - 生产环境建库与应用账号
#
#  用法:
#    MP_DB_PASSWORD='<强密码>' bash deploy/mysql/create-database.sh
#    MP_DB_ROOT_PASSWORD='<root密码>' MP_DB_PASSWORD='<强密码>' bash deploy/mysql/create-database.sh
#
#  密码来源优先级:
#    1) 环境变量 MP_DB_PASSWORD            (推荐, 生产从密钥管理注入, 不落盘)
#    2) 项目根目录 .env 里的 APP__DATABASE__URL 自动解析
#    3) 交互输入                            (不回显)
#
#  为什么用包装脚本而不是直接 mysql < 01-create-database.sql:
#    SQL 文件里只有 ${MP_DB_USER} / ${MP_DB_PASSWORD} 占位符, 明文密码既不写进
#    版本库, 也不会出现在 shell 历史或 ps 输出里。
# ============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SQL_TEMPLATE="$ROOT_DIR/deploy/mysql/01-create-database.sql"

MP_DB_NAME="${MP_DB_NAME:-meal_planner}"
MP_DB_USER="${MP_DB_USER:-meal_planner}"
MP_DB_HOST="${MP_DB_HOST:-127.0.0.1}"
MP_DB_PORT="${MP_DB_PORT:-3306}"
# root 连接参数: 有密码就用 -p<密码>, 没有就不带 (socket 免密场景)
MP_DB_ROOT_PASSWORD="${MP_DB_ROOT_PASSWORD:-}"
MP_DB_ROOT_USER="${MP_DB_ROOT_USER:-root}"

info() { printf "\033[1;34m▸ %s\033[0m\n" "$*"; }
ok()   { printf "\033[1;32m✓ %s\033[0m\n" "$*"; }
die()  { printf "\033[1;31m✗ %s\033[0m\n" "$*" >&2; exit 1; }

[ -f "$SQL_TEMPLATE" ] || die "找不到模板: $SQL_TEMPLATE"

# ---------- 1) 拿连接根的 mysql 客户端 ----------
MYSQL_BIN="${MYSQL_BIN:-$(command -v mysql || true)}"
[ -n "$MYSQL_BIN" ] || die "找不到 mysql 客户端, 请安装 MySQL 8.0 客户端或设置 MYSQL_BIN"

# ---------- 2) 拿应用账号密码 ----------
# 顺序: 环境变量 > .env 里解析 > 交互输入。永远不把它写进版本库。
if [ -z "${MP_DB_PASSWORD:-}" ] && [ -f "$ROOT_DIR/.env" ]; then
  candidate="$(
    sed -n 's|^APP__DATABASE__URL=mysql[^:]*://[^:]*:([^@]*)@.*|\1|p' "$ROOT_DIR/.env" | head -1
  )"
  if [ -n "$candidate" ] && [ "$candidate" != "change-me" ] && [ "$candidate" != "<password>" ]; then
    MP_DB_PASSWORD="$candidate"
    ok "从 .env 的 APP__DATABASE__URL 解析到应用账号密码"
  fi
fi

if [ -z "${MP_DB_PASSWORD:-}" ]; then
  # read -s 不回显; 在管道场景读不到就提示用户改用环境变量
  if [ -t 0 ]; then
    printf "请输入应用账号 %s 的密码 (不回显): " "$MP_DB_USER"
    read -rs MP_DB_PASSWORD
    printf "\n"
  else
    die "未设置 MP_DB_PASSWORD 且无法交互输入。请执行:
    MP_DB_PASSWORD='<强密码>' bash deploy/mysql/create-database.sh"
  fi
fi

case "$MP_DB_PASSWORD" in
  ""|"change-me"|"changeme"|"your_password"|"<password>"|'${'*)
    die "密码是占位值, 拒绝执行 —— 用模板密码建账号等于把库敞开。" ;;
esac
[ "${#MP_DB_PASSWORD}" -ge 8 ] || warn_short=1
if [ "${warn_short:-0}" = "1" ]; then
  printf "\033[1;33m! 密码短于 8 位, 生产环境请换更强的\033[0m\n"
fi

# ---------- 3) root 连接方式 ----------
ROOT_ARGS=()
if [ -n "$MP_DB_ROOT_PASSWORD" ]; then
  ROOT_ARGS=(-p"$MP_DB_ROOT_PASSWORD")
elif [ -t 0 ]; then
  printf "root 密码 (无密码直接回车): "
  read -rs root_pw
  printf "\n"
  [ -n "$root_pw" ] && ROOT_ARGS=(-p"$root_pw")
fi

"$MYSQL_BIN" -u "$MP_DB_ROOT_USER" -h "$MP_DB_HOST" -P "$MP_DB_PORT" --protocol=tcp \
  "${ROOT_ARGS[@]+"${ROOT_ARGS[@]}"}" -e "SELECT VERSION()" >/dev/null 2>&1 \
  || die "连不上 MySQL (root@$MP_DB_HOST:$MP_DB_PORT)。检查 MYSQL_BIN / MP_DB_ROOT_PASSWORD / 端口"

info "建库与应用账号: $MP_DB_NAME (+_test), 用户 $MP_DB_USER@$MP_DB_HOST:$MP_DB_PORT"

# ---------- 4) 占位替换后执行 ----------
# SQL 里的单引号要写成两个单引号。这一步必须在替换之后做,
# 否则会把整段 SQL 的分隔符也一起转义掉。
escaped_pw="${MP_DB_PASSWORD//\'/\'\'}"
rendered="$(sed \
  -e "s|\${MP_DB_USER}|$MP_DB_USER|g" \
  -e "s|\${MP_DB_PASSWORD}|$escaped_pw|g" \
  "$SQL_TEMPLATE")"

# 确认没有占位符残留 —— 模板改过字段名时这里会兜住
if printf '%s' "$rendered" | grep -qF '${MP_DB'; then
  die "模板里还有未替换的占位符, 请检查 01-create-database.sql 的变量名"
fi

printf '%s\n' "$rendered" | "$MYSQL_BIN" -u "$MP_DB_ROOT_USER" -h "$MP_DB_HOST" -P "$MP_DB_PORT" \
  --protocol=tcp "${ROOT_ARGS[@]+"${ROOT_ARGS[@]}"}"

ok "数据库就绪: $MP_DB_NAME / ${MP_DB_NAME}_test"
printf "\n下一步: 把同一个密码写进 .env ——\n"
printf "  APP__DATABASE__URL=mysql+aiomysql://%s:<上面的密码>@%s:%s/%s?charset=utf8mb4\n\n" \
  "$MP_DB_USER" "$MP_DB_HOST" "$MP_DB_PORT" "$MP_DB_NAME"
