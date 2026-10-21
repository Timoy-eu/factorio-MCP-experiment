"""Checks that the mock cannot do: rules of the real Factorio Lua environment."""

from __future__ import annotations

import pathlib
import re

MOD = pathlib.Path(__file__).resolve().parents[1] / "mod" / "fac_agent"


def test_require_only_at_file_level():
    """Factorio allows require() only while control.lua is being parsed ("Require can't be used outside of control.lua parsing").
    A require inside a function works in the mock and fails in the game, so every require must be a top-level `local X = require(...)`."""
    bad = []
    for path in [MOD / "control.lua", *sorted((MOD / "scripts").glob("*.lua"))]:
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if "require(" in line and not line.lstrip().startswith("--") and not re.match(r'^local \w+ = require\("[\w.]+"\)', line):
                bad.append(f"{path.name}:{number}: {line.strip()}")
    assert not bad, "require() must be a top-level local assignment:\n" + "\n".join(bad)


def test_no_require_cycle_between_script_files():
    deps: dict[str, set[str]] = {}
    for path in (MOD / "scripts").glob("*.lua"):
        deps[path.stem] = set(re.findall(r'require\("scripts\.(\w+)"\)', path.read_text()))
    state: dict[str, int] = {}

    def visit(name: str, chain: list[str]) -> None:
        assert state.get(name) != 1, "require cycle: " + " -> ".join(chain + [name])
        if state.get(name) == 2:
            return
        state[name] = 1
        for dep in deps.get(name, ()):
            visit(dep, chain + [name])
        state[name] = 2

    for name in deps:
        visit(name, [])
