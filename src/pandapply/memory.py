"""Owner decisions for proposed professional facts, persisted transactionally."""

import json
import sqlite3
import uuid

from pandapply.storage import now


def propose_skill(db: sqlite3.Connection, profile_id: str, skill: str) -> str:
    skill = skill.strip()
    if not skill or len(skill) > 200:
        raise ValueError("Skill must have between 1 and 200 characters")
    proposal_id = str(uuid.uuid4())
    timestamp = now()
    with db:
        if not db.execute("SELECT 1 FROM professional_profiles WHERE id=?", (profile_id,)).fetchone():
            raise ValueError("Profile not found")
        db.execute("INSERT INTO master_decisions (id, decision_type, related_entity_type, "
                   "related_entity_id, payload_json, decision_status, authorized_channel, "
                   "authorized_principal, created_at) "
                   "VALUES (?, 'MEMORY_SKILL', 'professional_profile', ?, ?, 'PENDING', 'local', "
                   "'local-owner', ?)",
                   (proposal_id, profile_id, json.dumps({"skill": skill}, ensure_ascii=False), timestamp))
    return proposal_id


def decide_skill_in_transaction(db: sqlite3.Connection, proposal_id: str, *, approve: bool, channel: str) -> str:
    decision = db.execute("SELECT * FROM master_decisions WHERE id=?", (proposal_id,)).fetchone()
    if not decision or decision["decision_type"] != "MEMORY_SKILL":
        raise ValueError("Memory proposal not found")
    if decision["decision_status"] != "PENDING":
        raise ValueError("Memory proposal has already been decided")
    if (channel not in ("cli", "web") or decision["authorized_channel"] not in ("local", channel)
            or decision["authorized_principal"] != "local-owner"):
        raise ValueError("Decision is not authorized for this channel")
    timestamp = now()
    status = "APPROVED" if approve else "REJECTED"
    if approve:
        skill = json.loads(decision["payload_json"])["skill"]
        db.execute("INSERT INTO knowledge_claims (id,profile_id,claim_type,claim_json,source_uri,"
                   "verification_status,approval_id,created_at,updated_at) "
                   "VALUES (?,?,'skill',?,?,'master_confirmed',?,?,?)",
                   (str(uuid.uuid4()), decision["related_entity_id"],
                    json.dumps({"value": skill}, ensure_ascii=False), "master:" + channel,
                    proposal_id, timestamp, timestamp))
    db.execute("UPDATE master_decisions SET decision_status=?,decided_at=? WHERE id=?",
               (status, timestamp, proposal_id))
    return status


def decide_skill(db: sqlite3.Connection, proposal_id: str, *, approve: bool) -> str:
    db.execute("BEGIN IMMEDIATE")
    try:
        status = decide_skill_in_transaction(db, proposal_id, approve=approve, channel="cli")
        db.commit()
        return status
    except Exception:
        db.rollback()
        raise
