# 01 — PRD y especificación funcional de PandApply

**Versión:** 1.0 — alcance validado con el propietario del proyecto el 17-11-2026. **Prioridad:** flujo completo, pero desarrollo incremental con pruebas y gates.

## 1. Objetivo y usuario

**Usuario:** un programador que instala PandApply para sí mismo en Linux/Windows. El sistema denomina **maestro** a la persona autorizada para configurar preferencias, responder preguntas, aprobar datos de memoria y decidir respuestas de correo. **No** es SaaS/multiusuario; se admite múltiples perfiles profesionales de un solo propietario.

**Problema:** búsqueda repetitiva, documentos adaptados, formularios con preguntas redundantes y seguimiento disperso por correo. **Resultado deseado:** configurar una vez y mantener búsquedas/programación activas mientras el equipo esté encendido, con capacidad de reconfigurar y pausar.

## 2. Límites de producto

**Incluye el flujo completo:** onboarding → búsqueda por Google según preferencias → lectura del anuncio/formulario → cálculo de compatibilidad → CV adecuado o PDF generado → carta cuando corresponda → completar/enviar dentro de política aprobada → conservar comprobante → monitorizar Gmail → clasificar avance/rechazo/confirmación → notificar y responder con aprobación.

**Fuera de alcance v1:** SaaS, cobros/planes, gestión multiusuario remota, evasión de captchas, superar restricciones de portales, aceptar contratos, ofrecer datos falsos, automatizar pruebas técnicas o entrevistas, enviar respuestas de correo sin autorización humana, crear cuentas de portales o guardar claves en texto plano.

## 3. Requisitos funcionales y criterios de aceptación

| ID | Requisito | Comportamiento verificable |
|---|---|---|
| FR-01 | Instalación personal Linux/Windows | CLI detecta Hermes, verifica versión/capacidades y falla con mensaje accionable si falta requisito |
| FR-02 | Onboarding/reconfiguración | Asistente persistente: se puede reanudar, repetir o editar sin borrar historial |
| FR-03 | Definición de perfiles | Maestro define uno o varios perfiles/cargos, skills, seniority, idioma, lugar/remoto, salario, exclusiones |
| FR-04 | Importación CV | Lee PDF y DOCX de carpeta autorizada; calcula hash y extrae contenido; no modifica originales |
| FR-05 | Conocimiento | Archivos Markdown con afirmaciones trazables y estado confirmado/no confirmado |
| FR-06 | Descubrimiento Google | Construye búsquedas con preferencias, registra URL, fecha, fuente y descripción; soporta provider alternativo |
| FR-07 | Filtro de compatibilidad | Muestra puntuación, razones, incompatibilidades y evidencias; umbral configurable |
| FR-08 | Inspección formulario | Detecta preguntas, adjuntos, requisitos y acciones irreversibles; estructura los campos |
| FR-09 | Consulta al maestro | Solicita datos faltantes por canal disponible; mantiene tareas en `WAITING_USER` |
| FR-10 | Memoria con aprobación | Recomienda guardar datos nuevos; respuestas sí/no actualizan solo la propuesta correspondiente |
| FR-11 | CV PDF | Escoge CV existente compatible o produce PDF fiel a hechos confirmados, guarda checksum y ruta |
| FR-12 | Carta de presentación | Genera carta adaptada opcional, registra contenido y origen; no inventa experiencia |
| FR-13 | Autopostulación | Envío automático solo con consentimiento vigente, perfil elegible, datos completos y sitio permitido |
| FR-14 | Duplicados | Dedupe por identificación ATS, URL canónica y llave alternativa; proceso atómico/lease |
| FR-15 | Confirmación y auditoría | Solo `SUBMITTED` con recibo verificable; logs y evidencia minimizada/redactada |
| FR-16 | Seguimiento Gmail | Polling configurable, cursor/canal de mensajes, clasificación y correlación segura con aplicación |
| FR-17 | Estados de proceso | Rechazo, avance, entrevista, confirmación e incertidumbre; historial append-only |
| FR-18 | Respuestas correo | Maestro elige sugerencia o proporciona texto; el agente responde en hilo correcto una sola vez |
| FR-19 | WhatsApp opcional | Modo self-chat o bot y autorización de remitente; fallback CLI/web ante desconexión |
| FR-20 | Interfaz | CLI + web local: estado, historial, perfiles, configuración, aprobaciones, errores, pausa/resume |
| FR-21 | Planificación | Búsquedas y Gmail programados; reanudación segura tras reinicio, sin duplicar envíos |
| FR-22 | Autoevaluación | `doctor` prueba Hermes, modelo, navegador, correo, permisos, scheduler y almacenamiento |
| FR-23 | Exportación/eliminación | Export JSON/CSV y borrado local controlado del usuario, incluidos PDF generados |
| FR-24 | Modularidad | Puertos y adaptadores documentados; la lógica de negocio no importa paquetes internos de Hermes |
| FR-25 | Easy setup | Un comando prepara el entorno virtual y abre un asistente; reutiliza Hermes/Gmail/WhatsApp existentes |
| FR-26 | Configuración antes del panel | Validar SQLite, perfiles de búsqueda, filtros, frecuencia, volumen y cupo diario antes de ofrecer el panel |
| FR-27 | Piloto de primera búsqueda | Saludo por WhatsApp al propietario; respuesta autenticada y contextual inicia una sola búsqueda, sin habilitar postulaciones |
| FR-28 | Login visible | El enlace local abre un formulario de sesión; credenciales claras en la terminal y cierre de sesión |

Los detalles añadidos por el propietario y el estado verificable se mantienen en
[10-OWNER-REQUIREMENTS.md](10-OWNER-REQUIREMENTS.md). Una función pendiente allí
sigue formando parte del alcance; no se considera terminada por figurar en el asistente.

## 4. Parámetros reconfigurables

- **Perfiles**: nombre, cargos, roles alternativos, seniority, años verificados, palabras clave obligatorias/excluidas, stack, idiomas, países, zonas horarias, remoto/híbrido/presencial, piso salarial, divisa y período, tipos de contrato, empresas excluidas, nivel de inglés, CV preferidos.

En el onboarding, **perfil de búsqueda** significa un grupo de preferencias guardadas;
su nombre es una etiqueta del propietario. Los **cargos** son los títulos que se
buscarán dentro de ese grupo y comparten sus filtros. Un único perfil puede contener
varios cargos. Explicar esta relación con un ejemplo antes de pedir nombres; los
perfiles adicionales son opcionales y se usan para preferencias diferentes.
- **Búsqueda**: Google como opción seleccionada, dominios preferidos, consultas generadas, volumen por corrida, frecuencia, días/horas permitidos, antigüedad máxima, número máximo de páginas; alternativa con proveedor autorizado.
- **Evaluación**: umbral mínimo, reglas duras (salario, ubicación, modalidad), cantidad máxima diaria de envíos, límite de gasto en LLM, política por dominio/plataforma.
- **Documentación**: directorio fuente de CV, directorio generado, idioma de CV, plantilla, carta opcional; nunca sobrescribir originales.
- **Navegador**: (a) browser administrado Hermes, (b) conexión a navegador existente vía CDP, (c) perfil real/snapshot si soportado, (d) MCP externo solo tras smoke test; permisos y riesgo explicados.
- **Gmail**: cuenta autorizada, frecuencia polling, etiquetas/filtros, tipos de eventos, notificaciones, habilitación de envío de respuestas (siempre con autorización concreta).
- **Comunicación**: WhatsApp opcional, fallback a CLI/web, horario silencioso, idioma, mensajes acumulados, principal autorizado.
- **Sistema**: almacenamiento local, bind loopback, zona horaria, autoarranque opcional, políticas de retención, modo simulación.

**Defaults de diseño (ajustables, no respuestas confirmadas del propietario):** búsquedas cada 6 horas, Gmail cada 20 minutos, máximo 5 postulaciones/día, compatibilidad >=0.8, `dry_run=true` hasta completar la verificación inicial, cero autorizaciones de dominio implícitas. El usuario los revisa en onboarding y los puede cambiar.

## 5. Experiencia principal

1. `pandapply setup` abre un asistente de seis pasos, valida cada integración y explica permisos.
2. Usuario elige `hermes`, modelo, carpeta de CV, perfiles y preferencias de búsqueda.
3. Selecciona navegador administrado o existente; abre un portal de prueba y comprueba acceso, sin enviar nada.
4. Configura Gmail con el mecanismo más estable soportado por Hermes/Google Workspace; la aplicación prueba lectura y **separadamente** la capacidad de responder, si autorizada.
5. Configura WhatsApp o marca «Omitir»; se registra la identidad autorizada.
6. Visualiza la política de envío automático, acepta explícitamente los dominios permitidos, activa scheduler, revisa un ensayo. Puede cambiar cualquier campo con `pandapply config` o UI.
7. Desde entonces una búsqueda completa se dispara por cron o por instrucción del maestro. Los trabajos pendientes sobreviven reinicios (las sesiones del navegador y del gateway pueden requerir reconexión).

## 6. Comandos y consultas esperados del maestro

- «Encuentra 15 ofertas remotas de Backend Node.js, mínimo USD 2.000/mes, y postúlate a las elegibles».
- «Pausa las postulaciones, continúa solo buscando».
- «Cambia mi límite diario a 3 e incluye trabajos híbridos en Cali».
- «Muéstrame las 10 últimas postulaciones y por qué fueron elegidas».
- «No guardes esa habilidad en mi perfil».
- «Responde al correo de [empresa] con la opción 2» / «Responde exactamente: ...».
- «Revisa el estado del navegador y Gmail».

## 7. UX web y CLI

El dashboard **propio de PandApply** muestra: Resumen, Vacantes, Postulaciones (filtros por estado/empresa), Bandeja de decisiones, Perfiles/Conocimiento, Configuración, Logs y Estado de conectores. Reutilizar el chat de Hermes cuando funcione; cuando no, el sitio PandApply puede enviar órdenes mediante el API de Hermes con clave local. No acoplar el negocio al HTML interno del dashboard Hermes.

La CLI tiene equivalentes: `setup`, `doctor`, `config`, `profiles`, `search`, `applications`, `approvals`, `gmail`, `run`, `pause`, `resume`, `web`, `export`.

## 8. Métricas y criterios no funcionales

- Cero postulaciones duplicadas en las pruebas de concurrencia y en reinicios simulados.
- Cero respuestas de correo enviadas sin autorización asociada a identidad/hilo/texto.
- Cero afirmaciones no respaldadas introducidas automáticamente en documentos.
- Reanudar estado tras un `kill` durante el llenado, dejando la acción irreversible como **desconocida**, no reintentable automáticamente.
- Funcionamiento sin WhatsApp; funcionamiento con Gmail desconectado debe mostrar degradación y permitir búsquedas.
- Sin credenciales ni cuerpo completo de correo en logs; secretos en almacén del sistema/Hermes, no SQLite.
- Todo motor/modelo externo se representa como adaptador intercambiable.
- Windows y Linux deben pasar pruebas de instalación, ejecución local, exploración browser y UI.

## 9. Restricciones legales y del entorno

La búsqueda por Google es una preferencia del producto, no una licencia para scrapear resultados o evadir mecanismos anti-bot. El adaptador debe respetar términos de uso y bloquear/derivar a navegación manual cuando corresponda. En portales que prohíban bots (p. ej. LinkedIn, Indeed), PandApply **no ejecutará postulaciones automatizadas**, aunque el maestro habilite autopostulación global. No se proporciona bypass de CAPTCHA ni de credenciales.
