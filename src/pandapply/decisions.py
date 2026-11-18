"""Idempotent, transactionally recorded local-owner decisions."""

import hashlib
import json
import sqlite3

from pandapply.mail import decide_reply_in_transaction
from pandapply.mail_review import decide_mail_review_in_transaction
from pandapply.memory import decide_skill_in_transaction
from pandapply.storage import now


def respond(db: sqlite3.Connection, decision_id: str, *, action: str, key: str, channel: str) -> dict:
    if action not in ("approve", "reject"):
        raise ValueError("This decision requires approve or reject")
    if not key or len(key) > 200:
        raise ValueError("Idempotency key must contain 1–200 characters")
    request_hash = hashlib.sha256(json.dumps({"action": action, "channel": channel}, sort_keys=True).encode()).hexdigest()
    scope = "decision:" + decision_id
    db.execute("BEGIN IMMEDIATE")
    try:
        previous = db.execute("SELECT request_hash,response_json FROM http_idempotency WHERE scope=? AND key=?",
                              (scope, key)).fetchone()
        if previous:
            if previous["request_hash"] != request_hash:
                raise ValueError("Idempotency key reused with a different action")
            response = json.loads(previous["response_json"])
            db.commit()
            return response
        decision = db.execute("SELECT decision_type FROM master_decisions WHERE id=?", (decision_id,)).fetchone()
        if not decision:
            raise ValueError("Decision not found")
        if decision["decision_type"] == "MEMORY_SKILL":
            status = decide_skill_in_transaction(db, decision_id, approve=action == "approve", channel=channel)
        elif decision["decision_type"] == "REPLY_APPROVAL":
            status = decide_reply_in_transaction(db, decision_id, approve=action == "approve", channel=channel)
        elif decision["decision_type"] == "MAIL_REVIEW":
            status = decide_mail_review_in_transaction(db, decision_id, approve=action == "approve", channel=channel)
        else:
            raise ValueError("Decision type is not yet supported")
        response = {"id": decision_id, "status": status}
        db.execute("INSERT INTO http_idempotency (key,scope,request_hash,response_json,created_at) VALUES (?,?,?,?,?)",
                   (key, scope, request_hash, json.dumps(response), now()))
        db.commit()
        return response
    except Exception:
        db.rollback()
        raise
