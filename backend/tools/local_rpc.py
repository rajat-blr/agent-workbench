"""Authenticated loopback RPC helpers for local verification tools."""

import json
import re
import sqlite3
import subprocess
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from tools.eval_baselines import ROOT

CHAT_COUNT_QUERIES = {
    "sessions": "SELECT count(*) FROM sessions",
    "messages": "SELECT count(*) FROM messages",
    "runs": "SELECT count(*) FROM runs",
}


def read_chat_counts(source: sqlite3.Connection) -> dict[str, int]:
    return {
        table: source.execute(query).fetchone()[0]
        for table, query in CHAT_COUNT_QUERIES.items()
    }


class NoBackendRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        raise ValueError("Local backend redirects are not allowed")


def connection_for_process(pid: int, database: Path) -> tuple[str, str]:
    files = subprocess.run(
        ["lsof", "-p", str(pid), "-Fn"], check=True, capture_output=True, text=True
    ).stdout
    if f"n{database}\n" not in files:
        raise ValueError(
            "The selected backend does not have the expected database open"
        )
    # Never print the process environment or persist its authentication token.
    environment = subprocess.run(
        ["ps", "eww", "-p", str(pid), "-o", "command="],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if str(ROOT / "backend/main.py") not in environment:
        raise ValueError("Selected process is not this source-build app backend")
    token = re.search(r"(?:^|\s)LOCAL_AUTH_TOKEN=([^\s]+)", environment)
    port = re.search(r"(?:^|\s)PORT=(\d+)(?:\s|$)", environment)
    if not token or not port:
        raise ValueError("Could not locate backend connection settings")
    return f"http://127.0.0.1:{int(port[1])}", token[1]


class Rpc:
    def __init__(self, url: str, token: str) -> None:
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or (parsed.port is not None and not 1 <= parsed.port <= 65535)
        ):
            raise ValueError("RPC URL must be an HTTP(S) loopback backend origin")
        self.url, self.token = url.rstrip("/"), token
        # Never send the backend token through ambient proxies or redirects.
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoBackendRedirects()
        )

    def __call__(self, method: str, params: dict | None = None):
        request = urllib.request.Request(  # noqa: S310 - constructor restricts origins; opener blocks redirects/proxies.
            self.url + "/rpc",
            data=json.dumps(
                {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
            ).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}",
            },
        )
        with self.opener.open(request, timeout=240) as response:
            result = json.load(response)
        if "error" in result:
            raise RuntimeError(f"{method}: {result['error']['message']}")
        return result["result"]
