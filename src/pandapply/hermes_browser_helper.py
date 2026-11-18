"""Hermes browser adapter restricted to a disposable loopback ATS sandbox."""

import hashlib
import json
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit


def main() -> int:
    try:
        request = json.load(sys.stdin)
        endpoint = urlsplit(request["url"])
        if (endpoint.scheme != "http" or endpoint.hostname != "127.0.0.1" or not endpoint.port
                or endpoint.path != "/" or endpoint.query or endpoint.fragment or endpoint.username or endpoint.password):
            raise ValueError("Only an exact local sandbox endpoint is supported")
        if str(uuid.UUID(request["attempt_id"])) != request["attempt_id"]:
            raise ValueError("Invalid attempt ID")
        root = Path(request["sandbox_dir"]).resolve(strict=True)
        cv = Path(request["pdf_path"]).resolve(strict=True)
        if not cv.is_relative_to(root) or cv.name != "cv.pdf" or not cv.is_file():
            raise ValueError("CV must be the isolated sandbox copy")
        content = cv.read_bytes()
        if len(content) > 2_000_000 or hashlib.sha256(content).hexdigest() != request["pdf_sha256"]:
            raise ValueError("Sandbox CV changed")
        from tools.browser_use_cli import browser_exec, stop_harness_daemons

        code = ("# Submit a fictional application to the local sandbox\n"
                f"new_tab({request['url']!r})\nwait_for_load()\n"
                f"fill_input('input[name=idempotency_key]', {request['attempt_id']!r})\n"
                "fill_input('input[name=name]', 'Example Candidate')\n"
                "fill_input('input[name=email]', 'candidate@example.test')\n"
                "root = cdp('DOM.getDocument')\n"
                "node = cdp('DOM.querySelector', nodeId=root['root']['nodeId'], selector='input[name=cv]')['nodeId']\n"
                f"cdp('DOM.setFileInputFiles', nodeId=node, files=[{str(cv)!r}])\n"
                "js(\"setTimeout(() => document.querySelector('form').requestSubmit(), 100); 'submitted'\")\n"
                "import json, time\n"
                "for _ in range(30):\n"
                " time.sleep(0.5)\n"
                " text = js('document.body.innerText')\n"
                " try:\n"
                "  receipt = json.loads(text)\n"
                "  if receipt.get('sandbox') and receipt.get('receipt', '').startswith('sandbox-'):\n"
                "   print('PANDAPPLY_RECEIPT=' + receipt['receipt']); break\n"
                " except (ValueError, AttributeError): pass\n")
        try:
            result = browser_exec(code, session="pandapply-sandbox", timeout_s=90)
            result = json.loads(result) if isinstance(result, str) else result
            output = result.get("output", "") if isinstance(result, dict) else ""
            receipts = [line.removeprefix("PANDAPPLY_RECEIPT=") for line in output.splitlines()
                        if line.startswith("PANDAPPLY_RECEIPT=")]
            if not result.get("success") or len(receipts) != 1:
                raise ValueError("Browser did not return a sandbox receipt")
            print(json.dumps({"receipt": receipts[0]}))
            return 0
        finally:
            stop_harness_daemons()
    except Exception:  # noqa: BLE001 - avoid leaking browser output or private filesystem data
        print("Hermes sandbox browser could not complete the submission", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
