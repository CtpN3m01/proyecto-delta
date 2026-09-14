"""Envío directo de shares desde el cliente confiable a una party."""

from typing import Any

import httpx


class PartyClientError(RuntimeError):
    """Error al entregar un share a su party asignada."""


class PartyClient:
    def __init__(self, timeout: httpx.Timeout | None = None) -> None:
        self._timeout = timeout or httpx.Timeout(
            connect=5.0,
            read=60.0,
            write=300.0,
            pool=5.0,
        )

    def send_share(
        self,
        party_id: int,
        party_url: str,
        video_id: str,
        share: bytes,
    ) -> None:
        if party_id not in (0, 1, 2):
            raise ValueError("party_id debe ser 0, 1 o 2.")
        if not share:
            raise ValueError("No se puede enviar un share vacío.")

        endpoint = f"{party_url.rstrip('/')}/api/v1/shares/{video_id}"
        try:
            response = httpx.post(
                endpoint,
                content=share,
                headers={"Content-Type": "application/octet-stream"},
                timeout=self._timeout,
            )
        except httpx.RequestError as exc:
            raise PartyClientError(
                f"Party {party_id} no está disponible en {party_url}: {exc}"
            ) from exc

        if response.is_error:
            detail = self._error_detail(response)
            raise PartyClientError(
                f"Party {party_id} rechazó el share "
                f"(HTTP {response.status_code}): {detail}"
            )

        try:
            receipt: Any = response.json()
            receipt_party_id = int(receipt["party_id"])
            receipt_video_id = str(receipt["video_id"])
            receipt_status = str(receipt["status"])
        except (ValueError, TypeError, KeyError) as exc:
            raise PartyClientError(
                f"Party {party_id} devolvió una confirmación inválida."
            ) from exc

        if (
            receipt_party_id != party_id
            or receipt_video_id != video_id
            or receipt_status != "RECEIVED"
        ):
            raise PartyClientError(
                f"Party {party_id} devolvió una confirmación que no coincide con el envío."
            )

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        try:
            body = response.json()
            if isinstance(body, dict) and body.get("detail"):
                return str(body["detail"])
        except ValueError:
            pass
        return response.text

