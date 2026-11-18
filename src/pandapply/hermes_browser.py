"""Sandbox-only Hermes browser transport with an isolated temporary profile."""

import hashlib
import json
import os
import re
import subprocess
from importlib.resources import as_file, files
from pathlib import Path


class SandboxBrowserUnavailable(RuntimeError):
    pass


class HermesSandboxBrowser:
    def __init__(self, interpreter: Path, hermes_root: Path, *, timeout: int = 120):
        # Do not resolve the interpreter symlink: on POSIX it may point out of
        # the venv, and executing the resolved path would lose that environment.
        self.interpreter = interpreter.expanduser().absolute()
        self.hermes_root = hermes_root.expanduser().resolve(strict=True)
        if (not self.interpreter.is_file() or not (self.hermes_root / "tools" / "browser_use_cli.py").is_file()
                or timeout < 1):
            raise ValueError("A Hermes Python executable and source root with browser_exec are required")
        self.timeout = timeout

    def submit(self, *, url: str, attempt_id: str, pdf: bytes, directory: Path) -> str:
        """Run only a fixed local form. No personal browser profile or credentials are inherited."""
        home = directory / "hermes-home"
        runtime = directory / "runtime"
        home.mkdir(mode=0o700)
        runtime.mkdir(mode=0o700)
        cv = directory / "cv.pdf"
        with cv.open("xb") as handle:
            handle.write(pdf)
        if os.name != "nt":
            cv.chmod(0o600)
        allowed = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL")
        env = {key: os.environ[key] for key in allowed if key in os.environ}
        env.update({"HOME": str(home), "USERPROFILE": str(home), "APPDATA": str(home), "LOCALAPPDATA": str(home),
                    "HERMES_HOME": str(home), "HERMES_WRITE_SAFE_ROOT": str(home), "XDG_RUNTIME_DIR": str(runtime),
                    "PYTHONPATH": str(self.hermes_root), "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"})
        tools_dir = self.hermes_root / "tools"
        env["HERMES_RUNTIME_DIR"] = str(tools_dir)
        env["PLAYWRIGHT_BROWSERS_PATH"] = str(tools_dir)
        request = {"url": url, "attempt_id": attempt_id, "pdf_path": str(cv), "sandbox_dir": str(directory),
                   "pdf_sha256": hashlib.sha256(pdf).hexdigest()}
        try:
            with as_file(files("pandapply").joinpath("hermes_browser_helper.py")) as helper:
                result = subprocess.run([str(self.interpreter), str(helper)], input=json.dumps(request),
                                        capture_output=True, text=True, encoding="utf-8", errors="replace",
                                        env=env, timeout=self.timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SandboxBrowserUnavailable("Hermes sandbox browser failed or timed out") from exc
        if result.returncode != 0 or len(result.stdout) > 10_000:
            raise SandboxBrowserUnavailable("Hermes sandbox browser failed; submission may be uncertain")
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise SandboxBrowserUnavailable("Hermes sandbox browser returned an invalid receipt") from exc
        receipt = data.get("receipt") if isinstance(data, dict) else None
        if not isinstance(receipt, str) or not re.fullmatch(r"sandbox-[0-9a-f-]{36}", receipt):
            raise SandboxBrowserUnavailable("Hermes sandbox browser returned an invalid receipt")
        return receipt
