"""Manage only PandApply's own loopback panel through a private control channel."""

import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener


def _record(database: Path) -> Path:
    return database.parent / "panel-control.json"


def _load(database: Path) -> dict | None:
    try:
        path = _record(database)
        if path.stat().st_size > 10_000:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(data, dict) or not isinstance(data.get("port"), int)
                or not 1 <= data["port"] <= 65535
                or not isinstance(data.get("control"), str) or not isinstance(data.get("instance"), str)):
            return None
        return data
    except (OSError, ValueError):
        return None


def _call(data: dict, action: str) -> dict | None:
    try:
        request = Request(f"http://127.0.0.1:{data['port']}/_panel/{action}",
                          headers={"Authorization": "Bearer " + data["control"]},
                          data=b"" if action == "stop" else None)
        # Ignore proxy environment variables; process control never leaves loopback.
        opener = build_opener(ProxyHandler({}))
        from pandapply.browser_checks import NoRedirects

        opener.add_handler(NoRedirects())
        with opener.open(request, timeout=0.5) as response:
            content = response.read(10_001)
            if len(content) > 10_000:
                return None
            result = json.loads(content)
        return result if isinstance(result, dict) and result.get("instance") == data["instance"] else None
    except (OSError, ValueError):
        return None


def status(database: Path) -> dict:
    data = _load(database)
    result = _call(data, "status") if data else None
    if not result:
        return {"status": "stopped"}
    return {"status": "running", "pid": result["pid"], "url": f"http://127.0.0.1:{data['port']}/login"}


def start(database: Path, *, port: int = 8765) -> dict:
    if not 1 <= port <= 65535:
        raise ValueError("El puerto debe estar entre 1 y 65535")
    current = status(database)
    if current["status"] == "running":
        return {**current, "already_running": True}
    password = secrets.token_urlsafe(24)
    data = {"instance": str(uuid.uuid4()), "control": secrets.token_urlsafe(32), "port": port}
    payload = {**data, "database": str(database.resolve(strict=True)), "password": password}
    log_path = database.parent / "panel.log"
    fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    process = None
    try:
        with os.fdopen(fd, "ab") as log:
            process = subprocess.Popen([sys.executable, "-m", "pandapply.panel_server"], stdin=subprocess.PIPE,
                                       stdout=log, stderr=log, **flags)
        # Login credentials travel over a pipe, never argv, environment or log files.
        process.stdin.write(json.dumps(payload).encode("utf-8"))
        process.stdin.close()
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise ValueError("El panel no pudo iniciar. Revisa si el puerto está ocupado y consulta panel.log")
            if _call(data, "status"):
                path = _record(database)
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as output:
                    temporary = Path(output.name)
                    json.dump(data, output)
                try:
                    os.replace(temporary, path)
                finally:
                    temporary.unlink(missing_ok=True)
                return {"status": "running", "pid": process.pid, "url": f"http://127.0.0.1:{port}/login",
                        "password": password, "already_running": False}
            time.sleep(0.1)
        raise ValueError("El panel no confirmó su inicio; consulta panel.log")
    except Exception:
        if process is not None and process.poll() is None:
            # This handle belongs to the child just created, never a PID read from disk.
            process.terminate()
            process.wait(timeout=5)
        raise


def stop(database: Path) -> dict:
    data = _load(database)
    if not data or not _call(data, "status"):
        return {"status": "stopped", "already_stopped": True}
    if not _call(data, "stop"):
        raise ValueError("No se pudo solicitar la detención del panel")
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if not _call(data, "status"):
            current = _load(database)
            if current and current["instance"] == data["instance"]:
                _record(database).unlink(missing_ok=True)
            return {"status": "stopped"}
        time.sleep(0.1)
    raise ValueError("Se solicitó detener el panel pero todavía no confirmó su cierre")
