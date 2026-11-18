"""Read-only discovery of existing Hermes assets; never opens credential files."""

import os
import re
import shutil
from pathlib import Path


def discover(*, home: Path | None = None, root: Path | None = None,
             interpreter: Path | None = None) -> dict:
    executable = shutil.which("hermes")
    issues = []
    if home is None:
        configured = os.environ.get("HERMES_HOME", "").strip()
        if configured:
            home = Path(os.path.expandvars(configured)).expanduser()
        else:
            suffix = os.environ.get("HERMES_DATA_DIR_SUFFIX", "")
            candidates = [Path.home() / (".hermes" + suffix)]
            if os.name == "nt":
                candidates.insert(0, Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
                                  / ("hermes" + suffix))
            found = [p for p in candidates if p.is_dir()]
            if len(found) == 1:
                home = found[0]
                active = home / "active_profile"
                if active.is_file():
                    if active.stat().st_size > 128:
                        home = None
                        issues.append("Invalid active profile; use --hermes-home")
                    else:
                        name = active.read_text(encoding="utf-8").strip()
                        if name and name != "default":
                            if re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", name):
                                home = home / "profiles" / name
                            else:
                                home = None
                                issues.append("Invalid active profile; use --hermes-home")
            elif len(found) > 1:
                issues.append("Multiple Hermes homes found; use --hermes-home")
    if home is not None:
        home = home.expanduser().absolute()
        if not home.is_dir():
            issues.append("Selected Hermes home does not exist")
            home = None
    roots = [root.expanduser().absolute()] if root else []
    if not roots and executable:
        roots = list(dict.fromkeys([Path(executable).absolute().parent.parent,
                                   Path(executable).resolve().parent.parent]))
    if interpreter:
        python_candidates = [interpreter.expanduser().absolute()]
    else:
        python_candidates = [r / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python") for r in roots]
        if executable:
            python_candidates.insert(0, Path(executable).absolute().parent / ("python.exe" if os.name == "nt" else "python"))
    pythons = list(dict.fromkeys(p for p in python_candidates if p.is_file()))
    # Only select a venv interpreter automatically. Explicit paths remain visible for validation.
    if not interpreter:
        pythons = [p for p in pythons if (p.parent.parent / "pyvenv.cfg").is_file()]
    if len(pythons) > 1:
        issues.append("Multiple Hermes interpreters found; use --hermes-python")
    skill = Path("skills/productivity/google-workspace/scripts/google_api.py")
    scripts = list(dict.fromkeys(p / skill for p in ([home] if home else []) + roots if (p / skill).is_file()))
    script = scripts[0] if scripts else None  # Selected profile's skill takes precedence.
    gmail = bool(home and (home / "google_token.json").is_file())
    whatsapp = bool(home and any((home / p / "creds.json").is_file() for p in (
        "platforms/whatsapp/session", "whatsapp/session")))
    return {"executable": executable, "home": str(home) if home else None,
            "python": str(pythons[0]) if len(pythons) == 1 else None,
            "workspace_script": str(script) if script else None,
            "gmail": "credentials_detected_not_verified" if gmail else "not_detected",
            "whatsapp": "session_detected_not_verified" if whatsapp else "not_detected",
            "issues": issues}
