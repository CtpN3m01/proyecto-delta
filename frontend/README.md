# TEC PeopleFlow · frontend de demostración

Interfaz local de React y TypeScript para explorar el acceso por roles y el recorrido de un video. Funciona sin levantar la API, MPC ni modelos del proyecto.

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

## Video y recorrido

Selecciona un archivo MP4 válido de hasta **20 segundos**. El navegador lee sus metadatos y muestra una vista previa del video original mediante una URL local `blob:`. El archivo no se sube a ningún servicio.

**Simular recorrido** presenta cuatro etapas de demostración, permite cancelar y termina sin procesar ni anonimizar el video. No ejecuta detección, MPC ni modelos, y no genera archivos ni ofrece descargas de resultados.

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

La suite comprueba el acceso por roles, la creación de usuarios, los errores de selección, la vista previa original, la simulación y la ausencia de peticiones de subida o descargas durante ese recorrido. Los informes quedan en `playwright-report/` y las evidencias de fallos en `test-results/`. Esos directorios, `node_modules/` y `dist/` están excluidos de Git.
