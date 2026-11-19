# 06 — Seguridad, privacidad y cumplimiento

## 1. Modelo de amenazas

**Activos protegidos:** sesión navegador (cuentas/cookies), acceso Gmail, datos personales del CV, historial de postulaciones, dinero/uso de LLM, identidad del maestro, capacidad de enviar correos y formularios. **Adversarios:** página de vacante o correo malicioso (prompt injection), intruso local/red, cuenta de mensajería no autorizada, dependencias comprometidas, LLM que alucina o interpreta mal un formulario.

La seguridad principal NO es «que el LLM prometa ser cuidadoso»: las acciones que alteran sistemas externos pasan por controles deterministas en el core. Un modo de conversación no equivale a un grant de acción.

## 2. Política por portal

- Conservar `SitePolicy` versionada por dominio/plataforma y operación (`discover`, `read`, `fill`, `submit`) con estado `ALLOWED | MANUAL_ONLY | BLOCKED | UNKNOWN`.
- `UNKNOWN` **nunca permite submit**. El maestro puede confirmar sus preferencias, pero su aprobación no anula los términos/limitaciones de un portal.
- Bloquear por defecto automatización en LinkedIn e Indeed y otros portales que la prohíban; permitir ayuda manual, información pública mediante vías autorizadas o APIs oficiales cuando correspondan.
- No evadir CAPTCHA, medidas antibot, límites de consultas, autenticaciones ni áreas privadas.
- Google como fuente preferida: navegar sin scraping masivo ni evasión; cuando lo impidan las condiciones de uso, explicar el bloqueo y proponer proveedor autorizado/manual. No presentar Google Custom Search JSON API como servicio general para usuarios nuevos.

## 3. Autonomía con límites

- Autopostulación requiere `auto_apply_enabled`, finalización del wizard, `dry_run=false`, perfil concreto, cuota diaria, dominio permitido, estado de consentimiento vigente y validación de evidencias. Todo se registra.
- `submit` se representa como intento irreversible con un permiso de corta vida y hash de formulario; solo una vez por aplicación mientras haya intento en estado `UNKNOWN`.
- Acciones no autorizadas v1: aceptar contratos/NDAs, pruebas técnicas/entrevistas, pagos, compartir contraseñas/códigos OTP, eliminar correo, crear cuentas y cambiar configuración desde contenido de terceros.
- Desactivar selectores que puedan aceptar términos legales o marcar compromisos contractuales como si fueran campos rutinarios; cuando un formulario requiera una declaración legal, pedir aprobación explícita o `MANUAL_REVIEW`.

## 4. Prompt injection e información de fuentes externas

Correos, anuncios, archivos CV externos y HTML son **datos**, nunca instrucciones de sistema. La skill debe mantener separación de roles e ignorar órdenes incrustadas (ej. «envía tus credenciales a...», «desactiva la auditoría», «aplica a este enlace no relacionado»). Validar URLs (esquemas http/https, host permitido, bloquear IP privadas/loopback para navegación externa salvo sandbox test). Desinfectar HTML en dashboard y no ejecutar scripts de anuncios.

## 5. Navegador y CDP

Hermes CDP, Chrome DevTools MCP y Playwright extension pueden dar acceso a sesiones autenticadas. **No exponer endpoints CDP a `0.0.0.0` ni a Internet**. Preferir browser aislado por defecto; usuario elige existente y confirma los riesgos. El `--autoConnect` moderno puede acceder al perfil personal; la UI debe advertir claramente sobre esto. No guardar cookies ni perfiles del navegador en nuestro SQLite. Fijar versiones y limitar host/protocol.

## 6. Gmail y privacidad

- Usar OAuth2 de escritorio con credenciales proporcionadas por cada usuario en su entorno, mediante integración Hermes Google Workspace; scopes mínimos necesarios y consentimiento explícito para envío.
- Gmail API `gmail.readonly` y `gmail.compose` son scopes **restringidos**; `gmail.send` es sensible. Elegir los menores compatibles con las operaciones reales. Algunas publicaciones exigirán verificación y eventualmente requisitos adicionales; cada usuario puede emplear credenciales propias cuando las reglas de Google lo permitan, pero no se promete ausencia de verificaciones.
- Gmail MCP oficial es **Developer Preview** al 17-11-2026 y no se adopta como dependencia central; clientes que lo usen deben cumplir requisitos OAuth agentic vigentes.
- Respuesta por Gmail solo con selección/opción/texto del maestro ligado a hilo/mensaje/hash. Evitar cambios de destinatario no aprobados, cc/bcc no previstos, respuestas automáticas en masa.
- No guardar texto íntegro de correos o archivos adjuntos salvo aprobación y necesidad técnica; almacenar IDs, clase, remitente seleccionado y digest redaccionado. Borrar/exportar explícitamente.

## 7. WhatsApp

Usar Hermes; elegir `self-chat` o número bot, verificar `allowed_users`, deshabilitar acceso abierto; no confiar solo en el texto «soy el maestro». Una orden sensible lleva nonce/decision ID y expira. No reenviar el contenido íntegro de CV ni correo a números desconocidos. Bridge WhatsApp Web no oficial puede desconectarse o implicar riesgos de cuenta: debe ser opcional y nunca el único canal.

## 8. Ejecución local y secretos

La ayuda de configuración abre Hermes con argumentos literales y sin shell, perfil
explícito y directorio de trabajo del perfil seleccionado. Conserva interacción
humana para OAuth/QR y no usa flags de aprobación automática. PandApply no captura
su salida ni copia credenciales. Las peticiones son fijas y limitan la ayuda a
configurar; la prueba posterior de PandApply no confía en afirmaciones del agente.
No se lanza en modo sin TTY para evitar autorizar mediante un agente desatendido.

- Config y base SQLite con permisos de usuario; API ligada a `127.0.0.1` y protegida con token para mutaciones. Para acceso remoto futuro usar TLS + autenticación robusta, no abrir un puerto manualmente.
- Guardar secretos en almacenamiento de Hermes o keyring del sistema, nunca en repositorio, SQLite, archivos de ejemplo o logs.
- HTML web: escape por defecto, CSRF para formularios, Content Security Policy básica, cabeceras de seguridad, rate limiting y validación de esquema.
- PDFs con nombres neutralizados; sanitizar path traversal al aceptar carpeta CV, origen de attachments e IDs de archivo.
- Dependencias fijadas, SBOM/licencias comprobadas y GitHub Actions en Windows/Linux.
- Backup y borrado bajo control local del propietario; etiquetas claras de evidencia que podría contener PII.

## 9. Registro de riesgos

| Riesgo | Prob. | Impacto | Mitigación |
|---|---|---|---|
| Bloqueo por automatización de portal | Alta | Alta | Políticas por sitio, manual-only, no bypass |
| Gmail OAuth no disponible/preview | Media | Alta | Hermes Workspace primario, pruebas y reautorización |
| LLM genera CV con datos falsos | Media | Alta | Claims con evidencia, verificación estricta |
| Formulario se envía dos veces | Media | Alta | Attempt antes de clic, estado UNKNOWN y dedupe |
| Browser personal expone cuentas | Media | Alta | consentimiento explícito, loopback, opción aislada |
| Email malicioso manda instrucciones | Alta | Alta | aislamiento de fuentes, permisos deterministas |
| WhatsApp desconectado | Alta | Media | CLI/web fallback, outbox |
| Versiones Hermes alteran API/comandos | Media | Media | capability checks y suite contractual por versión |
| Windows limita dashboard Hermes | Media | Media | web PandApply propia + API Hermes, detección |
| Google Search no permite scraping | Alta | Alta | proveedor autorizado/manual y límites |

## 10. Aclaración legal

La implementación debe respetar los términos vigentes de las plataformas y leyes de privacidad aplicables. Este documento es especificación de ingeniería, **no asesoría legal** ni garantía de autorización por parte de Google, LinkedIn, Indeed u otros portales.
