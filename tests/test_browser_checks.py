import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from pandapply.browser_checks import cdp_endpoint, probe_cdp
from pandapply.configuration import read_settings
from pandapply.onboarding import configure_browser
from pandapply.storage import connect, migrate


@pytest.mark.parametrize(("entered", "normalized"), [
    ("127.0.0.1:54723", "http://127.0.0.1:54723"),
    (" localhost:54723 ", "http://127.0.0.1:54723"),
    ("http://127.0.0.1:54723/", "http://127.0.0.1:54723"),
    ("[::1]:54723", "http://[::1]:54723"),
    ("//127.0.0.1:54723", "http://127.0.0.1:54723"),
])
def test_local_cdp_address_can_omit_http(entered, normalized):
    assert cdp_endpoint(entered) == normalized


@contextmanager
def local_browser(*, redirect=False):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            if redirect:
                self.send_response(302)
                self.send_header("Location", "http://192.0.2.1:9222/json/version")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"Browser": "Synthetic Chrome", "webSocketDebuggerUrl":
                f"ws://127.0.0.1:{self.server.server_port}/devtools/browser/synthetic"}).encode())

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_cdp_probe_reads_only_local_version_and_never_follows_redirects():
    with local_browser() as (endpoint, requests):
        assert probe_cdp(endpoint.removeprefix("http://"))["status"] == "cdp_reachable"
        assert requests == ["/json/version"]
    with local_browser(redirect=True) as (endpoint, requests):
        with pytest.raises(ValueError, match="comprobar"):
            probe_cdp(endpoint)
        assert requests == ["/json/version"]
    for endpoint in ("https://example.com:9222", "http://192.0.2.1:9222", "file:///tmp/browser",
                     "http://user:password@127.0.0.1:9222", "http://127.0.0.1:9222/arbitrary",
                     "192.0.2.1:9222", "user:password@127.0.0.1:9222", "127.0.0.1:65536"):
        with pytest.raises(ValueError):
            cdp_endpoint(endpoint)


def test_browser_setup_persists_selection_and_precise_check_scope(tmp_path, monkeypatch):
    path = tmp_path / "data.db"
    migrate(path)
    with local_browser() as (endpoint, _):
        replies = iter(["2", endpoint.removeprefix("http://"), "s"])
        monkeypatch.setattr("builtins.input", lambda prompt: next(replies))
        with connect(path) as db:
            configure_browser(db, tmp_path / "config.json")
            settings = read_settings(db, tmp_path / "config.json")
            assert settings.browser_mode == "cdp" and settings.browser_cdp_endpoint == endpoint
            assert not settings.auto_apply_enabled
            assert db.execute("SELECT state FROM connector_health WHERE connector_id='browser'").fetchone()[0] == "cdp_reachable"
            replies = iter(["1", "n"])
            configure_browser(db, tmp_path / "config.json")
            assert db.execute("SELECT state FROM connector_health WHERE connector_id='browser'").fetchone()[0] == "not_checked"
