"""Server-rendered workspace based on the owner's HTML redesign."""

import html
from importlib.resources import files
from urllib.parse import urlencode

from pandapply.work_modes import parse_work_modes

VIEWS = {"inicio": ("Resumen", "layout"), "perfiles": ("Perfiles", "user"),
         "vacantes": ("Vacantes", "briefcase"), "decisiones": ("Decisiones", "check"),
         "correo": ("Correo", "mail"), "configuracion": ("Configuración", "settings")}


def icon(name: str) -> str:
    return f"<svg class='icon' aria-hidden='true' fill='none' stroke='currentColor'><use href='#i-{name}'/></svg>"


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
            f"<p class='sub'>{subtitle}</p></div>{action}</div>")


def card(title: str, content: str, subtitle: str = "") -> str:
    return (f"<section class='panel'><div class='panel-head'><div><h3>{title}</h3><p>{subtitle}</p>"
            f"</div></div><div class='panel-content'>{content}</div></section>")


def metric(label: str, count: int, caption: str, symbol: str, color: str) -> str:
    return (f"<div class='kpi'><div><div class='kpi-label'>{label}</div><div class='kpi-value'>{count}</div>"
            f"<div class='kpi-hint'>{caption}</div></div><div class='kpi-icon {color}'>{icon(symbol)}</div></div>")


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
            "</head><body class='action-page'><main class='workspace'><a class='brand' href='/'>PandApply</a>"
            f"<section class='panel config-card'><h1>{html.escape(title)}</h1>{content}</section></main></body></html>")


def render_panel(*, view: str, selected_id: str | None, query: str, profiles: list[dict],
                 profile_forms: dict[str, str], csrf: str, settings, counts: dict[str, int],
                 jobs: str, decisions: str, inbox: str, manual_mail: str, replies: str,
                 configuration: str, saved: bool = False) -> str:
    view = view if view in VIEWS else 'inicio'
    visible = [p for p in profiles if query.casefold() in p['name'].casefold()]
    selected = next((p for p in visible if p['id'] == selected_id), visible[0] if visible else None)
    nav = []
    for key, (label, symbol) in VIEWS.items():
        active = ' active' if key == view else ''
        current = " aria-current='page'" if key == view else ''
        count = f"<span class='nav-count'>{len(profiles)}</span>" if key == 'perfiles' else ''
        nav.append(f"<a class='nav-item{active}' href='{url(key)}'{current}>{icon(symbol)}{label}{count}</a>")

    def profile_card(profile):
        active = ' selected' if selected and selected['id'] == profile['id'] and view == 'perfiles' else ''
        chosen = profile['id'] in settings.search_profile_ids
        status = 'Seleccionado para buscar' if chosen else 'Disponible'
        return (f"<a class='profile-card{active}' href='{url('perfiles', profile['id'], query)}#editar-perfil'>"
                "<div class='profile-head'><span class='profile-mark'>"
                f"{html.escape(profile['name'][:2].upper())}</span><div class='profile-text'>"
                f"<div class='profile-title'>{html.escape(profile['name'])}</div>"
                f"<div class='profile-kicker'>{html.escape(mode_text(profile['preferences'].get('work_mode')))}</div>"
                f"</div></div><div class='profile-footer'><span class='pill{' neutral' if not chosen else ''}'>"
                f"{status}</span><span class='arrow-circle'>{icon('chevron')}</span></div></a>")

    empty = "<div class='empty-note'>No se encontraron perfiles.</div>"
    profile_cards = ''.join(profile_card(p) for p in visible) or empty
    home_cards = ''.join(profile_card(p) for p in profiles[:4]) or empty
    search = (f"<form class='search' method='get' action='/'>{icon('search')}"
              "<input type='hidden' name='view' value='perfiles'>"
              f"<input name='q' type='search' value='{html.escape(query, quote=True)}' placeholder='Buscar un perfil...' aria-label='Buscar perfiles'>"
              "<button class='search-submit' aria-label='Buscar'>→</button></form>")
    if selected:
        prefs = selected['preferences']
        salary = prefs.get('salary_min_usd_month')
        salary_text = f'USD {salary:,.2f}' if isinstance(salary, (int, float)) and salary else 'Sin definir'
        detail = ("<section class='panel profile-detail' id='editar-perfil'><div class='drawer-header'><div>"
                  f"<h2 class='drawer-head-title'>{html.escape(selected['name'])}</h2>"
                  "<p>Edita tu perfil y guarda todos los cambios juntos.</p></div>"
                  f"<span class='seal' aria-hidden='true'>道</span></div><div class='drawer-content'>"
                  + ("<p class='save-notice' role='status'>Cambios guardados.</p>" if saved else '')
                  + "<div class='info-grid'><div class='mini-info'><small>Modalidades</small><strong>"
                  + html.escape(mode_text(prefs.get('work_mode'))) + "</strong></div><div class='mini-info'>"
                  f"<small>Salario mínimo mensual</small><strong>{html.escape(salary_text)}</strong></div></div>"
                  + profile_forms[selected['id']] + '</div></section>')
    else:
        detail = ''
    create_form = ("<section class='panel config-card' id='crear-perfil'><h2>Crear perfil</h2>"
                   "<p>El nombre es el cargo que buscas. Después puedes editar todos sus criterios.</p>"
                   f"<form method='post' action='/profiles'><input type='hidden' name='csrf' value='{csrf}'>"
                   "<div class='form-grid'><label>Cargo o nombre del perfil <input name='name' required maxlength='200' placeholder='Ej. Backend Developer'></label>"
                   "<label>Zona horaria del sistema <input name='timezone' value='UTC' placeholder='America/Bogota o UTC-5' required></label></div>"
                   "<button class='btn btn-primary'>Crear perfil</button></form></section>")
    panda = files('pandapply').joinpath('assets/panel-panda.html').read_text(encoding='utf-8')
    brand = files('pandapply').joinpath('assets/panel-brand.html').read_text(encoding='utf-8')
    hero = ("<div class='hero'><div class='hero-copy'><div class='micro'>✦ LA SENDA HACIA TU PRÓXIMO EMPLEO</div>"
            "<h2>Tu próximo paso,<br>con <em>calma y propósito.</em></h2>"
            "<p>Prepara tus perfiles, encuentra tu rumbo y decide cada movimiento de tu búsqueda profesional.</p>"
            f"<a class='btn hero-btn' href='{url('perfiles')}'>{icon('user')}Preparar mis perfiles</a></div>"
            "<div class='hero-art' aria-hidden='true'><div class='hero-sun'></div><div class='hero-bamboo'></div>"
            f"<span class='hero-script'>功夫</span>{panda}</div></div>")
    metrics = ("<div class='kpis'>" + metric('Perfiles creados', len(profiles), 'En tu espacio de trabajo', 'user', '')
               + metric('Vacantes registradas', counts['jobs'], 'En tu base local', 'briefcase', '')
               + metric('Postulaciones', counts['submitted'], 'Con comprobante registrado', 'check', '')
               + metric('Decisiones pendientes', counts['pending'], 'Requieren tu revisión', 'bell', '') + '</div>')
    journey = ("<aside class='panel journey'><div class='journey-top'><h2>La senda del panda</h2>"
               "<div class='seal' aria-hidden='true'>道</div></div><p class='journey-sub'>Un paso a la vez, con tus decisiones al frente.</p><div class='journey-steps'>")
    for symbol, title, description, target in [
        ('user', '01. Prepara tu técnica', 'Ajusta los cargos y preferencias de tus perfiles.', 'perfiles'),
        ('search', '02. Explora oportunidades', 'Revisa las vacantes registradas y evaluadas.', 'vacantes'),
        ('check', '03. Elige tu movimiento', 'Resuelve las decisiones que requieren tu aprobación.', 'decisiones'),
    ]:
        journey += (f"<a class='journey-step' href='{url(target)}'><span class='step-icon'>{icon(symbol)}</span>"
                    f"<span><span class='step-title'>{title}</span><span class='step-desc'>{description}</span></span></a>")
    journey += "</div><div class='side-state'>" + icon('check') + "<div><strong>Tú decides el rumbo</strong><p>Guardar preferencias no autoriza envíos ni activa búsquedas automáticas.</p></div></div></aside>"
    contents = {
        'inicio': heading('TU CENTRO DE CONTROL', 'Tu búsqueda, bajo control', 'Tu espacio para avanzar con claridad.', create=True)
        + hero + metrics + "<div class='dashboard-grid'><section><div class='section-heading'><div><h2>Mis perfiles profesionales</h2>"
        f"<p>Cada perfil, un rumbo para tu búsqueda.</p></div><a class='section-link' href='{url('perfiles')}'>Ver todos →</a>"
        f"</div><div class='profile-grid'>{home_cards}</div></section>{journey}</div><div class='bottom-grid'>"
        + card('Actividad reciente', f"<ul class='record-list'>{jobs}</ul>")
        + card('Bandeja de correo', f"<ul class='record-list'>{manual_mail}</ul>") + '</div>',
        'perfiles': heading('PERFILES', 'Perfiles profesionales', 'Abre un perfil para editar su nombre y todos sus criterios.', create=True)
        + f"<div class='toolbar'>{search}<span class='profile-total'>{len(visible)} perfiles</span></div>"
        + f"<div class='profiles-workspace'><div class='roster profile-list'>{profile_cards}</div>{detail}</div>" + create_form,
        'vacantes': heading('OPORTUNIDADES', 'Vacantes evaluadas', 'Revisa las oportunidades y sus resultados de evaluación.')
        + card('Vacantes evaluadas', f"<ul class='record-list'>{jobs}</ul>"),
        'decisiones': heading('REVISIÓN', 'Decisiones pendientes', 'Cada acción importante permanece bajo tu control.')
        + card('Decisiones pendientes', f"<ul class='record-list'>{decisions}</ul>"),
        'correo': heading('COMUNICACIONES', 'Centro de correo', 'Revisa mensajes y respuestas que requieren tu atención.')
        + "<div class='kpis mail-metrics'>" + metric('Correos registrados', counts['mail'], 'Historial local', 'mail', '')
        + metric('Por revisar en Gmail', counts['manual_mail'], 'Pendientes de revisión', 'bell', '')
        + metric('Respuestas aprobadas', counts['replies'], 'Pendientes de envío', 'check', '') + '</div>'
        + card('Correo registrado', f"<ul class='record-list'>{inbox}</ul>")
        + card('Correos para revisar en Gmail', f"<ul class='record-list'>{manual_mail}</ul>")
        + card('Respuestas aprobadas', f"<ul class='record-list'>{replies}</ul>"),
        'configuracion': heading('PERSONALIZACIÓN', 'Configuración', 'Administra tus preferencias e integraciones.') + configuration,
    }
    simulation = 'Modo simulación activo' if settings.dry_run else 'Modo real seleccionado'
    explanation = 'Los envíos reales están desactivados.' if settings.dry_run else 'Cada envío requiere permisos y aprobación.'
    sprite = files('pandapply').joinpath('assets/panel-icons.html').read_text(encoding='utf-8')
    return ("<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>"
            "<title>PandApply — Panda Oriental</title><link rel='stylesheet' href='/assets/panel.css'></head><body>"
            + sprite + "<a class='skip-link' href='#workspace'>Ir al contenido</a><div class='shell'><aside class='sidebar'>"
            f"<a class='brand' href='/'><span class='brand-emblem' aria-hidden='true'>{brand}</span>"
            "<span><span class='brand-name'>Pand<span>Apply</span></span><span class='brand-note'>ENCUENTRA TU CAMINO</span></span></a>"
            "<div class='side-label'>ESPACIO DE TRABAJO</div><nav class='nav' aria-label='Navegación principal'>"
            + ''.join(nav) + "</nav><div class='sidebar-spacer'></div><div class='side-note'>"
            f"<div class='side-note-top'><span class='dot'></span>{simulation}</div><p>{explanation}</p></div>"
            "<div class='side-profile'><span class='side-avatar'>PA</span><span><strong>Panel local</strong><small>Tu espacio personal</small></span></div>"
            "</aside><main class='main'><header class='topbar'><div class='breadcrumb'>Mi espacio <span>/</span>"
            f"<strong>{VIEWS[view][0]}</strong></div><div class='top-actions'><span class='mode'><span class='dot'></span>{simulation}</span>"
            f"<a class='top-mini-btn' aria-label='Decisiones pendientes' href='{url('decisiones')}'>{icon('bell')}</a>"
            f"<form method='post' action='/logout'><input type='hidden' name='csrf' value='{csrf}'>"
            "<button class='btn btn-small'>Cerrar sesión</button></form></div></header>"
            f"<div class='content workspace' id='workspace'><section class='view active' id='view-{view}'>"
            f"{contents[view]}</section></div></main></div></body></html>")
