import json
import sqlite3
import subprocess

import pytest

from pandapply.adapters.hermes.whatsapp import (
    INVITATION,
    HermesWhatsApp,
    WhatsAppOutcomeUnknown,
    invite,
    owner_jid,
)
from pandapply.setup_checks import check_database
from pandapply.storage import connect, migrate


class Sender:
    def __init__(self, *, fail=False):
        self.calls = []
        self.fail = fail

    def send(self, target, message):
        self.calls.append((target, message))
        if self.fail:
            raise TimeoutError("synthetic timeout")
        return "synthetic-receipt"


@pytest.mark.parametrize("fail", [False, True])
def test_invitation_is_confirmed_persisted_and_never_retried(tmp_path, fail):
    path = tmp_path / "data.db"
    migrate(path)
    sender = Sender(fail=fail)
    with connect(path) as db:
        assert check_database(db)["integrity"] == "ok"
        with pytest.raises(ValueError, match="Confirma"):
            invite(db, sender, "+573001234567", confirm=False)
        if fail:
            with pytest.raises(WhatsAppOutcomeUnknown):
                invite(db, sender, "+573001234567", confirm=True)
        else:
            assert invite(db, sender, "+573001234567", confirm=True)["status"] == "SENT"
        result = invite(db, sender, "+573001234567", confirm=True)
        assert result["status"] == ("UNKNOWN" if fail else "SENT")
        assert sender.calls == [("573001234567@s.whatsapp.net", INVITATION)]
        payload = db.execute("SELECT payload_redacted_json FROM event_outbox WHERE event_type='PILOT_INVITATION'").fetchone()[0]
        assert "573001234567" not in payload
        assert db.execute("SELECT count(*) FROM submission_attempts").fetchone()[0] == 0


def test_whatsapp_adapter_uses_selected_home_and_requires_receipt(tmp_path, monkeypatch):
    executable = tmp_path / "hermes.exe"
    executable.touch()
    adapter = HermesWhatsApp(executable, tmp_path)

    def execute(command, **kwargs):
        assert command == [str(executable), "send", "--to", "whatsapp:573001234567@s.whatsapp.net", "--json", "--file", "-"]
        assert kwargs["input"] == INVITATION and kwargs["env"]["HERMES_HOME"] == str(tmp_path.resolve())
        return subprocess.CompletedProcess(command, 0, json.dumps({"success": True, "message_id": "fixture-id"}), "")

    monkeypatch.setattr(subprocess, "run", execute)
    assert adapter.send("+573001234567", INVITATION) == "fixture-id"
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess([], 0, '{"success":true}', ""))
    with pytest.raises(WhatsAppOutcomeUnknown):
        adapter.send("+573001234567", INVITATION)
    with pytest.raises(ValueError):
        owner_jid("123@g.us")


def test_database_check_fails_on_invalid_relationships(tmp_path):
    path = tmp_path / "data.db"
    migrate(path)
    with connect(path) as db:
        db.execute("PRAGMA foreign_keys=OFF")
        db.execute("INSERT INTO professional_profiles VALUES ('p','missing','Backend','{}',1,1,'now','now')")
        db.commit()
        with pytest.raises(ValueError, match="integridad"):
            check_database(db)


def test_database_check_rejects_read_only_database(tmp_path):
    path = tmp_path / "data.db"
    migrate(path)
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db, pytest.raises(sqlite3.OperationalError):
        check_database(db)
