import subprocess
import sys

import pytest

from pandapply.adapters.hermes.guidance import launch_setup, setup_command
from pandapply.cli import main
from pandapply.configuration import patch_settings, read_settings
from pandapply.onboarding import (
    configure_browser,
    configure_gmail,
    configure_whatsapp,
    connect_integration,
    run,
)
from pandapply.storage import connect, migrate


def test_assistant_uses_selected_home_and_literal_prompt_without_capturing_secrets(tmp_path, monkeypatch):
    executable = tmp_path / 'hermes executable.exe'
    executable.touch()
    home = tmp_path / 'profile'
    home.mkdir()
    monkeypatch.setattr(sys.stdin, 'isatty', lambda: True)
    monkeypatch.setattr(sys.stdout, 'isatty', lambda: True)
    calls = []

    def execute(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, 'run', execute)
    assert launch_setup('gmail', executable, home)['status'] == 'conversation_finished'
    command, options = calls[0]
    assert command[:5] == [str(executable), '--profile', 'default', 'chat', '-q']
    assert 'Google Workspace' in command[-1] and 'No envíes correos' in command[-1]
    assert options['env']['HERMES_HOME'] == str(home.resolve())
    assert options['cwd'] == str(home.resolve())
    assert not options.get('shell') and not options.get('capture_output')
    assert not any(key in options for key in ('stdin', 'stdout', 'stderr', 'input'))
    assert '--yolo' not in command and '--oneshot' not in command


def test_named_profile_is_explicit_and_unknown_components_are_rejected(tmp_path):
    home = tmp_path / 'profiles' / 'work'
    home.mkdir(parents=True)
    command = setup_command('browser', tmp_path / 'hermes', home, browser_mode='cdp', cdp_endpoint='127.0.0.1:9222')
    assert command[1:3] == ['--profile', 'work']
    assert 'CDP' in command[-1] and '127.0.0.1:9222' in command[-1]
    with pytest.raises(ValueError):
        setup_command('arbitrary', tmp_path / 'hermes', home)


def test_non_terminal_and_missing_hermes_do_not_start_an_agent(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: calls.append(a))
    assert launch_setup('gmail', None, None)['status'] == 'unavailable'
    executable = tmp_path / 'hermes'
    executable.touch()
    monkeypatch.setattr(sys.stdin, 'isatty', lambda: False)
    assert launch_setup('gmail', executable, tmp_path)['status'] == 'needs_terminal'
    assert calls == []


@pytest.mark.parametrize('interrupted', [False, True])
def test_launch_failures_remain_failures(tmp_path, monkeypatch, interrupted):
    executable = tmp_path / 'hermes'
    executable.touch()
    monkeypatch.setattr(sys.stdin, 'isatty', lambda: True)
    monkeypatch.setattr(sys.stdout, 'isatty', lambda: True)

    def execute(*args, **kwargs):
        if interrupted:
            raise KeyboardInterrupt()
        raise OSError('private provider details')

    monkeypatch.setattr(subprocess, 'run', execute)
    assert launch_setup('gmail', executable, tmp_path)['status'] == ('interrupted' if interrupted else 'failed')


@pytest.fixture
def setup_state(tmp_path, monkeypatch):
    path = tmp_path / 'data.db'
    migrate(path)
    home = tmp_path / 'hermes-home'
    home.mkdir()
    executable = tmp_path / 'hermes.exe'
    executable.touch()
    script = tmp_path / 'workspace.py'
    script.touch()
    detected = {'executable': str(executable), 'home': str(home), 'python': sys.executable,
                'workspace_script': str(script), 'root': str(tmp_path), 'gmail': 'not_detected',
                'whatsapp': 'not_detected', 'issues': []}
    monkeypatch.setattr('pandapply.onboarding.discover', lambda **kw: detected)
    with connect(path) as db:
        patch_settings(db, tmp_path / 'config.json', {'hermes_home': str(home),
                       'hermes_executable': str(executable), 'hermes_python': sys.executable,
                       'hermes_workspace_script': str(script), 'hermes_root': str(tmp_path)}, actor='cli')
    return path, tmp_path / 'config.json', detected


def inputs(monkeypatch, replies):
    values = iter(replies)
    monkeypatch.setattr('builtins.input', lambda prompt: next(values))


def test_missing_gmail_can_be_configured_in_hermes_then_verified(setup_state, monkeypatch):
    path, config, detected = setup_state
    launches = []
    monkeypatch.setattr('pandapply.onboarding.launch_setup', lambda *a, **kw: launches.append(a) or {'status': 'conversation_finished'})
    monkeypatch.setattr('pandapply.onboarding.HermesWorkspaceReader.primary_account', lambda self: 'owner@example.test')
    inputs(monkeypatch, ['4', '', '10', '20', '2'])
    with connect(path) as db:
        configure_gmail(db, config, detected)
        settings = read_settings(db, config)
        assert settings.gmail_account == 'owner@example.test' and settings.gmail_enabled and settings.dry_run
        assert db.execute("SELECT state FROM connector_health WHERE connector_id='gmail'").fetchone()[0] == 'account_verified'
        assert db.execute('SELECT count(*) FROM reply_attempts').fetchone()[0] == 0
    assert len(launches) == 1 and launches[0][0] == 'gmail'


def test_failed_gmail_check_offers_assistance_and_rechecks_once(setup_state, monkeypatch):
    path, config, detected = setup_state
    checks = []

    def account(self):
        checks.append(1)
        if len(checks) == 1:
            raise ValueError('Unavailable')
        return 'owner@example.test'

    monkeypatch.setattr('pandapply.onboarding.HermesWorkspaceReader.primary_account', account)
    monkeypatch.setattr('pandapply.onboarding.launch_setup', lambda *a, **kw: {'status': 'conversation_finished'})
    inputs(monkeypatch, ['1', 's', '', '10', '20', '1'])
    with connect(path) as db:
        configure_gmail(db, config, detected)
        assert read_settings(db, config).gmail_account == 'owner@example.test'
    assert len(checks) == 2


def test_successful_conversation_is_not_proof_of_connection_or_account_switch(setup_state, monkeypatch):
    path, config, detected = setup_state
    monkeypatch.setattr('pandapply.onboarding.launch_setup', lambda *a, **kw: {'status': 'conversation_finished'})
    monkeypatch.setattr('pandapply.onboarding.HermesWorkspaceReader.primary_account', lambda self: 'other@example.test')
    inputs(monkeypatch, ['4', '', '', '10', '20', '1'])
    with connect(path) as db:
        patch_settings(db, config, {'gmail_account': 'owner@example.test'}, actor='cli')
        configure_gmail(db, config, detected)
        assert read_settings(db, config).gmail_account == 'owner@example.test'
        assert db.execute("SELECT state FROM connector_health WHERE connector_id='gmail'").fetchone()[0] == 'configured_unverified'


def test_failed_assistant_never_marks_gmail_verified(setup_state, monkeypatch):
    path, config, detected = setup_state
    monkeypatch.setattr('pandapply.onboarding.launch_setup', lambda *a, **kw: {'status': 'failed'})
    checks = []
    monkeypatch.setattr('pandapply.onboarding.HermesWorkspaceReader.primary_account', lambda self: checks.append(1))
    inputs(monkeypatch, ['4', ''])
    with connect(path) as db:
        configure_gmail(db, config, detected)
        assert not read_settings(db, config).gmail_enabled
        assert db.execute("SELECT state FROM connector_health WHERE connector_id='gmail'").fetchone()[0] == 'unavailable'
    assert checks == []


def test_missing_workspace_is_rediscovered_after_assistance(setup_state, monkeypatch):
    path, config, detected = setup_state
    script = detected['workspace_script']
    detected['workspace_script'] = None

    def installed(*args, **kwargs):
        detected['workspace_script'] = script
        return {'status': 'conversation_finished'}

    monkeypatch.setattr('pandapply.onboarding.launch_setup', installed)
    monkeypatch.setattr('pandapply.onboarding.HermesWorkspaceReader.primary_account', lambda self: 'owner@example.test')
    inputs(monkeypatch, ['1', 's', '', '10', '20', '1'])
    with connect(path) as db:
        patch_settings(db, config, {'hermes_workspace_script': ''}, actor='cli')
        configure_gmail(db, config, detected)
        assert read_settings(db, config).hermes_workspace_script == script
        assert read_settings(db, config).gmail_account == 'owner@example.test'


def test_browser_assistance_returns_to_selection_and_runs_actual_probe(setup_state, monkeypatch):
    path, config, _ = setup_state
    monkeypatch.setattr('pandapply.onboarding.launch_setup', lambda *a, **kw: {'status': 'conversation_finished'})
    probes = []
    monkeypatch.setattr('pandapply.onboarding.probe_cdp', lambda endpoint: probes.append(endpoint) or {
        'status': 'cdp_reachable', 'scope': 'local_connection_only'})
    inputs(monkeypatch, ['4', '2', '127.0.0.1:9222'])
    with connect(path) as db:
        configure_browser(db, config)
        assert db.execute("SELECT state FROM connector_health WHERE connector_id='browser'").fetchone()[0] == 'cdp_reachable'
    assert probes == ['http://127.0.0.1:9222']


def test_whatsapp_assistance_does_not_send_messages_or_claim_session_verified(setup_state, monkeypatch):
    path, config, detected = setup_state
    monkeypatch.setattr('pandapply.onboarding.launch_setup', lambda *a, **kw: {'status': 'conversation_finished'})
    detected['whatsapp'] = 'session_detected_not_verified'
    inputs(monkeypatch, ['s'])
    with connect(path) as db:
        configure_whatsapp(db, config)
        assert db.execute('SELECT count(*) FROM event_outbox').fetchone()[0] == 0
        assert db.execute("SELECT state FROM connector_health WHERE connector_id='whatsapp'").fetchone()[0] == 'session_detected_not_verified'


def test_failed_browser_repair_does_not_retry_forever_or_claim_ready(setup_state, monkeypatch):
    path, config, _ = setup_state
    probes, launches = [], []

    def unavailable(endpoint):
        probes.append(endpoint)
        raise ValueError('Unavailable')

    monkeypatch.setattr('pandapply.onboarding.probe_cdp', unavailable)
    monkeypatch.setattr('pandapply.onboarding.launch_setup', lambda *a, **kw: launches.append(a) or {'status': 'conversation_finished'})
    inputs(monkeypatch, ['2', '127.0.0.1:9222', 's', 's', ''])
    with connect(path) as db:
        configure_browser(db, config)
        assert db.execute("SELECT state FROM connector_health WHERE connector_id='browser'").fetchone()[0] == 'unavailable'
    assert len(probes) == 2 and len(launches) == 1


def test_connect_cli_only_repeats_the_requested_integration(tmp_path, monkeypatch):
    monkeypatch.setattr('pandapply.cli.data_dir', lambda: tmp_path)
    monkeypatch.setattr(sys, 'argv', ['pandapply', 'connect', 'gmail'])
    monkeypatch.setattr('pandapply.onboarding.discover', lambda **kw: {'home': None, 'gmail': 'not_detected'})
    inputs(monkeypatch, ['3'])
    assert main() == 0
    with connect(tmp_path / 'pandapply.db') as db:
        assert db.execute('SELECT count(*) FROM professional_profiles').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM event_outbox').fetchone()[0] == 0


def test_whatsapp_repair_preserves_unknown_pilot_without_resending(setup_state, monkeypatch):
    path, _, detected = setup_state
    detected['whatsapp'] = 'session_detected_not_verified'
    sends, assists = [], []

    def uncertain(*args):
        sends.append(args)
        raise OSError('simulated lost receipt')

    monkeypatch.setattr('pandapply.adapters.hermes.whatsapp.HermesWhatsApp.send', uncertain)
    monkeypatch.setattr('pandapply.onboarding.launch_setup', lambda *a, **kw: assists.append(a) or {'status': 'conversation_finished'})
    inputs(monkeypatch, ['1', 's', '3', '3', 'Backend', 'UTC', '', 'n', 'n',
                         's', '573001234567', 's', 's', 'n'])
    assert run(path) == 0
    inputs(monkeypatch, ['s'])
    assert connect_integration(path, 'whatsapp') == 0
    with connect(path) as db:
        row = db.execute("SELECT delivery_status,attempt_count FROM event_outbox WHERE event_type='PILOT_INVITATION'").fetchone()
        assert row['delivery_status'] == 'UNKNOWN' and row['attempt_count'] == 1
        assert db.execute('SELECT count(*) FROM event_outbox').fetchone()[0] == 1
    assert len(sends) == 1 and len(assists) == 2
