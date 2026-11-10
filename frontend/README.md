# TEC PeopleFlow · frontend web

Interfaz local de React y TypeScript para el acceso por roles y la anonimización de video. El login sigue siendo una demostración del navegador; el procesamiento de video sí requiere el puente local, el Coordinator y las parties MPC.

## Ejecutar

Requiere Node.js **22.12 o posterior** y npm. Desde esta carpeta:

```sh
npm install
npm run dev
```

Abre la dirección que muestre Vite, normalmente `http://127.0.0.1:5173`. Si PowerShell bloquea `npm.ps1`, usa `npm.cmd install` y `npm.cmd run dev`; la misma alternativa sirve para los demás comandos.

Las rutas usan `HashRouter`: `/#/login`, `/#/dashboard` y `/#/admin/users`. El directorio generado `dist/` puede servirse como sitio estático sin reglas de reescritura.

## Cuentas de demostración

| Rol | Correo | Contraseña |
| --- | --- | --- |
| Administrador | `admin@tecpeopleflow.local` | `AdminDemo123!` |
| Usuario | `usuario@tecpeopleflow.local` | `UsuarioDemo123!` |

El administrador puede crear cuentas de ambos roles desde **Usuarios**. No hay registro público. El usuario normal sólo accede a su espacio; las rutas de administración comprueban el rol.

Las cuentas y sus contraseñas derivadas con PBKDF2 se guardan en `localStorage`; la sesión de la pestaña se guarda en `sessionStorage`. Recargar mantiene esa sesión y **Cerrar sesión** la elimina. Es una demostración del navegador: los datos pueden inspeccionarse o modificarse localmente y no sustituyen autenticación ni autorización de un servidor. Para reiniciar las cuentas, borra los datos del sitio en el navegador.

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

La suite comprueba el acceso por roles, la creación de usuarios, los errores de selección, la vista previa original y el contrato HTTP del procesamiento mediante respuestas simuladas. Los informes quedan en `playwright-report/` y las evidencias de fallos en `test-results/`. Esos directorios, `node_modules/` y `dist/` están excluidos de Git.
