import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

from pandapply.adapters.hermes.installation import discover
from pandapply.cli import main
from pandapply.hermes_workspace import HermesWorkspaceReader


def fixture_installation(tmp_path):
    home = tmp_path / "profile"
    home.mkdir()
    (home / "google_token.json").write_text("PRIVATE_TOKEN", encoding="utf-8")
    session = home / "platforms/whatsapp/session"
    session.mkdir(parents=True)
    (session / "creds.json").write_text("PRIVATE_SESSION", encoding="utf-8")
    root = tmp_path / "runtime"
    python = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    python.parent.mkdir(parents=True)
    python.write_text("fixture", encoding="utf-8")
    (python.parent.parent / "pyvenv.cfg").write_text("home=fixture", encoding="utf-8")
    script = root / "skills/productivity/google-workspace/scripts/google_api.py"
    script.parent.mkdir(parents=True)
    script.write_text("# fixture", encoding="utf-8")
    return home, root, python, script


def test_native_launcher_finds_selected_managed_environment(tmp_path, monkeypatch):
    home = tmp_path / "hermes"
    executable = home / "bin/hermes.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()
    project = home / "hermes-agent"
    (project / "hermes_cli").mkdir(parents=True)
    (project / "pyproject.toml").touch()
    key = hashlib.sha256(str(project.resolve()).encode("utf-8")).hexdigest()[:16]
    state = home / "installs" / key
    environment = state / "environments/current/venv"
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    python.parent.mkdir(parents=True)
    python.touch()
    (environment / "pyvenv.cfg").touch()
    facts = state / "facts.json"
    facts.write_text(json.dumps({"packages": {"venv": {"environment": str(environment)}}}), encoding="utf-8")
    old_python = project / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    old_python.parent.mkdir(parents=True)
    old_python.touch()
    (old_python.parent.parent / "pyvenv.cfg").touch()
    monkeypatch.setattr("pandapply.adapters.hermes.installation.shutil.which", lambda name: str(executable))
    assert discover(home=home)["python"] == str(python)
    monkeypatch.setattr("pandapply.adapters.hermes.installation.shutil.which", lambda name: None)
    assert discover(home=home)["python"] == str(python)
    python.unlink()
    result = discover(home=home)
    assert result["python"] is None and result["issues"]
    # An invalid PM selection must not silently select another environment.
    facts.write_text(json.dumps({"packages": {"venv": {"environment": str(old_python.parent.parent)}}}), encoding="utf-8")
    assert discover(home=home)["python"] is None


def test_discovery_never_reads_or_exposes_credentials(tmp_path, monkeypatch):
    home, root, python, script = fixture_installation(tmp_path)
    original = Path.read_text

    def guarded(path, *args, **kwargs):
        assert path.name not in ("google_token.json", "creds.json")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded)
    result = discover(home=home, root=root)
    assert result["python"] == str(python)
    assert result["workspace_script"] == str(script)
    assert result["gmail"] == "credentials_detected_not_verified"
    assert result["whatsapp"] == "session_detected_not_verified"
    assert "PRIVATE" not in json.dumps(result)


def test_setup_reuses_paths_without_enabling_or_overwriting_settings(tmp_path, monkeypatch, capsys):
    home, root, python, script = fixture_installation(tmp_path)
    monkeypatch.setenv("LOCALAPPDATA" if os.name == "nt" else "XDG_DATA_HOME", str(tmp_path / "data"))

    def invoke(*args):
        monkeypatch.setattr(sys, "argv", ["pandapply", *args])
        assert main() == 0
        return json.loads(capsys.readouterr().out)

    report = invoke("setup", "--hermes-home", str(home), "--hermes-root", str(root))
    assert set(report["reused_settings"]) == {"hermes_home", "hermes_python", "hermes_workspace_script"}
    settings = invoke("config", "show")
    assert settings["hermes_python"] == str(python) and settings["hermes_workspace_script"] == str(script)
    assert settings["dry_run"] and not settings["gmail_enabled"] and not settings["gmail_reply_enabled"]
    another = tmp_path / "other-profile"
    another.mkdir()
    report = invoke("setup", "--hermes-home", str(another), "--hermes-root", str(root))
    assert report["reused_settings"] == []
    assert invoke("config", "show")["hermes_home"] == str(home)


def test_workspace_bridge_pins_selected_profile_without_changing_process(tmp_path, monkeypatch):
    home = tmp_path / "selected"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", "other-profile")
    script = tmp_path / "google_api.py"
    script.write_text("import os,json\nprint(json.dumps([{'id':os.environ['HERMES_HOME']}]))\n", encoding="utf-8")
    reader = HermesWorkspaceReader(Path(sys.executable), script, home=home)
    assert reader.search("newer_than:1d")[0]["id"] == str(home.resolve())
    assert os.environ["HERMES_HOME"] == "other-profile"


def test_discovery_follows_sticky_profile_and_rejects_path_traversal(tmp_path, monkeypatch):
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.delenv("HERMES_DATA_DIR_SUFFIX", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    native = tmp_path / "appdata/hermes" if os.name == "nt" else tmp_path / ".hermes"
    selected = native / "profiles/work"
    selected.mkdir(parents=True)
    (native / "active_profile").write_text("work", encoding="utf-8")
    (native / "google_token.json").write_text("wrong-profile-token", encoding="utf-8")
    report = discover()
    assert report["home"] == str(selected)
    assert report["gmail"] == "not_detected"
    (native / "active_profile").write_text("../../other", encoding="utf-8")
    report = discover()
    assert report["home"] is None and report["issues"]


def test_setup_can_verify_existing_account_without_reading_mail(tmp_path, monkeypatch, capsys):
    home, root, _, script = fixture_installation(tmp_path)
    script.write_text("""
import os
class Result:
    def execute(self):
        return {'emailAddress': 'owner@example.test'}
class Service:
    def users(self):
        return self
    def getProfile(self, **kwargs):
        assert os.environ['HERMES_HOME'].endswith('profile')
        return Result()
def build_service(*args):
    return Service()
""", encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA" if os.name == "nt" else "XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(sys, "argv", ["pandapply", "setup", "--hermes-home", str(home), "--hermes-root", str(root),
                                     "--hermes-python", sys.executable, "--verify-gmail"])
    assert main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["gmail_verification"]["status"] == "account_verified"
    monkeypatch.setattr(sys, "argv", ["pandapply", "config", "show"])
    assert main() == 0
    settings = json.loads(capsys.readouterr().out)
    assert settings["gmail_account"] == "owner@example.test"
    assert not settings["gmail_enabled"] and not settings["gmail_reply_enabled"] and settings["dry_run"]
    monkeypatch.setattr(HermesWorkspaceReader, "primary_account", lambda self: "other@example.test")
    monkeypatch.setattr(sys, "argv", ["pandapply", "setup", "--hermes-home", str(home), "--hermes-root", str(root),
                                     "--hermes-python", sys.executable, "--verify-gmail"])
    with pytest.raises(SystemExit):
        main()
    assert "differs from saved account" in capsys.readouterr().err
    monkeypatch.setattr(sys, "argv", ["pandapply", "config", "show"])
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["gmail_account"] == "owner@example.test"
