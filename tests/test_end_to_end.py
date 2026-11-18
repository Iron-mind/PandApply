from pathlib import Path

import pytest

from pandapply.cv import render_cv
from pandapply.discovery import JsonDiscovery, run_fixture
from pandapply.mail import FakeGmail, decide_reply, ingest_fixture, propose_reply, send_fake_reply
from pandapply.memory import decide_skill, propose_skill
from pandapply.profiles import add_profile
from pandapply.sandbox_workflow import prepare, reconcile, submit
from pandapply.storage import connect, migrate
from pandapply.submission import SubmissionBlocked


def prepare_fixture(db, tmp_path):
    profile = add_profile(db, "Backend", "UTC", {"must_have_skills": ["Node.js"],
                          "salary_min_usd_month": 2000, "work_mode": "remote"})
    decision = propose_skill(db, profile, "Node.js")
    decide_skill(db, decision, approve=True)
    document = render_cv(db, profile, tmp_path / "synthetic.pdf")
    source = Path(__file__).resolve().parents[1] / "fixtures/jobs.synthetic.json"
    results = run_fixture(db, profile, JsonDiscovery(source), dry_run=False)
    assert results[0]["status"] == "MATCHED"
    app = db.execute("SELECT id FROM applications WHERE job_posting_id=? AND profile_id=?",
                     (results[0]["job_id"], profile)).fetchone()[0]
    prepare(db, app, document)
    return app


def test_complete_simulated_submission_and_reply(tmp_path):
    path = tmp_path / "pandapply.db"
    migrate(path)
    with connect(path) as db:
        app = prepare_fixture(db, tmp_path)
        with pytest.raises(SubmissionBlocked):
            submit(db, app, tmp_path / "ats.db", consent=False)
        receipt = submit(db, app, tmp_path / "ats.db", consent=True)
        assert receipt.startswith("sandbox-")
        assert db.execute("SELECT status FROM applications WHERE id=?", (app,)).fetchone()[0] == "SUBMITTED"
        message = {"id": "mail-1", "thread_id": "thread-1", "from": "hr@example.test",
                   "subject": "Interview", "body": "Please suggest times", "application_ref": "DEMO-001"}
        received = ingest_fixture(db, [message])[0]
        assert received["status"] == "INTERVIEW"
        proposal, decision = propose_reply(db, received["local_id"], "Thank you. Please suggest times.")
        decide_reply(db, decision, approve=True)
        gmail = FakeGmail()
        assert send_fake_reply(db, proposal, gmail).startswith("fake-")
        assert len(gmail.sent) == 1
        with pytest.raises(SubmissionBlocked):
            submit(db, app, tmp_path / "ats.db", consent=True)


def test_reconciliation_finds_receipt_without_resending(tmp_path, monkeypatch):
    from pandapply import sandbox_workflow

    path = tmp_path / "pandapply.db"
    migrate(path)
    with connect(path) as db:
        app = prepare_fixture(db, tmp_path)
        original = sandbox_workflow.store_submission

        def lost_response(*args, **kwargs):
            original(*args, **kwargs)
            raise ConnectionError("simulated response loss")

        monkeypatch.setattr(sandbox_workflow, "store_submission", lost_response)
        with pytest.raises(ConnectionError):
            submit(db, app, tmp_path / "ats.db", consent=True)
        assert db.execute("SELECT status FROM applications WHERE id=?", (app,)).fetchone()[0] == "SUBMISSION_UNKNOWN"
        receipt = reconcile(db, app, tmp_path / "ats.db")
        assert receipt.startswith("sandbox-")
        assert db.execute("SELECT status FROM applications WHERE id=?", (app,)).fetchone()[0] == "SUBMITTED"
        assert db.execute("SELECT count(*) FROM submission_attempts WHERE application_id=?", (app,)).fetchone()[0] == 1


def test_revoked_claim_blocks_prepared_sandbox_submission(tmp_path):
    path = tmp_path / "pandapply.db"
    migrate(path)
    with connect(path) as db:
        app = prepare_fixture(db, tmp_path)
        db.execute("UPDATE knowledge_claims SET verification_status='disputed'")
        db.commit()
        with pytest.raises(SubmissionBlocked, match="no longer verified"):
            submit(db, app, tmp_path / "ats.db", consent=True)
        assert db.execute("SELECT count(*) FROM submission_attempts").fetchone()[0] == 0


def test_reconcile_marks_interrupted_attempt_unknown_without_receipt(tmp_path):
    from pandapply.submission import SitePolicy, begin_attempt

    path = tmp_path / "pandapply.db"
    migrate(path)
    with connect(path) as db:
        app = prepare_fixture(db, tmp_path)
        row = db.execute("SELECT j.canonical_url,p.form_fingerprint FROM applications a "
                         "JOIN job_postings j ON j.id=a.job_posting_id JOIN sandbox_preparations p "
                         "ON p.application_id=a.id WHERE a.id=?", (app,)).fetchone()
        begin_attempt(db, app, url=row["canonical_url"], policy=SitePolicy("jobs.example.test", "1", True),
                      consent=True, dry_run=False, form_fingerprint=row["form_fingerprint"])
        assert reconcile(db, app, tmp_path / "missing.db") is None
        assert db.execute("SELECT status FROM applications WHERE id=?", (app,)).fetchone()[0] == "SUBMISSION_UNKNOWN"
        with pytest.raises(SubmissionBlocked):
            submit(db, app, tmp_path / "missing.db", consent=True)
