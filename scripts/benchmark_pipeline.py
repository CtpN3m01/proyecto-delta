"""Mide por fases el flujo completo de ``upload`` sobre un video real.

Ejecuta la misma ruta que la CLI (``client.cli.upload_video``) contra el
Coordinator y las tres parties levantadas con Docker Compose, y cronometra cada
fase con tiempo real y CPU del proceso: detección (YuNet y LPD-YuNet), llamadas
de control, cada tramo de ExternalIO, validación y reconstrucción.

Uso, desde la raíz del repositorio y con el entorno virtual activo::

    python scripts/benchmark_pipeline.py VIDEO.mp4 --detect-faces --detect-plates \\
        --max-width 640 --max-height 360 --fps 10 --output-json resultado.json

Sin ``--detect-faces`` ni ``--detect-plates`` se mide el modo identidad. Con
``--docker-stats ARCHIVO.csv`` se muestrea además el CPU y la memoria de los
contenedores durante la corrida.

El video reconstruido se escribe en un directorio temporal, que se indica al
final, salvo que se pase ``--output-dir``. Código de salida: 0 si el trabajo
terminó, 1 si falló (las mediciones se guardan igualmente).
"""

import argparse
import json
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

timings: dict[str, float] = {}
calls: dict[str, int] = {}


def timed(name, function):
    """Acumula tiempo real y de CPU del proceso (``name`` y ``name_cpu``)."""

    def wrapper(*args, **kwargs):
        wall, cpu = time.perf_counter(), time.process_time()
        try:
            return function(*args, **kwargs)
        finally:
            timings[name] = timings.get(name, 0.0) + time.perf_counter() - wall
            timings[name + "_cpu"] = timings.get(name + "_cpu", 0.0) + time.process_time() - cpu
            calls[name] = calls.get(name, 0) + 1

    return wrapper


def peak_memory_mb() -> float | None:
    """Pico de memoria residente del proceso, en MiB; None si no se puede leer."""
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class Counters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = Counters()
            counters.cb = ctypes.sizeof(counters)
            ctypes.windll.kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [
                wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD,
            ]
            ctypes.windll.psapi.GetProcessMemoryInfo(
                ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb,
            )
            return counters.PeakWorkingSetSize / 2**20
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return peak / 2**20 if sys.platform == "darwin" else peak / 1024
    except Exception:  # noqa: BLE001 - es una medida accesoria
        return None


def sample_docker_stats(path: Path, stop: threading.Event) -> None:
    """Una fila ``segundos,contenedor,cpu,memoria`` por contenedor y muestra."""
    start = time.monotonic()
    with path.open("w", encoding="utf-8") as output:
        output.write("t,name,cpu,mem\n")
        while not stop.is_set():
            try:
                lines = subprocess.run(
                    ["docker", "stats", "--no-stream", "--format", "{{.Name}},{{.CPUPerc}},{{.MemUsage}}"],
                    capture_output=True, text=True, timeout=30,
                ).stdout.splitlines()
            except (OSError, subprocess.SubprocessError):
                return
            now = int(time.monotonic() - start)
            for line in lines:
                output.write(f"{now},{line}\n")
            output.flush()
            stop.wait(2)


def instrument(preprocessor, reconstructor, mpc, party, coordinator, model, detect_plates: bool):
    """Envuelve con cronómetros las fases del flujo; no cambia su comportamiento."""
    from client.anonymization import AnonymizationPlan
    from client.detection import LPDYuNet
    import mpc.external_io as external_io

    module = mpc._load_official_client()  # cliente oficial de MP-SPDZ (camino original)
    module.octetStream.Receive = timed("socket_receive", module.octetStream.Receive)
    module.octetStream.Send = timed("socket_send", module.octetStream.Send)
    module.Client.receive_triples = timed("receive_triples", module.Client.receive_triples)
    module.Client.send_private_inputs = timed("send_private_inputs", module.Client.send_private_inputs)
    module.Client.receive_outputs = timed("receive_outputs", module.Client.receive_outputs)
    module.Client.send_public_inputs = timed("send_public_inputs", module.Client.send_public_inputs)

    channel = getattr(external_io, "_VectorizedChannel", None)  # canal vectorizado, si existe
    if channel is not None:
        channel._receive_sum = timed("vec_receive_sum", channel._receive_sum)
        channel._send_all = timed("vec_send_all", channel._send_all)
        channel.exchange = timed("vec_exchange", channel.exchange)
        channel.send_public_mask = timed("vec_send_mask", channel.send_public_mask)

    AnonymizationPlan.validate_result = timed("validate_result", AnonymizationPlan.validate_result)
    AnonymizationPlan.mask_chunk = timed("mask_chunk", AnonymizationPlan.mask_chunk)
    LPDYuNet.detect_frame = timed("lpd_yunet", LPDYuNet.detect_frame)
    model.infer = timed("yunet", model.infer)
    preprocessor.process = timed("preprocess_total", preprocessor.process)
    reconstructor.reconstruct = timed("reconstruct", reconstructor.reconstruct)
    mpc.process_anonymize = timed("mpc_total", mpc.process_anonymize)
    mpc.process_identity = timed("mpc_total", mpc.process_identity)
    for name in ("prepare_job", "start_job", "complete_job", "cleanup_job"):
        setattr(party, name, timed("party_" + name, getattr(party, name)))
    coordinator.wait_for_status = timed("coordinator_wait_ready", coordinator.wait_for_status)


def summary(result: dict) -> str:
    t = result["timings"]
    total = t["total"]
    control = sum(t.get(key, 0.0) for key in (
        "party_prepare_job", "party_start_job", "party_complete_job",
        "party_cleanup_job", "coordinator_wait_ready",
    ))
    rows = [
        ("MPC por ExternalIO", t.get("mpc_total", 0.0)),
        ("Detección y preprocesamiento", t.get("preprocess_total", 0.0)),
        ("  LPD-YuNet (placas)", t.get("lpd_yunet", 0.0)),
        ("  YuNet (rostros)", t.get("yunet", 0.0)),
        ("Plano de control", control),
        ("Validación del resultado", t.get("validate_result", 0.0)),
        ("Reconstrucción del MP4", t.get("reconstruct", 0.0)),
        ("TOTAL", total),
    ]
    lines = [f"Estado: {result['status']}" + (f" ({result['error']})" if result["error"] else "")]
    lines += [f"{name:32s}{value:10.2f} s  {100 * value / total:5.1f} %" for name, value in rows]
    if "client_peak_memory_mb" in t:
        lines.append(f"Pico de memoria del cliente    {t['client_peak_memory_mb']:10.0f} MiB")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("video", type=Path, help="MP4 a procesar")
    parser.add_argument("--detect-faces", action="store_true")
    parser.add_argument("--detect-plates", action="store_true")
    parser.add_argument("--max-width", type=int, default=None, help="Ancho máximo para MPC")
    parser.add_argument("--max-height", type=int, default=None, help="Alto máximo para MPC")
    parser.add_argument("--fps", type=float, default=None, help="FPS de muestreo para MPC")
    parser.add_argument("--coordinator-url", default="http://localhost:8000")
    parser.add_argument("--output-json", type=Path, help="Guarda las mediciones en este JSON")
    parser.add_argument("--output-dir", type=Path, help="Directorio del video reconstruido")
    parser.add_argument("--docker-stats", type=Path, help="CSV de CPU y memoria de los contenedores")
    args = parser.parse_args(argv)

    from client import cli
    from client.networking import CoordinatorClient, PartyClient
    from client.preprocessing import VideoPreprocessor, VideoReconstructor
    from client.preprocessing.yunet import DEFAULT_YUNET_MODEL, YuNet
    from mpc import MpcExternalClient
    from mpc.video_profile import DEFAULT_MPC_FPS

    model = YuNet(modelPath=DEFAULT_YUNET_MODEL, inputSize=[320, 320], confThreshold=0.6,
                  nmsThreshold=0.3, topK=5000, backendId=0, targetId=0)
    preprocessor = VideoPreprocessor(
        max_width=args.max_width, max_height=args.max_height,
        target_fps=args.fps if args.fps is not None else DEFAULT_MPC_FPS,
    )
    reconstructor, mpc = VideoReconstructor(), MpcExternalClient()
    party, coordinator = PartyClient(), CoordinatorClient(args.coordinator_url)
    instrument(preprocessor, reconstructor, mpc, party, coordinator, model, args.detect_plates)

    anonymize = args.detect_faces or args.detect_plates
    output_dir = args.output_dir or Path(tempfile.mkdtemp(prefix="delta-benchmark-"))
    stop, sampler = threading.Event(), None
    if args.docker_stats:
        sampler = threading.Thread(target=sample_docker_stats, args=(args.docker_stats, stop), daemon=True)
        sampler.start()

    status, error = "COMPLETED", None
    started = time.perf_counter()
    try:
        cli.upload_video(
            args.video, coordinator, party, preprocessor, mpc, reconstructor, model, output_dir,
            processing_mode="anonymize" if anonymize else "identity",
            detect_faces=args.detect_faces, detect_plates=args.detect_plates,
        )
    except BaseException as exc:  # noqa: BLE001 - se informa y se conservan las mediciones
        status, error = "FAILED", f"{type(exc).__name__}: {exc}"
    timings["total"] = time.perf_counter() - started
    stop.set()
    if sampler is not None:
        sampler.join(timeout=35)
    memory = peak_memory_mb()
    if memory is not None:
        timings["client_peak_memory_mb"] = memory

    result = {"status": status, "error": error, "video": str(args.video),
              "timings": {key: round(value, 3) for key, value in timings.items()}, "calls": calls}
    if args.output_json:
        args.output_json.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n" + summary(result))
    print(f"Video reconstruido en: {output_dir}")
    return 0 if status == "COMPLETED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
