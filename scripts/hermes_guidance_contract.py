"""Offline validation against Hermes' actual parser, never running a chat or OAuth."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from hermes_cli._parser import build_top_level_parser

from pandapply.adapters.hermes.guidance import setup_command

with tempfile.TemporaryDirectory(prefix='pandapply-guidance-') as temporary:
    root = Path(temporary)
    (root / 'config.yaml').write_text('{}', encoding='utf-8')
    named = root / 'profiles' / 'work'
    named.mkdir(parents=True)
    (named / 'config.yaml').write_text('{}', encoding='utf-8')
    executable = shutil.which('hermes')
    assert executable
    parser, _, _ = build_top_level_parser()
    for home in (root, named):
        for component in ('gmail', 'browser', 'whatsapp'):
            command = setup_command(component, Path(executable), home)
            args = parser.parse_args(command[3:])
            assert args.command == 'chat' and args.query == command[-1]
            assert not args.oneshot and not args.quiet
        # --help exercises the real profile selection / CLI without invoking a model.
        result = subprocess.run([*command[:3], 'chat', '--help'],
                                env={**os.environ, 'HERMES_HOME': str(home)},
                                capture_output=True, text=True, check=False, timeout=30)
        assert result.returncode == 0 and '--query' in result.stdout, result.stderr[-2000:]
    print('Hermes chat -q and explicit profile selection: passed (no agent, no OAuth, no messages)')
