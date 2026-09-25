# Guía simple de Proyecto Delta

Esta guía explica qué hace el proyecto, cómo se relacionan sus partes y dónde se encuentra cada cosa. Está dividida en dos niveles:

1. una explicación sencilla, pensada para alguien que no conoce MPC;
2. una explicación técnica para quienes van a trabajar en el código.

Para los comandos de instalación y ejecución, consultar también `README.md`.

## 1. Explicación sencilla

### ¿Qué problema resuelve?

Proyecto Delta demuestra que un video puede procesarse mediante **Multi-Party Computation (MPC)** sin entregar el video completo a un servidor central ni a una sola party.

En este MVP el cálculo es intencionalmente sencillo: devuelve los mismos píxeles que recibió. Esto permite comprobar que toda la infraestructura MPC funciona antes de agregar Computer Vision, detección de rostros o anonimización.

El video reconstruido queda solamente en la computadora del cliente:

```text
output/<video_id>/reconstructed.mp4
```

### Una analogía

Se puede imaginar el sistema de esta forma:

- **Cliente confiable:** la persona dueña del video.
- **Coordinator:** una recepcionista que asigna un número de trabajo y lleva el estado, pero nunca ve el video.
- **Tres parties:** tres calculadoras que colaboran. Cada una recibe información secreta incompleta y ninguna puede ver el video por sí sola.
- **MP-SPDZ:** el sistema criptográfico que permite que las tres calculadoras trabajen juntas.
- **ExternalIO:** el canal oficial por el cual el cliente entrega datos privados a MP-SPDZ y recibe el resultado autorizado.
- **Programa MPC:** las instrucciones que ejecutan las tres parties. En este sprint hace una operación identidad.

### ¿Qué sucede al ejecutar `python -m client upload video.mp4`?

```text
Video original en el cliente
          │
          ▼
Validación y preprocesamiento local
          │
          ▼
Píxeles grayscale pequeños
          │
          ├────────── metadata ──────────> Coordinator
          │
          └──── entrada privada MPC ─────> Party 0
                                      ├──> Party 1
                                      └──> Party 2
                                               │
                                               ▼
                                  delta_video_identity.mpc
                                               │
                                               ▼
                                  resultado autorizado al cliente
                                               │
                                               ▼
                              output/<video_id>/reconstructed.mp4
```

Paso a paso:

1. El cliente abre el MP4 localmente.
2. Comprueba que dure como máximo 20 segundos.
3. Reduce el video a un máximo de 320×240, máximo 5 FPS y escala de grises.
4. Convierte los frames a números `uint8` entre 0 y 255.
5. El Coordinator crea un UUID y registra únicamente metadata no sensible.
6. Los tres Node Agents preparan sus procesos MP-SPDZ.
7. ExternalIO distribuye los píxeles como entrada privada compatible con el protocolo.
8. Las tres parties ejecutan juntas el programa identidad.
9. El resultado se revela únicamente al cliente que inició el trabajo.
10. El cliente comprueba que los bytes recibidos sean iguales a los enviados.
11. El cliente crea y valida `reconstructed.mp4`.
12. Las parties limpian el job y detienen los runtimes temporales.

El resultado no será idéntico al archivo MP4 original porque primero se reduce resolución/FPS, se convierte a grayscale y finalmente se vuelve a codificar como MP4. La identidad se verifica exactamente sobre los píxeles preprocesados, antes de esa codificación final.

### ¿Qué no hace todavía?

- No detecta rostros ni placas.
- No aplica blur ni anonimización.
- No procesa múltiples trabajos al mismo tiempo.
- No utiliza base de datos.
- No está desplegado en Raspberry Pi.
- No busca procesamiento en tiempo real.

## 2. Conceptos importantes

### MPC

Multi-Party Computation permite calcular sobre datos secretos entre varias parties. El resultado acordado puede revelarse sin que una sola party tenga que recibir el dato original completo.

### Party

Una party es uno de los tres participantes del protocolo MPC. En este proyecto cada party lógica contiene:

- un **Node Agent FastAPI**, que maneja estados y controla el proceso;
- un proceso real `replicated-ring-party.x`, que ejecuta la criptografía de MP-SPDZ.

Un contenedor o una carpeta con nombre `party` no sería suficiente por sí solo: lo importante es que exista el runtime real de MP-SPDZ.

### Coordinator

Es el plano de control. Crea el UUID, guarda el estado en memoria, conoce las direcciones de las parties y recibe confirmaciones. Nunca recibe los píxeles ni el MP4.

### ExternalIO

Es la interfaz oficial de MP-SPDZ usada por el cliente. Conecta una instancia de cliente con las tres parties y crea la entrada privada que entiende el protocolo. Sustituye el esquema XOR provisional de T09.

### Node Agent

Es la API FastAPI que vive junto a cada party. Prepara el job, inicia o verifica el runtime, reporta estado y hace cleanup. No realiza criptografía y no recibe píxeles por HTTP.

## 3. Mapa general del repositorio

```text
proyecto-delta/
├── src/                         código Python de la aplicación
│   ├── client/                  cliente confiable
│   ├── coordinator/             API central de control
│   ├── mpc/                     puente Python hacia ExternalIO
│   └── party_receiver/          Node Agent de cada party
├── mpc/                         archivos que usa MP-SPDZ
├── docker/                      imagen especial de MP-SPDZ
├── tests/                       pruebas automatizadas
├── output/                      videos reconstruidos del cliente
├── .runtime/                    certificados y logs generados
├── data/                        almacenamiento legado de T09
├── TareasDeInvestigacion/       documentación histórica
├── docker-compose.yml           topología completa del MVP
├── Dockerfile                   imagen Python del Coordinator
├── pyproject.toml               definición del paquete Python
├── requirements.txt             dependencias de ejecución
├── requirements-dev.txt         dependencias para pruebas
├── .env.example                 variables de entorno disponibles
├── README.md                    instrucciones para ejecutar
└── CONTEXTO_TECNICO_PROYECTO.md investigación histórica anterior al MVP
```

El motor no vive dentro de este repositorio. Se usa el clon hermano:

```text
ProyectoDelta/
├── proyecto-delta/   aplicación explicada en esta guía
└── MP-SPDZ/          framework criptográfico externo requerido para el build
```

## 4. ¿Qué hay dentro de `src/`?

`src` significa **source**: contiene el código fuente Python que escribimos para Proyecto Delta.

### `src/client/`

Es todo lo que ocurre en la computadora confiable del usuario.

| Archivo/carpeta | Función |
|---|---|
| `cli.py` | Coordina el flujo completo del comando `upload`. |
| `__main__.py` | Permite ejecutar `python -m client`. |
| `networking/coordinator_client.py` | Registra y consulta trabajos en el Coordinator. |
| `networking/party_client.py` | Envía comandos de control a los tres Node Agents. No envía píxeles. |
| `preprocessing/video_preprocessor.py` | Abre el MP4, reduce FPS/resolución y crea píxeles grayscale `uint8`. |
| `preprocessing/video_reconstructor.py` | Recibe el resultado MPC y crea `reconstructed.mp4`. |
| `sharing/` | Código XOR heredado de T09. Se conserva como referencia/pruebas, pero el MVP actual no lo usa. |

La parte más importante para seguir el flujo completo es `src/client/cli.py`.

### `src/coordinator/`

Es la API central del plano de control.

| Archivo/carpeta | Función |
|---|---|
| `main.py` | Crea la aplicación FastAPI y `/health`. |
| `api/videos.py` | Define endpoints para registrar, preparar, iniciar, completar, fallar y limpiar jobs. |
| `models/video.py` | Define requests, responses, metadata y estados válidos. |
| `services/video_service.py` | Mantiene el job activo y aplica las transiciones de estado. |

El Coordinator mantiene la información solo en memoria. Si su contenedor se reinicia, pierde los jobs anteriores, pero no afecta los videos reconstruidos que ya están en el cliente.

### `src/mpc/`

Contiene el **puente Python** entre la CLI y MP-SPDZ.

| Archivo | Función |
|---|---|
| `external_io.py` | Carga el cliente oficial `ExternalIO/client.py`, conecta con P0/P1/P2, envía bloques privados y recibe resultados. |

Este directorio no contiene el programa MPC. Contiene el código Python que habla con MP-SPDZ.

### `src/party_receiver/`

El nombre `party_receiver` viene de T09, cuando el componente solo recibía archivos `.share`. En el MVP actual evolucionó a un **Node Agent**.

| Archivo/carpeta | Función actual |
|---|---|
| `main.py` | Crea la API FastAPI de una party lógica. |
| `runtime.py` | Inicia, comprueba y detiene `replicated-ring-party.x`. |
| `api/jobs.py` | Expone `prepare`, `start`, `complete`, `fail`, `cleanup` y consulta de job. |
| `services/job_service.py` | Guarda el estado en memoria y notifica `READY` al Coordinator. |
| `api/shares.py` | Endpoint legado de T09; la aplicación actual no lo monta. |
| `services/share_service.py` | Servicio legado para archivos XOR; no participa en el MVP MPC. |
| `storage/local_storage.py` | Escritura local usada por T09; no almacena datos del flujo ExternalIO actual. |

## 5. Diferencia entre `mpc/` y `src/mpc/`

Los nombres son parecidos, pero tienen responsabilidades distintas:

### `mpc/` en la raíz

Contiene archivos destinados al entorno MP-SPDZ:

| Ruta | Función |
|---|---|
| `Programs/Source/delta_video_identity.mpc` | Programa que ejecutan conjuntamente las tres parties. |
| `hosts-docker` | Relaciona cada party con su hostname y puerto interno. |
| `setup-dev-certs.sh` | Genera certificados TLS de desarrollo para parties y cliente. |

El archivo `.mpc` no es Python normal. Usa el lenguaje/compiler de MP-SPDZ para producir bytecode que ejecutan sus runtimes.

### `src/mpc/`

Contiene Python normal de Proyecto Delta. Su trabajo es usar ExternalIO desde la CLI.

En resumen:

```text
src/mpc/ = cliente/adaptador Python
mpc/     = programa y configuración de MP-SPDZ
```

## 6. ¿Qué hay dentro de `docker/`?

| Archivo | Función |
|---|---|
| `mp-spdz.Dockerfile` | Construye `replicated-ring-party.x`, compila `delta_video_identity.mpc` e instala el Node Agent. |
| `mp-spdz.Dockerfile.dockerignore` | Evita copiar archivos innecesarios durante ese build grande. |

El `Dockerfile` de la raíz es diferente: crea la imagen Python sencilla usada por el Coordinator. El Dockerfile de MP-SPDZ usa como contexto el directorio padre porque necesita leer tanto `proyecto-delta/` como el clon hermano `MP-SPDZ/`.

## 7. Servicios de Docker Compose

`docker-compose.yml` conecta todo el MVP.

| Servicio | Qué contiene | Puertos |
|---|---|---|
| `coordinator-api` | FastAPI del Coordinator | `8000` |
| `cert-init` | Genera certificados y termina | ninguno |
| `party-0` | Node Agent + runtime MP-SPDZ P0 | HTTP `8100`, ExternalIO `14000` |
| `party-1` | Node Agent + runtime MP-SPDZ P1 | HTTP `8101`, ExternalIO `14001` |
| `party-2` | Node Agent + runtime MP-SPDZ P2 | HTTP `8102`, ExternalIO `14002` |
| `delta-client` | CLI confiable opcional ejecutada con `docker compose run` | ninguno |

Los puertos internos `5000`, `5001` y `5002` permiten la comunicación MP-SPDZ entre parties dentro de la red de Compose.

Es normal que `cert-init` aparezca como `Exited (0)`: es una tarea de preparación que debe terminar correctamente.

Después del cleanup, FastAPI sigue saludable pero el proceso MPC queda detenido. El siguiente `prepare` lo inicia otra vez.

## 8. Flujo técnico detallado

### 8.1 Preprocesamiento

`VideoPreprocessor` produce:

- máximo 20 segundos;
- máximo 320×240, conservando proporción cuando corresponde;
- máximo 5 FPS;
- un canal grayscale;
- `dtype=uint8`;
- bytes ordenados por frame, fila y columna.

La metadata pública contiene ancho, alto, FPS, cantidad de frames, canales, tipo y versión.

### 8.2 Control del job

El Coordinator utiliza estos estados:

```text
REGISTERED → PREPARING → MPC_READY → PROCESSING → COMPLETED
                                             └──→ FAILED
```

Solo permite un job activo. Después de `cleanup` libera el espacio para registrar otro.

### 8.3 Entrada MPC

`MpcExternalClient`:

1. conecta con las tres parties usando TLS;
2. anuncia el tamaño y cantidad de bloques;
3. divide el payload en bloques de 4096 valores;
4. rellena con ceros únicamente el último bloque cuando es necesario;
5. llama `send_private_inputs()` del cliente oficial de MP-SPDZ.

MP-SPDZ genera el sharing compatible con `replicated-ring-party.x`. Proyecto Delta no intenta construir manualmente esos shares.

### 8.4 Programa MPC

`delta_video_identity.mpc`:

1. escucha clientes en el puerto base 14000;
2. acepta la conexión del cliente autorizado;
3. recibe cada bloque como valores `sint` secretos;
4. mantiene los valores sin modificarlos;
5. usa `reveal_to_clients()` para devolverlos al mismo cliente;
6. cierra la conexión.

Se compila para un ring de 64 bits y se ejecuta con tres instancias reales de `replicated-ring-party.x`.

### 8.5 Reconstrucción y cleanup

La CLI compara exactamente el payload recibido con el preprocesado. Después `VideoReconstructor` genera el MP4 y comprueba que OpenCV pueda abrirlo.

Al terminar:

- el Coordinator conserva metadata terminal en memoria y libera el slot activo;
- cada Node Agent elimina su estado de job;
- se detienen los procesos MPC;
- no quedan shares o archivos de video en las parties;
- `reconstructed.mp4` permanece en `output/`.

## 9. ¿Quién puede ver qué?

| Componente | Información visible |
|---|---|
| Cliente confiable | video original, píxeles preprocesados y resultado reconstruido |
| Coordinator | nombre, UUID, metadata y estados |
| Party 0 | su información secreta del protocolo, no el video completo |
| Party 1 | su información secreta del protocolo, no el video completo |
| Party 2 | su información secreta del protocolo, no el video completo |

Las tres parties viven en un mismo host durante este sprint. Es suficiente para demostrar el flujo, pero en producción deberían separarse en distintos dominios de confianza.

## 10. Carpetas generadas durante la ejecución

### `output/`

Contiene los resultados locales:

```text
output/<video_id>/reconstructed.mp4
```

Está ignorada por Git porque los videos pueden ser sensibles.

### `.runtime/`

Contiene:

- certificados autofirmados de desarrollo;
- logs mínimos de los runtimes;
- archivos temporales usados por pruebas locales.

También está ignorada por Git. `docker compose down` no la borra.

### `.venv/`

Es el entorno virtual Python local. Guarda dependencias instaladas para esa computadora y nunca se sube a Git.

### `data/parties/`

Es un remanente del flujo T09 que guardaba `.share` XOR. ExternalIO no utiliza esas carpetas en el MVP actual.

## 11. Archivos importantes de la raíz

| Archivo | Para qué sirve |
|---|---|
| `README.md` | Guía oficial para instalar, ejecutar, probar y detener el MVP. |
| `docker-compose.yml` | Declara y conecta todos los servicios. |
| `Dockerfile` | Construye la imagen ligera del Coordinator. |
| `pyproject.toml` | Nombre/versión del paquete, dependencias y comando `delta`. |
| `requirements.txt` | Lista simple de dependencias para ejecución. |
| `requirements-dev.txt` | Agrega pytest para desarrollo. |
| `.env.example` | Ejemplos de URLs, puertos y rutas configurables. |
| `.gitignore` | Evita subir videos, outputs, certificados, entornos y cachés. |
| `.dockerignore` | Evita enviar archivos innecesarios al build de Docker. |
| `CONTEXTO_TECNICO_PROYECTO.md` | Investigación previa a implementar el MVP. Es útil como historia, pero sus secciones sobre mocks/T09 ya no describen la ejecución actual. |

## 12. Código activo frente a código legado

### Activo en el MVP

- `src/client/cli.py`;
- `src/client/preprocessing/`;
- `src/client/networking/`;
- `src/mpc/external_io.py`;
- `src/coordinator/`;
- `src/party_receiver/main.py`;
- `src/party_receiver/runtime.py`;
- `src/party_receiver/api/jobs.py`;
- `src/party_receiver/services/job_service.py`;
- `mpc/`;
- `docker/` y `docker-compose.yml`.

### Legado T09, no usado por el flujo actual

- `src/client/sharing/`;
- `src/party_receiver/api/shares.py`;
- `src/party_receiver/services/share_service.py`;
- `src/party_receiver/storage/local_storage.py`;
- `data/parties/`.

No se deben conectar los `.share` XOR antiguos a MP-SPDZ. ExternalIO reemplaza ese mecanismo para el MVP.

## 13. Lectura recomendada para una persona nueva

Para entender el proyecto sin leerlo todo:

1. esta guía;
2. `README.md` para ejecutarlo;
3. `src/client/cli.py` para ver el flujo completo;
4. `docker-compose.yml` para ver los servicios;
5. `src/coordinator/models/video.py` y `services/video_service.py` para los estados;
6. `src/party_receiver/runtime.py` para el proceso real de cada party;
7. `src/mpc/external_io.py` para la entrada/salida privada;
8. `mpc/Programs/Source/delta_video_identity.mpc` para el cálculo MPC.

`TareasDeInvestigacion/` y `CONTEXTO_TECNICO_PROYECTO.md` son útiles para conocer la historia y las decisiones anteriores. No deben usarse como descripción del runtime actual ni son necesarios para ejecutar el MVP por primera vez; para eso la fuente vigente es `README.md`.

## 14. Comandos esenciales

Levantar el entorno:

```powershell
docker compose up --build -d
```

Ejecutar desde el entorno virtual:

```powershell
.\.venv\Scripts\Activate.ps1
python -m client upload C:\ruta\video.mp4
```

Abrir el resultado:

```powershell
Invoke-Item ".\output\<video_id>\reconstructed.mp4"
```

Consultar el estado:

```powershell
Invoke-RestMethod "http://localhost:8000/api/v1/videos/<video_id>" |
    ConvertTo-Json -Depth 5
```

Detener y retirar los contenedores:

```powershell
docker compose down
```

Los videos reconstruidos permanecen en `output/` después de detener Docker.
