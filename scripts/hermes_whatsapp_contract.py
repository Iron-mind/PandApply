"""Verify Hermes' real send parser/JSON contract with a fake backend; never sends messages."""

import argparse
import io
import json
import sys
from contextlib import redirect_stdout
from types import SimpleNamespace

from hermes_cli import send_cmd

from pandapply.adapters.hermes.whatsapp import INVITATION


def fake_send(request):
    assert request == {"action": "send", "target": "whatsapp:573001234567@s.whatsapp.net", "message": INVITATION}
    return json.dumps({"success": True, "message_id": "synthetic-receipt"})


send_cmd._load_hermes_env = lambda: None
sys.modules["gateway.outbound.send"] = SimpleNamespace(send_message_tool=fake_send)
parser = argparse.ArgumentParser()
send_cmd.register_send_subparser(parser.add_subparsers())
arguments = parser.parse_args(["send", "--to", "whatsapp:573001234567@s.whatsapp.net", "--json", "--file", "-"])
sys.stdin = io.StringIO(INVITATION)
output = io.StringIO()
with redirect_stdout(output):
    try:
        send_cmd.cmd_send(arguments)
    except SystemExit as result:
        assert result.code == 0
assert json.loads(output.getvalue()) == {"success": True, "message_id": "synthetic-receipt"}
print("Hermes send parser and JSON receipt: passed (fake backend, no credentials, no messages sent)")
