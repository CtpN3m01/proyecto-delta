# Webs de Proyecto Delta (T49)

React/Vite, Node >=22.12. `npm ci`, `npm run dev` y `npm run build` preparan
los modelos y WASM locales. La compilación genera `index.html` (procesamiento
con login demo) y `catalog.html` (listado y descarga sin sesión). Compose publica
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

Docker escribe `/config.js` al iniciar con `DELTA_COORDINATOR_URL`,
`DELTA_PARTY_URLS` y `DELTA_STORAGE_URL`. En Vite se usan las variables
`VITE_DELTA_COORDINATOR_URL`, `VITE_DELTA_PARTY_URLS`, `VITE_DELTA_STORAGE_URL`
o los puertos locales predeterminados. Se requiere localhost o HTTPS y COOP/COEP.

`npm test` ejecuta pruebas unitarias; `npm run build` incluye TypeScript.
Playwright usa Chrome; `PLAYWRIGHT_BROWSER_PATH` permite otro binario.
Inferencia (`RUN_T49_PROBE=1`), paridad (`RUN_T49_PARITY=1`) y MPC real
(`RUN_WEB_MPC_E2E=1`) son opt-in. Ver [docs/T49.md](../docs/T49.md).
Se retiraron las pruebas que simulaban la subida del original al puente Python.
