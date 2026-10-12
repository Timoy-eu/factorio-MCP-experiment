"""Build safe `remote.call` commands for the fac_agent mod."""

from __future__ import annotations

import math

INTERFACE = "fac_agent"


def lua_string(value: str) -> str:
    out = ['"']
    for ch in value:
        code = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif code < 32 or code == 127:
            out.append(f"\\{code:03d}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def lua_literal(value: object) -> str:
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non finite number cannot be sent to Lua")
        return repr(value)
    if isinstance(value, str):
        return lua_string(value)
    if isinstance(value, (list, tuple)):
        return "{" + ", ".join(lua_literal(v) for v in value) + "}"
    raise TypeError(f"unsupported Lua argument type: {type(value).__name__}")


def remote_call(function: str, *args: object) -> str:
    """Return the RCON command that calls fac_agent.<function>(*args) and prints its result."""
    if not function.isidentifier():
        raise ValueError(f"bad function name {function!r}")
    arguments = "".join(", " + lua_literal(a) for a in args)
    return f'/silent-command rcon.print(remote.call("{INTERFACE}", "{function}"{arguments}))'
