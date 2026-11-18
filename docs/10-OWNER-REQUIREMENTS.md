# Requisitos adicionales del propietario y estado de implementación

Estas instrucciones proceden de la conversación con el propietario y amplían el PRD.
No reducen el alcance aprobado ni convierten una prueba simulada en integración real.

| Requisito | Comportamiento exigido | Estado actual |
|---|---|---|
| Instalador sencillo | Un comando ejecutable inicia la instalación y un asistente paso a paso en Windows/Linux | `install.cmd` y `install.sh`; entorno virtual automático |
| Entorno aislado | PandApply siempre usa su propio entorno virtual | Implementado; sin activar `.venv` manualmente desde el instalador |
| Pruebas autónomas | El desarrollador ejecuta las pruebas locales; el propietario solo valida integraciones externas cuando sea necesario | Pruebas locales, simuladas y Docker a cargo del desarrollador |
| Reutilizar Hermes | Detectar instalación, perfil activo, Gmail autorizado y sesión WhatsApp existentes | Detección local y comprobación opcional de identidad Gmail; no copiar tokens ni sesiones |
| Ocultar rutas internas | No preguntar al propietario dónde están Python o `google_api.py` durante el setup habitual | Resuelve instalación nativa `hermes-agent` y entorno PM seleccionado mediante su metadata; ante fallo muestra Gmail pendiente, sin exigir rutas técnicas |
| SQL comprobado | Crear/migrar SQLite y validar integridad, relaciones y escritura antes de finalizar | Implementado en el asistente; no requiere cliente SQLite externo |
| Varios perfiles | Preguntar qué perfiles profesionales se buscarán y permitir crear varios | Selección persistida en `search_profile_ids` |
| Claridad de perfiles y cargos | Explicar antes de preguntar: perfil = grupo de preferencias; cargos = títulos buscados dentro del grupo. Un perfil admite varios cargos y crear otros es opcional | Explicación y ejemplos en el asistente y README; no exigir un perfil por cargo |
| Preferencias | Preguntar cargos, ubicaciones, idiomas, habilidades como filtros, modalidad y piso salarial | Guardadas por perfil; no se convierten en experiencia confirmada |
| Cuotas | Preguntar cuántas vacantes llenar por día y distinguir ese cupo del volumen de evaluación | Cupo diario, resultados por búsqueda y frecuencia configurables; no habilitan envíos |
| Gmail guiado | Verificar cuenta existente y pedir filtro de seguimiento; mostrar permisos o pasos pendientes | Cuenta/filtro configurables; activación automática, cursor completo y validación con cuenta real pendientes |
| Panel al final | La pregunta de abrir el panel es el último paso, después de configurar y mostrar pendientes | Implementado; abrir el servidor bloquea la terminal hasta Ctrl+C |
| Login visible | Enlace a un formulario de usuario y contraseña, sesión y cierre de sesión | Implementado; credenciales temporales en la terminal |
| Piloto WhatsApp | Al terminar, saludar al propietario y pedir autorización para la primera búsqueda | Saludo optativo con destino confirmado e intento persistido; falta recepción autenticada de respuesta e inicio de búsqueda real |
| Primera búsqueda | Una respuesta afirmativa del propietario, vinculada al piloto, inicia una sola búsqueda con los perfiles/filtros elegidos; no autoriza postulaciones | Pendiente de adaptador de recepción y proveedor de búsqueda real autorizado |
| Documentación inicial | Getting started para Hermes y OpenClaw incoming | README actualizado; OpenClaw no disponible todavía |
| Historial Git | Conservar la primera versión y avances en commits revisables | Commits locales; no implica publicación remota |

## Flujo obligatorio de onboarding

1. Preparar el entorno virtual e instalar las dependencias.
2. Elegir runtime y detectar/confirmar el perfil Hermes existente.
3. Migrar y comprobar SQLite automáticamente; fallar con un resultado accionable si no es válido.
4. Comprobar Gmail con su autorización existente si el propietario lo desea; conservar cuenta anterior ante discrepancias.
5. Seleccionar/crear perfiles, registrar CV sin alterar originales y configurar cargos/filtros.
6. Elegir perfiles para búsqueda, cupo diario de postulaciones, volumen por búsqueda y frecuencia.
7. Mostrar capacidades listas y pendientes. Configurar una frecuencia no implica que exista una tarea cron activa.
8. Ofrecer el piloto WhatsApp al propio propietario, con consentimiento de envío y destino explícitos.
9. Mostrar estado persistido del piloto. Un resultado incierto bloquea un reenvío automático.
10. Ofrecer abrir el panel al final. No considerar la búsqueda real operativa hasta completar los conectores pendientes.

## Criterios del piloto completo (pendientes)

El mensaje inicial es «Hola, soy PandApply. ¿Quieres que ejecutemos la primera búsqueda de vacantes?».
La respuesta debe proceder del principal WhatsApp autorizado, estar vinculada al piloto
y caducar; un «sí» suelto de otro chat no es autorización. «No» conserva el sistema
sin iniciar búsqueda. Una respuesta repetida no ejecuta una segunda búsqueda. Si faltan
proveedor autorizado o permisos, informar el bloqueo sin simular una búsqueda real.
El piloto no habilita autopostulación, respuestas de Gmail ni cambios de memoria.
