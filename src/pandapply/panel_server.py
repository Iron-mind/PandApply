"""Private background entry point; all process secrets arrive on stdin."""

import json
import os
import secrets
import sys
from pathlib import Path

import uvicorn
from fastapi import HTTPException, Request

from pandapply.web import create_app


def main() -> int:
    if sys.prefix == sys.base_prefix:
        return 1
    payload = json.load(sys.stdin)
    app = create_app(Path(payload["database"]), payload["password"])
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=payload["port"], log_level="warning", access_log=False))

    def check(request: Request) -> None:
        supplied = request.headers.get("authorization", "")
        if (request.headers.get("origin") or not secrets.compare_digest(
                supplied.encode(), ("Bearer " + payload["control"]).encode())):
            raise HTTPException(status_code=403)

    @app.get("/_panel/status")
    def state(request: Request):
        check(request)
        return {"instance": payload["instance"], "pid": os.getpid()}

    @app.post("/_panel/stop")
    def shutdown(request: Request):
        check(request)
        server.should_exit = True
        return {"instance": payload["instance"], "status": "stopping"}

    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
