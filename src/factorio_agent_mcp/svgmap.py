"""Realistic looking SVG of a snapshot, meant for the human operator (not for the model)."""

from __future__ import annotations

import math
from html import escape
from typing import Any

from .asciimap import ARROW
from .game import as_list, as_map

ORE_COLOR = {
    "iron-ore": ("#7d8a96", "#a9bac8"), "copper-ore": ("#c0683a", "#e9955e"), "coal": ("#1d1d1f", "#4a4a50"),
    "stone": ("#a08a5c", "#cdb98a"), "uranium-ore": ("#4fa83a", "#8be06a"), "crude-oil": ("#2b1a3a", "#6d3fa0"),
}
MACHINE_STYLE = {  # name -> (fill, stroke, label)
    "burner-mining-drill": ("#8a6a3a", "#4a3418", "BD"), "electric-mining-drill": ("#4a7aa8", "#1f3d5a", "MD"),
    "stone-furnace": ("#9b9387", "#4d4740", "F"), "steel-furnace": ("#7e8794", "#3c4350", "SF"),
    "electric-furnace": ("#6f7f90", "#2f3a46", "EF"),
    "assembling-machine-1": ("#6b8fb5", "#2b4660", "A1"), "assembling-machine-2": ("#5a7fb0", "#233f66", "A2"),
    "assembling-machine-3": ("#4f6fb8", "#1d2f7a", "A3"),
    "wooden-chest": ("#a9783c", "#5b3c17", ""), "iron-chest": ("#8793a0", "#3f4952", ""),
    "boiler": ("#b4533a", "#5d2a1d", "B"), "steam-engine": ("#8c9a8d", "#3f4a40", "SE"), "offshore-pump": ("#4a8bc2", "#1e4668", "P"),
    "lab": ("#7c5aa8", "#36234f", "Lab"), "inserter": ("#d3a53a", "#6a5018", ""), "burner-inserter": ("#b08a40", "#5a4418", ""),
    "long-handed-inserter": ("#c2503e", "#5a1f16", ""), "fast-inserter": ("#4a8ec2", "#1d4260", ""),
    "gun-turret": ("#6a6f55", "#2c2f20", "T"), "stone-wall": ("#b8b2a2", "#6f6a5c", ""), "radar": ("#5f8f9a", "#243f46", "R"),
    "storage-tank": ("#9aa6b0", "#454f58", "Tank"), "oil-refinery": ("#7a6f6a", "#332c28", "Ref"),
    "chemical-plant": ("#8a7aa0", "#382e4a", "Chem"), "rocket-silo": ("#b0b4bc", "#4a4e56", "Silo"),
}
STATUS_RING = {
    "no_power": "#e0c020", "no_fuel": "#e03030", "no_minable_resources": "#b040c0", "full_output": "#3090e0",
    "no_ingredients": "#e08030", "missing_required_fluid": "#e08030", "low_power": "#e0c020",
}
HUD_BG = "#111418"


def _hash(x: int, y: int) -> float:
    n = (x * 374761393 + y * 668265263) & 0xFFFFFFFF
    n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
    return ((n ^ (n >> 16)) & 0xFFFF) / 65535.0


def _tile_color(name: str, x: int, y: int) -> str:
    j = _hash(x, y)
    if "water" in name:
        deep = "deep" in name
        base = (28, 70, 120) if deep else (46, 104, 150)
        d = int(j * 14)
        return f"rgb({base[0] + d // 2},{base[1] + d},{base[2] + d})"
    if "sand" in name or "desert" in name:
        d = int(j * 16)
        return f"rgb({196 + d},{160 + d},{100 + d // 2})"
    if "dirt" in name or "red-desert" in name:
        d = int(j * 16)
        return f"rgb({140 + d},{98 + d // 2},{66 + d // 3})"
    d = int(j * 18)
    return f"rgb({64 + d // 2},{98 + d},{44 + d // 3})"


def render(snapshot: dict[str, Any], scale: int = 16, grid: bool = True, title: str | None = None) -> str:
    area = as_map(snapshot["area"])
    x1, y1, x2, y2 = int(area["x1"]), int(area["y1"]), int(area["x2"]), int(area["y2"])
    w, h = x2 - x1, y2 - y1
    s = max(4, int(scale))
    margin_l, margin_t = 36, 26
    legend_w = 190
    W, H = margin_l + w * s + legend_w, margin_t + max(h * s, 220) + 10
    out: list[str] = []
    add = out.append

    def X(tx: float) -> float:
        return margin_l + (tx - x1) * s

    def Y(ty: float) -> float:
        return margin_t + (ty - y1) * s

    add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        f'font-family="Segoe UI, Helvetica, Arial, sans-serif">')
    add('<defs>'
        '<filter id="sh" x="-20%" y="-20%" width="150%" height="150%"><feDropShadow dx="1" dy="2" stdDeviation="1.5" flood-opacity="0.45"/></filter>'
        '<linearGradient id="gl" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity="0.28"/><stop offset="1" stop-color="#000" stop-opacity="0.18"/></linearGradient>'
        '</defs>')
    add(f'<rect width="{W}" height="{H}" fill="{HUD_BG}"/>')
    add(f'<text x="{margin_l}" y="17" fill="#d8dee6" font-size="12">{escape(title or "Factorio")}  |  x {x1}..{x2 - 1}, y {y1}..{y2 - 1}  |  tick {snapshot.get("tick", "?")}</text>')

    # terrain
    palette = as_map(snapshot.get("palette"))
    rows = as_list(snapshot.get("rows"))
    add(f'<g clip-path="url(#clip)"><clipPath id="clip"><rect x="{margin_l}" y="{margin_t}" width="{w * s}" height="{h * s}"/></clipPath>')
    add(f'<rect x="{margin_l}" y="{margin_t}" width="{w * s}" height="{h * s}" fill="{_tile_color("grass", 0, 0)}"/>')
    for ry, row in enumerate(rows):
        for rx, ch in enumerate(row):
            name = palette.get(ch)
            if name is None:
                continue
            add(f'<rect x="{X(x1 + rx):.0f}" y="{Y(y1 + ry):.0f}" width="{s}" height="{s}" fill="{_tile_color(name, x1 + rx, y1 + ry)}"/>')

    # ore: blob per tile, density by amount
    for name, flat in as_map(snapshot.get("resources")).items():
        dark, light = ORE_COLOR.get(name, ("#777", "#aaa"))
        amounts = [flat[i + 2] for i in range(0, len(flat) - 2, 3)] or [1]
        top = max(amounts) or 1
        for i in range(0, len(flat) - 2, 3):
            tx, ty, amt = int(flat[i]), int(flat[i + 1]), flat[i + 2]
            add(f'<rect x="{X(tx):.0f}" y="{Y(ty):.0f}" width="{s}" height="{s}" fill="{dark}" opacity="0.55"/>')
            n = 2 + int(3 * min(1.0, amt / top))
            for k in range(n):
                jx, jy = _hash(tx * 7 + k, ty * 13), _hash(tx * 3, ty * 11 + k)
                add(f'<circle cx="{X(tx) + (0.15 + 0.7 * jx) * s:.1f}" cy="{Y(ty) + (0.15 + 0.7 * jy) * s:.1f}" r="{s * (0.11 + 0.08 * jx):.1f}" fill="{light}"/>')

    # trees
    flat = as_list(snapshot.get("trees"))
    for i in range(0, len(flat) - 1, 2):
        cx, cy = X(flat[i]), Y(flat[i + 1])
        add(f'<circle cx="{cx + 2:.1f}" cy="{cy + 3:.1f}" r="{s * 0.5:.1f}" fill="#000" opacity="0.25"/>'
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{s * 0.5:.1f}" fill="#2d5a2a"/>'
            f'<circle cx="{cx - s * 0.12:.1f}" cy="{cy - s * 0.14:.1f}" r="{s * 0.3:.1f}" fill="#3f7a38"/>')

    ents = as_list(snapshot.get("entities"))
    belts = [e for e in ents if e.get("t") in ("transport-belt", "underground-belt", "splitter")]
    pipes = [e for e in ents if e.get("t") in ("pipe", "pipe-to-ground")]
    poles = [e for e in ents if e.get("t") == "electric-pole"]
    others = [e for e in ents if e not in belts and e not in pipes and e not in poles]

    # pipes
    pipe_at = {(int(math.floor(p["x"])), int(math.floor(p["y"]))) for p in pipes}
    for p in pipes:
        tx, ty = int(math.floor(p["x"])), int(math.floor(p["y"]))
        cx, cy = X(tx) + s / 2, Y(ty) + s / 2
        for dx, dy in ((1, 0), (0, 1), (-1, 0), (0, -1)):
            if (tx + dx, ty + dy) in pipe_at:
                add(f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{cx + dx * s / 2:.1f}" y2="{cy + dy * s / 2:.1f}" stroke="#5f6c78" stroke-width="{s * 0.4:.1f}"/>')
        add(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{s * 0.28:.1f}" fill="#8996a2" stroke="#46525d"/>')

    # belts: yellow tile, dark rails, chevron in the running direction
    for b in belts:
        tx, ty = int(math.floor(b["x"])), int(math.floor(b["y"]))
        cx, cy = X(tx) + s / 2, Y(ty) + s / 2
        d = b.get("d") or "north"
        ang = {"north": -90, "east": 0, "south": 90, "west": 180}.get(d, -90)
        color = {"underground-belt": "#c9a227", "splitter": "#d9a520"}.get(b.get("t"), "#e0b833")
        add(f'<g transform="translate({cx:.1f},{cy:.1f}) rotate({ang})">'
            f'<rect x="{-s / 2:.1f}" y="{-s / 2:.1f}" width="{s}" height="{s}" fill="{color}"/>'
            f'<rect x="{-s / 2:.1f}" y="{-s * 0.5:.1f}" width="{s}" height="{s * 0.14:.1f}" fill="#7a5e10"/>'
            f'<rect x="{-s / 2:.1f}" y="{s * 0.36:.1f}" width="{s}" height="{s * 0.14:.1f}" fill="#7a5e10"/>'
            f'<polyline points="{-s * 0.18:.1f},{-s * 0.24:.1f} {s * 0.12:.1f},0 {-s * 0.18:.1f},{s * 0.24:.1f}" fill="none" stroke="#5a430a" stroke-width="{max(1.5, s * 0.12):.1f}" stroke-linejoin="round"/>'
            + (f'<circle r="{s * 0.16:.1f}" fill="#5a430a"/>' if b.get("t") == "underground-belt" else "") + '</g>')

    # machines
    for e in sorted(others, key=lambda it: -(float(it.get("w") or 1) * float(it.get("h") or 1))):
        ew, eh = float(e.get("w") or 1), float(e.get("h") or 1)
        left, top = X(e["x"] - ew / 2), Y(e["y"] - eh / 2)
        pw, ph = ew * s, eh * s
        if e.get("f") == "e":
            add(f'<circle cx="{X(e["x"]):.1f}" cy="{Y(e["y"]):.1f}" r="{s * 0.4:.1f}" fill="#b02020" stroke="#ff7070" stroke-width="1.5"/>')
            continue
        fill, stroke, label = MACHINE_STYLE.get(e["n"], ("#8a8f99", "#3a3d44", e["n"][:3].upper()))
        inset = max(1.0, s * 0.06)
        add(f'<g filter="url(#sh)"><rect x="{left + inset:.1f}" y="{top + inset:.1f}" width="{pw - 2 * inset:.1f}" height="{ph - 2 * inset:.1f}" rx="{s * 0.2:.1f}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>'
            f'<rect x="{left + inset:.1f}" y="{top + inset:.1f}" width="{pw - 2 * inset:.1f}" height="{ph - 2 * inset:.1f}" rx="{s * 0.2:.1f}" fill="url(#gl)"/></g>')
        ring = STATUS_RING.get(e.get("s") or "")
        if ring:
            add(f'<rect x="{left:.1f}" y="{top:.1f}" width="{pw:.1f}" height="{ph:.1f}" rx="{s * 0.25:.1f}" fill="none" stroke="{ring}" stroke-width="2.2"/>')
        # facing marker for things that have a direction
        d = e.get("d")
        if d and e.get("t") in ("mining-drill", "inserter", "assembling-machine", "offshore-pump") and ew * eh <= 9:
            vx, vy = {"north": (0, -1), "east": (1, 0), "south": (0, 1), "west": (-1, 0)}.get(d, (0, 0))
            cx, cy = X(e["x"]), Y(e["y"])
            tipx, tipy = cx + vx * pw * 0.42, cy + vy * ph * 0.42
            add(f'<polygon points="{tipx:.1f},{tipy:.1f} {tipx - vx * s * 0.3 - vy * s * 0.22:.1f},{tipy - vy * s * 0.3 + vx * s * 0.22:.1f} {tipx - vx * s * 0.3 + vy * s * 0.22:.1f},{tipy - vy * s * 0.3 - vx * s * 0.22:.1f}" fill="#fff" opacity="0.85"/>')
        text = e.get("r") or label
        if text and pw >= s * 1.5:
            add(f'<text x="{left + pw / 2:.1f}" y="{top + ph / 2 + 4:.1f}" text-anchor="middle" fill="#fff" font-size="{max(8, int(s * 0.6))}" '
                f'style="paint-order:stroke" stroke="#000" stroke-width="2.5">{escape(text)}</text>')

    # wires between nearby poles, then poles
    for i, a in enumerate(poles):
        for b in poles[i + 1:]:
            if math.hypot(a["x"] - b["x"], a["y"] - b["y"]) <= 7.5:
                add(f'<line x1="{X(a["x"]):.1f}" y1="{Y(a["y"]):.1f}" x2="{X(b["x"]):.1f}" y2="{Y(b["y"]):.1f}" stroke="#d9a066" stroke-width="1" opacity="0.7"/>')
    for p in poles:
        add(f'<circle cx="{X(p["x"]):.1f}" cy="{Y(p["y"]):.1f}" r="{s * 0.2:.1f}" fill="#8a5a2b" stroke="#2b1a0a"/>')

    # agent
    ag = as_map(snapshot.get("agent"))
    if ag:
        ax, ay = X(ag["x"]), Y(ag["y"])
        add(f'<circle cx="{ax:.1f}" cy="{ay:.1f}" r="{s * 0.5:.1f}" fill="#ffd54a" stroke="#222" stroke-width="2"/>'
            f'<circle cx="{ax:.1f}" cy="{ay:.1f}" r="{s * 1.0:.1f}" fill="none" stroke="#ffd54a" stroke-width="1" opacity="0.6"/>')
    add('</g>')

    # grid and axes
    if grid:
        step = 5 if s >= 10 else 10
        for tx in range(x1, x2 + 1):
            if tx % step == 0:
                add(f'<line x1="{X(tx):.1f}" y1="{margin_t}" x2="{X(tx):.1f}" y2="{margin_t + h * s}" stroke="#fff" stroke-opacity="{0.22 if tx % 10 == 0 else 0.09}"/>')
        for ty in range(y1, y2 + 1):
            if ty % step == 0:
                add(f'<line x1="{margin_l}" y1="{Y(ty):.1f}" x2="{margin_l + w * s}" y2="{Y(ty):.1f}" stroke="#fff" stroke-opacity="{0.22 if ty % 10 == 0 else 0.09}"/>')
    for tx in range(x1, x2 + 1):
        if tx % 10 == 0:
            add(f'<text x="{X(tx):.1f}" y="{margin_t - 4}" fill="#9aa7b4" font-size="10" text-anchor="middle">{tx}</text>')
    for ty in range(y1, y2 + 1):
        if ty % 10 == 0:
            add(f'<text x="{margin_l - 4}" y="{Y(ty) + 3:.1f}" fill="#9aa7b4" font-size="10" text-anchor="end">{ty}</text>')
    add(f'<rect x="{margin_l}" y="{margin_t}" width="{w * s}" height="{h * s}" fill="none" stroke="#3a4450"/>')

    # legend with only what is on the map
    lx, ly = margin_l + w * s + 14, margin_t + 8
    items: list[tuple[str, str]] = [("#ffd54a", "you")]
    for name in as_map(snapshot.get("resources")):
        items.append((ORE_COLOR.get(name, ("#777", "#aaa"))[1], name))
    if as_list(snapshot.get("trees")):
        items.append(("#3f7a38", "tree"))
    seen = {e["n"] for e in others if e.get("f") != "e"}
    for n in sorted(seen):
        items.append((MACHINE_STYLE.get(n, ("#8a8f99", "", ""))[0], n))
    if belts:
        items.append(("#e0b833", "belt (chevron = direction)"))
    if pipes:
        items.append(("#8996a2", "pipe"))
    if poles:
        items.append(("#8a5a2b", "pole / wire"))
    if any(e.get("f") == "e" for e in others):
        items.append(("#b02020", "enemy"))
    if any(STATUS_RING.get(e.get("s") or "") for e in others):
        items.append(("#e03030", "ring = problem (fuel/power/...)"))
    for color, name in items[:22]:
        add(f'<rect x="{lx}" y="{ly - 9}" width="12" height="12" rx="2" fill="{color}" stroke="#000" stroke-opacity="0.4"/>'
            f'<text x="{lx + 18}" y="{ly + 1}" fill="#cfd6de" font-size="11">{escape(name)}</text>')
        ly += 17
    if snapshot.get("truncated"):
        add(f'<text x="{lx}" y="{ly + 8}" fill="#e08030" font-size="11">entity limit reached</text>')
    add('</svg>')
    return "\n".join(out)
