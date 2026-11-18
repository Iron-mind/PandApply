"""Server-rendered workspace based on the owner's HTML redesign."""

import html
from importlib.resources import files
from urllib.parse import urlencode

from pandapply.work_modes import parse_work_modes

VIEWS = {"inicio": ("Resumen", "layout"), "perfiles": ("Perfiles", "user"),
         "vacantes": ("Vacantes", "briefcase"), "decisiones": ("Decisiones", "check"),
         "correo": ("Correo", "mail"), "configuracion": ("Configuración", "settings")}


def icon(name: str) -> str:
    return f"<svg aria-hidden='true' fill='none' stroke='currentColor'><use href='#i-{name}'/></svg>"


def url(view: str, profile: str | None = None, q: str = "") -> str:
    parameters = {"view": view}
    if profile:
        parameters["profile"] = profile
    if q:
        parameters["q"] = q
    return "/?" + html.escape(urlencode(parameters), quote=True)


def heading(kicker: str, title: str, subtitle: str, *, create: bool = False) -> str:
    action = (f"<a class='btn btn-primary' href='{url('perfiles')}#crear-perfil'>"
              + icon("plus") + "Nuevo perfil</a>") if create else ""
    return (f"<div class='page-heading'><div><div class='eyebrow'>{kicker}</div><h1>{title}</h1>"
            f"<p>{subtitle}</p></div>{action}</div>")


def card(title: str, content: str, subtitle: str = "") -> str:
    return (f"<section class='panel'><div class='panel-head'><div><h3>{title}</h3><p>{subtitle}</p>"
            f"</div></div><div class='panel-content'>{content}</div></section>")


def metric(label: str, count: int, caption: str, symbol: str, color: str) -> str:
    return (f"<div class='metric'><div><div class='metric-label'>{label}</div><div class='metric-value'>{count}</div>"
            f"<div class='metric-foot'>{caption}</div></div><div class='metric-ico {color}'>{icon(symbol)}</div></div>")


def mode_text(value) -> str:
    labels = {"remote": "Remoto", "hybrid": "Híbrido", "onsite": "Presencial"}
    try:
        return ", ".join(labels[m] for m in parse_work_modes(value)) or "Todas las modalidades"
    except ValueError:
        return "Modalidad por revisar"


def render_action_page(title: str, content: str) -> str:
    """Style secondary server-rendered forms consistently with the workspace."""
    return ("<!doctype html><html lang='es'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>{html.escape(title)} — PandApply</title><link rel='stylesheet' href='/assets/panel.css'>"
            "</head><body class='action-page'><main class='workspace'><a class='brand' href='/'>PandApply.</a>"
            f"<section class='panel config-card'><h1>{html.escape(title)}</h1>{content}</section></main></body></html>")


def render_panel(*, view: str, selected_id: str | None, query: str, profiles: list[dict],
                 profile_forms: dict[str, str], csrf: str, settings, counts: dict[str, int],
                 jobs: str, decisions: str, inbox: str, manual_mail: str, replies: str,
                 configuration: str) -> str:
    view = view if view in VIEWS else "inicio"
    visible = [p for p in profiles if query.casefold() in p["name"].casefold()]
    selected = next((p for p in visible if p["id"] == selected_id), visible[0] if visible else None)
    nav = []
    for name, (label, symbol) in VIEWS.items():
        active = " active" if name == view else ""
        current = " aria-current='page'" if name == view else ""
        count = f"<span class='nav-count'>{len(profiles)}</span>" if name == "perfiles" else ""
        nav.append(f"<a class='nav-button{active}' href='{url(name)}'{current}>{icon(symbol)}{label}{count}</a>")
    rows = []
    for profile in visible:
        name = html.escape(profile["name"])
        skills = profile["preferences"].get("must_have_skills", [])
        skills = skills if isinstance(skills, list) else []
        active = " selected" if selected and selected["id"] == profile["id"] else ""
        rows.append(f"<a class='profile-row{active}' href='{url(view if view in ('inicio', 'perfiles') else 'perfiles', profile['id'], query)}'>"
                    f"<span class='profile-monogram'>{html.escape(profile['name'][:2].upper())}</span>"
                    f"<span class='profile-text'><span class='profile-name'>{name}</span><span class='profile-sub'>"
                    f"{len(skills)} habilidades · {html.escape(mode_text(profile['preferences'].get('work_mode')))}</span></span>"
                    f"{icon('chevron')}</a>")
    list_markup = "".join(rows) or "<div class='empty-skill'>No se encontraron perfiles.</div>"
    search = (f"<form class='search-wrap' method='get' action='/'>{icon('search')}"
              f"<input type='hidden' name='view' value='{view}'>"
              f"<input name='q' type='search' value='{html.escape(query, quote=True)}' placeholder='Buscar un perfil...' aria-label='Buscar perfiles'>"
              "<button class='search-submit' aria-label='Buscar'>→</button></form>")
    list_panel = ("<section class='panel'><div class='panel-head'><div><h3>Mis perfiles profesionales</h3>"
                  "<p>Selecciona uno para ver sus preferencias.</p></div>"
                  f"<a class='text-action' href='{url('perfiles')}'>Ver todos →</a></div>{search}"
                  f"<div class='profile-list'>{list_markup}</div></section>")
    if selected:
        prefs = selected["preferences"]
        skills = prefs.get("must_have_skills", [])
        skills = [s for s in skills if isinstance(s, str)] if isinstance(skills, list) else []
        chips = "".join(f"<span class='chip'>{html.escape(s)}</span>" for s in skills)
        chips = f"<div class='chips'>{chips}</div>" if chips else "<div class='empty-skill'>Todavía no has agregado habilidades obligatorias.</div>"
        salary = prefs.get("salary_min_usd_month")
        salary_label = html.escape(f"USD {salary:,}" if isinstance(salary, (float, int)) and salary else "Sin definir")
        detail = (f"<div class='detail-inner'><div class='detail-top'><div class='large-avatar'>"
                  f"{html.escape(selected['name'][:2].upper())}</div><div><div class='detail-title'>{html.escape(selected['name'])}</div>"
                  "<div class='substatus'><span class='dot'></span>Preferencias guardadas</div></div></div>"
                  f"<div class='info-grid'><div class='mini-info'><div class='k'>Modalidades preferidas</div><div class='v'>"
                  f"{icon('world')}{html.escape(mode_text(prefs.get('work_mode')))}</div></div><div class='mini-info'>"
                  f"<div class='k'>Salario mínimo mensual</div><div class='v'>{icon('wallet')}{salary_label}</div></div></div>"
                  f"<div class='field-heading'>Habilidades requeridas <span>{len(skills)} configuradas</span></div>{chips}"
                  f"{profile_forms[selected['id']]}</div>")
    else:
        detail = "<div class='empty-page'><div class='empty-illustration'>" + icon("user") + "</div><h3>Configura tu primera búsqueda</h3><p>Crea un perfil para guardar tus cargos y preferencias.</p></div>"
    detail_panel = "<section class='panel'><div class='panel-head'><div><h3>Detalles del perfil</h3><p>Preferencias y habilidades configuradas.</p></div></div>" + detail + "</section>"
    split = f"<div class='split'>{list_panel}{detail_panel}</div>"
    create_form = ("<section class='panel config-card' id='crear-perfil'><h3>Crear perfil</h3>"
                   "<p>Un perfil agrupa cargos que comparten preferencias. Puedes empezar con uno.</p>"
                   f"<form method='post' action='/profiles'><input type='hidden' name='csrf' value='{csrf}'>"
                   "<label>Nombre <input name='name' required maxlength='200' placeholder='Ej. Desarrollo remoto'></label>"
                   "<label>Zona horaria <input name='timezone' value='UTC' placeholder='America/Bogota o UTC-5' required></label>"
                   "<button class='btn btn-primary'>Crear perfil</button></form></section>")
    hero = ("<div class='hero'><div class='hero-content'><span class='hero-kicker'>✧ TU ASISTENTE DE BÚSQUEDA</span>"
            "<h2>Las oportunidades correctas empiezan con un buen perfil.</h2>"
            "<p>Organiza tus preferencias, descubre coincidencias y mantén cada decisión bajo control.</p></div>"
            "<div class='hero-figure' aria-hidden='true'><div class='floating-card'><div class='float-line'></div>"
            "<div class='float-line'></div><div class='float-line'></div></div><div class='float-star'>✦</div></div></div>")
    metrics = ("<div class='metrics'>" + metric("Perfiles creados", len(profiles), "En tu espacio de trabajo", "user", "lilac")
               + metric("Vacantes registradas", counts["jobs"], "En tu base local", "briefcase", "blue")
               + metric("Postulaciones", counts["submitted"], "Con comprobante registrado", "check", "mint")
               + metric("Decisiones pendientes", counts["pending"], "Requieren tu revisión", "bell", "amber") + "</div>")
    contents = {
        "inicio": heading("TU CENTRO DE CONTROL", "Tu búsqueda, bajo control ✦", "Gestiona tus perfiles, oportunidades y postulaciones desde un solo lugar.", create=True)
        + hero + metrics + split + "<div class='lower-grid'>" + card("Actividad reciente", f"<ul class='record-list'>{jobs}</ul>")
        + card("Bandeja de correo", f"<ul class='record-list'>{manual_mail}</ul>") + "</div>",
        "perfiles": heading("PERFILES", "Perfiles profesionales", "Personaliza los criterios para evaluar tus oportunidades.", create=True)
        + split + create_form,
        "vacantes": heading("OPORTUNIDADES", "Vacantes evaluadas", "Revisa las oportunidades y sus resultados de evaluación.")
        + card("Vacantes evaluadas", f"<ul class='record-list'>{jobs}</ul>"),
        "decisiones": heading("REVISIÓN", "Decisiones pendientes", "Cada acción importante permanece bajo tu control.")
        + card("Decisiones pendientes", f"<ul class='record-list'>{decisions}</ul>"),
        "correo": heading("COMUNICACIONES", "Centro de correo", "Revisa mensajes y respuestas que requieren tu atención.")
        + "<div class='mail-metrics metrics'>" + metric("Correos registrados", counts["mail"], "Historial local", "mail", "blue")
        + metric("Por revisar en Gmail", counts["manual_mail"], "Pendientes de revisión", "bell", "amber")
        + metric("Respuestas aprobadas", counts["replies"], "Pendientes de envío", "check", "mint") + "</div>"
        + card("Correo registrado", f"<ul class='record-list'>{inbox}</ul>")
        + card("Correos para revisar en Gmail", f"<ul class='record-list'>{manual_mail}</ul>")
        + card("Respuestas aprobadas", f"<ul class='record-list'>{replies}</ul>"),
        "configuracion": heading("PERSONALIZACIÓN", "Configuración", "Administra las preferencias y la integración de Gmail.") + configuration,
    }
    screens = "".join(f"<section class='view{' active' if key == view else ''}' id='view-{key}'>{content}</section>"
                      for key, content in contents.items())
    simulation = "Modo simulación activo" if settings.dry_run else "Modo real seleccionado"
    explanation = "Los envíos reales están desactivados." if settings.dry_run else "Cada envío requiere permisos y aprobación."
    sprite = files("pandapply").joinpath("assets/panel-icons.html").read_text(encoding="utf-8")
    return ("<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>"
            "<title>PandApply — Panel local</title><link rel='stylesheet' href='/assets/panel.css'></head><body>"
            + sprite + "<a class='skip-link' href='#workspace'>Ir al contenido</a><div class='shell'><aside class='sidebar'>"
            "<a class='brand' href='/'><span class='brand-mark'><svg aria-hidden='true' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2'>"
            "<path d='m6 5 6 14 6-14M8.2 12h7.6'/></svg></span><span><span class='brand-name'>PandApply<span class='accent'>.</span></span>"
            "<span class='brand-sub'>Career workspace</span></span></a><nav aria-label='Navegación principal'><div class='nav-label'>ESPACIO DE TRABAJO</div>"
            "<div class='nav-list'>" + "".join(nav) + "</div></nav><div class='sidebar-footer'><div class='sandbox'>"
            f"<strong><span class='dot'></span>{simulation}</strong><p>{explanation}</p></div>"
            "<div class='account'><div class='avatar'>PA</div><div><div class='a-name'>Panel local</div><div class='a-desc'>Entorno de trabajo</div></div></div>"
            "</div></aside><main class='main'><header class='topbar'><div class='breadcrumb'>Workspace <span>/</span>"
            f"<b>{VIEWS[view][0]}</b></div><div class='top-actions'><span class='top-indicator'><span class='dot'></span>{simulation}</span>"
            f"<a class='round-btn' aria-label='Decisiones pendientes' href='{url('decisiones')}'>{icon('bell')}</a>"
            f"<form method='post' action='/logout'><input type='hidden' name='csrf' value='{csrf}'>"
            "<button class='btn btn-outline small'>Cerrar sesión</button></form></div></header>"
            f"<div class='workspace' id='workspace'>{screens}</div></main></div></body></html>")
