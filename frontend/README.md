# Webs de Proyecto Delta (T49)

React/Vite, Node >=22.12. `npm ci`, `npm run dev` y `npm run build` preparan
los modelos y WASM locales. La compilación genera `index.html` (procesamiento
con login PocketBase) y `catalog.html` (listado y descarga sin sesión). Compose publica
las webs en 8080 y 8081. Ver [README principal](../README.md).

Al seleccionar un MP4, un worker ejecuta los tres modelos, decodifica cuadros,
prepara máscaras, intercambia mensajes privados con las parties y valida la
salida antes de codificar. WebCodecs es la primera opción; FFmpeg/WASM local
cubre MPEG-4 Part 2 y la codificación alternativa. El dashboard envía el resultado
al almacenamiento. La descarga se hace desde la segunda web.

`public/models/` y `public/vendor/` son recursos generados e ignorados por Git.
`scripts/prepare-assets.cjs` conserva los pesos y operadores ONNX, adapta los
metadatos de dimensiones y publica hashes para detectar daños. Conserva licencias.
No hay descargas desde un CDN durante el procesamiento.

Docker escribe `/config.js` al iniciar con `DELTA_POCKETBASE_URL`, `DELTA_COORDINATOR_URL`,
`DELTA_PARTY_URLS` y `DELTA_STORAGE_URL`. En Vite se usan las variables
`VITE_POCKETBASE_URL`, `VITE_DELTA_COORDINATOR_URL`, `VITE_DELTA_PARTY_URLS`, `VITE_DELTA_STORAGE_URL`
o los puertos locales predeterminados. Se requiere localhost o HTTPS y COOP/COEP.

`npm test` ejecuta pruebas unitarias; `npm run build` incluye TypeScript.
Playwright usa Chrome; `PLAYWRIGHT_BROWSER_PATH` permite otro binario.
Inferencia (`RUN_T49_PROBE=1`), paridad (`RUN_T49_PARITY=1`) y MPC real
(`RUN_WEB_MPC_E2E=1`) son opt-in. Ver [docs/T49.md](../docs/T49.md).
Se retiraron las pruebas que simulaban la subida del original al puente Python.

La autenticación usa `users` de PocketBase; solo el rol `admin` puede listar y
crear cuentas, también por las reglas del servidor. No hay cuentas precargadas.
El token y el registro autenticado viven en `sessionStorage`; las contraseñas
no se guardan en el navegador. Recargar restaura/renueva la sesión; cerrar sesión
la elimina. La administración inicial se explica en
[EJECUCION_MVP.md](../docs/EJECUCION_MVP.md).

Un solo `npm run dev` sirve procesamiento en `/` y catálogo en `/catalog.html`.
Copiar `.env.example` a `.env` solo si se requieren URLs distintas.

`npm run test:integration` crea una instancia temporal real de PocketBase y una
web Docker en 18090/5173 (detener Vite antes), prepara cuentas aleatorias, reinicia la base, ejecuta
Playwright y retira ambos contenedores. Construir antes las imágenes con
`docker compose build pocketbase processing-web`. Con `-- --with-mpc` y
`E2E_VIDEO_PATH` añade el recorrido MPC/almacenamiento/descarga de un MP4 corto.
Para correr Playwright contra cuentas propias, definir `E2E_ADMIN_EMAIL`,
`E2E_ADMIN_PASSWORD`, `E2E_USER_EMAIL` y `E2E_USER_PASSWORD`; la prueba de creación
de cuentas conserva las cuentas creadas en esa base. Usar preferentemente el
verificador aislado. El catálogo continúa público y no requiere PocketBase.
