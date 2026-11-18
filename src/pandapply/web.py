"""Authenticated local dashboard and explicitly authorized workflows."""

import html
import json
import secrets
import sqlite3
import time
from contextlib import closing
from importlib.resources import as_file, files
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from pandapply.configuration import patch_settings, read_settings
from pandapply.decisions import respond
from pandapply.discovery import JsonDiscovery, run_fixture
from pandapply.mail import (
    FakeGmail,
    MailBlocked,
    MailOutcomeUnknown,
    propose_reply,
    send_fake_reply,
)
from pandapply.mail_send import send_approved
from pandapply.memory import propose_skill
from pandapply.profiles import add_profile, edit_profile, list_profiles
from pandapply.storage import connect
from pandapply.work_modes import work_mode_label, work_mode_preference

security = HTTPBasic(auto_error=False)


class DecisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str


class ProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    preferences: dict = Field(default_factory=dict)
    active: bool = True
    version: int = 1


def create_app(database: Path, token: str) -> FastAPI:
    app = FastAPI(title="PandApply local", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1"])
    csrf_secret = secrets.token_urlsafe(32)
    sessions: dict[str, float] = {}
    session_lifetime = 12 * 60 * 60

    def equal(first: str, second: str) -> bool:
        return secrets.compare_digest(first.encode("utf-8"), second.encode("utf-8"))

    def has_session(request: Request) -> bool:
        session = request.cookies.get("pandapply_session", "")
        expires = sessions.get(session, 0)
        if expires <= time.monotonic():
            sessions.pop(session, None)
            return False
        return True

    def authorized(request: Request, credentials: Annotated[HTTPBasicCredentials | None, Depends(security)]) -> None:
        header = request.headers.get("authorization", "")
        supplied = header[7:] if header.startswith("Bearer ") else ""
        basic_ok = bool(credentials and equal(credentials.username, "pandapply")
                        and equal(credentials.password, token))
        try:
            bearer_ok = bool(supplied and secrets.compare_digest(supplied, token))
        except TypeError:
            bearer_ok = False
        if not (basic_ok or bearer_ok or has_session(request)):
            if request.method == "GET" and not request.url.path.startswith("/api/"):
                raise HTTPException(status_code=303, headers={"Location": "/login"})
            raise HTTPException(status_code=401, detail="Unauthorized",
                                headers={"WWW-Authenticate": "Basic, Bearer"})

    def authorized_mutation(request: Request) -> None:
        header = request.headers.get("authorization", "")
        supplied = header[7:] if header.startswith("Bearer ") else ""
        try:
            valid = bool(supplied and secrets.compare_digest(supplied, token))
        except TypeError:
            valid = False
        if not valid:
            raise HTTPException(status_code=401, detail="Bearer token required")
        origin = request.headers.get("origin")
        if origin and origin != f"http://{request.url.netloc}":
            raise HTTPException(status_code=403, detail="Cross-origin mutation denied")

    def check_form(request: Request, csrf: str) -> None:
        origin = request.headers.get("origin")
        if origin != f"http://{request.url.netloc}" or not secrets.compare_digest(csrf.encode(), csrf_secret.encode()):
            raise HTTPException(status_code=403, detail="Invalid origin or CSRF token")

    @app.middleware("http")
    async def protect_browser(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    def login_page(*, invalid: bool = False) -> HTMLResponse:
        error = "<p role='alert'>Usuario o contraseña incorrectos.</p>" if invalid else ""
        return HTMLResponse(
            "<!doctype html><html lang='es'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            "<title>Iniciar sesión — PandApply</title><style>"
            "body{font-family:system-ui,sans-serif;background:#f3f5f7;color:#18232d;margin:0;"
            "min-height:100vh;display:grid;place-items:center}main{background:white;padding:2rem;"
            "border-radius:1rem;width:min(24rem,80vw);box-shadow:0 8px 32px #18232d15}"
            "h1{margin-top:0}label{display:block;margin:1rem 0}input{box-sizing:border-box;display:block;"
            "width:100%;padding:.7rem;margin-top:.4rem;border:1px solid #aab4bd;border-radius:.4rem}"
            "button{width:100%;padding:.8rem;background:#185c47;color:white;border:0;"
            "border-radius:.4rem;font:inherit;cursor:pointer}[role=alert]{color:#a12020}</style></head>"
            "<body><main><h1>PandApply</h1><h2>Iniciar sesión</h2>"
            "<p>Usa la contraseña que aparece en la terminal donde abriste el panel.</p>"
            + error + "<form method='post' action='/login'>"
            f"<input type='hidden' name='csrf' value='{csrf_secret}'>"
            "<label>Usuario<input name='username' value='pandapply' autocomplete='username' required></label>"
            "<label>Contraseña<input name='password' type='password' autocomplete='current-password' required autofocus></label>"
            "<button>Entrar al panel</button></form>"
            "<p>Si reinicias PandApply, usa la nueva contraseña de la terminal.</p></main></body></html>",
            status_code=401 if invalid else 200)

    @app.get("/login", response_class=HTMLResponse)
    def login(request: Request):
        if has_session(request):
            return RedirectResponse(url="/", status_code=303)
        return login_page()

    @app.post("/login")
    def sign_in(request: Request, username: Annotated[str, Form()], password: Annotated[str, Form()],
                csrf: Annotated[str, Form()]):
        check_form(request, csrf)
        if not (equal(username, "pandapply") and equal(password, token)):
            return login_page(invalid=True)
        timestamp = time.monotonic()
        for session, expires in list(sessions.items()):
            if expires <= timestamp:
                sessions.pop(session, None)
        sessions.pop(request.cookies.get("pandapply_session", ""), None)
        if len(sessions) >= 256:
            sessions.pop(next(iter(sessions)))
        session = secrets.token_urlsafe(32)
        sessions[session] = timestamp + session_lifetime
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie("pandapply_session", session, max_age=session_lifetime, httponly=True, samesite="strict")
        return response

    @app.post("/logout", dependencies=[Depends(authorized)])
    def sign_out(request: Request, csrf: Annotated[str, Form()]):
        check_form(request, csrf)
        sessions.pop(request.cookies.get("pandapply_session", ""), None)
        response = RedirectResponse(url="/login", status_code=303)
        response.delete_cookie("pandapply_session", httponly=True, samesite="strict")
        return response

    @app.get("/api/v1/health", dependencies=[Depends(authorized)])
    def health():
        try:
            with closing(connect(database)) as db:
                db.execute("SELECT count(*) FROM professional_profiles").fetchone()
        except sqlite3.Error:
            return {"status": "unavailable", "components": {"database": "unavailable"}}
        return {"status": "degraded", "components": {"database": "available", "integrations": "not verified"}}

    @app.get("/api/v1/profiles", dependencies=[Depends(authorized)])
    def profiles():
        with closing(connect(database)) as db:
            return list_profiles(db)

    @app.post("/api/v1/profiles", status_code=201, dependencies=[Depends(authorized_mutation)])
    def create_profile(profile: ProfileRequest):
        if not profile.active or profile.version != 1:
            raise HTTPException(status_code=400, detail="New profiles must be active and version 1")
        try:
            with closing(connect(database)) as db:
                profile_id = add_profile(db, profile.name, "UTC", profile.preferences, profile_id=profile.id)
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Profile already exists") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"id": profile_id, "name": profile.name.strip(), "preferences": profile.preferences,
                "active": True, "version": 1}

    @app.get("/api/v1/config", dependencies=[Depends(authorized)])
    def config():
        with closing(connect(database)) as db:
            return read_settings(db, database.parent / "config.json").model_dump()

    @app.patch("/api/v1/config", dependencies=[Depends(authorized_mutation)])
    def update_config(patch: dict):
        try:
            with closing(connect(database)) as db:
                return patch_settings(db, database.parent / "config.json", patch, actor="web").model_dump()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/v1/jobs", dependencies=[Depends(authorized)])
    def jobs(profile_id: str | None = None):
        with closing(connect(database)) as db:
            if profile_id:
                query = ("SELECT j.id,j.title,j.company_name,j.location,j.source_url,j.discovered_at "
                         "FROM job_postings j JOIN applications a ON a.job_posting_id=j.id "
                         "WHERE a.profile_id=? ORDER BY j.discovered_at DESC")
                rows = db.execute(query, (profile_id,)).fetchall()
            else:
                rows = db.execute("SELECT id,title,company_name,location,source_url,discovered_at "
                                  "FROM job_postings ORDER BY discovered_at DESC").fetchall()
            return [dict(row) for row in rows]

    @app.get("/api/v1/applications", dependencies=[Depends(authorized)])
    def applications(limit: int = 30, offset: int = 0, status: str | None = None):
        if not 1 <= limit <= 100 or offset < 0:
            raise HTTPException(status_code=400, detail="Invalid pagination")
        where = " WHERE status=?" if status else ""
        parameters = (status,) if status else ()
        with closing(connect(database)) as db:
            total = db.execute("SELECT count(*) FROM applications" + where, parameters).fetchone()[0]
            items = [dict(row) for row in db.execute(
                "SELECT id,job_posting_id,profile_id,status,phase,match_score,policy_version,"
                "receipt_uri,applied_at FROM applications" + where + " ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (*parameters, limit, offset)).fetchall()]
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    @app.get("/api/v1/applications/{application_id}", dependencies=[Depends(authorized)])
    def application_detail(application_id: str):
        with closing(connect(database)) as db:
            row = db.execute("SELECT id,job_posting_id,profile_id,status,phase,match_score,policy_version,"
                             "receipt_uri,applied_at FROM applications WHERE id=?", (application_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Application not found")
        return dict(row)

    @app.get("/api/v1/decisions", dependencies=[Depends(authorized)])
    def decisions(status: str = "PENDING"):
        with closing(connect(database)) as db:
            rows = db.execute("SELECT d.id,d.decision_type,d.decision_status,d.related_entity_id,d.payload_json,"
                              "d.authorized_channel,d.created_at,d.expires_at,p.text_body,p.recipient "
                              "FROM master_decisions d LEFT JOIN reply_proposals p ON d.decision_type='REPLY_APPROVAL' "
                              "AND p.id=d.related_entity_id WHERE d.decision_status=? ORDER BY d.created_at DESC",
                              (status,)).fetchall()

        return [{"id": row["id"], "decision_type": row["decision_type"], "status": row["decision_status"],
                 "related_entity_id": row["related_entity_id"], "question": None, "options": [],
                 "created_at": row["created_at"], "payload": json.loads(row["payload_json"]),
                 "authorized_channel": row["authorized_channel"], "reply_text": row["text_body"],
                 "recipient": row["recipient"], "expires_at": row["expires_at"]} for row in rows]

    @app.post("/api/v1/decisions/{decision_id}/respond", dependencies=[Depends(authorized_mutation)])
    def respond_to_decision(decision_id: str, response: DecisionResponse,
                            idempotency_key: Annotated[str, Header(alias="Idempotency-Key")]):
        try:
            with closing(connect(database)) as db:
                return respond(db, decision_id, action=response.action, key=idempotency_key, channel="web")
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v1/events", dependencies=[Depends(authorized)])
    def events(limit: int = 30):
        if not 1 <= limit <= 100:
            raise HTTPException(status_code=400, detail="Invalid limit")
        with closing(connect(database)) as db:
            rows = db.execute("SELECT id,application_id,event_type,created_at,payload_redacted_json "
                              "FROM application_events ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [{"id": row["id"], "application_id": row["application_id"], "event_type": row["event_type"],
                 "timestamp": row["created_at"],
                 "payload": json.loads(row["payload_redacted_json"]) if row["payload_redacted_json"] else {}}
                for row in rows]

    @app.get("/api/v1/connectors", dependencies=[Depends(authorized)])
    def connectors():
        with closing(connect(database)) as db:
            rows = db.execute("SELECT connector_id,state,detail_redacted FROM connector_health").fetchall()
        return [{"id": row["connector_id"], "status": row["state"], "detail": row["detail_redacted"]} for row in rows]

    @app.get("/", response_class=HTMLResponse, dependencies=[Depends(authorized)])
    def dashboard():
        with closing(connect(database)) as db:
            rows = list_profiles(db)
            job_count = db.execute("SELECT count(*) FROM job_postings").fetchone()[0]
            application_count = db.execute("SELECT count(*) FROM applications").fetchone()[0]
            recent = db.execute("SELECT j.title,j.company_name,a.status FROM applications a "
                                "JOIN job_postings j ON j.id=a.job_posting_id "
                                "ORDER BY a.created_at DESC LIMIT 30").fetchall()
            pending = db.execute("SELECT d.id,d.decision_type,d.payload_json,d.authorized_channel,d.expires_at,p.text_body,p.recipient "
                                 "FROM master_decisions d LEFT JOIN reply_proposals p ON d.decision_type='REPLY_APPROVAL' "
                                 "AND p.id=d.related_entity_id WHERE d.decision_status='PENDING' "
                                 "ORDER BY d.created_at DESC LIMIT 30").fetchall()
            inbox = db.execute("SELECT id,sender,classification,application_id,gmail_account_id FROM mailbox_messages "
                               "ORDER BY processed_at DESC LIMIT 30").fetchall()
            mail_review_queue = db.execute("SELECT gmail_account_id,gmail_message_id,reason FROM mail_review_queue "
                                           "WHERE state='PENDING' ORDER BY last_seen_at DESC LIMIT 30").fetchall()
            approved = db.execute("SELECT p.id,p.recipient,p.text_body,m.gmail_account_id,d.payload_json,d.expires_at "
                                  "FROM reply_proposals p JOIN mailbox_messages m ON m.id=p.mailbox_message_id "
                                  "JOIN master_decisions d ON d.id=p.approved_by_decision_id "
                                  "WHERE p.state='APPROVED' AND d.decision_status='APPROVED' "
                                  "ORDER BY p.updated_at DESC LIMIT 30").fetchall()
            settings = read_settings(db, database.parent / "config.json")
            settings_revision = db.execute("SELECT COALESCE(MAX(id),0) FROM config_revisions").fetchone()[0]
        profile_items = []
        for profile in rows:
            profile_id = html.escape(profile["id"], quote=True)
            preferences = profile["preferences"]
            skills = preferences.get("must_have_skills", [])
            skills_text = ", ".join(value for value in skills if isinstance(value, str)) if isinstance(skills, list) else ""
            mode = work_mode_label(preferences.get("work_mode"))
            salary = preferences.get("salary_min_usd_month", "")
            profile_items.append(
                f"<li>{html.escape(profile['name'])}<form method='post' action='/profiles/{profile_id}/skills'>"
                f"<input type='hidden' name='csrf' value='{csrf_secret}'>"
                "<label>Habilidad <input name='skill' required maxlength='200'></label> "
                "<button>Proponer habilidad</button></form>"
                f"<form method='post' action='/profiles/{profile_id}/preferences'>"
                f"<input type='hidden' name='csrf' value='{csrf_secret}'>"
                f"<input type='hidden' name='version' value='{profile['version']}'>"
                f"<label>Habilidades obligatorias, separadas por comas <input name='skills' "
                f"value='{html.escape(skills_text, quote=True)}'></label> "
                f"<label>Modalidades (varias separadas por comas; any = todas) <input name='work_mode' value='{html.escape(mode, quote=True)}' "
                "placeholder='remote, hybrid'></label> "
                f"<label>Salario mínimo USD/mes <input name='salary' type='number' min='0' step='0.01' "
                f"value='{html.escape(str(salary), quote=True)}'></label> "
                "<button>Guardar preferencias</button></form>"
                f"<form method='post' action='/profiles/{profile_id}/fixture-discovery'>"
                f"<input type='hidden' name='csrf' value='{csrf_secret}'>"
                "<button>Evaluar vacantes ficticias</button></form></li>"
            )
        names = "".join(profile_items) or "<li>Sin perfiles</li>"
        jobs_html = "".join(
            f"<li>{html.escape(row['title'])} — {html.escape(row['company_name'])} "
            f"({html.escape(row['status'])})</li>" for row in recent
        ) or "<li>Sin vacantes evaluadas</li>"
        decisions_html = []
        for row in pending:
            payload = json.loads(row["payload_json"])
            if row["decision_type"] == "MEMORY_SKILL":
                summary = "¿Guardar la habilidad: " + str(payload.get("skill", "")) + "?"
            elif row["decision_type"] == "REPLY_APPROVAL":
                summary = "¿Aprobar respuesta a " + str(row["recipient"]) + ": " + str(row["text_body"]) + "?"
                if payload.get("primary_account"):
                    summary += " Cuenta de envío: " + str(payload["primary_account"])
                if row["expires_at"]:
                    summary += " Vence: " + str(row["expires_at"])
            elif row["decision_type"] == "MAIL_REVIEW":
                summary = ("Revise primero el correo en Gmail. ¿Confirmar " + str(payload.get("proposed_classification"))
                           + " para la postulación " + str(payload.get("application_id")) + "? Remitente: "
                           + str(payload.get("sender")) + "; mensaje: " + str(payload.get("gmail_message_id")))
            else:
                summary = "Decisión no disponible en el panel: " + row["decision_type"]
            item = "<li><p>" + html.escape(summary) + "</p>"
            if row["decision_type"] in ("MEMORY_SKILL", "REPLY_APPROVAL", "MAIL_REVIEW") and row["authorized_channel"] in ("local", "web"):
                key = secrets.token_urlsafe(16)
                item += (f"<form method='post' action='/decisions/{html.escape(row['id'], quote=True)}/respond'>"
                         f"<input type='hidden' name='csrf' value='{csrf_secret}'>"
                         f"<input type='hidden' name='key' value='{key}'>"
                         "<button name='action' value='approve'>Aprobar</button> "
                         "<button name='action' value='reject'>Rechazar</button></form>")
            else:
                item += "<p>Responder desde el canal autorizado.</p>"
            decisions_html.append(item + "</li>")
        decisions_markup = "".join(decisions_html) or "<li>No hay decisiones pendientes</li>"
        inbox_items = []
        for message in inbox:
            item = ("<li>" + html.escape(str(message["sender"] or "Remitente desconocido")) + " — "
                    + html.escape(str(message["classification"] or "Pendiente de revisión")))
            if message["application_id"] and message["classification"] == "interview":
                item += (f"<form method='post' action='/mail/{html.escape(message['id'], quote=True)}/suggest'>"
                         f"<input type='hidden' name='csrf' value='{csrf_secret}'>"
                         "<button>Solicitar sugerencias de respuesta</button></form>")
            inbox_items.append(item + "</li>")
        inbox_markup = "".join(inbox_items) or "<li>No hay correos registrados</li>"
        manual_mail_items = []
        for message in mail_review_queue:
            account_id = html.escape(message["gmail_account_id"], quote=True)
            message_id = html.escape(message["gmail_message_id"], quote=True)
            manual_mail_items.append(
                f"<li>Mensaje {message_id} — {html.escape(message['reason'])}"
                "<form method='post' action='/mail/manual-review/dismiss'>"
                f"<input type='hidden' name='csrf' value='{csrf_secret}'>"
                f"<input type='hidden' name='account_id' value='{account_id}'>"
                f"<input type='hidden' name='message_id' value='{message_id}'>"
                "<button>Ya lo revisé en Gmail</button></form></li>")
        manual_mail_markup = "".join(manual_mail_items) or "<li>No hay correos pendientes</li>"
        approved_items = []
        for reply in approved:
            payload = json.loads(reply["payload_json"])
            simulated = reply["gmail_account_id"] == "fixture"
            summary = ("Simulación" if simulated else "Gmail real experimental") + " — Para: " + str(reply["recipient"])
            if not simulated:
                summary += " — Cuenta: " + str(payload.get("primary_account", ""))
            item = "<li><p>" + html.escape(summary) + "</p><pre>" + html.escape(reply["text_body"]) + "</pre>"
            item += f"<p>La aprobación vence: {html.escape(str(reply['expires_at'] or 'sin fecha'))}</p>"
            item += (f"<form method='post' action='/mail/replies/{html.escape(reply['id'], quote=True)}/send'>"
                     f"<input type='hidden' name='csrf' value='{csrf_secret}'>")
            if not simulated:
                item += ("<label>Python de Hermes <input name='hermes_python' required></label> "
                         "<label>Script Google Workspace <input name='workspace_script' required></label> "
                         "<button>Enviar respuesta real aprobada</button>")
            else:
                item += "<button>Enviar respuesta simulada</button>"
            approved_items.append(item + "</form></li>")
        approved_markup = "".join(approved_items) or "<li>No hay respuestas aprobadas</li>"
        return ("<!doctype html><html lang='es'><meta charset='utf-8'><title>PandApply</title>"
                "<style>body{font:16px system-ui;max-width:60rem;margin:3rem auto;padding:0 1rem}"
                "section{border:1px solid #ccc;border-radius:.5rem;padding:1rem;margin:1rem 0}</style>"
                f"<h1>PandApply</h1><p>Panel local</p>"
                f"<form method='post' action='/logout'><input type='hidden' name='csrf' value='{csrf_secret}'>"
                f"<button>Cerrar sesión</button></form><section><h2>Perfiles</h2><ul>{names}</ul>"
                f"<form method='post' action='/profiles'><input type='hidden' name='csrf' value='{csrf_secret}'>"
                "<label>Nombre <input name='name' required maxlength='200'></label> "
                "<label>Zona horaria (ciudad o desfase, ej. America/Bogota o UTC-5) <input name='timezone' value='UTC' required></label> "
                "<button>Crear perfil</button></form></section>"
                f"<section><h2>Actividad</h2><p>Vacantes: {job_count}</p>"
                f"<p>Postulaciones: {application_count}</p></section>"
                f"<section><h2>Vacantes evaluadas</h2><ul>{jobs_html}</ul></section>"
                f"<section><h2>Decisiones pendientes</h2><ul>{decisions_markup}</ul></section>"
                f"<section><h2>Correo registrado</h2><ul>{inbox_markup}</ul></section>"
                f"<section><h2>Correos para revisar en Gmail</h2><ul>{manual_mail_markup}</ul></section>"
                f"<section><h2>Respuestas aprobadas</h2><ul>{approved_markup}</ul></section>"
                f"<section><h2>Configuración</h2><form method='post' action='/config'>"
                f"<input type='hidden' name='csrf' value='{csrf_secret}'>"
                f"<label>Idioma <input name='locale' value='{html.escape(settings.locale, quote=True)}' required></label> "
                f"<label>Compatibilidad mínima <input name='min_match_score' type='number' min='0' max='1' step='0.01' "
                f"value='{settings.min_match_score}' required></label> <button>Guardar</button></form>"
                f"<p>Modo de simulación: {'activado' if settings.dry_run else 'desactivado'}</p>"
                "<p>El envío real es experimental y requiere revisión, aprobación y confirmación adicional.</p>"
                f"<form method='post' action='/config/gmail'><input type='hidden' name='csrf' value='{csrf_secret}'>"
                f"<input type='hidden' name='revision' value='{settings_revision}'>"
                f"<label><input type='checkbox' name='gmail_enabled' {'checked' if settings.gmail_enabled else ''}> Gmail habilitado</label> "
                f"<label><input type='checkbox' name='gmail_reply_enabled' {'checked' if settings.gmail_reply_enabled else ''}> Respuestas reales habilitadas</label> "
                f"<label><input type='checkbox' name='dry_run' {'checked' if settings.dry_run else ''}> Modo simulación</label> "
                "<button>Guardar configuración de Gmail</button></form>"
                "<p>Datos para el seguimiento programado; no introduzca contraseñas ni tokens.</p>"
                f"<form method='post' action='/config/mail-monitor'><input type='hidden' name='csrf' value='{csrf_secret}'>"
                f"<input type='hidden' name='revision' value='{settings_revision}'>"
                f"<label>Cuenta principal <input name='gmail_account' value='{html.escape(settings.gmail_account, quote=True)}'></label> "
                f"<label>Consulta Gmail <input name='gmail_query' value='{html.escape(settings.gmail_query, quote=True)}'></label> "
                f"<label>Python de Hermes <input name='hermes_python' value='{html.escape(settings.hermes_python, quote=True)}'></label> "
                f"<label>Perfil de Hermes (directorio) <input name='hermes_home' value='{html.escape(settings.hermes_home, quote=True)}'></label> "
                f"<label>Script Google Workspace <input name='hermes_workspace_script' value='{html.escape(settings.hermes_workspace_script, quote=True)}'></label> "
                f"<label>Límite de mensajes <input name='gmail_poll_limit' type='number' min='1' max='20' value='{settings.gmail_poll_limit}' required></label> "
                "<button>Guardar seguimiento</button></form></section>"
                "<p>Las integraciones todavía no están verificadas.</p></html>")

    @app.post("/decisions/{decision_id}/respond", dependencies=[Depends(authorized)])
    def respond_from_dashboard(request: Request, decision_id: str, action: Annotated[str, Form()],
                               csrf: Annotated[str, Form()], key: Annotated[str, Form()]):
        check_form(request, csrf)
        try:
            with closing(connect(database)) as db:
                respond(db, decision_id, action=action, key=key, channel="web")
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return RedirectResponse(url="/", status_code=303)

    @app.post("/profiles", dependencies=[Depends(authorized)])
    def create_profile_from_dashboard(request: Request, name: Annotated[str, Form()],
                                      timezone: Annotated[str, Form()], csrf: Annotated[str, Form()]):
        check_form(request, csrf)
        try:
            with closing(connect(database)) as db:
                add_profile(db, name, timezone, {})
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse(url="/", status_code=303)

    @app.post("/profiles/{profile_id}/skills", dependencies=[Depends(authorized)])
    def propose_skill_from_dashboard(request: Request, profile_id: str, skill: Annotated[str, Form()],
                                     csrf: Annotated[str, Form()]):
        check_form(request, csrf)
        try:
            with closing(connect(database)) as db:
                propose_skill(db, profile_id, skill)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse(url="/", status_code=303)

    @app.post("/profiles/{profile_id}/preferences", dependencies=[Depends(authorized)])
    def edit_preferences_from_dashboard(request: Request, profile_id: str, csrf: Annotated[str, Form()],
                                        version: Annotated[int, Form()], skills: Annotated[str, Form()] = "",
                                        work_mode: Annotated[str, Form()] = "", salary: Annotated[str, Form()] = ""):
        check_form(request, csrf)
        try:
            mode = work_mode_preference(work_mode)
            parsed_salary = float(salary) if salary.strip() else None
            if parsed_salary is not None and not 0 <= parsed_salary <= 10_000_000:
                raise ValueError("Invalid salary")
            skill_list = [part.strip() for part in skills.split(",") if part.strip()]
            if len(skill_list) > 100 or any(len(part) > 200 for part in skill_list):
                raise ValueError("Too many skills or skill text too long")
            with closing(connect(database)) as db:
                row = db.execute("SELECT preferences_json FROM professional_profiles WHERE id=?", (profile_id,)).fetchone()
                if not row:
                    raise ValueError("Profile not found")
                preferences = json.loads(row[0])
                preferences["must_have_skills"] = skill_list
                if mode:
                    preferences["work_mode"] = mode
                else:
                    preferences.pop("work_mode", None)
                if parsed_salary is not None:
                    preferences["salary_min_usd_month"] = parsed_salary
                else:
                    preferences.pop("salary_min_usd_month", None)
                edit_profile(db, profile_id, preferences=preferences, expected_version=version)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse(url="/", status_code=303)

    @app.post("/profiles/{profile_id}/fixture-discovery", dependencies=[Depends(authorized)])
    def run_fixture_from_dashboard(request: Request, profile_id: str, csrf: Annotated[str, Form()]):
        check_form(request, csrf)
        try:
            fixture = files("pandapply").joinpath("assets/jobs.synthetic.json")
            with as_file(fixture) as fixture_path, closing(connect(database)) as db:
                settings = read_settings(db, database.parent / "config.json")
                run_fixture(db, profile_id, JsonDiscovery(fixture_path), dry_run=False,
                            min_score=settings.min_match_score)
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse(url="/", status_code=303)

    @app.post("/mail/{message_id}/suggest", response_class=HTMLResponse, dependencies=[Depends(authorized)])
    def suggest_reply_from_dashboard(request: Request, message_id: str, csrf: Annotated[str, Form()]):
        check_form(request, csrf)
        with closing(connect(database)) as db:
            message = db.execute("SELECT sender,classification,application_id,gmail_account_id FROM mailbox_messages "
                                 "WHERE id=?", (message_id,)).fetchone()
        if not message or message["classification"] != "interview" or not message["application_id"]:
            raise HTTPException(status_code=400, detail="An approved, correlated interview is required")
        account_input = ("<label>Correo principal de Gmail <input type='email' name='account' required></label>"
                         if message["gmail_account_id"].startswith("hermes:") else "")
        return ("<!doctype html><html lang='es'><meta charset='utf-8'><title>Propuesta de respuesta</title>"
                "<h1>Propuesta de respuesta</h1><p>Estas opciones son solo sugerencias. Revise el correo original.</p>"
                "<ul><li>Thank you for reaching out. Please suggest available times.</li>"
                "<li>Thank you for the invitation. Could you share the next steps?</li></ul>"
                f"<p>Destinatario: {html.escape(str(message['sender']))}</p>"
                f"<form method='post' action='/mail/{html.escape(message_id, quote=True)}/draft'>"
                f"<input type='hidden' name='csrf' value='{csrf_secret}'>"
                f"{account_input}<label>Texto exacto <textarea name='text' required maxlength='10000'></textarea></label>"
                "<button>Crear propuesta para aprobar</button></form><p><a href='/'>Volver</a></p></html>")

    @app.post("/mail/{message_id}/draft", dependencies=[Depends(authorized)])
    def draft_reply_from_dashboard(request: Request, message_id: str, csrf: Annotated[str, Form()],
                                   text: Annotated[str, Form()], account: Annotated[str, Form()] = ""):
        check_form(request, csrf)
        try:
            with closing(connect(database)) as db:
                propose_reply(db, message_id, text, account=account or None)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse(url="/", status_code=303)

    @app.post("/mail/replies/{proposal_id}/send", dependencies=[Depends(authorized)])
    def send_reply_from_dashboard(request: Request, proposal_id: str, csrf: Annotated[str, Form()],
                                  hermes_python: Annotated[str, Form()] = "", workspace_script: Annotated[str, Form()] = ""):
        check_form(request, csrf)
        try:
            with closing(connect(database)) as db:
                row = db.execute("SELECT m.gmail_account_id FROM reply_proposals p "
                                 "JOIN mailbox_messages m ON m.id=p.mailbox_message_id WHERE p.id=?",
                                 (proposal_id,)).fetchone()
                if not row:
                    raise MailBlocked("Reply proposal not found")
                if row["gmail_account_id"] == "fixture":
                    send_fake_reply(db, proposal_id, FakeGmail())
                else:
                    if not hermes_python or not workspace_script:
                        raise MailBlocked("Hermes interpreter and Workspace script are required")
                    send_approved(database, proposal_id, interpreter=Path(hermes_python),
                                  script=Path(workspace_script), confirm=True)
        except MailOutcomeUnknown as exc:
            raise HTTPException(status_code=409, detail="Resultado incierto: no reenviar; concilie el mensaje") from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse(url="/", status_code=303)

    @app.post("/config", dependencies=[Depends(authorized)])
    def update_config_from_dashboard(request: Request, locale: Annotated[str, Form()],
                                     min_match_score: Annotated[float, Form()], csrf: Annotated[str, Form()]):
        check_form(request, csrf)
        try:
            with closing(connect(database)) as db:
                patch_settings(db, database.parent / "config.json", {"locale": locale,
                               "min_match_score": min_match_score}, actor="web")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse(url="/", status_code=303)

    @app.post("/config/gmail", dependencies=[Depends(authorized)])
    def update_gmail_settings(request: Request, csrf: Annotated[str, Form()], revision: Annotated[int, Form()],
                              gmail_enabled: Annotated[str, Form()] = "", gmail_reply_enabled: Annotated[str, Form()] = "",
                              dry_run: Annotated[str, Form()] = ""):
        check_form(request, csrf)
        if any(value not in ("", "on") for value in (gmail_enabled, gmail_reply_enabled, dry_run)):
            raise HTTPException(status_code=400, detail="Invalid Gmail configuration")
        try:
            with closing(connect(database)) as db:
                patch_settings(db, database.parent / "config.json",
                               {"gmail_enabled": gmail_enabled == "on", "gmail_reply_enabled": gmail_reply_enabled == "on",
                                "dry_run": dry_run == "on"}, actor="web", expected_revision=revision)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return RedirectResponse(url="/", status_code=303)

    @app.post("/mail/manual-review/dismiss", dependencies=[Depends(authorized)])
    def dismiss_manual_mail(request: Request, csrf: Annotated[str, Form()], account_id: Annotated[str, Form()],
                            message_id: Annotated[str, Form()]):
        check_form(request, csrf)
        with closing(connect(database)) as db, db:
            db.execute("UPDATE mail_review_queue SET state='DISMISSED' WHERE gmail_account_id=? AND gmail_message_id=?",
                       (account_id, message_id))
        return RedirectResponse(url="/", status_code=303)

    @app.post("/config/mail-monitor", dependencies=[Depends(authorized)])
    def update_mail_monitor(request: Request, csrf: Annotated[str, Form()], revision: Annotated[int, Form()],
                            gmail_poll_limit: Annotated[int, Form()], gmail_account: Annotated[str, Form()] = "",
                            gmail_query: Annotated[str, Form()] = "", hermes_python: Annotated[str, Form()] = "",
                            hermes_workspace_script: Annotated[str, Form()] = "",
                            hermes_home: Annotated[str | None, Form()] = None):
        check_form(request, csrf)
        try:
            with closing(connect(database)) as db:
                patch = {
                    "gmail_account": gmail_account, "gmail_query": gmail_query, "hermes_python": hermes_python,
                    "hermes_workspace_script": hermes_workspace_script, "gmail_poll_limit": gmail_poll_limit,
                }
                if hermes_home is not None:
                    patch["hermes_home"] = hermes_home
                patch_settings(db, database.parent / "config.json", patch, actor="web", expected_revision=revision)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return RedirectResponse(url="/", status_code=303)

    return app
