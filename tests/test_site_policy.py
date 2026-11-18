from datetime import UTC, datetime, timedelta

import pytest

from pandapply.configuration import Configuration
from pandapply.site_policy import consent, preflight, review
from pandapply.storage import connect, migrate


def test_policy_defaults_deny_and_consent_does_not_override_restrictions(tmp_path):
    path = tmp_path / "db.sqlite"
    migrate(path)
    config = Configuration(dry_run=False, auto_apply_enabled=True,
                           allowed_submission_domains=["jobs.example.com", "linkedin.com"])
    with connect(path) as db:
        assert preflight(db, "https://jobs.example.com/role", config).decision == "MANUAL_REVIEW"
        assert preflight(db, "https://www.linkedin.com/jobs/123", config).decision == "BLOCKED"
        assert preflight(db, "http://jobs.example.com/role", config).decision == "BLOCKED"
        assert preflight(db, "https://127.0.0.1/role", config).decision == "BLOCKED"
        assert preflight(db, "https://127.1/role", config).decision == "BLOCKED"
        expiry = (datetime.now(UTC) + timedelta(days=1)).isoformat()
        with pytest.raises(ValueError, match="restricted"):
            review(db, domain="linkedin.com", operation="submit", disposition="ALLOWED",
                   source_url="https://linkedin.com/legal", rationale="Permission reviewed carefully", expires_at=expiry)


def test_latest_review_and_explicit_consent_are_both_required(tmp_path):
    path = tmp_path / "db.sqlite"
    migrate(path)
    config = Configuration(dry_run=False, auto_apply_enabled=True, allowed_submission_domains=["jobs.example.com"])
    with connect(path) as db:
        expiry = (datetime.now(UTC) + timedelta(days=1)).isoformat()
        policy = review(db, domain="jobs.example.com", operation="submit", disposition="ALLOWED",
                        source_url="https://jobs.example.com/terms", rationale="Explicit automation permission reviewed",
                        expires_at=expiry)
        assert preflight(db, "https://jobs.example.com/role", config).decision == "MANUAL_REVIEW"
        with pytest.raises(ValueError, match="consent"):
            consent(db, policy, confirm=False)
        consent(db, policy, confirm=True)
        assert preflight(db, "https://jobs.example.com/role", config).decision == "PRELIMINARY_ALLOW"
        assert preflight(db, "https://jobs.example.com/role", Configuration()).decision == "MANUAL_REVIEW"
        review(db, domain="jobs.example.com", operation="submit", disposition="BLOCKED",
               source_url="https://jobs.example.com/terms", rationale="Updated terms prohibit automation", expires_at=expiry)
        assert preflight(db, "https://jobs.example.com/role", config).decision == "BLOCKED"


def test_expired_review_and_subdomain_do_not_inherit_permission(tmp_path):
    path = tmp_path / "db.sqlite"
    migrate(path)
    config = Configuration(dry_run=False, auto_apply_enabled=True,
                           allowed_submission_domains=["jobs.example.com", "other.jobs.example.com"])
    with connect(path) as db:
        expiry = (datetime.now(UTC) + timedelta(days=1)).isoformat()
        policy = review(db, domain="jobs.example.com", operation="submit", disposition="ALLOWED",
                        source_url="https://jobs.example.com/terms", rationale="Explicit permission checked",
                        expires_at=expiry)
        consent(db, policy, confirm=True)
        assert preflight(db, "https://other.jobs.example.com/role", config).decision == "MANUAL_REVIEW"
        db.execute("UPDATE site_policy_reviews SET expires_at=? WHERE id=?",
                   ((datetime.now(UTC) - timedelta(days=1)).isoformat(), policy))
        db.commit()
        assert preflight(db, "https://jobs.example.com/role", config).decision == "MANUAL_REVIEW"
