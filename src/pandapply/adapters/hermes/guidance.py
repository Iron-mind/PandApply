"""Hand configuration to the user's interactive Hermes, without collecting secrets."""

import os
import re
import subprocess
import sys
from pathlib import Path

from pandapply.browser_checks import cdp_endpoint as normalize_endpoint

PROMPTS = {
    'gmail': (
        'Ayúdame a configurar o reparar Gmail para PandApply en este perfil de Hermes. '
        'Comprueba primero lo que ya está instalado y autorizado. Usa la habilidad Google Workspace '
        'de Hermes y su puente Python google_api.py con build_service para Gmail v1, que es el '
        'adaptador que PandApply puede comprobar actualmente. Si falta una dependencia o la '
        'habilidad, ayúdame a instalarla con el mecanismo soportado por esta versión. Guíame '
        'por OAuth de Google y verifica la dirección principal con getProfile; explícame los '
        'permisos y conserva credenciales en Hermes. No envíes correos ni leas el contenido del '
        'buzón como prueba. Si solo puedes configurar otro conector, explica que PandApply aún '
        'necesita un adaptador compatible; no prometas que ya está conectado.'),
    'browser': (
        'Ayúdame a configurar o reparar el navegador de Hermes para PandApply. Revisa primero '
        'la instalación existente. Pregúntame si usaré el navegador administrado o Chrome/Edge '
        'existente mediante CDP; respeta la selección que ya te indico. Ayúdame a instalar los '
        'componentes ausentes con mecanismos soportados. Si elijo CDP, explica qué es, cómo '
        'habilitarlo con un directorio de datos separado y cómo comprobar /json/version, y '
        'devuélveme el endpoint local para introducirlo en PandApply. Mantén CDP en loopback. '
        'Limita las pruebas a una página local ficticia; no postules, no envíes formularios '
        'reales ni cierres o reemplaces mi navegador personal.'),
    'whatsapp': (
        'Ayúdame a configurar o reparar WhatsApp en este perfil de Hermes para usarlo con '
        'PandApply. Reutiliza el puente y las sesiones existentes antes de instalar nada. '
        'Guíame con los comandos soportados por esta versión (como hermes whatsapp), QR, '
        'modo de cuenta, remitentes permitidos y estado del gateway. Pregunta antes de '
        'cambiar una sesión existente. No envíes mensajes de prueba; el saludo opcional '
        'se confirma por separado en PandApply. Conserva QR, credenciales y sesiones en Hermes.'),
}


def setup_command(component: str, executable: Path, home: Path, *, browser_mode: str = '',
                  cdp_endpoint: str = '') -> list[str]:
    if component not in PROMPTS:
        raise ValueError('Unknown integration')
    profile = home.name if home.parent.name == 'profiles' else 'default'
    if profile != 'default' and not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}', profile):
        raise ValueError('Invalid Hermes profile name')
    prompt = PROMPTS[component]
    if component == 'browser' and browser_mode in ('cdp', 'hermes_managed'):
        prompt += '\nSelección actual de PandApply: ' + browser_mode + '.'
        if browser_mode == 'cdp' and cdp_endpoint:
            prompt += ' Endpoint local guardado: ' + normalize_endpoint(cdp_endpoint) + '.'
    prompt += ('\nSolo configura esta integración. No cambies perfiles profesionales, autorizaciones '
               'de envío ni tareas programadas de PandApply. No muestres tokens ni contraseñas. '
               'Al terminar indícame que use /exit para regresar al setup; PandApply hará su propia comprobación.')
    # An explicit profile prevents Hermes' sticky active_profile from silently changing accounts.
    return [str(executable), '--profile', profile, 'chat', '-q', prompt]


def launch_setup(component: str, executable: Path | None, home: Path | None, **options) -> dict:
    if component not in PROMPTS:
        raise ValueError('Unknown integration')
    if executable is None or home is None or not executable.is_file() or not home.is_dir():
        return {'status': 'unavailable'}
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        # Non-TTY -q is a one-shot in Hermes, unsuitable for an interactive authorization flow.
        return {'status': 'needs_terminal'}
    try:
        home = home.expanduser().resolve(strict=True)
        command = setup_command(component, executable, home, **options)
        result = subprocess.run(command, cwd=str(home), env={**os.environ, 'HERMES_HOME': str(home)},
                                check=False)
    except KeyboardInterrupt:
        return {'status': 'interrupted'}
    except (OSError, ValueError):
        return {'status': 'failed'}
    return {'status': 'conversation_finished' if result.returncode == 0 else 'failed'}
