# 08 — Architecture Decision Records (ADR) y preguntas aplazadas

| ADR | Estado | Decisión | Motivo |
|---|---|---|---|
| 001 | Aprobado por el propietario | Proyecto llamado **PandApply** | Nombre oficial |
| 002 | Aprobado | Hermes primero, OpenClaw después | Reutilizar gateway, navegador, cron, habilidades |
| 003 | Aprobado | Instancia por programador; Linux y Windows | Evitar SaaS y complejidad multiusuario |
| 004 | Aprobado | Google como fuente de búsqueda, preferencias configurables | Diseño centrado en cada usuario |
| 005 | Aprobado con restricciones técnicas | Autopostulación cuando los datos basten | Sitios y políticas externas prevalecen |
| 006 | Aprobado | CV importados PDF/DOCX de carpeta; CV nuevos solo PDF | Control de documentos originales |
| 007 | Aprobado | Maestro decide si se guardan memorias nuevas | Consentimiento explícito |
| 008 | Aprobado | Gmail clasifica; respuestas siempre tras interacción con maestro | Evitar correos no consentidos |
| 009 | Aprobado | WhatsApp opcional; CLI y web obligatorias | Alta disponibilidad de interfaz local |
| 010 | Aprobado | Navegador administrado o existente con opciones CDP/Relay/MCP | Reusar sesiones cuando se desea |
| 011 | Diseño propuesto | Python + SQLite + Markdown + FastAPI/HTMX | Portabilidad y claridad |
| 012 | Diseño propuesto | Hermes cron para scheduling; core para estado y leases | Evitar crear otro agente/scheduler |
| 013 | Diseño propuesto | SitePolicy deny-by-default para submit | Seguridad y términos |
| 014 | Diseño propuesto | Recibo obligatorio; `SUBMISSION_UNKNOWN` sin reintento | Evitar duplicados irreversibles |
| 015 | Diseño propuesto | Google Workspace Hermes primario; Gmail MCP futuro | MCP remoto aún en Developer Preview |
| 016 | Diseño propuesto | Dashboard PandApply propio, no solo Hermes | Seguimiento específico y Windows |
| 017 | Solicitado por el propietario | Instalador de un comando y asistente completo; entorno virtual automático | Evitar cadenas de comandos manuales |
| 018 | Solicitado por el propietario | Aprovechar Hermes, Gmail y WhatsApp ya configurados | Evitar repetir autorizaciones y configuraciones |
| 019 | Solicitado por el propietario | Configurar perfiles buscados, filtros y cupos antes de abrir panel | El panel es el último paso del asistente |
| 020 | Solicitado por el propietario | Piloto WhatsApp con saludo y autorización para primera búsqueda | Validar recorrido externo completo, sin confundir saludo con búsqueda ejecutada |
| 021 | Solicitado por el propietario | El desarrollador ejecuta pruebas locales; propietario valida integraciones externas necesarias | No delegar pruebas internas al usuario |
| 022 | Solicitado por el propietario | Usar el propio Hermes para configurar y reparar integraciones ausentes o fallidas | Conversación interactiva con el perfil guardado, regreso al setup y comprobación independiente; sin repetir envíos inciertos |

## Supuestos de implementación a confirmar con UX en wizard

- Defaults de frecuencia/cupo/score son **propuestas**, no preferencias acordadas por el propietario. El usuario elige en onboarding y puede reconfigurar.
- Plataforma de IA/modelo queda a elección del usuario; costos, cuotas y políticas de proveedor varían.
- La carpeta de CV puede estar en ubicación distinta según usuario; nunca incluir rutas de la máquina de desarrollo en el repositorio.
- La zona horaria predeterminada del ejemplo es `America/Bogota` por contexto de creación, pero instalación final debe detectar/proponer y permitir elegir cualquier IANA zone.
- La interfaz web mínima propia es parte de v1; el chat de Hermes puede aprovecharse en Linux y algunas versiones Windows, pero no constituye dependencia de disponibilidad de PandApply.
- El primer adaptador Gmail usa la ruta `gws`/Google Workspace disponible en Hermes; Codex debe confirmar un contrato funcional para `ingest` y `reply` sin acceso a tokens crudos.
- La licencia exacta para publicación se propone MIT (sujeto a la decisión del autor y revisión de licencias de terceros).

## No modificar sin autorización explícita del propietario

- Quitar Gmail, WhatsApp opcional, CLI/web o generación PDF del alcance.
- Pasar el proyecto a SaaS o requerir infraestructura centralizada.
- Activar respuestas Gmail sin aprobación humana.
- Guardar nuevos hechos profesionales automáticamente.
- Exigir usar un navegador nuevo cuando el maestro eligió existente y hay conector viable.
- Sustituir Hermes como runtime inicial sin demostrar un impedimento técnico.

## Decisiones que Codex puede tomar y documentar

- Typer vs Click, FastAPI+HTMX vs React, reportlab vs WeasyPrint, librería SQLite, formato interno de eventos: sujeto a pruebas de portabilidad y a conservar contratos.
- Orden de features visuales mientras se mantenga el alcance completo al final.
- Tipo de proveedor de búsqueda alternativo autorizado, siempre opcional y documentado.
- Formato de distribución de la CLI (`pipx`, `uv tool`, wheel) tras CI Linux/Windows.
