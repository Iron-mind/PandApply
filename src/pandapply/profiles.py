"""Local professional profiles and evidence files."""

import hashlib
import json
import mimetypes
import sqlite3
import uuid
from pathlib import Path

from pandapply.storage import now
from pandapply.timezones import normalize_timezone


def add_profile(db: sqlite3.Connection, name: str, timezone: str, preferences: dict, *,
                profile_id: str | None = None) -> str:
    name = name.strip()
    if not name or len(name) > 200:
        raise ValueError("Profile name must contain 1–200 characters")
    timezone = normalize_timezone(timezone)
    if profile_id is not None and (not profile_id.strip() or len(profile_id) > 200):
        raise ValueError("Profile ID must contain 1–200 characters")
    profile_id = profile_id or str(uuid.uuid4())
    timestamp = now()
    with db:
        master = db.execute("SELECT id FROM master_profile LIMIT 1").fetchone()
        master_id = master[0] if master else str(uuid.uuid4())
        if master is None:
            db.execute("INSERT INTO master_profile VALUES (?, ?, ?, ?)",
                       (master_id, None, timezone, timestamp))
        db.execute("INSERT INTO professional_profiles VALUES (?, ?, ?, ?, 1, 1, ?, ?)",
                   (profile_id, master_id, name, json.dumps(preferences, ensure_ascii=False),
                    timestamp, timestamp))
    return profile_id


def list_profiles(db: sqlite3.Connection) -> list[dict]:
    rows = db.execute("SELECT id, name, preferences_json, active, version FROM professional_profiles "
                      "ORDER BY created_at, id").fetchall()
    return [{"id": row["id"], "name": row["name"],
             "preferences": json.loads(row["preferences_json"]),
             "active": bool(row["active"]), "version": row["version"]} for row in rows]


def edit_profile(db: sqlite3.Connection, profile_id: str, *, name: str | None = None,
                 preferences: dict | None = None, expected_version: int | None = None) -> int:
    if name is None and preferences is None:
        raise ValueError("Specify a name or preferences to change")
    if name is not None:
        name = name.strip()
        if not name or len(name) > 200:
            raise ValueError("Profile name must contain 1–200 characters")
    if preferences is not None and not isinstance(preferences, dict):
        raise ValueError("Preferences must be a JSON object")
    db.execute("BEGIN IMMEDIATE")
    try:
        row = db.execute("SELECT name,preferences_json,version FROM professional_profiles WHERE id=?",
                         (profile_id,)).fetchone()
        if row is None:
            raise ValueError("Profile not found")
        if expected_version is not None and row["version"] != expected_version:
            raise ValueError("Profile was changed by another operation")
        new_name = name if name is not None else row["name"]
        new_preferences = (json.dumps(preferences, ensure_ascii=False, sort_keys=True)
                           if preferences is not None else row["preferences_json"])
        if new_name == row["name"] and json.loads(new_preferences) == json.loads(row["preferences_json"]):
            db.commit()
            return row["version"]
        version = row["version"] + 1
        db.execute("UPDATE professional_profiles SET name=?,preferences_json=?,version=?,updated_at=? WHERE id=?",
                   (new_name, new_preferences, version, now(), profile_id))
        db.commit()
        return version
    except Exception:
        db.rollback()
        raise


def import_cv(db: sqlite3.Connection, profile_id: str, path: Path) -> str:
    path = path.expanduser().resolve(strict=True)
    if not path.is_file() or path.suffix.lower() not in (".pdf", ".docx"):
        raise ValueError("CV must be a PDF or DOCX file")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    document_id = str(uuid.uuid4())
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    with db:
        if not db.execute("SELECT 1 FROM professional_profiles WHERE id=?", (profile_id,)).fetchone():
            raise ValueError("Profile not found")
        db.execute("INSERT INTO documents (id, profile_id, kind, file_path, sha256, mime_type, "
                   "created_at) VALUES (?, ?, 'cv_original', ?, ?, ?, ?)",
                   (document_id, profile_id, str(path), digest.hexdigest(), mime, now()))
    return document_id
