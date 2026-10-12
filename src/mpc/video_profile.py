"""Límites de video compartidos por el cliente y las APIs de control."""

from dataclasses import dataclass
import os


# Perfil espacial verificado con tres parties en clips pequeños.
# No es una validación de 20 segundos a esta resolución ni de Raspberry Pi.
DEFAULT_MPC_WIDTH = 640
MAX_CONFIGURED_WIDTH = 640
MAX_CONFIGURED_HEIGHT = 480
DEFAULT_MPC_FPS = 10.0
MAX_CONFIGURED_FPS = 10
MAX_VIDEO_DURATION_SECONDS = 20
MAX_VIDEO_FRAMES = MAX_VIDEO_DURATION_SECONDS * MAX_CONFIGURED_FPS


@dataclass(frozen=True)
class MpcVideoProfile:
    max_width: int
    max_height: int

    def __post_init__(self) -> None:
        for name, value, ceiling in (
            ("MPC_MAX_WIDTH", self.max_width, MAX_CONFIGURED_WIDTH),
            ("MPC_MAX_HEIGHT", self.max_height, MAX_CONFIGURED_HEIGHT),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} debe ser un entero")
            if not 2 <= value <= ceiling:
                raise ValueError(f"{name} debe estar entre 2 y {ceiling}")

    @classmethod
    def from_environment(
        cls,
        max_width: int | None = None,
        max_height: int | None = None,
    ) -> "MpcVideoProfile":
        """Los argumentos tienen prioridad; el alto por defecto es 3/4 del ancho.

        Este par define una caja máxima, no la proporción del video. Todos los
        servicios deben configurar los mismos máximos antes de aceptar un job.
        Las cotas 640x480 limitan los perfiles a los evaluados en esta tarea;
        admitirlos no demuestra que 20 segundos sean viables a ese tamaño.
        """
        width = cls._dimension("MPC_MAX_WIDTH", max_width, DEFAULT_MPC_WIDTH)
        height = cls._dimension("MPC_MAX_HEIGHT", max_height, width * 3 // 4)
        return cls(width, height)

    @staticmethod
    def _dimension(name: str, override: int | None, default: int) -> int:
        if override is not None:
            return override
        value = os.getenv(name)
        if value is None or not value.strip():
            return default
        try:
            return int(value)
        except ValueError as exc:
            raise ValueError(f"{name} debe ser un entero") from exc
