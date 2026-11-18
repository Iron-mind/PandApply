"""Offline Linux launcher smoke test using the disposable Hermes container's venv."""

import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

with tempfile.TemporaryDirectory(prefix="pandapply setup smoke ") as temporary:
    root = Path(temporary)
    source = Path(__file__).resolve().parents[1]
    for filename in ("install.py", "install.sh"):
        shutil.copyfile(source / filename, root / filename)
    (root / ".venv").symlink_to(Path(sys.prefix), target_is_directory=True)
    env = {**os.environ, "HOME": str(root), "HERMES_HOME": str(root / "missing-hermes"),
           "XDG_DATA_HOME": str(root / "data"), "PYTHONPATH": str(source / "src")}
    result = subprocess.run(["sh", str(root / "install.sh"), "--configure-only"],
                            input="1\n\nBackend\nUTC\n\nn\nn\nn\n", env=env, capture_output=True,
                            text=True, encoding="utf-8", timeout=60, check=False)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    with sqlite3.connect(root / "data/pandapply/pandapply.db") as db:
        assert db.execute("SELECT name FROM professional_profiles").fetchone()[0] == "Backend"
    print("Linux launcher and guided setup: passed (offline, synthetic profile)")
