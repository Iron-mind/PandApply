"""Versioned site reviews and conservative preflight checks.

This is a preflight only; it never authorizes a browser to perform a submission.
Actual site integrations still need verified terms, form permits, quotas and receipts.
"""

import ipaddress
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

from pandapply.configuration import Configuration
from pandapply.storage import now

RESTRICTED = ("linkedin.com", "indeed.com")
OPERATIONS = ("discover", "read", "fill", "submit")


def _domain(host: str) -> str:
    try:
        host = host.strip().rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ValueError("Invalid domain") from exc
    if (len(host) > 253 or "." not in host or not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                                                      for label in host.split("."))
            or host.split(".")[-1].isdigit()):
        raise ValueError("Invalid domain")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return host
    raise ValueError("IP literals are not supported for external sites")


def _restricted(domain: str) -> bool:
    return any(domain == blocked or domain.endswith("." + blocked) for blocked in RESTRICTED)


def review(db: sqlite3.Connection, *, domain: str, operation: str, disposition: str,
           source_url: str, rationale: str, expires_at: str) -> str:
    domain = _domain(domain)
    if operation not in OPERATIONS or disposition not in ("ALLOWED", "MANUAL_ONLY", "BLOCKED"):
        raise ValueError("Invalid policy operation or disposition")
    if _restricted(domain) and disposition == "ALLOWED":
        raise ValueError("This platform is restricted by PandApply's policy")
    source = urlsplit(source_url)
    if (source.scheme != "https" or not source.hostname or source.username or source.password
            or _domain(source.hostname) != domain):
        raise ValueError("Policy source must be an HTTPS page on the reviewed domain")
    rationale = rationale.strip()
    if not 10 <= len(rationale) <= 2000:
        raise ValueError("A policy review rationale of 10–2000 characters is required")
    try:
        expiry = datetime.fromisoformat(expires_at)
        if expiry.tzinfo is None or expiry.astimezone(UTC) <= datetime.now(UTC):
            raise ValueError("Invalid expiry")
    except (TypeError, ValueError) as exc:
        raise ValueError("Policy expiry must be a future timestamp with timezone") from exc
    identifier = str(uuid.uuid4())
    with db:
        db.execute("INSERT INTO site_policy_reviews (id,domain,operation,disposition,source_url,rationale,reviewer,"
                   "reviewed_at,expires_at) VALUES (?,?,?,?,?,?,'local-owner',?,?)",
                   (identifier, domain, operation, disposition, source_url, rationale, now(), expiry.astimezone(UTC).isoformat()))
    return identifier


def consent(db: sqlite3.Connection, policy_id: str, *, confirm: bool) -> None:
    if not confirm:
        raise ValueError("Explicit owner consent is required")
    db.execute("BEGIN IMMEDIATE")
    try:
        policy = db.execute("SELECT disposition,operation,expires_at FROM site_policy_reviews WHERE id=?",
                            (policy_id,)).fetchone()
        if (not policy or policy["disposition"] != "ALLOWED" or policy["operation"] != "submit"
                or datetime.fromisoformat(policy["expires_at"]) <= datetime.now(UTC)):
            raise ValueError("Only a current submit policy reviewed as allowed can be consented to")
        db.execute("INSERT INTO site_policy_consents (policy_id,principal,created_at) VALUES (?,'local-owner',?) "
                   "ON CONFLICT(policy_id) DO UPDATE SET created_at=excluded.created_at,revoked_at=NULL",
                   (policy_id, now()))
        db.commit()
    except Exception:
        db.rollback()
        raise


@dataclass(frozen=True)
class Preflight:
    decision: str
    reason: str
    policy_id: str | None = None


def preflight(db: sqlite3.Connection, url: str, config: Configuration) -> Preflight:
    try:
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            raise ValueError("External submission requires an HTTPS URL")
        domain = _domain(parts.hostname)
    except ValueError:
        return Preflight("BLOCKED", "Unsafe or unsupported URL")
    if _restricted(domain):
        return Preflight("BLOCKED", "Platform is restricted")
    if domain.endswith((".test", ".localhost", ".local")):
        return Preflight("BLOCKED", "Local or synthetic domains cannot use the external submission gate")
    row = db.execute("SELECT * FROM site_policy_reviews WHERE domain=? AND operation='submit' "
                     "ORDER BY reviewed_at DESC, rowid DESC LIMIT 1", (domain,)).fetchone()
    if not row or datetime.fromisoformat(row["expires_at"]) <= datetime.now(UTC):
        return Preflight("MANUAL_REVIEW", "No current reviewed site policy")
    if row["disposition"] != "ALLOWED":
        return Preflight("BLOCKED" if row["disposition"] == "BLOCKED" else "MANUAL_REVIEW",
                         "Site policy does not permit automatic submission", row["id"])
    if config.dry_run or not config.auto_apply_enabled or domain not in config.allowed_submission_domains:
        return Preflight("MANUAL_REVIEW", "Automation is disabled or domain is not allowed", row["id"])
    permitted = db.execute("SELECT 1 FROM site_policy_consents WHERE policy_id=? AND principal='local-owner' "
                           "AND revoked_at IS NULL", (row["id"],)).fetchone()
    if not permitted:
        return Preflight("MANUAL_REVIEW", "Owner consent for this policy is missing", row["id"])
    return Preflight("PRELIMINARY_ALLOW", "Policy and consent satisfied; remaining submit gates still apply", row["id"])
