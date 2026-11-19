# 04 — Modelo de datos, configuración y contratos de PandApply

El panel HTML incluye `GET /login` y `POST /login` para iniciar sesión con el usuario
`pandapply` y la contraseña temporal de la terminal. La sesión se guarda en una cookie
opaca HttpOnly y SameSite=Strict, caduca a las 12 horas y no sobrevive al reinicio
del servidor. `POST /logout` la revoca. Los formularios de login, logout y operaciones
del panel exigen Origin local y token CSRF. Estas rutas HTML están fuera del prefijo
`/api/v1`; las modificaciones de la API siguen exigiendo Bearer, aunque el navegador
tenga una sesión válida.

Los fallos de validación de formularios HTML conservan el estado HTTP 403 y ofrecen
una página para volver a abrir el formulario, sin mostrar datos enviados ni repetir
la operación. La política `Referrer-Policy: same-origin` permite que el navegador
conserve el origen en los POST nativos locales; `Origin: null` y tokens inválidos
siguen bloqueados. Las respuestas de error de la API conservan su formato JSON.

La configuración local de onboarding incorpora `search_profile_ids` (IDs de perfiles
seleccionados), `search_interval_minutes` (5–10080), `max_results_per_run` (1–100),
`max_confirmed_submissions_per_day` (0–1000), `hermes_executable` y
`whatsapp_owner_jid` (destino personal confirmado). Los criterios de búsqueda se
guardan en las preferencias del perfil; no crean claims profesionales confirmados.
El saludo piloto usa `event_outbox`, tipo `PILOT_INVITATION`, con intento previo
`SENDING`, recibo `SENT` o resultado `UNKNOWN`. El payload de auditoría contiene
el hash del destino, no el número. Un intento previo impide repetir el saludo.

`preferences.work_mode` conserva el formato de texto para una modalidad y admite
una lista para varias (`[remote, hybrid]`). `null` o la entrada `any` representan
ausencia de restricción. El asistente y el panel aceptan separadores por coma y la
conjunción «y», y normalizan remoto/híbrido/presencial. El evaluador aplica coincidencia
con cualquiera de las modalidades seleccionadas. Si hay filtro y la modalidad de
la vacante falta o es desconocida, exige revisión manual.

`DELETE /api/v1/profiles/{id}` retira lógicamente un perfil (`active=false`), actualiza
la selección de búsqueda en una misma transacción y conserva sus relaciones. Requiere
Bearer y admite `if_version` para detectar ediciones concurrentes. Repetirlo no añade
otro evento. `GET /profiles` excluye retirados; `include_inactive=true` los incluye.
Los formularios HTML de eliminación usan confirmación explícita, CSRF y versión.

La configuración añade `browser_mode` (`not_configured`, `hermes_managed`, `cdp`),
`browser_cdp_endpoint` y `hermes_root`. `connector_health.browser` registra
`not_checked`, `unavailable`, `cdp_reachable` o `sandbox_verified`. Estos dos últimos
estados describen solo la prueba local ejecutada y no conceden permiso de envío real.

El asistente configura `gmail_poll_interval_minutes` (5–10080), `gmail_poll_limit`,
`gmail_enabled` y `gmail_reply_enabled` a partir de la cuenta guardada. Conserva
`dry_run`; guardar permisos no crea intentos de respuesta ni tareas. Al instalar
el cron, su intervalo predeterminado toma el valor guardado por el asistente.

El proceso de panel en segundo plano mantiene sus sesiones en memoria. Usa un token
de control propio en `panel-control.json`, protegido por los permisos del directorio
del usuario y modo 0600 en POSIX; no es la contraseña del login y no permite leer datos
del panel. El hijo recibe su contraseña por stdin y no la registra en archivos ni argv.
Los endpoints privados `/_panel/status` y `/_panel/stop` solo existen en ese modo y
exigen el token de control, rechazan peticiones de navegador con Origin y no forman
parte de `/api/v1`. No se detienen procesos ajenos mediante un PID tomado del archivo.

## 1. Estrategia de persistencia

**SQLite** es la fuente de verdad transaccional para vacantes, postulaciones, ejecución, decisiones, deduplicación, correos y auditoría. **Markdown** almacena conocimiento profesional transparente y modificable. **Archivos PDF/DOCX** se leen como fuentes (originales inmutables); **PDF generados** son artefactos derivados. Configuración YAML local se valida con Pydantic.

El diseño evita transacciones distribuidas ficticias con Gmail o la web: se usan intentos/recibos/outbox y estados `UNKNOWN`.

## 2. Tablas mínimas (DDL de referencia)

```sql
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE master_profile (
  id TEXT PRIMARY KEY,
  display_name TEXT,
  timezone TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE professional_profiles (
  id TEXT PRIMARY KEY,
  master_id TEXT NOT NULL REFERENCES master_profile(id),
  name TEXT NOT NULL,
  preferences_json TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE knowledge_claims (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL REFERENCES professional_profiles(id),
  claim_type TEXT NOT NULL,
  claim_json TEXT NOT NULL,
  source_uri TEXT NOT NULL,
  source_hash TEXT,
  verification_status TEXT NOT NULL CHECK (verification_status IN ('master_confirmed','document_supported','unverified','disputed')),
  approval_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE documents (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL REFERENCES professional_profiles(id),
  kind TEXT NOT NULL CHECK (kind IN ('cv_original','cv_generated','cover_letter','other')),
  file_path TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  mime_type TEXT NOT NULL,
  source_document_ids_json TEXT NOT NULL DEFAULT '[]',
  claim_ids_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL
);
CREATE TABLE search_runs (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL REFERENCES professional_profiles(id),
  search_provider TEXT NOT NULL,
  query_json TEXT NOT NULL,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  error_code TEXT
);
CREATE TABLE job_postings (
  id TEXT PRIMARY KEY,
  canonical_url TEXT,
  ats_provider TEXT,
  ats_requisition_id TEXT,
  fingerprint TEXT NOT NULL,
  title TEXT NOT NULL,
  company_name TEXT NOT NULL,
  location TEXT,
  description_text TEXT,
  source_url TEXT NOT NULL,
  discovered_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  UNIQUE(fingerprint)
);
CREATE UNIQUE INDEX job_posting_ats_unique
  ON job_postings(ats_provider, ats_requisition_id)
  WHERE ats_provider IS NOT NULL AND ats_requisition_id IS NOT NULL;
CREATE TABLE applications (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL REFERENCES professional_profiles(id),
  job_posting_id TEXT NOT NULL REFERENCES job_postings(id),
  phase TEXT NOT NULL,
  status TEXT NOT NULL,
  match_score REAL,
  match_explanation_json TEXT,
  policy_version TEXT,
  selected_cv_id TEXT REFERENCES documents(id),
  cover_letter_id TEXT REFERENCES documents(id),
  applied_at TEXT,
  receipt_uri TEXT,
  receipt_ref TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  UNIQUE(profile_id, job_posting_id)
);
CREATE TABLE submission_attempts (
  id TEXT PRIMARY KEY,
  application_id TEXT NOT NULL REFERENCES applications(id),
  idempotency_key TEXT NOT NULL UNIQUE,
  permit_json TEXT NOT NULL,
  attempt_status TEXT NOT NULL CHECK (attempt_status IN ('PREPARED','SUBMITTING','CONFIRMED','UNKNOWN','FAILED_PRE_CLICK')),
  external_receipt TEXT,
  initiated_at TEXT NOT NULL,
  completed_at TEXT
);
CREATE TABLE mailbox_messages (
  id TEXT PRIMARY KEY,
  gmail_account_id TEXT NOT NULL,
  gmail_message_id TEXT NOT NULL,
  gmail_thread_id TEXT NOT NULL,
  sender TEXT,
  subject_redacted TEXT,
  sent_at TEXT NOT NULL,
  classification TEXT,
  confidence REAL,
  application_id TEXT REFERENCES applications(id),
  correlation_confidence REAL,
  processed_at TEXT,
  UNIQUE(gmail_account_id, gmail_message_id)
);
CREATE TABLE gmail_cursors (
  gmail_account_id TEXT PRIMARY KEY,
  last_history_id TEXT,
  last_poll_at TEXT,
  overlap_start_at TEXT
);
CREATE TABLE reply_proposals (
  id TEXT PRIMARY KEY,
  mailbox_message_id TEXT NOT NULL REFERENCES mailbox_messages(id),
  recipient TEXT NOT NULL,
  text_body TEXT NOT NULL,
  text_sha256 TEXT NOT NULL,
  state TEXT NOT NULL,
  approved_by_decision_id TEXT,
  sent_gmail_message_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE master_decisions (
  id TEXT PRIMARY KEY,
  decision_type TEXT NOT NULL,
  related_entity_type TEXT NOT NULL,
  related_entity_id TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  decision_status TEXT NOT NULL CHECK (decision_status IN ('PENDING','APPROVED','REJECTED','EXPIRED','CANCELLED')),
  authorized_channel TEXT,
  authorized_principal TEXT,
  decided_at TEXT,
  expires_at TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE application_events (
  id TEXT PRIMARY KEY,
  application_id TEXT NOT NULL REFERENCES applications(id),
  event_type TEXT NOT NULL,
  from_status TEXT,
  to_status TEXT,
  actor_type TEXT NOT NULL,
  actor_id TEXT,
  correlation_id TEXT NOT NULL,
  evidence_ref TEXT,
  payload_redacted_json TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE job_locks (
  key TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL,
  locked_until TEXT NOT NULL,
  heartbeat_at TEXT NOT NULL
);
CREATE TABLE event_outbox (
  id TEXT PRIMARY KEY,
  event_type TEXT NOT NULL,
  payload_redacted_json TEXT NOT NULL,
  destination TEXT NOT NULL,
  delivery_status TEXT NOT NULL,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  delivered_at TEXT
);
CREATE TABLE connector_health (
  connector_id TEXT PRIMARY KEY,
  state TEXT NOT NULL,
  checked_at TEXT NOT NULL,
  detail_redacted TEXT
);
```

**Migraciones requeridas:** índice adicional `(applications.status, updated_at)`, `(mailbox_messages.gmail_thread_id)`, `(application_events.application_id, created_at)`. Verificar lógica de unicidad de `fingerprint`: si dos anuncios comparten empresa/título pero son distintos req IDs, no fusionarlos; preferir ID ATS, luego URL normalizada, luego heurística **con revisión**. Un hash semántico no puede considerarse prueba absoluta.

### Propuesta de jerarquía de Markdown

```text
<DATA_HOME>/knowledge/
  master.md                 # Datos de contacto aprobados, referencias
  profiles/
    backend-node.md         # Perfil resumido, preferencias y evidencias
    fullstack.md
  experiences/
    company-2019-2022.md   # Un hecho/periodo por registro legible
  projects/
    project-a.md            # Descripción y resultados verificables
  skills.md                 # Herramientas y niveles confirmados
  approved-facts.jsonl     # append-only opcional de origen y aprobación
<DATA_HOME>/original-cv/   # symlinks o paths autorizados; no copiar sin motivo
<DATA_HOME>/generated/     # PDF con nombre+ID, no nombres sensibles en URL
<DATA_HOME>/pandapply.db
```

**No escribir automáticamente Markdown por parsing sin aprobación.** El CV PDF/DOCX puede servir como evidencia documental, pero afirmaciones potencialmente ambiguas pasan por verificación humana. No incluir información sensible de terceros en logs.

## 3. Contrato de perfiles y configuración (plantilla en `/config/pandapply.example.yaml`)

- `runtime`: `hermes` inicialmente; `openclaw` reservado.
- `master`: zona horaria, locale, identidad y canal seguro.
- `search`: proveedor Google seleccionado, plan B, consultas, frecuencia, límites.
- `profiles`: múltiples identidades profesionales de un mismo maestro, criterios obligatorios y preferencias.
- `browser`: modo, endpoint CDP (loopback), permisos sobre perfil.
- `gmail`: polling, cuenta, scopes autorizados, política de lectura/envío.
- `channels`: cli, web, whatsapp con binding al principal maestro.
- `autonomy`: límites y allowlist por sitio, `dry_run`, selector de envío.
- `storage`: ruta de DB, conocimientos, documentos, retención.

Para la CLI, validar la configuración antes de habilitar cualquier scheduler. Guardar versiones, emitir checksum por cambio y registrar `config_changed` sin claves.

## 4. API HTTP local (OpenAPI en `/specs/openapi.yaml`)

Base `/api/v1`. Auth token local, origin/CSRF protection si hay cookies, bind `127.0.0.1`; dar soporte a `localhost` de forma segura. Operaciones:

| Método / ruta | Uso |
|---|---|
| `GET /health` | Salud del core y adaptadores |
| `GET /config` | Configuración redactada |
| `PATCH /config` | Reconfigurar con validación y versionado |
| `GET /profiles` | Perfiles profesionales |
| `POST /profiles` | Crear perfil |
| `GET /jobs` | Vacantes descubiertas, filtros |
| `GET /applications` | Historial de postulaciones, paginado |
| `GET /applications/{id}` | Detalle con evidencia redaccionada |
| `POST /runs/discovery` | Ejecutar ciclo (modo simulado o productivo) |
| `POST /runs/mail` | Consultar/ingestar correos |
| `GET /decisions` | Decisiones pendientes del maestro |
| `POST /decisions/{id}/respond` | Sí/no, selección o texto firmado por sesión |
| `POST /applications/{id}/reconcile` | Investigar estado desconocido (no reenvío) |
| `GET /events` | Auditoría paginada |
| `POST /system/pause` | Pausar tareas y autoplay |
| `POST /system/resume` | Reanudar según configuración |
| `GET /connectors` | Estado de integraciones |

**Idempotency-Key** obligatorio en mutaciones de ejecución/respuesta si originan acciones externas; la API responde `409` a conflictos de transición y `423` si hay lock activo. `POST /decisions/{id}/respond` no acepta otro maestro ni otro texto tras decisión final.

### Modelo de respuesta ejemplo

```json
{
  "application_id": "app_123",
  "posting_id": "job_456",
  "status": "SUBMISSION_UNKNOWN",
  "phase": "SUBMISSION",
  "next_action": "RECONCILE_EXTERNAL_RECEIPT",
  "retriable": false,
  "evidence": ["attempt:att_789"],
  "last_updated": "2026-11-17T16:00:00-05:00"
}
```

## 5. CLI propuesta (contrato funcional; NO comandos existentes)

```text
pandapply setup [--resume] [--dry-run]
pandapply doctor [--json]
pandapply config show|edit|set
pandapply profiles list|add|edit|import-cv
pandapply run discovery [--profile ID] [--dry-run]
pandapply run mail [--dry-run]
pandapply applications list|show|reconcile
pandapply decisions list|respond <id> <choice_or_text>
pandapply gmail ingest --input path_or_stdin
pandapply gmail suggest-reply --message-id ID
pandapply gmail send-approved --proposal-id ID
pandapply memory propose|approve|reject
pandapply scheduler install|status|pause|resume
pandapply web [--host 127.0.0.1] [--port 8765]
pandapply pause|resume
pandapply export --format json|csv
```

Commands `run`, `gmail ingest`, `gmail send-approved` son usados por la skill Hermes y validan permisos dentro del core. `setup` detecta capacidades del runtime, no las asume.

## 6. Protocolo entre skill Hermes y core

1. Hermes usa herramientas web/browser/email para obtener **datos estructurados**.
2. Estandariza input como `JobCandidate`, `FormInspection`, `GmailEnvelope`, `LLMClassification`, `MasterResponse`.
3. Invoca `pandapply ...` con JSON por archivo temporal o stdin, **no** shell interpolado con texto web/email; validador Pydantic y tamaño máximo.
4. Core responde JSON tipado `OK|HUMAN_REQUIRED|POLICY_BLOCKED|DEFERRED|RETRYABLE_ERROR|UNKNOWN_EXTERNAL_OUTCOME`; solo un `OK` con permiso autoriza operar externamente.
5. Hermes no puede bypass: backend controla emisión y verificación de permit, firma/HMAC local si aplica. Emitir permit sin verificar configura bug crítico.
6. Después de acción externa, Hermes devuelve recibo normalizado; el core cierra intento o lo deja desconocido.

## 7. Límite de retención y privacidad

Propongo: evidencia de navegación con metadatos mínimos; no guardar screenshots por defecto; los textos de Gmail completos se procesan transitoriamente, conservando IDs y extractos redaccionados; backups locales cifrados cuando contengan datos privados. La retención se configura en setup, exportación y borrado deben incluir anexos generados. SQLite no debe contener OAuth tokens ni contraseñas.
