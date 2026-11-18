"""Explicit local browser checks. They do not authorize automation of job portals."""

import json
import tempfile
from contextlib import closing
from importlib.resources import as_file, files
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


def cdp_endpoint(value: str) -> str:
    try:
        url = urlsplit(value.strip())
        if (url.scheme != "http" or url.hostname not in ("127.0.0.1", "localhost", "::1")
                or not url.port or url.username or url.password or url.path not in ("", "/")
                or url.query or url.fragment):
            raise ValueError("Invalid endpoint")
        host = "[::1]" if url.hostname == "::1" else "127.0.0.1"
        return urlunsplit(("http", f"{host}:{url.port}", "", "", ""))
    except ValueError as exc:
        raise ValueError("Usa una conexión local como http://127.0.0.1:9222, sin usuario ni contraseña") from exc


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def probe_cdp(value: str) -> dict:
    endpoint = cdp_endpoint(value)
    try:
        opener = build_opener(ProxyHandler({}), NoRedirects())
        with opener.open(Request(endpoint + "/json/version", headers={"Accept": "application/json"}), timeout=3) as response:
            raw = response.read(65_537)
            if response.status != 200 or len(raw) > 65_536:
                raise ValueError("Invalid response")
        data = json.loads(raw)
        socket = urlsplit(data.get("webSocketDebuggerUrl", ""))
        origin = urlsplit(endpoint)
        if (socket.scheme != "ws" or socket.hostname not in (origin.hostname, "localhost")
                or socket.port != origin.port or not socket.path.startswith("/devtools/browser/")
                or socket.username or socket.password or not isinstance(data.get("Browser"), str)):
            raise ValueError("Invalid browser metadata")
    except (OSError, ValueError, AttributeError, TypeError) as exc:
        raise ValueError("No se pudo comprobar el navegador existente. Revisa que su conexión CDP local esté habilitada") from exc
    return {"status": "cdp_reachable", "scope": "local_connection_only"}


def probe_managed(interpreter: Path, root: Path) -> dict:
    """Exercise the existing Hermes sandbox transport using only temporary fictional data."""
    from pandapply.cv import render_cv
    from pandapply.discovery import JsonDiscovery, run_fixture
    from pandapply.memory import decide_skill, propose_skill
    from pandapply.profiles import add_profile
    from pandapply.sandbox_workflow import prepare, submit_with_hermes
    from pandapply.storage import connect, migrate

    with tempfile.TemporaryDirectory(prefix="pandapply-browser-check-") as temporary:
        directory = Path(temporary)
        database = directory / "data.db"
        migrate(database)
        with closing(connect(database)) as db:
            profile = add_profile(db, "Synthetic browser check", "UTC", {"must_have_skills": ["Node.js"]})
            decide_skill(db, propose_skill(db, profile, "Node.js"), approve=True)
            document = render_cv(db, profile, directory / "synthetic.pdf")
            with as_file(files("pandapply").joinpath("assets/jobs.synthetic.json")) as fixture:
                job = run_fixture(db, profile, JsonDiscovery(fixture), dry_run=False)[0]
            application = db.execute("SELECT id FROM applications WHERE profile_id=? AND job_posting_id=?",
                                     (profile, job["job_id"])).fetchone()[0]
            prepare(db, application, document)
            receipt = submit_with_hermes(db, application, directory / "sandbox.db", consent=True,
                                         interpreter=interpreter, hermes_root=root)
            if not receipt.startswith("sandbox-"):
                raise ValueError("No se pudo verificar el recibo de prueba del navegador")
    return {"status": "sandbox_verified", "scope": "synthetic_local_form_only"}
