"""Local CLI with simulated workflows and explicitly gated experimental integrations."""

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

from pandapply.configuration import load_config, patch_settings, read_settings
from pandapply.profiles import add_profile, delete_profile, edit_profile, import_cv, list_profiles
from pandapply.runtime import HermesAdapter
from pandapply.storage import connect, migrate


def data_dir() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "PandApply"
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "pandapply"


def main() -> int:
    if sys.prefix == sys.base_prefix:
        print("PandApply requires a virtual environment. Activate .venv or run its pandapply executable.",
              file=sys.stderr)
        return 1
    parser = argparse.ArgumentParser(prog="pandapply")
    sub = parser.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser("doctor", help="Check runtime availability without changing data")
    doctor.add_argument("--json", action="store_true")
    setup = sub.add_parser("setup", help="Initialize local storage in safe simulation mode")
    setup.add_argument("--resume", action="store_true")
    setup.add_argument("--dry-run", action="store_true")
    setup.add_argument("--hermes-home", type=Path, help="Use this existing Hermes profile directory")
    setup.add_argument("--hermes-root", type=Path, help="Existing Hermes source installation")
    setup.add_argument("--hermes-python", type=Path, help="Existing Hermes virtual environment Python")
    setup.add_argument("--verify-gmail", action="store_true", help="Query the existing Gmail authorization for account identity")
    setup_mode = setup.add_mutually_exclusive_group()
    setup_mode.add_argument("--wizard", action="store_true", help="Run the step-by-step setup assistant")
    setup_mode.add_argument("--non-interactive", action="store_true", help="Print a JSON report without prompting")
    profiles = sub.add_parser("profiles", help="Manage local professional profiles")
    profile_commands = profiles.add_subparsers(dest="profile_command", required=True)
    profile_list = profile_commands.add_parser("list")
    profile_list.add_argument("--all", action="store_true", help="Include deleted profiles retained for history")
    profile_delete = profile_commands.add_parser("delete", help="Remove a profile from use, preserving its history")
    profile_delete.add_argument("profile_id")
    profile_delete.add_argument("--confirm", action="store_true")
    profile_delete.add_argument("--if-version", type=int)
    add = profile_commands.add_parser("add")
    add.add_argument("name")
    add.add_argument("--timezone", default="UTC")
    add.add_argument("--preferences", default="{}", help="JSON object with search preferences")
    edit = profile_commands.add_parser("edit")
    edit.add_argument("profile_id")
    edit.add_argument("--name")
    edit.add_argument("--preferences", help="Replace preferences with this JSON object")
    edit.add_argument("--if-version", type=int)
    cv = profile_commands.add_parser("import-cv")
    cv.add_argument("profile_id")
    cv.add_argument("path", type=Path)
    extract = profile_commands.add_parser("extract-cv")
    extract.add_argument("document_id")
    generate = profile_commands.add_parser("generate-cv")
    generate.add_argument("profile_id")
    generate.add_argument("output", type=Path)
    web = sub.add_parser("web", help="Start the authenticated local dashboard")
    web.add_argument("--host", default="127.0.0.1", choices=["127.0.0.1"])
    web.add_argument("--port", type=int, default=8765)
    sandbox = sub.add_parser("sandbox", help="Start the synthetic ATS on loopback")
    sandbox.add_argument("--port", type=int, default=8766)
    sub.add_parser("demo", help="Run the complete local simulation with temporary synthetic data")
    config = sub.add_parser("config", help="View or update safe local settings")
    config_commands = config.add_subparsers(dest="config_command", required=True)
    config_commands.add_parser("show")
    config_set = config_commands.add_parser("set")
    config_set.add_argument("key")
    config_set.add_argument("value", help="JSON value")
    run = sub.add_parser("run", help="Run a local workflow")
    run_commands = run.add_subparsers(dest="run_command", required=True)
    discovery = run_commands.add_parser("discovery", help="Evaluate a local JSON fixture")
    discovery.add_argument("--profile", required=True)
    source = discovery.add_mutually_exclusive_group(required=True)
    source.add_argument("--fixture", type=Path, help="Import synthetic .test jobs")
    source.add_argument("--input", type=Path, help="Import manually supplied job data without network access")
    discovery.add_argument("--dry-run", action="store_true", help="Do not persist results (default)")
    discovery.add_argument("--save", action="store_true", help="Save evaluation results locally")
    mail_run = run_commands.add_parser("mail", help="Review a bounded Gmail query through Hermes")
    mail_run.add_argument("--hermes-python", type=Path)
    mail_run.add_argument("--workspace-script", type=Path)
    mail_run.add_argument("--account-id")
    mail_run.add_argument("--query")
    mail_run.add_argument("--limit", type=int, default=10)
    memory = sub.add_parser("memory", help="Propose and approve a professional skill")
    memory_commands = memory.add_subparsers(dest="memory_command", required=True)
    propose = memory_commands.add_parser("propose")
    propose.add_argument("--profile", required=True)
    propose.add_argument("--skill", required=True)
    for action in ("approve", "reject"):
        decision = memory_commands.add_parser(action)
        decision.add_argument("proposal_id")
    export = sub.add_parser("export", help="Export local data to stdout")
    export.add_argument("--format", choices=["json", "csv"], required=True)
    gmail = sub.add_parser("gmail", help="Simulated Gmail workflow with .test addresses")
    gmail_commands = gmail.add_subparsers(dest="gmail_command", required=True)
    gmail_commands.add_parser("review-queue", help="List messages requiring manual review")
    dismiss_mail = gmail_commands.add_parser("mark-reviewed", help="Mark a queued message reviewed in Gmail")
    dismiss_mail.add_argument("--account-id", required=True, help="Hashed account identifier from review-queue")
    dismiss_mail.add_argument("--message-id", required=True)
    ingest = gmail_commands.add_parser("ingest")
    ingest.add_argument("--input", required=True, type=Path)
    suggest = gmail_commands.add_parser("suggest-reply")
    suggest.add_argument("--message-id", required=True)
    draft = gmail_commands.add_parser("draft")
    draft.add_argument("--message-id", required=True)
    draft.add_argument("--text", required=True)
    draft.add_argument("--account", help="Primary Gmail address for a reviewed real message")
    for action in ("approve", "reject"):
        reply_decision = gmail_commands.add_parser(action)
        reply_decision.add_argument("decision_id")
    send = gmail_commands.add_parser("send-approved")
    send.add_argument("--proposal-id", required=True)
    send_real = gmail_commands.add_parser("send-approved-real", help="Send one explicitly approved Gmail reply")
    send_real.add_argument("--proposal-id", required=True)
    send_real.add_argument("--hermes-python", required=True, type=Path)
    send_real.add_argument("--workspace-script", required=True, type=Path)
    send_real.add_argument("--confirm", action="store_true", help="Confirm this exact approved reply should be sent")
    reconcile_mail = gmail_commands.add_parser("reconcile-real", help="Search sent mail without resending an uncertain reply")
    reconcile_mail.add_argument("--proposal-id", required=True)
    reconcile_mail.add_argument("--hermes-python", required=True, type=Path)
    reconcile_mail.add_argument("--workspace-script", required=True, type=Path)
    for command in ("search-real", "get-real", "ingest-real"):
        read = gmail_commands.add_parser(command, help="Read using an explicitly configured Hermes Workspace script")
        read.add_argument("--hermes-python", type=Path)
        read.add_argument("--workspace-script", type=Path)
        if command == "search-real":
            read.add_argument("--query", required=True)
            read.add_argument("--limit", type=int, default=10)
        else:
            read.add_argument("--message-id", required=True)
            if command == "ingest-real":
                read.add_argument("--account-id", required=True, help="Stable account label (stored hashed)")
                read.add_argument("--application-id", required=True, help="Owner-selected application")
                read.add_argument("--classification", required=True,
                                  choices=["application_received", "rejection", "next_step", "interview", "offer"])
    applications = sub.add_parser("applications", help="Inspect and simulate applications")
    application_commands = applications.add_subparsers(dest="application_command", required=True)
    application_commands.add_parser("list")
    application_show = application_commands.add_parser("show")
    application_show.add_argument("application_id")
    application_prepare = application_commands.add_parser("sandbox-prepare")
    application_prepare.add_argument("application_id")
    application_prepare.add_argument("--document-id", required=True)
    application_submit = application_commands.add_parser("sandbox-submit")
    application_submit.add_argument("application_id")
    application_submit.add_argument("--consent", action="store_true", help="Explicitly authorize this simulated submission")
    application_submit.add_argument("--browser", choices=["fake", "hermes"], default="fake")
    application_submit.add_argument("--hermes-python", type=Path)
    application_submit.add_argument("--hermes-root", type=Path)
    application_reconcile = application_commands.add_parser("reconcile")
    application_reconcile.add_argument("application_id")
    manual = application_commands.add_parser("record-manual", help="Record a submission already completed by the owner")
    manual.add_argument("application_id")
    manual.add_argument("--receipt-id", required=True)
    manual.add_argument("--confirm", action="store_true", help="Confirm you already submitted and observed this receipt")
    decisions = sub.add_parser("decisions", help="Review pending local decisions")
    decisions_commands = decisions.add_subparsers(dest="decisions_command", required=True)
    list_decisions = decisions_commands.add_parser("list")
    list_decisions.add_argument("--status", default="PENDING")
    respond_decision = decisions_commands.add_parser("respond")
    respond_decision.add_argument("decision_id")
    respond_decision.add_argument("action", choices=["approve", "reject"])
    respond_decision.add_argument("--idempotency-key")
    policy = sub.add_parser("policy", help="Record reviewed site terms and inspect preliminary checks")
    policy_commands = policy.add_subparsers(dest="policy_command", required=True)
    policy_commands.add_parser("list")
    policy_review = policy_commands.add_parser("review")
    policy_review.add_argument("--domain", required=True)
    policy_review.add_argument("--operation", choices=["discover", "read", "fill", "submit"], required=True)
    policy_review.add_argument("--disposition", choices=["ALLOWED", "MANUAL_ONLY", "BLOCKED"], required=True)
    policy_review.add_argument("--source-url", required=True)
    policy_review.add_argument("--rationale", required=True)
    policy_review.add_argument("--expires-at", required=True, help="Future ISO 8601 timestamp with timezone")
    policy_review.add_argument("--confirm-reviewed", action="store_true")
    policy_consent = policy_commands.add_parser("consent")
    policy_consent.add_argument("policy_id")
    policy_consent.add_argument("--confirm", action="store_true")
    policy_check = policy_commands.add_parser("check")
    policy_check.add_argument("url")
    scheduler = sub.add_parser("scheduler", help="Manage the optional Hermes mail-monitor job")
    scheduler_commands = scheduler.add_subparsers(dest="scheduler_command", required=True)
    scheduler_install = scheduler_commands.add_parser("install")
    scheduler_install.add_argument("--hermes-executable", required=True, type=Path)
    scheduler_install.add_argument("--hermes-home", required=True, type=Path)
    scheduler_install.add_argument("--interval", help="Defaults to the Gmail interval configured in setup")
    for action in ("status", "pause", "resume", "reconcile"):
        scheduler_commands.add_parser(action)
    args = parser.parse_args()
    if args.command == "doctor":
        from pandapply.adapters.hermes.installation import discover

        result = {"python": sys.version.split()[0], "storage_path": str(data_dir()),
                  "hermes": HermesAdapter().capabilities(), "whatsapp_required": False,
                  "existing_installation": discover()}
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            print("Capabilities marked 'not verified' require integration tests.")
        return 0
    path = data_dir() / "pandapply.db"
    if args.command == "demo":
        from pandapply.demo import run_demo

        print(json.dumps(run_demo(), ensure_ascii=False, indent=2))
        return 0
    if path.exists() and args.command in {"profiles", "memory", "run", "web", "export", "gmail", "applications", "decisions", "config", "policy", "scheduler"}:
        migrate(path)
    if args.command == "scheduler":
        from pandapply.adapters.hermes.cron import NAME, HermesCron, SchedulerUnavailable

        if not path.exists():
            parser.error("Run pandapply setup first")
        try:
            with connect(path) as db:
                if args.scheduler_command == "install":
                    cron = HermesCron(args.hermes_executable, args.hermes_home)
                    settings = read_settings(db, data_dir() / "config.json")
                    result = cron.install(db, args.interval or f"every {settings.gmail_poll_interval_minutes}m")
                else:
                    row = db.execute("SELECT * FROM scheduled_jobs WHERE name=?", (NAME,)).fetchone()
                    if args.scheduler_command == "status":
                        result = {"status": "not_installed"} if not row else dict(row)
                    else:
                        if not row:
                            raise ValueError("Hermes mail-monitor job is not installed")
                        cron = HermesCron(Path(row["hermes_executable"]), Path(row["hermes_home"]))
                        result = (cron.reconcile(db) if args.scheduler_command == "reconcile"
                                  else cron.change(db, action=args.scheduler_command))
                print(json.dumps(result, ensure_ascii=False, indent=2))
        except (ValueError, OSError, SchedulerUnavailable) as exc:
            parser.error(str(exc))
        return 0
    if args.command == "policy":
        from dataclasses import asdict

        from pandapply.site_policy import consent, preflight, review

        if not path.exists():
            parser.error("Run pandapply setup first")
        try:
            with connect(path) as db:
                if args.policy_command == "list":
                    rows = db.execute("SELECT * FROM site_policy_reviews ORDER BY reviewed_at DESC").fetchall()
                    print(json.dumps([dict(row) for row in rows], ensure_ascii=False, indent=2))
                elif args.policy_command == "review":
                    if not args.confirm_reviewed:
                        raise ValueError("Confirm that you reviewed the source before recording a site policy")
                    print(review(db, domain=args.domain, operation=args.operation, disposition=args.disposition,
                                 source_url=args.source_url, rationale=args.rationale, expires_at=args.expires_at))
                elif args.policy_command == "consent":
                    consent(db, args.policy_id, confirm=args.confirm)
                    print(json.dumps({"policy_id": args.policy_id, "status": "consented"}))
                else:
                    settings = read_settings(db, data_dir() / "config.json")
                    print(json.dumps(asdict(preflight(db, args.url, settings)), ensure_ascii=False, indent=2))
        except (ValueError, OSError) as exc:
            parser.error(str(exc))
        return 0
    if args.command == "decisions":
        from pandapply.decisions import respond

        if not path.exists():
            parser.error("Run pandapply setup first")
        try:
            with connect(path) as db:
                if args.decisions_command == "list":
                    rows = db.execute("SELECT d.id,d.decision_type,d.related_entity_id,d.payload_json,"
                                      "d.authorized_channel,d.created_at,p.text_body,p.recipient "
                                      "FROM master_decisions d LEFT JOIN reply_proposals p "
                                      "ON d.decision_type='REPLY_APPROVAL' AND p.id=d.related_entity_id "
                                      "WHERE d.decision_status=? ORDER BY d.created_at DESC", (args.status,)).fetchall()
                    print(json.dumps([dict(row) for row in rows], ensure_ascii=False, indent=2))
                else:
                    key = args.idempotency_key or str(uuid.uuid4())
                    print(json.dumps(respond(db, args.decision_id, action=args.action, key=key, channel="cli")))
        except ValueError as exc:
            parser.error(str(exc))
        return 0
    if args.command == "applications":
        from pandapply.hermes_browser import SandboxBrowserUnavailable
        from pandapply.manual import record_submission
        from pandapply.sandbox_workflow import prepare, reconcile, submit, submit_with_hermes

        if not path.exists():
            parser.error("Run pandapply setup first")
        try:
            with connect(path) as db:
                if args.application_command == "list":
                    rows = db.execute("SELECT a.id,a.status,j.title,j.company_name FROM applications a "
                                      "JOIN job_postings j ON j.id=a.job_posting_id ORDER BY a.created_at DESC").fetchall()
                    print(json.dumps([dict(row) for row in rows], ensure_ascii=False, indent=2))
                elif args.application_command == "show":
                    row = db.execute("SELECT * FROM applications WHERE id=?", (args.application_id,)).fetchone()
                    if not row:
                        raise ValueError("Application not found")
                    print(json.dumps(dict(row), ensure_ascii=False, indent=2))
                elif args.application_command == "sandbox-prepare":
                    print(prepare(db, args.application_id, args.document_id))
                elif args.application_command == "sandbox-submit":
                    if args.browser == "hermes":
                        if not args.hermes_python or not args.hermes_root:
                            raise ValueError("Hermes Python and root are required for the browser sandbox")
                        receipt = submit_with_hermes(db, args.application_id, data_dir() / "sandbox-ats.db",
                                                     consent=args.consent, interpreter=args.hermes_python,
                                                     hermes_root=args.hermes_root)
                    else:
                        receipt = submit(db, args.application_id, data_dir() / "sandbox-ats.db", consent=args.consent)
                    print(json.dumps({"transport": "simulated", "receipt": receipt}))
                elif args.application_command == "record-manual":
                    record_submission(db, args.application_id, args.receipt_id, confirm=args.confirm)
                    print(json.dumps({"application_id": args.application_id, "status": "SUBMITTED",
                                      "evidence": "owner-confirmed"}))
                else:
                    receipt = reconcile(db, args.application_id, data_dir() / "sandbox-ats.db")
                    print(json.dumps({"transport": "simulated", "receipt": receipt, "resent": False}))
        except (ValueError, OSError, SandboxBrowserUnavailable) as exc:
            parser.error(str(exc))
        return 0
    if args.command == "gmail":
        from pandapply.hermes_workspace import HermesWorkspaceReader, WorkspaceUnavailable
        from pandapply.mail import (
            FakeGmail,
            MailOutcomeUnknown,
            decide_reply,
            ingest_fixture,
            propose_reply,
            send_fake_reply,
        )
        from pandapply.mail_review import ingest_for_review
        from pandapply.mail_send import reconcile_unknown, send_approved

        if not path.exists():
            parser.error("Run pandapply setup first")
        try:
            with connect(path) as db:
                if args.gmail_command == "review-queue":
                    rows = db.execute("SELECT gmail_account_id,gmail_message_id,reason,first_seen_at,last_seen_at "
                                      "FROM mail_review_queue WHERE state='PENDING' ORDER BY last_seen_at DESC").fetchall()
                    print(json.dumps([dict(row) for row in rows], ensure_ascii=False, indent=2))
                elif args.gmail_command == "mark-reviewed":
                    with db:
                        updated = db.execute("UPDATE mail_review_queue SET state='DISMISSED' WHERE gmail_account_id=? "
                                             "AND gmail_message_id=? AND state='PENDING'",
                                             (args.account_id, args.message_id)).rowcount
                    if not updated:
                        raise ValueError("Pending message not found")
                    print(json.dumps({"status": "reviewed"}))
                elif args.gmail_command == "ingest":
                    if args.input.stat().st_size > 5_000_000:
                        raise ValueError("Input file exceeds 5 MB")
                    document = json.loads(args.input.read_text(encoding="utf-8"))
                    if not isinstance(document, dict) or not isinstance(document.get("emails"), list):
                        raise ValueError("Input must contain an emails array")
                    print(json.dumps(ingest_fixture(db, document["emails"]), ensure_ascii=False, indent=2))
                elif args.gmail_command == "suggest-reply":
                    message = db.execute("SELECT classification,application_id FROM mailbox_messages WHERE id=?",
                                         (args.message_id,)).fetchone()
                    if not message or not message["application_id"] or message["classification"] != "interview":
                        raise ValueError("An approved, correlated interview is required")
                    print(json.dumps(["Thank you for reaching out. Please suggest available times.",
                                      "Thank you for the invitation. Could you share the next steps?"], indent=2))
                elif args.gmail_command == "draft":
                    proposal, decision = propose_reply(db, args.message_id, args.text, account=args.account)
                    print(json.dumps({"proposal_id": proposal, "decision_id": decision}, indent=2))
                elif args.gmail_command in ("approve", "reject"):
                    print(decide_reply(db, args.decision_id, approve=args.gmail_command == "approve"))
                elif args.gmail_command in ("search-real", "get-real", "ingest-real"):
                    settings = read_settings(db, data_dir() / "config.json")
                    interpreter = args.hermes_python or settings.hermes_python
                    script = args.workspace_script or settings.hermes_workspace_script
                    if not interpreter or not script:
                        raise ValueError("Run setup to detect Hermes or provide --hermes-python and --workspace-script")
                    reader = HermesWorkspaceReader(Path(interpreter), Path(script),
                                                   home=Path(settings.hermes_home) if settings.hermes_home else None)
                    if args.gmail_command == "search-real":
                        result = reader.search(args.query, limit=args.limit)
                    else:
                        message = (reader.get_for_account(args.account_id, args.message_id)
                                   if args.gmail_command == "ingest-real" else reader.get(args.message_id))
                        result = (ingest_for_review(db, args.account_id, message, application_id=args.application_id,
                                                    classification=args.classification)
                                  if args.gmail_command == "ingest-real" else message)
                    print(json.dumps(result, ensure_ascii=False, indent=2))
                elif args.gmail_command == "send-approved-real":
                    message_id = send_approved(path, args.proposal_id, interpreter=args.hermes_python,
                                               script=args.workspace_script, confirm=args.confirm)
                    print(json.dumps({"transport": "hermes-gmail", "message_id": message_id}))
                elif args.gmail_command == "reconcile-real":
                    result = reconcile_unknown(path, args.proposal_id, interpreter=args.hermes_python,
                                               script=args.workspace_script)
                    print(json.dumps(result))
                else:
                    message_id = send_fake_reply(db, args.proposal_id, FakeGmail())
                    print(json.dumps({"transport": "simulated", "message_id": message_id}))
        except (ValueError, OSError, WorkspaceUnavailable, MailOutcomeUnknown) as exc:
            parser.error(str(exc))
        return 0
    if args.command == "sandbox":
        import uvicorn

        from pandapply.sandbox import create_sandbox

        if not 1 <= args.port <= 65535:
            parser.error("Port must be between 1 and 65535")
        print(f"Synthetic ATS: http://127.0.0.1:{args.port}/ (use fictional data only)", flush=True)
        uvicorn.run(create_sandbox(data_dir() / "sandbox-ats.db"), host="127.0.0.1",
                    port=args.port, log_level="warning")
        return 0
    if args.command == "export":
        from pandapply.export import export_data

        if not path.exists():
            parser.error("Run pandapply setup first")
        with connect(path) as db:
            print(export_data(db, args.format))
        return 0
    if args.command == "memory":
        from pandapply.memory import decide_skill, propose_skill

        if not path.exists():
            parser.error("Run pandapply setup first")
        try:
            with connect(path) as db:
                if args.memory_command == "propose":
                    print(propose_skill(db, args.profile, args.skill))
                else:
                    print(decide_skill(db, args.proposal_id, approve=args.memory_command == "approve"))
        except ValueError as exc:
            parser.error(str(exc))
        return 0
    if args.command == "run":
        from pandapply.discovery import JsonDiscovery, ManualDiscovery, run_fixture
        from pandapply.hermes_workspace import HermesWorkspaceReader, WorkspaceUnavailable
        from pandapply.mail_monitor import poll

        if not path.exists():
            parser.error("Run pandapply setup first")
        if args.run_command == "discovery" and args.save and args.dry_run:
            parser.error("Choose --save or --dry-run, not both")
        try:
            with connect(path) as db:
                if args.run_command == "mail":
                    settings = read_settings(db, data_dir() / "config.json")
                    interpreter = args.hermes_python or settings.hermes_python
                    script = args.workspace_script or settings.hermes_workspace_script
                    account = args.account_id or settings.gmail_account
                    query = args.query or settings.gmail_query
                    if not interpreter or not script or not account or not query:
                        raise ValueError("Configure Hermes paths, Gmail account and query in the dashboard, or provide command options")
                    reader = HermesWorkspaceReader(Path(interpreter), Path(script),
                                                   home=Path(settings.hermes_home) if settings.hermes_home else None)
                    result = poll(db, reader, account=account, query=query, limit=args.limit)
                else:
                    settings = read_settings(db, data_dir() / "config.json")
                    provider = JsonDiscovery(args.fixture) if args.fixture else ManualDiscovery(args.input)
                    result = run_fixture(db, args.profile, provider, dry_run=not args.save,
                                         min_score=settings.min_match_score)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        except (ValueError, OSError, WorkspaceUnavailable) as exc:
            parser.error(str(exc))
        return 0
    if args.command == "config":
        config_path = data_dir() / "config.json"
        try:
            if not path.exists():
                if args.config_command == "set":
                    raise ValueError("Run pandapply setup first")
                settings = load_config(config_path)
            else:
                with connect(path) as db:
                    if args.config_command == "set":
                        settings = patch_settings(db, config_path, {args.key: json.loads(args.value)}, actor="cli")
                    else:
                        settings = read_settings(db, config_path)
            print(settings.model_dump_json(indent=2))
        except ValueError as exc:
            parser.error(str(exc))
        return 0
    if args.command == "web":
        if not path.exists():
            parser.error("Run pandapply setup first")
        if not 1 <= args.port <= 65535:
            parser.error("Port must be between 1 and 65535")
        from pandapply.onboarding import dashboard

        dashboard(path, host=args.host, port=args.port)
        return 0
    if args.command == "profiles":
        if not path.exists():
            parser.error("Run pandapply setup first")
        try:
            with connect(path) as db:
                if args.profile_command == "list":
                    print(json.dumps(list_profiles(db, include_inactive=args.all), ensure_ascii=False, indent=2))
                elif args.profile_command == "delete":
                    if not args.confirm:
                        raise ValueError("Add --confirm to remove this profile; application history and original CV files are preserved")
                    print(json.dumps(delete_profile(db, args.profile_id, actor="cli", expected_version=args.if_version)))
                elif args.profile_command == "add":
                    preferences = json.loads(args.preferences)
                    if not isinstance(preferences, dict):
                        raise ValueError("Preferences must be a JSON object")
                    print(add_profile(db, args.name, args.timezone, preferences))
                elif args.profile_command == "edit":
                    preferences = json.loads(args.preferences) if args.preferences is not None else None
                    version = edit_profile(db, args.profile_id, name=args.name, preferences=preferences,
                                           expected_version=args.if_version)
                    print(json.dumps({"id": args.profile_id, "version": version}))
                elif args.profile_command == "import-cv":
                    print(import_cv(db, args.profile_id, args.path))
                elif args.profile_command == "extract-cv":
                    from pandapply.documents import extract_cv

                    print(json.dumps(extract_cv(db, args.document_id), ensure_ascii=False, indent=2))
                else:
                    from pandapply.cv import render_cv

                    print(render_cv(db, args.profile_id, args.output))
        except (ValueError, OSError) as exc:
            parser.error(str(exc))
        return 0
    from pandapply.adapters.hermes.installation import discover
    from pandapply.hermes_workspace import HermesWorkspaceReader, WorkspaceUnavailable

    try:
        if args.wizard or (sys.stdin.isatty() and not args.non_interactive and not args.dry_run and not args.verify_gmail):
            if args.dry_run or args.verify_gmail:
                raise ValueError("Use --wizard alone; Gmail verification is offered inside the assistant")
            from pandapply.onboarding import run

            return run(path, home=args.hermes_home, root=args.hermes_root, interpreter=args.hermes_python)
        if args.dry_run and args.verify_gmail:
            raise ValueError("--dry-run cannot contact Gmail; run setup --verify-gmail separately")
        detected = discover(home=args.hermes_home, root=args.hermes_root, interpreter=args.hermes_python)
        report = {"storage": str(path), "dry_run": args.dry_run, "hermes": detected,
                  "next_steps": ["Create or select a professional profile", "Import and review your CV"]}
        if detected["gmail"] == "credentials_detected_not_verified":
            report["next_steps"].append("Reuse Hermes Gmail authorization; verify the selected account before enabling monitoring")
        if detected["whatsapp"] == "session_detected_not_verified":
            report["next_steps"].append("Existing WhatsApp session detected; PandApply messaging integration is not yet verified")
        if not args.dry_run:
            migrate(path)
            with connect(path) as db:
                settings = read_settings(db, data_dir() / "config.json")
                patch = {}
                same_home = (not settings.hermes_home or (detected["home"] and
                             Path(settings.hermes_home).resolve() == Path(detected["home"]).resolve()))
                if not same_home:
                    detected["issues"].append("Saved Hermes profile differs; existing configuration preserved")
                for key, value in (("hermes_home", detected["home"]), ("hermes_python", detected["python"]),
                                   ("hermes_workspace_script", detected["workspace_script"]), ("hermes_root", detected["root"])):
                    if value and same_home and not getattr(settings, key):
                        patch[key] = value
                if patch:
                    patch_settings(db, data_dir() / "config.json", patch, actor="cli")
                report["reused_settings"] = list(patch)
                if args.verify_gmail:
                    settings = read_settings(db, data_dir() / "config.json")
                    if not all((settings.hermes_python, settings.hermes_workspace_script, settings.hermes_home)):
                        raise ValueError("Hermes profile, interpreter and Workspace script are required to verify Gmail")
                    reader = HermesWorkspaceReader(Path(settings.hermes_python), Path(settings.hermes_workspace_script),
                                                   home=Path(settings.hermes_home))
                    account = reader.primary_account()
                    if settings.gmail_account and settings.gmail_account.casefold() != account.casefold():
                        raise ValueError("Authenticated Gmail account differs from saved account; configuration preserved")
                    if not settings.gmail_account:
                        patch_settings(db, data_dir() / "config.json", {"gmail_account": account}, actor="cli")
                    report["gmail_verification"] = {"status": "account_verified", "account": account,
                                                   "monitoring_enabled": settings.gmail_enabled}
        print(json.dumps(report, ensure_ascii=False, indent=2))
    except (OSError, ValueError, WorkspaceUnavailable) as exc:
        parser.error(str(exc))
    return 0
