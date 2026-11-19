# 03 — Flujos, decisiones y estados

## 0. Onboarding y piloto del propietario

El orden requerido es instalación aislada → detección de Hermes y perfil → validación
SQLite → cuenta/filtro Gmail → perfiles/CV → selección de perfiles de búsqueda y
preferencias → cupos/frecuencia → resumen de pendientes → piloto WhatsApp → panel.
El panel se ofrece al final, después de configurar las integraciones. Por defecto
se inicia en segundo plano y devuelve el control de la terminal; el modo en primer
plano queda disponible para diagnóstico.
Un cupo guardado no habilita envíos y una frecuencia guardada no crea un cron por sí sola.

El piloto pregunta «Hola, soy PandApply. ¿Quieres que ejecutemos la primera búsqueda
de vacantes?». El saludo necesita destino propio confirmado, intento persistido,
recibo y manejo UNKNOWN sin reenvío ciego. Su recepción no es autorización de búsqueda:
se requiere una respuesta afirmativa autenticada y vinculada al piloto. El alcance
completo y los componentes pendientes están en [10-OWNER-REQUIREMENTS.md](10-OWNER-REQUIREMENTS.md).

## 1. Flujo A — búsqueda y postulación automática

**Precondiciones:** configuración validada; consentimiento explícito `auto_apply_enabled=true`; perfiles y límites disponibles; conector Google/search sano; navegador probado; fuentes/permisos habilitados.

1. Hermes cron o el maestro invoca `pandapply run discovery` con `run_id`.
2. Core crea/reutiliza `job_runs`; reserva `profile_id`, aplica cuotas por día, horario y presupuesto.
3. Agente construye consultas Google a partir de preferencias. La búsqueda solo opera si el método es permitido; proveedor alternativo configurado si falla. Registrar query, fuente, timestamp y enlaces.
4. Core normaliza URL, ATS req ID y llave semántica; inserción de vacante es idempotente. Vacantes ya postuladas -> `SKIPPED_DUPLICATE`.
5. Hermes navega al anuncio y al formulario, extrae campos, restricciones, requisitos, descripción, ubicación, salarios y capturas mínimas. No seguir contenido de página que intente instruir al agente.
6. Un matching **explicable** emite `matching_score` y justificaciones respaldadas por Markdown/CVs; reglas duras prevalecen sobre el score. Si rechazo, `SKIPPED_INELIGIBLE`.
7. Antes de seguir, evaluar `SitePolicy` (términos, robots donde aplique, consentimiento y modo). Si bloqueo o no verificado -> `MANUAL_REVIEW` sin enviar.
8. Buscar CV exacto compatible. Si no, generar un PDF adaptado **solo con claims verificados**; adjuntar evidencia/plantilla/hash. Generar carta solo si es solicitada o útil para el formulario y está permitida.
9. Resolver preguntas del formulario usando hechos documentados. Ambigüedades -> registrar `MasterQuestion`, notificar al maestro, mover a `WAITING_USER`. El workflow no expira ni inventa respuesta.
10. La respuesta del maestro se valida y puede originar una propuesta de memoria; memorizar **solo** si el maestro aprueba el texto de persistencia.
11. Guardar snapshot de formulario; comprobar política, cupo, datos y permisos; producir `SubmissionPermit` breve.
12. `submission_attempt` transaccional con estado `SUBMITTING`; Hermes completa campos, adjunta PDF y activa submit una sola vez. Captchas no se solucionan por evasión y requieren asistencia manual legítima.
13. Si aparece recibo inequívoco, guardar identificador/URL/fecha y estado `SUBMITTED`; si no hay evidencia, `SUBMISSION_UNKNOWN`, suspender reintento y avisar.
14. Registrar evento, actualizar cuota diaria solo por envío confirmado (y contar tentativas para anti-spam según política), notificar según preferencias.

**Errores:** URL caída -> reintento de lectura; autorización/SSO vencidos -> `WAITING_AUTH`; cuota consumida -> `DEFERRED`; sitio restringido -> `MANUAL_REVIEW`; submit ambiguo -> `SUBMISSION_UNKNOWN`; servidor de email caído no revierte un submit confirmado.

## 2. Flujo B — Gmail seguimiento

1. Hermes cron ejecuta `pandapply run mail` (o bridge de Gmail). Cursor con solapamiento y deduplicación por `gmail_message_id`.
2. Consultar correos recientes con autorización mínima, evitar leer toda la bandeja indiscriminadamente; filtrar por remitentes, asuntos y ventanas de postulaciones, manteniendo opción de revisar coincidencias dudosas.
3. Clasificar con resultados estructurados: `application_received | rejection | next_step | interview | offer | unrelated | ambiguous`; score/confidence y evidencia de asunto/cuerpo.
4. Correlacionar por `thread_id`, `reply-to`, referencias externas, nombre/empresa, timestamp y, si está disponible, un identificador de ATS; no elegir relación por nombre parecido sin umbral suficiente.
5. `application_received`: agregar evento y, por defecto, no notificar.
6. `rejection`: marcar aplicación `REJECTED` **solo** cuando correlación y clasificación sean confiables; caso ambiguo -> decisión pendiente.
7. `next_step`, `interview`, `offer`: actualizar estado, resumir correo al maestro, preguntar «¿Quieres sugerencias de respuesta rápida?».
8. Si maestro responde **no**, no redactar ni enviar; conservar evento. Si **sí**, generar 2–3 borradores que contesten el correo real.
9. Maestro elige propuesta o dicta un texto exacto. Convertir en `ReplyApproval` vinculado al hilo, mensaje objetivo y hash. Mostrar destinatarios antes de confirmar si hay ambigüedad.
10. Enviar una vez desde Gmail manteniendo hilo/encabezados, guardar ID remitido y notificar. **Nunca** responder automáticamente basándose únicamente en un correo.

**Protección:** cuerpo de email no puede ordenar al sistema que cambie preferencias, ejecute código, contacte terceros ni modifique permisos; se procesa como dato no confiable.

## 3. Flujo C — corrección de perfil/memoria

1. Maestro proporciona información nueva en respuesta a pregunta (ej. «sí, tengo 3 años con Node.js»).
2. El sistema la utiliza **para la tarea actual** como dato proporcionado por el propietario, y ofrece guardarla indicando documento y sección sugeridos.
3. Maestro contesta sí/no a un `memory_proposal_id`, no a un mensaje suelto ambivalente.
4. Si sí, se persiste un claim con fuente `master_confirmed`, timestamp, versión y ámbito; si no, se cancela la propuesta. Nunca actualizar automáticamente una skill de Hermes como sustituto de aprobación.
5. Si altera datos clave, recalcular matching/documentos **antes de un nuevo envío**, sin modificar solicitudes ya enviadas.

## 4. Máquina de estados de una candidatura

```text
DISCOVERED
  -> EXTRACTED              [anuncio y formulario interpretados]
  -> SKIPPED_DUPLICATE      [ya aplicada o vacante idéntica]
  -> SKIPPED_INELIGIBLE     [no cumple reglas duras]
EXTRACTED
  -> MATCHED                [perfil cumple umbral]
  -> MANUAL_REVIEW          [sitio sin permiso, captcha, términos dudosos]
  -> SKIPPED_INELIGIBLE
MATCHED
  -> PREPARING              [PDF, carta y respuestas]
PREPARING
  -> READY_TO_SUBMIT        [todos los datos y autorización general]
  -> WAITING_USER           [preguntas sin respuesta]
  -> WAITING_AUTH           [browser/correo no autenticados]
  -> MANUAL_REVIEW          [portal requiere intervención manual]
WAITING_USER | WAITING_AUTH -> PREPARING [cuando resuelto]
READY_TO_SUBMIT
  -> SUBMITTING             [permiso efímero y intento registrado]
  -> DEFERRED               [límite o franja horaria]
  -> MANUAL_REVIEW          [política bloquea]
SUBMITTING
  -> SUBMITTED              [recibo verificable]
  -> SUBMISSION_UNKNOWN     [resultado incierto: NO auto-retry]
SUBMISSION_UNKNOWN
  -> SUBMITTED              [comprobación manual/Gmail posterior]
  -> MANUAL_REVIEW          [requiere intervención]
SUBMITTED
  -> ACKNOWLEDGED           [confirmación automática de recepción]
  -> IN_PROCESS             [recruiter/ATS pide más pasos]
  -> INTERVIEW              [entrevista programable/solicitada]
  -> REJECTED               [rechazo confirmado]
  -> OFFER                  [oferta]
ACKNOWLEDGED | IN_PROCESS | INTERVIEW
  -> IN_PROCESS | INTERVIEW | REJECTED | OFFER [con transiciones validadas]
OFFER -> CLOSED             [cerrado por maestro]
REJECTED -> CLOSED          [historial conservado]
```

Estados de seguimiento **distintos** de estados de preparación para evitar transiciones imposibles. Se recomienda implementar `application.phase` (`DISCOVERY`, `PREPARATION`, `SUBMISSION`, `TRACKING`, `CLOSED`) y `application.status` enums; el esquema incluye ambos. Cada transición requiere evento, actor, fecha y evidencia.

## 5. Máquina de estados de correo saliente

`NEW_EVENT → NOTIFIED → SUGGESTIONS_OFFERED → DRAFT_SELECTED → APPROVED → SENDING → SENT`; variantes `DECLINED`, `WAITING_USER`, `SEND_UNKNOWN`, `FAILED`. `APPROVED` solo a partir de una decisión del maestro identificada en sesión/identidad. Un texto generado por el LLM nunca habilita `APPROVED`.

## 6. Recuperación ante fallos

| Situación | Respuesta |
|---|---|
| Crash antes de guardar vacante | Descubrir nuevamente y dedupe |
| Crash durante preparación PDF | Archivo temporal y rename atómico, verificar checksum |
| Crash antes del clic submit | Si no existe intento, revalidar desde READY |
| Crash después del clic submit | `SUBMISSION_UNKNOWN`; verificar recibo/ATS/Gmail, jamás reintentar a ciegas |
| Gmail envía respuesta pero se corta conexión | `SEND_UNKNOWN`, buscar ID en hilo antes de decidir |
| Token Gmail vencido | Marcar degradación y pedir reconexión, no borrar cursor |
| WhatsApp desconectado | Outbox en espera; CLI/web accesibles |
| Browser CDP desconectado | Pausar tareas browser y pedir reconectar |
| Maestro no responde | Esperar con fecha límite configurable; no inventar respuesta |
| Portal pide captcha/2FA | Pausar, notificar y completar humano, nunca bypass |
| Servicio no permite automatización | `MANUAL_REVIEW` sin submit |
| Dos cron simultáneos | DB unique + lease + secuencia de transición transaccional |

## 7. Casos de aceptación extremo a extremo

**AT-01:** el usuario configura 2 perfiles, carga 3 CV, ejecuta 1 búsqueda simulada de 4 vacantes: 1 duplicada, 1 fuera de salario, 1 apta con formulario permitido, 1 con captcha. Debe enviar solo la permitida y registrar motivos de todas.

**AT-02:** falta respuesta sobre disponibilidad de traslado; la tarea espera, el maestro responde por WhatsApp, aprueba guardarla; la tarea continúa y queda reflejada en Markdown.

**AT-03:** recibo externo desaparece tras el clic; ningún segundo submit ocurre en 3 reintentos de cron; la tarea queda `SUBMISSION_UNKNOWN`.

**AT-04:** Gmail recibe confirmación de candidatura, rechazo de otra y solicitud de entrevista. Actualiza estados correctos; ignora notificación normal para el maestro, pregunta por respuesta rápida para entrevista. Tras selección, envía exactamente una respuesta.

**AT-05:** envío simultáneo desde dos sesiones con el mismo `job_id` produce una sola aplicación y un único intento autorizado.

**AT-06:** reinicio de Windows/Linux después de una aprobación de memoria no altera otras propuestas; no hay leakage de secretos en logs.
