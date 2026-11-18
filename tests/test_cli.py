import json

from pandapply.cli import main


def test_cli_rejects_shared_python(monkeypatch, capsys):
    monkeypatch.setattr("sys.prefix", __import__("sys").base_prefix)
    assert main() == 1
    assert "virtual environment" in capsys.readouterr().err


def test_doctor_does_not_create_storage(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LOCALAPPDATA" if __import__('os').name == 'nt' else "XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr("sys.argv", ["pandapply", "doctor", "--json"])
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["whatsapp_required"] is False
    assert list(tmp_path.iterdir()) == []


def test_setup_dry_run_is_read_only(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA" if __import__('os').name == 'nt' else "XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr("sys.argv", ["pandapply", "setup", "--dry-run"])
    assert main() == 0
    assert list(tmp_path.iterdir()) == []
