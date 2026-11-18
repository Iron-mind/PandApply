"""Runtime detection does not assume installed Hermes features are configured."""

import shutil
import subprocess
from typing import Protocol


class AgentRuntime(Protocol):
    def capabilities(self) -> dict[str, str]: ...


class HermesAdapter:
    def capabilities(self) -> dict[str, str]:
        path = shutil.which("hermes")
        result = {name: "not verified" for name in (
            "skills", "cron", "browser", "google_workspace", "whatsapp", "api", "dashboard"
        )}
        result["executable"] = path or "not installed"
        result["version"] = "unknown"
        if path:
            try:
                proc = subprocess.run([path, "--version"], capture_output=True, text=True,
                                      timeout=5, check=False)
                if proc.returncode == 0:
                    result["version"] = proc.stdout.strip()[:200] or "unknown"
            except (OSError, subprocess.TimeoutExpired):
                pass
        return result


class FakeAgentRuntime:
    def capabilities(self) -> dict[str, str]:
        return {"executable": "fake", "version": "fake"}
