"""Portable data export, without reading or exposing integration credentials."""

import csv
import io
import json
import sqlite3

TABLES = (
    "master_profile", "professional_profiles", "knowledge_claims", "documents", "search_runs",
    "job_postings", "applications", "submission_attempts", "mailbox_messages", "gmail_cursors",
    "reply_proposals", "reply_attempts", "master_decisions", "application_events", "job_locks", "event_outbox",
    "connector_health", "sandbox_preparations", "http_idempotency", "config_revisions", "mail_review_evidence",
    "site_policy_reviews", "site_policy_consents", "reply_dispatches", "scheduled_jobs", "mail_review_queue",
)


def export_data(db: sqlite3.Connection, format_name: str) -> str:
    """Export a consistent snapshot. Original CV files are not embedded."""
    if format_name not in ("json", "csv"):
        raise ValueError("Export format must be json or csv")
    db.execute("BEGIN")
    try:
        data = {table: [dict(row) for row in db.execute(f'SELECT * FROM "{table}"').fetchall()]
                for table in TABLES}
        db.commit()
    except Exception:
        db.rollback()
        raise
    if format_name == "json":
        return json.dumps({"format_version": 1, "tables": data}, ensure_ascii=False, indent=2)
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(("table", "row_json"))
    for table, rows in data.items():
        for row in rows:
            writer.writerow((table, json.dumps(row, ensure_ascii=False)))
    return output.getvalue()
