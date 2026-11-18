"""Hermes cron adapter, verified against Hermes 0.23.2 CLI in an isolated container."""

import os
import re
import sqlite3
import subprocess
import sys
from email.utils import parseaddr
from pathlib import Path

from pandapply.configuration import read_settings
from pandapply.hermes_workspace import HermesWorkspaceReader
from pandapply.storage import now

NAME = "pandapply-mail-monitor"
SCRIPT_NAME = "pandapply_mail_monitor.py"
SCRIPT_TEMPLATE = ("from pathlib import Path\nfrom pandapply.scheduler_worker import main\n"
                   "raise SystemExit(main(Path({database!r})))\n")


class SchedulerUnavailable(RuntimeError):
    pass


def _schedule(value: str) -> str:
    match = re.fullmatch(r"every\s+([1-9][0-9]{0,4})(m|h|d)", value.strip().lower())
    if not match:
        raise ValueError("Use a schedule such as 'every 20m', 'every 2h' or 'every 1d'")
    amount, unit = int(match.group(1)), match.group(2)
    minutes = amount * {"m": 1, "h": 60, "d": 1440}[unit]
    if not 5 <= minutes <= 10080:
        raise ValueError("Mail monitoring interval must be between 5 minutes and 7 days")
    return f"every {minutes}m"


class HermesCron:
    def __init__(self, executable: Path, home: Path, *, interpreter: Path | None = None, timeout: int = 30):
        # Preserve venv symlinks: resolving them executes the base interpreter on POSIX.
        self.executable = executable.expanduser().absolute()
        self.interpreter = (interpreter or Path(sys.executable)).expanduser().absolute()
        self.home = home.expanduser().resolve(strict=True)
        if (not self.executable.is_file() or not self.interpreter.is_file() or not self.home.is_dir()
                or timeout < 1):
            raise ValueError("An existing Hermes executable, home and PandApply interpreter are required")
        if os.name == "nt" and self.executable.suffix.lower() in (".cmd", ".bat", ".ps1"):
            raise SchedulerUnavailable("This Windows Hermes launcher is not yet supported safely; use CLI/web manually")
        self.timeout = timeout

    def _invoke(self, *args: str) -> str:
        env = {**os.environ, "HERMES_HOME": str(self.home)}
        try:
            result = subprocess.run([str(self.executable), "cron", *args], env=env, capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", timeout=self.timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SchedulerUnavailable("Hermes cron did not return a definitive result") from exc
        if result.returncode != 0 or len(result.stdout) > 100_000:
            raise SchedulerUnavailable("Hermes cron returned an error; inspect it locally before retrying")
        return result.stdout

    def _script(self, database: Path) -> None:
        scripts = self.home / "scripts"
        scripts.mkdir(mode=0o700, exist_ok=True)
        if scripts.resolve().parent != self.home:
            raise ValueError("Hermes scripts directory must remain inside the selected home")
        target = scripts / SCRIPT_NAME
        content = SCRIPT_TEMPLATE.format(database=str(database))
        if target.is_symlink():
            raise ValueError("Refusing a symlinked scheduler script")
        try:
            with target.open("x", encoding="utf-8", newline="\n") as output:
                output.write(content)
            if os.name != "nt":
                target.chmod(0o600)
        except FileExistsError:
            if not target.is_file() or target.read_text(encoding="utf-8") != content:
                raise ValueError("A different Hermes script already uses the PandApply name") from None

    def install(self, db: sqlite3.Connection, schedule: str) -> dict:
        schedule = _schedule(schedule)
        existing = db.execute("SELECT * FROM scheduled_jobs WHERE name=?", (NAME,)).fetchone()
        if existing:
            if existing["state"] in ("UNKNOWN", "CREATING"):
                raise SchedulerUnavailable("Cron state is uncertain; reconcile with Hermes before retrying")
            if (existing["hermes_home"] != str(self.home) or existing["hermes_executable"] != str(self.executable)
                    or existing["schedule"] != schedule):
                raise ValueError("A different PandApply mail job already exists")
            return dict(existing)
        help_text = self._invoke("create", "--help")
        if not all(flag in help_text for flag in ("--script", "--no-agent", "--interpreter", "--paused")):
            raise SchedulerUnavailable("Hermes cron lacks the required verified options")
        database = db.execute("PRAGMA database_list").fetchone()[2]
        if not database:
            raise ValueError("A persistent PandApply database is required for scheduling")
        self._script(Path(database).absolute())
        db.execute("BEGIN IMMEDIATE")
        try:
            timestamp = now()
            db.execute("INSERT INTO scheduled_jobs (name,hermes_home,hermes_executable,schedule,state,created_at,updated_at) "
                       "VALUES (?,?,?,?,'CREATING',?,?)", (NAME, str(self.home), str(self.executable),
                                                             schedule, timestamp, timestamp))
            db.commit()
        except sqlite3.IntegrityError as exc:
            db.rollback()
            raise SchedulerUnavailable("A cron installation is already in progress; inspect its state") from exc
        except Exception:
            db.rollback()
            raise
        try:
            output = self._invoke("create", schedule, "--name", NAME, "--paused", "--deliver", "local",
                                  "--script", SCRIPT_NAME, "--no-agent", "--interpreter", str(self.interpreter))
            match = re.search(r"(?m)^Created job:\s*([0-9a-f]{8,64})\s*$", output)
            if not match or "Created PAUSED" not in output:
                raise SchedulerUnavailable("Hermes did not confirm a paused job")
        except Exception:
            with db:
                db.execute("UPDATE scheduled_jobs SET state='UNKNOWN',updated_at=? WHERE name=?", (now(), NAME))
            raise
        with db:
            db.execute("UPDATE scheduled_jobs SET state='PAUSED',hermes_job_id=?,updated_at=? WHERE name=?",
                       (match.group(1), now(), NAME))
        return dict(db.execute("SELECT * FROM scheduled_jobs WHERE name=?", (NAME,)).fetchone())

    def change(self, db: sqlite3.Connection, *, action: str) -> dict:
        if action not in ("pause", "resume"):
            raise ValueError("Unsupported scheduler action")
        db.execute("BEGIN IMMEDIATE")
        try:
            row = db.execute("SELECT * FROM scheduled_jobs WHERE name=?", (NAME,)).fetchone()
            if (not row or row["state"] not in ("PAUSED", "ACTIVE") or not row["hermes_job_id"]
                    or row["hermes_home"] != str(self.home) or row["hermes_executable"] != str(self.executable)):
                raise SchedulerUnavailable("Cron job is missing or uncertain; reconcile before changing it")
            desired = "PAUSED" if action == "pause" else "ACTIVE"
            if row["state"] == desired:
                db.commit()
                return dict(row)
            if action == "resume":
                settings = read_settings(db, Path(db.execute("PRAGMA database_list").fetchone()[2]).parent / "config.json")
                if (not settings.gmail_enabled or settings.dry_run or not all((settings.gmail_account, settings.gmail_query,
                        settings.hermes_python, settings.hermes_workspace_script))):
                    raise ValueError("Configure Gmail monitoring and disable simulation before resuming")
                address = parseaddr(settings.gmail_account)[1]
                if not address or "@" not in address or address.casefold() != settings.gmail_account.strip().casefold():
                    raise ValueError("Configure the primary Gmail address without a display name")
                HermesWorkspaceReader(Path(settings.hermes_python), Path(settings.hermes_workspace_script))
            db.execute("UPDATE scheduled_jobs SET state='UNKNOWN',updated_at=? WHERE name=?", (now(), NAME))
            db.commit()
        except Exception:
            db.rollback()
            raise
        # UNKNOWN was committed before the external request; never blindly retry.
        output = self._invoke(action, row["hermes_job_id"])
        expected = ("Paused job:" if action == "pause" else "Resumed job:")
        if expected not in output or row["hermes_job_id"] not in output:
            raise SchedulerUnavailable("Hermes did not confirm the requested cron state")
        with db:
            db.execute("UPDATE scheduled_jobs SET state=?,updated_at=? WHERE name=? AND state='UNKNOWN'",
                       (desired, now(), NAME))
        return dict(db.execute("SELECT * FROM scheduled_jobs WHERE name=?", (NAME,)).fetchone())

    def reconcile(self, db: sqlite3.Connection) -> dict:
        """Inspect Hermes' verified 0.23.2 list format; never create or resume a job."""
        row = db.execute("SELECT * FROM scheduled_jobs WHERE name=?", (NAME,)).fetchone()
        if (not row or row["state"] not in ("UNKNOWN", "CREATING")
                or row["hermes_home"] != str(self.home) or row["hermes_executable"] != str(self.executable)):
            raise SchedulerUnavailable("No uncertain job for the selected Hermes installation")
        listing = self._invoke("list", "--all")
        headers = list(re.finditer(r"(?m)^\s{2}([0-9a-f]{8,64}) \[(paused|active)\]\s*$", listing))
        matches = []
        for index, header in enumerate(headers):
            end = headers[index + 1].start() if index + 1 < len(headers) else len(listing)
            block = listing[header.end():end]
            if (re.search(r"(?m)^\s+Name:\s+" + re.escape(NAME) + r"\s*$", block)
                    and re.search(r"(?m)^\s+Schedule:\s+" + re.escape(row["schedule"]) + r"\s*$", block)
                    and re.search(r"(?m)^\s+Script:\s+" + re.escape(SCRIPT_NAME) + r"\s*$", block)
                    and re.search(r"(?m)^\s+Python:\s+" + re.escape(str(self.interpreter)) + r"\s*$", block)
                    and re.search(r"(?m)^\s+Deliver:\s+local\s*$", block)
                    and "no-agent" in block):
                matches.append((header.group(1), header.group(2)))
        if len(matches) != 1:
            raise SchedulerUnavailable("Cannot uniquely identify the Hermes job; inspect cron list manually")
        job_id, state = matches[0]
        if row["hermes_job_id"] and row["hermes_job_id"] != job_id:
            raise SchedulerUnavailable("Hermes job ID differs from the recorded job")
        with db:
            updated = db.execute("UPDATE scheduled_jobs SET hermes_job_id=?,state=?,updated_at=? "
                                 "WHERE name=? AND state IN ('UNKNOWN','CREATING')",
                                 (job_id, state.upper(), now(), NAME)).rowcount
            if updated != 1:
                raise SchedulerUnavailable("Cron state changed during reconciliation")
        return dict(db.execute("SELECT * FROM scheduled_jobs WHERE name=?", (NAME,)).fetchone())
