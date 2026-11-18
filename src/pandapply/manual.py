"""Record evidence for actions the owner completed independently of PandApply."""

import sqlite3
import uuid

from pandapply.storage import now


def record_submission(db: sqlite3.Connection, application_id: str, receipt: str, *, confirm: bool) -> None:
    receipt = receipt.strip()
    if not confirm or not 3 <= len(receipt) <= 500 or any(ch in receipt for ch in "\r\n\x00"):
        raise ValueError("Explicit confirmation and a receipt/reference of 3–500 characters are required")
    db.execute("BEGIN IMMEDIATE")
    try:
        app = db.execute("SELECT a.status,j.ats_provider FROM applications a JOIN job_postings j "
                         "ON j.id=a.job_posting_id WHERE a.id=?", (application_id,)).fetchone()
        if not app or app["status"] not in ("MANUAL_REVIEW", "SKIPPED_INELIGIBLE") or app["ats_provider"] == "fixture":
            raise ValueError("Only a non-synthetic application awaiting manual handling can be recorded")
        prior = db.execute("SELECT 1 FROM submission_attempts WHERE application_id=? AND "
                           "attempt_status IN ('SUBMITTING','UNKNOWN','CONFIRMED')", (application_id,)).fetchone()
        if prior:
            raise ValueError("Existing submission attempt requires reconciliation")
        timestamp = now()
        db.execute("UPDATE applications SET status='SUBMITTED',phase='TRACKING',receipt_ref=?,applied_at=?,"
                   "updated_at=? WHERE id=?", ("owner-confirmed:" + receipt, timestamp, timestamp, application_id))
        db.execute("INSERT INTO application_events (id,application_id,event_type,from_status,to_status,actor_type,"
                   "actor_id,correlation_id,evidence_ref,created_at) "
                   "VALUES (?,?,'MANUAL_SUBMISSION_RECORDED',?,'SUBMITTED','owner','local-owner',?,?,?)",
                   (str(uuid.uuid4()), application_id, app["status"], str(uuid.uuid4()), "owner-confirmed:" + receipt, timestamp))
        db.commit()
    except Exception:
        db.rollback()
        raise
