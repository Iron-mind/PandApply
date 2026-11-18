"""End-to-end demo on temporary, fictional data without external services."""

import tempfile
from contextlib import closing
from importlib.resources import as_file, files
from pathlib import Path

from pandapply.cv import render_cv
from pandapply.discovery import JsonDiscovery, run_fixture
from pandapply.mail import FakeGmail, decide_reply, ingest_fixture, propose_reply, send_fake_reply
from pandapply.memory import decide_skill, propose_skill
from pandapply.profiles import add_profile
from pandapply.sandbox_workflow import prepare, submit
from pandapply.storage import connect, migrate


def run_demo() -> dict:
    with tempfile.TemporaryDirectory(prefix="pandapply-demo-") as temp:
        root = Path(temp)
        database = root / "pandapply.db"
        migrate(database)
        with closing(connect(database)) as db:
            profile = add_profile(db, "Backend (demo)", "UTC", {"must_have_skills": ["Node.js"],
                                  "salary_min_usd_month": 2000, "work_mode": "remote"})
            decision = propose_skill(db, profile, "Node.js")
            decide_skill(db, decision, approve=True)
            document = render_cv(db, profile, root / "cv-demo.pdf")
            fixture = files("pandapply").joinpath("assets/jobs.synthetic.json")
            with as_file(fixture) as fixture_path:
                jobs = run_fixture(db, profile, JsonDiscovery(fixture_path), dry_run=False)
            application = db.execute("SELECT id FROM applications WHERE job_posting_id=? AND profile_id=?",
                                     (jobs[0]["job_id"], profile)).fetchone()[0]
            prepare(db, application, document)
            receipt = submit(db, application, root / "ats.db", consent=True)
            message = {"id": "demo-interview-1", "thread_id": "demo-thread-1", "from": "hr@example.test",
                       "subject": "Interview DEMO-001", "body": "Please suggest times.",
                       "application_ref": "DEMO-001"}
            local_message = ingest_fixture(db, [message])[0]
            proposal, approval = propose_reply(db, local_message["local_id"], "Thank you. Please suggest times.")
            decide_reply(db, approval, approve=True)
            fake = FakeGmail()
            reply_id = send_fake_reply(db, proposal, fake)
            return {"mode": "simulated", "jobs": [job["status"] for job in jobs], "cv": "generated",
                    "receipt": receipt, "mail": local_message["classification"],
                    "reply": reply_id, "replies_sent": len(fake.sent)}
