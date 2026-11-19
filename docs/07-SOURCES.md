# 07 — Investigación técnica y fuentes

**Fecha de consulta:** 17 de noviembre de 2026. Son fuentes públicas; las capacidades de productos externos pueden cambiar. Codex debe verificar versiones instaladas antes de programar integraciones.

**Verificación adicional, 18-11-2026:** la referencia CLI y `hermes chat --help`
confirman `chat -q` como consulta inicial de una conversación cuando hay TTY.
Se comprobó el parser real y la selección explícita de perfil con el script
`scripts/hermes_guidance_contract.py`, sin ejecutar un modelo ni OAuth. La forma
natural «hermes configurar gmail» se implementa como una petición al chat, no como
un supuesto subcomando de Hermes.

| Fuente oficial | Evidencia relevante para PandApply |
|---|---|
| [Hermes Agent GitHub](https://github.com/NousResearch/hermes-agent) | Runtime, gateways, WhatsApp, cron, herramientas |
| [Hermes Skills System](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills) | `SKILL.md`, ruta `~/.hermes/skills/`, distribución mediante tap |
| [Hermes Creating Skills](https://hermes-agent.nousresearch.com/docs/developer-guide/creating-skills) | Frontmatter de skill; blueprint cron opt-in y publicación |
| [Hermes Browser Automation](https://hermes-agent.nousresearch.com/docs/user-guide/features/browser) | `browser_exec`, conexión `/browser connect` vía CLI, `use_real_profile` |
| [Hermes Google Workspace Skill](https://hermes-agent.nousresearch.com/docs/user-guide/skills/google-workspace) | OAuth escritorio, preferencia `gws`, fallback Python, email search/read/send/reply |
| [Hermes WhatsApp](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/whatsapp) | self-chat / bot con QR, allowlist y gateway |
| [Hermes Cron](https://hermes-agent.nousresearch.com/docs/user-guide/features/cron) | Tareas, skills por job, cron CLI y recuperación |
| [Hermes Web Dashboard](https://hermes-agent.nousresearch.com/docs/user-guide/features/web-dashboard) | UI administración, chat TUI web, cron, perfiles; restricciones/cambios por SO |
| [Hermes Windows Native](https://hermes-agent.nousresearch.com/docs/user-guide/windows-native) | Windows 10/11 nativo, PowerShell, pywinpty/ConPTY en docs actuales |
| [Hermes API Server](https://hermes-agent.nousresearch.com/docs/user-guide/features/api-server) | API OpenAI-compatible en gateway para frontend de terceros |
| [Hermes CLI Reference](https://hermes-agent.nousresearch.com/docs/reference/cli-commands) | Validar comandos de setup/cron/whatsapp; versión exacta |
| [Playwright MCP Browser Extension](https://playwright.dev/mcp/configuration/browser-extension) | Reusar pestañas, cookies y sesiones del Chrome existente |
| [Chrome DevTools MCP Configuration](https://developer.chrome.com/docs/devtools/agents/get-started/configuration/) | `--autoConnect`, versión Chrome y conexión CDP |
| [Chrome DevTools MCP Auto-Connect](https://developer.chrome.com/docs/devtools/agents/use-cases/auto-connect) | Riesgo de acceso al perfil completo del navegador |
| [Gmail MCP Setup](https://developers.google.com/workspace/gmail/api/guides/configure-mcp-server) | Gmail MCP remoto en Developer Preview (no dependencia base) |
| [Google Workspace/Gmail release notes](https://developers.google.com/workspace/gmail/release-notes) | Requisito de cliente OAuth agentic para Workspace MCP desde 11-11-2026 |
| [Gmail OAuth Scopes](https://developers.google.com/workspace/gmail/api/auth/scopes) | Scopes sensibles y restringidos; verificación |
| [Indeed Terms](https://www.indeed.com/legal) | Restricciones a bots y automatización de Indeed Apply |
| [LinkedIn Prohibited Software](https://www.linkedin.com/help/linkedin/answer/a1341387/prohibited-software-and-extensions) | Prohibiciones sobre automatización no autorizada |
| [Google Search Spam Policies](https://developers.google.com/search/docs/essentials/spam-policies) | Límites sobre acceso no autorizado y scraping de resultados |

## Hechos verificados vs. elecciones de diseño

- **Verificado:** Hermes tiene skills, cron, WhatsApp, Google Workspace, browser CDP, API y dashboard. **Diseño propuesto:** un core Python con CLI, SQLite, FastAPI y Markdown; esas piezas aún no existen en PandApply.
- **Verificado:** Chrome DevTools MCP y Playwright extension pueden conectarse a un navegador existente bajo condiciones documentadas. **No verificado:** que todos los métodos funcionen automáticamente dentro de cualquier versión/configuración de Hermes; se exige smoke test en setup.
- **Verificado:** Gmail MCP remoto tiene prerequisitos de preview. **Diseño:** usar Google Workspace de Hermes y reservar MCP remoto para más adelante.
- **Verificado:** las políticas de portales restringen automatizaciones. **Diseño:** sitios no autorizados pasan a manual-only; autopostulación en sitios permitidos sigue siendo requisito.
- **Verificado:** documentación web de Hermes presenta variaciones por versión respecto a chat y Windows. **Diseño:** PandApply web independiente y capability detection.

## Base solicitada por el propietario

Archivo `references/original-idea.excalidraw` (copia del diagrama aportado por el usuario). Ideas preservadas: búsqueda de vacantes de cantidad configurable; lectura de perfil/formulario; base de conocimiento Markdown/CVs/LinkedIn/proyectos/anécdotas; consulta al maestro por WhatsApp o terminal/web; selección o generación de CV/carta; completado del formulario; dedupe; revisión de Gmail; silencio en confirmaciones simples; alertas por rechazos/continuación.

Las decisiones adicionales proceden de las respuestas explícitas del propietario o de diseño propuesto en este paquete y se diferencian en `08-DECISIONS.md`.
