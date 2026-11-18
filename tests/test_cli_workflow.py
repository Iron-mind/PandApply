import json
import os
import sys
from pathlib import Path

from pandapply.cli import main
from pandapply.storage import connect


def test_cli_manual_mail_review_queue(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LOCALAPPDATA" if os.name == "nt" else "XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["pandapply", "setup"])
    assert main() == 0
    capsys.readouterr()
    from pandapply.cli import data_dir

    with connect(data_dir() / "pandapply.db") as db, db:
        db.execute("INSERT INTO mail_review_queue (gmail_account_id,gmail_message_id,reason,first_seen_at,last_seen_at) "
                   "VALUES ('account','message-1','ambiguous','now','now')")
    monkeypatch.setattr(sys, "argv", ["pandapply", "gmail", "review-queue"])
    assert main() == 0
    assert json.loads(capsys.readouterr().out)[0]["gmail_message_id"] == "message-1"
    monkeypatch.setattr(sys, "argv", ["pandapply", "gmail", "mark-reviewed", "--account-id", "account",
                                     "--message-id", "message-1"])
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["status"] == "reviewed"


def test_cli_simulated_workflow(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LOCALAPPDATA" if os.name == "nt" else "XDG_DATA_HOME", str(tmp_path))

    def invoke(*args):
        monkeypatch.setattr(sys, "argv", ["pandapply", *args])
        assert main() == 0
        return capsys.readouterr().out.strip()

    invoke("setup")
    assert json.loads(invoke("config", "set", "min_match_score", "0.9"))["min_match_score"] == 0.9
    assert json.loads(invoke("config", "show"))["min_match_score"] == 0.9
    preferences = json.dumps({"must_have_skills": ["Node.js"], "salary_min_usd_month": 2000, "work_mode": "remote"})
    profile = invoke("profiles", "add", "Backend", "--preferences", preferences)
    decision = invoke("memory", "propose", "--profile", profile, "--skill", "Node.js")
    assert invoke("memory", "approve", decision) == "APPROVED"
    document = invoke("profiles", "generate-cv", profile, str(tmp_path / "synthetic.pdf"))
    fixture = str(Path(__file__).resolve().parents[1] / "fixtures/jobs.synthetic.json")
    assert json.loads(invoke("run", "discovery", "--profile", profile, "--fixture", fixture, "--save"))[0]["status"] == "MATCHED"
    apps = json.loads(invoke("applications", "list"))
    app = next(item["id"] for item in apps if item["status"] == "MATCHED")
    invoke("applications", "sandbox-prepare", app, "--document-id", document)
    result = json.loads(invoke("applications", "sandbox-submit", app, "--consent"))
    assert result["transport"] == "simulated" and result["receipt"].startswith("sandbox-")
    fixture = str(Path(__file__).resolve().parents[1] / "fixtures/gmail.synthetic.json")
    messages = json.loads(invoke("gmail", "ingest", "--input", fixture))
    assert messages[0]["status"] == "ACKNOWLEDGED"


def test_cli_hermes_workspace_bridge_reads_without_sending(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LOCALAPPDATA" if os.name == "nt" else "XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["pandapply", "setup"])
    assert main() == 0
    capsys.readouterr()
    script = tmp_path / "google_api.py"
    script.write_text("import json,sys\nassert sys.argv[1:3] == ['gmail','search']\n"
                      "print(json.dumps([{'id':'test-1', 'subject':'fixture'}]))\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["pandapply", "gmail", "search-real", "--hermes-python", sys.executable,
                                     "--workspace-script", str(script), "--query", "is:unread"])
    assert main() == 0
    assert json.loads(capsys.readouterr().out)[0]["id"] == "test-1"
    for key, value in (("hermes_python", sys.executable), ("hermes_workspace_script", str(script))):
        monkeypatch.setattr(sys, "argv", ["pandapply", "config", "set", key, json.dumps(value)])
        assert main() == 0
        capsys.readouterr()
    monkeypatch.setattr(sys, "argv", ["pandapply", "gmail", "search-real", "--query", "is:unread"])
    assert main() == 0
    assert json.loads(capsys.readouterr().out)[0]["id"] == "test-1"


def test_cli_manual_application_and_real_mail_review_with_fake_hermes(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LOCALAPPDATA" if os.name == "nt" else "XDG_DATA_HOME", str(tmp_path))

    def invoke(*args):
        monkeypatch.setattr(sys, "argv", ["pandapply", *args])
        assert main() == 0
        return capsys.readouterr().out.strip()

    invoke("setup")
    profile = invoke("profiles", "add", "Backend", "--preferences", '{"must_have_skills":["Python"]}')
    approval = invoke("memory", "propose", "--profile", profile, "--skill", "Python")
    invoke("memory", "approve", approval)
    source = tmp_path / "jobs.json"
    source.write_text(json.dumps({"jobs": [{"title": "Developer", "company": "Example",
                                          "url": "https://jobs.example.com/123", "skills": ["Python"]}]}),
                      encoding="utf-8")
    invoke("run", "discovery", "--profile", profile, "--input", str(source), "--save")
    app = json.loads(invoke("applications", "list"))[0]["id"]
    invoke("applications", "record-manual", app, "--receipt-id", "receipt-123", "--confirm")
    script = tmp_path / "google_api.py"
    script.write_text("class Result:\n"
                      " def __init__(self, data): self.data = data\n"
                      " def execute(self): return self.data\n"
                      "class Service:\n"
                      " def users(self): return self\n"
                      " def messages(self): return self\n"
                      " def getProfile(self, **kw): return Result({'emailAddress':'owner@example.com'})\n"
                      " def get(self, **kw): return Result({'id':kw['id'],'threadId':'thread'})\n"
                      "def build_service(api, version): return Service()\n"
                      "def _headers_dict(message): return {'from':'hr@example.com','subject':'Interview',"
                      "'date':'Tue, 17 Nov 2026 12:00:00 +0000'}\n"
                      "def _extract_message_body(message): return 'Please reply'\n", encoding="utf-8")
    review = json.loads(invoke("gmail", "ingest-real", "--hermes-python", sys.executable, "--workspace-script", str(script),
                               "--message-id", "m-1", "--account-id", "owner@example.com", "--application-id", app,
                               "--classification", "interview"))
    assert review["status"] == "review_required"
    assert json.loads(invoke("applications", "show", app))["status"] == "SUBMITTED"
    invoke("decisions", "respond", review["decision_id"], "approve")
    assert json.loads(invoke("applications", "show", app))["status"] == "INTERVIEW"


def test_policy_cli_requires_review_and_consent(tmp_path, monkeypatch, capsys):
    from datetime import UTC, datetime, timedelta

    monkeypatch.setenv("LOCALAPPDATA" if os.name == "nt" else "XDG_DATA_HOME", str(tmp_path))

    def invoke(*args):
        monkeypatch.setattr(sys, "argv", ["pandapply", *args])
        assert main() == 0
        return capsys.readouterr().out.strip()

    invoke("setup")
    expires = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    policy = invoke("policy", "review", "--domain", "jobs.example.com", "--operation", "submit",
                    "--disposition", "ALLOWED", "--source-url", "https://jobs.example.com/terms",
                    "--rationale", "Automation permission was reviewed", "--expires-at", expires, "--confirm-reviewed")
    assert json.loads(invoke("policy", "check", "https://jobs.example.com/job"))["decision"] == "MANUAL_REVIEW"
    assert json.loads(invoke("policy", "consent", policy, "--confirm"))["status"] == "consented"
    assert json.loads(invoke("policy", "check", "https://jobs.example.com/job"))["decision"] == "MANUAL_REVIEW"
