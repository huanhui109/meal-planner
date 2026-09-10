"""MySQL 备份脚本 - mysqldump + 保留最近 N 天

用法:
  python scripts/backup_db.py                 # 备份到 ./backups
  BACKUP_DIR=/var/backups/meal python scripts/backup_db.py
环境变量:
  APP__DATABASE__URL   数据库连接串 (从中解析库名/账号/主机)
  BACKUP_DIR           备份目录, 默认 ./backups
  BACKUP_KEEP_DAYS     保留天数, 默认 14
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import unquote, urlparse

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("backup")

DEFAULT_KEEP_DAYS = 14


def parse_database_url(url: str) -> dict:
    """mysql+asyncmy://user:pass@host:3306/db?charset=utf8mb4 -> 连接参数"""
    parsed = urlparse(url)
    return {
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "host": parsed.hostname or "127.0.0.1",
        "port": str(parsed.port or 3306),
        "database": (parsed.path or "/").lstrip("/"),
    }


def main() -> int:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
    from app.config import get_settings

    settings = get_settings()
    conn = parse_database_url(settings.database.url)
    if not conn["database"]:
        logger.error("无法从 APP__DATABASE__URL 解析出数据库名")
        return 1

    backup_dir = Path(os.getenv("BACKUP_DIR", "backups"))
    keep_days = int(os.getenv("BACKUP_KEEP_DAYS", DEFAULT_KEEP_DAYS))
    backup_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backup_dir / f"{conn['database']}-{stamp}.sql"
    command = [
        "mysqldump",
        f"--host={conn['host']}",
        f"--port={conn['port']}",
        f"--user={conn['user']}",
        "--single-transaction",
        "--routines",
        "--default-character-set=utf8mb4",
        conn["database"],
    ]
    logger.info("开始备份 %s -> %s", conn["database"], target)
    with open(target, "w", encoding="utf-8") as handle:
        env = dict(os.environ)
        if conn["password"]:
            env["MYSQL_PWD"] = conn["password"]
        result = subprocess.run(command, stdout=handle, stderr=subprocess.PIPE, env=env, text=True)
    if result.returncode != 0:
        logger.error("备份失败: %s", result.stderr.strip())
        target.unlink(missing_ok=True)
        return result.returncode

    cutoff = datetime.now() - timedelta(days=keep_days)
    removed = 0
    for old in backup_dir.glob("*.sql"):
        if datetime.fromtimestamp(old.stat().st_mtime) < cutoff:
            old.unlink()
            removed += 1
    logger.info("备份完成: %s (清理 %s 个过期备份)", target, removed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
