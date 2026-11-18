"""Run inside Hermes' Python environment; never expose OAuth tokens to PandApply.

This adapter targets the `build_service` and normalization functions present in the
verified Hermes Workspace skill. Missing or changed interfaces fail closed.
"""

import base64
import hashlib
import json
import re
import runpy
import sqlite3
import sys
import uuid
from contextlib import closing
from datetime import UTC, datetime
from email.mime.text import MIMEText
from email.utils import getaddresses, parseaddr
from pathlib import Path


def _claim_reply(database: str, attempt_id: str) -> dict:
    """Revalidate and atomically consume the persisted permit before any send."""
    if str(uuid.UUID(attempt_id)) != attempt_id:
        raise ValueError("Invalid attempt ID")
    with closing(sqlite3.connect(Path(database).resolve(strict=True).as_uri() + "?mode=rw", uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("BEGIN IMMEDIATE")
        try:
            config_row = db.execute("SELECT config_json FROM config_revisions ORDER BY id DESC LIMIT 1").fetchone()
            config = json.loads(config_row[0]) if config_row else {}
            if (config.get("gmail_enabled") is not True or config.get("gmail_reply_enabled") is not True
                    or config.get("dry_run") is not False):
                raise ValueError("Real Gmail replies are disabled")
            row = db.execute("SELECT a.id AS attempt_id,a.body_sha256,a.attempt_status,p.id AS proposal_id,"
                             "p.text_body,p.text_sha256,p.state,p.recipient,m.id AS local_message_id,m.gmail_account_id,"
                             "m.gmail_message_id,m.gmail_thread_id,m.sender,m.application_id,m.classification,"
                             "d.payload_json,d.decision_status,d.authorized_channel,d.authorized_principal,d.expires_at,"
                             "e.content_sha256,e.application_id AS review_application_id,"
                             "e.proposed_classification,r.decision_status AS review_status,"
                             "r.payload_json AS review_payload,r.related_entity_id AS reviewed_message_id,"
                             "r.authorized_principal AS review_principal,r.authorized_channel AS review_channel "
                             "FROM reply_attempts a JOIN reply_proposals p ON p.id=a.proposal_id "
                             "JOIN mailbox_messages m ON m.id=p.mailbox_message_id "
                             "JOIN master_decisions d ON d.id=p.approved_by_decision_id "
                             "AND d.decision_type='REPLY_APPROVAL' AND d.related_entity_id=p.id "
                             "JOIN mail_review_evidence e ON e.message_id=m.id "
                             "JOIN master_decisions r ON r.id=e.decision_id AND r.decision_type='MAIL_REVIEW' "
                             "WHERE a.id=?", (attempt_id,)).fetchone()
            if (not row or row["attempt_status"] != "SENDING" or row["state"] != "SENDING"
                    or row["decision_status"] != "APPROVED" or row["review_status"] != "APPROVED"
                    or row["authorized_principal"] != "local-owner"
                    or row["review_principal"] != "local-owner" or row["review_channel"] not in ("local", "cli", "web")
                    or row["authorized_channel"] not in ("local", "cli", "web") or not row["classification"]):
                raise ValueError("Reply is not authorized")
            if not row["expires_at"] or datetime.fromisoformat(row["expires_at"]) <= datetime.now(UTC):
                raise ValueError("Reply approval expired")
            binding = json.loads(row["payload_json"])
            review = json.loads(row["review_payload"])
            body = row["text_body"]
            account = binding.get("primary_account", "")
            recipient = row["recipient"]
            if (not isinstance(body, str) or not 0 < len(body) <= 10_000 or not isinstance(account, str)
                    or not isinstance(recipient, str) or any(ch in account + recipient for ch in "\r\n\x00")):
                raise ValueError("Invalid approved content")
            address = parseaddr(account)[1]
            sender = parseaddr(recipient)[1]
            account_id = "hermes:" + hashlib.sha256(address.casefold().encode()).hexdigest()
            body_hash = hashlib.sha256(body.encode()).hexdigest()
            if (not address or address.casefold() != account.strip().casefold() or not sender
                    or sender.casefold() != recipient.strip().casefold() or recipient != row["sender"]
                    or account_id != row["gmail_account_id"] or binding.get("account_id") != account_id
                    or body_hash != row["body_sha256"] or body_hash != row["text_sha256"]
                    or body_hash != binding.get("body_sha256") or row["content_sha256"] != binding.get("source_sha256")
                    or row["review_application_id"] != row["application_id"]
                    or row["reviewed_message_id"] != row["local_message_id"]
                    or row["reviewed_message_id"] != review.get("message_id")
                    or row["review_application_id"] != review.get("application_id")
                    or row["proposed_classification"] != row["classification"]
                    or row["proposed_classification"] != review.get("proposed_classification")
                    or row["content_sha256"] != review.get("content_sha256")
                    or row["gmail_message_id"] != review.get("gmail_message_id")
                    or row["gmail_thread_id"] != review.get("thread_id") or row["sender"] != review.get("sender")
                    or row["gmail_thread_id"] != binding.get("thread_id")
                    or row["gmail_message_id"] != binding.get("message_id") or recipient != binding.get("recipient")):
                raise ValueError("Approved reply context changed")
            db.execute("INSERT INTO reply_dispatches (attempt_id,claimed_at) VALUES (?,?)",
                       (attempt_id, datetime.now(UTC).isoformat()))
            db.commit()
            return {"account_hash": account_id.removeprefix("hermes:"), "message_id": row["gmail_message_id"],
                    "thread_id": row["gmail_thread_id"], "recipient": recipient,
                    "source_sha256": row["content_sha256"], "body": body, "attempt_id": attempt_id}
        except Exception:
            db.rollback()
            raise


def main() -> int:
    try:
        request = json.load(sys.stdin)
        if request.get("action") == "send_approved":
            request = {"action": "send_approved", **_claim_reply(request["database"], request["attempt_id"])}
        script = Path(sys.argv[1]).resolve(strict=True)
        module = runpy.run_path(str(script), run_name="_pandapply_workspace_adapter")
        service = module["build_service"]("gmail", "v1")
        users = service.users()
        profile = users.getProfile(userId="me").execute()
        email = profile.get("emailAddress")
        address = parseaddr(email)[1] if isinstance(email, str) else ""
        if not address or "@" not in address or address.casefold() != email.strip().casefold():
            raise ValueError("Invalid authenticated email")
        if request["action"] == "profile":
            print(json.dumps({"emailAddress": address}))
            return 0
        account_hash = hashlib.sha256(address.casefold().encode()).hexdigest()
        if account_hash != request["account_hash"]:
            raise ValueError("Authenticated Gmail account does not match the selected account")
        if request["action"] == "search":
            result = users.messages().list(userId="me", q=request["query"], maxResults=request["limit"]).execute()
            output = []
            for metadata in result.get("messages", []):
                message = users.messages().get(userId="me", id=metadata["id"], format="metadata",
                                               metadataHeaders=["From", "To", "Subject", "Date"]).execute()
                headers = module["_headers_dict"](message)
                output.append({"id": message["id"], "threadId": message["threadId"],
                               "from": headers.get("from", ""), "to": headers.get("to", ""),
                               "subject": headers.get("subject", ""), "date": headers.get("date", ""),
                               "snippet": message.get("snippet", ""), "labels": message.get("labelIds", [])})
        elif request["action"] == "get":
            message = users.messages().get(userId="me", id=request["message_id"], format="full").execute()
            headers = module["_headers_dict"](message)
            output = {"id": message["id"], "threadId": message["threadId"], "from": headers.get("from", ""),
                      "to": headers.get("to", ""), "subject": headers.get("subject", ""),
                      "date": headers.get("date", ""), "labels": message.get("labelIds", []),
                      "body": module["_extract_message_body"](message)}
        elif request["action"] == "send_approved":
            message = users.messages().get(userId="me", id=request["message_id"], format="full").execute(num_retries=0)
            headers = module["_headers_dict"](message)
            original = {"id": message["id"], "threadId": message["threadId"], "from": headers.get("from", ""),
                        "subject": headers.get("subject", ""), "body": module["_extract_message_body"](message),
                        "date": headers.get("date", "")}
            content = json.dumps(original, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            sender = parseaddr(original["from"])[1]
            if (original["id"] != request["message_id"] or original["threadId"] != request["thread_id"]
                    or not sender or sender.casefold() != request["recipient"].casefold()
                    or hashlib.sha256(content.encode()).hexdigest() != request["source_sha256"]):
                raise ValueError("Original message no longer matches the approved context")
            subject = original["subject"]
            header_id = headers.get("message-id", "")
            if any(char in subject + header_id + sender for char in "\r\n\x00"):
                raise ValueError("Invalid message header")
            addresses = getaddresses([original["from"]])
            reply_to = getaddresses([headers["reply-to"]]) if headers.get("reply-to") else []
            if (len(addresses) != 1 or addresses[0][1].casefold() != sender.casefold()
                    or (reply_to and (len(reply_to) != 1 or reply_to[0][1].casefold() != sender.casefold()))
                    or not re.fullmatch(r"<[^<>\s@]+@[^<>\s@]+>", header_id)):
                raise ValueError("Original message has an ambiguous reply target or missing Message-ID")
            if not subject.casefold().startswith("re:"):
                subject = "Re: " + subject
            reply = MIMEText(request["body"], "plain", "utf-8")
            reply["From"] = address
            reply["To"] = sender
            reply["Subject"] = subject
            reply["Message-ID"] = f"<pandapply.{request['attempt_id']}@pandapply.invalid>"
            reply["In-Reply-To"] = header_id
            reply["References"] = header_id
            raw = base64.urlsafe_b64encode(reply.as_bytes()).decode("ascii")
            sent = users.messages().send(userId="me", body={"raw": raw, "threadId": original["threadId"]}).execute(num_retries=0)
            if not sent.get("id") or sent.get("threadId") != original["threadId"]:
                raise ValueError("Gmail did not return an unambiguous reply receipt")
            output = {"id": sent["id"], "threadId": sent["threadId"]}
        elif request["action"] == "reconcile_reply":
            attempt_id = request["attempt_id"]
            if str(uuid.UUID(attempt_id)) != attempt_id:
                raise ValueError("Invalid attempt ID")
            header_id = f"<pandapply.{attempt_id}@pandapply.invalid>"
            matches = users.messages().list(userId="me", q=f"in:sent rfc822msgid:{header_id}", maxResults=2).execute(num_retries=0)
            candidates = matches.get("messages", [])
            if len(candidates) != 1 or matches.get("nextPageToken"):
                output = {"status": "unknown"}
            else:
                sent = users.messages().get(userId="me", id=candidates[0]["id"], format="full").execute(num_retries=0)
                headers = module["_headers_dict"](sent)
                recipients = getaddresses([headers.get("to", "")])
                senders = getaddresses([headers.get("from", "")])
                body = module["_extract_message_body"](sent)
                valid = (sent.get("threadId") == request["thread_id"] and "SENT" in sent.get("labelIds", [])
                         and headers.get("message-id") == header_id and len(recipients) == 1 and len(senders) == 1
                         and recipients[0][1].casefold() == request["recipient"].casefold()
                         and senders[0][1].casefold() == address.casefold() and not headers.get("cc")
                         and not headers.get("bcc") and hashlib.sha256(body.encode()).hexdigest() == request["body_sha256"])
                output = {"status": "found", "id": sent["id"]} if valid else {"status": "unknown"}
        else:
            raise ValueError("Unsupported operation")
        print(json.dumps(output, ensure_ascii=False))
        return 0
    except Exception:  # noqa: BLE001 - provider errors may contain secrets or private message content
        # Third-party errors may contain private messages or OAuth details.
        print("Hermes account verification or Gmail read failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
