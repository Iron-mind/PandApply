import sys
from pathlib import Path

import pytest

from pandapply.adapters.hermes.cron import NAME, HermesCron, SchedulerUnavailable
from pandapply.configuration import patch_settings
from pandapply.scheduler_worker import mail_lease, run_mail
from pandapply.storage import connect, migrate


def setup_cron(tmp_path):
    home = tmp_path / "hermes-home"
    home.mkdir()
    executable = tmp_path / ("hermes.exe" if sys.platform == "win32" else "hermes")
    executable.write_text("fixture", encoding="utf-8")
    return HermesCron(executable, home, interpreter=Path(sys.executable))


def test_scheduler_creates_paused_job_and_requires_config_to_resume(tmp_path, monkeypatch):
    path = tmp_path / "data.db"
    migrate(path)
    cron = setup_cron(tmp_path)
    calls = []

    def invoke(*args):
        calls.append(args)
        if args == ("create", "--help"):
            return "--script --no-agent --interpreter --paused"
        if args[0] == "create":
            assert "--paused" in args and "--no-agent" in args and "--deliver" in args
            assert args[args.index("--script") + 1] == "pandapply_mail_monitor.py"
            return "Created job: abcdef123456\n  Created PAUSED"
        return ("Resumed job: " if args[0] == "resume" else "Paused job: ") + NAME + " (abcdef123456)"

    monkeypatch.setattr(cron, "_invoke", invoke)
    with connect(path) as db:
        assert cron.install(db, "every 20m")["state"] == "PAUSED"
        script = (cron.home / "scripts" / "pandapply_mail_monitor.py").read_text(encoding="utf-8")
        compile(script, "pandapply_mail_monitor.py", "exec")
        assert repr(str(path.absolute())) in script
        assert cron.install(db, "every 20m")["state"] == "PAUSED"
        assert len([call for call in calls if call[0] == "create" and call != ("create", "--help")]) == 1
        with pytest.raises(ValueError, match="Configure Gmail"):
            cron.change(db, action="resume")
        workspace = tmp_path / "google_api.py"
        workspace.write_text("# fixture", encoding="utf-8")
        patch_settings(db, tmp_path / "config.json", {"gmail_enabled": True, "dry_run": False,
                       "gmail_account": "owner@example.com", "gmail_query": "newer_than:1d",
                       "hermes_python": sys.executable, "hermes_workspace_script": str(workspace)}, actor="cli")
        assert cron.change(db, action="resume")["state"] == "ACTIVE"
        assert cron.change(db, action="pause")["state"] == "PAUSED"


def test_uncertain_create_is_reconciled_without_duplicate(tmp_path, monkeypatch):
    path = tmp_path / "data.db"
    migrate(path)
    cron = setup_cron(tmp_path)
    calls = []

    def invoke(*args):
        calls.append(args)
        if args == ("create", "--help"):
            return "--script --no-agent --interpreter --paused"
        if args[0] == "create":
            raise SchedulerUnavailable("Simulated response loss")
        if args == ("list", "--all"):
            return ("  abcdef123456 [paused]\n    Name:      pandapply-mail-monitor\n"
                    "    Schedule:  every 20m\n    Deliver:   local\n    Script:    pandapply_mail_monitor.py\n"
                    f"    Mode:      no-agent\n    Python:    {cron.interpreter}\n")
        raise AssertionError("Unexpected command")

    monkeypatch.setattr(cron, "_invoke", invoke)
    with connect(path) as db:
        with pytest.raises(SchedulerUnavailable):
            cron.install(db, "every 20m")
        assert db.execute("SELECT state FROM scheduled_jobs").fetchone()[0] == "UNKNOWN"
        with pytest.raises(SchedulerUnavailable, match="reconcile"):
            cron.install(db, "every 20m")
        assert cron.reconcile(db)["state"] == "PAUSED"
        assert len([call for call in calls if call[0] == "create" and call != ("create", "--help")]) == 1


def test_mail_worker_disabled_and_lease_excludes_second_worker(tmp_path):
    path = tmp_path / "data.db"
    migrate(path)
    assert run_mail(path)["status"] == "disabled"
    with connect(path) as first, connect(path) as second:
        with mail_lease(first, "owner@example.com"), pytest.raises(ValueError, match="already running"), \
                mail_lease(second, "owner@example.com"):
            pass
        with mail_lease(second, "owner@example.com"):
            assert second.execute("SELECT count(*) FROM job_locks").fetchone()[0] == 1


def test_mail_worker_reports_when_query_may_be_truncated(tmp_path, monkeypatch):
    path = tmp_path / "data.db"
    migrate(path)
    workspace = tmp_path / "google_api.py"
    workspace.write_text("# fixture", encoding="utf-8")
    with connect(path) as db:
        patch_settings(db, tmp_path / "config.json", {"gmail_enabled": True, "dry_run": False,
                       "gmail_account": "owner@example.com", "gmail_query": "newer_than:1d",
                       "hermes_python": sys.executable, "hermes_workspace_script": str(workspace),
                       "gmail_poll_limit": 1}, actor="cli")
    monkeypatch.setattr("pandapply.scheduler_worker.poll", lambda *args, **kwargs: [{"status": "manual_review"}])
    result = run_mail(path)
    assert result["possibly_truncated"] is True
    assert result["manual_review"] == 1
