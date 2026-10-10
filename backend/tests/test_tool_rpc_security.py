import io
import json
import sqlite3
import urllib.request

import pytest

from tools.local_rpc import NoBackendRedirects, Rpc, read_chat_counts


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/state.db",
        "https://example.com",
        "http://127.0.0.1.example.com",
        "http://user:password@127.0.0.1",
        "http://127.0.0.1/rpc",
        "http://127.0.0.1?token=secret",
        "http://localhost#fragment",
        "http://127.0.0.1:0",
        "http://127.0.0.1:70000",
    ],
)
def test_rpc_rejects_non_loopback_or_ambiguous_origins(url):
    with pytest.raises(ValueError):
        Rpc(url, "fixture-token")


def test_rpc_normalizes_allowed_origins_and_blocks_proxies_and_redirects(monkeypatch):
    calls = []

    class Opener:
        def open(self, request, timeout):
            calls.append((request, timeout))
            return io.BytesIO(json.dumps({"result": {"status": "ok"}}).encode())

    def build(*handlers):
        assert any(
            isinstance(handler, urllib.request.ProxyHandler) and handler.proxies == {}
            for handler in handlers
        )
        redirect = next(
            handler for handler in handlers if isinstance(handler, NoBackendRedirects)
        )
        with pytest.raises(ValueError, match="redirects"):
            redirect.redirect_request(
                None, None, 302, "Redirect", {}, "https://example.com"
            )
        return Opener()

    monkeypatch.setattr(urllib.request, "build_opener", build)
    for origin in ("http://127.0.0.1:8123/", "https://localhost", "http://[::1]:8123"):
        rpc = Rpc(origin, "fixture-token")
        assert rpc("health.check") == {"status": "ok"}
        request, timeout = calls[-1]
        assert request.full_url == origin.rstrip("/") + "/rpc"
        assert request.get_header("Authorization") == "Bearer fixture-token"
        assert json.loads(request.data)["method"] == "health.check"
        assert timeout == 240


def test_chat_counts_use_static_queries_and_preserve_the_import_evidence_shape():
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE sessions (id INTEGER)")
        db.execute("CREATE TABLE messages (id INTEGER)")
        db.execute("CREATE TABLE runs (id INTEGER)")
        db.execute("INSERT INTO sessions VALUES (1)")
        assert read_chat_counts(db) == {"sessions": 1, "messages": 0, "runs": 0}
