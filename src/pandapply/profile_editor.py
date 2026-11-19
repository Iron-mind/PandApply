"""Native profile forms; search preferences are separate from confirmed CV facts."""

import html
import json
import math

from pandapply.work_modes import parse_work_modes, work_mode_preference

LIST_FIELDS = {
    'locations': 'Países o ciudades', 'languages': 'Idiomas de las vacantes',
    'nice_to_have_skills': 'Habilidades deseables', 'required_keywords': 'Palabras obligatorias',
    'excluded_keywords': 'Palabras excluidas', 'excluded_companies': 'Empresas excluidas',
    'contract_types': 'Tipos de contrato', 'timezones': 'Zonas horarias de las vacantes',
    'preferred_cvs': 'CV preferidos (identificadores)',
}
TEXT_FIELDS = {'seniority': 'Nivel de experiencia buscado', 'english_level': 'Nivel de inglés buscado',
               'cv_directory': 'Carpeta de CV', 'cv_language': 'Idioma del CV'}
KNOWN_FIELDS = set(LIST_FIELDS) | set(TEXT_FIELDS) | {
    'must_have_skills', 'role_queries', 'work_mode', 'salary_min_usd_month', 'min_verified_years'}


def escape(value) -> str:
    return html.escape(str(value if value is not None else ''), quote=True)


def render_profile_editor(profile: dict, csrf: str, submitted=None) -> str:
    prefs = profile['preferences']

    def value(key, default=''):
        if submitted is not None and key in submitted:
            return submitted[key]
        stored = prefs.get(key, default)
        return ', '.join(str(item) for item in stored) if isinstance(stored, list) else stored

    def field(key, label, *, default='', kind='text', help_text=''):
        current = value(key, default)
        if key == 'name':
            current = submitted.get('name', profile['name']) if submitted is not None else profile['name']
        if key == 'skills':
            current = submitted.get('skills', value('must_have_skills')) if submitted is not None else value('must_have_skills')
        if key == 'salary':
            current = submitted.get('salary', value('salary_min_usd_month')) if submitted is not None else value('salary_min_usd_month')
        if key == 'role_queries' and submitted is None and prefs.get(key) == [profile['name']]:
            current = ''
        attributes = " min='0' step='0.01'" if kind == 'number' else " maxlength='4000'"
        if key == 'name':
            attributes = " required maxlength='200'"
        return (f"<label class='field'>{label}<input name='{key}' type='{kind}' value='{escape(current)}'{attributes}>"
                + (f"<small>{help_text}</small>" if help_text else '') + '</label>')

    selected = (submitted.getlist('work_modes') if submitted is not None
                else parse_work_modes(prefs.get('work_mode')))
    modes = ''.join(f"<label class='mode-option'><input type='checkbox' name='work_modes' value='{key}'"
                    + (' checked' if key in selected else '') + f'>{label}</label>'
                    for key, label in [('remote', 'Remoto'), ('hybrid', 'Híbrido'), ('onsite', 'Presencial')])
    extra = {key: val for key, val in prefs.items() if key not in KNOWN_FIELDS}
    extra_json = (submitted.get('extra_preferences') if submitted is not None and 'extra_preferences' in submitted
                  else json.dumps(extra, ensure_ascii=False, indent=2))
    return (
        f"<form class='profile-edit-form' method='post' action='/profiles/{escape(profile['id'])}/edit'>"
        f"<input type='hidden' name='csrf' value='{escape(csrf)}'>"
        f"<input type='hidden' name='version' value='{escape(submitted.get('version', profile['version']) if submitted is not None else profile['version'])}'>"
        "<fieldset><legend>Tu perfil de búsqueda</legend>"
        + field('name', 'Nombre del perfil / cargo que buscas')
        + "<p class='form-help'>El nombre se usa para buscar vacantes. Estos criterios expresan lo que buscas; no añaden experiencia a tu CV.</p>"
        + "<div class='form-grid'>" + field('locations', LIST_FIELDS['locations'], help_text='Separa varios valores con comas.')
        + field('languages', LIST_FIELDS['languages'], help_text='Por ejemplo: es, en.') + '</div>'
        + "<div class='field'><span>Modalidades que aceptas</span><input type='hidden' name='work_modes_present' value='1'>"
        + f"<div class='mode-options'>{modes}</div><small>Sin marcar ninguna, se aceptan todas.</small></div>"
        + '<div class="form-grid">' + field('salary', 'Salario mínimo mensual (USD)', kind='number')
        + field('seniority', TEXT_FIELDS['seniority']) + '</div>'
        + field('skills', 'Habilidades obligatorias', help_text='Separa varias con comas.')
        + field('nice_to_have_skills', LIST_FIELDS['nice_to_have_skills']) + '</fieldset>'
        + "<details class='advanced-options'><summary>Más criterios y documentos</summary><div class='form-grid'>"
        + field('role_queries', 'Términos de búsqueda personalizados', help_text='Opcional. En blanco se usa el nombre del perfil; separa alternativas con comas.')
        + field('min_verified_years', 'Experiencia mínima requerida en la vacante (años)', kind='number')
        + ''.join(field(key, label) for key, label in LIST_FIELDS.items()
                  if key not in ('locations', 'languages', 'nice_to_have_skills'))
        + ''.join(field(key, label) for key, label in TEXT_FIELDS.items() if key != 'seniority')
        + "</div><p class='form-help'>Estos criterios se guardan por perfil. La aplicación de algunos filtros y la selección automática de CV siguen en desarrollo. Guardar una carpeta no importa sus archivos.</p></details>"
        + "<details class='advanced-options'><summary>Otros datos guardados (avanzado)</summary>"
        + "<label class='field'>Preferencias adicionales en JSON"
        + f"<textarea name='extra_preferences' rows='5' spellcheck='false'>{escape(extra_json)}</textarea>"
        + '<small>Conserva aquí los campos personalizados de versiones o adaptadores anteriores.</small></label></details>'
        + "<div class='editor-actions'><button class='btn btn-primary'>Guardar cambios</button>"
        + "<a class='btn' href='/?view=perfiles'>Cancelar</a></div></form>"
    )


def parse_profile_form(profile: dict, form) -> tuple[str, dict]:
    name = form.get('name', '').strip()
    if not name or len(name) > 200:
        raise ValueError('El nombre debe contener entre 1 y 200 caracteres.')
    prefs = dict(profile['preferences'])
    if 'extra_preferences' in form:
        raw = form['extra_preferences']
        if len(raw) > 20000:
            raise ValueError('Los datos adicionales son demasiado largos.')
        try:
            extra = json.loads(raw or '{}')
        except ValueError as exc:
            raise ValueError('Revisa el formato JSON de los datos adicionales.') from exc
        if not isinstance(extra, dict) or KNOWN_FIELDS.intersection(extra):
            raise ValueError('Los datos adicionales deben ser un objeto JSON sin repetir los campos del formulario.')
        prefs = {key: value for key, value in prefs.items() if key in KNOWN_FIELDS}
        prefs.update(extra)
    for key in [*LIST_FIELDS, 'skills', 'role_queries']:
        if key not in form:
            continue
        parts = list(dict.fromkeys(part.strip() for part in form[key].split(',') if part.strip()))
        if len(parts) > 100 or any(len(part) > 200 for part in parts):
            raise ValueError('Usa como máximo 100 valores por campo, de hasta 200 caracteres cada uno.')
        prefs['must_have_skills' if key == 'skills' else key] = parts
    if not prefs.get('role_queries') or ('role_queries' not in form and prefs.get('role_queries') == [profile['name']]):
        prefs['role_queries'] = [name]
    for key in TEXT_FIELDS:
        if key in form:
            text = form[key].strip()
            if len(text) > 4000:
                raise ValueError('Un campo de texto supera los 4000 caracteres.')
            if text:
                prefs[key] = text
            else:
                prefs.pop(key, None)
    for key, target, maximum in [('salary', 'salary_min_usd_month', 10_000_000),
                                 ('min_verified_years', 'min_verified_years', 100)]:
        if key in form:
            text = form[key].strip()
            if text:
                try:
                    number = float(text)
                except ValueError as exc:
                    raise ValueError('Salario y años de experiencia deben ser números positivos.') from exc
                if not math.isfinite(number) or not 0 <= number <= maximum:
                    raise ValueError(f'El valor de {key} debe estar entre 0 y {maximum}.')
                prefs[target] = number
            else:
                prefs.pop(target, None)
    if 'work_modes_present' in form or 'work_modes' in form:
        mode = work_mode_preference(','.join(form.getlist('work_modes')) or 'any')
        if mode:
            prefs['work_mode'] = mode
        else:
            prefs.pop('work_mode', None)
    return name, prefs
