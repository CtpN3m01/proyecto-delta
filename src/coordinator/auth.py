"""Identidad del usuario: el coordinator valida el token de PocketBase."""

import hashlib
import os
import time

import httpx
from fastapi import Header, HTTPException

_CACHE: dict[str, tuple[str, float]] = {}
_CACHE_SECONDS = 60.0


def pocketbase_url() -> str:
    return os.getenv("POCKETBASE_URL", "http://127.0.0.1:8090").rstrip("/")


async def verify_token(token: str) -> str:
    """Devuelve el id del usuario dueño del token o lanza 401."""

    key = hashlib.sha256(token.encode()).hexdigest()
    cached = _CACHE.get(key)
    if cached and cached[1] > time.monotonic():
        return cached[0]
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{pocketbase_url()}/api/collections/users/auth-refresh",
                headers={"Authorization": token},
            )
    except httpx.RequestError as exc:
        raise HTTPException(503, "No se pudo validar la sesión") from exc
    if response.status_code != 200:
        raise HTTPException(401, "Sesión inválida o vencida")
    user_id = str(response.json().get("record", {}).get("id") or "")
    if not user_id:
        raise HTTPException(401, "Sesión inválida o vencida")
    if len(_CACHE) > 1000:
        _CACHE.clear()
    _CACHE[key] = (user_id, time.monotonic() + _CACHE_SECONDS)
    return user_id


async def current_user(authorization: str | None = Header(default=None)) -> str:
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not token or len(token) > 4096:
        raise HTTPException(401, "Inicia sesión para continuar")
    return await verify_token(token)
