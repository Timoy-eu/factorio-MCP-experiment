"""Blueprint library: the model and the human develop reusable layouts together.

A blueprint is a plain JSON file (easy to read and edit by hand) in the blueprint folder.
Entities are stored relative to the top left corner of the captured area.
"""

from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path
from typing import Any

DIRS = ["north", "east", "south", "west"]
LAYER_ORDER = {"machines": 0, "pipes": 1, "power": 2, "inserters": 3, "belts": 4}


def safe_name(name: str) -> str:
    clean = re.sub(r"[^a-z0-9_-]+", "-", name.strip().lower()).strip("-")
    if not clean:
        raise ValueError("blueprint name must contain letters or digits")
    return clean


def rotate_dir(direction: str | None, quarter_turns: int) -> str | None:
    if direction not in DIRS:
        return direction
    return DIRS[(DIRS.index(direction) + quarter_turns) % 4]


def rotate_offset(dx: float, dy: float, quarter_turns: int) -> tuple[float, float]:
    for _ in range(quarter_turns % 4):  # clockwise on screen (y grows down): (x, y) -> (-y, x)
        dx, dy = -dy, dx
    return dx, dy


def layer_of(entity: dict[str, Any]) -> int:
    t = entity.get("t", "")
    if t in ("transport-belt", "underground-belt", "splitter"):
        return LAYER_ORDER["belts"]
    if t in ("pipe", "pipe-to-ground"):
        return LAYER_ORDER["pipes"]
    if t == "electric-pole":
        return LAYER_ORDER["power"]
    if t == "inserter":
        return LAYER_ORDER["inserters"]
    return LAYER_ORDER["machines"]


def from_snapshot(snapshot: dict[str, Any], x1: float, y1: float, x2: float, y2: float) -> dict[str, Any]:
    left, right = min(x1, x2), max(x1, x2)
    top, bottom = min(y1, y2), max(y1, y2)
    ox, oy = math.floor(left), math.floor(top)
    entities = []
    for e in snapshot.get("entities", []):
        if e.get("f") != "p" or not (left <= e["x"] < right and top <= e["y"] < bottom):
            continue
        item = {"n": e["n"], "t": e.get("t", ""), "dx": round(e["x"] - ox, 2), "dy": round(e["y"] - oy, 2),
                "w": e.get("w", 1), "h": e.get("h", 1)}
        if e.get("d"):
            item["d"] = e["d"]
        if e.get("r"):
            item["r"] = e["r"]
        entities.append(item)
    entities.sort(key=lambda it: (layer_of(it), it["dy"], it["dx"]))
    return {
        "width": math.ceil(right) - ox, "height": math.ceil(bottom) - oy, "entities": entities,
    }


def items_needed(entities: list[dict[str, Any]]) -> dict[str, int]:
    need: dict[str, int] = {}
    for e in entities:
        need[e["n"]] = need.get(e["n"], 0) + 1
    return need


def transformed(blueprint: dict[str, Any], quarter_turns: int) -> list[dict[str, Any]]:
    out = []
    for e in blueprint["entities"]:
        dx, dy = rotate_offset(e["dx"], e["dy"], quarter_turns)
        item = dict(e)
        item["dx"], item["dy"] = dx, dy
        if e.get("d"):
            item["d"] = rotate_dir(e["d"], quarter_turns)
        out.append(item)
    return out


def anchor_shift(blueprint: dict[str, Any], quarter_turns: int) -> tuple[float, float]:
    """Offset that moves the rotated blueprint's top left corner back to (0, 0)."""
    w, h = blueprint["width"], blueprint["height"]
    corners = [rotate_offset(cx, cy, quarter_turns) for cx, cy in ((0, 0), (w, 0), (0, h), (w, h))]
    return -min(c[0] for c in corners), -min(c[1] for c in corners)


class Store:
    def __init__(self, folder: str | Path) -> None:
        self.folder = Path(folder)

    def path(self, name: str) -> Path:
        return self.folder / f"{safe_name(name)}.json"

    def names(self) -> list[str]:
        if not self.folder.exists():
            return []
        return sorted(p.stem for p in self.folder.glob("*.json"))

    def load(self, name: str) -> dict[str, Any]:
        p = self.path(name)
        if not p.exists():
            raise KeyError(name)
        return json.loads(p.read_text(encoding="utf-8"))

    def save(self, blueprint: dict[str, Any]) -> Path:
        self.folder.mkdir(parents=True, exist_ok=True)
        p = self.path(blueprint["name"])
        p.write_text(json.dumps(blueprint, indent=1, ensure_ascii=False), encoding="utf-8")
        return p

    def delete(self, name: str) -> bool:
        p = self.path(name)
        if p.exists():
            p.unlink()
            return True
        return False


class Notes:
    """Small persistent notebook so the model keeps goals and locations across context resets."""

    def __init__(self, file: str | Path) -> None:
        self.file = Path(file)

    def _read(self) -> list[dict[str, Any]]:
        if not self.file.exists():
            return []
        return json.loads(self.file.read_text(encoding="utf-8"))

    def _write(self, items: list[dict[str, Any]]) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.file.write_text(json.dumps(items, indent=1, ensure_ascii=False), encoding="utf-8")

    def add(self, text: str, tag: str = "") -> int:
        items = self._read()
        nid = max((i["id"] for i in items), default=0) + 1
        items.append({"id": nid, "tag": tag, "text": text, "time": time.strftime("%Y-%m-%d %H:%M")})
        self._write(items)
        return nid

    def list(self, tag: str = "") -> list[dict[str, Any]]:
        return [i for i in self._read() if not tag or i["tag"] == tag]

    def remove(self, nid: int) -> bool:
        items = self._read()
        kept = [i for i in items if i["id"] != nid]
        self._write(kept)
        return len(kept) != len(items)
