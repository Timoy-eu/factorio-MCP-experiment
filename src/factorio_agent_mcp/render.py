"""Turn mod replies into short plain text for small models."""

from __future__ import annotations

from typing import Any

from .game import GameError, as_list, as_map
from .planner import next_steps

PLATE_SOURCES = {
    "iron-plate": "iron-ore",
    "copper-plate": "copper-ore",
    "stone-brick": "stone",
    "steel-plate": "iron-plate",
}
GATHERABLE = {"wood", "stone", "coal", "iron-ore", "copper-ore"}


def num(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def at(point: dict[str, Any]) -> str:
    return f"({num(point.get('x'))},{num(point.get('y'))})"


def hint_for(err: GameError) -> str:
    data = err.data
    code = err.code
    item = data.get("item")
    if code == "no_item":
        return f"get one with craft {item}, or gather the parts" if item else "craft or gather it first"
    if code == "missing":
        if item in PLATE_SOURCES:
            return (f"smelt {PLATE_SOURCES[item]} in a furnace (build stone-furnace, insert, fuel, wait, collect)")
        if item in GATHERABLE:
            return f"gather {item} {data.get('count', '')}".strip()
        return f"craft {item} first or find it"
    if code == "blocked":
        suggestion = as_map(data.get("suggestion"))
        if suggestion:
            return f"try x={num(suggestion.get('x'))}, y={num(suggestion.get('y'))}"
        return "pick another spot (use look)"
    if code in ("not_found", "nothing_found", "no_ore"):
        return "walk is automatic; use look or find to see what is nearby"
    if code == "locked":
        return "research it first (research tool)"
    if code == "not_by_hand":
        return "this needs a machine (furnace or assembler), not hand crafting"
    if code == "not_gatherable":
        return "gatherable by hand: wood, stone, coal, iron-ore, copper-ore"
    if code in ("rotate_failed", "not_rotatable"):
        return "check the entity with look; some entities cannot rotate"
    if code == "no_site":
        return "move to a bigger ore patch (find iron-ore) or clear obstacles"
    if code == "mod_missing":
        return "install mod/fac_agent into the Factorio mods folder and restart the server"
    if code == "no_connection":
        return "check RCON host, port and password"
    return ""


def error_text(err: GameError) -> str:
    hint = hint_for(err)
    blocked = as_list(err.data.get("blocked_by"))
    extra = f" (blocked by {', '.join(sorted(set(blocked)))})" if blocked else ""
    tail = f" | try: {hint}" if hint else ""
    return f"ERR {err.code}: {err.message}{extra}{tail}"


def inventory_text(inv: dict[str, Any], limit: int = 20) -> str:
    items = sorted(as_map(inv).items(), key=lambda kv: (-int(kv[1]), kv[0]))
    items = [(k, v) for k, v in items if int(v) > 0]
    if not items:
        return "nothing"
    shown = ", ".join(f"{k} {v}" for k, v in items[:limit])
    return shown + (f", +{len(items) - limit} more" if len(items) > limit else "")


def placed_text(placed: dict[str, Any]) -> str:
    parts = []
    for name, entry in sorted(as_map(placed).items()):
        entry = as_map(entry)
        status = as_map(entry.get("status"))
        detail = ", ".join(f"{k} {v}" for k, v in sorted(status.items()))
        parts.append(f"{name} x{entry.get('n', 0)}" + (f" [{detail}]" if detail else ""))
    return "; ".join(parts) if parts else "nothing yet"


def status_text(data: dict[str, Any]) -> str:
    inventory = as_map(data.get("inventory"))
    placed = as_map(data.get("placed"))
    steps = next_steps(inventory, placed, data.get("research"))
    health = f"  hp {num(data['health'])}" if data.get("health") is not None else ""
    lines = [
        f"tick {data.get('tick')} at {at(as_map(data.get('position')))}{health}",
        f"carry: {inventory_text(inventory)}",
        f"built nearby: {placed_text(placed)}",
        f"research: {data.get('research') or 'none'}",
        "next: " + "  ".join(f"{i}) {s}" for i, s in enumerate(steps, 1)),
    ]
    if not placed:
        lines.append("tip: call guide once to learn how to play (method, belts, power, debugging)")
    return "\n".join(lines)


def look_text(data: dict[str, Any]) -> str:
    lines = [f"at {at(as_map(data.get('position')))}, radius {data.get('radius')}"]
    resources = as_map(data.get("resources"))
    if resources:
        parts = [
            f"{name} {r['tiles']} tiles nearest {at(r)} d={num(r['d'])}"
            for name, r in sorted(resources.items(), key=lambda kv: kv[1]["d"])
        ]
        lines.append("ore: " + "; ".join(parts))
    else:
        lines.append("ore: none in range")
    trees = as_map(data.get("trees"))
    nearest_tree = as_map(trees.get("nearest"))
    lines.append(f"trees: {trees.get('count', 0)}" + (f" nearest {at(nearest_tree)} d={num(nearest_tree['d'])}" if nearest_tree else ""))
    rock = as_map(data.get("rock"))
    if rock:
        lines.append(f"rock: {at(rock)} d={num(rock['d'])} (gives stone and coal)")
    water = as_map(data.get("water"))
    if water:
        lines.append(f"water: {at(water)} d={num(water['d'])}")
    entities = as_list(data.get("entities"))
    if entities:
        shown = []
        for e in entities[:15]:
            piece = f"{e['name']} {at(e)}"
            if e.get("dir"):
                piece += f" {e['dir']}"
            if e.get("status"):
                piece += f" [{e['status']}]"
            shown.append(piece)
        lines.append("yours: " + "; ".join(shown) + (f"; +{len(entities) - 15} more" if len(entities) > 15 else ""))
    lines.append(f"enemies: {data.get('enemies', 0)}")
    return "\n".join(lines)


def find_text(data: dict[str, Any]) -> str:
    return f"nearest {data.get('name') or data.get('kind')}: {at(data)} distance {num(data.get('d'))}"


def gather_text(data: dict[str, Any], wanted: int) -> str:
    got, item = data.get("got", 0), data.get("item")
    if data.get("partial"):
        return f"got {got}/{wanted} {item} (have {data.get('have')}); stopped: {data.get('reason')}"
    return f"got {got} {item} (have {data.get('have')})"


def craft_text(data: dict[str, Any]) -> str:
    made = ", ".join(f"{k} {v}" for k, v in sorted(as_map(data.get("crafted")).items()))
    return f"crafted {data.get('item')}, now have {data.get('have')}. made: {made}"


def recipe_text(data: dict[str, Any]) -> str:
    parts = ", ".join(f"{i['amount']} {i['name']}" for i in as_list(data.get("ingredients")))
    hand = "yes" if data.get("by_hand") else f"no, needs {data.get('category')}"
    lock = "" if data.get("enabled") else " (locked, needs research)"
    return f"{data.get('item')} needs: {parts}. by hand: {hand}{lock}"


def build_text(data: dict[str, Any]) -> str:
    text = f"built {data.get('entity')} at {at(data)}"
    if data.get("direction"):
        text += f" facing {data['direction']}"
    if data.get("moved"):
        text += " (spot was blocked, used nearest free spot)"
    if data.get("warning"):
        text += f". WARNING: {data['warning']}"
    return text


def rotate_text(data: dict[str, Any]) -> str:
    if data.get("note"):
        return f"{data.get('entity')} at {at(data)}: {data['note']}. No action needed."
    return f"{data.get('entity')} at {at(data)} now faces {data.get('direction')}"


def miner_text(data: dict[str, Any]) -> str:
    drill, furnace = as_map(data.get("drill")), as_map(data.get("furnace"))
    return (f"miner on {data.get('ore')}: drill at {at(drill)} facing {drill.get('direction')} "
            f"feeds furnace at {at(furnace)}. coal inserted: {data.get('coal_inserted')}")


def fuel_text(data: dict[str, Any]) -> str:
    targets = ", ".join(f"{t['name']} {at(t)} +{t['put']}" for t in as_list(data.get("fueled")))
    return f"fueled with {data.get('item')} (total {data.get('total')}, {data.get('left')} left): {targets}"


def collect_text(data: dict[str, Any]) -> str:
    got = as_map(data.get("collected"))
    if not got:
        return "nothing to collect yet (machines have no output)"
    return "collected " + ", ".join(f"{k} {v}" for k, v in sorted(got.items()))


def insert_text(data: dict[str, Any]) -> str:
    return f"inserted {data.get('inserted')} {data.get('item')} into {data.get('entity')} ({data.get('left')} left)"


def set_recipe_text(data: dict[str, Any]) -> str:
    return f"{data.get('entity')} now makes {data.get('recipe')} (facing {data.get('direction')})"


def research_text(data: dict[str, Any]) -> str:
    if data.get("queued"):
        return f"research queued: {data['queued']}"
    available = ", ".join(as_list(data.get("available"))) or "none"
    return f"current: {data.get('current') or 'none'}. available: {available}"


# ---------------------------------------------------------------- extended tools

def can_place_text(data: dict[str, Any]) -> str:
    if data.get("can_place"):
        return f"yes, {data.get('entity')} fits at {at(data)} facing {data.get('direction')}"
    text = f"no, {data.get('entity')} does not fit at {at(data)}"
    by = as_list(data.get("blocked_by"))
    if by:
        text += " (blocked by " + ", ".join(str(b.get("name", b)) if isinstance(b, dict) else str(b) for b in by) + ")"
    sug = as_map(data.get("suggestion"))
    if sug:
        text += f". nearest free spot: {at(sug)}"
    return text


def site_text(data: dict[str, Any]) -> str:
    text = (f"free {data.get('width')}x{data.get('height')} area centered at {at(data)} "
            f"(from {at(as_map(data.get('left_top')))} to {at(as_map(data.get('right_bottom')))}), {data.get('d')} tiles away")
    if data.get("covered") is not None:
        text += f", {data['covered']} ore tiles under it"
    return text


def pickup_text(data: dict[str, Any]) -> str:
    got = ", ".join(f"{k} {v}" for k, v in sorted(as_map(data.get("got")).items())) or "nothing"
    return f"picked up {data.get('entity')} at {at(data)}; items back in inventory: {got}"


def shift_text(data: dict[str, Any]) -> str:
    return f"moved {data.get('entity')} to {at(data)} facing {data.get('direction')}"


def extract_text(data: dict[str, Any]) -> str:
    return f"took {data.get('extracted')} {data.get('item')} from {data.get('entity')} (you have {data.get('have')})"


def _inv_line(inv: dict[str, Any]) -> str:
    return ", ".join(f"{k} {v}" for k, v in sorted(as_map(inv).items())) or "empty"


def inv_view_text(data: dict[str, Any]) -> str:
    if data.get("owner") == "you":
        return "your inventory: " + _inv_line(data.get("items"))
    parts = [f"{name}: {_inv_line(c)}" for name, c in as_map(data.get("inventories")).items()]
    return f"{data.get('owner')} at {at(data)} -> " + ("; ".join(parts) or "no inventory")


def entity_text(data: dict[str, Any]) -> str:
    text = f"{data.get('name')} ({data.get('type')}) at {at(data)}"
    for key, label in (("direction", "facing"), ("status", "status"), ("recipe", "recipe"), ("amount", "amount"),
                       ("health", "health")):
        if data.get(key) is not None:
            text += f", {label} {data[key]}"
    for name, c in as_map(data.get("inventories")).items():
        text += f"\n  {name}: {_inv_line(c)}"
    for f in as_list(data.get("fluids")):
        text += f"\n  fluid {f.get('name')} {f.get('amount')}"
    if data.get("drops_into"):
        d = data["drops_into"]
        text += f"\n  outputs into {d.get('name')} at {at(d)}"
    if data.get("belt_outputs"):
        text += "\n  belt continues to " + ", ".join(at(p) for p in as_list(data["belt_outputs"]))
    if data.get("electric_network") is not None:
        text += f"\n  power network #{data['electric_network']}"
    return text


def entities_text(data: dict[str, Any]) -> str:
    lines = [f"{data.get('total')} entities found" + (" (list shortened)" if data.get("total", 0) > len(as_list(data.get("entities"))) else "")]
    for e in as_list(data.get("entities")):
        extra = (f" {e['dir']}" if e.get("dir") else "") + (f" [{e['status']}]" if e.get("status") else "")
        lines.append(f"- {e['name']} {at(e)}{extra}")
    groups = as_map(data.get("groups"))
    for g in as_list(groups.get("belts")):
        s = ", ".join(f"{at(p)} {p.get('dir') or ''}".strip() for p in as_list(g.get("starts")))
        e = ", ".join(f"{at(p)} {p.get('dir') or ''}".strip() for p in as_list(g.get("ends")))
        lines.append(f"belt line of {g['n']} pieces: starts {s or '-'}; ends {e or '-'}")
    for g in as_list(groups.get("pipes")):
        lines.append(f"pipe network of {g['n']} pieces from {at(as_map(g.get('from')))} to {at(as_map(g.get('to')))}")
    for g in as_list(groups.get("poles")):
        lines.append(f"power network #{g['id']}: {g['n']} poles from {at(as_map(g.get('from')))} to {at(as_map(g.get('to')))}")
    return "\n".join(lines)


def patch_text(data: dict[str, Any]) -> str:
    return (f"{data.get('resource')} patch: {data.get('tiles')} tiles, {data.get('amount')} total, center {at(as_map(data.get('center')))}, "
            f"from {at(as_map(data.get('left_top')))} to {at(as_map(data.get('right_bottom')))}, {data.get('d')} tiles away")


def move_text(data: dict[str, Any]) -> str:
    return f"you are now at {at(data)} (moved {data.get('moved')} tiles)"


def score_text(data: dict[str, Any]) -> str:
    prod = ", ".join(f"{k} {v}" for k, v in sorted(as_map(data.get("produced")).items(), key=lambda kv: -kv[1])) or "nothing yet"
    text = f"tick {data.get('tick')}, researched {data.get('researched')} techs, produced total {data.get('produced_total')}: {prod}"
    rate = as_map(data.get("per_minute"))
    if rate:
        text += "\nper minute: " + ", ".join(f"{k} {v}" for k, v in sorted(rate.items()))
    return text


def research_info_text(data: dict[str, Any]) -> str:
    if data.get("researched"):
        return f"{data.get('name')} is already researched"
    packs = ", ".join(f"{p['amount']} {p['name']}" for p in as_list(data.get("packs_needed"))) or "none"
    return (f"{data.get('name')}: {data.get('progress')}% done, {data.get('units_left')} of {data.get('units_total')} units left, "
            f"still needs packs: {packs}")


def connect_text(data: dict[str, Any]) -> str:
    if "enough" in data:
        text = f"{data.get('length')} tiles, needs {data.get('needed')} {data.get('item')}, you have {data.get('have')}"
        return text + (" (enough)" if data.get("enough") else f" (missing {data['needed'] - data['have']})")
    text = (f"laid {data.get('placed')} {data.get('entity')} ({data.get('length')} tiles) from {at(as_map(data.get('from')))} "
            f"to {at(as_map(data.get('to')))}")
    if not data.get("connected"):
        text += ". WARNING: result does not look connected, check with get_entities"
    return text
