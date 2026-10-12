"""Test harness: the real mod Lua runs inside lupa against tests/mock_factorio.lua and is
reached through a fake RCON server, so the whole Python -> RCON -> Lua path is exercised."""

from __future__ import annotations

import pathlib
import socket
import struct
import threading

import pytest
from lupa import LuaRuntime

from factorio_agent_mcp import server
from factorio_agent_mcp.game import Game
from factorio_agent_mcp.rcon import Rcon

ROOT = pathlib.Path(__file__).resolve().parents[1]
PASSWORD = "secret"


class LuaWorld:
    def __init__(self, load_mod: bool = True) -> None:
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute((ROOT / "tests" / "mock_factorio.lua").read_text())
        self.lua.execute('package.path = "%s/?.lua;" .. package.path' % (ROOT / "mod" / "fac_agent"))
        if load_mod:
            self.lua.execute((ROOT / "mod" / "fac_agent" / "control.lua").read_text())
        self._lock = threading.Lock()

    def run(self, command: str) -> str:
        prefix = "/silent-command "
        if not command.startswith(prefix):
            return ""
        with self._lock:
            try:
                self.lua.execute(command[len(prefix):])
            except Exception as exc:  # noqa: BLE001 - mimic Factorio printing the error
                return f"Cannot execute command. Error: {exc}"
            return self.lua.eval("mock.take_output()")

    def exec(self, code: str):
        with self._lock:
            return self.lua.execute(code)

    def eval(self, code: str):
        with self._lock:
            return self.lua.eval(code)


def send_packet(conn: socket.socket, packet_id: int, packet_type: int, body: str) -> None:
    raw = body.encode()
    conn.sendall(struct.pack("<iii", 10 + len(raw), packet_id, packet_type) + raw + b"\x00\x00")


class FakeRconServer:
    def __init__(self, handler, password: str = PASSWORD, chunk: int = 4000) -> None:
        self.handler = handler
        self.password = password
        self.chunk = chunk
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.port = self.sock.getsockname()[1]
        self.connections = 0
        threading.Thread(target=self._serve, daemon=True).start()

    def close(self) -> None:
        self.sock.close()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            self.connections += 1
            threading.Thread(target=self._client, args=(conn,), daemon=True).start()

    @staticmethod
    def _recv(conn: socket.socket, count: int) -> bytes:
        data = b""
        while len(data) < count:
            chunk = conn.recv(count - len(data))
            if not chunk:
                raise ConnectionError
            data += chunk
        return data

    def _client(self, conn: socket.socket) -> None:
        try:
            while True:
                (size,) = struct.unpack("<i", self._recv(conn, 4))
                payload = self._recv(conn, size)
                packet_id, packet_type = struct.unpack("<ii", payload[:8])
                body = payload[8:-2].decode()
                if packet_type == 3:
                    send_packet(conn, packet_id if body == self.password else -1, 2, "")
                elif packet_type == 2:
                    out = self.handler(body)
                    pieces = [out[i:i + self.chunk] for i in range(0, len(out), self.chunk)] or [""]
                    for piece in pieces:
                        send_packet(conn, packet_id, 0, piece)
        except (ConnectionError, OSError):
            pass
        finally:
            conn.close()


@pytest.fixture
def world():
    w = LuaWorld()
    w.exec("mock.reset()")
    return w


@pytest.fixture
def rcon_server(world):
    srv = FakeRconServer(world.run)
    yield srv
    srv.close()


@pytest.fixture
def game(rcon_server):
    rcon = Rcon("127.0.0.1", rcon_server.port, PASSWORD, timeout=5)
    g = Game(rcon)
    server.configure(g, rcon)
    yield g
    rcon.close()
