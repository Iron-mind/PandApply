import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from pandapply.domain import Job
from pandapply.mail import (
    FakeGmail,
    MailBlocked,
    MailOutcomeUnknown,
    decide_reply,
    ingest_fixture,
    propose_reply,
    recover_replies,
    send_fake_reply,
)
from pandapply.profiles import add_profile
from pandapply.storage import connect, migrate, save_job


def seed(db):
    profile = add_profile(db, "Developer", "UTC", {})
    for number in ("001", "002", "004"):
        job, _ = save_job(db, Job("Developer", "Demo", f"https://jobs.example.test/job/{number}",
                                  "fixture", f"DEMO-{number}"))
        db.execute("INSERT INTO applications (id,profile_id,job_posting_id,phase,status,created_at,updated_at) "
                   "VALUES (?, ?, ?, 'TRACKING', 'SUBMITTED', 'now', 'now')", ("app-" + number, profile, job))
        db.commit()


def test_fixture_ingest_classifies_and_correlates_without_sending(tmp_path):
    path = tmp_path / "db.sqlite"
    migrate(path)
    fixture = json.loads((Path(__file__).resolve().parents[1] / "fixtures/gmail.synthetic.json").read_text("utf-8"))
    with connect(path) as db:
        seed(db)
        results = ingest_fixture(db, fixture["emails"])
        assert [item["classification"] for item in results] == ["application_received", "interview", "rejection", "unrelated"]
        assert [item["status"] for item in results] == ["ACKNOWLEDGED", "INTERVIEW", "REJECTED", "unresolved"]
        assert db.execute("SELECT count(*) FROM event_outbox").fetchone()[0] == 2
        assert db.execute("SELECT count(*) FROM reply_proposals").fetchone()[0] == 0
        assert all(item["status"] == "duplicate" for item in ingest_fixture(db, fixture["emails"]))
        assert db.execute("SELECT count(*) FROM mailbox_messages").fetchone()[0] == 4


def test_approved_reply_is_bound_to_body_and_sent_once(tmp_path):
    path = tmp_path / "db.sqlite"
    migrate(path)
    fixture = json.loads((Path(__file__).resolve().parents[1] / "fixtures/gmail.synthetic.json").read_text("utf-8"))
    with connect(path) as db:
        seed(db)
        local_id = ingest_fixture(db, [fixture["emails"][1]])[0]["local_id"]
        proposal, decision = propose_reply(db, local_id, "Thank you. Please suggest times.")
        transport = FakeGmail()
        with pytest.raises(MailBlocked):
            send_fake_reply(db, proposal, transport)
        assert transport.sent == {}
        assert decide_reply(db, decision, approve=True) == "APPROVED"
        db.execute("UPDATE reply_proposals SET text_body='Modified' WHERE id=?", (proposal,))
        db.commit()
        with pytest.raises(MailBlocked, match="changed"):
            send_fake_reply(db, proposal, transport)
        db.execute("UPDATE reply_proposals SET text_body='Thank you. Please suggest times.' WHERE id=?", (proposal,))
        db.commit()
        assert send_fake_reply(db, proposal, transport).startswith("fake-")
        with pytest.raises(MailBlocked):
            send_fake_reply(db, proposal, transport)
        assert len(transport.sent) == 1


def test_unknown_reply_is_never_automatically_resent(tmp_path):
    path = tmp_path / "db.sqlite"
    migrate(path)
    fixture = json.loads((Path(__file__).resolve().parents[1] / "fixtures/gmail.synthetic.json").read_text("utf-8"))
    with connect(path) as db:
        seed(db)
        local_id = ingest_fixture(db, [fixture["emails"][1]])[0]["local_id"]
        proposal, decision = propose_reply(db, local_id, "Thanks for reaching out.")
        decide_reply(db, decision, approve=True)
        transport = FakeGmail(fail_after_send=True)
        with pytest.raises(MailOutcomeUnknown):
            send_fake_reply(db, proposal, transport)
        assert db.execute("SELECT state FROM reply_proposals WHERE id=?", (proposal,)).fetchone()[0] == "SEND_UNKNOWN"
        assert recover_replies(db) == 0
        with pytest.raises(MailBlocked):
            send_fake_reply(db, proposal, transport)
        assert len(transport.sent) == 1


def test_two_approved_proposals_cannot_send_to_same_message_twice(tmp_path):
    path = tmp_path / "db.sqlite"
    migrate(path)
    fixture = json.loads((Path(__file__).resolve().parents[1] / "fixtures/gmail.synthetic.json").read_text("utf-8"))
    with connect(path) as db:
        seed(db)
        local_id = ingest_fixture(db, [fixture["emails"][1]])[0]["local_id"]
        proposals = []
        for text in ("Please suggest times.", "Please share next steps."):
            proposal, decision = propose_reply(db, local_id, text)
            decide_reply(db, decision, approve=True)
            proposals.append(proposal)
    transport = FakeGmail()

    def attempt(proposal):
        db = connect(path)
        try:
            return send_fake_reply(db, proposal, transport)
        except MailBlocked:
            return None
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, proposals))
    assert sum(result is not None for result in results) == 1
    assert len(transport.sent) == 1
