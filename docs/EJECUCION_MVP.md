# Ejecución del MVP integrado

Integración de `base-datos` en `main`, 19 de noviembre de 2026.

PocketBase 0.42.3 administra autenticación, usuarios y roles. El SDK 0.26.2 del
frontend conserva la sesión en la pestaña y la renueva al recargar. La migración
`pb_migrations/1794880000_create_users_auth.js` configura `users` con nombre y rol
`admin`/`user`; las reglas del servidor reservan la administración de cuentas a
`admin`. No hay registro público ni cuentas predeterminadas.

El original y los tres modelos permanecen en el navegador. Los adaptadores de las
parties conservan ExternalIO y MP-SPDZ. Solo el resultado anonimizado llega a
`result-storage` (SQLite y archivos), y la segunda web lo lista y descarga sin
sesión. PocketBase no recibe videos. No se utiliza el antiguo puente Python.

## Arranque completo

Requisitos: Docker Compose, Chrome de escritorio y `MP-SPDZ/` como hermano de
`proyecto-delta/`. Node >=22.12 solo es necesario para desarrollo y pruebas locales.

Desde la raíz del repositorio, Windows PowerShell:

```powershell
$env:HOST_UID="0"
$env:HOST_GID="0"
docker compose up --build -d --wait
```

En Linux/macOS, definir `HOST_UID` y `HOST_GID` con el UID/GID del operador antes
del mismo comando. La primera compilación de MP-SPDZ puede tardar. Para reutilizar
imágenes ya construidas, usar `docker compose up -d --no-build --wait`.
`cert-init` debe terminar y Coordinator/parties/PocketBase deben estar saludables.

| Servicio | URL local |
| --- | --- |
| Procesamiento e inicio de sesión | http://localhost:8080 |
| Catálogo y descarga sin sesión | http://localhost:8081 |
| PocketBase y Dashboard | http://127.0.0.1:8090/_/ |
| Salud PocketBase | http://127.0.0.1:8090/api/health |
| Coordinator | http://localhost:8000 |
| Adaptadores de parties | http://localhost:8100, :8101, :8102 |
| Almacenamiento de resultados | http://localhost:8200 |

PocketBase queda ligado a loopback. Los otros puertos conservan la configuración
local anterior. No publicar este Compose directamente en Internet: las APIs de
MPC y resultados todavía no validan las sesiones de PocketBase.

## Primera cuenta

1. Abrir el Dashboard de PocketBase y crear el primer superusuario con el
   instalador. Si se necesita un enlace de instalación, aparece en los logs de
   PocketBase; reemplazar `0.0.0.0` por `127.0.0.1` al abrirlo localmente.
2. Dentro del Dashboard, abrir **Collections → users** y crear una cuenta con
   correo, contraseña, nombre (2–80 caracteres) y rol `admin`.
3. Entrar en la web de procesamiento con esa cuenta. Desde **Usuarios**, crear
   cuentas `user` u otros administradores.

El superusuario de PocketBase administra su Dashboard; no es una cuenta de la web.
Si el instalador no está disponible, el operador puede crear/actualizar el
superusuario desde la raíz con credenciales propias:

```powershell
docker compose exec pocketbase /pb/pocketbase superuser upsert 'tu-correo@ejemplo.com' 'TuContraseñaPropia'
```

Ese comando actualiza la contraseña si ya existe el correo; no ejecutarlo sobre
una cuenta existente sin intención de cambiarla. Las antiguas cuentas demo en
localStorage no se migran y sus contraseñas ya no permiten entrar.

## Desarrollo de ambas webs

Con PocketBase y los demás servicios Docker activos:

```powershell
cd frontend
npm ci
npm run dev
```

Un servidor sirve ambas entradas:

- Procesamiento: http://127.0.0.1:5173
- Catálogo: http://127.0.0.1:5173/catalog.html

No es necesario crear `.env` para las URLs locales predeterminadas. Para otras
URLs, copiar `frontend/.env.example` a `.env` sin sobrescribir uno existente y
reiniciar Vite. Se configuran `VITE_POCKETBASE_URL`, `VITE_DELTA_COORDINATOR_URL`,
`VITE_DELTA_PARTY_URLS` y `VITE_DELTA_STORAGE_URL`.

En Docker las URLs se inyectan al iniciar, sin recompilar JavaScript, mediante
`DELTA_POCKETBASE_URL`, `DELTA_COORDINATOR_URL`, `DELTA_PARTY_URLS` y
`DELTA_STORAGE_URL` del entorno Compose. Recrear las webs tras cambiarlas:

```powershell
docker compose up -d --force-recreate processing-web catalog-web
```

Las URLs son accesibles desde el navegador; no usar nombres internos de Compose.
Cambiar `DELTA_POCKETBASE_URL` no cambia la dirección donde escucha PocketBase.

## Datos y operación

- `pocketbase-data`: usuarios, contraseñas administradas por PocketBase y su esquema.
- `delta-results`: catálogo SQLite y archivos MP4 anonimizados de T49.
- `.runtime/party-N`: certificados propios de cada party y logs de desarrollo.

`docker compose down` conserva ambos volúmenes. `docker compose down -v` los
elimina: no usarlo para reiniciar. No se borran resultados existentes al integrar.
La cola MPC es global y volátil; no reanuda trabajos tras cerrar la pestaña o
reiniciar Coordinator. La CLI Python permanece como referencia y diagnóstico;
no ejecutarla al mismo tiempo que un trabajo de navegador.

Para trabajar solo en login: `docker compose up --build -d --wait pocketbase`,
luego `npm run dev` desde frontend. Los videos requerirán el resto del stack.

## Verificación

Regresión rápida desde la raíz:

```powershell
python -m pytest -m "not e2e" -q
cd frontend
npm test
npm run build
```

Integración real de PocketBase y web de producción, sin tocar usuarios principales:

```powershell
# Desde la raíz:
docker compose build pocketbase processing-web
# Desde frontend:
npm run test:integration
```

Requiere Chrome instalado o `PLAYWRIGHT_BROWSER_PATH` apuntando a un Chrome local.
El verificador levanta una base y una web temporales en puertos 18090 y 5173,
crea cuentas aleatorias, reinicia PocketBase, ejecuta Playwright y retira sus
contenedores y volúmenes. Las credenciales no se guardan en el repositorio.
Ambos puertos deben estar libres; detener Vite antes. Se usa el origen 5173 ya
permitido por Coordinator, almacenamiento y adaptadores, sin ampliar sus CORS.

Para incluir procesamiento real, con Compose saludable y un MP4 corto:

```powershell
$env:E2E_VIDEO_PATH="C:\ruta\video-corto.mp4"
npm run test:integration -- --with-mpc
```

Este modo añade un resultado anonimizado al catálogo principal y descarga desde
la segunda web. No ejecuta automáticamente los videos largos. Las evidencias
locales quedan en `.runtime/t49-evidence/`.

Para correr Playwright contra cuentas propias en vez de la base temporal, definir
`E2E_ADMIN_EMAIL`, `E2E_ADMIN_PASSWORD`, `E2E_USER_EMAIL` y `E2E_USER_PASSWORD`.
`E2E_POCKETBASE_URL` es opcional para la prueba directa de permisos (predeterminado
8090). La prueba de creación de usuarios deja sus cuentas en esa base; usar
preferentemente el verificador aislado.

## Estado de validación de esta integración

Pasaron 557 pruebas Python (siete E2E largos excluidos), 51 unitarias frontend,
TypeScript, Vite y los builds Docker de PocketBase y ambas webs. Las 51 sustituyen
las pruebas del servicio demo retirado por las del adaptador PocketBase; la cifra
histórica de T49 era 73.

Pasaron nueve pruebas Playwright sobre PocketBase y la web Docker reales: rutas
privadas, rechazo de credenciales, sesión tras recarga/cierre, almacenamiento de
sesión, interfaz adaptable, creación de ambos roles y correo duplicado, validación
de archivos, permisos directos del servidor y recorrido navegador → MPC →
almacenamiento → descarga. Las cuentas sobreviven al reinicio real de PocketBase.
Se verificó cambiar su URL al iniciar la misma imagen web.

El recorrido MPC usó ocho cuadros locales de `video3.mp4`, 478×850, 30 FPS:
88,910 s hasta la descarga, 22,279 s de inferencia y 33,482 s de intercambio.
La salida se decodificó independientemente: ocho cuadros grises, sin audio,
un track H.264 y SHA-256 idéntico al catálogo. No se repitieron videos largos.
El MP4 de prueba anonimizado queda en el catálogo; no se borraron resultados
anteriores. La base principal de PocketBase conserva su instalación inicial,
sin cuentas de aplicación de prueba ni contraseñas predeterminadas.

El navegador usado fue **Edge Chromium 157.0.4341.60**. No había Chrome instalado;
el Chrome for Testing guardado se cerraba al arrancar. Playwright conserva un
user-agent emulado de Chrome 156, que no identifica el ejecutable real. La
compatibilidad Chrome previa de T49 es evidencia histórica, no una ejecución
nueva de esta integración. No se verificó Brave en esta ronda.

Los contenedores y volúmenes temporales se retiraron; los servicios principales
quedaron funcionando. Los scripts Linux mantienen LF y pasan `sh -n`/`bash -n`.
Permanecen dos avisos de deprecación Python de Starlette/httpx y AnyIO.
Evidencia de esta integración, sin videos originales ni credenciales:
[base-datos-validation.json](base-datos-validation.json).
El detalle histórico de modelos/MPC permanece en [T49.md](T49.md).
