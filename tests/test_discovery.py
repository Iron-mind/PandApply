import json
from pathlib import Path

import pytest

from pandapply.discovery import (
    Candidate,
    JsonDiscovery,
    ManualDiscovery,
    ProfileCriteria,
    evaluate,
    run_fixture,
)
from pandapply.memory import decide_skill, propose_skill
from pandapply.profiles import add_profile
from pandapply.storage import connect, migrate
from pandapply.work_modes import parse_work_modes


def test_multiple_work_modes_accept_any_selected_mode_and_preserve_legacy_profiles():
    criteria = ProfileCriteria(work_mode=["remote", "hybrid"], must_have_skills=["Python"],
                               confirmed_claims=["Python"])
    job = Candidate(title="Engineer", company="Demo", url="https://example.test/job", skills=["Python"])
    assert evaluate(criteria, job.model_copy(update={"work_mode": "remote"})).status == "MATCHED"
    assert evaluate(criteria, job.model_copy(update={"work_mode": "hybrid"})).status == "MATCHED"
    assert evaluate(criteria, job.model_copy(update={"work_mode": "onsite"})).status == "SKIPPED_INELIGIBLE"
    assert evaluate(criteria, job).status == "MANUAL_REVIEW"
    assert evaluate(criteria, job.model_copy(update={"work_mode": "unknown"})).status == "MANUAL_REVIEW"
    unrestricted = ProfileCriteria(work_mode="any", must_have_skills=["Python"], confirmed_claims=["Python"])
    assert evaluate(unrestricted, job).status == "MATCHED"
    assert ProfileCriteria(work_mode="remote").work_mode == "remote"
    assert parse_work_modes("remote, hybrid y onsite") == ["remote", "hybrid", "onsite"]
    assert parse_work_modes("remoto, híbrido y presencial") == ["remote", "hybrid", "onsite"]
    with pytest.raises(ValueError):
        parse_work_modes("remote, invalid")
    with pytest.raises(ValueError):
        parse_work_modes("any, remote")


def test_hard_filters_and_missing_information():
    criteria = ProfileCriteria(salary_min_usd_month=2000, work_mode="remote")
    base = {"title": "Engineer", "company": "Demo", "url": "https://example.test/job"}
    assert evaluate(criteria, Candidate(**base, salary_usd_month=1500, work_mode="remote")).status == "SKIPPED_INELIGIBLE"
    assert evaluate(criteria, Candidate(**base, salary_usd_month=3000)).status == "MANUAL_REVIEW"
    assert evaluate(criteria, Candidate(**base, salary_usd_month=3000, work_mode="remote")).status == "MANUAL_REVIEW"
    assert evaluate(criteria, Candidate(**base, salary_usd_month=3000, work_mode="remote",
                                        form={"captcha": True})).status == "MANUAL_REVIEW"


def test_configured_threshold_applies_to_verified_skill_score():
    criteria = ProfileCriteria(must_have_skills=["Python"], nice_to_have_skills=["SQL"],
                               confirmed_claims=["Python"])
    job = Candidate(title="Engineer", company="Demo", url="https://example.test/job",
                    skills=["Python", "SQL"])
    assert evaluate(criteria, job, min_score=0.8).status == "SKIPPED_INELIGIBLE"
    match = evaluate(criteria, job, min_score=0.5)
    assert match.status == "MATCHED" and match.score == 0.5


def test_fixture_discovery_is_persistent_idempotent_and_claims_are_not_self_verified(tmp_path):
    path = tmp_path / "db.sqlite"
    migrate(path)
    fixture = Path(__file__).resolve().parents[1] / "fixtures/jobs.synthetic.json"
    preferences = {"must_have_skills": ["Node.js"], "confirmed_claims": ["Node.js"],
                   "salary_min_usd_month": 2000, "work_mode": "remote"}
    with connect(path) as db:
        profile_id = add_profile(db, "Backend", "UTC", preferences)
        preview = run_fixture(db, profile_id, JsonDiscovery(fixture))
        assert preview[0]["status"] == "MANUAL_REVIEW"
        assert preview[1]["status"] == "SKIPPED_DUPLICATE"
        assert preview[2]["status"] == "SKIPPED_INELIGIBLE"
        assert preview[3]["status"] == "MANUAL_REVIEW"
        assert db.execute("SELECT count(*) FROM job_postings").fetchone()[0] == 0
        proposal = propose_skill(db, profile_id, "Node.js")
        decide_skill(db, proposal, approve=True)
        first = run_fixture(db, profile_id, JsonDiscovery(fixture), dry_run=False)
        assert first[0]["status"] == "MATCHED"
        assert db.execute("SELECT count(*) FROM applications").fetchone()[0] == 4
        assert db.execute("SELECT count(*) FROM application_events").fetchone()[0] == 4
        second = run_fixture(db, profile_id, JsonDiscovery(fixture), dry_run=False)
        assert all(row["status"] == "SKIPPED_DUPLICATE" for row in second)
        assert db.execute("SELECT count(*) FROM application_events").fetchone()[0] == 4


def test_real_urls_are_manual_only_and_not_mislabeled_as_fixtures(tmp_path):
    path = tmp_path / "db.sqlite"
    migrate(path)
    source = tmp_path / "job.json"
    source.write_text(json.dumps({"jobs": [{"title": "Developer", "company": "Company",
                                          "url": "https://careers.example.com/position",
                                          "ats_provider": "example-ats", "ats_requisition_id": "123",
                                          "skills": ["Python"]}]}), encoding="utf-8")
    with connect(path) as db:
        profile = add_profile(db, "Developer", "UTC", {"must_have_skills": ["Python"]})
        decision = propose_skill(db, profile, "Python")
        decide_skill(db, decision, approve=True)
        with pytest.raises(ValueError, match=".test"):
            run_fixture(db, profile, JsonDiscovery(source))
        result = run_fixture(db, profile, ManualDiscovery(source), dry_run=False)[0]
        assert result["status"] == "MANUAL_REVIEW"
        assert "requieren revisión" in result["reasons"][-1]
        assert db.execute("SELECT ats_provider FROM job_postings").fetchone()[0] == "example-ats"
