"""Conservative Gmail discovery using the Hermes Workspace read-only interface."""

import hashlib
import re
import sqlite3
from typing import Protocol

from pandapply.mail_review import TRACKABLE, ingest_for_review
from pandapply.storage import now


class WorkspaceReader(Protocol):
    def search_for_account(self, account: str, query: str, *, limit: int = 10) -> list[dict]: ...
    def get_for_account(self, account: str, message_id: str) -> dict: ...


def _queue_manual_review(db: sqlite3.Connection, account_id: str, message_id: str, reason: str) -> None:
    timestamp = now()
    with db:
        db.execute("INSERT INTO mail_review_queue (gmail_account_id,gmail_message_id,reason,first_seen_at,last_seen_at) "
                   "VALUES (?,?,?,?,?) ON CONFLICT(gmail_account_id,gmail_message_id) DO UPDATE SET "
                   "reason=excluded.reason,last_seen_at=excluded.last_seen_at",
                   (account_id, message_id, reason, timestamp, timestamp))


def _suggest_classification(text: str) -> str | None:
    text = text.casefold()
    if any(term in text for term in ("interview", "entrevista")):
        return "interview"
    if any(term in text for term in ("will not proceed", "not moving forward", "no continuaremos")):
        return "rejection"
    if any(term in text for term in ("received your application", "recibimos tu postulación")):
        return "application_received"
    if any(term in text for term in ("next step", "siguiente etapa")):
        return "next_step"
    return None


def poll(db: sqlite3.Connection, reader: WorkspaceReader, *, account: str, query: str,
         limit: int = 10) -> list[dict]:
    """Poll a bounded, owner-provided query; no status changes occur without review."""
    if not account.strip() or len(account) > 320 or not 1 <= limit <= 20:
        raise ValueError("Account label and limit between 1 and 20 are required")
    account_id = "hermes:" + hashlib.sha256(account.strip().casefold().encode()).hexdigest()
    placeholders = ",".join("?" for _ in TRACKABLE)
    applications = db.execute("SELECT a.id,a.status,j.ats_requisition_id FROM applications a "
                              "JOIN job_postings j ON j.id=a.job_posting_id WHERE a.status IN (" +
                              placeholders + ") AND j.ats_requisition_id IS NOT NULL "
                              "AND (j.ats_provider IS NULL OR j.ats_provider != 'fixture')", TRACKABLE).fetchall()
    results = []
    messages = reader.search_for_account(account, query, limit=limit)
    if len(messages) > limit:
        raise ValueError("Hermes returned more messages than the requested limit")
    for item in messages:
        message_id = item.get("id")
        subject, snippet = item.get("subject", ""), item.get("snippet", "")
        if (not isinstance(message_id, str) or not message_id or len(message_id) > 512
                or not isinstance(subject, str) or not isinstance(snippet, str)
                or len(subject) > 2000 or len(snippet) > 5000):
            raise ValueError("Hermes returned malformed search metadata")
        existing = db.execute("SELECT id FROM mailbox_messages WHERE gmail_account_id=? AND gmail_message_id=?",
                              (account_id, message_id)).fetchone()
        if existing:
            with db:
                db.execute("DELETE FROM mail_review_queue WHERE gmail_account_id=? AND gmail_message_id=?",
                           (account_id, message_id))
            results.append({"id": message_id, "status": "duplicate"})
            continue
        text = subject + "\n" + snippet
        matches = []
        for app in applications:
            ref = app["ats_requisition_id"]
            if len(ref) >= 5 and re.search(r"(?<![\w])" + re.escape(ref) + r"(?![\w])", text, re.IGNORECASE):
                matches.append(app)
        classification = _suggest_classification(text)
        if len(matches) != 1 or classification is None:
            reason = "ambiguous correlation or classification"
            _queue_manual_review(db, account_id, message_id, reason)
            results.append({"id": message_id, "status": "manual_review", "reason": reason})
            continue
        app = matches[0]
        if classification == "application_received" and app["status"] != "SUBMITTED":
            reason = "application already advanced"
            _queue_manual_review(db, account_id, message_id, reason)
            results.append({"id": message_id, "status": "manual_review", "reason": reason})
            continue
        message = reader.get_for_account(account, message_id)
        review = ingest_for_review(db, account, message, application_id=app["id"], classification=classification)
        with db:
            db.execute("DELETE FROM mail_review_queue WHERE gmail_account_id=? AND gmail_message_id=?",
                       (account_id, message_id))
        results.append({"id": message_id, **review})
    # This is an observation time, not a Gmail history cursor. The next query is
    # explicitly supplied by the owner and should include overlap where appropriate.
    timestamp = now()
    with db:
        db.execute("INSERT INTO gmail_cursors (gmail_account_id,last_poll_at) VALUES (?,?) "
                   "ON CONFLICT(gmail_account_id) DO UPDATE SET last_poll_at=excluded.last_poll_at",
                   (account_id, timestamp))
    return results
