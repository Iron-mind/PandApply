"""Read-only discovery of existing Hermes assets; never opens credential files."""

import hashlib
import json
import os
import re
import shutil
from pathlib import Path


def _managed_python(project: Path, homes: list[Path], issues: list[str]) -> tuple[bool, list[Path]]:
    """Read PM's committed environment for this exact checkout, without importing Hermes."""
    key = hashlib.sha256(str(project.resolve()).encode("utf-8")).hexdigest()[:16]
    found = False
    selected = []
    for home in dict.fromkeys(homes):
        state = home / "installs" / key
        facts = state / "facts.json"
        if not facts.is_file():
            continue
        try:
            if facts.is_symlink() or facts.stat().st_size > 1_000_000:
                raise ValueError("Invalid installation metadata")
            data = json.loads(facts.read_text(encoding="utf-8-sig"))
            value = data.get("packages", {}).get("venv", {}).get("environment")
            if value is None:
                continue
            found = True
            if not isinstance(value, str) or not Path(value).is_absolute():
                raise ValueError("Invalid environment")
            environment = Path(value)
            if (not environment.resolve().is_relative_to((state / "environments").resolve())
                    or not (environment / "pyvenv.cfg").is_file()):
                raise ValueError("Missing or foreign environment")
            python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            if not python.is_file():
                raise ValueError("Missing interpreter")
            selected.append(python.absolute())
        except (OSError, ValueError, AttributeError):
            found = True
            issues.append("Hermes selected environment is unavailable; repair Hermes before connecting Gmail")
    return found, selected


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
    if not root and home:
        roots.append(home.parent.parent if home.parent.name == "profiles" else home)
    # Native installers place the checkout beside bin/, rather than inside the data home.
    for parent in list(roots):
        checkout = parent / "hermes-agent"
        if (checkout / "pyproject.toml").is_file() and (checkout / "hermes_cli").is_dir():
            roots.append(checkout)
    roots = list(dict.fromkeys(roots))
    homes = [home] if home else []
    if home and home.parent.name == "profiles":
        homes.append(home.parent.parent)
    if executable:
        homes.append(Path(executable).absolute().parent.parent)
    managed_found = False
    managed = []
    if not interpreter:
        for project in roots:
            if (project / "pyproject.toml").is_file() and (project / "hermes_cli").is_dir():
                found, candidates = _managed_python(project, homes + [project.parent], issues)
                managed_found |= found
                managed.extend(candidates)
    if interpreter:
        python_candidates = [interpreter.expanduser().absolute()]
    else:
        python_candidates = [r / folder / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
                             for r in roots for folder in (".venv", "venv")]
        if executable:
            python_candidates.insert(0, Path(executable).absolute().parent / ("python.exe" if os.name == "nt" else "python"))
    pythons = list(dict.fromkeys(p for p in python_candidates if p.is_file()))
    # Only select a venv interpreter automatically. Explicit paths remain visible for validation.
    if not interpreter:
        pythons = [p for p in pythons if (p.parent.parent / "pyvenv.cfg").is_file()]
        if managed_found:
            # A committed PM generation takes precedence over stale in-tree venvs.
            pythons = list(dict.fromkeys(managed))
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
