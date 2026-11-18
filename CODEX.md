# Instrucciones para Codex — implementar PandApply

Eres el agente de programación encargado de implementar **PandApply**, un sistema open source instalable por programadores en Linux y Windows. **El diseño y los requisitos están en `README.md` y `docs/`.** Usa `references/original-idea.excalidraw` para comprobar trazabilidad; **no reemplaces** la arquitectura aprobada por una app SaaS o un bot casero.

## Antes de tocar código

1. Lee en este orden: `docs/01-PRD.md`, `docs/02-ARCHITECTURE.md`, `docs/03-WORKFLOWS.md`, `docs/04-DATA-AND-API.md`, `docs/06-SECURITY-AND-RISKS.md`, `docs/05-IMPLEMENTATION-PLAN.md`, `docs/08-DECISIONS.md`.
2. Consulta las fuentes oficiales en `docs/07-SOURCES.md` y verifica los comandos/versiones Hermes que realmente puedas instalar. Si una capacidad no existe, implementa **fallback explícito** y deja registro; no inventes APIs.
3. Implementa primero tests y mocks; en el primer PR deja `pandapply doctor`, CLI mínima, esquema y migraciones. **No** intentes automatizar un portal real de empleo hasta probar un ATS de simulación local y site policy.
4. Usa core Python agnóstico del runtime y `HermesAdapter` en `adapters/hermes`; no importes paquetes Hermes dentro del dominio. El futuro OpenClaw debe cambiar solo adaptadores.
5. Mantén todos los comandos previstos de CLI y contrato HTTP de `specs/openapi.yaml`; si ajustas un contrato, actualiza documentación y pruebas en el mismo PR.
6. Cada acción externa irreversible (submit de aplicación, envío Gmail) necesita idempotencia, intent persistido antes de ejecutar, policy gate, recibo y manejo UNKNOWN. No uses reintento automático ciego.
7. Ni CV ni carta pueden inventar experiencia: claims trazables y confirmados; datos nuevos se guardan solo con decisión afirmativa del maestro.
8. Un correo no provoca envío automático; ofrece sugerencias solo si el maestro desea y ejecuta la respuesta escogida o dictada.
9. Google es fuente preferida pero respeta restricciones de buscadores/portales. No eludir CAPTCHA, automatizar LinkedIn/Indeed contra sus términos, ni implementar scraping evasivo.
10. `Web` y `CLI` deben funcionar en Windows/Linux incluso sin WhatsApp. Usa Hermes cron/WhatsApp/Gmail cuando esté disponible, no reprogrames un gateway.

## Plan de ejecución

Trabaja en fases `T0` a `T7` de `docs/05-IMPLEMENTATION-PLAN.md`. Al terminar cada fase entrega resumen de cambios, tests ejecutados, decisiones técnicas, riesgos abiertos, y comandos para reproducir la demo local. No avances a integración con cuentas/portales reales sin cumplir gates de seguridad y aceptación.

**Primera tarea concreta:** scaffold Python, CI multiplataforma, modelos de dominio, migración inicial, Fake adapters, CLI `doctor`/`setup`, tests de dedupe y `SUBMISSION_UNKNOWN`; no se requieren tokens ni credenciales del usuario.

## Criterios absolutos de aceptación

- Demo fixture completa de búsqueda → matching → CV PDF → formulario en sandbox → confirmación → Gmail simulado → sugerencia → aprobación → respuesta sin duplicados.
- Web + CLI funcional y visible en Linux y Windows.
- Configuración modificable, estado reanudable, datos locales, privacidad.
- Integración Hermes real probada **por capacidad** (skills, cron, navegador, Google Workspace, WhatsApp opcional) y documentada con versión compatible.
- Tests que prueban que **nunca** se envía sin política/autorización ni se reintenta submit ambiguo.

No afirmes que PandApply «está funcionando» hasta ejecutar las pruebas. Los diagramas son guía técnica editable; los modelos y contratos prevalecen si el layout visual tiene simplificaciones.
