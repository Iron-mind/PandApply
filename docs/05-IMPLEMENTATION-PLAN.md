# 05 — Roadmap ejecutable para Codex

**Enfoque:** desarrollar flujo completo de v1 en entregas verticales, con mocks en primer lugar, conectores reales después y todos los envíos externos detrás de un gate de política. Cada fase debe dejar tests, migraciones, README y comandos demostrables. No pedir credenciales reales para tests.

## 0. Preparación y verificación de Hermes (P0)

**T0.1** Crear proyecto Python con `pyproject.toml`, lint (`ruff`), type-check, pytest, GitHub Actions Linux/Windows, MIT provisional (confirmar titular licenciante); `pre-commit` y `.gitignore` para secretos/datos.

**T0.2** Construir matriz de capacidades `HermesAdapter.capabilities`: skill loader, cron, gateway/WhatsApp, browser managed/CDP/real profile, Google Workspace, API server y dashboard. Implementar detección real, pruebas automatizadas por fixtures y documentación de versión mínima confirmada; no codificar comandos especulativos como estables.

**T0.3** Crear repositorio con puertos/adaptadores. Un `FakeAgentRuntime` permitirá tests sin invocar LLM ni Hermes.

**Entregable:** `pandapply doctor` de solo lectura, tabla de capacidades y errores accionables. **Aceptación:** tests Linux y Windows sin Hermes y con Hermes mock; no falla por WhatsApp ausente.

## 1. Estado local, configuración y CLI (P0)

**T1.1** Entidades/estados Pydantic, errores tipados, directorios XDG/Windows, migraciones SQLite con WAL/FK, transacciones y outbox.

**T1.2** Implementar `pandapply setup`, `config show/edit/set`, perfiles, importación de CV PDF/DOCX, validaciones y políticas de datos confirmados; sin modificación de originales.

**T1.3** `pandapply web` con FastAPI/HTMX (pantallas de resumen, vacantes, aplicaciones, decisiones, configuración y health), token local y CORS/CSRF; API descrita en `specs/openapi.yaml`.

**T1.4** Registrar un evento por transición; pruebas de coherencia y migración hacia atrás. Un usuario puede exportar datos sin tener configurado Gmail.

**Entregable:** CLI y dashboard local navegables con fixtures. **Aceptación:** `pytest -q` + prueba Windows/Ubuntu; instalar, crear perfil, importar 2 CV, reiniciar y encontrar todo.

## 2. Descubrimiento y evaluación (P0)

**T2.1** `DiscoveryPort` y `GoogleBrowserProvider`, traducir perfiles a consultas configurables. Verificar condiciones de uso; cuando no se autorice acceso automatizado registrar bloqueo y ofrecer proveedor licenciado/manual sin bypass.

**T2.2** `JobPosting` normalize + `JobDedupeService`. ATS ID > URL canónica > similitud con validación. Pruebas de anuncios similares no idénticos.

**T2.3** `VacancyInspector` detecta descripción, formulario y requisitos con el browser de Hermes. Convertir a `FormInspection` estructurado y versión de snapshot.

**T2.4** `MatchEvaluator` con razones/citas y filtros duros. Score es señal; nunca anula restricciones de ubicación/salario/empresa. Solo conocimiento aprobado o evidencia verificable.

**Entregable:** buscar -> guardar -> evaluar -> ver en dashboard, sin postular aún. **Aceptación:** 4 fixtures con una duplicada, una incompatible, una apta y una ambigua clasificadas correctamente.

## 3. CV, carta, maestro y memoria (P0)

**T3.1** Parser PDF/DOCX, extracción y claims con referencia de origen (archivo, página si disponible, hash), detección de contradicciones y verificación por el maestro.

**T3.2** `CVSelector` escoge CV original exacto o `CVRenderer` genera PDF nuevo. Renderer aísla plantilla del contenido, produce PDF legible con validación PDF/A opcional (no obligatoria). Guardar hash y links de evidencia.

**T3.3** `MasterDecisionService` conecta preguntas/decisiones vía outbox, CLI, web y Hermes chat; autorización con principal, caducidad y token/contexto.

**T3.4** `KnowledgeProposalService`: proponer diff Markdown y agregar solo tras `APPROVED` explícito. Pruebas `yes/no`, repetición de mensaje y respuesta fuera de contexto.

**Entregable:** CV adaptado real y carta sobre perfiles de prueba, editable y auditable. **Aceptación:** 100% de claims del PDF trazables; no cambian CV originales; respuestas de maestro reanudan espera.

## 4. Navegador y submit (P0; no activar en producción sin tests)

**T4.1** `BrowserPort` Hermes managed, Hermes CDP y real profile con capability checks; smoke test manual en Chrome/Edge sobre página local de pruebas. Opcional MCP Playwright/DevTools después.

**T4.2** `SitePolicyService`: allowlist/delegación, denylist, detección de plataforma, términos y consentimiento; sitio desconocido → `MANUAL_REVIEW`, nunca autopostulación por defecto.

**T4.3** `FormFiller` adjunta PDF, llena campos respaldados y pregunta datos ausentes. Nunca completa captcha/2FA automáticamente ni acepta acuerdos contractuales.

**T4.4** `SubmissionService`: permit vinculado a fingerprint/versión del formulario, intento previo al clic, recibo de sitio, unknown/no auto-retry, cuota diaria, locks y pruebas de concurrencia.

**Entregable:** 1 postulación de integración en un **ATS sandbox propio** con recibo, no en portales reales. **Aceptación:** interrupción en cada punto crítico no genera doble envío; el resultado incierto queda pendiente de revisión.

## 5. Gmail y respuestas aprobadas (P0)

**T5.1** Adapter Hermes Google Workspace `GmailPort` + `gmail ingest`. Pruebas de permisos y caída OAuth. Gmail remoto MCP solo feature flag experimental.

**T5.2** Poll/cursor con overlap, dedupe de message ID y correlación con ATS/aplicación. Clasificaciones y ambigüedades verificables, sin actualizar estados si correlación insuficiente.

**T5.3** Generador de resumen y sugerencias, `ReplyApproval` con hash/canal/identidad y `GmailReplyService` con transacción previa, thread correctness e idempotencia.

**T5.4** Políticas de clasificación: silencio en confirmaciones simples; aviso en rechazos/entrevistas/avances; solicitud explícita de sugerencias; límites de reintento.

**Entregable:** correo simulado de rechazo y entrevista -> historial/notificación -> elección de respuesta -> una sola contestación vía fake Gmail. **Aceptación:** 0 envíos sin decisión y 0 envíos duplicados bajo fallo de red simulado.

## 6. WhatsApp, scheduler, observabilidad (P0)

**T6.1** Integración con Hermes WhatsApp, self-chat/bot, allowlist, autorización de identidad, fallback CLI/web y cola de mensajes. No almacenar QR/session secrets en DB.

**T6.2** Crear/editar/pausar cron de Hermes desde setup (confirmar comandos reales); reconfiguración de frecuencia sin perder job en curso.

**T6.3** Logs JSON con correlación y secretos redactados, audit trail y controles de pausar/reanudar; health panel y backup/export.

**T6.4** Instalación a partir de clone + `uv tool install`/`pipx` o setup documentado; distribución de skill por GitHub tap cuando esté probada. Tests end-to-end local/mock.

**Entregable:** demo completa desde onboarding, con eventos realistas simulados; ejecución programada y mensaje WhatsApp cuando disponible. **Aceptación:** sin WhatsApp y sin Gmail aún debe permitir búsqueda/manual; reconexión no pierde estado.

## 7. Release v1.0 y después

**T7.1** Checklist de QA e informe de permisos por portal; prueba de instalación limpia en Windows 11 y Ubuntu LTS, navegador manejado + CDP. Windows nativo: web PandApply disponible aunque Hermes chat PTY falle.

**T7.2** Guía de instalación para programadores, privacidad, troubleshooting OAuth, conexión browser, políticas por sitio, cómo cambiar LLM y exportar/detener/desinstalar.

**T7.3** Publicación GitHub (release tag, changelog, licencia, guía de contribución, issue templates, CI). No publicar datos del desarrollador.

**P1** Adapter OpenClaw con la misma suite contractual, Gmail remoto MCP cuando salga de preview y sea apto; Playwright extension / Chrome DevTools MCP opcionales; dashboard más rico; conectores ATS oficiales adicionales.

## 8. Definition of Done universal

- Feature con pruebas unitarias, integración mock y smoke test si toca integración real.
- Una operación irreversible pasa por una política evaluable y con evento de auditoría.
- Documentación CLI/API y screenshots simuladas (sin datos reales) actualizadas.
- Manejo de fallos y reintentos con estados explícitos, nunca `except: pass`.
- No hay secretos ni CV de clientes en el repositorio, fixtures o logs.
- Windows y Linux verificados con al menos un script de prueba automática; diferencias documentadas.
- Pruebas de compatibilidad/regresión contra versión Hermes fijada en matriz.

## 9. Estrategia de pruebas

**Unitarias:** normalización URL, equivalencia ATS, correlación correo, autorización, hash, CV, schema migraciones, selección de perfil, rankings.

**Contractuales:** para cada `AgentRuntime`, `BrowserPort`, `GmailPort`, `DiscoveryPort`, `HumanChannel`.

**Integración:** fake Google/ATS/Gmail/WhatsApp; máquina de estados y recovery con crash injection (`before_click`, `after_click`, `before_db_commit`, `after_send`).

**E2E manual:** onboarding local Windows/Linux, Chrome ya abierto, CLI + dashboard, Gmail autorizable, WhatsApp modo self-chat, ejecución cron; sin enviar una solicitud real hasta crear un sandbox del proyecto y obtener autorización.

**Seguridad:** URL insegura (localhost SSRF, file://), inyección de instrucciones en página/correo, XSS en HTML procesado, CSRF, acceso a API externo, exposición de CDP, owner spoofing, accidental upload de secreto, bypass de cuota.

## 10. Orden sugerido para trabajar con Codex

En lugar de pedir «haz todo», abrir issues por cada T* y exigir un PR incremental. Primero P0/T0-T1; luego búsqueda; luego CV; por último operaciones externas. En cada PR, Codex debe marcar qué reutiliza de Hermes, cómo lo verificó y qué queda simulado. La demo completa se habilita al final de T6 y no antes.
