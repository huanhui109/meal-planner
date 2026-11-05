"""Live scoped CLI roundtrip using an explicitly named development test account."""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills/fandecide/scripts/fandecide.py"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:5173")
    parser.add_argument("--name", required=True, help="An isolated development verification account")
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("fandecide_cli", CLI)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    url = cli.origin(args.url)

    with httpx.Client(base_url=url, follow_redirects=False, trust_env=False, timeout=30) as client:
        login = client.post("/api/auth/dev-login", json={"name": args.name})
        login.raise_for_status()
        grant_response = client.post("/api/assistant/grants", json={"name": "CLI roundtrip verification"})
        grant_response.raise_for_status()
        grant = grant_response.json()["data"]
        try:
            with tempfile.TemporaryDirectory(prefix="fandecide-smoke-") as directory:
                path = Path(directory)
                config = path / "connection.json"
                cli.write_connection(config, {"url": url, "token": grant["token"]})
                command = [sys.executable, str(CLI), "--config", str(config)]
                result = subprocess.run(command + [
                    "context", "--slot", "dinner", "--mode", "cook", "--servings", "1",
                ], capture_output=True, text=True, check=True)
                context = json.loads(result.stdout)
                complete = [dish for dish in context["candidates"] if dish["role"] == "complete"]
                assert complete, "No complete meal candidates in this verification context"
                preferred = next((dish for dish in complete if dish["name"] in (
                    "番茄鸡蛋面", "西红柿鸡蛋挂面", "西红柿鸡蛋面",
                )), complete[0])
                proposal = path / "proposal.json"
                proposal.write_text(json.dumps({
                    "context": context["context"], "expected_revision": context["revision"],
                    "candidate_keys": [preferred["key"]], "reason": "按一人份安排，主食与配料一起准备。",
                }, ensure_ascii=False), encoding="utf-8")
                result = subprocess.run(command + ["save", "--file", str(proposal)], capture_output=True, text=True, check=True)
                saved = json.loads(result.stdout)
                current = client.get("/api/meals/current", params={"meal_slot": "dinner"})
                current.raise_for_status()
                assert current.json()["data"]["proposal"]["id"] == saved["proposal"]["id"]
                assert saved["proposal"]["source"] == "assistant"
                revoked = client.delete(f"/api/assistant/grants/{grant['id']}")
                revoked.raise_for_status()
                retry = subprocess.run(command + ["context"], capture_output=True, text=True)
                assert retry.returncode == 1 and "401" in retry.stderr
                print("PASS: CLI context -> validated save -> shared web proposal -> revoke -> 401")
                print(f"Verification meal: {saved['proposal']['title']}; status={saved['proposal']['status']}")
        finally:
            client.delete(f"/api/assistant/grants/{grant['id']}")


if __name__ == "__main__":
    main()
