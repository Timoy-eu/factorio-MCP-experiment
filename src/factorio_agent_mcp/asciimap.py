"""ASCII rendering of a snapshot: one character per tile, belts as arrows."""

from __future__ import annotations

import math
from typing import Any

from .game import as_list, as_map

MAX_COLS = 100
MAX_ROWS = 60

LAYERS = ("machines", "belts", "pipes", "power", "ore", "trees", "water", "enemies")

ORE_CHAR = {
    "iron-ore": "i", "copper-ore": "c", "coal": "k", "stone": "s", "uranium-ore": "u",
    "crude-oil": "o",
}
ARROW = {"north": "^", "east": ">", "south": "v", "west": "<"}
# entity name -> (char, layer)
KNOWN = {
    "burner-mining-drill": "D", "electric-mining-drill": "D", "pumpjack": "J",
    "stone-furnace": "F", "steel-furnace": "F", "electric-furnace": "F",
    "wooden-chest": "C", "iron-chest": "C", "steel-chest": "C",
    "inserter": "n", "burner-inserter": "n", "long-handed-inserter": "n", "fast-inserter": "n",
    "assembling-machine-1": "A", "assembling-machine-2": "A", "assembling-machine-3": "A",
    "lab": "L", "boiler": "B", "steam-engine": "S", "offshore-pump": "W",
    "chemical-plant": "H", "oil-refinery": "R", "rocket-silo": "K",
    "storage-tank": "T", "radar": "Q", "gun-turret": "G", "stone-wall": "#",
    "splitter": "Y", "pipe-to-ground": "p",
}
BELT_NAMES_UNDER = {"underground-belt": "u"}


def _footprint(item: dict[str, Any]) -> tuple[int, int, int, int]:
    w, h = float(item.get("w") or 1), float(item.get("h") or 1)
    x, y = float(item["x"]), float(item["y"])
    left = int(math.floor(x - w / 2 + 1e-6))
    top = int(math.floor(y - h / 2 + 1e-6))
    return left, top, max(1, round(w)), max(1, round(h))


def _glyph(item: dict[str, Any]) -> tuple[str, str]:
    """(character, layer) for one entity."""
    name, etype = item.get("n", ""), item.get("t", "")
    d = item.get("d")
    if etype == "transport-belt" or name.endswith("transport-belt") and "underground" not in name and "splitter" not in name:
        return ARROW.get(d or "", "b"), "belts"
    if etype == "underground-belt":
        return "u", "belts"
    if etype == "splitter":
        return "Y", "belts"
    if etype in ("pipe",):
        return "=", "pipes"
    if etype == "pipe-to-ground":
        return "p", "pipes"
    if etype == "electric-pole":
        return "+", "power"
    if etype == "unit" or item.get("f") == "e":
        return "E", "enemies"
    if name in KNOWN:
        return KNOWN[name], "machines"
    return "X", "machines"


def _select(layers: str | None) -> set[str]:
    if not layers or layers.strip().lower() in ("all", "*"):
        return set(LAYERS)
    wanted = {p.strip().lower() for p in layers.replace(";", ",").split(",") if p.strip()}
    alias = {"belt": "belts", "pipe": "pipes", "pole": "power", "poles": "power", "electric": "power",
             "machine": "machines", "entities": "machines", "resources": "ore", "tree": "trees", "enemy": "enemies"}
    return {alias.get(p, p) for p in wanted} & set(LAYERS) or set(LAYERS)


def render(snapshot: dict[str, Any], layers: str | None = None) -> str:
    area = as_map(snapshot["area"])
    x1, y1, x2, y2 = int(area["x1"]), int(area["y1"]), int(area["x2"]), int(area["y2"])
    w, h = x2 - x1, y2 - y1
    use = _select(layers)
    grid = [["." for _ in range(w)] for _ in range(h)]
    used: dict[str, str] = {}

    def put(tx: int, ty: int, ch: str, meaning: str) -> None:
        if 0 <= tx - x1 < w and 0 <= ty - y1 < h:
            grid[ty - y1][tx - x1] = ch
            used.setdefault(ch, meaning)

    if "water" in use:
        palette = as_map(snapshot.get("palette"))
        wet = {c for c, name in palette.items() if "water" in name}
        for ry, row in enumerate(as_list(snapshot.get("rows"))):
            for rx, ch in enumerate(row):
                if ch in wet:
                    put(x1 + rx, y1 + ry, "~", "water")
    if "ore" in use:
        for name, flat in as_map(snapshot.get("resources")).items():
            ch = ORE_CHAR.get(name, "r")
            for i in range(0, len(flat) - 2, 3):
                put(int(flat[i]), int(flat[i + 1]), ch, name)
    if "trees" in use:
        flat = as_list(snapshot.get("trees"))
        for i in range(0, len(flat) - 1, 2):
            put(int(math.floor(flat[i])), int(math.floor(flat[i + 1])), "t", "tree")

    # big things first so that small things on top stay visible
    items = sorted(as_list(snapshot.get("entities")), key=lambda it: -(float(it.get("w") or 1) * float(it.get("h") or 1)))
    for it in items:
        ch, layer = _glyph(it)
        if layer not in use:
            continue
        left, top, fw, fh = _footprint(it)
        for ty in range(top, top + fh):
            for tx in range(left, left + fw):
                put(tx, ty, ch, it["n"] if layer in ("machines", "enemies") else _meaning(ch, it))
    ag = as_map(snapshot.get("agent"))
    if ag:
        put(int(math.floor(ag["x"])), int(math.floor(ag["y"])), "@", "you")

    return _compose(grid, x1, y1, w, h, used, snapshot)


def _meaning(ch: str, it: dict[str, Any]) -> str:
    return {"^": "belt north", ">": "belt east", "v": "belt south", "<": "belt west",
            "u": "underground belt", "Y": "splitter", "=": "pipe", "p": "pipe-to-ground",
            "+": "electric pole"}.get(ch, it.get("n", ch))


def _compose(grid, x1, y1, w, h, used, snapshot) -> str:
    pad = max(len(str(y1)), len(str(y1 + h - 1)), 3)
    # header with a number every 10 tiles
    ruler = [" "] * w
    for tx in range(x1, x1 + w):
        if tx % 10 == 0:
            label = str(tx)
            for k, c in enumerate(label):
                if tx - x1 + k < w:
                    ruler[tx - x1 + k] = c
    lines = [" " * (pad + 1) + "".join(ruler)]
    for ry in range(h):
        ty = y1 + ry
        label = str(ty) if (ty % 5 == 0 or ry == 0) else ""
        lines.append(label.rjust(pad) + " " + "".join(grid[ry]))
    legend = "  ".join(f"{c}={m}" for c, m in sorted(used.items(), key=lambda kv: kv[1]))
    head = (f"map x {x1}..{x1 + w - 1}, y {y1}..{y1 + h - 1} (1 char = 1 tile, x grows right, y grows down, "
            f"north is up). '.' = empty land")
    out = [head, *lines, "legend: " + legend if legend else "legend: (nothing to show)"]
    if snapshot.get("truncated"):
        out.append("note: too many entities, some are missing; use a smaller area")
    return "\n".join(out)


def check_size(x1: float, y1: float, x2: float, y2: float) -> str | None:
    w = int(math.ceil(max(x1, x2))) - int(math.floor(min(x1, x2)))
    h = int(math.ceil(max(y1, y2))) - int(math.floor(min(y1, y2)))
    if w > MAX_COLS or h > MAX_ROWS:
        return f"area {w}x{h} is too big for text, maximum {MAX_COLS}x{MAX_ROWS}; split it up or use render_map for a picture"
    return None
