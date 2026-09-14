"""Acceso de la CLI al Control Plane de Proyecto Delta."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx


class CoordinatorClientError(RuntimeError):
    """Error de comunicación o contrato con el Coordinator."""


@dataclass(frozen=True)
class PartyEndpoint:
    id: int
    url: str


@dataclass(frozen=True)
class VideoRegistration:
    id: str
    status: str
    parties: tuple[PartyEndpoint, PartyEndpoint, PartyEndpoint]


@dataclass(frozen=True)
class VideoState:
    id: str
    status: str
    parties: dict[str, str]


class CoordinatorClient:
    """Registra metadata y consulta estados; nunca transmite el video."""

    def __init__(self, base_url: str, timeout: float = 15.0) -> None:
        normalized_url = base_url.strip().rstrip("/")
        if not normalized_url:
            raise ValueError("COORDINATOR_URL no puede estar vacía.")
        self._base_url = normalized_url
        self._timeout = timeout

    def register_video(self, filename: str, video_format: str) -> VideoRegistration:
        data = self._post_json(
            "/api/v1/videos",
            {"filename": filename, "format": video_format},
            action="registrar el video",
        )
        try:
            video_id = str(UUID(str(data["id"])))
            status = str(data["status"])
            raw_parties = data["parties"]
            if not isinstance(raw_parties, list):
                raise TypeError
            parties = tuple(
                PartyEndpoint(id=int(item["id"]), url=str(item["url"]).rstrip("/"))
                for item in raw_parties
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CoordinatorClientError(
                "El Coordinator devolvió un registro con formato inválido."
            ) from exc

        if len(parties) != 3 or {party.id for party in parties} != {0, 1, 2}:
            raise CoordinatorClientError(
                "El Coordinator debe devolver exactamente las parties 0, 1 y 2."
            )
        if any(not party.url for party in parties):
            raise CoordinatorClientError("El Coordinator devolvió una URL de party vacía.")

        ordered = tuple(sorted(parties, key=lambda party: party.id))
        return VideoRegistration(
            id=video_id,
            status=status,
            parties=(ordered[0], ordered[1], ordered[2]),
        )

    def get_video(self, video_id: str) -> VideoState:
        data = self._get_json(
            f"/api/v1/videos/{video_id}",
            action="consultar el estado final",
        )
        try:
            returned_id = str(UUID(str(data["id"])))
            status = str(data["status"])
            raw_parties = data.get("parties", {})
            if not isinstance(raw_parties, dict):
                raise TypeError
            parties = {str(key): str(value) for key, value in raw_parties.items()}
        except (KeyError, TypeError, ValueError) as exc:
            raise CoordinatorClientError(
                "El Coordinator devolvió un estado con formato inválido."
            ) from exc
        return VideoState(id=returned_id, status=status, parties=parties)

    def _post_json(self, path: str, payload: dict[str, Any], action: str) -> dict[str, Any]:
        try:
            response = httpx.post(
                f"{self._base_url}{path}",
                json=payload,
                timeout=self._timeout,
            )
        except httpx.RequestError as exc:
            raise CoordinatorClientError(
                f"No se pudo contactar al Coordinator para {action}: {exc}"
            ) from exc
        return self._decode_response(response, action)

    def _get_json(self, path: str, action: str) -> dict[str, Any]:
        try:
            response = httpx.get(
                f"{self._base_url}{path}",
                timeout=self._timeout,
            )
        except httpx.RequestError as exc:
            raise CoordinatorClientError(
                f"No se pudo contactar al Coordinator para {action}: {exc}"
            ) from exc
        return self._decode_response(response, action)

    @staticmethod
    def _decode_response(response: httpx.Response, action: str) -> dict[str, Any]:
        if response.is_error:
            detail = response.text
            try:
                body = response.json()
                if isinstance(body, dict) and body.get("detail"):
                    detail = str(body["detail"])
            except ValueError:
                pass
            raise CoordinatorClientError(
                f"El Coordinator rechazó la solicitud al {action} "
                f"(HTTP {response.status_code}): {detail}"
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise CoordinatorClientError(
                "El Coordinator devolvió una respuesta que no es JSON."
            ) from exc
        if not isinstance(body, dict):
            raise CoordinatorClientError(
                "El Coordinator devolvió una respuesta JSON inválida."
            )
        return body

