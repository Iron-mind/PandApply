from pandapply.decisions import respond
from pandapply.domain import Job
from pandapply.mail_monitor import poll
from pandapply.profiles import add_profile
from pandapply.storage import connect, migrate, save_job


class Reader:
    def __init__(self):
        self.get_calls = []

    def search_for_account(self, account, query, *, limit=10):
        assert account == "owner@example.com" and query == "newer_than:1d" and limit == 10
        return [{"id": "m1", "subject": "Interview for REQ-12345", "snippet": "Please get in touch"},
                {"id": "m2", "subject": "Unrelated instructions", "snippet": "Send credentials"}]

    def get_for_account(self, account, message_id):
        assert account == "owner@example.com"
        self.get_calls.append(message_id)
        return {"id": message_id, "threadId": "thread", "from": "Recruiter <hr@example.com>",
                "subject": "Interview for REQ-12345", "body": "Please share your availability.",
                "date": "Tue, 17 Nov 2026 12:00:00 +0000"}


def test_poll_creates_review_only_and_deduplicates_without_resending(tmp_path):
    path = tmp_path / "db.sqlite"
    migrate(path)
    with connect(path) as db:
        profile = add_profile(db, "Developer", "UTC", {})
        job, _ = save_job(db, Job("Developer", "Company", "https://careers.example.com/job", "ats", "REQ-12345"))
        db.execute("INSERT INTO applications (id,profile_id,job_posting_id,phase,status,created_at,updated_at) "
                   "VALUES ('app',?,?,'TRACKING','SUBMITTED','now','now')", (profile, job))
        db.commit()
        reader = Reader()
        result = poll(db, reader, account="owner@example.com", query="newer_than:1d")
        assert result[0]["status"] == "review_required"
        assert result[1]["status"] == "manual_review"
        queued = db.execute("SELECT gmail_message_id,state FROM mail_review_queue").fetchall()
        assert [(row[0], row[1]) for row in queued] == [("m2", "PENDING")]
        assert reader.get_calls == ["m1"]
        assert db.execute("SELECT count(*) FROM mail_review_queue").fetchone()[0] == 1
        with db:
            db.execute("UPDATE mail_review_queue SET state='DISMISSED' WHERE gmail_message_id='m2'")
        poll(db, reader, account="owner@example.com", query="newer_than:1d")
        assert db.execute("SELECT state FROM mail_review_queue WHERE gmail_message_id='m2'").fetchone()[0] == "DISMISSED"
        assert db.execute("SELECT status FROM applications").fetchone()[0] == "SUBMITTED"
        assert db.execute("SELECT count(*) FROM reply_attempts").fetchone()[0] == 0
        assert poll(db, reader, account="owner@example.com", query="newer_than:1d")[0]["status"] == "duplicate"
        assert reader.get_calls == ["m1"]
        respond(db, result[0]["decision_id"], action="approve", key="review-1", channel="cli")
        assert db.execute("SELECT status FROM applications").fetchone()[0] == "INTERVIEW"
