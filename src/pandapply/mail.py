"""Local, simulated mail workflow. No real Gmail transport is implemented here."""

import hashlib
import json
import re
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.utils import parseaddr

from pandapply.storage import now


class MailBlocked(ValueError):
    pass


class MailOutcomeUnknown(RuntimeError):
    pass


@dataclass
class FakeGmail:
    """Test-only transport with an injectable failure after accepting a reply."""

    fail_after_send: bool = False
    sent: dict = field(default_factory=dict)

    def reply(self, *, thread_id: str, message_id: str, recipient: str, body: str,
              idempotency_key: str) -> str:
        if idempotency_key not in self.sent:
            self.sent[idempotency_key] = {"id": "fake-" + str(uuid.uuid4()), "thread_id": thread_id,
                                          "message_id": message_id, "recipient": recipient, "body": body}
        if self.fail_after_send:
            raise ConnectionError("Simulated loss after fake Gmail accepted the message")
        return self.sent[idempotency_key]["id"]


def _classify(subject: str, body: str, application_ref: str | None) -> str:
    if not application_ref:
        return "unrelated"
    text = (subject + "\n" + body).casefold()
    if "interview" in text:
        return "interview"
    if "will not proceed" in text:
        return "rejection"
    if "received your application" in text:
        return "application_received"
    return "ambiguous"


def ingest_fixture(db: sqlite3.Connection, messages: list[dict]) -> list[dict]:
    """Classify synthetic data. Only exact unique ATS IDs can affect an application."""
    results = []
    for message in messages:
        message_id = message.get("id")
        thread_id = message.get("thread_id")
        sender = message.get("from")
        subject = message.get("subject", "")
        body = message.get("body", "")
        ref = message.get("application_ref")
        if (not all(isinstance(value, str) and value for value in (message_id, thread_id, sender))
                or not isinstance(subject, str) or not isinstance(body, str)
                or (ref is not None and not isinstance(ref, str))
                or not re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.test", sender, re.IGNORECASE)):
            raise ValueError("Synthetic mail requires IDs, a .test sender and string content")
        if len(body) > 200_000 or len(subject) > 1000:
            raise ValueError("Synthetic message exceeds size limit")
        classification = _classify(subject, body, ref)
        db.execute("BEGIN IMMEDIATE")
        try:
            duplicate = db.execute("SELECT id FROM mailbox_messages WHERE gmail_account_id='fixture' "
                                   "AND gmail_message_id=?", (message_id,)).fetchone()
            if duplicate:
                db.commit()
                results.append({"id": message_id, "status": "duplicate"})
                continue
            candidates = []
            if ref:
                candidates = db.execute("SELECT a.id,a.status FROM applications a JOIN job_postings j "
                                        "ON j.id=a.job_posting_id WHERE j.ats_provider='fixture' "
                                        "AND j.ats_requisition_id=? AND a.status IN "
                                        "('SUBMITTED','ACKNOWLEDGED','IN_PROCESS','INTERVIEW')", (ref,)).fetchall()
            app = candidates[0] if len(candidates) == 1 else None
            timestamp = now()
            local_id = str(uuid.uuid4())
            db.execute("INSERT INTO mailbox_messages (id,gmail_account_id,gmail_message_id,gmail_thread_id,"
                       "sender,sent_at,classification,confidence,application_id,correlation_confidence,processed_at) "
                       "VALUES (?,'fixture',?,?,?,?,?, ?,?,?,?)",
                       (local_id, message_id, thread_id, sender, timestamp, classification, 1.0,
                        app["id"] if app else None, 1.0 if app else None, timestamp))
            transitions = {"application_received": "ACKNOWLEDGED", "rejection": "REJECTED",
                           "interview": "INTERVIEW"}
            next_status = transitions.get(classification) if app else None
            if app and app["status"] != "SUBMITTED" and classification == "application_received":
                next_status = None
            if next_status and app["status"] != next_status:
                db.execute("UPDATE applications SET status=?,phase='TRACKING',updated_at=? WHERE id=?",
                           (next_status, timestamp, app["id"]))
                db.execute("INSERT INTO application_events (id,application_id,event_type,from_status,to_status,"
                           "actor_type,correlation_id,evidence_ref,created_at) VALUES (?,?,?,?,?,'system',?,?,?)",
                           (str(uuid.uuid4()), app["id"], "MAIL_CLASSIFIED", app["status"], next_status,
                            str(uuid.uuid4()), "message:" + local_id, timestamp))
                if classification in ("interview", "rejection"):
                    db.execute("INSERT INTO event_outbox (id,event_type,payload_redacted_json,destination,"
                               "delivery_status,created_at) VALUES (?,?,?,'cli','PENDING',?)",
                               (str(uuid.uuid4()), "MAIL_" + classification.upper(),
                                json.dumps({"message_id": local_id, "application_id": app["id"]}), timestamp))
            db.commit()
            results.append({"id": message_id, "local_id": local_id, "classification": classification,
                            "application_id": app["id"] if app else None,
                            "status": next_status or "unresolved"})
        except Exception:
            db.rollback()
            raise
    return results


def propose_reply(db: sqlite3.Connection, message_id: str, text: str, *, account: str | None = None) -> tuple[str, str]:
    """Create a draft only in response to an explicit local-owner request."""
    text = text.strip()
    if not text or len(text) > 10_000:
        raise ValueError("Reply must contain 1–10000 characters")
    db.execute("BEGIN IMMEDIATE")
    try:
        message = db.execute("SELECT * FROM mailbox_messages WHERE id=?", (message_id,)).fetchone()
        if not message or not message["application_id"]:
            raise MailBlocked("Message is not uniquely associated with an application")
        binding = {}
        if message["gmail_account_id"] != "fixture":
            if not message["gmail_account_id"].startswith("hermes:") or not account:
                raise MailBlocked("A reviewed Gmail message and its primary account are required")
            address = parseaddr(account)[1]
            if (not address or address.casefold() != account.strip().casefold() or
                    "hermes:" + hashlib.sha256(address.casefold().encode()).hexdigest() != message["gmail_account_id"]):
                raise MailBlocked("The primary account does not match the reviewed message")
            review = db.execute("SELECT e.content_sha256 FROM mail_review_evidence e JOIN master_decisions d "
                                "ON d.id=e.decision_id WHERE e.message_id=? AND d.decision_status='APPROVED'",
                                (message_id,)).fetchone()
            if not review or not message["classification"]:
                raise MailBlocked("The owner must approve the original mail review first")
            binding = {"primary_account": address, "account_id": message["gmail_account_id"],
                       "source_sha256": review["content_sha256"]}
        proposal_id, decision_id, timestamp = str(uuid.uuid4()), str(uuid.uuid4()), now()
        expires_at = (datetime.now(UTC) + timedelta(hours=24)).isoformat()
        digest = hashlib.sha256(text.encode()).hexdigest()
        db.execute("INSERT INTO reply_proposals (id,mailbox_message_id,recipient,text_body,text_sha256,state,"
                   "created_at,updated_at) VALUES (?,?,?,?,?,'PENDING_APPROVAL',?,?)",
                   (proposal_id, message_id, message["sender"], text, digest, timestamp, timestamp))
        db.execute("INSERT INTO master_decisions (id,decision_type,related_entity_type,related_entity_id,"
                   "payload_json,decision_status,authorized_channel,authorized_principal,created_at,expires_at) "
                   "VALUES (?,'REPLY_APPROVAL','reply_proposal',?,?,'PENDING','local','local-owner',?,?)",
                   (decision_id, proposal_id, json.dumps({"body_sha256": digest, "thread_id": message["gmail_thread_id"],
                                                          "message_id": message["gmail_message_id"],
                                                          "recipient": message["sender"], **binding}), timestamp, expires_at))
        db.commit()
        return proposal_id, decision_id
    except Exception:
        db.rollback()
        raise


def decide_reply_in_transaction(db: sqlite3.Connection, decision_id: str, *, approve: bool, channel: str) -> str:
    row = db.execute("SELECT * FROM master_decisions WHERE id=? AND decision_type='REPLY_APPROVAL'",
                     (decision_id,)).fetchone()
    if (not row or row["decision_status"] != "PENDING" or channel not in ("cli", "web")
            or row["authorized_channel"] not in ("local", channel) or row["authorized_principal"] != "local-owner"):
        raise MailBlocked("Reply decision is missing, finalized or unauthorized")
    if not row["expires_at"] or datetime.fromisoformat(row["expires_at"]) <= datetime.now(UTC):
        raise MailBlocked("Reply approval has expired; create a new proposal")
    proposal = db.execute("SELECT * FROM reply_proposals WHERE id=?", (row["related_entity_id"],)).fetchone()
    if not proposal or proposal["state"] != "PENDING_APPROVAL":
        raise MailBlocked("Reply proposal is not awaiting approval")
    if hashlib.sha256(proposal["text_body"].encode()).hexdigest() != json.loads(row["payload_json"])["body_sha256"]:
        raise MailBlocked("Reply text changed after proposal")
    timestamp = now()
    state = "APPROVED" if approve else "REJECTED"
    db.execute("UPDATE master_decisions SET decision_status=?,decided_at=? WHERE id=?", (state, timestamp, decision_id))
    db.execute("UPDATE reply_proposals SET state=?,approved_by_decision_id=?,updated_at=? WHERE id=?",
               (state, decision_id if approve else None, timestamp, proposal["id"]))
    return state


def decide_reply(db: sqlite3.Connection, decision_id: str, *, approve: bool) -> str:
    db.execute("BEGIN IMMEDIATE")
    try:
        state = decide_reply_in_transaction(db, decision_id, approve=approve, channel="cli")
        db.commit()
        return state
    except Exception:
        db.rollback()
        raise


def send_fake_reply(db: sqlite3.Connection, proposal_id: str, transport: FakeGmail) -> str:
    """Persist the attempt before calling the explicitly simulated transport."""
    if type(transport) is not FakeGmail:
        raise MailBlocked("Only the built-in fake Gmail transport is supported")
    db.execute("BEGIN IMMEDIATE")
    try:
        row = db.execute("SELECT p.*,m.gmail_account_id,m.gmail_thread_id,m.gmail_message_id,m.sender,"
                         "d.decision_status,d.payload_json,d.authorized_channel,d.authorized_principal,d.expires_at "
                         "FROM reply_proposals p JOIN mailbox_messages m ON m.id=p.mailbox_message_id "
                         "LEFT JOIN master_decisions d ON d.id=p.approved_by_decision_id "
                         "AND d.related_entity_id=p.id AND d.decision_type='REPLY_APPROVAL' WHERE p.id=?",
                         (proposal_id,)).fetchone()
        if (not row or row["state"] != "APPROVED" or row["decision_status"] != "APPROVED"
                or row["authorized_channel"] not in ("local", "cli", "web") or row["authorized_principal"] != "local-owner"
                or row["gmail_account_id"] != "fixture"):
            raise MailBlocked("An approved synthetic reply is required")
        if not row["expires_at"] or datetime.fromisoformat(row["expires_at"]) <= datetime.now(UTC):
            raise MailBlocked("Reply approval has expired; create a new proposal")
        digest = hashlib.sha256(row["text_body"].encode()).hexdigest()
        binding = json.loads(row["payload_json"])
        if (digest != row["text_sha256"] or digest != binding.get("body_sha256")
                or row["gmail_thread_id"] != binding.get("thread_id")
                or row["gmail_message_id"] != binding.get("message_id")
                or row["recipient"] != binding.get("recipient") or row["recipient"] != row["sender"]):
            raise MailBlocked("Approved reply context changed")
        previous = db.execute("SELECT 1 FROM reply_attempts a JOIN reply_proposals p ON p.id=a.proposal_id "
                              "WHERE p.mailbox_message_id=? AND a.attempt_status IN ('SENDING','SENT','UNKNOWN')",
                              (row["mailbox_message_id"],)).fetchone()
        if previous:
            raise MailBlocked("A reply to this message already exists or needs reconciliation")
        attempt_id, timestamp = str(uuid.uuid4()), now()
        db.execute("INSERT INTO reply_attempts (id,proposal_id,idempotency_key,body_sha256,attempt_status,"
                   "initiated_at) VALUES (?,?,?,?,'SENDING',?)", (attempt_id, proposal_id, attempt_id, digest, timestamp))
        db.execute("UPDATE reply_proposals SET state='SENDING',updated_at=? WHERE id=?", (timestamp, proposal_id))
        db.commit()
    except Exception:
        db.rollback()
        raise
    try:
        external_id = transport.reply(thread_id=row["gmail_thread_id"], message_id=row["gmail_message_id"],
                                      recipient=row["recipient"], body=row["text_body"], idempotency_key=attempt_id)
        if not external_id:
            raise ValueError("Fake transport did not return a message ID")
    except Exception as exc:
        with db:
            db.execute("UPDATE reply_attempts SET attempt_status='UNKNOWN',completed_at=? WHERE id=?", (now(), attempt_id))
            db.execute("UPDATE reply_proposals SET state='SEND_UNKNOWN',updated_at=? WHERE id=?", (now(), proposal_id))
        raise MailOutcomeUnknown("The reply may have been sent; reconciliation is required") from exc
    with db:
        db.execute("UPDATE reply_attempts SET attempt_status='SENT',external_message_id=?,completed_at=? WHERE id=?",
                   (external_id, now(), attempt_id))
        db.execute("UPDATE reply_proposals SET state='SENT',sent_gmail_message_id=?,updated_at=? WHERE id=?",
                   (external_id, now(), proposal_id))
    return external_id


def recover_replies(db: sqlite3.Connection) -> int:
    db.execute("BEGIN IMMEDIATE")
    try:
        rows = db.execute("SELECT id,proposal_id FROM reply_attempts WHERE attempt_status='SENDING'").fetchall()
        for row in rows:
            db.execute("UPDATE reply_attempts SET attempt_status='UNKNOWN',completed_at=? WHERE id=?", (now(), row["id"]))
            db.execute("UPDATE reply_proposals SET state='SEND_UNKNOWN',updated_at=? WHERE id=?",
                       (now(), row["proposal_id"]))
        db.commit()
        return len(rows)
    except Exception:
        db.rollback()
        raise
