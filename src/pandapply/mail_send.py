"""Explicitly approved Gmail replies through a one-use Hermes dispatch permit."""

import hashlib
import json
import uuid
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from pandapply.configuration import read_settings
from pandapply.hermes_workspace import HermesWorkspaceReader
from pandapply.mail import MailBlocked, MailOutcomeUnknown
from pandapply.storage import connect, now


def _record_reply_event(db, proposal_id: str, attempt_id: str, message_id: str) -> None:
    row = db.execute("SELECT a.id,a.status FROM reply_proposals p JOIN mailbox_messages m ON m.id=p.mailbox_message_id "
                     "JOIN applications a ON a.id=m.application_id WHERE p.id=?", (proposal_id,)).fetchone()
    if not row:
        raise MailBlocked("Reply application is no longer available")
    timestamp = now()
    payload = json.dumps({"proposal_id": proposal_id, "sent_message_id": message_id})
    db.execute("INSERT INTO application_events (id,application_id,event_type,from_status,to_status,actor_type,"
               "actor_id,correlation_id,evidence_ref,payload_redacted_json,created_at) "
               "VALUES (?,?,'GMAIL_REPLY_SENT',?,?,'owner','local-owner',?,?,?,?)",
               (str(uuid.uuid4()), row["id"], row["status"], row["status"], attempt_id,
                "gmail:" + message_id, payload, timestamp))
    db.execute("INSERT INTO event_outbox (id,event_type,payload_redacted_json,destination,delivery_status,created_at) "
               "VALUES (?,'GMAIL_REPLY_SENT',?,'cli','PENDING',?)", (str(uuid.uuid4()), payload, timestamp))


def send_approved(database: Path, proposal_id: str, *, interpreter: Path, script: Path, confirm: bool) -> str:
    if not confirm:
        raise MailBlocked("Explicit confirmation is required to send the approved reply")
    with closing(connect(database)) as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            settings = read_settings(db, database.parent / "config.json")
            transport = HermesWorkspaceReader(interpreter, script,
                                              home=Path(settings.hermes_home) if settings.hermes_home else None)
            if not settings.gmail_enabled or not settings.gmail_reply_enabled or settings.dry_run:
                raise MailBlocked("Enable Gmail and approved replies and disable dry-run before sending")
            if not db.execute("SELECT 1 FROM config_revisions LIMIT 1").fetchone():
                raise MailBlocked("Persist the Gmail configuration before sending")
            row = db.execute("SELECT p.*,m.gmail_account_id,m.gmail_message_id,m.gmail_thread_id,m.sender,"
                             "d.decision_status,d.payload_json,d.authorized_channel,d.authorized_principal,d.expires_at,"
                             "e.content_sha256,r.decision_status AS review_status FROM reply_proposals p "
                             "JOIN mailbox_messages m ON m.id=p.mailbox_message_id "
                             "JOIN master_decisions d ON d.id=p.approved_by_decision_id "
                             "AND d.related_entity_id=p.id AND d.decision_type='REPLY_APPROVAL' "
                             "JOIN mail_review_evidence e ON e.message_id=m.id "
                             "JOIN master_decisions r ON r.id=e.decision_id WHERE p.id=?", (proposal_id,)).fetchone()
            if (not row or row["state"] != "APPROVED" or row["decision_status"] != "APPROVED"
                    or row["review_status"] != "APPROVED" or row["authorized_principal"] != "local-owner"
                    or row["authorized_channel"] not in ("local", "cli", "web")
                    or not row["gmail_account_id"].startswith("hermes:")):
                raise MailBlocked("An approved real Gmail reply and message review are required")
            if not row["expires_at"] or datetime.fromisoformat(row["expires_at"]) <= datetime.now(UTC):
                raise MailBlocked("Reply approval has expired; create a new proposal")
            binding = json.loads(row["payload_json"])
            body_hash = hashlib.sha256(row["text_body"].encode()).hexdigest()
            if (body_hash != row["text_sha256"] or body_hash != binding.get("body_sha256")
                    or row["gmail_account_id"] != binding.get("account_id")
                    or row["gmail_message_id"] != binding.get("message_id")
                    or row["gmail_thread_id"] != binding.get("thread_id")
                    or row["recipient"] != binding.get("recipient") or row["recipient"] != row["sender"]
                    or row["content_sha256"] != binding.get("source_sha256")):
                raise MailBlocked("The approved reply context changed")
            prior = db.execute("SELECT 1 FROM reply_attempts a JOIN reply_proposals p ON p.id=a.proposal_id "
                               "WHERE p.mailbox_message_id=? AND a.attempt_status IN ('SENDING','SENT','UNKNOWN')",
                               (row["mailbox_message_id"],)).fetchone()
            if prior:
                raise MailBlocked("A reply already exists or needs reconciliation")
            attempt, timestamp = str(uuid.uuid4()), now()
            db.execute("INSERT INTO reply_attempts (id,proposal_id,idempotency_key,body_sha256,attempt_status,initiated_at) "
                       "VALUES (?,?,?,?,'SENDING',?)", (attempt, proposal_id, attempt, body_hash, timestamp))
            db.execute("UPDATE reply_proposals SET state='SENDING',updated_at=? WHERE id=?", (timestamp, proposal_id))
            db.commit()
        except Exception:
            db.rollback()
            raise
        try:
            receipt = transport.dispatch_approved(database, attempt)
            if receipt.get("threadId") != row["gmail_thread_id"]:
                raise ValueError("Reply receipt thread does not match the approved thread")
        except Exception as exc:
            try:
                with db:
                    db.execute("UPDATE reply_attempts SET attempt_status='UNKNOWN',completed_at=? "
                               "WHERE id=? AND attempt_status='SENDING'", (now(), attempt))
                    db.execute("UPDATE reply_proposals SET state='SEND_UNKNOWN',updated_at=? "
                               "WHERE id=? AND state='SENDING'", (now(), proposal_id))
            except Exception as persist_exc:
                raise MailOutcomeUnknown("Reply outcome is uncertain and local state could not be updated; reconcile") from persist_exc
            raise MailOutcomeUnknown("Reply outcome is uncertain; do not resend without reconciliation") from exc
        try:
            with db:
                changed = db.execute("UPDATE reply_attempts SET attempt_status='SENT',external_message_id=?,completed_at=? "
                                     "WHERE id=? AND attempt_status='SENDING'", (receipt["id"], now(), attempt)).rowcount
                if changed != 1:
                    raise MailOutcomeUnknown("Reply state changed during dispatch; reconcile before further action")
                updated = db.execute("UPDATE reply_proposals SET state='SENT',sent_gmail_message_id=?,updated_at=? "
                                     "WHERE id=? AND state='SENDING'", (receipt["id"], now(), proposal_id)).rowcount
                if updated != 1:
                    raise MailOutcomeUnknown("Reply state changed during dispatch; reconcile before further action")
                _record_reply_event(db, proposal_id, attempt, receipt["id"])
        except Exception as exc:
            raise MailOutcomeUnknown("Reply was sent but its local receipt could not be recorded; reconcile") from exc
        return receipt["id"]


def reconcile_unknown(database: Path, proposal_id: str, *, interpreter: Path, script: Path) -> dict:
    """Search the approved account's sent mail; never sends or clears uncertainty without evidence."""
    with closing(connect(database)) as db:
        settings = read_settings(db, database.parent / "config.json")
        transport = HermesWorkspaceReader(interpreter, script,
                                          home=Path(settings.hermes_home) if settings.hermes_home else None)
        db.execute("BEGIN IMMEDIATE")
        try:
            row = db.execute("SELECT a.id AS attempt_id,a.attempt_status,a.body_sha256,p.state,p.text_body,p.text_sha256,"
                             "p.recipient,m.gmail_account_id,m.gmail_thread_id,d.payload_json,d.decision_status "
                             "FROM reply_proposals p JOIN reply_attempts a ON a.proposal_id=p.id "
                             "JOIN mailbox_messages m ON m.id=p.mailbox_message_id "
                             "JOIN master_decisions d ON d.id=p.approved_by_decision_id "
                             "AND d.decision_type='REPLY_APPROVAL' AND d.related_entity_id=p.id "
                             "WHERE p.id=? AND a.attempt_status IN ('SENDING','UNKNOWN') ORDER BY a.initiated_at DESC LIMIT 1",
                             (proposal_id,)).fetchone()
            if (not row or row["state"] not in ("SENDING", "SEND_UNKNOWN") or row["decision_status"] != "APPROVED"
                    or not row["gmail_account_id"].startswith("hermes:")):
                raise MailBlocked("No uncertain real Gmail reply to reconcile")
            binding = json.loads(row["payload_json"])
            account = binding.get("primary_account", "")
            digest = hashlib.sha256(row["text_body"].encode()).hexdigest()
            if (not account or "hermes:" + hashlib.sha256(account.casefold().encode()).hexdigest() != row["gmail_account_id"]
                    or digest != row["body_sha256"] or digest != row["text_sha256"] or digest != binding.get("body_sha256")
                    or row["recipient"] != binding.get("recipient") or row["gmail_thread_id"] != binding.get("thread_id")):
                raise MailBlocked("Approved reply context changed")
            if row["attempt_status"] == "SENDING":
                db.execute("UPDATE reply_attempts SET attempt_status='UNKNOWN',completed_at=? WHERE id=?",
                           (now(), row["attempt_id"]))
                db.execute("UPDATE reply_proposals SET state='SEND_UNKNOWN',updated_at=? WHERE id=?", (now(), proposal_id))
            db.commit()
        except Exception:
            db.rollback()
            raise
        result = transport.find_reply(account, attempt_id=row["attempt_id"], thread_id=row["gmail_thread_id"],
                                      recipient=row["recipient"], body_sha256=digest)
        if result["status"] != "found":
            return {"status": "SEND_UNKNOWN", "resent": False}
        db.execute("BEGIN IMMEDIATE")
        try:
            current = db.execute("SELECT a.attempt_status,p.state,p.text_body,p.text_sha256,p.recipient,m.gmail_thread_id "
                                 "FROM reply_attempts a JOIN reply_proposals p ON p.id=a.proposal_id "
                                 "JOIN mailbox_messages m ON m.id=p.mailbox_message_id WHERE a.id=? AND p.id=?",
                                 (row["attempt_id"], proposal_id)).fetchone()
            if (not current or current["attempt_status"] != "UNKNOWN" or current["state"] != "SEND_UNKNOWN"
                    or hashlib.sha256(current["text_body"].encode()).hexdigest() != digest
                    or current["text_sha256"] != digest or current["recipient"] != row["recipient"]
                    or current["gmail_thread_id"] != row["gmail_thread_id"]):
                raise MailBlocked("Reply changed during reconciliation")
            db.execute("UPDATE reply_attempts SET attempt_status='SENT',external_message_id=?,completed_at=? WHERE id=?",
                       (result["id"], now(), row["attempt_id"]))
            db.execute("UPDATE reply_proposals SET state='SENT',sent_gmail_message_id=?,updated_at=? WHERE id=?",
                       (result["id"], now(), proposal_id))
            _record_reply_event(db, proposal_id, row["attempt_id"], result["id"])
            db.commit()
        except Exception:
            db.rollback()
            raise
        return {"status": "SENT", "message_id": result["id"], "resent": False}
