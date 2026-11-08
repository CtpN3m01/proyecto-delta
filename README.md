# Proyecto Delta — MVP MPC Sprint 1

MVP funcional de infraestructura MPC para video. Un cliente confiable puede
detectar rostros con YuNet y placas con LPD-YuNet, juntos o por separado, sobre
los cuadros seleccionados a color y resolución original. Después prepara los
píxeles grayscale, por defecto hasta 640x480 y 10 FPS, conservando la proporción
y sin ampliar videos pequeños. ExternalIO introduce los píxeles privados y
las parties aplican máscaras públicas para ocultar las regiones detectadas.
El modo predeterminado sigue siendo identidad; anonimizar exige selección explícita.
El cliente reconstruye el resultado en:

```text
output/<video_id>/reconstructed.mp4
```

El MP4 original y el resultado no anonimizado nunca se envían al Coordinator ni
a una party individual.

## Arquitectura

```text
Cliente confiable
  ├─ metadata/estado HTTP ───────────────> Coordinator FastAPI
  ├─ control HTTP ───────────────────────> Node Agents P0/P1/P2
  └─ pixels uint8 privados por ExternalIO
          ├──────────────────────────────> replicated-ring Party 0
          ├──────────────────────────────> replicated-ring Party 1
          └──────────────────────────────> replicated-ring Party 2
                                             │
                         delta_video_anonymize.mpc
                         (identity / anonymize)
                                             │
                         reveal_to_clients (solo al cliente)
                                             ▼
                              reconstructed.mp4 local
```

Cada servicio `party-N` contiene un Node Agent FastAPI y un proceso real
`replicated-ring-party.x`. FastAPI solo controla el job; MP-SPDZ realiza el
sharing, la comunicación party-to-party y el cálculo secreto. El Node Agent
inicia o reinicia el runtime al preparar un job y lo detiene durante `cleanup`;
así un nuevo job funciona incluso después del timeout inactivo de ExternalIO.

La interfaz web se conecta a un puente FastAPI local (`client.local_api`) en
`127.0.0.1:8001`. Ese puente ejecuta el mismo cliente Python que la CLI en la
computadora del usuario; el MP4 no se envía al Coordinator. El Coordinator
recibe metadata y coordina las parties, y el resultado reconstruido queda bajo
`output/web/`.

Decisiones del MVP:

- exactamente tres parties;
- replicated secret sharing sobre ring de 64 bits;
- modelo semi-honesto de desarrollo (`program.active = False`);
- programa `delta_video_anonymize.mpc` con selección explícita; se conserva
  `delta_video_identity.mpc` como programa anterior compatible;
- bloques de 4096 pixels;
- un único job activo;
- estado y manifests solo en memoria;
- certificados autofirmados de desarrollo;
- sin archivos persistentes de shares ni staging de video.

## Requisitos

- Docker Desktop/Engine con Docker Compose;
- el clon de MP-SPDZ como hermano del repositorio:

  ```text
  ProyectoDelta/
  ├── proyecto-delta/
  └── MP-SPDZ/
  ```

- Python 3.10 o posterior si se ejecutará la CLI en el host.

La primera construcción compila `replicated-ring-party.x` y puede tardar varios
minutos. Las reconstrucciones posteriores usan la caché de Docker.

## Construir y levantar

Desde `proyecto-delta/`:

```bash
docker compose up --build -d
docker compose ps
```

Compose levanta:

| Servicio | Puerto host | Responsabilidad |
|---|---:|---|
| `coordinator-api` | 8000 | UUID, metadata y ciclo del job |
| `party-0` | 8100 / 14000 | Node Agent / ExternalIO P0 |
| `party-1` | 8101 / 14001 | Node Agent / ExternalIO P1 |
| `party-2` | 8102 / 14002 | Node Agent / ExternalIO P2 |
| `cert-init` | — | genera certificados de desarrollo y termina |

Los runtimes usan internamente `party-0:5000`, `party-1:5001` y
`party-2:5002`. `docker compose ps` debe mostrar saludables al Coordinator y a
las tres parties.

## Ejecutar un video

### Opción A: CLI en el host

En PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install -e .
python -m client upload C:\ruta\video.mp4
```

Linux/macOS:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install -e .
python -m client upload /ruta/video.mp4
```

El comando equivalente instalado es:

```bash
delta upload /ruta/video.mp4
```

#### Interfaz web

Para ejecutar el API del cliente se debe tener el entorno virtual activado.

Para usar la interfaz como lanzador del cliente Python, inicia los servicios MPC
de arriba y, desde la raíz del repositorio, instala e inicia el puente en la
computadora que tiene el video:

```bash
python -m pip install -e .
uvicorn client.local_api:app --host 127.0.0.1 --port 8001
```

En otra terminal, inicia el frontend desde `frontend/` con `npm install` y
`npm run dev`. El botón **Anonimizar video** envía el archivo al puente por
loopback y lanza `python -m client upload ... --processing-mode anonymize
--detect-faces --detect-plates`. El archivo fuente se borra al terminar; los
resultados permanecen bajo `output/web/`. El puente acepta por defecto los
orígenes locales de Vite y Preview; para otro origen configura
`DELTA_WEB_ORIGINS` con sus URLs exactas, separadas por comas.

### Resolución para MPC

`MPC_MAX_WIDTH` y `MPC_MAX_HEIGHT` configuran la caja máxima en el cliente,
Coordinator y parties. El perfil predeterminado es 640x480; si el alto no se
indica, se deriva como 3/4 del ancho. La imagen conserva su propia proporción
y se alinea a dimensiones pares para MP4. YuNet sigue recibiendo los cuadros
originales a color antes de esta reducción; los píxeles MPC siguen en gris.

La CLI puede elegir una caja menor que la admitida por los servicios:

```bash
python -m client upload /ruta/video.mp4 --mpc-max-width 320 --mpc-max-height 240
```

Para cambiar el máximo admitido por los servicios, configurar ambas variables
en `.env` y recrear Compose. Para la CLI del host se usan las mismas variables
de entorno o los argumentos anteriores; no se carga `.env` automáticamente.
Los perfiles admitidos están acotados a 640x480; no se cambió el protocolo MPC.

Se probaron cuatro cuadros a 2 FPS mediante tres parties reales: en la medición
final con muestreo de memoria, MPC tardó 17,02 s a 320x240, 37,12 s a 480x360
y 65,09 s a 640x480 en Docker local. El flujo completo tardó 18,15 / 44,21 /
72,46 s respectivamente. ExternalIO privado intercambió 22,12 / 49,85 / 88,48 MB
de aplicación (envío + recepción; no incluye TLS/TCP ni tráfico entre parties).

### FPS para MPC

El cliente muestrea hasta **10 FPS** por defecto y conserva el límite de
20 segundos: como máximo 200 cuadros. Si el original tiene menos FPS, conserva
su frecuencia; no duplica ni inventa cuadros. YuNet analiza cada cuadro
seleccionado en su resolución original y a color, antes de gris/resize.

Para volver al menor costo de 5 FPS, sin cambiar la resolución:

```bash
python -m client upload /ruta/video.mp4 --mpc-fps 5
```

`--mpc-fps` acepta valores mayores que 0 y hasta 10. La reconstrucción utiliza
los FPS del muestreo para mantener la duración, no para acelerar el video.
Pasar de 5 a 10 FPS con la misma duración y resolución implica aproximadamente
el doble de cuadros y comunicación; el tiempo real debe medirse. No cambia el
protocolo ni el programa MPC de identidad.

Si Compose ya estaba levantado con el límite anterior de 5 FPS/100 cuadros,
ejecutar `docker compose up --build -d` para actualizar también las validaciones
del Coordinator y las parties. Cambiar solo el cliente no basta.

Se compararon ambos perfiles con el mismo clip original a color de 640x480,
30 FPS y un segundo, mediante las tres parties reales del Compose habitual:

| Muestreo | Cuadros procesados | Tiempo MPC | Flujo CLI completo | ExternalIO privado (MB) |
|---|---:|---:|---:|---:|
| 5 FPS (`--mpc-fps 5`) | 5 | 46,76 s | 53,53 s | 110,61 |
| 10 FPS (predeterminado) | 10 | 95,69 s | 102,64 s | 221,21 |

El tráfico medido suma bytes de aplicación enviados y recibidos; excluye TLS/TCP,
la cabecera pública y comunicación entre parties. Ambos casos conservaron
identidad exacta antes de codificar, dimensiones y orden temporal. YuNet recibió
los cuadros originales BGR. A 10 FPS se observaron máximos de 54,60–55,95 MiB
por party y 107,84 MiB de memoria del cliente; las parties se midieron por
muestreo, no mediante un pico instantáneo garantizado. Los artefactos locales
quedan bajo `.runtime/fps-evaluation/`.

El máximo de entrada no demuestra rendimiento aceptable: no se ha verificado
un video completo de 20 segundos a 640x480 y 10 FPS ni ejecución en Raspberry Pi.

### Opción B: cliente confiable en Docker

Si el video se encuentra dentro de la carpeta del repositorio:

```bash
docker compose run --rm delta-client upload /workspace/video.mp4
```

Solo `delta-client` monta el repositorio que contiene el video. Coordinator y
parties no tienen ese volumen.

## Flujo y validaciones

### Anonimización genérica T025

`upload` conserva identidad por defecto y lo indica en consola. Para detectar
rostros con YuNet y ocultarlos mediante cajas negras dentro de MPC:

```bash
python -m client upload /ruta/video.mp4 --processing-mode anonymize --detect-faces
```

Para ocultar rostros y placas en el mismo trabajo:

```powershell
python -m client upload "..\video3.mp4" --processing-mode anonymize --detect-faces --detect-plates
```

Ambos detectores se pueden combinar. Las detecciones automáticas no se mezclan
con `--regions-json` ni con un plan manual. El blur no está implementado:
el circuito existente reemplaza con cero (negro) cada píxel dentro de las cajas.
La CLI admite además JSON de diagnóstico con resultados explícitos por cuadro:

```bash
python -m client upload /ruta/video.mp4 --processing-mode anonymize --regions-json /ruta/regiones.json
```

El archivo requiere las dimensiones MPC reales y resultados explícitos para
todos los cuadros, incluidos los vacíos. Ver formato e integración en
[T25](TareasDeInvestigacion/T25.md) y contrato en [T24](TareasDeInvestigacion/T24.md).
Las máscaras se envían públicamente por bloques de 4096 posiciones; los píxeles
originales entran privadamente y MP-SPDZ calcula `pixel * (1 - máscara)` antes
de revelar solo el resultado al cliente. No hay fallback a identidad. Se debe
reconstruir Compose para usar `MPC_PROGRAM=delta_video_anonymize`.

### Flujo de identidad compatible

La CLI:

1. valida el MP4 y el límite de 20 segundos;
2. ejecuta localmente YuNet en los frames muestreados, anota rostros detectados,
   reduce resolución/FPS y convierte a grayscale `uint8`;
3. registra metadata pública y obtiene un UUID;
4. prepara los tres Node Agents;
5. envía pixels privados a los tres runtimes mediante ExternalIO;
6. ejecuta identidad y revela cada bloque exclusivamente al cliente;
7. compara exactamente los bytes enviados y recibidos antes de codificar;
8. escribe y vuelve a abrir `reconstructed.mp4`;
9. marca `COMPLETED` y limpia el estado temporal de las parties.

Estados del Coordinator:

```text
REGISTERED → PREPARING → MPC_READY → PROCESSING → COMPLETED
                                             └─→ FAILED
```

Un segundo registro mientras el primero no se haya limpiado recibe `409`.

## Pruebas

Instalar dependencias de desarrollo y ejecutar la suite rápida:

```bash
python -m pip install -r requirements-dev.txt
python -m pip install -e .
python -m pytest -m "not e2e"
```

Con Compose actualizado y saludable, ejecutar el smoke test real
(64x48, 10 FPS, 1 s; original a 20 FPS):

PowerShell:

```powershell
$env:RUN_MPC_E2E="1"
python -m pytest tests/integration/test_mpc_e2e.py -s
```

Linux/macOS:

```bash
RUN_MPC_E2E=1 python -m pytest tests/integration/test_mpc_e2e.py -s
```

## Apagar y limpiar

```bash
docker compose down
```

Los jobs no crean shares ni archivos de entrada en las parties. `.runtime/`
conserva certificados de desarrollo reutilizables y logs mínimos de los
runtimes. Los resultados permanecen bajo `output/` en el cliente.

## Limitaciones del Sprint 1

- la CLI conserva identidad por defecto; anonimización negra exige selección
  explícita. YuNet y LPD-YuNet detectan en el cliente y alimentan la máscara MPC;
  pueden omitir regiones o generar falsos positivos. No se garantiza cobertura total;
- las tres parties viven en un solo host y una misma organización;
- los certificados son de desarrollo y la imagen compartida puede ver el mismo
  directorio de certificados;
- no hay base de datos ni recuperación tras reiniciar el Coordinator;
- se procesa un video a la vez;
- límite de entrada: 20 s y 10 FPS (hasta 200 cuadros), grayscale; caja espacial
  configurable, 640x480 por defecto, verificada únicamente en clips pequeños;
- no se ha preparado todavía el despliegue ARM/Raspberry Pi.
