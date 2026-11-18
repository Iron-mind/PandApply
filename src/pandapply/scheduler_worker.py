"""Hermes-invoked worker: bounded, read-only mail monitoring; never sends mail."""

import hashlib
import json
import sqlite3
import sys
import uuid
from contextlib import closing, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pandapply.configuration import read_settings
from pandapply.hermes_workspace import HermesWorkspaceReader, WorkspaceUnavailable
from pandapply.mail_monitor import poll
from pandapply.storage import connect, migrate


@contextmanager
def mail_lease(db: sqlite3.Connection, account: str):
    key = "mail:" + hashlib.sha256(account.strip().casefold().encode()).hexdigest()
    owner = str(uuid.uuid4())
    timestamp = datetime.now(UTC)
    expiry = (timestamp + timedelta(minutes=15)).isoformat()
    db.execute("BEGIN IMMEDIATE")
    try:
        changed = db.execute("INSERT INTO job_locks (key,owner_id,locked_until,heartbeat_at) VALUES (?,?,?,?) "
                             "ON CONFLICT(key) DO UPDATE SET owner_id=excluded.owner_id,"
                             "locked_until=excluded.locked_until,heartbeat_at=excluded.heartbeat_at "
                             "WHERE job_locks.locked_until < ?", (key, owner, expiry, timestamp.isoformat(),
                                                                    timestamp.isoformat())).rowcount
        db.commit()
    except Exception:
        db.rollback()
        raise
    if not changed:
        raise ValueError("Mail monitoring is already running")
    try:
        yield
    finally:
        with db:
            db.execute("DELETE FROM job_locks WHERE key=? AND owner_id=?", (key, owner))


def run_mail(database: Path) -> dict:
    if not database.is_file():
        raise ValueError("PandApply is not configured")
    migrate(database)
    with closing(connect(database)) as db:
        settings = read_settings(db, database.parent / "config.json")
        if not settings.gmail_enabled or settings.dry_run:
            return {"status": "disabled", "reason": "Gmail disabled or simulation mode active"}
        if not all((settings.gmail_account, settings.gmail_query, settings.hermes_python,
                    settings.hermes_workspace_script)):
            return {"status": "not_configured"}
        reader = HermesWorkspaceReader(Path(settings.hermes_python), Path(settings.hermes_workspace_script),
                                       home=Path(settings.hermes_home) if settings.hermes_home else None)
        with mail_lease(db, settings.gmail_account):
            result = poll(db, reader, account=settings.gmail_account, query=settings.gmail_query,
                          limit=settings.gmail_poll_limit)
        return {"status": "completed", "review_required": sum(row["status"] == "review_required" for row in result),
                "manual_review": sum(row["status"] == "manual_review" for row in result),
                "possibly_truncated": len(result) >= settings.gmail_poll_limit}


def main(database: Path | None = None) -> int:
    from pandapply.cli import data_dir

    if sys.prefix == sys.base_prefix:
        print(json.dumps({"status": "error", "reason": "virtual environment required"}))
        return 1
    try:
        result = run_mail(database if database is not None else data_dir() / "pandapply.db")
    except (ValueError, OSError, sqlite3.Error, WorkspaceUnavailable):
        # Provider exceptions may contain private mail or credentials.
        print(json.dumps({"status": "error", "reason": "mail monitoring failed; inspect connector configuration"}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
