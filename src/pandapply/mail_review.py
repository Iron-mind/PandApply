"""Review-only intake for real messages read through Hermes Workspace.

Messages are treated as untrusted data. Ingestion never changes an application or
creates/sends a reply; a specific local-owner decision is required for a transition.
"""

import hashlib
import json
import sqlite3
import uuid
from datetime import UTC
from email.utils import parseaddr, parsedate_to_datetime

from pandapply.storage import now

TRANSITIONS = {
    "application_received": "ACKNOWLEDGED",
    "rejection": "REJECTED",
    "next_step": "IN_PROCESS",
    "interview": "INTERVIEW",
    "offer": "OFFER",
}
TRACKABLE = ("SUBMITTED", "ACKNOWLEDGED", "IN_PROCESS", "INTERVIEW")


def ingest_for_review(db: sqlite3.Connection, account: str, message: dict, *,
                      application_id: str, classification: str) -> dict:
    """Persist minimal metadata and ask the owner to review a proposed transition."""
    if (not isinstance(account, str) or not account.strip() or len(account) > 320
            or classification not in TRANSITIONS or not isinstance(message, dict)):
        raise ValueError("Account and supported proposed classification are required")
    identifier, thread = message.get("id"), message.get("threadId")
    sender, subject, body, date = (message.get("from"), message.get("subject"),
                                   message.get("body"), message.get("date"))
    if (not all(isinstance(value, str) and 0 < len(value) <= 512 for value in (identifier, thread))
            or not isinstance(sender, str) or len(sender) > 1000 or "\n" in sender or "\r" in sender
            or not isinstance(subject, str) or len(subject) > 2000
            or not isinstance(body, str) or len(body) > 200_000 or not isinstance(date, str)):
        raise ValueError("Hermes message is missing required headers or exceeds size limits")
    address = parseaddr(sender)[1]
    if not address or "@" not in address:
        raise ValueError("Hermes message has no usable sender address")
    try:
        sent = parsedate_to_datetime(date)
        if sent is None or sent.tzinfo is None:
            raise ValueError("missing timezone")
        sent_at = sent.astimezone(UTC).isoformat()
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("Hermes message date is missing or invalid") from exc
    account_id = "hermes:" + hashlib.sha256(account.strip().casefold().encode()).hexdigest()
    content = json.dumps({"id": identifier, "threadId": thread, "from": sender,
                          "subject": subject, "body": body, "date": date},
                         ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(content.encode()).hexdigest()
    db.execute("BEGIN IMMEDIATE")
    try:
        existing = db.execute("SELECT m.id,e.content_sha256,e.application_id,e.proposed_classification,e.decision_id "
                              "FROM mailbox_messages m LEFT JOIN mail_review_evidence e ON e.message_id=m.id "
                              "WHERE m.gmail_account_id=? AND m.gmail_message_id=?", (account_id, identifier)).fetchone()
        if existing:
            if (existing["content_sha256"] != digest or existing["application_id"] != application_id
                    or existing["proposed_classification"] != classification):
                raise ValueError("Message was already imported with different content or review context")
            db.commit()
            return {"message_id": existing["id"], "decision_id": existing["decision_id"], "status": "duplicate"}
        application = db.execute("SELECT a.status,j.ats_provider FROM applications a JOIN job_postings j "
                                 "ON j.id=a.job_posting_id WHERE a.id=?", (application_id,)).fetchone()
        if not application or application["status"] not in TRACKABLE:
            raise ValueError("Select a submitted application eligible for follow-up")
        if application["ats_provider"] == "fixture":
            raise ValueError("Real mail cannot be attached to a simulated application")
        if classification == "application_received" and application["status"] != "SUBMITTED":
            raise ValueError("Receipt confirmation is only valid for a newly submitted application")
        message_id, decision_id, timestamp = str(uuid.uuid4()), str(uuid.uuid4()), now()
        db.execute("INSERT INTO mailbox_messages (id,gmail_account_id,gmail_message_id,gmail_thread_id,sender,"
                   "sent_at,classification,application_id,processed_at) VALUES (?,?,?,?,?,?,NULL,?,?)",
                   (message_id, account_id, identifier, thread, address, sent_at, application_id, timestamp))
        payload = {"message_id": message_id, "gmail_message_id": identifier, "thread_id": thread,
                   "application_id": application_id, "proposed_classification": classification,
                   "content_sha256": digest, "sender": address, "prior_status": application["status"]}
        db.execute("INSERT INTO master_decisions (id,decision_type,related_entity_type,related_entity_id,payload_json,"
                   "decision_status,authorized_channel,authorized_principal,created_at) "
                   "VALUES (?,'MAIL_REVIEW','mailbox_message',?,?,'PENDING','local','local-owner',?)",
                   (decision_id, message_id, json.dumps(payload, ensure_ascii=False), timestamp))
        db.execute("INSERT INTO mail_review_evidence VALUES (?,?,?,?,?,?,?)",
                   (message_id, application_id, decision_id, digest, classification, application["status"], timestamp))
        db.execute("INSERT INTO event_outbox (id,event_type,payload_redacted_json,destination,delivery_status,created_at) "
                   "VALUES (?,'MAIL_REVIEW_REQUIRED',?,'cli','PENDING',?)",
                   (str(uuid.uuid4()), json.dumps({"decision_id": decision_id, "application_id": application_id}), timestamp))
        db.commit()
        return {"message_id": message_id, "decision_id": decision_id, "status": "review_required"}
    except Exception:
        db.rollback()
        raise


def decide_mail_review_in_transaction(db: sqlite3.Connection, decision_id: str, *, approve: bool, channel: str) -> str:
    decision = db.execute("SELECT * FROM master_decisions WHERE id=? AND decision_type='MAIL_REVIEW'",
                          (decision_id,)).fetchone()
    if (not decision or decision["decision_status"] != "PENDING" or channel not in ("cli", "web")
            or decision["authorized_channel"] not in ("local", channel)
            or decision["authorized_principal"] != "local-owner"):
        raise ValueError("Mail review is missing, finalized or unauthorized")
    evidence = db.execute("SELECT * FROM mail_review_evidence WHERE decision_id=?", (decision_id,)).fetchone()
    if not evidence:
        raise ValueError("Mail review evidence is missing")
    payload = json.loads(decision["payload_json"])
    if (payload.get("message_id") != evidence["message_id"] or
            payload.get("application_id") != evidence["application_id"] or
            payload.get("proposed_classification") != evidence["proposed_classification"] or
            payload.get("content_sha256") != evidence["content_sha256"] or
            payload.get("prior_status") != evidence["prior_application_status"]):
        raise ValueError("Mail review evidence changed")
    message = db.execute("SELECT gmail_account_id,gmail_message_id,gmail_thread_id,sender,application_id "
                         "FROM mailbox_messages WHERE id=?", (evidence["message_id"],)).fetchone()
    if (not message or not message["gmail_account_id"].startswith("hermes:")
            or message["gmail_message_id"] != payload.get("gmail_message_id")
            or message["gmail_thread_id"] != payload.get("thread_id") or message["sender"] != payload.get("sender")
            or message["application_id"] != evidence["application_id"]):
        raise ValueError("Mail review message context changed")
    timestamp = now()
    status = "APPROVED" if approve else "REJECTED"
    if approve:
        app = db.execute("SELECT status FROM applications WHERE id=?", (evidence["application_id"],)).fetchone()
        if not app or app["status"] != evidence["prior_application_status"] or app["status"] not in TRACKABLE:
            raise ValueError("Application changed after the email was reviewed; reassess it")
        next_status = TRANSITIONS[evidence["proposed_classification"]]
        db.execute("UPDATE mailbox_messages SET classification=?,confidence=1.0,correlation_confidence=1.0 "
                   "WHERE id=?", (evidence["proposed_classification"], evidence["message_id"]))
        db.execute("UPDATE applications SET status=?,phase='TRACKING',updated_at=? WHERE id=?",
                   (next_status, timestamp, evidence["application_id"]))
        db.execute("INSERT INTO application_events (id,application_id,event_type,from_status,to_status,"
                   "actor_type,actor_id,correlation_id,evidence_ref,created_at) "
                   "VALUES (?,?,'MAIL_REVIEW_APPROVED',?,?,?, 'local-owner',?,?,?)",
                   (str(uuid.uuid4()), evidence["application_id"], app["status"], next_status, channel,
                    str(uuid.uuid4()), "message:" + evidence["message_id"], timestamp))
    db.execute("UPDATE master_decisions SET decision_status=?,decided_at=? WHERE id=?", (status, timestamp, decision_id))
    return status
