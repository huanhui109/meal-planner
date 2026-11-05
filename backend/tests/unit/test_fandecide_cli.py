from __future__ import annotations

import importlib.util
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[3] / "skills/fandecide/scripts/fandecide.py"
spec = importlib.util.spec_from_file_location("fandecide", MODULE)
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


@pytest.mark.parametrize("url", [
    "http://example.com", "https://name:secret@example.com", "https://example.com/api",
    "https://example.com?token=abc", "file:///tmp/x", "http://localhost.evil.com",
])
def test_rejects_untrusted_origins(url):
    with pytest.raises(cli.ClientError):
        cli.origin(url)


def test_config_is_private_and_status_does_not_show_token(tmp_path, capsys):
    path = tmp_path / "connection.json"
    cli.write_connection(path, {"url": "http://localhost:8000", "token": "fd_skill_test"})
    assert os.stat(path).st_mode & 0o777 == 0o600
    assert cli.main(["--config", str(path), "status"]) == 0
    assert "fd_skill_" not in capsys.readouterr().out
    with pytest.raises(cli.ClientError):
        cli.write_connection(path, {})
    path.chmod(0o644)
    with pytest.raises(cli.ClientError):
        cli.read_connection(path)


def test_redirects_cannot_forward_credentials():
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            calls.append(self.path)
            self.send_response(307)
            self.send_header("Location", "/leak")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with pytest.raises(cli.ClientError, match="Redirect refused"):
            cli.request({"url": f"http://127.0.0.1:{server.server_port}", "token": "fd_skill_test"}, "context", {})
        assert calls == ["/api/assistant/context"]
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


def test_save_requires_revision_and_real_context(tmp_path, capsys):
    config = tmp_path / "connection.json"
    cli.write_connection(config, {"url": "http://localhost:8000", "token": "fd_skill_test"})
    payload = tmp_path / "proposal.json"
    payload.write_text(json.dumps({"candidate_keys": ["made-up"]}))
    assert cli.main(["--config", str(config), "save", "--file", str(payload)]) == 1
    assert "expected_revision" in capsys.readouterr().err
