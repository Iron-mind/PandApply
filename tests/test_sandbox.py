import sqlite3

from fastapi.testclient import TestClient

from pandapply.domain import Job
from pandapply.profiles import add_profile
from pandapply.sandbox import create_sandbox
from pandapply.storage import connect, migrate, recover_submissions, save_job
from pandapply.submission import SitePolicy, SubmissionBlocked, begin_attempt


def test_ats_receipts_are_durable_and_deduplicated(tmp_path):
    path = tmp_path / "ats.db"
    data = {"idempotency_key": "attempt_123", "name": "Example Person", "email": "user@example.test"}
    files = {"cv": ("cv.pdf", b"%PDF-1.4\nsynthetic", "application/pdf")}
    with TestClient(create_sandbox(path), base_url="http://localhost") as client:
        assert client.get("/").status_code == 200
        first = client.post("/submit", data=data, files=files)
        assert first.status_code == 200
        assert first.json()["receipt"].startswith("sandbox-")
        assert client.post("/submit", data={**data, "email": "real@gmail.com"}, files=files).status_code == 400
        assert client.post("/submit", data={**data, "name": "Different"}, files=files).status_code == 409
    with TestClient(create_sandbox(path), base_url="http://localhost") as client:
        assert client.post("/submit", data=data, files=files).json() == first.json()
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM submissions").fetchone()[0] == 1


def test_private_sandbox_requires_token_for_post(tmp_path):
    path = tmp_path / "ats.db"
    data = {"idempotency_key": "attempt", "name": "Example", "email": "user@example.test"}
    files = {"cv": ("cv.pdf", b"%PDF-1.4 synthetic", "application/pdf")}
    with TestClient(create_sandbox(path, token="secret-token"), base_url="http://localhost") as client:
        assert client.post("/submit", data=data, files=files).status_code == 403
        assert client.post("/submit", data={**data, "sandbox_token": "wrong"}, files=files).status_code == 403
        assert client.post("/submit", data={**data, "sandbox_token": "secret-token"}, files=files).status_code == 200


def test_crash_after_sandbox_submit_is_unknown_and_not_retried(tmp_path):
    path = tmp_path / "pandapply.db"
    migrate(path)
    with connect(path) as db:
        job, _ = save_job(db, Job("Dev", "Demo", "https://jobs.example.test/job/1", "fixture", "1"))
        profile = add_profile(db, "Dev", "UTC", {})
        db.execute("INSERT INTO applications (id,profile_id,job_posting_id,phase,status,created_at,updated_at) "
                   "VALUES ('app',?,?,'SUBMISSION','READY_TO_SUBMIT','now','now')", (profile, job))
        db.execute("INSERT INTO documents (id,profile_id,kind,file_path,sha256,mime_type,created_at) "
                   "VALUES ('doc',?,'cv_generated','x','hash','application/pdf','now')", (profile,))
        db.execute("INSERT INTO sandbox_preparations VALUES ('app','doc','test-form','now')")
        db.commit()
        args = {"url": "https://jobs.example.test/job/1", "policy": SitePolicy("jobs.example.test", "1", True),
                "consent": True, "dry_run": False, "form_fingerprint": "test-form"}
        attempt = begin_attempt(db, "app", **args)
        ats_path = tmp_path / "ats.db"
        with TestClient(create_sandbox(ats_path), base_url="http://localhost") as client:
            response = client.post("/submit", data={"idempotency_key": attempt, "name": "Example",
                                                   "email": "user@example.test"},
                                   files={"cv": ("cv.pdf", b"%PDF-1.4\nsynthetic", "application/pdf")})
            assert response.status_code == 200
        # Simulate interruption after the remote ATS stored a receipt, before PandApply records it.
        assert recover_submissions(db) == 1
        assert db.execute("SELECT status FROM applications WHERE id='app'").fetchone()[0] == "SUBMISSION_UNKNOWN"
        import pytest

        with pytest.raises(SubmissionBlocked):
            begin_attempt(db, "app", **args)
        with sqlite3.connect(ats_path) as ats:
            assert ats.execute("SELECT count(*) FROM submissions").fetchone()[0] == 1
