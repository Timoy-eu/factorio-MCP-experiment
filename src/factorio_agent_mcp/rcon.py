"""Minimal thread safe Source RCON client, tuned for Factorio.

Factorio does not mirror an empty RESPONSE_VALUE packet like Valve servers do, so long
answers (split over several packets) are delimited with a real follow-up command whose
answer marks the end of the first reply.
"""

from __future__ import annotations

import socket
import struct
import threading

SERVERDATA_RESPONSE_VALUE = 0
SERVERDATA_EXECCOMMAND = 2
SERVERDATA_AUTH_RESPONSE = 2
SERVERDATA_AUTH = 3

BOUNDARY_COMMAND = '/silent-command rcon.print("")'


class RconError(Exception):
    """Connection, authentication or protocol problem."""


def encode_packet(packet_id: int, packet_type: int, body: str) -> bytes:
    raw = body.encode("utf-8")
    return struct.pack("<iii", 10 + len(raw), packet_id, packet_type) + raw + b"\x00\x00"


class Rcon:
    def __init__(self, host: str = "127.0.0.1", port: int = 27015, password: str = "",
                 timeout: float = 30.0) -> None:
        self.host = host
        self.port = port
        self.password = password
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self._lock = threading.Lock()
        self._next_id = 0

    # -- connection -----------------------------------------------------------------

    def _new_id(self) -> int:
        self._next_id = (self._next_id % 2_000_000_000) + 1
        return self._next_id

    def _read_exact(self, count: int) -> bytes:
        assert self._sock is not None
        data = b""
        while len(data) < count:
            chunk = self._sock.recv(count - len(data))
            if not chunk:
                raise RconError("connection closed by Factorio")
            data += chunk
        return data

    def _read_packet(self) -> tuple[int, int, str]:
        (size,) = struct.unpack("<i", self._read_exact(4))
        if size < 10 or size > 1_000_000:
            raise RconError(f"invalid RCON packet size {size}")
        payload = self._read_exact(size)
        packet_id, packet_type = struct.unpack("<ii", payload[:8])
        return packet_id, packet_type, payload[8:-2].decode("utf-8", errors="replace")

    def _connect(self) -> None:
        self._close()
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as exc:
            raise RconError(f"cannot connect to {self.host}:{self.port} ({exc})") from exc
        sock.settimeout(self.timeout)
        self._sock = sock
        auth_id = self._new_id()
        try:
            sock.sendall(encode_packet(auth_id, SERVERDATA_AUTH, self.password))
            while True:
                packet_id, packet_type, _ = self._read_packet()
                if packet_type == SERVERDATA_AUTH_RESPONSE:
                    if packet_id == -1:
                        raise RconError("RCON authentication failed (wrong password?)")
                    return
        except (OSError, RconError):
            self._close()
            raise

    def _close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def close(self) -> None:
        with self._lock:
            self._close()

    # -- commands -------------------------------------------------------------------

    def command(self, text: str) -> str:
        """Run a console command and return everything it printed."""
        with self._lock:
            if self._sock is None:
                self._connect()
            main_id, boundary_id = self._new_id(), self._new_id()
            packets = (encode_packet(main_id, SERVERDATA_EXECCOMMAND, text)
                       + encode_packet(boundary_id, SERVERDATA_EXECCOMMAND, BOUNDARY_COMMAND))
            try:
                assert self._sock is not None
                self._sock.sendall(packets)
            except OSError:
                # nothing reached the server before the failure, so one reconnect is safe
                self._connect()
                assert self._sock is not None
                self._sock.sendall(packets)
            chunks: list[str] = []
            try:
                while True:
                    packet_id, packet_type, body = self._read_packet()
                    if packet_type != SERVERDATA_RESPONSE_VALUE:
                        continue
                    if packet_id == boundary_id:
                        break
                    if packet_id == main_id:
                        chunks.append(body)
            except (OSError, RconError) as exc:
                self._close()
                raise RconError(f"connection lost while waiting for an answer ({exc})") from exc
            return "".join(chunks)
