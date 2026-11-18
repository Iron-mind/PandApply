"""Resumable terminal onboarding; credentials stay with the existing Hermes installation."""

import os
import secrets
from contextlib import closing
from pathlib import Path

from pandapply.adapters.hermes.installation import discover
from pandapply.configuration import patch_settings, read_settings
from pandapply.hermes_workspace import HermesWorkspaceReader, WorkspaceUnavailable
from pandapply.profiles import add_profile, import_cv, list_profiles
from pandapply.storage import connect, migrate


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
                                   ("hermes_workspace_script", "workspace_script")):
                    current = getattr(settings, key)
                    value = detected[field]
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
            if detected["home"] and yes("¿Comprobar ahora tu cuenta de Gmail en Hermes?", default=detected["gmail"] != "not_detected"):
                for key, label in (("hermes_python", "Ejecutable Python del entorno de Hermes"),
                                   ("hermes_workspace_script", "Archivo google_api.py de Google Workspace")):
                    while not getattr(settings, key):
                        value = ask(label + " (Enter para omitir)").strip('"')
                        if not value:
                            break
                        if Path(value).expanduser().is_file():
                            settings = patch_settings(db, config_path, {key: str(Path(value).expanduser().absolute())}, actor="cli")
                        else:
                            print("No se encontró el archivo.")
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
                    print("Gmail queda pendiente hasta configurar las rutas de Hermes.")
            print("\n2. Tu perfil profesional")
            profiles = [p for p in list_profiles(db) if p["active"]]
            profile_id = None
            if profiles:
                for index, profile in enumerate(profiles, 1):
                    print(f"{index}. {profile['name']}")
                while profile_id is None:
                    choice = ask("Elige tu perfil; 0 para crear otro", "1")
                    if choice == "0":
                        break
                    if choice.isdigit() and 1 <= int(choice) <= len(profiles):
                        profile_id = profiles[int(choice) - 1]["id"]
                    else:
                        print("Elige un número de la lista.")
            if profile_id is None:
                while True:
                    name = ask("Nombre del perfil (por ejemplo, Backend)", "Principal")
                    timezone = ask("Zona horaria IANA", os.environ.get("TZ", "UTC"))
                    try:
                        profile_id = add_profile(db, name, timezone, {})
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
        print("\nConfiguración local guardada. Las integraciones externas siguen siendo experimentales.")
        if yes("¿Abrir el panel local ahora?"):
            dashboard(database)
        print("Puedes repetir este asistente sin perder tus perfiles ni decisiones.")
        return 0
    except (EOFError, KeyboardInterrupt):
        print("\nAsistente interrumpido. Lo ya guardado se conserva para la próxima ejecución.")
        return 130
