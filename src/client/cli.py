"""CLI confiable para el MVP de video identidad con MP-SPDZ."""

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Sequence

import cv2 as cv

from client.preprocessing.yunet import YuNet

from client.networking import (
    CoordinatorClient,
    CoordinatorClientError,
    PartyClient,
    PartyClientError,
    VideoRegistration,
)
from client.preprocessing import (
    VideoPreprocessingError,
    VideoPreprocessor,
    VideoReconstructionError,
    VideoReconstructor,
)
from client.anonymization import AnonymizationPlan, prepare_anonymization
from client.regions import DetectedRegion, DetectorExecutionError, FrameDetections
from mpc import MpcExternalClient, MpcExternalIOError
from mpc.video_profile import DEFAULT_MPC_FPS, MAX_CONFIGURED_FPS

backend_target_pairs = (
    (cv.dnn.DNN_BACKEND_OPENCV, cv.dnn.DNN_TARGET_CPU),
    (cv.dnn.DNN_BACKEND_CUDA, cv.dnn.DNN_TARGET_CUDA),
    (cv.dnn.DNN_BACKEND_CUDA, cv.dnn.DNN_TARGET_CUDA_FP16),
    (cv.dnn.DNN_BACKEND_TIMVX, cv.dnn.DNN_TARGET_NPU),
    (cv.dnn.DNN_BACKEND_CANN, cv.dnn.DNN_TARGET_NPU),
)

class ClientInputError(ValueError):
    """La entrada local no cumple el perfil del MVP."""


class MpcResultMismatchError(RuntimeError):
    """El cálculo identidad no devolvió exactamente los pixels enviados."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m client",
        description="Proyecto Delta - MVP MPC de video identidad.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    upload = commands.add_parser(
        "upload",
        help="Preprocesa un MP4, ejecuta MPC y reconstruye el resultado.",
    )
    upload.add_argument("video", type=Path, help="Ruta local al archivo .mp4")
    upload.add_argument(
        "--processing-mode", choices=("identity", "anonymize"), default="identity",
        help="Selección explícita: identity conserva el MVP; anonymize requiere regiones.",
    )
    upload.add_argument(
        "--regions-json", type=Path,
        help="Regiones de prueba/manuales en coordenadas MPC; no integra detectores.",
    )
    upload.add_argument(
        "--mpc-max-width", type=int, default=None,
        help="Ancho máximo para MPC; predeterminado: MPC_MAX_WIDTH/perfil compartido.",
    )
    upload.add_argument(
        "--mpc-max-height", type=int, default=None,
        help="Alto máximo para MPC; predeterminado: MPC_MAX_HEIGHT o 3/4 del ancho.",
    )
    upload.add_argument(
        "--mpc-fps", type=float, default=DEFAULT_MPC_FPS,
        help=(
            f"FPS de muestreo para MPC; predeterminado: {DEFAULT_MPC_FPS:g}, "
            f"máximo: {MAX_CONFIGURED_FPS}. No aumenta los FPS del original."
        ),
    )
    upload.add_argument("--conf-threshold", "--conf_threshold", type=float, default=0.9)
    upload.add_argument("--nms-threshold", "--nms_threshold", type=float, default=0.3)
    upload.add_argument("--top-k", "--top_k", type=int, default=5000)
    upload.add_argument(
        "--backend-target",
        "--backend_target",
        "-bt",
        type=int,
        choices=range(len(backend_target_pairs)),
        default=0,
        help=(
            "Backend/target YuNet: 0 OpenCV+CPU (predeterminado), "
            "1 CUDA, 2 CUDA FP16, 3 TIM-VX+NPU, 4 CANN+NPU."
        ),
    )
    return parser


def _validated_video_path(path: Path) -> Path:
    if not path.exists():
        raise ClientInputError(f"El archivo no existe: {path}")
    if not path.is_file():
        raise ClientInputError(f"La ruta no corresponde a un archivo: {path}")
    if path.suffix.lower() != ".mp4":
        raise ClientInputError("El MVP solamente admite archivos .mp4")
    return path


def _plan_from_json(path: Path, metadata) -> AnonymizationPlan:
    """Entrada de diagnóstico; el transporte interno siempre usa tipos T024."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ClientInputError(f"No se pudo leer el JSON de regiones: {exc}") from exc
    if not isinstance(data, dict) or set(data) != {"width", "height", "frames"}:
        raise ClientInputError("El JSON requiere width, height y frames explícitos")
    size = (data["width"], data["height"])
    if size != (metadata.width, metadata.height):
        raise ClientInputError("El JSON debe referirse a las dimensiones MPC reales")
    if not isinstance(data["frames"], list):
        raise ClientInputError("frames debe ser una lista completa de resultados")
    frames = []
    for record in data["frames"]:
        if not isinstance(record, dict):
            raise ClientInputError("Cada fotograma debe declarar su resultado")
        if record.get("status") == "success":
            if set(record) != {"frame_index", "status", "regions"} or not isinstance(record["regions"], list):
                raise ClientInputError("Un éxito requiere frame_index, status y regions, incluso vacías")
            detections = []
            for region in record["regions"]:
                if not isinstance(region, dict) or set(region) != {"region_type", "x", "y", "width", "height"}:
                    raise ClientInputError("Cada región requiere region_type, x, y, width y height")
                detections.append(DetectedRegion(**region))
            frames.append(FrameDetections.success(record["frame_index"], detections))
        elif record.get("status") == "failed":
            if set(record) != {"frame_index", "status", "error"}:
                raise ClientInputError("Un fallo requiere frame_index, status y error")
            frames.append(FrameDetections.failure(record["frame_index"], record["error"]))
        else:
            raise ClientInputError("status debe ser success o failed; no se infiere éxito")
    return prepare_anonymization(
        frames, source_size=size, target_size=size, frame_count=metadata.frame_count
    )


def upload_video(
    video_path: Path,
    coordinator: CoordinatorClient,
    party_client: PartyClient,
    preprocessor: VideoPreprocessor,
    mpc_client: MpcExternalClient,
    reconstructor: VideoReconstructor,
    model: YuNet,
    output_root: str | Path = "output",
    *,
    processing_mode: str = "identity",
    anonymization_plan: AnonymizationPlan | None = None,
    regions_json: Path | None = None,
) -> int:
    path = _validated_video_path(video_path)
    if processing_mode not in ("identity", "anonymize"):
        raise ClientInputError("processing_mode debe ser identity o anonymize")
    if processing_mode == "identity" and (anonymization_plan is not None or regions_json is not None):
        raise ClientInputError("Las regiones requieren seleccionar explícitamente anonymize")
    if processing_mode == "anonymize" and (anonymization_plan is None) == (regions_json is None):
        raise ClientInputError("Anonimización requiere un plan o JSON, no ambos ni ninguno")
    print("Proyecto Delta - MPC MVP")
    print(f"\nVideo: {path.name}")

    processed = preprocessor.process(path, model)
    metadata = processed.metadata.as_dict()
    if processing_mode == "anonymize":
        if regions_json is not None:
            anonymization_plan = _plan_from_json(regions_json, processed.metadata)
        if not isinstance(anonymization_plan, AnonymizationPlan):
            raise ClientInputError("Se requiere un plan de anonimización validado")
        if not anonymization_plan.detections_complete:
            raise ClientInputError("Prepare el plan con resultados explícitos de todos los fotogramas")
        if (anonymization_plan.width, anonymization_plan.height, anonymization_plan.frame_count) != (
            processed.metadata.width, processed.metadata.height, processed.metadata.frame_count
        ) or len(processed.payload) != anonymization_plan.payload_size:
            raise ClientInputError("El plan no coincide con los fotogramas MPC realmente procesados")
        print("[MODO] ANONIMIZACIÓN MPC; regiones proporcionadas explícitamente")
    else:
        print("[MODO] IDENTIDAD; no anonimiza")
    print("[OK] Video validado y preprocesado localmente")
    print(
        f"     {processed.metadata.frame_count} frames, "
        f"{processed.metadata.width}x{processed.metadata.height}, "
        f"{processed.metadata.fps:g} FPS, grayscale"
    )

    registration = coordinator.register_video(path.name, "mp4")
    print(f"[OK] Job registrado: {registration.id}")

    try:
        coordinator.prepare(registration.id, metadata)
        for endpoint in registration.parties:
            party_client.prepare_job(
                endpoint.id,
                endpoint.url,
                registration.id,
                metadata,
            )
            print(f"[OK] Party {endpoint.id} lista")
        coordinator.wait_for_status(registration.id, "MPC_READY")
        print("[OK] MPC listo")

        for endpoint in registration.parties:
            party_client.start_job(endpoint.id, endpoint.url, registration.id)
        coordinator.start(registration.id)

        if processing_mode == "anonymize":
            result = mpc_client.process_anonymize(processed.payload, anonymization_plan)
            anonymization_plan.validate_result(processed.payload, result)
        else:
            result = mpc_client.process_identity(processed.payload)
        print("[OK] Datos enviados y recibidos mediante MP-SPDZ ExternalIO")
        if processing_mode == "identity" and result != processed.payload:
            raise MpcResultMismatchError(
                "El resultado MPC no coincide exactamente con el video preprocesado"
            )

        destination = reconstructor.reconstruct(
            result,
            processed.metadata,
            registration.id,
            output_root,
        )
        print("[OK] Video reconstruido y validado")

        for endpoint in registration.parties:
            party_client.complete_job(endpoint.id, endpoint.url, registration.id)
        for endpoint in registration.parties:
            party_client.cleanup_job(endpoint.id, endpoint.url, registration.id)
        coordinator.complete(registration.id)
        coordinator.cleanup(registration.id)

        print(f"\nResultado:\n{destination}")
        print("\nEstado: COMPLETED")
        return 0
    except KeyboardInterrupt:
        _best_effort_failure_cleanup(
            registration,
            coordinator,
            party_client,
            "Operación cancelada por el usuario",
        )
        raise
    except Exception as exc:
        _best_effort_failure_cleanup(registration, coordinator, party_client, str(exc))
        raise


def _best_effort_failure_cleanup(
    registration: VideoRegistration,
    coordinator: CoordinatorClient,
    party_client: PartyClient,
    detail: str,
) -> None:
    for endpoint in registration.parties:
        try:
            party_client.fail_job(endpoint.id, endpoint.url, registration.id, detail)
        except (PartyClientError, ValueError):
            pass
        try:
            party_client.cleanup_job(endpoint.id, endpoint.url, registration.id)
        except (PartyClientError, ValueError):
            pass
    try:
        coordinator.fail(registration.id, detail)
    except (CoordinatorClientError, ValueError):
        pass
    try:
        coordinator.cleanup(registration.id)
    except (CoordinatorClientError, ValueError):
        pass


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command != "upload":
        return 2

    backend_id = backend_target_pairs[args.backend_target][0]
    target_id = backend_target_pairs[args.backend_target][1]

    coordinator_url = os.getenv("COORDINATOR_URL", "http://localhost:8000")
    output_root = os.getenv("DELTA_OUTPUT_DIR", "output")
    try:
        return upload_video(

            video_path=args.video,
            coordinator=CoordinatorClient(coordinator_url),
            party_client=PartyClient(),
            preprocessor=VideoPreprocessor(
                max_width=args.mpc_max_width,
                max_height=args.mpc_max_height,
                target_fps=args.mpc_fps,
            ),
            mpc_client=MpcExternalClient(),
            reconstructor=VideoReconstructor(),
            output_root=output_root,
            processing_mode=args.processing_mode,
            regions_json=args.regions_json,
            model=YuNet(modelPath='./src/client/preprocessing/face_detection_yunet_2023mar.onnx',
                  inputSize=[320, 320],
                  confThreshold=args.conf_threshold,
                  nmsThreshold=args.nms_threshold,
                  topK=args.top_k,
                  backendId=backend_target_pairs[args.backend_target][0],
                  targetId=backend_target_pairs[args.backend_target][1],
                  )
        )
    except (
        ClientInputError,
        CoordinatorClientError,
        PartyClientError,
        VideoPreprocessingError,
        VideoReconstructionError,
        MpcExternalIOError,
        MpcResultMismatchError,
        DetectorExecutionError,
        ValueError,
    ) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nOperación cancelada", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
