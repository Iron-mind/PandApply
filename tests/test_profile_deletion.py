import json
import re

import pytest
from fastapi.testclient import TestClient

from pandapply.configuration import patch_settings, read_settings
from pandapply.domain import Job
from pandapply.memory import propose_skill
from pandapply.profiles import add_profile, delete_profile, edit_profile, import_cv, list_profiles
from pandapply.storage import connect, migrate, save_job
from pandapply.submission import SitePolicy, SubmissionBlocked, begin_attempt
from pandapply.web import create_app


def test_delete_preserves_history_files_and_removes_search_selection(tmp_path):
    path = tmp_path / "data.db"
    migrate(path)
    cv = tmp_path / "original.pdf"
    cv.write_bytes(b"%PDF-1.4 fixture")
    with connect(path) as db:
        profile = add_profile(db, "Backend", "UTC", {})
        other = add_profile(db, "QA", "UTC", {})
        import_cv(db, profile, cv)
        decision = propose_skill(db, profile, "Python")
        job, _ = save_job(db, Job("Backend", "Example", "https://jobs.example.test/1", "fixture", "REQ-1"))
        db.execute("INSERT INTO applications (id,profile_id,job_posting_id,phase,status,created_at,updated_at) "
                   "VALUES ('app',?,?,'PREPARATION','READY_TO_SUBMIT','now','now')", (profile, job))
        db.commit()
        patch_settings(db, tmp_path / "config.json", {"search_profile_ids": [profile, other], "search_enabled": True}, actor="cli")
        result = delete_profile(db, profile, actor="cli", expected_version=1)
        assert result["history_preserved"] and not result["active"]
        assert [p["id"] for p in list_profiles(db)] == [other]
        assert len(list_profiles(db, include_inactive=True)) == 2
        assert read_settings(db, tmp_path / "config.json").search_profile_ids == [other]
        assert db.execute("SELECT count(*) FROM applications WHERE profile_id=?", (profile,)).fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM documents WHERE profile_id=?", (profile,)).fetchone()[0] == 1
        assert db.execute("SELECT decision_status FROM master_decisions WHERE id=?", (decision,)).fetchone()[0] == "CANCELLED"
        assert delete_profile(db, profile, actor="cli") == result
        assert db.execute("SELECT count(*) FROM event_outbox WHERE event_type='PROFILE_DELETED'").fetchone()[0] == 1
        with pytest.raises(ValueError):
            propose_skill(db, profile, "SQL")
        with pytest.raises(ValueError):
            edit_profile(db, profile, name="Back again")
        with pytest.raises(SubmissionBlocked):
            begin_attempt(db, "app", url="https://jobs.example.test/1", policy=SitePolicy("jobs.example.test", "v1", True),
                          consent=True, dry_run=False, form_fingerprint="fixture")
        delete_profile(db, other, actor="cli")
        assert not read_settings(db, tmp_path / "config.json").search_enabled
    assert cv.read_bytes() == b"%PDF-1.4 fixture"


def test_deletion_rejects_stale_version_atomically(tmp_path):
    path = tmp_path / "data.db"
    migrate(path)
    with connect(path) as db:
        profile = add_profile(db, "Backend", "UTC", {})
        edit_profile(db, profile, name="New name")
        with pytest.raises(ValueError, match="refresh"):
            delete_profile(db, profile, actor="cli", expected_version=1)
        assert list_profiles(db)[0]["active"]
        assert db.execute("SELECT count(*) FROM config_revisions").fetchone()[0] == 0


def test_deletion_cannot_race_an_in_progress_submission(tmp_path):
    path = tmp_path / "data.db"
    migrate(path)
    with connect(path) as db:
        profile = add_profile(db, "Backend", "UTC", {})
        job, _ = save_job(db, Job("Backend", "Example", "https://jobs.example.test/1", "fixture", "REQ-1"))
        db.execute("INSERT INTO applications (id,profile_id,job_posting_id,phase,status,created_at,updated_at) "
                   "VALUES ('app',?,?,'SUBMISSION','SUBMITTING','now','now')", (profile, job))
        db.execute("INSERT INTO submission_attempts (id,application_id,idempotency_key,permit_json,attempt_status,initiated_at) "
                   "VALUES ('attempt','app','key','{}','SUBMITTING','now')")
        db.commit()
        with pytest.raises(ValueError, match="in progress"):
            delete_profile(db, profile, actor="cli")
        assert list_profiles(db)[0]["active"]
        assert db.execute("SELECT count(*) FROM event_outbox").fetchone()[0] == 0


def test_delete_forms_require_confirmation_csrf_and_bearer_for_api(tmp_path):
    path = tmp_path / "data.db"
    migrate(path)
    with connect(path) as db:
        profile = add_profile(db, "<Backend>", "UTC", {})
    client = TestClient(create_app(path, "secret"), base_url="http://localhost")
    auth = ("pandapply", "secret")
    page = client.get(f"/profiles/{profile}/delete", auth=auth)
    assert "&lt;Backend&gt;" in page.text
    csrf = re.search(r"name='csrf' value='([^']+)'", page.text).group(1)
    form = {"csrf": csrf, "version": 1, "confirmation": "delete"}
    route = f"/profiles/{profile}/delete"
    assert client.post(route, data=form, auth=auth).status_code == 403
    assert client.post(route, data={**form, "confirmation": ""}, auth=auth,
                       headers={"Origin": "http://localhost"}).status_code == 400
    assert client.delete(f"/api/v1/profiles/{profile}", auth=auth).status_code == 401
    assert client.post(route, data=form, auth=auth, headers={"Origin": "http://localhost"},
                       follow_redirects=False).status_code == 303
    assert client.get("/api/v1/profiles", auth=auth).json() == []
    assert not client.get("/api/v1/profiles?include_inactive=true", auth=auth).json()[0]["active"]
    assert client.delete(f"/api/v1/profiles/{profile}", headers={"Authorization": "Bearer secret"}).status_code == 200


def test_cli_delete_requires_explicit_confirmation(tmp_path, monkeypatch, capsys):
    import sys

    from pandapply.cli import main

    monkeypatch.setattr("pandapply.cli.data_dir", lambda: tmp_path)
    path = tmp_path / "pandapply.db"
    migrate(path)
    with connect(path) as db:
        profile = add_profile(db, "Backend", "UTC", {})
    monkeypatch.setattr(sys, "argv", ["pandapply", "profiles", "delete", profile])
    with pytest.raises(SystemExit):
        main()
    capsys.readouterr()
    monkeypatch.setattr(sys, "argv", ["pandapply", "profiles", "delete", profile, "--confirm"])
    assert main() == 0
    assert not json.loads(capsys.readouterr().out)["active"]
