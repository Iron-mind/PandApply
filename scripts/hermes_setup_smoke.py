"""Verify setup discovery against an installed Hermes, with synthetic credentials only."""

import json
import tempfile
from pathlib import Path

from pandapply.adapters.hermes.installation import discover

with tempfile.TemporaryDirectory(prefix="pandapply-setup-") as temporary:
    home = Path(temporary)
    report = discover(home=home, root=Path("/opt/hermes"))
    assert report["python"] == "/opt/hermes/.venv/bin/python", report
    assert report["workspace_script"] == "/opt/hermes/skills/productivity/google-workspace/scripts/google_api.py", report
    assert report["gmail"] == "not_detected" and report["whatsapp"] == "not_detected"
    (home / "google_token.json").write_text("synthetic-not-a-token", encoding="utf-8")
    session = home / "platforms/whatsapp/session"
    session.mkdir(parents=True)
    (session / "creds.json").write_text("synthetic-not-a-session", encoding="utf-8")
    report = discover(home=home, root=Path("/opt/hermes"))
    assert report["gmail"] == "credentials_detected_not_verified"
    assert report["whatsapp"] == "session_detected_not_verified"
    print(json.dumps({"discovery": "passed", "credentials": "synthetic", "network": "disabled"}))
