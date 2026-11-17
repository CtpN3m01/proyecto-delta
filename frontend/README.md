# TEC PeopleFlow · frontend web

Interfaz local de React y TypeScript para iniciar sesión con PocketBase, administrar cuentas por rol y anonimizar video. El procesamiento requiere el puente local, el Coordinator y las parties MPC.

## Ejecutar

Requiere Node.js **22.12 o posterior** y npm. Desde esta carpeta:

```sh
cp .env.example .env
npm install
npm run dev
```

Abre la dirección que muestre Vite, normalmente `http://127.0.0.1:5173`. Si PowerShell bloquea `npm.ps1`, usa `npm.cmd install` y `npm.cmd run dev`; la misma alternativa sirve para los demás comandos.

Las rutas usan `HashRouter`: `/#/login`, `/#/dashboard` y `/#/admin/users`. El directorio generado `dist/` puede servirse como sitio estático sin reglas de reescritura.

## Autenticación y cuentas

La autenticación usa PocketBase en `http://127.0.0.1:8090` por defecto. Configura `VITE_POCKETBASE_URL` en `.env` si la API está en otra URL accesible desde el navegador. Levanta PocketBase desde la raíz con `docker compose up --build -d`; la migración crea la colección `users` y el volumen `pocketbase-data` conserva sus registros.

Crea el superusuario desde la raíz del proyecto con `docker compose exec pocketbase /pb/pocketbase superuser upsert 'tu-correo@ejemplo.com' 'tu-contraseña'` y luego abre el Dashboard (`http://127.0.0.1:8090/_/`). En **Collections → users**, crea la primera cuenta de aplicación con el rol `admin`. Después, ese administrador puede dar de alta cuentas `admin` o `user` desde **Usuarios**. También puedes usar el enlace temporal de instalación que aparece en `docker compose logs pocketbase`; cambia `0.0.0.0` por `127.0.0.1` si aparece en la URL. No hay registro público ni cuentas precargadas. Las reglas de la colección PocketBase restringen las operaciones administrativas en el servidor. La sesión del SDK queda en `sessionStorage` y **Cerrar sesión** la elimina.

Para levantar el conjunto completo de servicios, crear las cuentas iniciales y consultar los comandos por sistema operativo, sigue la [guía de ejecución del MVP web](../docs/EJECUCION_MVP.md).

## Anonimizar un video desde la interfaz

La interfaz web no ejecuta Python directamente. Para iniciar la anonimización,
el navegador se comunica con un puente HTTP local que guarda temporalmente el
MP4 y ejecuta el cliente existente de `src/client`. El archivo se envía por
`localhost` al puente; no se carga al Coordinator. El cliente preprocesa y
detecta rostros y placas localmente, coordina las parties MPC, y reconstruye el
resultado en `output/web/<job>/<video_id>/reconstructed.mp4`.

Primero levanta el Coordinator y las tres parties siguiendo el
[README principal](../README.md#construir-y-levantar). Instala el proyecto
Python (`python -m pip install -e .`) y luego inicia el puente desde la raíz:

```sh
uvicorn client.local_api:app --host 127.0.0.1 --port 8001
```

Inicia el frontend como se describe arriba. Por defecto, acepta peticiones web
desde Vite en `localhost:5173` y sirve el resultado descargable. Para otro
origen, configura `DELTA_WEB_ORIGINS` con una lista separada por comas en el
proceso del puente. `VITE_DELTA_CLIENT_URL` cambia la URL del puente local
(por defecto `http://127.0.0.1:8001`).

Este puente HTTP está pensado para desarrollo local. Si el frontend se publica
en un sitio HTTPS remoto, permitir su origen en CORS no basta: el navegador
puede bloquear el acceso a un servicio HTTP local. Ese despliegue requiere
proteger también el puente con HTTPS y configurar el acceso local del navegador.

## Selección y vista previa del video

Selecciona un archivo MP4 válido de hasta **20 segundos**. El navegador lee sus metadatos y muestra una vista previa del video original mediante una URL local `blob:`. Al seleccionar el archivo aún no se envía; se transfiere al servicio `localhost` únicamente cuando se inicia la anonimización.

**Anonimizar video** inicia el procesamiento real del cliente local; el botón queda habilitado cuando se haya iniciado el puente y levantado Coordinator/parties. El límite de subida del puente es 256 MiB. El resultado se descarga desde la computadora del cliente.

## Verificar

```sh
npm run build
npm test
npm run test:e2e
```

`build` comprueba TypeScript y genera `dist/`; `test` ejecuta las pruebas unitarias. Las pruebas E2E usan Microsoft Edge ya instalado y arrancan Vite en `127.0.0.1:5173` si no está ejecutándose. No descargan ni instalan navegadores. Para comprobar otra instancia, define `PLAYWRIGHT_BASE_URL` con su dirección antes de ejecutar `test:e2e`.

Las pruebas de video generan un MP4 breve en memoria con `canvas` y `MediaRecorder` del propio Edge, sin guardar un video en el repositorio. Puedes indicar un archivo real compatible con el navegador, válido y de hasta 20 segundos; las pruebas lo leen sin copiarlo ni modificarlo:

```powershell
$env:E2E_VIDEO_PATH = 'C:\ruta\video-corto.mp4'
npm.cmd run test:e2e
```

La suite comprueba acceso por roles, creación de cuentas y reglas de PocketBase, errores de selección, vista previa original y el contrato HTTP del procesamiento mediante respuestas simuladas. Para las pruebas autenticadas define `E2E_ADMIN_EMAIL`, `E2E_ADMIN_PASSWORD`, `E2E_USER_EMAIL` y `E2E_USER_PASSWORD` con cuentas existentes de cada rol. Los informes quedan en `playwright-report/` y las evidencias de fallos en `test-results/`. Esos directorios, `node_modules/` y `dist/` están excluidos de Git.
