"""Resumable terminal onboarding; credentials stay with the existing Hermes installation."""

import os
import secrets
import sqlite3
from contextlib import closing
from pathlib import Path

from pandapply.adapters.hermes.installation import discover
from pandapply.browser_checks import cdp_endpoint, probe_cdp, probe_managed
from pandapply.configuration import patch_settings, read_settings
from pandapply.hermes_workspace import HermesWorkspaceReader, WorkspaceUnavailable
from pandapply.profiles import add_profile, edit_profile, import_cv, list_profiles
from pandapply.setup_checks import check_database
from pandapply.storage import connect, migrate, now
from pandapply.timezones import normalize_timezone
from pandapply.work_modes import work_mode_label, work_mode_preference


def ask(label: str, default: str = "") -> str:
    value = input(f"{label}" + (f" [{default}]" if default else "") + ": ").strip()
    return value or default


def yes(label: str, *, default: bool = True) -> bool:
    while True:
        answer = ask(label + (" (S/n)" if default else " (s/N)"), "s" if default else "n").casefold()
        if answer in ("s", "si", "sí", "y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("Responde s o n.")


def number(label: str, default: int, minimum: int, maximum: int) -> int:
    while True:
        value = ask(label, str(default))
        if value.isdigit() and minimum <= int(value) <= maximum:
            return int(value)
        print(f"Introduce un número entre {minimum} y {maximum}.")


def configure_search(db, config_path: Path, primary_profile_id: str) -> None:
    settings = read_settings(db, config_path)
    print("Cada perfil define el cargo que quieres buscar y sus filtros de salario, modalidad y ubicación.")
    print("Usaremos su nombre como término de búsqueda, sin volver a pedirte títulos ni cargos.")
    additional = ask("Otros cargos para crear como perfiles, separados por comas (opcional; Enter para ninguno)")
    profiles = list_profiles(db)
    names = {p["name"].casefold() for p in profiles}
    for name in [name.strip() for name in additional.split(",") if name.strip()]:
        if name.casefold() not in names:
            add_profile(db, name, "UTC", {})
            names.add(name.casefold())
    profiles = [p for p in list_profiles(db) if p["active"]]
    default_ids = settings.search_profile_ids or [primary_profile_id]
    for index, profile in enumerate(profiles, 1):
        print(f"{index}. {profile['name']}")
    default = ",".join(str(i) for i, p in enumerate(profiles, 1) if p["id"] in default_ids) or "1"
    while True:
        chosen = ask("¿Qué perfiles de búsqueda quieres usar? Números separados por comas", default)
        parts = [part.strip() for part in chosen.split(",")]
        if parts and all(p.isdigit() and 1 <= int(p) <= len(profiles) for p in parts):
            selected = [profiles[i - 1] for i in dict.fromkeys(int(p) for p in parts)]
            break
        print("Selecciona números de la lista.")
    for profile in selected:
        print("Perfil de búsqueda: " + profile["name"])
        preferences = dict(profile["preferences"])
        if not preferences.get("role_queries"):
            preferences["role_queries"] = [profile["name"]]
        print("Términos de búsqueda: " + ", ".join(preferences["role_queries"]))
        for field, label, fallback in (("locations", "Países o ubicaciones", ""),
                                       ("languages", "Idiomas de las vacantes", "es,en"),
                                       ("must_have_skills", "Habilidades requeridas (filtro, no experiencia confirmada)", "")):
            current = preferences.get(field, [])
            value = ask(label + ", separados por comas", ",".join(current) if current else fallback)
            preferences[field] = list(dict.fromkeys(p.strip() for p in value.split(",") if p.strip()))
        while True:
            mode = ask("Modalidades: remote, hybrid, onsite (puedes elegir varias separadas por comas) o any",
                       work_mode_label(preferences.get("work_mode", "remote")))
            try:
                preferences["work_mode"] = work_mode_preference(mode)
                break
            except ValueError as exc:
                print(str(exc))
        preferences["salary_min_usd_month"] = number("Salario mínimo USD/mes (0 = sin filtro)",
                                                     int(preferences.get("salary_min_usd_month") or 0), 0, 1_000_000) or None
        edit_profile(db, profile["id"], preferences=preferences, expected_version=profile["version"])
    quota = number("¿Cuántas vacantes al día quieres llenar como máximo? (0 = ninguna)",
                   settings.max_confirmed_submissions_per_day, 0, 1000)
    results = number("Máximo de vacantes a evaluar por búsqueda", settings.max_results_per_run, 1, 100)
    interval = number("¿Cada cuántos minutos quieres buscar?", settings.search_interval_minutes, 5, 10080)
    patch_settings(db, config_path, {"search_profile_ids": [p["id"] for p in selected],
                   "max_confirmed_submissions_per_day": quota, "max_results_per_run": results,
                   "search_interval_minutes": interval}, actor="cli")
    print("Perfiles seleccionados para buscar: " + ", ".join(p["name"] for p in selected))
    print("Preferencias guardadas. El cupo no autoriza postulaciones; la búsqueda real y su programación siguen pendientes.")


def configure_browser(db, config_path: Path) -> None:
    print("\nNavegador para las postulaciones")
    print("1. Navegador administrado por Hermes (prueba con datos ficticios)")
    print("2. Mi navegador existente, mediante una conexión CDP local")
    print("3. Configurar después")
    settings = read_settings(db, config_path)
    default = {"hermes_managed": "1", "cdp": "2", "not_configured": "3"}[settings.browser_mode]
    while True:
        choice = ask("¿Qué navegador quieres utilizar?", default)
        if choice in ("1", "2", "3"):
            break
        print("Elige 1, 2 o 3.")
    if choice == "3":
        print("Comprobación del navegador pendiente; la selección anterior se conserva.")
        return
    patch = {"browser_mode": "hermes_managed" if choice == "1" else "cdp", "browser_cdp_endpoint": ""}
    if choice == "2":
        print("Habilita la conexión de depuración local de Chrome/Edge. La comprobación consulta solo su estado.")
        while True:
            try:
                patch["browser_cdp_endpoint"] = cdp_endpoint(ask("Dirección CDP local", settings.browser_cdp_endpoint or "http://127.0.0.1:9222"))
                break
            except ValueError as exc:
                print(str(exc))
    settings = patch_settings(db, config_path, patch, actor="cli")
    # Changing configuration invalidates any earlier capability check.
    with db:
        db.execute("INSERT INTO connector_health (connector_id,state,checked_at,detail_redacted) "
                   "VALUES ('browser','not_checked',?,'Nueva selección pendiente de prueba') "
                   "ON CONFLICT(connector_id) DO UPDATE SET state=excluded.state,checked_at=excluded.checked_at,"
                   "detail_redacted=excluded.detail_redacted", (now(),))
    if not yes("¿Comprobar ahora la conexión del navegador?", default=False):
        return
    try:
        if settings.browser_mode == "cdp":
            result = probe_cdp(settings.browser_cdp_endpoint)
            print("Conexión CDP disponible. La automatización con este navegador todavía está pendiente.")
        else:
            if not settings.hermes_python or not settings.hermes_root:
                raise ValueError("No se pudo preparar la prueba administrada a partir de tu instalación de Hermes")
            print("Probando Hermes en un formulario local con datos ficticios; puede tardar hasta dos minutos...")
            result = probe_managed(Path(settings.hermes_python), Path(settings.hermes_root))
            print("Prueba local del navegador completada; no verifica portales de empleo reales.")
        state, detail = result["status"], result["scope"]
    except Exception:  # noqa: BLE001 - browser errors can contain private paths or page content
        state, detail = "unavailable", "No se pudo completar la comprobación local del navegador"
        print(detail + ". Puedes continuar y repetir la comprobación después.")
    with db:
        db.execute("UPDATE connector_health SET state=?,checked_at=?,detail_redacted=? WHERE connector_id='browser'",
                   (state, now(), detail))


def dashboard(database: Path, *, host: str = "127.0.0.1", port: int = 8765) -> None:
    import uvicorn

    from pandapply.web import create_app

    token = secrets.token_urlsafe(24)
    print(f"Abre http://{host}:{port}/login", flush=True)
    print("Usuario: pandapply", flush=True)
    print(f"Contraseña: {token}", flush=True)
    print("Para detener el panel, pulsa Ctrl+C.", flush=True)
    uvicorn.run(create_app(database, token), host=host, port=port, log_level="warning")


def run(database: Path, *, home: Path | None = None, root: Path | None = None,
        interpreter: Path | None = None) -> int:
    print("\nBienvenido a PandApply. Vamos a configurar tu instalación paso a paso.")
    try:
        runtime = ask("Motor: 1 = Hermes; 2 = OpenClaw (próximamente)", "1")
        while runtime not in ("1", "2"):
            runtime = ask("Elige 1 o 2", "1")
        if runtime == "2":
            print("OpenClaw está en preparación. Vuelve a ejecutar el asistente y elige Hermes para usar esta versión.")
            return 1
        migrate(database)
        with closing(connect(database)) as db:
            print("SQLite: comprobando integridad, relaciones y escritura...")
            check_database(db)
            print("SQLite validado correctamente.")
            config_path = database.parent / "config.json"
            settings = read_settings(db, config_path)
            selected_home = home or (Path(settings.hermes_home) if settings.hermes_home else None)
            detected = discover(home=selected_home, root=root, interpreter=interpreter)
            print("\n1. Hermes")
            print("Ejecutable: " + (detected["executable"] or "no detectado; puedes continuar con las funciones locales"))
            if detected["home"]:
                print("Perfil detectado: " + detected["home"])
            for issue in detected["issues"]:
                print(issue)
            if not detected["home"] or not yes("¿Usar este perfil de Hermes?"):
                while True:
                    value = ask("Directorio del perfil Hermes (Enter para configurar después)")
                    if not value:
                        detected = {**detected, "home": None, "gmail": "not_detected", "whatsapp": "not_detected"}
                        break
                    if Path(value.strip('"')).expanduser().is_dir():
                        detected = discover(home=Path(value.strip('"')), root=root, interpreter=interpreter)
                        break
                    print("Ese directorio no existe. Puedes dejarlo vacío para continuar.")
            patch = {}
            if detected["home"]:
                for key, field in (("hermes_home", "home"), ("hermes_python", "python"),
                                   ("hermes_workspace_script", "workspace_script"), ("hermes_executable", "executable"),
                                   ("hermes_root", "root")):
                    current = getattr(settings, key)
                    value = detected.get(field)
                    if (key == "hermes_home" or not current) and value:
                        patch[key] = value
                # A deliberate profile change must not retain another account's defaults.
                if settings.hermes_home and Path(settings.hermes_home).resolve() != Path(detected["home"]).resolve():
                    patch.update(gmail_account="", gmail_enabled=False, gmail_reply_enabled=False,
                                 hermes_workspace_script=detected["workspace_script"] or "")
                if patch:
                    settings = patch_settings(db, config_path, patch, actor="cli")
            print("Gmail: " + ("autorización existente detectada" if detected["gmail"] != "not_detected" else "no detectado"))
            print("WhatsApp: " + ("sesión existente detectada; canal PandApply pendiente" if detected["whatsapp"] != "not_detected" else "no detectado (opcional)"))
            print("\nConexión Gmail")
            if not detected["home"]:
                print("Gmail queda pendiente porque no hay una instalación de Hermes seleccionada.")
            if detected["home"] and yes("¿Comprobar ahora tu cuenta de Gmail en Hermes?", default=detected["gmail"] != "not_detected"):
                print("Preparando la conexión con la instalación existente de Hermes...")
                refreshed = discover(home=Path(settings.hermes_home), root=root, interpreter=interpreter)
                detected_paths = {"hermes_python": refreshed["python"],
                                  "hermes_workspace_script": refreshed["workspace_script"]}
                repair = {key: value for key, value in detected_paths.items() if value and (
                          not getattr(settings, key) or not Path(getattr(settings, key)).is_file())}
                if repair:
                    settings = patch_settings(db, config_path, repair, actor="cli")
                if settings.hermes_python and settings.hermes_workspace_script:
                    try:
                        reader = HermesWorkspaceReader(Path(settings.hermes_python), Path(settings.hermes_workspace_script),
                                                       home=Path(settings.hermes_home))
                        account = reader.primary_account()
                        if settings.gmail_account and settings.gmail_account.casefold() != account.casefold():
                            print("La cuenta de Hermes difiere de la guardada. Se conserva la configuración anterior.")
                        else:
                            settings = patch_settings(db, config_path, {"gmail_account": account}, actor="cli")
                            print("Cuenta comprobada: " + account)
                    except (OSError, ValueError, WorkspaceUnavailable):
                        print("No se pudo comprobar Gmail. Puedes continuar y revisar su autorización en Hermes después.")
                else:
                    print("No se pudo preparar la conexión con Gmail automáticamente. "
                          "Gmail queda pendiente; puedes continuar y revisar la instalación de Hermes después.")
            settings = read_settings(db, config_path)
            if settings.gmail_account:
                query = ask("Filtro de correo para el seguimiento Gmail", settings.gmail_query or "newer_than:7d")
                limit = number("Máximo de correos por consulta", settings.gmail_poll_limit, 1, 20)
                interval = number("Intervalo de seguimiento Gmail en minutos", settings.gmail_poll_interval_minutes, 5, 10080)
                print("Permisos Gmail: 1 = deshabilitado; 2 = solo consulta; 3 = consulta y respuestas con aprobación.")
                default = "3" if settings.gmail_reply_enabled else "2" if settings.gmail_enabled else "1"
                while True:
                    access = ask("¿Qué uso de Gmail autorizas?", default)
                    if access in ("1", "2", "3"):
                        break
                    print("Elige 1, 2 o 3.")
                patch_settings(db, config_path, {"gmail_query": query, "gmail_poll_limit": limit,
                               "gmail_poll_interval_minutes": interval, "gmail_enabled": access != "1",
                               "gmail_reply_enabled": access == "3"}, actor="cli")
                print("Cuenta, filtro, intervalo y permisos guardados. El modo de simulación se conserva; "
                      "la tarea programada todavía debe instalarse y activarse explícitamente.")
            configure_browser(db, config_path)
            print("\n2. Tus preferencias de búsqueda")
            print("Cada perfil representa un cargo a buscar y sus preferencias, por ejemplo 'Backend Developer'.")
            print("Su nombre se usa como término de búsqueda. Después elegirás los perfiles que quieras utilizar.")
            profiles = [p for p in list_profiles(db) if p["active"]]
            profile_id = None
            if profiles:
                for index, profile in enumerate(profiles, 1):
                    print(f"{index}. {profile['name']}")
                while profile_id is None:
                    choice = ask("Elige un perfil de búsqueda existente; 0 para crear otro", "1")
                    if choice == "0":
                        break
                    if choice.isdigit() and 1 <= int(choice) <= len(profiles):
                        profile_id = profiles[int(choice) - 1]["id"]
                    else:
                        print("Elige un número de la lista.")
            if profile_id is None:
                while True:
                    name = ask("¿Qué cargo quieres buscar? Será el nombre del perfil (ej. Backend Developer)")
                    if name and len(name) <= 200:
                        break
                    print("Escribe un cargo de entre 1 y 200 caracteres.")
                print("Puedes indicar una ciudad (America/Bogota) o un desfase fijo (UTC-5). "
                      "La ciudad ajusta los cambios de horario estacionales cuando corresponden.")
                while True:
                    timezone = ask("Zona horaria (ej. America/Bogota o UTC-5)", os.environ.get("TZ", "UTC"))
                    try:
                        timezone = normalize_timezone(timezone)
                        profile_id = add_profile(db, name, timezone, {"role_queries": [name]})
                        break
                    except ValueError as exc:
                        print(str(exc))
            while True:
                cv = ask("Ruta de tu CV PDF o DOCX (Enter para agregarlo después)").strip('"')
                if not cv:
                    break
                try:
                    source = Path(cv).expanduser().resolve(strict=True)
                    existing = db.execute("SELECT id FROM documents WHERE profile_id=? AND file_path=? AND kind='cv_original'",
                                          (profile_id, str(source))).fetchone()
                    if not existing:
                        import_cv(db, profile_id, source)
                    print("CV registrado. El archivo original se conserva; sus datos requieren revisión.")
                    break
                except (ValueError, OSError) as exc:
                    print(f"No se pudo registrar el CV: {exc}")
            print("\n3. Búsqueda y límites")
            if yes("¿Configurar ahora los perfiles, filtros y límites de búsqueda?"):
                configure_search(db, config_path, profile_id)
            print("\n4. Piloto de conexión por WhatsApp")
            print("Este piloto prueba el saludo. La recepción automática de respuestas y la primera búsqueda real aún están pendientes.")
            if yes("¿Enviar el saludo de prueba a tu propio WhatsApp?", default=False):
                from pandapply.adapters.hermes.whatsapp import (
                    INVITATION,
                    HermesWhatsApp,
                    WhatsAppOutcomeUnknown,
                    invite,
                    owner_jid,
                )

                settings = read_settings(db, config_path)
                if not settings.hermes_home or not settings.hermes_executable:
                    print("Piloto pendiente: falta el ejecutable o perfil de Hermes. Puedes continuar con CLI/web.")
                else:
                    while True:
                        value = ask("Tu número WhatsApp con prefijo internacional (Enter para omitir)", settings.whatsapp_owner_jid)
                        if not value:
                            break
                        try:
                            target = owner_jid(value)
                            print("Mensaje: " + INVITATION)
                            if yes("¿Confirmas que es tu número y quieres enviar este saludo?", default=False):
                                patch_settings(db, config_path, {"whatsapp_owner_jid": target}, actor="cli")
                                try:
                                    outcome = invite(db, HermesWhatsApp(Path(settings.hermes_executable), Path(settings.hermes_home)),
                                                     target, confirm=True)
                                    print("Estado del piloto: " + outcome["status"] + ". No se repetirá el saludo automáticamente.")
                                except (ValueError, OSError, WhatsAppOutcomeUnknown) as exc:
                                    print(str(exc))
                            break
                        except ValueError as exc:
                            print(str(exc))
            check_database(db)
        print("\nConfiguración local guardada. Las integraciones externas siguen siendo experimentales.")
        print("Pendiente: búsqueda real y programación, recepción de respuestas WhatsApp y activación del seguimiento Gmail.")
        print("\n5. Panel local (último paso)")
        if yes("¿Abrir el panel local ahora?"):
            dashboard(database)
        print("Puedes repetir este asistente sin perder tus perfiles ni decisiones.")
        return 0
    except (EOFError, KeyboardInterrupt):
        print("\nAsistente interrumpido. Lo ya guardado se conserva para la próxima ejecución.")
        return 130
    except sqlite3.Error:
        print("No se pudo validar o guardar SQLite. Conserva la base y revisa el acceso al directorio de datos.")
        return 1
