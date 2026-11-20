# Proyecto Delta — cliente web y MPC (T49)

El usuario inicia sesión con su cuenta de PocketBase y selecciona un MP4. El navegador ejecuta
YuNet, LPD-YuNet y YOLOX-S, prepara entradas privadas y se conecta a cada party.
MP-SPDZ aplica las máscaras públicas. El navegador verifica cada píxel de salida,
genera un MP4 gris sin audio y envía únicamente ese resultado al almacenamiento.
Una segunda web permite descargarlo. Se retiró el puente `client-api` que recibía
el original; la CLI Python se conserva para referencias, diagnóstico y pruebas.

## Levantar

El operador necesita Docker Compose y `MP-SPDZ/` como hermano de este repositorio.
El usuario de las webs solo necesita Chrome de escritorio.

```powershell
# Desde proyecto-delta. Windows con Docker Desktop:
$env:HOST_UID="0"
$env:HOST_GID="0"
docker compose up --build -d --wait
```

En Linux, definir `HOST_UID` y `HOST_GID` con el UID/GID del operador, que debe
poder escribir en `.runtime/`. La primera compilación de MP-SPDZ puede tardar.
El circuito actual usa ring de 64 bits y bloques de **262144** píxeles.
No reutilizar un circuito histórico compilado para 4096.

| Servicio | Dirección local | Función |
| --- | --- | --- |
| Web de procesamiento | http://localhost:8080 | Login con PocketBase; procesamiento automático |
| Web de consulta | http://localhost:8081 | Listado y descarga sin sesión |
| Coordinator | http://localhost:8000 | Cola FIFO global; solo metadatos |
| Parties/adaptadores | http://localhost:8100, :8101, :8102 | Un WebSocket independiente por party |
| Almacenamiento | http://localhost:8200 | SQLite y archivos en volumen `delta-results` |
| PocketBase | http://127.0.0.1:8090 | Autenticación y usuarios en volumen `pocketbase-data` |

No hay cuentas ni contraseñas predeterminadas. La primera vez, crea el superusuario
de PocketBase en http://127.0.0.1:8090/_/ y, desde su Dashboard, una cuenta en
`users` con nombre y rol `admin`. Esa cuenta inicia sesión en la web y crea las
demás desde **Usuarios**. El superusuario de PocketBase administra la base y no
se usa para entrar al frontend. Los usuarios de la antigua demo local no se migran.
Instrucciones completas: [docs/EJECUCION_MVP.md](docs/EJECUCION_MVP.md).

PocketBase valida autenticación y permisos de usuarios en el servidor. Las APIs
de control MPC y almacenamiento mantienen el contrato T49 sin autenticación;
este Compose sigue destinado al entorno local y no ofrece protección de extremo
a extremo para una publicación en Internet.

Ambas webs leen `DELTA_STORAGE_URL` al iniciar sus contenedores. También se
configuran `DELTA_POCKETBASE_URL`, `DELTA_COORDINATOR_URL`, `DELTA_PARTY_URLS` y `DELTA_WEB_ORIGINS`.
Ver [.env.example](.env.example). Recrear las webs al cambiar las direcciones.
El servidor sustituto debe conservar el contrato de [docs/T49.md](docs/T49.md).

```powershell
docker compose up -d --force-recreate processing-web catalog-web
docker compose down
```

`down` conserva usuarios y resultados; `down -v` elimina ambos volúmenes. La cola es volátil,
requiere un único proceso Uvicorn y no reanuda trabajos al cerrar la pestaña o
reiniciar el Coordinator. Solo se procesa un video en MPC a la vez.

## Desarrollo y pruebas

```powershell
python -m pip install -r requirements-dev.txt
python -m pip install -e .
python -m pytest -m "not e2e" -q
cd frontend
npm ci
npm test -- --silent
npm run build
npm run dev
```

`predev` y `prebuild` preparan modelos, licencias y runtimes WASM locales.
No se descargan recursos desde un CDN durante el procesamiento.
Los mismos pesos ONNX se ejecutan mediante WASM; solo se adaptan las declaraciones
de dimensiones de YuNet/LPD para admitir inferencia nativa.

Con Docker saludable y los tres originales junto al repositorio, desde frontend:

```powershell
$env:RUN_WEB_MPC_E2E="1"
$env:PLAYWRIGHT_BASE_URL="http://localhost:8080"
$env:E2E_USER_EMAIL="cuenta-real@ejemplo.com"
$env:E2E_USER_PASSWORD="contraseña-de-esa-cuenta"
# Opcional: $env:PLAYWRIGHT_BROWSER_PATH="C:\ruta\chrome.exe"
npx playwright test t49-real --reporter=list
```

Los E2E reales pueden tardar mucho. Evidencias locales: `.runtime/t49-evidence/`.
Para verificar login, roles, persistencia y las webs con cuentas desechables:

```powershell
# Primero, desde la raíz: docker compose build pocketbase processing-web
# Luego, desde frontend; requiere Chrome instalado o PLAYWRIGHT_BROWSER_PATH:
npm run test:integration
# Opcional: incluir MPC con un MP4 corto y el resto de Compose saludable:
$env:E2E_VIDEO_PATH="C:\ruta\video-corto.mp4"
npm run test:integration -- --with-mpc
```

El verificador usa puertos 5173/18090 (deben estar libres), una base temporal y contraseñas aleatorias;
retira sus contenedores/volúmenes al terminar. No crea cuentas en la base principal.
El modo `--with-mpc` añade un resultado anonimizado al catálogo principal.

La prueba de paridad usa seis PNG locales generados por
`python scripts/t49_reference.py`; ejecutar `RUN_T49_PARITY=1` con Playwright
`t49-parity` contra Vite. Los PNG solo se transfieren a un worker local.
La CLI sigue disponible para referencia: `python -m client upload ../video3.mp4
--processing-mode anonymize --detect-faces --detect-plates --count-objects`.
No ejecutar la CLI simultáneamente con trabajos de navegador.

## Privacidad y límites

Cada adaptador solo se conecta a su runtime y verifica su certificado TLS.
Las contribuciones se suman exclusivamente en el navegador. Cada contenedor
monta su propia llave de party, certificados públicos y la llave de transporte
C0; no monta las llaves privadas de las otras parties. Las máscaras revelan
posiciones, como en el circuito existente.

Se conserva MP-SPDZ semi-honesto. Este Compose en un único host no demuestra
independencia entre organizaciones ni protección frente a colusión del operador
que administra todas las parties. El despliegue remoto requiere HTTPS/WSS y
configuración de identidad y operación; este MVP no se publicó en Internet.

Perfil: hasta 30 FPS y 1920×1080, proporción conservada, sin ampliar y dimensiones
pares. Se liberan los cuadros decodificados conforme se procesan. El original
comprimido y la salida comprimida todavía ocupan memoria proporcional al video.
FFmpeg/WASM tiene límites adicionales de memoria y su fallback es más lento.
No se garantiza capacidad de 30 minutos/30 GB ni compatibilidad universal de MP4.
Los modelos pueden omitir regiones; no se garantiza cobertura total ni conteo
perfecto. La salida se verifica antes del códec, que introduce pérdidas.

Contrato, implementación y evidencia medida: [docs/T49.md](docs/T49.md).
La documentación T09–T46 conserva contexto histórico; sus referencias al puente
Python y a bloques de 4096 no describen la web T49.
