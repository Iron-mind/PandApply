"""Submission state management. No browser or network transport is provided here."""

import json
import sqlite3
import uuid
from dataclasses import dataclass
from urllib.parse import urlsplit

from pandapply.storage import now


class SubmissionBlocked(ValueError):
    pass


@dataclass(frozen=True)
class SitePolicy:
    domain: str
    version: str
    allowed: bool = False


def begin_attempt(db: sqlite3.Connection, application_id: str, *, url: str,
                  policy: SitePolicy, consent: bool, dry_run: bool, form_fingerprint: str) -> str:
    """Record an attempt for the synthetic ATS only, before an external operation.

    Caller-provided policy is not sufficient to authorize real portals. A future real
    adapter must use independently persisted consent, policy and form evidence.
    """
    host = urlsplit(url).hostname
    if (not host or host.lower() != "jobs.example.test" or host.lower() != policy.domain.lower()
            or not policy.allowed or not consent
            or dry_run or not policy.version or not form_fingerprint):
        raise SubmissionBlocked("Submission policy or authorization not satisfied")
    db.execute("BEGIN IMMEDIATE")
    try:
        app = db.execute("SELECT a.status,j.ats_provider,j.canonical_url FROM applications a "
                         "JOIN job_postings j ON j.id=a.job_posting_id WHERE a.id=?",
                         (application_id,)).fetchone()
        if not app or app["status"] != "READY_TO_SUBMIT":
            raise SubmissionBlocked("Application is not ready to submit")
        if app["ats_provider"] != "fixture" or app["canonical_url"] != url:
            raise SubmissionBlocked("Only the matching synthetic ATS posting is supported")
        preparation = db.execute("SELECT form_fingerprint FROM sandbox_preparations WHERE application_id=?",
                                 (application_id,)).fetchone()
        if not preparation or preparation["form_fingerprint"] != form_fingerprint:
            raise SubmissionBlocked("A matching sandbox preparation is required")
        prior = db.execute("SELECT 1 FROM submission_attempts WHERE application_id=? AND "
                           "attempt_status IN ('SUBMITTING', 'UNKNOWN', 'CONFIRMED')",
                           (application_id,)).fetchone()
        if prior:
            raise SubmissionBlocked("Existing attempt requires reconciliation")
        attempt_id = str(uuid.uuid4())
        permit = json.dumps({"domain": host.lower(), "policy_version": policy.version,
                             "form_fingerprint": form_fingerprint})
        timestamp = now()
        db.execute("INSERT INTO submission_attempts (id, application_id, idempotency_key, permit_json, "
                   "attempt_status, initiated_at) VALUES (?, ?, ?, ?, 'SUBMITTING', ?)",
                   (attempt_id, application_id, attempt_id, permit, timestamp))
        db.execute("UPDATE applications SET status='SUBMITTING', phase='SUBMISSION', policy_version=?, "
                   "updated_at=? WHERE id=?", (policy.version, timestamp, application_id))
        db.execute("INSERT INTO application_events (id, application_id, event_type, from_status, "
                   "to_status, actor_type, correlation_id, created_at) VALUES (?, ?, 'SUBMISSION_STARTED', "
                   "'READY_TO_SUBMIT', 'SUBMITTING', 'system', ?, ?)",
                   (str(uuid.uuid4()), application_id, attempt_id, timestamp))
        db.commit()
        return attempt_id
    except Exception:
        db.rollback()
        raise


def finish_attempt(db: sqlite3.Connection, attempt_id: str, receipt: str | None) -> str:
    db.execute("BEGIN IMMEDIATE")
    try:
        attempt = db.execute("SELECT application_id, attempt_status FROM submission_attempts WHERE id=?",
                             (attempt_id,)).fetchone()
        if not attempt or attempt["attempt_status"] != "SUBMITTING":
            raise SubmissionBlocked("Attempt is not submitting")
        receipt = receipt.strip() if receipt else None
        status = "SUBMITTED" if receipt else "SUBMISSION_UNKNOWN"
        attempt_status = "CONFIRMED" if receipt else "UNKNOWN"
        timestamp = now()
        db.execute("UPDATE submission_attempts SET attempt_status=?, external_receipt=?, completed_at=? "
                   "WHERE id=?", (attempt_status, receipt, timestamp, attempt_id))
        db.execute("UPDATE applications SET status=?, receipt_ref=?, updated_at=? WHERE id=?",
                   (status, receipt, timestamp, attempt["application_id"]))
        db.execute("INSERT INTO application_events (id, application_id, event_type, from_status, "
                   "to_status, actor_type, correlation_id, created_at) VALUES (?, ?, 'SUBMISSION_FINISHED', "
                   "'SUBMITTING', ?, 'system', ?, ?)",
                   (str(uuid.uuid4()), attempt["application_id"], status, attempt_id, timestamp))
        db.commit()
        return status
    except Exception:
        db.rollback()
        raise
