# 02 — Arquitectura técnica de PandApply

## 1. Resumen ejecutivo

**Patrón:** arquitectura hexagonal modular, monousuario y local. **Runtime v1:** Hermes Agent. **Núcleo:** paquete Python instalable con CLI + API HTTP + SQLite + Markdown. **Interacción:** skill de Hermes, Web local, CLI, WhatsApp de Hermes (opcional). **Planificación:** cron de Hermes dispara operaciones idempotentes; el core coordina su estado durable. **Límite fuerte:** PandApply es propietario de datos, decisiones y recibos; Hermes es propietario de conversación, herramientas y sesiones.

No hay backend SaaS. Cada usuario conecta su propio proveedor de LLM y su Gmail localmente. El proyecto distribuye código, esquema, skills y reglas, no tokens.

## 2. Stack propuesto (decisión de diseño, no dependencia existente)

| Capa | Elección | Justificación |
|---|---|---|
| Runtime agente | Hermes Agent | Skill, cron, gateways, navegador, Gmail/Workspace |
| Dominio/CLI | Python >=3.11, Typer, Pydantic | Multiplataforma; Python está cerca de Hermes, CLI tipada |
| Persistencia | SQLite con migraciones Alembic/SQLAlchemy o sqlite3+migrations | Transacciones atómicas, índices, FK y auditoría |
| Datos editables | Markdown UTF-8 y YAML (`yaml.safe_load`) | Transparencia y versionado |
| UI local | FastAPI + Jinja2/HTMX (mínimo) o React si escala | Dashboard ligero que funciona igual en Linux y Windows |
| HTTP | FastAPI, OpenAPI 3.1, auth local | Cliente separado del core; no publicar red por defecto |
| PDF | ReportLab o WeasyPrint (elegir tras prueba Windows) | PDF reproducible con fuentes instaladas, sin inventar datos |
| Extracción CV | pypdf y python-docx | Importación local de PDF/DOCX; no confiar en parsing perfecto |
| Scheduler | Hermes cron + `pandapply run ...` | Sin programador duplicado; recuperación controlada por core |
| Observabilidad | logs JSON con redacción + `application_events` | Reconstrucción de estados y depuración |
| Test | pytest, FastAPI TestClient, fixtures, navegadores en staging | Pruebas de todas las operaciones irreversibles |

> **Decisión importante:** no instalar un segundo agente/daemon LLM. La CLI, API y librerías de PandApply son un *complemento determinista*; Hermes ejecuta el razonamiento y las herramientas que requieren LLM. Un pequeño servidor HTTP local opcional solo alimenta el dashboard.

## 3. Capa de dominio (agnóstica del agente)

```text
pandapply/
  domain/
    entities.py        JobPosting, ProfessionalProfile, Application, MailEvent,
                       MasterDecision, Document, PolicyDecision, Evidence
    states.py          Transiciones explícitas
    policies.py        Evaluación previa a cualquier operación irreversible
    services.py        Deduplicación, scoring, correlación de correos, permisos
  application/
    use_cases.py       Buscar, evaluar, preparar, enviar, revisar Gmail, contestar
    ports.py           Interfaces de LLM, browser, search, Gmail, notify, scheduler
    events.py          Eventos inmutables y outbox
  adapters/
    hermes/            Skill y comandos puente (v1)
    browser/           Hermes CDP, Playwright MCP/Chrome DevTools MCP opcionales
    search/            Google vía browser si permitido; proveedor compatible alterno
    gmail/             Google Workspace (gws/GAPI) como transporte inicial
    storage/           SQLite + archivos
    channel/           Hermes gateway / CLI / web
  interfaces/
    cli/               Typer: pandapply ...
    http/              FastAPI: /api/v1/...
    web/               Plantillas/vistas locales
  assets/templates/    PDF y cartas
  migrations/          Migraciones de esquema
  tests/
```

Las dependencias van hacia el centro: `interfaces -> application -> domain`, y `adapters -> application.ports`. Ni `domain` ni `application` importan módulos de Hermes, `gws`, navegador concreto o proveedor de modelo.

## 4. Puertos/interfaces obligatorios

```python
from typing import Protocol, Sequence

class AgentRuntime(Protocol):
    def capabilities(self) -> set[str]: ...
    def invoke(self, task: dict, *, correlation_id: str) -> dict: ...

class DiscoveryPort(Protocol):
    def search(self, query: dict) -> Sequence[dict]: ...

class BrowserPort(Protocol):
    def inspect(self, url: str) -> dict: ...
    def fill(self, session: str, answers: dict, artifacts: dict) -> dict: ...
    def submit(self, session: str, *, permit_id: str) -> dict: ...
    def receipt(self, session: str) -> dict | None: ...

class GmailPort(Protocol):
    def changes(self, cursor: str | None) -> dict: ...
    def get_thread(self, thread_id: str) -> dict: ...
    def reply(self, thread_id: str, message_id: str, body: str,
              *, approval_id: str, idempotency_key: str) -> dict: ...

class HumanChannel(Protocol):
    def ask(self, question: dict, *, recipient_id: str) -> str: ...
    def notify(self, event: dict, *, recipient_id: str) -> None: ...

class SchedulerPort(Protocol):
    def create_or_update(self, key: str, schedule: str, task: str) -> None: ...
    def pause(self, key: str) -> None: ...
```

Las firmas son **contratos de diseño**, no código listo. Los adaptadores deben convertir a un modelo de datos unificado, incluyendo errores tipados (`AuthExpired`, `RateLimited`, `PolicyBlocked`, `HumanRequired`, `ProviderUnavailable`, `UnknownSubmissionOutcome`).

## 5. Hermes como primera implementación

### Skill

- Distribuir `skills/pandapply/SKILL.md` en el repo final; su frontmatter usa `name: pandapply` y `description` compatible con Hermes.
- El skill instruye al agente **cuándo** usar `pandapply ...`, cómo consultar hechos, cómo tratar correos/páginas como contenido no fiable y cómo invocar permisos.
- Reutilizar la skill oficial Google Workspace de Hermes cuando esté disponible, pero invocar la **API normalizada** de PandApply para grabar los resultados; no permitir que el LLM escriba directo en las tablas.
- La instalación local de skill debe ser compatible con `~/.hermes/skills/` / directorios externos y, más adelante, con skills tap de GitHub.

### Cron

- Configuración instala **dos tareas como máximo al inicio**: `pandapply-discovery` y `pandapply-mail-monitor` con intervalos configurables.
- Cron inicia una ejecución del agente con la skill PandApply y una instrucción estable; invoca los casos de uso del core. No usar cron para disparar un botón submit directamente sin gate de dominio.
- Reconstruir trabajo pendiente desde DB al iniciar cada corrida, usando leases y límites de concurrencia. El scheduler llama; la DB decide si el trabajo ya existe/está ejecutándose.
- Si falta internet, browser o Gmail, registrar `connector_status` y reintento con backoff; el scheduler no crea nuevas filas duplicadas.

### Navegación

Modalidades ofertadas en el asistente (depende de prueba de capacidades de la versión instalada):

1. **Hermes browser local / administrado**: navegador aislado, sesión independiente. Más reproducible; requiere iniciar sesión.
2. **Hermes `/browser connect` por CDP**: navegador Chromium/Chrome/Edge existente, conectado a endpoint local. El comando `/browser connect` es **interactivo CLI**; no fingir que se ejecuta desde chat web/WhatsApp.
3. **Hermes `use_real_profile`**: snapshot/copia del perfil real, reutiliza login. Explicar que NO es necesariamente control de la ventana que el maestro ve.
4. **Opcional** adaptador Playwright MCP `--extension` para pestañas existentes o Chrome DevTools MCP `--autoConnect` para Chrome compatible. Habilitar solo después de detectar y validar cliente MCP y versión; no prometer paridad de herramientas con Hermes.

Para CDP usar **loopback**, puertos efímeros controlados, sin exponer depuración a red, y confirmar identidad del navegador. Con navegador personal, mostrar advertencia de acceso a cuentas y cookies. **No** enganchar un Chrome existente al azar sin consentimiento.

### Gmail

El adaptador `adapters/hermes/guidance.py` abre la CLI interactiva existente para
configurar o reparar Gmail, navegador o WhatsApp. Usa `chat -q`, perfil explícito
y `HERMES_HOME` guardado, sin importar Hermes en el core ni capturar credenciales.
El onboarding reanuda la detección y las pruebas deterministas al regresar. La
implementación de Gmail comprobable hoy requiere el puente Python Google Workspace;
la ayuda no añade automáticamente compatibilidad con otros conectores.

- Primario v1: skill Google Workspace de Hermes, que prefiere `gws` cuando está disponible y puede recurrir a librerías de Google. El *bridge* lee correo mediante la interfaz aprobada por Hermes y pasa mensajes normalizados a `pandapply gmail ingest`.
- La CLI y el core no almacenan refresh tokens; el conector los gestiona. Cualquier resultado de Gmail se persiste en versión mínima (ID de mensaje/hilo, fecha, hash, clasificación, encabezados seleccionados, extracto redactado) y se referencia para consultar el contenido de nuevo.
- Polling por cron; usar cursor de historial/ventana con overlap y deduplicación por `gmail_message_id`; no asumir que la bandeja se entrega una sola vez.
- **MCP remoto oficial** de Gmail queda como adaptador futuro: está en Developer Preview y exige prerequisitos extra. No usarlo como única integración ni tratarlo como ruta garantizada de instalación para todos los usuarios.

### WhatsApp

Utilizar canal oficial de Hermes configurado en self-chat (mismo número) o modo bot según la elección del usuario. Solo remitente autorizado puede emitir decisiones. Si WhatsApp cae, se acumulan notificaciones y el usuario puede responder desde CLI/UI. La app no instala ni necesita `Iron-mind/whatsapp-web-api`.

### Interfaz web

El dashboard de Hermes es útil para chat/admin, pero no sustituye el tablero de seguimiento. PandApply debe ofrecer su **web local** propio para vacantes/decisiones/estado, en Windows y Linux. Su panel de chat opcional puede enviar instrucciones por el API OpenAI-compatible de Hermes si está activo, con clave almacenada en backend local; nunca exponerla al navegador. En Windows, probar si el chat del dashboard Hermes está soportado en la versión exacta y recurrir a la web PandApply/API si no. La documentación oficial de versiones actuales presenta diferencias respecto al PTY/ConPTY: la detección en instalación es obligatoria.

## 6. Separación modelo determinista vs. LLM

| LLM/Hermes | Código PandApply |
|---|---|
| Encontrar y resumir vacantes | Canonicalizar URLs y deduplicar |
| Comprender preguntas del formulario | Verificar tipos/validación y campos obligatorios |
| Matching explicable con evidencias | Aplicar umbral/reglas duras, conservar evidencias |
| Elegir hechos y redactar CV | Verificar claims, generar PDF reproducible |
| Redactar carta/sugerencias de email | Asociar aprobaciones, hash de texto y envío idempotente |
| Clasificar correos | Correlacionar hilo/postulación y confirmar transiciones |
| Preguntar aclaraciones | Crear decisión pendiente con estado, remitente y vencimiento |
| Usar navegador | Verificar permiso por sitio, marcar intento, registrar recibo |

## 7. Condiciones irreversibles y transacciones

**Submit:** antes de pulsar el botón externo, PandApply emite un `SubmissionPermit` con `application_id`, `domain`, `form_fingerprint`, `policy_version`, `expires_at` y nonce. La operación se marca `SUBMITTING` y se registra un `submission_attempt` **en transacción antes del clic**. La respuesta del navegador se convierte en `CONFIRMED` únicamente por comprobante. Si hubo crash entre clic y lectura de comprobante, mantener `SUBMISSION_UNKNOWN` y verificar manualmente/por email. **Nunca reintentar a ciegas.**

**Reply Gmail:** crear `reply_proposal` con `thread_id`, `message_id`, `to`, `body_hash`, `proposed_text`; autorizar `approval` por el maestro, con comprobación de hash antes de enviar. Registrar intento y verificar que la API devolvió ID de mensaje. Fallo de red después de petición → `SEND_UNKNOWN` y consultar hilo/Message-ID, no reenviar automáticamente.

**Memoria:** agregar `memory_proposal`, mostrar diferencia propuesta, autorizar `yes/no`, y solo entonces actualizar Markdown y registrar hash/versión.

## 8. Persistencia y recuperación

- Carpeta por usuario: Linux `~/.local/share/pandapply/` (o `XDG_DATA_HOME`); Windows `%LOCALAPPDATA%\PandApply\` para datos. Config en XDG_CONFIG_HOME o equivalente Windows; **no** depender de `~` en todos los comandos.
- SQLite WAL, FK on y migraciones; copias de respaldo atómicas, rollback de versión y respaldo de archivos Markdown/PDF.
- Locks/leases por `job_id` + TTL, heartbeat y política de expiración. Una tarea recuperada de un worker interrumpido no puede pulsar submit si existe un intento `SUBMITTING`/`UNKNOWN`.
- Eventos append-only, correlaciones por UUID y cada transición con actor, motivo, versión de política, recibo y fecha.
- Outbox para notificaciones; entregar al maestro al reconectar con idempotencia, sin bloquear la transacción de negocio.

## 9. Integración futura OpenClaw

Reemplazar **únicamente** el adaptador de agente (skill/cron/canales/browser) y, si es necesario, Gmail; conservar CLI, dominio, base SQLite, motor de políticas, interfaz web y PDFs. Dejar `runtime` configurable (`hermes` activo; `openclaw` reservado), y usar pruebas contractuales que simulen un `AgentRuntime` mínimo. No mantener dos bases de negocio salvo imposibilidad demostrada.

## 10. Puntos de integración que Codex debe verificar en la máquina objetivo

1. Versión real Hermes y comandos disponibles; la documentación de `main` evoluciona.
2. Alcance de herramientas en sesión normal, cron, gateway y API. No asumir que todos soportan el mismo set.
3. Autenticación Google Workspace con el perfil real del usuario, incluidas expiraciones y permisos send.
4. Si Chrome DevTools MCP necesita Chrome >=144 y permisos de depuración/autoconnect; no hay compatibilidad universal.
5. Si Playwright extension funciona con el cliente MCP disponible dentro de Hermes y sesión normal.
6. Si el dashboard chat Hermes en Windows nativo está disponible en versión instalada; fallback local obligatorio.
7. Reglas del sitio destino para búsqueda/lectura/formularios; entradas prohibidas terminan en revisión manual.

## 11. Vista de despliegue

```text
Equipo maestro (Linux / Windows)
 ├─ Hermes Agent (+ skills, gateway, cron, LLM configurable)
 │    ├─ WhatsApp opcional
 │    ├─ Browser CDP / perfil local / MCP opcional
 │    └─ Google Workspace skill (Gmail OAuth)
 ├─ PandApply CLI, web local (127.0.0.1) y API
 │    ├─ core de políticas, orquestación idempotente
 │    ├─ SQLite: aplicaciones, jobs, mensajes, auditoría
 │    └─ Markdown + CV originales + PDF generados
 └─ Chrome/Edge del maestro (si eligió reutilizar navegador)

Externo: buscador autorizado, páginas ATS permitidas, Gmail y proveedor LLM
```
