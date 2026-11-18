"""End-to-end submission exclusively to the synthetic, local ATS."""

import hashlib
import json
import secrets
import socket
import sqlite3
import tempfile
import threading
import time
import uuid
from contextlib import closing, contextmanager
from pathlib import Path

import uvicorn

from pandapply.hermes_browser import HermesSandboxBrowser
from pandapply.sandbox import create_sandbox, store_submission
from pandapply.storage import now
from pandapply.submission import SitePolicy, SubmissionBlocked, begin_attempt, finish_attempt


def _verified_claims(db: sqlite3.Connection, profile_id: str, claims_json: str) -> bool:
    claim_ids = json.loads(claims_json)
    if (not isinstance(claim_ids, list) or not claim_ids or not all(isinstance(i, str) for i in claim_ids)
            or len(set(claim_ids)) != len(claim_ids)):
        return False
    count = db.execute("SELECT count(*) FROM knowledge_claims WHERE profile_id=? AND id IN (" +
                       ",".join("?" for _ in claim_ids) + ") AND verification_status IN "
                       "('master_confirmed','document_supported')", (profile_id, *claim_ids)).fetchone()[0]
    return count == len(claim_ids)


def prepare(db: sqlite3.Connection, application_id: str, document_id: str) -> str:
    db.execute("BEGIN IMMEDIATE")
    try:
        app = db.execute("SELECT a.*,j.ats_provider,j.canonical_url FROM applications a "
                         "JOIN job_postings j ON j.id=a.job_posting_id WHERE a.id=?", (application_id,)).fetchone()
        doc = db.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
        if (not app or app["status"] != "MATCHED" or app["ats_provider"] != "fixture"
                or not app["canonical_url"].startswith("https://jobs.example.test/")
                or not doc or doc["profile_id"] != app["profile_id"] or doc["kind"] != "cv_generated"):
            raise SubmissionBlocked("A matched synthetic vacancy and its profile's generated CV are required")
        if not _verified_claims(db, app["profile_id"], doc["claim_ids_json"]):
            raise SubmissionBlocked("The CV has no traceable claims or contains claims that are no longer verified")
        cv_path = Path(doc["file_path"])
        if cv_path.stat().st_size > 2_000_000:
            raise SubmissionBlocked("The generated CV exceeds the sandbox limit")
        content = cv_path.read_bytes()
        if hashlib.sha256(content).hexdigest() != doc["sha256"]:
            raise SubmissionBlocked("The generated CV changed or exceeds the sandbox limit")
        fingerprint = hashlib.sha256((app["canonical_url"] + "\0" + doc["sha256"]).encode()).hexdigest()
        timestamp = now()
        db.execute("INSERT INTO sandbox_preparations VALUES (?,?,?,?)", (application_id, document_id, fingerprint, timestamp))
        db.execute("UPDATE applications SET status='READY_TO_SUBMIT',phase='SUBMISSION',selected_cv_id=?,"
                   "updated_at=? WHERE id=?", (document_id, timestamp, application_id))
        db.execute("INSERT INTO application_events (id,application_id,event_type,from_status,to_status,"
                   "actor_type,correlation_id,created_at) VALUES (?,?,'SANDBOX_PREPARED','MATCHED',"
                   "'READY_TO_SUBMIT','system',?,?)", (str(uuid.uuid4()), application_id, str(uuid.uuid4()), timestamp))
        db.commit()
        return fingerprint
    except Exception:
        db.rollback()
        raise


def _prepared(db: sqlite3.Connection, application_id: str):
    row = db.execute("SELECT a.status,a.profile_id,j.canonical_url,d.file_path,d.sha256,d.claim_ids_json,p.form_fingerprint "
                     "FROM applications a JOIN job_postings j ON j.id=a.job_posting_id "
                     "JOIN sandbox_preparations p ON p.application_id=a.id "
                     "JOIN documents d ON d.id=p.document_id WHERE a.id=?", (application_id,)).fetchone()
    if not row or row["status"] != "READY_TO_SUBMIT":
        raise SubmissionBlocked("Sandbox application is not prepared")
    if not _verified_claims(db, row["profile_id"], row["claim_ids_json"]):
        raise SubmissionBlocked("The CV contains claims that are no longer verified")
    path = Path(row["file_path"])
    if path.stat().st_size > 2_000_000:
        raise SubmissionBlocked("The generated CV exceeds the sandbox limit")
    contents = path.read_bytes()
    if hashlib.sha256(contents).hexdigest() != row["sha256"]:
        raise SubmissionBlocked("The generated CV changed after preparation")
    return row, contents


def submit(db: sqlite3.Connection, application_id: str, ats_database: Path, *, consent: bool) -> str:
    row, contents = _prepared(db, application_id)
    attempt = begin_attempt(db, application_id, url=row["canonical_url"],
                            policy=SitePolicy("jobs.example.test", "sandbox-1", True), consent=consent,
                            dry_run=False, form_fingerprint=row["form_fingerprint"])
    try:
        create_sandbox(ats_database)
        receipt = store_submission(ats_database, idempotency_key=attempt, name="Example Candidate",
                                   email="candidate@example.test", contents=contents)
    except Exception:
        finish_attempt(db, attempt, None)
        raise
    finish_attempt(db, attempt, receipt)
    return receipt


@contextmanager
def _sandbox_server(database: Path):
    token = secrets.token_urlsafe(32)
    app = create_sandbox(database, token=token)
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(32)
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", access_log=False))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        try:
            for _ in range(100):
                if server.started:
                    break
                if not thread.is_alive():
                    break
                time.sleep(0.05)
            if not server.started:
                raise RuntimeError("Local sandbox did not start")
            yield f"http://127.0.0.1:{port}/"
        finally:
            server.should_exit = True
            thread.join(timeout=10)


def submit_with_hermes(db: sqlite3.Connection, application_id: str, ats_database: Path, *, consent: bool,
                       interpreter: Path, hermes_root: Path) -> str:
    """Send a prepared fixture through Hermes' isolated browser to the local ATS only."""
    browser = HermesSandboxBrowser(interpreter, hermes_root)
    row, contents = _prepared(db, application_id)
    if not consent:
        raise SubmissionBlocked("Explicit consent is required even for the sandbox")
    with tempfile.TemporaryDirectory(prefix="pandapply-browser-") as directory, _sandbox_server(ats_database) as url:
        attempt = begin_attempt(db, application_id, url=row["canonical_url"],
                                policy=SitePolicy("jobs.example.test", "sandbox-1", True), consent=consent,
                                dry_run=False, form_fingerprint=row["form_fingerprint"])
        try:
            receipt = browser.submit(url=url, attempt_id=attempt, pdf=contents, directory=Path(directory))
            with closing(sqlite3.connect(ats_database.resolve().as_uri() + "?mode=ro", uri=True)) as ats:
                stored = ats.execute("SELECT receipt FROM submissions WHERE idempotency_key=?", (attempt,)).fetchone()
            if not stored or stored[0] != receipt:
                raise SubmissionBlocked("Browser receipt could not be verified against the local ATS")
        except Exception:
            finish_attempt(db, attempt, None)
            raise
        finish_attempt(db, attempt, receipt)
        return receipt


def reconcile(db: sqlite3.Connection, application_id: str, ats_database: Path) -> str | None:
    """Look up an uncertain submission in the local ATS without submitting again."""
    # An explicit reconciliation also handles an interrupted process that stopped
    # before it could change SUBMITTING into SUBMISSION_UNKNOWN.
    db.execute("BEGIN IMMEDIATE")
    try:
        active = db.execute("SELECT s.id FROM submission_attempts s JOIN applications a "
                            "ON a.id=s.application_id JOIN job_postings j ON j.id=a.job_posting_id "
                            "WHERE a.id=? AND a.status='SUBMITTING' AND s.attempt_status='SUBMITTING' "
                            "AND j.ats_provider='fixture'", (application_id,)).fetchone()
        if active:
            db.execute("UPDATE submission_attempts SET attempt_status='UNKNOWN',completed_at=? WHERE id=?",
                       (now(), active["id"]))
            db.execute("UPDATE applications SET status='SUBMISSION_UNKNOWN',updated_at=? WHERE id=?",
                       (now(), application_id))
            db.execute("INSERT INTO application_events (id,application_id,event_type,from_status,to_status,"
                       "actor_type,correlation_id,created_at) VALUES (?,?,'SANDBOX_RECOVERY','SUBMITTING',"
                       "'SUBMISSION_UNKNOWN','system',?,?)", (str(uuid.uuid4()), application_id, active["id"], now()))
        db.commit()
    except Exception:
        db.rollback()
        raise
    if not ats_database.is_file():
        return None
    row = db.execute("SELECT s.id FROM submission_attempts s JOIN applications a ON a.id=s.application_id "
                     "JOIN job_postings j ON j.id=a.job_posting_id WHERE a.id=? AND "
                     "a.status='SUBMISSION_UNKNOWN' AND s.attempt_status='UNKNOWN' "
                     "AND j.ats_provider='fixture' ORDER BY s.initiated_at DESC LIMIT 1", (application_id,)).fetchone()
    if not row:
        raise SubmissionBlocked("No uncertain sandbox submission to reconcile")
    with closing(sqlite3.connect(ats_database.resolve().as_uri() + "?mode=ro", uri=True)) as ats:
        receipt_row = ats.execute("SELECT receipt FROM submissions WHERE idempotency_key=?", (row["id"],)).fetchone()
    if not receipt_row:
        return None
    receipt = receipt_row[0]
    db.execute("BEGIN IMMEDIATE")
    try:
        changed = db.execute("UPDATE submission_attempts SET attempt_status='CONFIRMED',external_receipt=?,"
                             "completed_at=? WHERE id=? AND attempt_status='UNKNOWN'", (receipt, now(), row["id"])).rowcount
        if changed != 1:
            raise SubmissionBlocked("Attempt changed during reconciliation")
        db.execute("UPDATE applications SET status='SUBMITTED',receipt_ref=?,updated_at=? WHERE id=? "
                   "AND status='SUBMISSION_UNKNOWN'", (receipt, now(), application_id))
        db.execute("INSERT INTO application_events (id,application_id,event_type,from_status,to_status,"
                   "actor_type,correlation_id,evidence_ref,created_at) VALUES (?,?,'SANDBOX_RECONCILED',"
                   "'SUBMISSION_UNKNOWN','SUBMITTED','system',?,?,?)",
                   (str(uuid.uuid4()), application_id, row["id"], receipt, now()))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return receipt
