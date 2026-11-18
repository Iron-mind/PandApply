"""Real browser login regression: legacy referrer policy fails, fixed policy succeeds.

Run in the offline disposable Hermes container with no user profile or credentials.
"""

import json
import socket
import tempfile
import threading
import time
from pathlib import Path

import uvicorn
from tools.browser_use_cli import browser_exec, stop_harness_daemons

from pandapply.storage import migrate
from pandapply.web import create_app


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="pandapply-login-smoke-") as temporary:
        database = Path(temporary) / "data.db"
        migrate(database)
        app = create_app(database, "synthetic-password")
        state = {"legacy": True}
        origins = []

        @app.middleware("http")
        async def observe(request, call_next):
            if request.method == "POST" and request.url.path == "/login":
                origins.append(request.headers.get("origin"))
            response = await call_next(request)
            if state["legacy"]:
                response.headers["Referrer-Policy"] = "no-referrer"
            return response

        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        if not server.started:
            raise RuntimeError("Local test server did not start")
        url = f"http://127.0.0.1:{port}/login"

        def submit():
            code = (f"new_tab({url!r})\nwait_for_load()\n"
                    "fill_input('input[name=username]', 'pandapply')\n"
                    "fill_input('input[name=password]', 'synthetic-password')\n"
                    "js(\"setTimeout(() => document.querySelector('form').requestSubmit(), 100); 'submitted'\")\n"
                    "import time\ntime.sleep(1)\nwait_for_load()\nprint(js('document.body.innerText'))\n")
            result = browser_exec(code, session="pandapply-login", timeout_s=60)
            result = json.loads(result) if isinstance(result, str) else result
            if not result.get("success"):
                raise RuntimeError("Test browser failed")
            return result.get("output", "")

        try:
            legacy_output = submit()
            assert origins[-1] == "null", origins
            assert "Cerrar sesión" not in legacy_output
            state["legacy"] = False
            fixed_output = submit()
            assert origins[-1] == f"http://127.0.0.1:{port}", origins
            assert "Cerrar sesión" in fixed_output, fixed_output[:500]
            print(json.dumps({"legacy_origin": "null", "fixed_login": "passed", "browser": "Chromium via Hermes"}))
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            stop_harness_daemons()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
