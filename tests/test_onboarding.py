import importlib.util
import subprocess
import sys
from pathlib import Path

from pandapply.configuration import read_settings
from pandapply.discovery import Candidate, ProfileCriteria, evaluate
from pandapply.onboarding import run
from pandapply.profiles import list_profiles
from pandapply.storage import connect


def no_hermes(**kwargs):
    return dict.fromkeys(("executable", "home", "python", "workspace_script")) | {
        "gmail": "not_detected", "whatsapp": "not_detected", "issues": []}


def answers(monkeypatch, values):
    replies = iter(values)
    monkeypatch.setattr("builtins.input", lambda prompt: next(replies))


def test_wizard_creates_profile_and_resumes_without_duplicate(tmp_path, monkeypatch):
    monkeypatch.setattr("pandapply.onboarding.discover", no_hermes)
    path = tmp_path / "pandapply.db"
    answers(monkeypatch, ["1", "", "Backend", "UTC", "", "n", "n", "n"])
    assert run(path) == 0
    with connect(path) as db:
        assert [p["name"] for p in list_profiles(db)] == ["Backend"]
        assert read_settings(db, tmp_path / "config.json").dry_run
    answers(monkeypatch, ["1", "", "1", "", "n", "n", "n"])
    assert run(path) == 0
    with connect(path) as db:
        assert len(list_profiles(db)) == 1


def test_wizard_cancel_and_incoming_runtime_do_not_fake_success(tmp_path, monkeypatch):
    path = tmp_path / "pandapply.db"
    answers(monkeypatch, ["2"])
    assert run(path) == 1 and not path.exists()
    monkeypatch.setattr("builtins.input", lambda prompt: (_ for _ in ()).throw(EOFError()))
    assert run(path) == 130


def test_bootstrap_installs_and_launches_using_only_its_virtualenv(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("pandapply_installer", Path(__file__).parents[1] / "install.py")
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    monkeypatch.setattr(installer, "__file__", str(tmp_path / "install.py"))
    environment = tmp_path / ".venv"
    python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    python.parent.mkdir(parents=True)
    python.write_text("fixture", encoding="utf-8")
    (environment / "pyvenv.cfg").write_text("fixture", encoding="utf-8")
    calls = []

    def execute(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", execute)
    monkeypatch.setattr(sys, "argv", ["install.py"])
    assert installer.main() == 0
    assert calls == [[str(python), "-m", "pip", "install", "-e", str(tmp_path)],
                     [str(python), "-m", "pandapply", "setup", "--wizard"]]


def test_full_setup_saves_search_preferences_before_offering_dashboard(tmp_path, monkeypatch):
    monkeypatch.setattr("pandapply.onboarding.discover", no_hermes)
    answers(monkeypatch, ["1", "", "Backend", "UTC", "", "s", "QA", "1,2",
                          "Backend Engineer", "Colombia", "es,en", "Python", "remote, hybrid y onsite", "2000",
                          "QA Engineer", "Colombia", "es", "Testing", "hybrid", "1500",
                          "3", "12", "120", "n", "s"])
    observed = []

    def panel(path):
        with connect(path) as db:
            settings = read_settings(db, path.parent / "config.json")
            observed.append(settings.max_confirmed_submissions_per_day)
            assert len(settings.search_profile_ids) == 2
            assert settings.max_results_per_run == 12 and settings.search_interval_minutes == 120
            assert not settings.auto_apply_enabled and not settings.search_enabled
            profile = next(p for p in list_profiles(db) if p["name"] == "Backend")
            assert profile["preferences"]["work_mode"] == ["remote", "hybrid", "onsite"]
            assert db.execute("SELECT count(*) FROM knowledge_claims").fetchone()[0] == 0

    monkeypatch.setattr("pandapply.onboarding.dashboard", panel)
    assert run(tmp_path / "data.db") == 0
    assert observed == [3]


def test_onboarding_location_and_language_constraints_are_not_ignored():
    criteria = ProfileCriteria(locations=["Colombia"], languages=["es"], must_have_skills=["Python"],
                               confirmed_claims=["Python"])
    job = Candidate(title="Developer", company="Example", url="https://jobs.example.test/job", skills=["Python"])
    assert evaluate(criteria, job).status == "MANUAL_REVIEW"
    assert evaluate(criteria, job.model_copy(update={"locations": ["Chile"], "languages": ["es"]})).status == "SKIPPED_INELIGIBLE"
    assert evaluate(criteria, job.model_copy(update={"locations": ["Colombia"], "languages": ["en"]})).status == "SKIPPED_INELIGIBLE"
    assert evaluate(criteria, job.model_copy(update={"locations": ["Colombia"], "languages": ["es-CO"]})).status == "MATCHED"


def test_gmail_connection_does_not_ask_for_internal_paths(tmp_path, monkeypatch, capsys):
    home = tmp_path / "hermes"
    home.mkdir()
    detected = no_hermes() | {"home": str(home)}
    monkeypatch.setattr("pandapply.onboarding.discover", lambda **kwargs: detected)
    replies = iter(["1", "s", "s", "Backend", "UTC", "", "n", "n", "n"])

    def answer(prompt):
        assert "Ejecutable Python" not in prompt and "google_api.py" not in prompt
        return next(replies)

    monkeypatch.setattr("builtins.input", answer)
    assert run(tmp_path / "data.db") == 0
    assert "Gmail queda pendiente" in capsys.readouterr().out


def test_invalid_timezone_reasks_only_timezone_and_accepts_utc_offset(tmp_path, monkeypatch):
    monkeypatch.setattr("pandapply.onboarding.discover", no_hermes)
    replies = iter(["1", "", "Backend", "invalid-zone", "UTC-5", "", "n", "n", "n"])
    prompts = []

    def answer(prompt):
        prompts.append(prompt)
        return next(replies)

    monkeypatch.setattr("builtins.input", answer)
    path = tmp_path / "data.db"
    assert run(path) == 0
    assert sum("Nombre para estas preferencias" in prompt for prompt in prompts) == 1
    assert sum("Zona horaria (ej." in prompt for prompt in prompts) == 2
    with connect(path) as db:
        assert db.execute("SELECT timezone FROM master_profile").fetchone()[0] == "Etc/GMT+5"
