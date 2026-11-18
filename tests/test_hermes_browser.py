import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from pandapply.cv import render_cv
from pandapply.discovery import JsonDiscovery, run_fixture
from pandapply.hermes_browser import HermesSandboxBrowser
from pandapply.memory import decide_skill, propose_skill
from pandapply.profiles import add_profile
from pandapply.sandbox_workflow import prepare, reconcile, submit_with_hermes
from pandapply.storage import connect, migrate
from pandapply.submission import SubmissionBlocked


def setup_application(db, tmp_path):
    profile = add_profile(db, "Backend", "UTC", {"must_have_skills": ["Node.js"]})
    decision = propose_skill(db, profile, "Node.js")
    decide_skill(db, decision, approve=True)
    document = render_cv(db, profile, tmp_path / "synthetic.pdf")
    fixture = Path(__file__).resolve().parents[1] / "fixtures/jobs.synthetic.json"
    job = run_fixture(db, profile, JsonDiscovery(fixture), dry_run=False)[0]["job_id"]
    app = db.execute("SELECT id FROM applications WHERE profile_id=? AND job_posting_id=?", (profile, job)).fetchone()[0]
    prepare(db, app, document)
    return app


def fake_browser_run(*, wrong_receipt=False):
    def run(command, *, input, env, **kwargs):
        request = json.loads(input)
        assert request["url"].startswith("http://127.0.0.1:")
        assert "GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE" not in env
        assert Path(env["HERMES_HOME"]).is_relative_to(Path(request["sandbox_dir"]))
        form = httpx.get(request["url"])
        token = re.search(r"name='sandbox_token' value='([^']+)'", form.text).group(1)
        data = {"idempotency_key": request["attempt_id"], "name": "Example Candidate",
                "email": "candidate@example.test", "sandbox_token": token}
        pdf = Path(request["pdf_path"]).read_bytes()
        result = httpx.post(request["url"] + "submit", data=data, files={"cv": ("cv.pdf", pdf, "application/pdf")})
        assert result.status_code == 200
        receipt = "sandbox-00000000-0000-0000-0000-000000000000" if wrong_receipt else result.json()["receipt"]
        return SimpleNamespace(returncode=0, stdout=json.dumps({"receipt": receipt}))
    return run


def test_hermes_browser_workflow_records_attempt_and_checks_receipt(tmp_path, monkeypatch):
    path = tmp_path / "app.db"
    migrate(path)
    root = tmp_path / "hermes"
    (root / "tools").mkdir(parents=True)
    (root / "tools/browser_use_cli.py").write_text("# fake", encoding="utf-8")
    monkeypatch.setattr("pandapply.hermes_browser.subprocess.run", fake_browser_run())
    monkeypatch.setenv("GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE", "do-not-inherit")
    with connect(path) as db:
        app = setup_application(db, tmp_path)
        with pytest.raises(SubmissionBlocked, match="consent"):
            submit_with_hermes(db, app, tmp_path / "ats.db", consent=False, interpreter=Path(sys.executable), hermes_root=root)
        receipt = submit_with_hermes(db, app, tmp_path / "ats.db", consent=True,
                                     interpreter=Path(sys.executable), hermes_root=root)
        assert receipt.startswith("sandbox-")
        assert db.execute("SELECT status FROM applications WHERE id=?", (app,)).fetchone()[0] == "SUBMITTED"
        assert db.execute("SELECT count(*) FROM submission_attempts WHERE attempt_status='CONFIRMED'").fetchone()[0] == 1


def test_unverifiable_browser_receipt_never_causes_resubmission(tmp_path, monkeypatch):
    path = tmp_path / "app.db"
    migrate(path)
    root = tmp_path / "hermes"
    (root / "tools").mkdir(parents=True)
    (root / "tools/browser_use_cli.py").write_text("# fake", encoding="utf-8")
    monkeypatch.setattr("pandapply.hermes_browser.subprocess.run", fake_browser_run(wrong_receipt=True))
    with connect(path) as db:
        app = setup_application(db, tmp_path)
        with pytest.raises(SubmissionBlocked, match="could not be verified"):
            submit_with_hermes(db, app, tmp_path / "ats.db", consent=True,
                               interpreter=Path(sys.executable), hermes_root=root)
        assert db.execute("SELECT status FROM applications WHERE id=?", (app,)).fetchone()[0] == "SUBMISSION_UNKNOWN"
        with pytest.raises(SubmissionBlocked):
            submit_with_hermes(db, app, tmp_path / "ats.db", consent=True,
                               interpreter=Path(sys.executable), hermes_root=root)
        assert reconcile(db, app, tmp_path / "ats.db").startswith("sandbox-")
        assert db.execute("SELECT count(*) FROM submission_attempts").fetchone()[0] == 1


def test_browser_interpreter_symlink_is_not_resolved_outside_venv(tmp_path):
    link = tmp_path / "python"
    try:
        link.symlink_to(Path(sys.executable))
    except OSError:
        pytest.skip("Creating symlinks requires system permission")
    root = tmp_path / "hermes"
    (root / "tools").mkdir(parents=True)
    (root / "tools/browser_use_cli.py").write_text("# fake", encoding="utf-8")
    assert HermesSandboxBrowser(link, root).interpreter == link.absolute()
