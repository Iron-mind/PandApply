# Verificación inicial de Hermes con Docker

Imagen oficial `nousresearch/hermes-agent:stable`, digest
`sha256:d6746a084e9341baada483e3d6210444d3c1aeb7c130f0915150065fb2851459`.
La ejecución aislada informó Hermes Agent v0.23.2 (2026.9.24), Python 3.14.9.
La etiqueta `stable` puede cambiar; usar el digest para reproducir la misma imagen.

```sh
docker pull nousresearch/hermes-agent:stable
docker run --rm --network none nousresearch/hermes-agent:stable --version
docker run --rm --network none nousresearch/hermes-agent:stable cron --help
```

Sin montar carpetas del usuario ni proporcionar credenciales, `--version` respondió
correctamente, `cron --help` enumeró comandos de creación, edición, pausa y estado,
`cron list` mostró una lista vacía y `skills list` enumeró las skills disponibles.
En otro contenedor desechable, `cron create "every 24h" "PandApply fixture check only" --name pandapply-fixture --paused --deliver local`
creó una tarea pausada; Hermes informó que no había scheduler activo. La tarea no se
ejecutó y desapareció al destruir el contenedor.
Una prueba posterior con `scripts/hermes_cron_smoke.py` creó una tarea pausada,
comprobó su presencia, la reanudó y la pausó de nuevo en un `HERMES_HOME` temporal
sin red; no había gateway ni se ejecutó la tarea. Los comandos respondieron correctamente.
La inicialización informó sincronización de la skill `google-workspace` y un binario
Chromium incluido. La ayuda de cron también mostró una advertencia de pnpm ausente
o desactualizado en la imagen. Ninguna de estas observaciones verifica ejecución de
jobs, navegador, Gmail, WhatsApp, OAuth ni integración con PandApply; siguen pendientes
pruebas funcionales por capacidad. No hay versión mínima compatible confirmada.

`scripts/hermes_cron_e2e.py` prueba además el adaptador de PandApply contra Hermes
en un contenedor desechable sin red: crea una tarea pausada, reconcilia su estado,
la reanuda y vuelve a pausarla. No había gateway activo y la tarea no se ejecutó.
La prueba no usa Gmail ni credenciales y no confirma que el seguimiento automático
funcione con una cuenta real.

En un contenedor separado de la misma imagen se creó un entorno virtual independiente,
se instaló PandApply como paquete y se ejecutó `pandapply demo` correctamente con
Python 3.14. Esto verifica la instalación y demo dentro de la imagen, pero no que el
agente Hermes invoque PandApply, ni las capacidades externas anteriores.

El script incluido `skills/productivity/google-workspace/scripts/google_api.py` de esa
imagen documenta y acepta `gmail search QUERY --max N` y `gmail get MESSAGE_ID`.
Se verificó la ayuda de búsqueda sin credenciales. PandApply incluye un puente de
lectura para ese contrato, probado con un script falso; queda pendiente validarlo con
una cuenta autorizada.

Para asociar mensajes a postulaciones, el adaptador usa el `build_service` de esa
versión de la skill en el entorno Python de Hermes y consulta `users.getProfile`
antes de leer con el mismo servicio autenticado. Esta interfaz interna puede cambiar;
si faltan la función o las dependencias de Google, PandApply falla sin asociar datos.
La comprobación de cuenta se probó con un servicio falso, no con OAuth real.

También se implementó una ruta experimental de respuesta con un permiso persistente
de un solo uso, validación de cuenta y contexto, y reconciliación sin reenvío. Está
desactivada por defecto y se ha probado únicamente con un proveedor falso. No hay
evidencia de que el envío real, OAuth o la reconciliación funcionen con una cuenta.
La identidad se consulta con [Gmail users.getProfile](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users/getProfile);
el hilo y las cabeceras siguen la [guía oficial de conversaciones](https://developers.google.com/workspace/gmail/api/guides/threads).

Se ejecutó `scripts/hermes_sandbox_smoke.py` dentro de la misma imagen con `--network none`,
usuario sin privilegios y sin montar perfiles ni credenciales. `browser_exec` abrió el
formulario del ATS local, rellenó sus campos, adjuntó un archivo de prueba mediante
CDP y envió el formulario desde el navegador; el ATS devolvió un recibo. Esto verifica ese camino local, no el
control de ventanas personales, un portal real ni la reutilización de un perfil de usuario.

En una segunda prueba aislada, `scripts/hermes_browser_e2e.py` ejecutó el flujo de
PandApply: candidatura ficticia, PDF con evidencia confirmada, intento persistido,
formulario mediante `browser_exec` y comprobación del recibo contra el ATS. La prueba
produjo un solo intento confirmado usando un entorno Hermes temporal y sin red externa.
No verifica el comportamiento de una instalación nativa Windows ni habilita portales reales.

Fuente: [documentación oficial de Docker para Hermes](https://hermes-agent.nousresearch.com/docs/user-guide/docker).

`scripts/hermes_setup_smoke.py` verifica la detección de las rutas de Python y Google
Workspace en esa instalación, primero sin credenciales y luego con archivos ficticios
de Gmail y WhatsApp. Se ejecutó sin red, con un directorio temporal y sin montar
cuentas personales. Las ubicaciones se contrastaron con `hermes_constants.py`,
`google_api.py` y el adaptador WhatsApp de la imagen. La detección comprueba presencia
de archivos, no validez de tokens ni conexión del gateway. No lee sus contenidos,
no empareja WhatsApp y no inicia OAuth. Las rutas de sesión personalizadas y otros
conectores Google pueden necesitar configuración manual.

El asistente de instalación se comprobó además con una instalación desde cero en
Windows (entorno virtual nuevo y descarga de dependencias) y con
`scripts/easy_setup_smoke.py` en Linux dentro del contenedor sin red. La prueba
Linux reutiliza el entorno del contenedor y comprueba el lanzador y la configuración
guiada con un perfil ficticio; no prueba la descarga de dependencias en Linux.

Para el saludo piloto se verificaron `hermes send --help` y `hermes_cli/send_cmd.py`:
`send --to whatsapp:NUMERO@s.whatsapp.net --json --file -` recibe el texto por stdin
y devuelve un JSON con `success` y `message_id`. `scripts/hermes_whatsapp_contract.py`
ejecuta el parser y la salida JSON reales con un backend falso, sin red ni credenciales.
No envía mensajes. La entrega real por WhatsApp, la recepción autenticada de la respuesta
y el inicio de la primera búsqueda no quedan comprobados por esa prueba.

También se contrastó la distribución nativa Windows instalada: lanzador bajo `bin`,
código bajo `hermes-agent` y dependencias seleccionadas por PM en
`installs/<sha256-del-checkout:16>/facts.json`, clave
`packages.venv.environment`. La detección lee únicamente esa metadata y comprueba
que el entorno pertenezca a `environments` de esa instalación y tenga `pyvenv.cfg`.
Se comprobó que resuelve el intérprete y Google Workspace locales sin ejecutar Hermes
ni consultar Gmail. No se considera prueba de autenticación Gmail. Una selección PM
inválida no permite recurrir silenciosamente a un entorno antiguo del checkout.

`scripts/hermes_login_smoke.py` reproduce con Chromium real el fallo de login:
la política antigua `no-referrer` provoca `Origin: null` en el envío nativo del
formulario y el servidor lo rechaza. Con `same-origin`, el mismo navegador envía
el origen local y entra al panel. El comportamiento coincide con la
[documentación de Referrer-Policy sobre Origin](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Referrer-Policy#effect_on_the_origin_header).
La prueba usa un servidor, base y contraseña ficticios dentro de Docker sin red;
no utiliza perfiles del usuario. La protección de origen y token CSRF permanece activa.

El chequeo `pandapply.browser_checks.probe_managed` disponible desde el asistente
se ejecutó además en ese contenedor sin red: crea perfil, evidencia y CV ficticios,
usa Hermes para enviar al ATS local y verifica un recibo `sandbox-`. Su resultado
`sandbox_verified` se limita a ese formulario. Las pruebas CDP usan un servidor
HTTP local simulado, comprueban `/json/version` y rechazan redirecciones o destinos
remotos; no prueban control de un navegador personal real.

`scripts/hermes_panel_smoke.py` comprueba el panel rediseñado con Chromium mediante
Hermes: login, navegación, creación, edición y eliminación de un perfil ficticio,
persistencia en SQLite y vista móvil sin desbordamiento horizontal. Las capturas
usan exclusivamente datos sintéticos y pueden guardarse en `/artifacts` del contenedor.
