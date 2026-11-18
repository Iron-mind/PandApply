"""Offline browser check of the redesigned panel with synthetic profiles only."""

import json
import socket
import tempfile
import threading
import time
from pathlib import Path

import uvicorn
from tools.browser_use_cli import browser_exec, stop_harness_daemons

from pandapply.profiles import add_profile
from pandapply.storage import connect, migrate
from pandapply.web import create_app


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="pandapply-panel-") as temporary:
        database = Path(temporary) / "data.db"
        migrate(database)
        with connect(database) as db:
            add_profile(db, "Desarrollo Backend", "UTC-5", {"work_mode": ["remote", "hybrid"],
                        "salary_min_usd_month": 2500, "must_have_skills": ["Python", "FastAPI", "PostgreSQL", "Docker", "Git"]})
            add_profile(db, "Desarrollo Fullstack", "UTC", {"work_mode": "remote", "must_have_skills": ["TypeScript", "React", "Node.js"]})
            add_profile(db, "QA e ingeniería de calidad", "UTC", {"work_mode": "any"})
        app = create_app(database, "synthetic-password")
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
            raise RuntimeError("Local panel did not start")
        url = f"http://127.0.0.1:{port}"
        artifacts = "/artifacts" if Path("/artifacts").is_dir() else "/tmp"
        code = (f"new_tab({(url + '/login')!r})\nwait_for_load()\n"
                "fill_input('input[name=username]', 'pandapply')\n"
                "fill_input('input[name=password]', 'synthetic-password')\n"
                "js(\"setTimeout(() => document.querySelector('form').requestSubmit(), 100); 'submit'\")\n"
                "import time, base64\nfrom pathlib import Path\ntime.sleep(1)\nwait_for_load()\n"
                "cdp('Emulation.setDeviceMetricsOverride', width=1440, height=1100, deviceScaleFactor=1, mobile=False)\n"
                "time.sleep(0.5)\n"
                "assert js(\"document.querySelector('.view.active h1').textContent\").startswith('Tu búsqueda')\n"
                f"Path({(artifacts + '/panel-desktop.png')!r}).write_bytes(base64.b64decode(cdp('Page.captureScreenshot', format='png')['data']))\n"
                "js(\"document.querySelectorAll('nav a')[1].click(); 'clicked'\")\ntime.sleep(0.5)\nwait_for_load()\n"
                "assert js(\"document.querySelector('.view.active h1').textContent\") == 'Perfiles profesionales'\n"
                "fill_input('input[name=name]', 'Perfil nuevo de prueba')\n"
                "js(\"setTimeout(() => document.querySelector('form[action=\\\"/profiles\\\"]').requestSubmit(), 100); 'submit'\")\n"
                "for _ in range(50):\n"
                " time.sleep(0.1)\n"
                " if 'Perfil nuevo de prueba' in js(\"document.querySelector('.view.active').innerText\"): break\n"
                "assert 'Perfil nuevo de prueba' in js(\"document.querySelector('.view.active').innerText\"), js('document.body.innerText')\n"
                "js(\"document.querySelector('.view.active .profile-editor').open = true; 'opened'\")\n"
                "fill_input('.view.active input[name=work_mode]', 'remote, hybrid')\n"
                "fill_input('.view.active input[name=skills]', 'Python')\n"
                "js(\"setTimeout(() => document.querySelector('.view.active form[action$=\\\"/preferences\\\"]').requestSubmit(), 100); 'submit'\")\n"
                "for _ in range(50):\n"
                " time.sleep(0.1)\n"
                " if 'Remoto, Híbrido' in js(\"document.querySelector('.view.active .mini-info').innerText\"): break\n"
                "assert 'Remoto, Híbrido' in js(\"document.querySelector('.view.active .mini-info').innerText\")\n"
                "js(\"document.querySelector('.view.active .danger-link').click(); 'clicked'\")\n"
                "time.sleep(0.5)\nwait_for_load()\n"
                "js(\"document.querySelector('input[name=confirmation]').click(); 'confirmed'\")\n"
                "js(\"setTimeout(() => document.querySelector('form').requestSubmit(), 100); 'submit'\")\n"
                "for _ in range(50):\n"
                " time.sleep(0.1)\n"
                " if js(\"!!document.querySelector('.view.active .profile-list')\"): break\n"
                "assert 'Perfil nuevo de prueba' not in js(\"document.querySelector('.view.active .profile-list').innerText\")\n"
                "cdp('Emulation.setDeviceMetricsOverride', width=390, height=844, deviceScaleFactor=1, mobile=True)\n"
                "time.sleep(0.5)\n"
                "assert js('document.documentElement.scrollWidth <= window.innerWidth')\n"
                f"Path({(artifacts + '/panel-mobile.png')!r}).write_bytes(base64.b64decode(cdp('Page.captureScreenshot', format='png')['data']))\n"
                "print('PANEL_CHECK_PASSED')\n")
        try:
            result = browser_exec(code, session="pandapply-panel", timeout_s=90)
            result = json.loads(result) if isinstance(result, str) else result
            if not result.get("success") or "PANEL_CHECK_PASSED" not in result.get("output", ""):
                raise RuntimeError(str(result)[:4000])
            with connect(database) as db:
                assert db.execute("SELECT count(*) FROM professional_profiles").fetchone()[0] == 4
                profile = db.execute("SELECT active,preferences_json FROM professional_profiles WHERE name='Perfil nuevo de prueba'").fetchone()
                assert profile["active"] == 0 and json.loads(profile["preferences_json"])["work_mode"] == ["remote", "hybrid"]
            print(json.dumps({"panel": "passed", "navigation": "passed", "create_edit_delete_profile": "passed", "mobile": "passed"}))
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            stop_harness_daemons()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
