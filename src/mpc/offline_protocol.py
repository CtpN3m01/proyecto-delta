"""Protocolo del MPC en segundo plano (programa delta_video_offline).

Contrato con el navegador (frontend/src/browser/shares.ts):

* x = s0 + s1 + s2 (mod 256) para cada píxel gris.
* s1 y s2 nunca viajan: se expanden con AES-128-CTR desde una clave de 16
  bytes por party. El bloque contador inicial del cuadro f es
  ``f.to_bytes(8, "big") + bytes(8)``; WebCrypto usa ``length: 64``.
* Party 0 recibe s0 y la máscara pública de cada cuadro.

Contrato con MP-SPDZ: ExternalIO semi-honesto sobre Z(2^64); cada mensaje
lleva un prefijo de longitud uint32 little-endian.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import os
from pathlib import Path
import socket
import ssl
import struct
from typing import Iterable, Iterator

import numpy as np

CHUNK_SIZE = int(os.getenv("MPC_CHUNK_SIZE", "262144"))
OFFLINE_ACK = (0x444C5446, 1)
KEY_SIZE = 16
OUTPUT_CLIENT_ID = 3
MAX_OUTPUT_VALUE = 3 * 255
MAX_MESSAGE = CHUNK_SIZE * 8


class OfflineProtocolError(RuntimeError):
    """Una party o un cliente rompió el contrato del programa offline."""


def keystream(key: bytes, frame_index: int, length: int) -> np.ndarray:
    """Share pseudoaleatorio de un cuadro; idéntico al de WebCrypto AES-CTR."""

    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    if len(key) != KEY_SIZE:
        raise ValueError("La clave del share debe tener 16 bytes")
    if frame_index < 0 or length < 0:
        raise ValueError("Cuadro o longitud inválidos")
    counter = frame_index.to_bytes(8, "big") + bytes(8)
    encryptor = Cipher(algorithms.AES(key), modes.CTR(counter)).encryptor()
    return np.frombuffer(encryptor.update(bytes(length)), dtype=np.uint8)


def rechunk(frames: Iterable[np.ndarray], size: int = CHUNK_SIZE) -> Iterator[np.ndarray]:
    """Reagrupa cuadros consecutivos en bloques MPC de ``size`` valores."""

    buffer = np.empty(size, dtype=np.uint8)
    filled = 0
    for frame in frames:
        offset = 0
        while offset < len(frame):
            n = min(size - filled, len(frame) - offset)
            buffer[filled : filled + n] = frame[offset : offset + n]
            filled += n
            offset += n
            if filled == size:
                yield buffer.copy()
                filled = 0
    if filled:
        yield buffer[:filled].copy()


def padded_words(values: np.ndarray, size: int = CHUNK_SIZE) -> np.ndarray:
    words = np.zeros(size, dtype="<u8")
    words[: len(values)] = values
    return words


def chunk_count(payload_size: int, size: int = CHUNK_SIZE) -> int:
    return math.ceil(payload_size / size)


@dataclass(frozen=True)
class ExternalIoSettings:
    hostnames: tuple[str, str, str]
    port_base: int
    certificate_dir: Path
    timeout: float

    @classmethod
    def from_environment(cls) -> "ExternalIoSettings":
        hosts = tuple(
            item.strip()
            for item in os.getenv("MPC_PARTY_HOSTS", "party-0,party-1,party-2").split(",")
            if item.strip()
        )
        if len(hosts) != 3:
            raise ValueError("MPC_PARTY_HOSTS debe contener exactamente tres hosts")
        return cls(
            hostnames=(hosts[0], hosts[1], hosts[2]),
            port_base=int(os.getenv("MPC_CLIENT_PORT_BASE", "14000")),
            certificate_dir=Path(os.getenv("MPC_CERT_DIR", "/opt/MP-SPDZ/Player-Data")),
            timeout=float(os.getenv("MPC_SOCKET_TIMEOUT", "600")),
        )


class ExternalIoSession:
    """Cliente ExternalIO mínimo y vectorizado para un id de cliente fijo."""

    def __init__(self, client_id: int, settings: ExternalIoSettings | None = None) -> None:
        self.client_id = client_id
        self.settings = settings or ExternalIoSettings.from_environment()
        self.sockets: list[ssl.SSLSocket] = []

    def connect(self, attempts: int = 60) -> None:
        import time

        cert_dir = self.settings.certificate_dir
        name = f"C{self.client_id}"
        try:
            for party, host in enumerate(self.settings.hostnames):
                context = ssl.create_default_context(cafile=str(cert_dir / f"P{party}.pem"))
                context.load_cert_chain(cert_dir / f"{name}.pem", cert_dir / f"{name}.key")
                for attempt in range(attempts):
                    try:
                        plain = socket.create_connection(
                            (host, self.settings.port_base + party), timeout=self.settings.timeout
                        )
                        break
                    except (ConnectionRefusedError, socket.gaierror, socket.timeout):
                        if attempt == attempts - 1:
                            raise
                        time.sleep(1)
                identity = str(self.client_id).encode()
                plain.sendall(struct.pack("<I", len(identity)) + identity)
                secure = context.wrap_socket(plain, server_hostname=f"P{party}")
                secure.settimeout(self.settings.timeout)
                self.sockets.append(secure)
            specifications = [self._receive(connection) for connection in self.sockets]
        except BaseException:
            self.close()
            raise
        if any(spec != specifications[0] for spec in specifications) or len(specifications[0]) != 12:
            raise OfflineProtocolError("Especificaciones MPC inconsistentes")
        kind, modulus_bits, word_bits = struct.unpack("<iii", specifications[0])
        if (kind, modulus_bits, word_bits) != (ord("R"), 64, 64):
            raise OfflineProtocolError("Se requiere el ring MPC de 64 bits")

    def handshake(self, payload_size: int, number_chunks: int) -> None:
        self.send_words(np.array([payload_size, number_chunks], dtype="<u8"))
        for connection in self.sockets:
            ack = np.frombuffer(self._receive(connection), dtype="<u8")
            if tuple(int(v) for v in ack) != OFFLINE_ACK:
                raise OfflineProtocolError("Una party no confirmó el programa offline")

    def send_words(self, words: np.ndarray) -> None:
        body = np.ascontiguousarray(words, dtype="<u8").tobytes()
        message = struct.pack("<I", len(body)) + body
        for connection in self.sockets:
            connection.sendall(message)

    def receive_sum(self, count: int) -> np.ndarray:
        total = np.zeros(count, dtype=np.uint64)
        for connection in self.sockets:
            body = self._receive(connection)
            if len(body) != count * 8:
                raise OfflineProtocolError(
                    f"Longitud inesperada de ExternalIO: {len(body)} bytes para {count} valores"
                )
            total += np.frombuffer(body, dtype="<u8")
        return total

    def input_private(self, words: np.ndarray) -> None:
        """Entrada privada: recibe r = suma de shares aleatorios y envía x + r."""

        masked = np.asarray(words, dtype=np.uint64) + self.receive_sum(len(words))
        self.send_words(masked)

    def close(self) -> None:
        for connection in self.sockets:
            try:
                connection.close()
            except OSError:
                pass
        self.sockets = []

    def __enter__(self) -> "ExternalIoSession":
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @staticmethod
    def _exactly(connection: ssl.SSLSocket, count: int) -> bytes:
        buffer = bytearray(count)
        view = memoryview(buffer)
        received = 0
        while received < count:
            read = connection.recv_into(view[received:], count - received)
            if not read:
                raise OfflineProtocolError("Una party cerró la conexión ExternalIO")
            received += read
        return bytes(buffer)

    def _receive(self, connection: ssl.SSLSocket) -> bytes:
        (length,) = struct.unpack("<I", self._exactly(connection, 4))
        if not 0 < length <= MAX_MESSAGE:
            raise OfflineProtocolError("Longitud de mensaje ExternalIO inválida")
        return self._exactly(connection, length)


def decode_output(words: np.ndarray, length: int) -> np.ndarray:
    """z = (s0+s1+s2)*(1-m) en Z(2^64) -> píxel anonimizado uint8."""

    if (words[:length] > MAX_OUTPUT_VALUE).any():
        raise OfflineProtocolError("MP-SPDZ devolvió un valor fuera del rango de shares")
    if words[length:].any():
        raise OfflineProtocolError("MP-SPDZ devolvió padding no nulo")
    return (words[:length] % 256).astype(np.uint8)
