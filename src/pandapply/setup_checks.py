"""Local database checks used by onboarding; no external database client required."""

import sqlite3


def check_database(db: sqlite3.Connection) -> dict:
    integrity = [row[0] for row in db.execute("PRAGMA quick_check")]
    if integrity != ["ok"] or db.execute("PRAGMA foreign_key_check").fetchone():
        raise ValueError("SQLite no superó la validación de integridad o relaciones")
    if db.execute("PRAGMA journal_mode").fetchone()[0].lower() != "wal":
        raise ValueError("SQLite debe estar configurado en modo WAL")
    db.execute("SAVEPOINT onboarding_check")
    try:
        # Exercise the main database's write permission, not just the temp store.
        db.execute("UPDATE config_revisions SET sha256=sha256 WHERE 0")
        db.execute("CREATE TEMP TABLE pandapply_setup_write_check (value INTEGER)")
        db.execute("INSERT INTO pandapply_setup_write_check VALUES (1)")
        if db.execute("SELECT value FROM pandapply_setup_write_check").fetchone()[0] != 1:
            raise ValueError("Falló la comprobación de escritura SQLite")
    finally:
        db.execute("ROLLBACK TO onboarding_check")
        db.execute("RELEASE onboarding_check")
    return {"integrity": "ok", "foreign_keys": "ok", "write": "ok",
            "schema_version": db.execute("PRAGMA user_version").fetchone()[0]}
