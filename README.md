# PandApply

PandApply es un proyecto en desarrollo para asistir en la búsqueda de empleo desde el equipo del usuario. Incluye una demo local completa con datos ficticios y conectores experimentales para Hermes. El diseño completo está en [docs/](docs/05-IMPLEMENTATION-PLAN.md).

## Getting started con Hermes

Necesitas Python 3.11 o posterior y esta carpeta del proyecto descargada o clonada. Si ya usas Hermes con Gmail o WhatsApp, el asistente intentará aprovechar esa instalación. También puedes comenzar con las funciones locales sin tener Hermes instalado.

Abre una terminal en la carpeta de PandApply y ejecuta **un comando**:

**Windows:**

```powershell
.\install.cmd
```

**Linux:**

```sh
sh install.sh
```

El instalador crea un entorno virtual exclusivo, instala las dependencias y abre el asistente. No necesitas activar `.venv` ni ejecutar comandos adicionales de configuración. En Linux, Python debe tener disponible el módulo `venv`.

El asistente te guía para:

1. Elegir Hermes y confirmar su perfil detectado, o indicar su ubicación si hace falta.
2. Reutilizar la autorización existente de Gmail y comprobar la cuenta si lo deseas. La sesión de WhatsApp se reconoce, pero su canal en PandApply sigue pendiente.
   Con la cuenta guardada, el asistente pide filtro, límite de correos, intervalo y permisos (deshabilitado, consulta o respuestas con aprobación). Guarda la configuración sin desactivar el modo de simulación ni activar una tarea programada.
   El asistente también permite elegir navegador administrado por Hermes o conexión local CDP a un navegador existente y comprobarlo. La prueba administrada utiliza un formulario local con datos ficticios. La comprobación CDP solo verifica que la conexión responde; la automatización de ese navegador sigue pendiente. Puedes dejarlo para después.
3. Elegir o crear un perfil profesional y registrar un CV PDF/DOCX, que también puedes agregar después.
4. Elegir los perfiles que buscarán vacantes, cargos, ubicaciones, idiomas, habilidades como filtros, modalidad y piso salarial.
5. Elegir el máximo diario de postulaciones, el volumen de evaluación y la frecuencia. Guardar esos valores no activa postulaciones ni crea un cron.
6. Ofrecer un saludo piloto a tu propio WhatsApp mediante Hermes, con confirmación del número y del mensaje. El intento queda guardado para evitar reenvíos ciegos. La recepción automática de tu respuesta y el inicio de la primera búsqueda real siguen pendientes.
7. Mostrar lo configurado y lo pendiente y, al final, ofrecer iniciar el panel local. La terminal muestra su dirección, usuario y contraseña; Ctrl+C lo detiene.

SQLite se valida automáticamente durante el asistente (integridad, relaciones y escritura); no necesitas instalar un cliente SQL. Los requisitos adicionales del propietario y sus pendientes se documentan en [docs/10-OWNER-REQUIREMENTS.md](docs/10-OWNER-REQUIREMENTS.md).

Los filtros de ubicación e idioma requieren datos explícitos de la vacante (`locations` y `languages` como listas). Si esos datos faltan, la evaluación exige revisión manual en lugar de ignorar el filtro. Las ubicaciones se comparan por nombre normalizado; los idiomas usan códigos como `es` o `en`.

**¿Qué es un perfil de búsqueda?** Es un grupo de preferencias guardadas: modalidad, ubicación, salario y otros filtros. Su nombre es una etiqueta que eliges, por ejemplo «Desarrollo remoto». Dentro puedes buscar varios **cargos**, como «Backend Developer» y «Python Developer», que compartirán esos filtros. Normalmente basta un perfil; crea otro cuando quieras preferencias distintas, por ejemplo para buscar consultoría presencial. La configuración o perfil de Hermes, por su parte, identifica las conexiones de Hermes que reutiliza PandApply.

La zona horaria acepta nombres de ciudades como `America/Bogota` y desfases fijos de horas completas como `UTC-5` o `UTC+3`. Un desfase fijo no cambia en verano/invierno; utiliza una ciudad para seguir esos cambios o para zonas con desfases de media hora. Si te equivocas, el asistente vuelve a pedir únicamente la zona horaria.

Puedes seleccionar varias modalidades: `remote, hybrid`, `remote, hybrid y onsite` o `remoto, híbrido y presencial`. Una vacante cumple el filtro si coincide con cualquiera de las elegidas. `any` acepta todas y se usa sola. Las mismas opciones funcionan en el panel local.

Puedes omitir Gmail y el CV y completar esos datos más adelante. Las credenciales permanecen en Hermes y los archivos originales de CV se conservan. La comprobación de Gmail no habilita respuestas ni envíos. Las integraciones externas son experimentales.

Para volver al asistente sin reinstalar, ejecuta `.\install.cmd --configure-only` en Windows o `sh install.sh --configure-only` en Linux. Si interrumpes la configuración, se conserva lo que ya hayas guardado. Las instalaciones de Hermes dentro de WSL o Docker requieren ejecutar PandApply en ese mismo entorno o configurar el puente correspondiente; el instalador del host no las conecta automáticamente.

## Getting started con OpenClaw — incoming

La integración con OpenClaw está prevista y todavía no está disponible. No requiere instalación ni configuración por ahora. El asistente identifica esta opción como «próximamente»; Hermes es el motor disponible para esta versión.

## Instalación manual para desarrollo

Requiere Python 3.11 o posterior y un entorno virtual exclusivo para PandApply. En PowerShell (Windows):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
pandapply doctor --json
pandapply setup --dry-run
pandapply setup
python -m pytest -q
```

En Linux:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
pandapply doctor --json
pandapply setup
python -m pytest -q
```

Activa `.venv` cada vez que abras una terminal para usar `pandapply`. Si PowerShell impide activar scripts, puedes ejecutar directamente `.\.venv\Scripts\pandapply.exe` sin activar el entorno. PandApply rechaza ejecutarse desde un Python compartido; también se puede instalar en un entorno aislado administrado por `pipx` o `uv`. Los datos guardados se conservan fuera del entorno virtual.

`doctor` no modifica archivos. `setup` abre el asistente en una terminal interactiva; `setup --wizard` lo fuerza y `setup --non-interactive` conserva el informe JSON para scripts. Inicializa una base SQLite local y puede repetirse. Detecta una instalación existente de Hermes y completa las rutas de su entorno Python y Google Workspace cuando puede identificarlas. Los datos se guardan en `%LOCALAPPDATA%/PandApply` en Windows o en `$XDG_DATA_HOME/pandapply` (por defecto `~/.local/share/pandapply`) en Linux. No se necesitan credenciales para trabajar localmente.

Si Gmail y WhatsApp ya están configurados en Hermes, el setup informa de la autorización y sesión detectadas sin leer ni copiar sus secretos. La detección no comprueba OAuth ni una conexión activa y no habilita envíos. Respeta `HERMES_HOME` y el perfil activo; si encuentra varias instalaciones, pide especificar `--hermes-home`. También acepta `--hermes-root` y `--hermes-python` para instalaciones fuera de las rutas habituales. `pandapply setup --dry-run` muestra el diagnóstico sin guardar cambios. La detección desde un host Windows no inspecciona automáticamente instalaciones dentro de WSL o Docker.

El asistente resuelve internamente el Python y Google Workspace de Hermes; no pide sus rutas técnicas. Reconoce tanto los entornos tradicionales `.venv`/`venv` como el entorno seleccionado por el administrador de paquetes de Hermes bajo `installs`. Si esa instalación está incompleta o no es compatible, deja Gmail pendiente con un mensaje y permite continuar con las funciones locales. Las opciones de rutas anteriores quedan disponibles para configuración avanzada.

Con las rutas detectadas, `pandapply gmail search-real --query CONSULTA` ya no necesita repetirlas. Tras guardar la cuenta y consulta en el panel, `pandapply run mail` utiliza esos valores. Las credenciales siguen administradas por Hermes; cambiar el perfil de Hermes después del setup no cambia el perfil guardado en PandApply.

`pandapply setup --verify-gmail` permite comprobar la autorización existente consultando únicamente la identidad de la cuenta en Gmail y guardar su dirección principal. Puede refrescar el token mediante Hermes, pero no inicia un nuevo emparejamiento ni lee mensajes. Si la cuenta difiere de la configurada, conserva esta y devuelve un error. Esta comprobación opcional no se combina con `--dry-run` y no habilita el seguimiento ni las respuestas. Se ha probado con un proveedor simulado; requiere una prueba funcional con la cuenta del usuario.

Para crear un perfil y registrar un CV sin modificar el original:

```sh
pandapply profiles add Backend --timezone UTC
pandapply profiles list
pandapply profiles import-cv ID_DEL_PERFIL ruta/al/cv.pdf
```

Para eliminar un perfil, usa «Eliminar perfil» en el panel o `pandapply profiles delete ID_DEL_PERFIL --confirm`. Se retira de las búsquedas y de la lista habitual; se conservan sus postulaciones, evidencias y archivos CV. `pandapply profiles list --all` permite consultar también los retirados. No se puede eliminar mientras haya una postulación en curso; primero hay que comprobar su resultado.

La importación registra la ruta y el hash del archivo sin modificar el original. El identificador devuelto permite consultar texto con `pandapply profiles extract-cv ID_DEL_DOCUMENTO`. El texto extraído no se incorpora automáticamente a la memoria ni se considera confirmado; los PDF escaneados pueden necesitar OCR y las tablas DOCX no se extraen todavía.

`pandapply config show` muestra los valores locales; `pandapply config set min_match_score 0.8` permite modificar un valor validado. Las modificaciones se guardan como revisiones en SQLite; si existía un `config.json` anterior, sus valores se conservan al crear la primera revisión y después prevalece SQLite. Esta configuración es preliminar y no activa conectores.

Cuando hay una migración pendiente de la base existente, PandApply crea primero una copia SQLite junto a ella. Esa copia contiene datos personales y debe protegerse y mantenerse junto con los demás datos locales.

Para evaluar las vacantes ficticias incluidas, usa `pandapply run discovery --profile ID_DEL_PERFIL --fixture fixtures/jobs.synthetic.json`. El comando solo muestra resultados; agrega `--save` para guardarlos. La evaluación usa restricciones del perfil y evidencia confirmada de la base de datos, y manda los datos insuficientes a revisión manual. No consulta sitios web ni envía postulaciones.

También se pueden importar vacantes obtenidas manualmente y de forma autorizada con `pandapply run discovery --profile ID_DEL_PERFIL --input vacantes.json --save`. El archivo contiene un objeto `jobs` con una lista de objetos que incluyen `title`, `company`, `url` y, opcionalmente, `ats_provider`, `ats_requisition_id`, `skills`, `work_mode` y `salary_usd_month`. Esta vía no consulta las URLs; las vacantes que cumplen el filtro quedan en revisión manual hasta comprobar la política del sitio. `--fixture` está reservado a dominios `.test`.

El grupo `pandapply policy` permite registrar la revisión humana de términos de un dominio, su fuente y vencimiento, registrar un consentimiento específico y consultar una comprobación preliminar. La revisión es una declaración local: PandApply no comprueba automáticamente la página de términos. `PRELIMINARY_ALLOW` no es permiso de envío ni habilita una integración real; todavía faltan los controles y las pruebas del navegador. LinkedIn e Indeed siguen bloqueados para automatización aunque se aporte consentimiento.

Para registrar una habilidad confirmada, ejecuta `pandapply memory propose --profile ID_DEL_PERFIL --skill Python` y revisa el identificador devuelto. Después usa `pandapply memory approve ID_DE_LA_PROPUESTA` o `pandapply memory reject ID_DE_LA_PROPUESTA`. Solo la aprobación crea el dato verificable; la respuesta se aplica únicamente a esa propuesta.

Con al menos una habilidad verificada, `pandapply profiles generate-cv ID_DEL_PERFIL ruta/al/nuevo.pdf` genera un PDF básico con el nombre del perfil y las habilidades verificadas, y registra su trazabilidad. No sobrescribe archivos existentes. Todavía no adapta el CV a una vacante ni produce cartas.

`pandapply export --format json` y `pandapply export --format csv` escriben una copia de la base local en la salida estándar; contienen datos personales y deben guardarse en una ubicación protegida. El CSV contiene una fila por registro con el nombre de la tabla y los datos en JSON. La exportación incluye rutas y hashes de documentos, pero no sus archivos originales ni credenciales externas.

`pandapply web` abre un servidor local en `127.0.0.1:8765`. El enlace lleva a una pantalla de inicio de sesión: introduce el usuario `pandapply` y la contraseña aleatoria mostrada en la terminal, en líneas separadas. La contraseña cambia al reiniciar el panel. La sesión dura hasta 12 horas; puedes terminarla con «Cerrar sesión» y se invalida al reiniciar el servidor. El panel permite consultar la actividad, solicitar sugerencias y aprobar o rechazar decisiones locales; muestra el texto completo y la cuenta antes de enviar una respuesta aprobada. Para detenerlo, usa Ctrl+C. La API sigue aceptando autenticación Basic o Bearer para lecturas y exige Bearer para sus modificaciones. Las decisiones están protegidas contra solicitudes entre sitios y repeticiones. Solo se implementa una parte del contrato de `specs/openapi.yaml`.

Si tenías una pestaña abierta antes de reiniciar el panel, vuelve a abrir `/login` y usa la nueva contraseña de la terminal. Un formulario desactualizado muestra una página de recuperación; su enlace abre un formulario nuevo y no repite la operación anterior. Tras actualizar el código, reinicia el panel para que cargue la corrección.

También puedes consultar `pandapply decisions list` y responder con `pandapply decisions respond ID_DE_LA_DECISIÓN approve` (o `reject`). Las decisiones anteriores limitadas al canal CLI siguen restringidas a ese canal.

## Demo integral simulada

`pandapply demo` crea datos ficticios temporales, evalúa vacantes, genera un PDF, registra una postulación en un ATS local, procesa una entrevista ficticia y simula una respuesta aprobada. La demo aprueba sus propios datos de ejemplo para mostrar el recorrido; no usa perfiles ni cuentas personales, y no contacta Gmail ni portales de empleo. El resultado identifica los recibos y correos como `sandbox-` y `fake-`.

`pandapply sandbox` inicia un ATS local separado en `127.0.0.1:8766` que acepta únicamente correos terminados en `.test`; usa exclusivamente datos y archivos ficticios. Para el flujo manual persistente se dispone de `applications list`, `applications sandbox-prepare`, `applications sandbox-submit --consent` y `applications reconcile`. La conciliación solo consulta el recibo del ATS de prueba y nunca vuelve a enviar.

El envío al sandbox también admite `applications sandbox-submit ID --consent --browser hermes --hermes-python RUTA_PYTHON --hermes-root RUTA_HERMES`. PandApply crea un perfil de navegador temporal, registra el intento antes de enviar y contrasta el recibo con el ATS local. Si el resultado es incierto no reintenta automáticamente. El flujo completo se probó con Hermes 0.23.2 en un contenedor Linux aislado; otras instalaciones pueden necesitar ajustes de navegador y se deben verificar por separado.

Si ya realizaste una postulación manual a una vacante importada, `pandapply applications record-manual ID --receipt-id REFERENCIA --confirm` registra tu confirmación y la referencia observada. PandApply no verifica ese recibo en el portal ni realiza la postulación; registra que el propietario aportó la evidencia.

El flujo de prueba de `pandapply gmail` es **simulado**: `ingest` acepta un JSON de correos `.test`, `suggest-reply` sugiere texto solo cuando se solicita, `draft` crea una propuesta, `approve` o `reject` registra la decisión y `send-approved` utiliza un transporte falso. Una pérdida de confirmación deja el envío en `SEND_UNKNOWN` y bloquea su repetición automática.

Además hay un puente experimental para una instalación ya autenticada de la skill Google Workspace de Hermes: `pandapply gmail search-real --hermes-python RUTA_PYTHON_HERMES --workspace-script RUTA_GOOGLE_API_PY --query CONSULTA` y `gmail get-real` con `--message-id`. Estos comandos muestran datos reales en la terminal si la cuenta está autorizada; Hermes administra las credenciales. `gmail ingest-real` permite indicar el identificador del mensaje, el correo principal de la cuenta, la postulación y una clasificación propuesta; verifica la cuenta autenticada mediante Gmail `getProfile` y crea una decisión pendiente sin cambiar el estado ni guardar el cuerpo del mensaje. El usuario debe revisar el correo y aprobar o rechazar esa decisión en CLI o web. El puente depende de funciones internas observadas en la skill de Hermes 0.23.2 y de su cliente Python de Google; si faltan, falla sin recurrir a otra cuenta. Se ha probado con scripts simulados, pero todavía no con una cuenta real.

Existe además un envío real **experimental y desactivado por defecto**, probado únicamente con un proveedor simulado. Exige habilitar `gmail_enabled` y `gmail_reply_enabled`, desactivar `dry_run`, revisar el correo, crear el borrador con `gmail draft --account CORREO_PRINCIPAL`, aprobarlo y ejecutar `gmail send-approved-real --proposal-id ID --hermes-python RUTA --workspace-script RUTA --confirm`. La aprobación vence a las 24 horas y está vinculada a cuenta, mensaje, destinatario y texto. El proceso vuelve a verificar la cuenta y el correo antes de enviar, registra un intento de un solo uso y no reintenta automáticamente. Hermes necesita autorización de lectura y envío para Gmail. **No se ha validado con una cuenta real.**

Si el resultado es `SEND_UNKNOWN`, `gmail reconcile-real --proposal-id ID --hermes-python RUTA --workspace-script RUTA` busca el identificador del mensaje en la carpeta de enviados y verifica hilo, remitente, destinatario y contenido. Si no encuentra evidencia inequívoca conserva `SEND_UNKNOWN`; no reenvía. Revisar el correo enviado manualmente sigue siendo necesario cuando Gmail no devuelve coincidencia.

`pandapply run mail` ofrece una consulta puntual y limitada mediante ese puente, con `--hermes-python`, `--workspace-script`, `--account-id` y una `--query` explícita de Gmail. Busca identificadores ATS exactos en asunto o extracto y propone una revisión solo si encuentra una coincidencia única y una clasificación reconocible; las demás coincidencias quedan para revisión manual. No cambia el estado sin aprobación ni envía correo. No implementa todavía un cursor completo de Gmail: la consulta debe cubrir una ventana con suficiente solapamiento para no perder mensajes.

Los mensajes ambiguos quedan en una lista persistente del panel para revisarlos en Gmail; también se consultan con `pandapply gmail review-queue` y se marcan revisados con `pandapply gmail mark-reviewed --account-id ID_CUENTA --message-id ID_MENSAJE`. PandApply guarda el identificador del mensaje, una referencia no reversible de la cuenta, el motivo y las fechas de detección; no guarda el cuerpo ni el asunto en esta lista. Marcarlo como revisado lo retira de los pendientes y conserva esa decisión en consultas posteriores.

### Programación experimental con Hermes

`pandapply scheduler install --hermes-executable RUTA_HERMES --hermes-home DIRECTORIO_HERMES --interval "every 20m"` registra una tarea de seguimiento de correo **pausada**. Acepta intervalos de cinco minutos a siete días y utiliza el Python del entorno virtual de PandApply. Requiere un ejecutable y un directorio de Hermes existentes; no inicia el gateway de Hermes ni lo instala. `pandapply scheduler status` muestra el último estado registrado, y `pandapply scheduler pause` pausa la tarea.

Para permitir su activación hay que configurar `gmail_enabled`, desactivar `dry_run` y establecer `gmail_account`, `gmail_query`, `hermes_python` y `hermes_workspace_script` mediante la web, `pandapply config set` o la API local. `pandapply scheduler resume` verifica esos datos y reanuda la tarea; requiere además un gateway de Hermes operativo para que se ejecute. La tarea solo consulta correo y crea propuestas para revisión; no envía respuestas. Si el resultado alcanza el límite configurado, informa `possibly_truncated`: puede haber mensajes sin examinar y es necesario acotar la consulta o revisarlos manualmente. Si una operación queda en estado `UNKNOWN`, `pandapply scheduler reconcile` consulta Hermes sin crear una tarea nueva ni reintentarlo a ciegas. El seguimiento programado todavía no se ha validado con una cuenta Gmail real ni con una ejecución automática del gateway. Los lanzadores Windows `.cmd`, `.bat` y `.ps1` de Hermes aún no están soportados por este adaptador; se puede usar `pandapply run mail` manualmente.

## Estado y límites

Esta entrega incorpora el esquema inicial, detección básica del ejecutable Hermes, deduplicación conservadora, evaluación de fixtures locales, PDF básico y recuperación de intentos inciertos. La presencia de Hermes no implica que sus capacidades estén verificadas. No hay todavía un servicio de envío ni un flujo completo de configuración; la web y la API son parciales. Búsqueda real, generación de documentos adaptados, Gmail, políticas de sitio y conectores reales están pendientes. La licencia para publicación requiere decisión del titular.

La referencia oficial de [comandos Hermes](https://hermes-agent.nousresearch.com/docs/reference/cli-commands) documenta `hermes --version`. Se verificó una imagen Docker aislada; los resultados y límites están en [la nota de verificación](docs/09-HERMES-DOCKER-VERIFICATION.md). Los resultados inciertos de un submit se marcan `SUBMISSION_UNKNOWN` y requieren conciliación, nunca reenvío automático.
