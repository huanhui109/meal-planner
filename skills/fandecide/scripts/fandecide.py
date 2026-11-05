#!/usr/bin/env python3
"""Small scoped API client. Never sends credentials through redirects."""
from __future__ import annotations

import argparse
import getpass
import ipaddress
import json
import os
import stat
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_CONFIG = Path.home() / ".config" / "fandecide" / "connection.json"


class ClientError(Exception):
    pass


def origin(value: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(value)
        host = parsed.hostname or ""
        port = parsed.port
    except ValueError as exc:
        raise ClientError("Invalid service URL") from exc
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host == "localhost"
    if (
        parsed.scheme not in ("http", "https")
        or not host or parsed.username is not None or parsed.password is not None
        or parsed.query or parsed.fragment or parsed.path not in ("", "/")
        or (parsed.scheme == "http" and not loopback)
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise ClientError("Use an HTTPS origin, or HTTP on localhost/loopback only")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(connection: dict, endpoint: str, body: dict) -> dict:
    if endpoint not in ("context", "proposals"):
        raise ClientError("Unsupported assistant endpoint")
    token = connection.get("token", "")
    if not isinstance(token, str) or not token.startswith("fd_skill_") or len(token) > 100:
        raise ClientError("Invalid connection token; reconnect from the web app")
    try:
        encoded = json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
    except (ValueError, TypeError):
        raise ClientError("Request must contain valid finite JSON values") from None
    req = urllib.request.Request(
        f"{origin(connection['url'])}/api/assistant/{endpoint}",
        data=encoded,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    # Ignore ambient proxies: credentials belong to this explicitly configured origin.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(req, timeout=30) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise ClientError("401: Connection revoked or expired; reconnect in the web app") from None
        if exc.code == 409:
            raise ClientError("409: Meal changed. Read context again before saving; do not blindly retry") from None
        if 300 <= exc.code < 400:
            raise ClientError("Redirect refused; configure the final trusted service origin") from None
        try:
            error = json.loads(exc.read(8192)).get("detail", "")
        except (ValueError, AttributeError):
            error = ""
        raise ClientError(f"HTTP {exc.code}: {str(error)[:500]}".replace(token, "[redacted]")) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ClientError("Connection failed; check service availability. No automatic retry was made") from None
    except (ValueError, TypeError):
        raise ClientError("Service returned invalid JSON") from None
    if not isinstance(result, dict) or result.get("code") != 0 or not isinstance(result.get("data"), dict):
        raise ClientError("Unexpected service response")
    return result["data"]


def read_connection(path: Path) -> dict:
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise ClientError("Connection file must be a regular private file (mode 0600)")
        if hasattr(os, "getuid") and info.st_uid != os.getuid():
            raise ClientError("Connection file is not owned by the current user")
        result = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(result, dict):
            raise ValueError
        origin(result["url"])
        return result
    except (OSError, ValueError, KeyError):
        raise ClientError("Not connected. Create an assistant grant in the web app and run connect") from None


def write_connection(path: Path, connection: dict, replace: bool = False) -> None:
    if path.exists() or path.is_symlink():
        if not replace or path.is_symlink() or not path.is_file():
            raise ClientError("Connection already exists; use --replace explicitly to reconnect")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            temporary = handle.name
            os.chmod(temporary, 0o600)
            json.dump(connection, handle, ensure_ascii=False)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path: str) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (OSError, ValueError):
        raise ClientError("Expected a readable JSON object file") from None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Fandecide: read context and save meal suggestions only")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    commands = parser.add_subparsers(dest="command", required=True)
    connect = commands.add_parser("connect")
    connect.add_argument("--url", required=True)
    connect.add_argument("--replace", action="store_true")
    commands.add_parser("status")
    context = commands.add_parser("context")
    context.add_argument("--file")
    context.add_argument("--date")
    context.add_argument("--slot", choices=["breakfast", "lunch", "dinner", "late_night"])
    context.add_argument("--mode", choices=["auto", "cook", "takeout"])
    context.add_argument("--servings", type=int)
    save = commands.add_parser("save")
    save.add_argument("--file", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "connect":
            url = origin(args.url)
            if not sys.stdin.isatty():
                raise ClientError("Run connect in a trusted interactive terminal for hidden token input")
            token = getpass.getpass("Assistant token (hidden): ").strip()
            connection = {"url": url, "token": token}
            request(connection, "context", {})
            write_connection(args.config, connection, args.replace)
            print("Connected. Token stored privately; read/propose access only.")
            return 0
        connection = read_connection(args.config)
        if args.command == "status":
            print(json.dumps({"url": origin(connection["url"]), "configured": True}))
            return 0
        if args.command == "context":
            body = read_json(args.file) if args.file else {}
            for name, key in (("date", "meal_date"), ("slot", "meal_slot"), ("mode", "mode"), ("servings", "servings")):
                if getattr(args, name) is not None:
                    body[key] = getattr(args, name)
            result = request(connection, "context", body)
        else:
            body = read_json(args.file)
            if not {"context", "expected_revision", "candidate_keys"} <= body.keys():
                raise ClientError("Save requires context, expected_revision and candidate_keys from a fresh context read")
            result = request(connection, "proposals", body)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except ClientError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
