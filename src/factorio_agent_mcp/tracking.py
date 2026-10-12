"""Item tracking and machine statistics built on repeated samples from the mod."""

from __future__ import annotations

from typing import Any, Callable

from .game import Game, GameError, as_list, as_map

TICKS_PER_SECOND = 60
STUCK_TICKS = 180  # an item that stays on the same belt tile this long is stuck

HINTS = {
    "no_fuel": "put fuel in (fuel tool)",
    "no_power": "connect it to power (connect kind=power)",
    "low_power": "add generators or reduce consumers",
    "no_ingredients": "the input side delivers too little, check the belt or inserter feeding it",
    "item_ingredient_shortage": "the input side delivers too little, check the belt or inserter feeding it",
    "fluid_ingredient_shortage": "fluid input is missing, check pipes and pumps",
    "full_output": "the output is blocked, add an inserter/belt that takes items away",
    "no_minable_resources": "ore under the drill is exhausted, move it to richer ground",
    "missing_required_fluid": "fluid input is missing, check pipes and pumps",
    "no_recipe": "set a recipe (set_recipe)",
}


def belt_text(d: dict[str, Any]) -> str:
    if not d.get("belts"):
        return "no belts of yours in that area"
    items = ", ".join(f"{v} {k}" for k, v in sorted(as_map(d.get("items")).items(), key=lambda kv: -kv[1])) or "nothing"
    text = (f"{d['belts']} belt pieces, {d['empty']} empty, carrying {d['total']} items ({d['fill']}% of capacity): {items}")
    if d["fill"] >= 90:
        text += ". Belt is full: if nothing leaves it, the end is blocked"
    elif d["total"] == 0:
        text += ". Belt is empty: the source delivers nothing or the belt is not connected"
    tiles = as_list(d.get("tiles"))
    if tiles:
        text += "\n" + "; ".join(
            f"({t['x']:g},{t['y']:g}){t['d']} " + ",".join(f"{v} {k}" for k, v in as_map(t.get("n")).items()) for t in tiles[:12])
    return text


def trace(game: Game, x: float, y: float, item: str, wait_seconds: float, sleep: Callable[[float], None]) -> str:
    start = game.call("trace_start", x, y, item)
    tid = start["id"]
    waited = 0.0
    last: dict[str, Any] = start
    step = 0.5
    while waited <= wait_seconds:
        sleep(step)
        waited += step
        last = game.call("trace_probe", tid)
        elapsed = last["tick"] - last["started"]
        if not last["found"]:
            if last["tiles"] > 0 or elapsed > 30:
                return (f"{item} travelled {last['tiles']:g} tiles in {elapsed / TICKS_PER_SECOND:.1f}s and left the belt near "
                        f"({last['x']:g},{last['y']:g}) (picked up by an inserter, fell into a machine or the belt ends there)")
        elif last["idle"] >= STUCK_TICKS:
            return (f"STUCK: {item} travelled {last['tiles']:g} tiles and has been standing at ({last['x']:g},{last['y']:g}) "
                    f"for {last['idle'] / TICKS_PER_SECOND:.1f}s. The belt is blocked there or ends without a consumer. "
                    f"Check inspect {last['x']:g} {last['y']:g}")
    elapsed = last["tick"] - last["started"]
    if last["tick"] == last["started"]:
        return "no game time passed, the game seems paused"
    return (f"still on the belt after {elapsed / TICKS_PER_SECOND:.1f}s, now at ({last['x']:g},{last['y']:g}), "
            f"{last['tiles']:g} tiles travelled (speed {last['tiles'] / max(elapsed / TICKS_PER_SECOND, 0.1):.1f} tiles/s). Use a longer wait for long belts")


def _collect(game: Game, x, y, radius, item, seconds, sleep, every) -> list[dict[str, Any]]:
    samples = [game.call("sample", x, y, radius, item)]
    waited = 0.0
    while waited < seconds:
        sleep(every)
        waited += every
        samples.append(game.call("sample", x, y, radius, item))
    return samples


def flow(game: Game, x: float, y: float, seconds: float, item: str, sleep: Callable[[float], None]) -> str:
    samples = _collect(game, x, y, 0.6, item, seconds, sleep, 1.0)
    first, last = samples[0], samples[-1]
    ticks = last["tick"] - first["tick"]
    if ticks <= 0:
        return "no game time passed, the game seems paused"
    mins = ticks / TICKS_PER_SECOND / 60
    parts = [f"measured {ticks / TICKS_PER_SECOND:.1f}s of game time"]
    ma, mb = as_list(first.get("machines")), as_list(last.get("machines"))
    if ma and mb and ma[0].get("p") is not None and mb[0].get("p") is not None:
        made = mb[0]["p"] - ma[0]["p"]
        working = sum(1 for s in samples if as_list(s.get("machines")) and s["machines"][0].get("s") == "working")
        parts.append(f"{mb[0]['n']} finished {made} crafts = {made / mins:.1f}/min, working {100 * working // len(samples)}% of the time"
                     f" (status now: {mb[0].get('s')})")
    elif ma:
        parts.append(f"{ma[0]['n']} status: {ma[0].get('s')}")
    if first.get("belts"):
        fill = sum(s["belt_items"] for s in samples) / len(samples)
        parts.append(f"belt tile holds on average {fill:.1f} of 8 items (fully loaded belts move 15 items/s)")
    if first.get("produced") is not None:
        made = last["produced"] - first["produced"]
        parts.append(f"{item}: {made} produced in total = {made / mins:.1f}/min")
    if len(parts) == 1:
        parts.append("nothing measurable at that position (give a machine or belt tile, or an item name for the whole factory)")
    return ". ".join(parts)


def machine_stats(game: Game, x, y, radius: float, seconds: float, sleep: Callable[[float], None]) -> str:
    samples = _collect(game, x, y, radius, "", seconds, sleep, 2.0)
    ticks = samples[-1]["tick"] - samples[0]["tick"]
    if ticks <= 0:
        return "no game time passed, the game seems paused"
    mins = ticks / TICKS_PER_SECOND / 60
    rows: dict[tuple, dict[str, Any]] = {}
    for sample in samples:
        for m in as_list(sample.get("machines")):
            key = (m["n"], m["x"], m["y"])
            row = rows.setdefault(key, {"n": m["n"], "x": m["x"], "y": m["y"], "ok": 0, "seen": 0, "st": {}, "p0": m.get("p"), "p1": m.get("p")})
            row["seen"] += 1
            row["ok"] += 1 if m.get("s") == "working" else 0
            row["st"][m.get("s")] = row["st"].get(m.get("s"), 0) + 1
            row["p1"] = m.get("p")
    if not rows:
        return "no machines in that area"
    lines = [f"{len(rows)} machines over {ticks / TICKS_PER_SECOND:.0f}s game time:"]
    problems: dict[str, list[str]] = {}
    for row in sorted(rows.values(), key=lambda r: r["ok"] / r["seen"]):
        up = 100 * row["ok"] // row["seen"]
        rate = ""
        if row["p0"] is not None and row["p1"] is not None:
            rate = f", {(row['p1'] - row['p0']) / mins:.1f}/min"
        top = max(row["st"].items(), key=lambda kv: kv[1])[0]
        lines.append(f"- {row['n']} ({row['x']:g},{row['y']:g}) working {up}%{rate}" + ("" if up >= 90 else f", mostly {top}"))
        if up < 90 and top in HINTS:
            problems.setdefault(top, []).append(f"({row['x']:g},{row['y']:g})")
    if problems:
        lines.append("diagnosis:")
        for status, where in sorted(problems.items(), key=lambda kv: -len(kv[1])):
            lines.append(f"- {status} at {len(where)} machines ({', '.join(where[:5])}): {HINTS[status]}")
    else:
        lines.append("diagnosis: all machines work almost all the time")
    return "\n".join(lines[:40])


def selftest_text(d: dict) -> str:
    mark = {"ok": "OK  ", "fail": "FAIL", "warn": "WARN", "skip": "SKIP"}
    lines = [f"selftest in sandbox at ({d['area']['x']},{d['area']['y']}), mod {d.get('version')}"]
    for r in as_list(d.get("results")):
        detail = f": {r['d']}" if r.get("d") else ""
        lines.append(f"{mark.get(r['s'], r['s'])} {r['n']}{detail}")
    s = as_map(d.get("summary"))
    lines.append(f"result: {s.get('ok', 0)} ok, {s.get('warn', 0)} warnings, {s.get('fail', 0)} failed, {s.get('skip', 0)} skipped. "
                 "Everything built was removed again.")
    if s.get("fail", 0):
        lines.append("Send this report to the developer: each FAIL names the API assumption that does not hold.")
    return "\n".join(lines)
