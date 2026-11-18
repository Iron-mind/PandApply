from concurrent.futures import ThreadPoolExecutor

import pytest

from pandapply.domain import Job
from pandapply.profiles import add_profile
from pandapply.storage import connect, migrate, save_job
from pandapply.submission import SitePolicy, SubmissionBlocked, begin_attempt, finish_attempt


def test_policy_gate_and_unknown_prevent_repeat(tmp_path):
    path = tmp_path / "local.db"
    migrate(path)
    with connect(path) as db:
        job, _ = save_job(db, Job("Dev", "Demo", "https://jobs.example.test/job", "fixture", "1"))
        profile = add_profile(db, "Dev", "UTC", {})
        db.execute("INSERT INTO applications (id, profile_id, job_posting_id, phase, status, "
                   "created_at, updated_at) VALUES ('a', ?, ?, 'SUBMISSION', 'READY_TO_SUBMIT', 'x', 'x')",
                   (profile, job))
        db.execute("INSERT INTO documents (id,profile_id,kind,file_path,sha256,mime_type,created_at) "
                   "VALUES ('doc',?,'cv_generated','x','hash','application/pdf','now')", (profile,))
        db.execute("INSERT INTO sandbox_preparations VALUES ('a','doc','hash','now')")
        db.commit()
        policy = SitePolicy("jobs.example.test", "1", True)
        args = {"url": "https://jobs.example.test/job", "policy": policy, "consent": True,
                "dry_run": False, "form_fingerprint": "hash"}
        with pytest.raises(SubmissionBlocked):
            begin_attempt(db, "a", **{**args, "consent": False})
        with pytest.raises(SubmissionBlocked):
            begin_attempt(db, "a", **{**args, "dry_run": True})
        with pytest.raises(SubmissionBlocked):
            begin_attempt(db, "a", **{**args, "url": "https://other.test/job"})
        attempt = begin_attempt(db, "a", **args)
        assert finish_attempt(db, attempt, None) == "SUBMISSION_UNKNOWN"
        with pytest.raises(SubmissionBlocked):
            begin_attempt(db, "a", **args)
        assert db.execute("SELECT count(*) FROM submission_attempts").fetchone()[0] == 1


def test_concurrent_sandbox_submissions_allow_one_attempt(tmp_path):
    path = tmp_path / "local.db"
    migrate(path)
    with connect(path) as db:
        job, _ = save_job(db, Job("Dev", "Demo", "https://jobs.example.test/job", "fixture", "1"))
        profile = add_profile(db, "Dev", "UTC", {})
        db.execute("INSERT INTO applications (id,profile_id,job_posting_id,phase,status,created_at,updated_at) "
                   "VALUES ('a',?,?,'SUBMISSION','READY_TO_SUBMIT','now','now')", (profile, job))
        db.execute("INSERT INTO documents (id,profile_id,kind,file_path,sha256,mime_type,created_at) "
                   "VALUES ('doc',?,'cv_generated','x','hash','application/pdf','now')", (profile,))
        db.execute("INSERT INTO sandbox_preparations VALUES ('a','doc','hash','now')")
        db.commit()

    def try_begin():
        db = connect(path)
        try:
            return begin_attempt(db, "a", url="https://jobs.example.test/job",
                                 policy=SitePolicy("jobs.example.test", "1", True), consent=True,
                                 dry_run=False, form_fingerprint="hash")
        except SubmissionBlocked:
            return None
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: try_begin(), range(2)))
    assert sum(result is not None for result in results) == 1
    with connect(path) as db:
        assert db.execute("SELECT count(*) FROM submission_attempts").fetchone()[0] == 1
