"""Bridge to Hermes Workspace with a separately gated reply dispatch.

The caller supplies the Hermes interpreter and script explicitly. Authentication and
token storage remain Hermes' responsibility. A reply requires a persisted one-use permit.
"""

import hashlib
import json
import os
import subprocess
from email.utils import parseaddr
from importlib.resources import as_file, files
from pathlib import Path


class WorkspaceUnavailable(RuntimeError):
    """The Hermes Workspace bridge could not complete a read operation."""


class HermesWorkspaceReader:
    def __init__(self, interpreter: Path, script: Path, *, timeout: float = 30, home: Path | None = None):
        # Preserve venv symlinks: resolving them can execute the base interpreter.
        self.interpreter = interpreter.expanduser().absolute()
        self.script = script.expanduser().resolve(strict=True)
        if not self.interpreter.is_file() or not self.script.is_file() or timeout <= 0:
            raise ValueError("An existing Hermes Python executable and Workspace script are required")
        self.timeout = timeout
        self.home = home.expanduser().resolve(strict=True) if home else None
        if self.home is not None and not self.home.is_dir():
            raise ValueError("Hermes profile directory must exist")

    def _environment(self) -> dict:
        return {**os.environ, **({"HERMES_HOME": str(self.home)} if self.home else {})}

    def _read(self, args: list[str]) -> object:
        try:
            result = subprocess.run([str(self.interpreter), str(self.script), "gmail", *args],
                                    stdin=subprocess.DEVNULL, capture_output=True, text=True, env=self._environment(),
                                    encoding="utf-8", errors="replace", timeout=self.timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise WorkspaceUnavailable("Hermes Google Workspace is unavailable or timed out") from exc
        # Do not include the provider's output in errors: it can contain mail or credentials.
        if result.returncode != 0 or len(result.stdout) > 5_000_000:
            raise WorkspaceUnavailable("Hermes Google Workspace returned an error or oversized response")
        try:
            result_json = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise WorkspaceUnavailable("Hermes Google Workspace returned invalid JSON") from exc
        if isinstance(result_json, dict) and (result_json.get("error") or result_json.get("status") == "error"):
            raise WorkspaceUnavailable("Hermes Google Workspace reported an error; check its authentication")
        return result_json

    def search(self, query: str, *, limit: int = 10) -> list[dict]:
        if not query.strip() or len(query) > 2000 or not 1 <= limit <= 100:
            raise ValueError("Search requires a query and a limit between 1 and 100")
        result = self._read(["search", query, "--max", str(limit)])
        if not isinstance(result, list) or not all(isinstance(item, dict) and isinstance(item.get("id"), str)
                                                   for item in result):
            raise WorkspaceUnavailable("Hermes Google Workspace returned an unexpected search result")
        return result

    def get(self, message_id: str) -> dict:
        if not message_id or len(message_id) > 512 or message_id.startswith("-"):
            raise ValueError("Invalid Gmail message ID")
        result = self._read(["get", message_id])
        if not isinstance(result, dict) or result.get("id") != message_id:
            raise WorkspaceUnavailable("Hermes Google Workspace returned an unexpected message")
        return result

    def _verified_read(self, account: str, request: dict) -> object:
        if (not isinstance(account, str) or not account.strip() or len(account) > 320
                or "\n" in account or "\r" in account):
            raise ValueError("A valid primary Gmail address is required")
        address = parseaddr(account)[1]
        if not address or "@" not in address or address.casefold() != account.strip().casefold():
            raise ValueError("Use the primary Gmail address without a display name")
        request = {**request, "account_hash": hashlib.sha256(address.casefold().encode()).hexdigest()}
        return self._helper_request(request)

    def _helper_request(self, request: dict) -> object:
        try:
            with as_file(files("pandapply").joinpath("hermes_workspace_helper.py")) as helper:
                result = subprocess.run([str(self.interpreter), str(helper), str(self.script)],
                                        input=json.dumps(request), capture_output=True, text=True, env=self._environment(),
                                        encoding="utf-8", errors="replace", timeout=self.timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise WorkspaceUnavailable("Hermes verified Gmail read is unavailable or timed out") from exc
        if result.returncode != 0 or len(result.stdout) > 5_000_000:
            raise WorkspaceUnavailable("Hermes could not verify the selected Gmail account or complete the read")
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise WorkspaceUnavailable("Hermes verified Gmail read returned invalid JSON") from exc

    def primary_account(self) -> str:
        """Explicit connectivity check; asks Gmail only for the existing account identity."""
        result = self._helper_request({"action": "profile"})
        address = result.get("emailAddress") if isinstance(result, dict) else None
        if (not isinstance(address, str) or len(address) > 320 or "@" not in address
                or any(char in address for char in "\r\n\x00") or parseaddr(address)[1] != address):
            raise WorkspaceUnavailable("Hermes did not return a valid primary Gmail address")
        return address

    def search_for_account(self, account: str, query: str, *, limit: int = 10) -> list[dict]:
        if not query.strip() or len(query) > 2000 or not 1 <= limit <= 20:
            raise ValueError("Search requires a query and a limit between 1 and 20")
        result = self._verified_read(account, {"action": "search", "query": query, "limit": limit})
        if not isinstance(result, list) or len(result) > limit or not all(
                isinstance(item, dict) and isinstance(item.get("id"), str) for item in result):
            raise WorkspaceUnavailable("Hermes verified Gmail search returned an unexpected result")
        return result

    def get_for_account(self, account: str, message_id: str) -> dict:
        if not message_id or len(message_id) > 512 or message_id.startswith("-"):
            raise ValueError("Invalid Gmail message ID")
        result = self._verified_read(account, {"action": "get", "message_id": message_id})
        if not isinstance(result, dict) or result.get("id") != message_id:
            raise WorkspaceUnavailable("Hermes verified Gmail read returned an unexpected message")
        return result

    def dispatch_approved(self, database: Path, attempt_id: str) -> dict:
        """The helper independently verifies and consumes the stored permit."""
        request = {"action": "send_approved", "database": str(database.resolve(strict=True)), "attempt_id": attempt_id}
        try:
            with as_file(files("pandapply").joinpath("hermes_workspace_helper.py")) as helper:
                result = subprocess.run([str(self.interpreter), str(helper), str(self.script)],
                                        input=json.dumps(request), capture_output=True, text=True, env=self._environment(),
                                        encoding="utf-8", errors="replace", timeout=self.timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise WorkspaceUnavailable("Hermes reply outcome is unknown") from exc
        if result.returncode != 0 or len(result.stdout) > 100_000:
            raise WorkspaceUnavailable("Hermes reply outcome is unknown")
        try:
            response = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise WorkspaceUnavailable("Hermes reply outcome is unknown") from exc
        if not isinstance(response, dict) or not isinstance(response.get("id"), str) or not response.get("id"):
            raise WorkspaceUnavailable("Hermes did not return a reply receipt")
        return response

    def find_reply(self, account: str, *, attempt_id: str, thread_id: str, recipient: str, body_sha256: str) -> dict:
        result = self._verified_read(account, {"action": "reconcile_reply", "attempt_id": attempt_id,
                                     "thread_id": thread_id, "recipient": recipient, "body_sha256": body_sha256})
        if not isinstance(result, dict) or result.get("status") not in ("found", "unknown"):
            raise WorkspaceUnavailable("Hermes returned an unexpected reconciliation result")
        if result["status"] == "found" and (not isinstance(result.get("id"), str) or not result["id"]):
            raise WorkspaceUnavailable("Hermes returned an incomplete reconciliation receipt")
        return result
