# Proyecto Delta

Proyecto universitario para procesar video de videovigilancia de forma segura. La implementación actual corresponde a **T09**: el video se preprocesa exclusivamente en el cliente confiable, se transforma en tres secret shares provisionales y cada share se envía directamente a una party distinta.

El Coordinator solo recibe metadata y confirmaciones. Ni el MP4 original ni los shares pasan por él. T09 todavía no implementa Computer Vision ni MP-SPDZ.

## Requisitos

- Docker con Docker Compose.
- Python 3.10 o posterior para ejecutar la CLI local.

## Instalación de la CLI

En PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install -e .
```

En Linux o macOS:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install -e .
```

## Ejecución de T09

Levantar el Coordinator y las tres mock parties:

```bash
docker compose up --build
```

Los servicios quedan disponibles en:

- Coordinator: `http://localhost:8000`
- Party 0: `http://localhost:8100`
- Party 1: `http://localhost:8101`
- Party 2: `http://localhost:8102`

En otra terminal, con el entorno virtual activo, cargar un MP4:

```bash
python -m client upload ./video.mp4
```

También se instala el comando equivalente:

```bash
delta upload ./video.mp4
```

La CLI registra metadata, preprocesa el video localmente, genera los tres shares y los distribuye directamente. Al completarse debe mostrar `Estado: READY_FOR_MPC` y crear un archivo `<video_id>.share` dentro de cada carpeta `data/parties/party-N/`.

Consultar el estado posteriormente:

```bash
curl http://localhost:8000/api/v1/videos/<video_id>
```

La arquitectura, endpoints, configuración, alcance y criterios de aceptación se documentan en [TareasDeInvestigacion/T09.md](TareasDeInvestigacion/T09.md).

## Pruebas automatizadas

La suite rápida cubre servicios, APIs, Secret Sharing, preprocesamiento, networking, CLI, almacenamiento y errores esperados. Para ejecutarla:

```bash
python -m pip install -r requirements-dev.txt
python -m pip install -e .
python -m pytest
```

Las validaciones Docker y E2E requieren los cuatro servicios levantados y un MP4 local; la suite rápida no depende de los videos del usuario.
