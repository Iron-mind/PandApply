# Configuración asistida por Hermes, navegador y panel

## Pedir a Hermes que prepare o repare las integraciones

El setup ofrece ayuda de Hermes para Gmail, navegador y WhatsApp cuando faltan
componentes o autorizaciones. Gmail y navegador tienen una opción **4** de ayuda;
si una comprobación falla, también se ofrece reparación. WhatsApp pregunta por
configuración o reparación antes del saludo piloto, que sigue siendo independiente.

Para repetir solo una conexión, sin rehacer perfiles ni enviar un saludo:

```sh
pandapply connect gmail
pandapply connect browser
pandapply connect whatsapp
```

La ayuda ejecuta el Hermes detectado con `--profile NOMBRE chat -q PETICION`, fija
`HERMES_HOME` al perfil guardado y mantiene la entrada/salida de la terminal.
Es una conversación normal: el propietario interactúa con Hermes, completa las
autorizaciones y escribe `/exit` para volver a PandApply. La petición solicita
reutilizar lo existente y ayudar a instalar los componentes faltantes mediante
los mecanismos que la versión instalada soporte. No se capturan conversaciones,
QR ni tokens en PandApply, no se usa `--yolo` y no se instala otro agente ni un
daemon de configuración.

Una solicitud manual equivalente es `hermes chat -q "Configura Gmail para PandApply"`.
La forma `hermes configurar gmail` expresa la intención, pero no es un subcomando
que PandApply añada a Hermes. El flujo `chat -q` está verificado contra la CLI real
y su [documentación oficial](https://hermes-agent.nousresearch.com/docs/reference/cli-commands#hermes-chat).
Con entrada/salida sin TTY, Hermes trataría la consulta como una sola ejecución;
por eso PandApply solicita usar una terminal interactiva y no inicia la conversación.

Al volver, PandApply redetecta intérprete, habilidad y sesiones sin cambiar de
cuenta silenciosamente. Comprueba Gmail con `getProfile`; comprueba navegador
con su prueba local o CDP. Una sesión WhatsApp detectada sigue sin demostrar
gateway ni entrega. El código de salida cero de Hermes no prueba una conexión.
Si falla o se cancela, conserva los datos guardados y permite continuar pendiente.
No activa cron, postulaciones ni respuestas Gmail y no repite saludos inciertos.

## Gmail: un paso visible incluso sin credenciales detectadas

El setup siempre ofrece comprobar la cuenta conectada, guardar preferencias,
posponer Gmail o pedir a Hermes que configure/repare la conexión. Con Hermes
disponible y sin credenciales detectadas, la ayuda es la opción predeterminada.
Si la comprobación falla, ofrece ayuda y vuelve a comprobar una vez al regresar.

Al configurar pide dirección principal, filtro de mensajes, volumen por consulta,
intervalo y permisos: deshabilitado, solo consulta o respuestas con aprobación.
Guardar estos datos no comprueba OAuth ni habilita la ejecución programada.
El diagnóstico distingue `account_verified` de `configured_unverified`.

La autorización pertenece a Google Workspace de Hermes. Para una conexión nueva,
elige la ayuda de Hermes en el setup, sigue su autorización Google y vuelve con
`/exit` para comprobarla. PandApply no pide contraseñas de Google
ni copia tokens. Otros conectores Gmail de Hermes pueden necesitar un adaptador
compatible; su existencia no garantiza que el puente Google Workspace esté autorizado.

## Navegador existente: qué significa CDP

La opción de ayuda permite a Hermes revisar las dependencias del navegador o
preparar Chrome/Edge. Después selecciona en PandApply la conexión preparada.
Si es CDP, introduce el endpoint local que Hermes te indique. La prueba posterior
es la que determina el estado; configurar mediante chat no prueba un portal real.

CDP es **Chrome DevTools Protocol**: una conexión que permite a herramientas
comunicarse con Chrome o Edge. Una ventana abierta normalmente no ofrece por sí
sola esa conexión. La opción de navegador existente del setup usa CDP; la opción
administrada utiliza el navegador de Hermes para su prueba local.

Para la conexión mediante puerto, inicia una ventana con depuración remota y un
directorio de datos separado. Chrome exige un directorio distinto del perfil habitual
para estos parámetros desde Chrome 136. Véanse la [explicación oficial de Chrome](https://developer.chrome.com/blog/remote-debugging-port)
y la [guía actual de Edge](https://learn.microsoft.com/en-us/microsoft-edge/web-platform/devtools-mcp-server).

Ejemplo PowerShell para una instalación habitual de Chrome:

```powershell
& "$env:ProgramFiles\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="$env:LOCALAPPDATA\PandApply\BrowserCDP"
```

El asistente busca el ejecutable instalado y muestra un comando con su ruta.
Si usas Edge, emplea su `msedge.exe` con los mismos parámetros.

Ejemplo Linux:

```sh
google-chrome --remote-debugging-port=9222 --user-data-dir="$HOME/.local/share/pandapply/chrome-cdp"
```

En esa ventana, abre `http://127.0.0.1:9222/json/version`: debe mostrar información
del navegador. Ese endpoint se describe en la [documentación oficial de Edge](https://learn.microsoft.com/en-us/microsoft-edge/devtools/protocol/).
Introduce `127.0.0.1:9222` en PandApply. Si elegiste otro puerto, usa el mismo en
el comando y en la dirección. Mantén el puerto limitado a tu equipo. La ventana
separada tiene sus propias sesiones; tendrás que iniciar sesión allí cuando corresponda.

La comprobación actual consulta el estado de la conexión. La automatización de
portales reales mediante ese navegador todavía está pendiente.

## Panel en segundo plano

`pandapply web` y la última opción del setup inician el panel en segundo plano.
La terminal muestra dirección, usuario y contraseña y recupera el control. Puedes
cerrarla; el proceso continúa mientras el equipo esté funcionando. Esto no instala
un servicio ni configura autoarranque al encender el equipo.

```sh
pandapply web --status
pandapply web --stop
pandapply web --restart
pandapply web --foreground
```

Repetir `web` reutiliza el panel existente. La contraseña se muestra solo al crear
el proceso y no se guarda en disco; si la olvidaste, `--restart` genera otra e
invalida las sesiones anteriores. En primer plano se detiene con Ctrl+C.

El proceso recibe su contraseña por una tubería. `panel-control.json` guarda un
token de control privado, distinto de la contraseña y limitado a consultar/detener
ese proceso local. `panel.log` registra errores del servidor sin credenciales de login.
El control usa loopback, autenticación y una identidad de instancia; no termina
procesos por un PID reutilizado ni sigue redirecciones de red.
