import sys
from pathlib import Path

import pytest

from pandapply.hermes_workspace import HermesWorkspaceReader, WorkspaceUnavailable


def test_read_bridge_uses_argument_list_without_shell_and_never_sends(tmp_path):
    script = tmp_path / "google_api.py"
    script.write_text("import json,sys\n"
                      "assert sys.argv[1] == 'gmail'\n"
                      "assert sys.argv[2] in ('search', 'get')\n"
                      "print(json.dumps([{'id':'m1','query':sys.argv[3]}] if sys.argv[2]=='search' "
                      "else {'id':sys.argv[3],'body':'message'}))\n", encoding="utf-8")
    reader = HermesWorkspaceReader(Path(sys.executable), script)
    query = "from:test@example.test; echo SHOULD_NOT_EXECUTE"
    assert reader.search(query)[0]["query"] == query
    assert reader.get("m1")["id"] == "m1"
    with pytest.raises(ValueError):
        reader.get("--help")
    assert not hasattr(reader, "send")


def test_bridge_redacts_provider_errors(tmp_path):
    script = tmp_path / "google_api.py"
    script.write_text("import sys\nprint('private mailbox content', file=sys.stderr)\nsys.exit(1)\n", encoding="utf-8")
    reader = HermesWorkspaceReader(Path(sys.executable), script)
    with pytest.raises(WorkspaceUnavailable) as error:
        reader.search("is:unread")
    assert "private mailbox content" not in str(error.value)


def test_workspace_interpreter_symlink_is_not_resolved_outside_venv(tmp_path):
    link = tmp_path / "python"
    try:
        link.symlink_to(Path(sys.executable))
    except OSError:
        pytest.skip("Creating symlinks requires system permission")
    script = tmp_path / "workspace.py"
    script.write_text("# test", encoding="utf-8")
    reader = HermesWorkspaceReader(link, script)
    assert reader.interpreter == link.absolute()


def test_verified_read_binds_primary_account_before_getting_mail(tmp_path):
    marker = tmp_path / "mail-read"
    script = tmp_path / "workspace.py"
    script.write_text("from pathlib import Path\n"
                      "class Result:\n"
                      " def __init__(self, data): self.data=data\n"
                      " def execute(self): return self.data\n"
                      "class Service:\n"
                      " def users(self): return self\n"
                      " def messages(self): return self\n"
                      " def getProfile(self, **kw): return Result({'emailAddress':'owner@example.com'})\n"
                      f" def get(self, **kw): Path({str(marker)!r}).touch(); "
                      "return Result({'id':kw['id'], 'threadId':'thread'})\n"
                      "def build_service(api, version): return Service()\n"
                      "def _headers_dict(message): return {'from':'hr@example.com'}\n"
                      "def _extract_message_body(message): return 'body'\n", encoding="utf-8")
    reader = HermesWorkspaceReader(Path(sys.executable), script)
    with pytest.raises(WorkspaceUnavailable):
        reader.get_for_account("other@example.com", "m1")
    assert not marker.exists()
    assert reader.get_for_account("owner@example.com", "m1")["id"] == "m1"
    assert marker.exists()
