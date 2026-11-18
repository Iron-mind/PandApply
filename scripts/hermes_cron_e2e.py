"""Exercise PandApply's Hermes cron adapter in a disposable offline container."""

import json
import tempfile
from contextlib import closing
from pathlib import Path

from pandapply.adapters.hermes.cron import HermesCron
from pandapply.configuration import patch_settings
from pandapply.storage import connect, migrate


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="pandapply-cron-e2e-") as temp:
        root = Path(temp)
        home = root / "hermes"
        home.mkdir()
        database = root / "data.db"
        migrate(database)
        cron = HermesCron(Path("/opt/hermes/bin/hermes"), home,
                          interpreter=Path("/opt/hermes/.venv/bin/python"), timeout=60)
        with closing(connect(database)) as db:
            created = cron.install(db, "every 24h")
            if created["state"] != "PAUSED":
                raise RuntimeError("Cron must be created paused")
            with db:
                db.execute("UPDATE scheduled_jobs SET state='UNKNOWN'")
            if cron.reconcile(db)["state"] != "PAUSED":
                raise RuntimeError("Cron reconciliation failed")
            patch_settings(db, root / "config.json", {"gmail_enabled": True, "dry_run": False,
                           "gmail_account": "owner@example.test", "gmail_query": "newer_than:1d",
                           "hermes_python": "/opt/hermes/.venv/bin/python",
                           "hermes_workspace_script": "/opt/hermes/skills/productivity/google-workspace/scripts/google_api.py"},
                           actor="cli")
            if cron.change(db, action="resume")["state"] != "ACTIVE":
                raise RuntimeError("Cron did not resume")
            if cron.change(db, action="pause")["state"] != "PAUSED":
                raise RuntimeError("Cron did not pause")
            print(json.dumps({"success": True, "state": "PAUSED", "network": "disabled"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
