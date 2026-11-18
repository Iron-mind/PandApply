import sqlite3

import pytest

from pandapply.domain import Job, canonical_url
from pandapply.storage import connect, migrate, recover_submissions, save_job


def test_migration_idempotent_and_foreign_keys(tmp_path):
    path = tmp_path / "db.sqlite"
    migrate(path)
    migrate(path)
    with connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 10
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO professional_profiles VALUES ('p','missing','n','{}',1,1,'x','x')")


def test_dedupe_prefers_ats_and_does_not_merge_distinct_ids(tmp_path):
    path = tmp_path / "db.sqlite"
    migrate(path)
    with connect(path) as db:
        first, created = save_job(db, Job("Engineer", "Co", "https://example.com/job?utm_source=x",
                                           "ats", "123"))
        assert created
        same, created = save_job(db, Job("Engineer", "Co", "https://other.com/job", "ats", "123"))
        assert same == first and not created
        other, created = save_job(db, Job("Engineer", "Co", "https://example.com/job", "ats", "124"))
        assert created and other != first


def test_url_normalization():
    assert canonical_url("https://EXAMPLE.com/a/?utm_source=x&b=2#top") == "https://example.com/a?b=2"
    with pytest.raises(ValueError):
        canonical_url("file:///etc/passwd")


def test_url_dedupe_does_not_merge_different_ats_ids(tmp_path):
    path = tmp_path / "db.sqlite"
    migrate(path)
    with connect(path) as db:
        original, _ = save_job(db, Job("Engineer", "Co", "https://example.com/job"))
        same, created = save_job(db, Job("Engineer", "Co", "https://example.com/job", "ats", "a"))
        assert same == original and not created
        other, created = save_job(db, Job("Engineer", "Co", "https://example.com/job", "ats", "b"))
        assert created and other != original
        with pytest.raises(ValueError, match="Ambiguous"):
            save_job(db, Job("Engineer", "Co", "https://example.com/job"))


def test_interrupted_submission_stays_unknown_and_recovery_is_idempotent(tmp_path):
    path = tmp_path / "db.sqlite"
    migrate(path)
    with connect(path) as db:
        job, _ = save_job(db, Job("Engineer", "Co", "https://example.com/job"))
        db.execute("INSERT INTO master_profile VALUES ('m','Master','UTC','now')")
        db.execute("INSERT INTO professional_profiles VALUES ('p','m','profile','{}',1,1,'now','now')")
        db.execute("INSERT INTO applications (id,profile_id,job_posting_id,phase,status,created_at,updated_at) "
                   "VALUES ('a','p',?,'SUBMISSION','SUBMITTING','now','now')", (job,))
        db.execute("INSERT INTO submission_attempts (id,application_id,idempotency_key,permit_json,"
                   "attempt_status,initiated_at) VALUES ('t','a','key','{}','SUBMITTING','now')")
        db.commit()
        assert recover_submissions(db) == 1
        assert recover_submissions(db) == 0
        assert db.execute("SELECT status FROM applications").fetchone()[0] == "SUBMISSION_UNKNOWN"
        assert db.execute("SELECT attempt_status FROM submission_attempts").fetchone()[0] == "UNKNOWN"
        assert db.execute("SELECT count(*) FROM application_events").fetchone()[0] == 1
