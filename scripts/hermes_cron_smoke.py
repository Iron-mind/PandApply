"""Verify Hermes cron lifecycle only inside a disposable, network-isolated container."""

import os
import re
import subprocess
import tempfile
from pathlib import Path


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="pandapply-cron-smoke-") as home:
        env = {**os.environ, "HERMES_HOME": home, "HERMES_WRITE_SAFE_ROOT": home, "HOME": home}

        def run(*args):
            result = subprocess.run(["/opt/hermes/bin/hermes", "cron", *args], env=env, capture_output=True,
                                    text=True, timeout=30, check=False)
            if result.returncode:
                raise RuntimeError("Hermes cron failed: " + result.stdout + result.stderr)
            return result.stdout.strip()

        script = Path(home) / "scripts" / "pandapply-test.py"
        script.parent.mkdir()
        script.write_text("print('synthetic test')\n", encoding="utf-8")
        created = run("create", "every 24h", "--name", "pandapply-smoke", "--paused", "--deliver", "local",
                      "--script", script.name, "--no-agent", "--interpreter", "/opt/hermes/.venv/bin/python")
        match = re.search(r"(?m)^Created job:\s*([0-9a-f]{8,64})\s*$", created)
        if not match:
            raise RuntimeError("Hermes did not report a recognizable job ID")
        job = match.group(1)
        listed = run("list")
        resumed = run("resume", job)
        active_list = run("list")
        paused = run("pause", job)
        if job not in listed or not resumed or not paused:
            raise RuntimeError("Hermes cron lifecycle did not return expected results")
        print("CREATED:\n" + created + "\nLISTED:\n" + listed + "\nRESUMED:\n" + resumed
              + "\nACTIVE LIST:\n" + active_list + "\nPAUSED:\n" + paused)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
