#!/usr/bin/env bash
# ============================================================================
#  项目专用 MySQL 实例管理器 (macOS / Homebrew) —— 仅作兜底, 正常情况不要用
#
#  ⚠ 默认使用的是 **3306 上的系统 MySQL 8.0 实例**, 不是这里管的实例。
#    本脚本只在系统实例真的起不来时才用, 例如:
#      /opt/homebrew/var/mysql 被更高版本 MySQL (9.x) 建过, 8.0 拒绝降级打开
#      (MySQL 不支持降级), brew services start mysql@8.0 会无限崩溃重启。
#    那种情况下才单独跑一个实例: 自己的数据目录、自己的端口、自己的 socket,
#    完全不动机器上原有的数据。
#
#    跑起来之后记得把 .env 里的 APP__DATABASE__URL 指到本实例的端口,
#    否则应用仍然连 3306, 会连到一个"看起来正常但表里没数据"的库。
#    一键修正: bash scripts/setup_local.sh
#
#  用法:
#    bash scripts/mysql_local.sh start     # 启动 (首次会自动初始化数据目录)
#    bash scripts/mysql_local.sh stop      # 停止
#    bash scripts/mysql_local.sh restart   # 重启
#    bash scripts/mysql_local.sh status    # 看状态
#    bash scripts/mysql_local.sh logs      # 跟踪错误日志 (Ctrl+C 退出)
#    bash scripts/mysql_local.sh shell     # 用 root 连进去
#    bash scripts/mysql_local.sh destroy   # 删除本实例的数据目录 (只影响本项目)
#
#  可用环境变量覆盖:
#    MP_MYSQL_DATADIR  数据目录   默认 $(brew --prefix)/var/mysql80
#    MP_MYSQL_PORT     端口       默认 3307
#                                 刻意避开 3306: 本实例存在的意义就是"不与系统实例
#                                 抢端口", 两台 mysqld 才能同时跑、互不干扰。
#                                 改回 3306 要先停掉系统实例, 否则会启动失败。
#    MP_MYSQL_SOCKET   socket     默认 /tmp/meal-planner-mysql.sock
#    MP_MYSQL_FORMULA  公式名     默认自动探测 mysql@8.0 / mysql@8.4 / mysql
# ============================================================================
set -euo pipefail

if [ "$(uname -s)" != "Darwin" ]; then
  echo "此脚本仅用于 macOS (Homebrew)。Linux 请用 systemd: sudo systemctl start mysql" >&2
  exit 1
fi

info() { printf "\033[1;34m▸ %s\033[0m\n" "$*"; }
ok()   { printf "\033[1;32m✓ %s\033[0m\n" "$*"; }
warn() { printf "\033[1;33m! %s\033[0m\n" "$*"; }
die()  { printf "\033[1;31m✗ %s\033[0m\n" "$*" >&2; exit 1; }

BREW_PREFIX="$(brew --prefix 2>/dev/null || echo /opt/homebrew)"
MP_MYSQL_DATADIR="${MP_MYSQL_DATADIR:-$BREW_PREFIX/var/mysql80}"
MP_MYSQL_PORT="${MP_MYSQL_PORT:-3307}"
MP_MYSQL_SOCKET="${MP_MYSQL_SOCKET:-/tmp/meal-planner-mysql.sock}"
MP_MYSQLX_SOCKET="${MP_MYSQLX_SOCKET:-/tmp/meal-planner-mysqlx.sock}"
MP_MYSQLX_PORT="${MP_MYSQLX_PORT:-33070}"
MP_MYSQL_LABEL="${MP_MYSQL_LABEL:-com.mealplanner.mysql80}"
MP_MYSQL_PLIST="$HOME/Library/LaunchAgents/$MP_MYSQL_LABEL.plist"
MP_MYSQL_PIDFILE="$MP_MYSQL_DATADIR/mysqld.pid"
MP_MYSQL_ERRLOG="$MP_MYSQL_DATADIR/error.log"

# ---------- 找到 mysqld 二进制 ----------
# 注意: 这里必须直接给 MYSQL_BIN_DIR / MP_MYSQL_FORMULA 赋值, 不能写成
#   MYSQL_BIN_DIR="$(find_bin_dir)"
# 因为命令替换会开子 shell, 函数里设的 MP_MYSQL_FORMULA 传不回父 shell,
# 后面 write_plist/start_nohup 用到它时就会被 `set -u` 判成 unbound variable。
find_bin_dir() {
  local formula
  if [ -n "${MP_MYSQL_FORMULA:-}" ]; then
    [ -x "$BREW_PREFIX/opt/$MP_MYSQL_FORMULA/bin/mysqld" ] \
      || die "MP_MYSQL_FORMULA=$MP_MYSQL_FORMULA 下没有 mysqld"
    MYSQL_BIN_DIR="$BREW_PREFIX/opt/$MP_MYSQL_FORMULA/bin"
    return 0
  fi
  for formula in mysql@8.0 mysql@8.4 mysql; do
    if [ -x "$BREW_PREFIX/opt/$formula/bin/mysqld" ]; then
      MP_MYSQL_FORMULA="$formula"
      MYSQL_BIN_DIR="$BREW_PREFIX/opt/$formula/bin"
      return 0
    fi
  done
  die "没找到 mysqld。请先安装: brew install mysql@8.0"
}
MYSQL_BIN_DIR=""
find_bin_dir

# macOS 会定期清理 /tmp, socket 文件可能凭空消失。
# 所以所有客户端命令都走这个包装: 有 socket 就用 socket, 没有就退回 TCP。
mysql_cli() {
  local bin="$1"; shift
  if [ -S "$MP_MYSQL_SOCKET" ]; then
    "$bin" --socket="$MP_MYSQL_SOCKET" "$@"
  else
    "$bin" --protocol=TCP -h 127.0.0.1 -P "$MP_MYSQL_PORT" "$@"
  fi
}

# 判断"真的能连上"。只看 pidfile 会误判: mysqld 退出后 pid 可能被别的进程复用,
# 或者 pidfile 残留, 于是 start 时会以为"已在运行"而拒绝启动, 把库留成停着的状态。
# 所以只认 socket ping / TCP ping 这两个真实探活。
is_alive() {
  if [ -S "$MP_MYSQL_SOCKET" ] \
     && "$MYSQL_BIN_DIR/mysqladmin" --socket="$MP_MYSQL_SOCKET" -u root ping >/dev/null 2>&1; then
    return 0
  fi
  # socket 文件被系统清理 / 只在 TCP 上监听时, 用端口探测作为兜底
  "$MYSQL_BIN_DIR/mysqladmin" --protocol=TCP -h 127.0.0.1 -P "$MP_MYSQL_PORT" -u root ping >/dev/null 2>&1
}

# 等端口真正释放, 避免 restart 时 "刚停掉就以为还活着"
wait_stopped() {
  local seconds="${1:-15}" i
  for i in $(seq 1 "$seconds"); do
    is_alive || return 0
    sleep 1
  done
  return 1
}

datadir_ready() {
  [ -d "$MP_MYSQL_DATADIR/mysql" ]
}

init_datadir() {
  datadir_ready && return 0
  if [ -d "$MP_MYSQL_DATADIR" ] && [ -n "$(ls -A "$MP_MYSQL_DATADIR" 2>/dev/null)" ]; then
    die "数据目录 $MP_MYSQL_DATADIR 非空但不是有效的 MySQL 数据目录。
   请先备份后清空它, 或换路径:  MP_MYSQL_DATADIR=\$HOME/mysql80 bash scripts/mysql_local.sh start"
  fi
  if ! mkdir -p "$MP_MYSQL_DATADIR" 2>/dev/null; then
    die "无法创建 $MP_MYSQL_DATADIR (权限不足)。
   换个可写路径:  MP_MYSQL_DATADIR=\$HOME/mysql80 bash scripts/mysql_local.sh start"
  fi
  info "首次初始化数据目录 (root 无密码, 仅监听本机)"
  if ! "$MYSQL_BIN_DIR/mysqld" --no-defaults --initialize-insecure \
      --datadir="$MP_MYSQL_DATADIR" \
      --basedir="$BREW_PREFIX/opt/$MP_MYSQL_FORMULA" \
      --port="$MP_MYSQL_PORT" \
      --socket="$MP_MYSQL_SOCKET" \
      --log-error="$MP_MYSQL_ERRLOG" 2>&1; then
    warn "初始化失败, 日志最后 20 行:"
    tail -20 "$MP_MYSQL_ERRLOG" 2>/dev/null | sed 's/^/     /'
    die "请把上面的日志发出来定位"
  fi
  ok "数据目录就绪: $MP_MYSQL_DATADIR"
}

write_plist() {
  mkdir -p "$(dirname "$MP_MYSQL_PLIST")"
  cat > "$MP_MYSQL_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key>
	<string>$MP_MYSQL_LABEL</string>
	<key>ProgramArguments</key>
	<array>
		<string>$MYSQL_BIN_DIR/mysqld</string>
		<string>--no-defaults</string>
		<string>--basedir=$BREW_PREFIX/opt/$MP_MYSQL_FORMULA</string>
		<string>--datadir=$MP_MYSQL_DATADIR</string>
		<string>--port=$MP_MYSQL_PORT</string>
		<string>--socket=$MP_MYSQL_SOCKET</string>
		<string>--mysqlx-socket=$MP_MYSQLX_SOCKET</string>
		<string>--mysqlx-port=$MP_MYSQLX_PORT</string>
		<string>--pid-file=$MP_MYSQL_PIDFILE</string>
		<string>--log-error=$MP_MYSQL_ERRLOG</string>
	</array>
	<key>RunAtLoad</key>
	<true/>
	<key>KeepAlive</key>
	<true/>
	<key>ThrottleInterval</key>
	<integer>10</integer>
	<key>WorkingDirectory</key>
	<string>$MP_MYSQL_DATADIR</string>
</dict>
</plist>
PLIST
}

start_launchd() {
  write_plist
  launchctl bootout "gui/$(id -u)/$MP_MYSQL_LABEL" >/dev/null 2>&1 || true
  launchctl enable "gui/$(id -u)/$MP_MYSQL_LABEL" >/dev/null 2>&1 || true
  launchctl bootstrap "gui/$(id -u)" "$MP_MYSQL_PLIST" >/dev/null 2>&1
}

start_nohup() {
  rm -f "$MP_MYSQL_SOCKET" "$MP_MYSQLX_SOCKET" "$MP_MYSQL_SOCKET.lock" 2>/dev/null || true
  nohup "$MYSQL_BIN_DIR/mysqld" \
    --no-defaults \
    --basedir="$BREW_PREFIX/opt/$MP_MYSQL_FORMULA" \
    --datadir="$MP_MYSQL_DATADIR" \
    --port="$MP_MYSQL_PORT" \
    --socket="$MP_MYSQL_SOCKET" \
    --mysqlx-socket="$MP_MYSQLX_SOCKET" \
    --mysqlx-port="$MP_MYSQLX_PORT" \
    --pid-file="$MP_MYSQL_PIDFILE" \
    --log-error="$MP_MYSQL_ERRLOG" >/dev/null 2>&1 &
}

wait_ready() {
  local seconds="$1" i
  for i in $(seq 1 "$seconds"); do
    is_alive && return 0
    sleep 1
  done
  return 1
}

cmd_start() {
  if is_alive; then
    ok "MySQL 已在运行 (端口 $MP_MYSQL_PORT, socket $MP_MYSQL_SOCKET)"
    return 0
  fi
  init_datadir
  rm -f "$MP_MYSQL_SOCKET" "$MP_MYSQL_SOCKET.lock" 2>/dev/null || true

  info "启动 MySQL (优先开机自启 launchd, 失败则转后台进程)"
  if start_launchd && wait_ready 30; then
    ok "已启动并注册开机自启 (launchd: $MP_MYSQL_LABEL)"
    return 0
  fi

  warn "launchd 注册未成功 (常见于本机 launchd 状态异常), 改用后台进程启动"
  launchctl bootout "gui/$(id -u)/$MP_MYSQL_LABEL" >/dev/null 2>&1 || true
  rm -f "$MP_MYSQL_PLIST" 2>/dev/null || true
  start_nohup
  if wait_ready 30; then
    warn "已启动, 但重启电脑后需要重新执行: bash scripts/mysql_local.sh start"
    return 0
  fi

  warn "启动失败, 错误日志最后 25 行 ($MP_MYSQL_ERRLOG):"
  tail -25 "$MP_MYSQL_ERRLOG" 2>/dev/null | sed 's/^/     /'
  die "MySQL 未能启动"
}

cmd_stop() {
  local stopped="0"
  if launchctl print "gui/$(id -u)/$MP_MYSQL_LABEL" >/dev/null 2>&1; then
    launchctl bootout "gui/$(id -u)/$MP_MYSQL_LABEL" >/dev/null 2>&1 && stopped="1"
  fi
  if is_alive; then
    mysql_cli "$MYSQL_BIN_DIR/mysqladmin" -u root shutdown >/dev/null 2>&1 \
      && stopped="1"
  fi
  # mysqladmin 没停掉 (socket 丢失/权限问题) 就按 pid 兜底
  if [ "$stopped" != "1" ] && [ -f "$MP_MYSQL_PIDFILE" ]; then
    kill "$(cat "$MP_MYSQL_PIDFILE" 2>/dev/null)" >/dev/null 2>&1 && stopped="1"
  fi
  rm -f "$MP_MYSQL_SOCKET" "$MP_MYSQLX_SOCKET" "$MP_MYSQL_SOCKET.lock" 2>/dev/null || true
  rm -f "$MP_MYSQL_PLIST" 2>/dev/null || true
  if [ "$stopped" = "1" ]; then
    # 等端口真的释放, 否则紧接着 start 会撞端口
    if ! wait_stopped 15; then
      warn "进程还在退出中, 端口 $MP_MYSQL_PORT 仍被占用"
    fi
    ok "已停止"
  else
    warn "本来就没在运行"
  fi
}

cmd_status() {
  echo "数据目录 : $MP_MYSQL_DATADIR"
  echo "端口     : $MP_MYSQL_PORT"
  echo "socket   : $MP_MYSQL_SOCKET"
  echo "日志     : $MP_MYSQL_ERRLOG"
  echo "自启     : $MP_MYSQL_PLIST"
  echo -n "运行状态 : "
  if is_alive; then
    printf "\033[1;32m运行中\033[0m  "
    mysql_cli "$MYSQL_BIN_DIR/mysql" -u root -N -B \
      -e "SELECT CONCAT('版本 ', VERSION())" 2>/dev/null \
      || echo "已就绪 (TCP 端口 $MP_MYSQL_PORT)"
  else
    printf "\033[1;31m未运行\033[0m\n"
  fi
  echo -n "数据库   : "
  mysql_cli "$MYSQL_BIN_DIR/mysql" -u root -N -B \
    -e "SHOW DATABASES" 2>/dev/null | tr '\n' ' ' || true
  echo
}

cmd_destroy() {
  cmd_stop >/dev/null 2>&1 || true
  info "删除 $MP_MYSQL_DATADIR (只影响本项目实例)"
  rm -rf "$MP_MYSQL_DATADIR" 2>/dev/null || true
  ok "已删除, 下次 start 会重新初始化"
}

usage() {
  cat <<USAGE
项目专用 MySQL 实例 (端口 $MP_MYSQL_PORT, 数据目录 $MP_MYSQL_DATADIR)

用法:  bash scripts/mysql_local.sh <命令>

  start     启动 (首次会自动初始化数据目录, 并注册开机自启)
  stop      停止
  restart   重启
  status    查看状态 / 版本 / 已有数据库
  logs      跟踪错误日志 (Ctrl+C 退出)
  shell     用 root 连进去
  destroy   删除本实例的数据目录 (只影响本项目, 会二次确认)

常用入口:  make db-start / db-stop / db-status / db-logs / db-shell
项目全套启停:  bash scripts/service.sh   (交互式运维台)
USAGE
}

case "${1:-}" in
  start)   cmd_start ;;
  stop)    cmd_stop ;;
  restart) cmd_stop; cmd_start ;;
  status)  cmd_status ;;
  logs)    touch "$MP_MYSQL_ERRLOG"; tail -f "$MP_MYSQL_ERRLOG" ;;
  shell)
    # exec 会替换进程, 所以这里把参数算好再 exec
    if [ -S "$MP_MYSQL_SOCKET" ]; then
      exec "$MYSQL_BIN_DIR/mysql" --socket="$MP_MYSQL_SOCKET" -u root
    else
      warn "socket 不存在 (被系统清理过?), 改用 TCP 127.0.0.1:$MP_MYSQL_PORT"
      exec "$MYSQL_BIN_DIR/mysql" --protocol=TCP -h 127.0.0.1 -P "$MP_MYSQL_PORT" -u root
    fi
    ;;
  destroy)
    warn "这会删除 $MP_MYSQL_DATADIR 里所有数据 (只影响本项目, 不碰系统 MySQL)"
    printf "确认请输入 yes: "
    read -r answer
    [ "$answer" = "yes" ] || die "已取消"
    cmd_destroy
    ;;
  ""|-h|--help|help) usage ;;
  *) usage; echo; die "未知命令: $1" ;;
esac
