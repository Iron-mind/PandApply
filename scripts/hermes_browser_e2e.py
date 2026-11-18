"""Disposable-container integration test: PandApply -> Hermes browser -> fake ATS."""

import json
import tempfile
from contextlib import closing
from importlib.resources import as_file, files
from pathlib import Path

from pandapply.cv import render_cv
from pandapply.discovery import JsonDiscovery, run_fixture
from pandapply.memory import decide_skill, propose_skill
from pandapply.profiles import add_profile
from pandapply.sandbox_workflow import prepare, submit_with_hermes
from pandapply.storage import connect, migrate


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="pandapply-hermes-e2e-") as temp:
        root = Path(temp)
        database = root / "data.db"
        migrate(database)
        with closing(connect(database)) as db:
            profile = add_profile(db, "Synthetic backend", "UTC", {"must_have_skills": ["Node.js"]})
            decision = propose_skill(db, profile, "Node.js")
            decide_skill(db, decision, approve=True)
            document = render_cv(db, profile, root / "synthetic.pdf")
            with as_file(files("pandapply").joinpath("assets/jobs.synthetic.json")) as source:
                result = run_fixture(db, profile, JsonDiscovery(source), dry_run=False)[0]
            app = db.execute("SELECT id FROM applications WHERE profile_id=? AND job_posting_id=?",
                             (profile, result["job_id"])).fetchone()[0]
            prepare(db, app, document)
            receipt = submit_with_hermes(db, app, root / "ats.db", consent=True,
                                          interpreter=Path("/opt/hermes/.venv/bin/python"), hermes_root=Path("/opt/hermes"))
            state = db.execute("SELECT status FROM applications WHERE id=?", (app,)).fetchone()[0]
            attempts = db.execute("SELECT count(*) FROM submission_attempts WHERE application_id=?", (app,)).fetchone()[0]
            if state != "SUBMITTED" or not receipt.startswith("sandbox-") or attempts != 1:
                raise RuntimeError("The browser sandbox did not produce exactly one confirmed receipt")
            print(json.dumps({"success": True, "transport": "hermes-browser-sandbox", "attempts": attempts}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
