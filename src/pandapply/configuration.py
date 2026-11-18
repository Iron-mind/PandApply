"""Validated local configuration, with safe defaults and no credentials."""

import hashlib
import json
import os
import sqlite3
import tempfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from pandapply.storage import now


class Configuration(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    version: int = 1
    locale: str = Field(default="es", min_length=2, max_length=35)
    search_enabled: bool = False
    gmail_enabled: bool = False
    gmail_reply_enabled: bool = False
    gmail_account: str = Field(default="", max_length=320)
    gmail_query: str = Field(default="", max_length=2000)
    hermes_python: str = Field(default="", max_length=4096)
    hermes_home: str = Field(default="", max_length=4096)
    hermes_workspace_script: str = Field(default="", max_length=4096)
    gmail_poll_limit: int = Field(default=10, ge=1, le=20)
    auto_apply_enabled: bool = False
    dry_run: bool = True
    min_match_score: float = Field(default=0.8, ge=0, le=1)
    max_confirmed_submissions_per_day: int = Field(default=5, ge=0, le=1000)
    allowed_submission_domains: list[str] = Field(default_factory=list)


def load_config(path: Path) -> Configuration:
    if not path.exists():
        return Configuration()
    return Configuration.model_validate_json(path.read_text(encoding="utf-8"))


def save_config(path: Path, config: Configuration) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         delete=False) as output:
            temporary = Path(output.name)
            output.write(config.model_dump_json(indent=2))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_settings(db: sqlite3.Connection, legacy_path: Path) -> Configuration:
    row = db.execute("SELECT config_json FROM config_revisions ORDER BY id DESC LIMIT 1").fetchone()
    return Configuration.model_validate_json(row[0]) if row else load_config(legacy_path)


def patch_settings(db: sqlite3.Connection, legacy_path: Path, patch: dict, *, actor: str,
                   expected_revision: int | None = None) -> Configuration:
    if not isinstance(patch, dict) or "version" in patch or actor not in ("cli", "web"):
        raise ValueError("Invalid configuration update")
    db.execute("BEGIN IMMEDIATE")
    try:
        revision = db.execute("SELECT COALESCE(MAX(id),0) FROM config_revisions").fetchone()[0]
        if expected_revision is not None and revision != expected_revision:
            raise ValueError("Configuration changed in another session; refresh before saving")
        current = read_settings(db, legacy_path).model_dump()
        current.update(patch)
        settings = Configuration.model_validate(current)
        content = json.dumps(settings.model_dump(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
        last = db.execute("SELECT sha256 FROM config_revisions ORDER BY id DESC LIMIT 1").fetchone()
        if last is None or last[0] != checksum:
            db.execute("INSERT INTO config_revisions (config_json,sha256,actor,created_at) VALUES (?,?,?,?)",
                       (content, checksum, actor, now()))
        db.commit()
        return settings
    except Exception:
        db.rollback()
        raise
