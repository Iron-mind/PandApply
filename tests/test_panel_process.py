import json
import socket
import subprocess
import sys
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener

import pytest

from pandapply.panel_process import start, status, stop
from pandapply.storage import migrate


def test_background_panel_survives_launcher_and_can_be_stopped_safely(tmp_path):
    database = tmp_path / "data.db"
    migrate(database)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    script = ("import sys,json; from pathlib import Path; from pandapply.panel_process import start; "
              "print(json.dumps(start(Path(sys.argv[1]),port=int(sys.argv[2]))))")
    try:
        launched = subprocess.run([sys.executable, "-c", script, str(database), str(port)], capture_output=True,
                                  text=True, check=True, timeout=25)
        result = json.loads(launched.stdout)
        assert status(database)["status"] == "running"
        assert start(database, port=port)["already_running"]
        assert result["password"] not in (tmp_path / "panel-control.json").read_text(encoding="utf-8")
        assert result["password"] not in (tmp_path / "panel.log").read_text(encoding="utf-8")
        opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))
        with opener.open(result["url"], timeout=3) as response:
            page = response.read().decode()
        import re

        csrf = re.search(r"name='csrf' value='([^']+)'", page).group(1)
        origin = f"http://127.0.0.1:{port}"
        request = Request(result["url"], data=urlencode({"username": "pandapply", "password": result["password"],
                          "csrf": csrf}).encode(), headers={"Origin": origin})
        with opener.open(request, timeout=3) as response:
            assert "Cerrar sesión" in response.read().decode()
        with pytest.raises(HTTPError) as forbidden:
            opener.open(Request(origin + "/_panel/stop", data=b""), timeout=3)
        assert forbidden.value.code == 403 and status(database)["status"] == "running"
        assert stop(database)["status"] == "stopped"
        assert status(database)["status"] == "stopped"
    finally:
        stop(database)
