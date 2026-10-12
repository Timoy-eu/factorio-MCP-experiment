"""Typed access to the fac_agent mod: call a function, get a dict or a GameError."""

from __future__ import annotations

import json
import time
from typing import Any, Protocol

from .luacall import remote_call
from .rcon import RconError


class Transport(Protocol):
    def command(self, text: str) -> str: ...


class GameError(Exception):
    def __init__(self, code: str, message: str, data: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data or {}


def as_map(value: Any) -> dict[str, Any]:
    """Factorio serialises empty tables as [] - treat that as an empty mapping."""
    if isinstance(value, dict):
        return value
    return {}


def as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return []


def parse_reply(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if not text:
        raise GameError("no_response", "Factorio returned nothing (twice). Check: is the game paused (auto_pause in server-settings.json), is a save loaded, is the fac_agent mod active? Try run_lua with rcon.print(game.tick).")
    if "Unknown interface" in text:
        raise GameError("mod_missing", "The fac_agent mod is not loaded in this save.")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise GameError("bad_response", text[:300]) from None
    if not isinstance(data, dict):
        raise GameError("bad_response", text[:300])
    return data


class Game:
    def __init__(self, transport: Transport) -> None:
        self.transport = transport

    def call(self, function: str, *args: object) -> dict[str, Any]:
        try:
            raw = self.transport.command(remote_call(function, *args))
        except RconError as exc:
            raise GameError("no_connection", str(exc)) from exc
        if not raw.strip():  # sometimes the first answer after a pause is empty, try once more
            time.sleep(0.3)
            try:
                raw = self.transport.command(remote_call(function, *args))
            except RconError as exc:
                raise GameError("no_connection", str(exc)) from exc
        data = parse_reply(raw)
        if not data.get("ok"):
            code = str(data.get("code", "error"))
            message = str(data.get("message", "unknown error"))
            extra = {k: v for k, v in data.items() if k not in ("ok", "code", "message")}
            raise GameError(code, message, extra)
        return data
