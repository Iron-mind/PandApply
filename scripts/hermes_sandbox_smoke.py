"""Optional isolated smoke test of Hermes browser against PandApply's fake ATS.

Run only inside a disposable Hermes container with `--network none`, the repo mounted
read-only and no user credentials or real browser profile. This does not test a real
employment portal or authorize browser automation elsewhere.
"""

import json
import socket
import tempfile
import threading
import time
from pathlib import Path

import uvicorn
from tools.browser_use_cli import browser_exec, stop_harness_daemons

from pandapply.sandbox import create_sandbox


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="pandapply-hermes-smoke-") as temp:
        app = create_sandbox(Path(temp) / "sandbox.db")
        cv_path = Path(temp) / "synthetic.pdf"
        cv_path.write_bytes(b"%PDF-1.4 synthetic")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        if not server.started:
            raise RuntimeError("Sandbox did not start")
        url = f"http://127.0.0.1:{port}/"
        code = ("# Submit a fictional application to the local sandbox\n"
                f"new_tab({url!r})\nwait_for_load()\n"
                "print(js(\"document.querySelector('h1').textContent\"))\n"
                "fill_input('input[name=idempotency_key]', 'hermes-smoke-1')\n"
                "fill_input('input[name=name]', 'Example Candidate')\n"
                "fill_input('input[name=email]', 'candidate@example.test')\n"
                "root = cdp('DOM.getDocument')\n"
                "file_node = cdp('DOM.querySelector', nodeId=root['root']['nodeId'], "
                "selector='input[name=cv]')['nodeId']\n"
                f"cdp('DOM.setFileInputFiles', nodeId=file_node, files=[{str(cv_path)!r}])\n"
                "js(\"setTimeout(() => document.querySelector('form').requestSubmit(), 100); 'submitted'\")\n"
                "import time\ntime.sleep(1)\nwait_for_load()\nprint(js('document.body.innerText'))\n")
        try:
            result = browser_exec(code, session="pandapply-smoke", timeout_s=90)
            parsed = json.loads(result) if isinstance(result, str) else result
            output = parsed.get("output", "") if isinstance(parsed, dict) else ""
            if not parsed.get("success") or "ATS de prueba" not in output or "sandbox-" not in output:
                raise RuntimeError("Hermes browser did not complete the sandbox smoke test: " + str(parsed)[:5000])
            print(json.dumps({"success": True, "mode": "local-sandbox", "browser": "Hermes browser_exec"}))
            return 0
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            stop_harness_daemons()


if __name__ == "__main__":
    raise SystemExit(main())
