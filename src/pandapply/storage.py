"""SQLite persistence and conservative crash recovery."""

import hashlib
import json
import os
import sqlite3
import time
import uuid
from contextlib import closing
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path

from pandapply.domain import Job, canonical_url


def now() -> str:
    return datetime.now(UTC).isoformat()


def connect(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


def _enable_wal(db: sqlite3.Connection) -> None:
    # journal_mode changes can return SQLITE_BUSY immediately despite busy_timeout
    # when two processes initialize the same new database concurrently.
    deadline = time.monotonic() + 10
    while True:
        try:
            db.execute("PRAGMA journal_mode=WAL")
            return
        except sqlite3.OperationalError as exc:
            code = getattr(exc, "sqlite_errorcode", 0) & 0xff
            if code not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED) or time.monotonic() >= deadline:
                raise
            time.sleep(0.05)


def migrate(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_data = path.exists() and path.stat().st_size > 0
    with closing(connect(path)) as db:
        _enable_wal(db)
        db.execute("BEGIN IMMEDIATE")
        try:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > 10:
                raise RuntimeError("Database version is newer than this PandApply")
            if existing_data and version < 10:
                # A second read connection captures a consistent snapshot while the
                # write lock prevents another migration from changing the schema.
                backup_path = path.with_name(f"{path.name}.backup-v{version}-{uuid.uuid4().hex}.sqlite")
                fd = os.open(backup_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(fd)
                try:
                    with closing(connect(path)) as source, closing(sqlite3.connect(backup_path)) as backup:
                        source.backup(backup)
                except Exception:
                    backup_path.unlink(missing_ok=True)
                    raise
            migrations = ("001_initial.sql", "002_reply_attempts.sql", "003_sandbox_preparations.sql",
                          "004_http_idempotency.sql", "005_config_revisions.sql", "006_mail_review.sql",
                          "007_site_policy.sql", "008_reply_dispatches.sql", "009_scheduled_jobs.sql",
                          "010_mail_review_queue.sql")
            for index in range(version, len(migrations)):
                sql = files("pandapply").joinpath("migrations", migrations[index]).read_text("utf-8")
                sql = sql.replace("PRAGMA foreign_keys = ON;", "").replace("PRAGMA journal_mode = WAL;", "")
                statement = ""
                for line in sql.splitlines(keepends=True):
                    statement += line
                    if sqlite3.complete_statement(statement):
                        db.execute(statement)
                        statement = ""
                if statement.strip():
                    raise RuntimeError(f"Incomplete migration {migrations[index]}")
                db.execute(f"PRAGMA user_version={index + 1}")
            db.commit()
        except Exception:
            db.rollback()
            raise


def save_job(db: sqlite3.Connection, job: Job) -> tuple[str, bool]:
    url = canonical_url(job.url)
    if bool(job.ats_provider) != bool(job.ats_id):
        raise ValueError("ATS provider and ID must be supplied together")
    db.execute("BEGIN IMMEDIATE")
    try:
        row = None
        if job.ats_provider:
            row = db.execute("SELECT id FROM job_postings WHERE ats_provider=? AND ats_requisition_id=?",
                             (job.ats_provider, job.ats_id)).fetchone()
        if row is None:
            # A shared URL is not enough to pick between distinct known ATS IDs.
            matches = db.execute("SELECT id, ats_provider, ats_requisition_id FROM job_postings "
                                 "WHERE canonical_url=?", (url,)).fetchall()
            if job.ats_provider:
                eligible = [candidate for candidate in matches if candidate['ats_provider'] is None]
                if len(eligible) > 1:
                    raise ValueError("Ambiguous job URL requires manual review")
                if eligible and len(matches) == 1:
                    row = eligible[0]
                    db.execute("UPDATE job_postings SET ats_provider=?, ats_requisition_id=? WHERE id=?",
                               (job.ats_provider, job.ats_id, row['id']))
            elif len(matches) == 1:
                row = matches[0]
            elif len(matches) > 1:
                raise ValueError("Ambiguous job URL requires manual review")
        if row:
            db.commit()
            return row[0], False
        job_id = str(uuid.uuid4())
        identity = (f"ats:{job.ats_provider}:{job.ats_id}" if job.ats_provider else f"url:{url}")
        fingerprint = hashlib.sha256(identity.encode()).hexdigest()
        timestamp = now()
        db.execute("INSERT INTO job_postings (id, canonical_url, ats_provider, ats_requisition_id, "
                   "fingerprint, title, company_name, source_url, discovered_at, last_seen_at) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   (job_id, url, job.ats_provider, job.ats_id, fingerprint, job.title, job.company,
                    job.url, timestamp, timestamp))
        db.commit()
        return job_id, True
    except Exception:
        db.rollback()
        raise


def recover_submissions(db: sqlite3.Connection) -> int:
    """After restart, any interrupted submit may have reached the external site."""
    db.execute("BEGIN IMMEDIATE")
    try:
        rows = db.execute("SELECT id, application_id FROM submission_attempts "
                          "WHERE attempt_status='SUBMITTING'").fetchall()
        for row in rows:
            db.execute("UPDATE submission_attempts SET attempt_status='UNKNOWN', completed_at=? "
                       "WHERE id=?", (now(), row['id']))
            db.execute("UPDATE applications SET status='SUBMISSION_UNKNOWN', updated_at=? WHERE id=?",
                       (now(), row['application_id']))
            db.execute("INSERT INTO application_events (id, application_id, event_type, from_status, "
                       "to_status, actor_type, correlation_id, payload_redacted_json, created_at) "
                       "VALUES (?, ?, 'RECOVERY', 'SUBMITTING', 'SUBMISSION_UNKNOWN', 'system', ?, ?, ?)",
                       (str(uuid.uuid4()), row['application_id'], str(uuid.uuid4()),
                        json.dumps({'attempt_id': row['id']}), now()))
        db.commit()
        return len(rows)
    except Exception:
        db.rollback()
        raise
