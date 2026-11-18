import re

from fastapi.testclient import TestClient

from pandapply.domain import Job
from pandapply.mail import ingest_fixture
from pandapply.memory import propose_skill
from pandapply.profiles import add_profile
from pandapply.storage import connect, migrate, save_job
from pandapply.web import create_app


def test_redesigned_panel_uses_live_profiles_navigation_and_local_assets(tmp_path):
    path = tmp_path / "data.db"
    migrate(path)
    with connect(path) as db:
        add_profile(db, "Backend", "UTC", {"must_have_skills": ["Python"]})
        chosen = add_profile(db, "QA <seguro>", "UTC", {"work_mode": ["remote", "hybrid"]})
    client = TestClient(create_app(path, "secret"), base_url="http://localhost")
    auth = ("pandapply", "secret")
    page = client.get(f"/?view=perfiles&profile={chosen}", auth=auth)
    assert page.status_code == 200
    assert "class='shell'" in page.text and "class='sidebar'" in page.text
    assert "class='view active' id='view-perfiles'" in page.text
    assert "QA &lt;seguro&gt;" in page.text and "<seguro>" not in page.text
    assert "Remoto, Híbrido" in page.text
    assert "VISTA PREVIA" not in page.text and "onclick=" not in page.text
    assert "class='nav-count'>2</span>" in page.text
    search = client.get("/", params={"view": "perfiles", "q": "<script>alert(1)</script>"}, auth=auth)
    assert "<script>" not in search.text and "No se encontraron perfiles" in search.text
    assert client.get("/?view=unknown", auth=auth).status_code == 200
    stylesheet = client.get("/assets/panel.css")
    assert stylesheet.status_code == 200 and "text/css" in stylesheet.headers["content-type"]
    assert "--purple:#6958f5" in stylesheet.text
    assert "fonts.googleapis.com" not in page.text + stylesheet.text
    font = client.get("/assets/fonts/dm-sans.woff2")
    assert font.status_code == 200 and font.content.startswith(b"wOF2")
    assert client.get("/assets/fonts/not-a-font").status_code == 404
    assert "style-src 'self'" in page.headers["content-security-policy"]


def test_login_form_session_logout_and_api_boundaries(tmp_path):
    path = tmp_path / "data.db"
    migrate(path)
    client = TestClient(create_app(path, "secret"), base_url="http://localhost")
    page = client.get("/")
    assert page.status_code == 200 and page.url.path == "/login"
    assert "Iniciar sesión" in page.text and "type='password'" in page.text
    assert "WWW-Authenticate" not in page.headers and "secret" not in page.text
    assert page.headers["referrer-policy"] == "same-origin"
    csrf = re.search(r"name='csrf' value='([^']+)'", page.text).group(1)
    data = {"username": "pandapply", "password": "secret", "csrf": csrf}
    origin = {"Origin": "http://localhost"}
    assert client.post("/login", data=data).status_code == 403
    assert client.post("/login", data=data, headers={"Origin": "https://evil.test"}).status_code == 403
    null_origin = client.post("/login", data=data, headers={"Origin": "null"})
    assert null_origin.status_code == 403 and "text/html" in null_origin.headers["content-type"]
    assert "Volver a abrir el formulario" in null_origin.text
    assert "secret" not in null_origin.text and "pandapply_session" not in client.cookies
    stale = client.post("/login", data={**data, "csrf": "old-form"}, headers=origin)
    assert stale.status_code == 403 and "href='/login'" in stale.text
    assert "pandapply_session" not in client.cookies
    bad = client.post("/login", data={**data, "password": "contraseña inválida"}, headers=origin)
    assert bad.status_code == 401 and "incorrectos" in bad.text
    assert "WWW-Authenticate" not in bad.headers
    response = client.post("/login", data=data, headers=origin, follow_redirects=False)
    assert response.status_code == 303
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "secret" not in cookie
    assert "Cerrar sesión" in client.get("/").text
    assert client.get("/api/v1/profiles").status_code == 200
    assert client.patch("/api/v1/config", json={"locale": "es-CO"}).status_code == 401
    assert client.post("/profiles", data={"csrf": csrf, "name": "Backend", "timezone": "UTC"},
                       headers=origin, follow_redirects=False).status_code == 303
    assert client.post("/logout", data={"csrf": csrf}, headers={"Origin": "https://evil.test"}).status_code == 403
    old_cookie = client.cookies.get("pandapply_session")
    assert client.post("/logout", data={"csrf": csrf}, headers=origin, follow_redirects=False).status_code == 303
    assert client.get("/api/v1/profiles", headers={"Cookie": f"pandapply_session={old_cookie}"}).status_code == 401


def test_browser_sessions_expire_and_do_not_survive_server_restart(tmp_path, monkeypatch):
    from types import SimpleNamespace

    clock = [100.0]
    monkeypatch.setattr("pandapply.web.time", SimpleNamespace(monotonic=lambda: clock[0]))
    path = tmp_path / "data.db"
    migrate(path)
    client = TestClient(create_app(path, "secret"), base_url="http://localhost")
    page = client.get("/login")
    csrf = re.search(r"name='csrf' value='([^']+)'", page.text).group(1)
    client.post("/login", data={"csrf": csrf, "username": "pandapply", "password": "secret"},
                headers={"Origin": "http://localhost"}, follow_redirects=False)
    cookie = {"Cookie": "pandapply_session=" + client.cookies.get("pandapply_session")}
    restarted = TestClient(create_app(path, "new-secret"), base_url="http://localhost")
    assert restarted.get("/api/v1/profiles", headers=cookie).status_code == 401
    clock[0] += 12 * 60 * 60 + 1
    assert client.get("/api/v1/profiles", headers=cookie).status_code == 401


def test_dashboard_requires_auth_and_escapes_profile_names(tmp_path):
    path = tmp_path / "data.db"
    migrate(path)
    with connect(path) as db:
        add_profile(db, "<script>alert(1)</script>", "UTC", {})
    client = TestClient(create_app(path, "secret"), base_url="http://localhost")
    unauthenticated = client.get("/", follow_redirects=False)
    assert unauthenticated.status_code == 303 and unauthenticated.headers["location"] == "/login"
    assert client.get("/api/v1/profiles", auth=("pandapply", "wrong")).status_code == 401
    result = client.get("/", auth=("pandapply", "secret"))
    assert result.status_code == 200
    assert "<script>" not in result.text
    assert "&lt;script&gt;" in result.text
    assert client.get("/api/v1/profiles", auth=("pandapply", "secret")).json()[0]["name"].startswith("<script>")
    assert client.get("/", headers={"host": "evil.example"}, auth=("pandapply", "secret")).status_code == 400


def test_bearer_auth_and_local_api_reads(tmp_path):
    path = tmp_path / "data.db"
    migrate(path)
    with connect(path) as db:
        add_profile(db, "Backend", "UTC", {})
    client = TestClient(create_app(path, "secret"), base_url="http://127.0.0.1")
    headers = {"Authorization": "Bearer secret"}
    assert client.get("/api/v1/profiles", headers=headers).json()[0]["name"] == "Backend"
    assert client.get("/api/v1/config", headers=headers).json()["dry_run"] is True
    assert client.get("/api/v1/decisions", headers=headers).json() == []
    assert client.get("/api/v1/events", headers=headers).json() == []
    assert client.get("/api/v1/connectors", headers=headers).json() == []
    assert client.get("/api/v1/applications/missing", headers=headers).status_code == 404
    assert client.get("/api/v1/profiles", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_api_decision_requires_bearer_and_is_idempotent(tmp_path):
    path = tmp_path / "data.db"
    migrate(path)
    with connect(path) as db:
        profile = add_profile(db, "Backend", "UTC", {})
        proposal = propose_skill(db, profile, "Python")
    client = TestClient(create_app(path, "secret"), base_url="http://localhost")
    route = f"/api/v1/decisions/{proposal}/respond"
    headers = {"Authorization": "Bearer secret", "Idempotency-Key": "request-1"}
    assert client.post(route, json={"action": "approve"}, auth=("pandapply", "secret"),
                       headers={"Idempotency-Key": "request-1"}).status_code == 401
    assert client.post(route, json={"action": "approve"}, headers={**headers, "Origin": "https://evil.test"}).status_code == 403
    decision = client.post(route, json={"action": "approve"}, headers=headers)
    assert decision.status_code == 200 and decision.json()["status"] == "APPROVED"
    assert client.post(route, json={"action": "approve"}, headers=headers).json() == decision.json()
    assert client.post(route, json={"action": "reject"}, headers=headers).status_code == 409
    assert client.post(route, json={"action": "approve"}, headers={**headers, "Idempotency-Key": "different"}).status_code == 409
    with connect(path) as db:
        assert db.execute("SELECT count(*) FROM knowledge_claims").fetchone()[0] == 1


def test_config_mutation_requires_bearer_and_is_audited(tmp_path):
    path = tmp_path / "data.db"
    migrate(path)
    client = TestClient(create_app(path, "secret"), base_url="http://localhost")
    assert client.patch("/api/v1/config", json={"min_match_score": 0.6},
                        auth=("pandapply", "secret")).status_code == 401
    headers = {"Authorization": "Bearer secret"}
    assert client.patch("/api/v1/config", json={"min_match_score": 0.6},
                        headers={**headers, "Origin": "https://evil.test"}).status_code == 403
    assert client.patch("/api/v1/config", json={"min_match_score": 2.0}, headers=headers).status_code == 400
    response = client.patch("/api/v1/config", json={"min_match_score": 0.6}, headers=headers)
    assert response.status_code == 200 and response.json()["min_match_score"] == 0.6
    assert client.get("/api/v1/config", headers=headers).json()["min_match_score"] == 0.6
    with connect(path) as db:
        assert db.execute("SELECT actor FROM config_revisions").fetchone()[0] == "web"


def test_create_profile_api_uses_supplied_id_and_requires_bearer(tmp_path):
    path = tmp_path / "data.db"
    migrate(path)
    client = TestClient(create_app(path, "secret"), base_url="http://localhost")
    profile = {"id": "backend", "name": "Backend", "preferences": {"roles": ["Python"]}}
    assert client.post("/api/v1/profiles", json=profile, auth=("pandapply", "secret")).status_code == 401
    headers = {"Authorization": "Bearer secret"}
    created = client.post("/api/v1/profiles", json=profile, headers=headers)
    assert created.status_code == 201 and created.json()["id"] == "backend"
    assert client.post("/api/v1/profiles", json=profile, headers=headers).status_code == 409


def test_dashboard_decision_requires_csrf_and_same_origin(tmp_path):
    path = tmp_path / "data.db"
    migrate(path)
    with connect(path) as db:
        profile = add_profile(db, "Backend", "UTC", {})
        proposal = propose_skill(db, profile, "Python<script>")
    client = TestClient(create_app(path, "secret"), base_url="http://localhost")
    auth = ("pandapply", "secret")
    page = client.get("/", auth=auth)
    assert "Python&lt;script&gt;" in page.text
    csrf = re.search(r"name='csrf' value='([^']+)'", page.text).group(1)
    key = re.search(r"name='key' value='([^']+)'", page.text).group(1)
    route = f"/decisions/{proposal}/respond"
    form = {"csrf": csrf, "key": key, "action": "approve"}
    assert client.post(route, data=form, auth=auth, headers={"Origin": "https://evil.test"}).status_code == 403
    assert client.post(route, data={**form, "csrf": "wrong"}, auth=auth,
                       headers={"Origin": "http://localhost"}).status_code == 403
    result = client.post(route, data=form, auth=auth, headers={"Origin": "http://localhost"}, follow_redirects=False)
    assert result.status_code == 303
    assert client.post(route, data=form, auth=auth, headers={"Origin": "http://localhost"},
                       follow_redirects=False).status_code == 303
    with connect(path) as db:
        assert db.execute("SELECT count(*) FROM knowledge_claims").fetchone()[0] == 1


def test_dashboard_can_create_profile_and_change_config_with_csrf(tmp_path):
    path = tmp_path / "data.db"
    migrate(path)
    client = TestClient(create_app(path, "secret"), base_url="http://localhost")
    auth = ("pandapply", "secret")
    page = client.get("/", auth=auth)
    csrf = re.search(r"name='csrf' value='([^']+)'", page.text).group(1)
    headers = {"Origin": "http://localhost"}
    profile = {"name": "Backend", "timezone": "UTC", "csrf": csrf}
    assert client.post("/profiles", data=profile, auth=auth, headers=headers, follow_redirects=False).status_code == 303
    with connect(path) as db:
        profile_id = db.execute("SELECT id FROM professional_profiles").fetchone()[0]
    skill = {"skill": "Python", "csrf": csrf}
    assert client.post(f"/profiles/{profile_id}/skills", data=skill, auth=auth,
                       headers=headers, follow_redirects=False).status_code == 303
    assert "Guardar la habilidad: Python" in client.get("/", auth=auth).text
    preferences = {"csrf": csrf, "version": "1", "skills": "Python, SQL", "work_mode": "remote, hybrid", "salary": "2000"}
    route = f"/profiles/{profile_id}/preferences"
    assert client.post(route, data=preferences, auth=auth, headers=headers, follow_redirects=False).status_code == 303
    assert client.get("/api/v1/profiles", auth=auth).json()[0]["preferences"]["work_mode"] == ["remote", "hybrid"]
    assert "value='remote, hybrid'" in client.get("/", auth=auth).text
    assert client.post(route, data=preferences, auth=auth, headers=headers, follow_redirects=False).status_code == 400
    route = f"/profiles/{profile_id}/fixture-discovery"
    assert client.post(route, data={"csrf": csrf}, auth=auth, headers=headers, follow_redirects=False).status_code == 303
    jobs = client.get(f"/api/v1/jobs?profile_id={profile_id}", auth=auth).json()
    assert len(jobs) == 4
    assert client.get("/api/v1/jobs?profile_id=missing", auth=auth).json() == []
    config = {"locale": "es-CO", "min_match_score": "0.9", "csrf": csrf}
    assert client.post("/config", data=config, auth=auth, headers=headers, follow_redirects=False).status_code == 303
    with connect(path) as db:
        assert db.execute("SELECT name FROM professional_profiles").fetchone()[0] == "Backend"
        assert db.execute("SELECT actor FROM config_revisions").fetchone()[0] == "web"
        assert db.execute("SELECT count(*) FROM knowledge_claims").fetchone()[0] == 0
        assert "Python" in db.execute("SELECT preferences_json FROM professional_profiles").fetchone()[0]


def test_dashboard_suggestions_require_request_and_approval_before_fake_send(tmp_path):
    path = tmp_path / "data.db"
    migrate(path)
    with connect(path) as db:
        profile = add_profile(db, "Backend", "UTC", {})
        job, _ = save_job(db, Job("Engineer", "Demo", "https://jobs.example.test/job", "fixture", "DEMO-001"))
        db.execute("INSERT INTO applications (id,profile_id,job_posting_id,phase,status,created_at,updated_at) "
                   "VALUES ('app',?,?,'TRACKING','SUBMITTED','now','now')", (profile, job))
        db.commit()
        message = {"id": "m1", "thread_id": "thread1", "from": "hr@example.test", "subject": "Interview",
                   "body": "Interview next week", "application_ref": "DEMO-001"}
        local_id = ingest_fixture(db, [message])[0]["local_id"]
    client = TestClient(create_app(path, "secret"), base_url="http://localhost")
    auth, headers = ("pandapply", "secret"), {"Origin": "http://localhost"}
    page = client.get("/", auth=auth)
    csrf = re.search(r"name='csrf' value='([^']+)'", page.text).group(1)
    assert "Thank you for reaching out" not in page.text
    suggested = client.post(f"/mail/{local_id}/suggest", data={"csrf": csrf}, auth=auth, headers=headers)
    assert suggested.status_code == 200 and "Thank you for reaching out" in suggested.text
    response = client.post(f"/mail/{local_id}/draft", data={"csrf": csrf, "text": "Thank you. <script>alert(1)</script>"},
                           auth=auth, headers=headers, follow_redirects=False)
    assert response.status_code == 303
    with connect(path) as db:
        decision = db.execute("SELECT id FROM master_decisions WHERE decision_type='REPLY_APPROVAL'").fetchone()[0]
        proposal = db.execute("SELECT id FROM reply_proposals").fetchone()[0]
    assert client.post(f"/mail/replies/{proposal}/send", data={"csrf": csrf}, auth=auth,
                       headers=headers).status_code == 400
    page = client.get("/", auth=auth)
    key = re.search(r"name='key' value='([^']+)'", page.text).group(1)
    response = client.post(f"/decisions/{decision}/respond", data={"csrf": csrf, "key": key, "action": "approve"},
                           auth=auth, headers=headers, follow_redirects=False)
    assert response.status_code == 303
    page = client.get("/", auth=auth)
    assert "Enviar respuesta simulada" in page.text and "Thank you." in page.text
    assert "<script>alert(1)</script>" not in page.text and "&lt;script&gt;" in page.text
    response = client.post(f"/mail/replies/{proposal}/send", data={"csrf": csrf}, auth=auth,
                           headers=headers, follow_redirects=False)
    assert response.status_code == 303
    with connect(path) as db:
        assert db.execute("SELECT state FROM reply_proposals WHERE id=?", (proposal,)).fetchone()[0] == "SENT"


def test_dashboard_gmail_settings_reject_stale_revision(tmp_path):
    path = tmp_path / "data.db"
    migrate(path)
    client = TestClient(create_app(path, "secret"), base_url="http://localhost")
    auth, origin = ("pandapply", "secret"), {"Origin": "http://localhost"}
    page = client.get("/", auth=auth)
    csrf = re.search(r"name='csrf' value='([^']+)'", page.text).group(1)
    revision = re.search(r"name='revision' value='([^']+)'", page.text).group(1)
    assert client.patch("/api/v1/config", json={"locale": "es-CO"},
                        headers={"Authorization": "Bearer secret"}).status_code == 200
    data = {"csrf": csrf, "revision": revision, "gmail_enabled": "on", "gmail_reply_enabled": "on"}
    assert client.post("/config/gmail", data=data, auth=auth, headers=origin).status_code == 409
    page = client.get("/", auth=auth)
    data["revision"] = re.search(r"name='revision' value='([^']+)'", page.text).group(1)
    assert client.post("/config/gmail", data=data, auth=auth, headers=origin, follow_redirects=False).status_code == 303
    config = client.get("/api/v1/config", auth=auth).json()
    assert config["gmail_enabled"] and config["gmail_reply_enabled"] and not config["dry_run"]


def test_dashboard_mail_monitor_requires_origin_and_current_revision(tmp_path):
    path = tmp_path / "data.db"
    migrate(path)
    client = TestClient(create_app(path, "secret"), base_url="http://localhost")
    auth, origin = ("pandapply", "secret"), {"Origin": "http://localhost"}
    page = client.get("/", auth=auth)
    data = {"csrf": re.search(r"name='csrf' value='([^']+)'", page.text).group(1),
            "revision": re.search(r"name='revision' value='([^']+)'", page.text).group(1),
            "gmail_account": "owner@example.test", "gmail_query": "<script>alert(1)</script>",
            "hermes_python": "/tmp/python", "hermes_workspace_script": "/tmp/google.py", "gmail_poll_limit": "10"}
    assert client.post("/config/mail-monitor", data=data, auth=auth).status_code == 403
    assert client.post("/config/mail-monitor", data=data, auth=auth, headers=origin, follow_redirects=False).status_code == 303
    assert client.post("/config/mail-monitor", data=data, auth=auth, headers=origin).status_code == 409
    page = client.get("/", auth=auth)
    assert "<script>alert(1)</script>" not in page.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page.text


def test_manual_mail_review_dismissal_requires_origin(tmp_path):
    path = tmp_path / "data.db"
    migrate(path)
    with connect(path) as db, db:
        db.execute("INSERT INTO mail_review_queue (gmail_account_id,gmail_message_id,reason,first_seen_at,last_seen_at) "
                   "VALUES ('account','message-1','ambiguous','now','now')")
    client = TestClient(create_app(path, "secret"), base_url="http://localhost")
    auth = ("pandapply", "secret")
    page = client.get("/", auth=auth)
    assert "message-1" in page.text
    data = {"csrf": re.search(r"name='csrf' value='([^']+)'", page.text).group(1),
            "account_id": "account", "message_id": "message-1"}
    assert client.post("/mail/manual-review/dismiss", data=data, auth=auth).status_code == 403
    response = client.post("/mail/manual-review/dismiss", data=data, auth=auth,
                           headers={"Origin": "http://localhost"}, follow_redirects=False)
    assert response.status_code == 303
    assert "message-1" not in client.get("/", auth=auth).text
    with connect(path) as db:
        assert db.execute("SELECT state FROM mail_review_queue").fetchone()[0] == "DISMISSED"
