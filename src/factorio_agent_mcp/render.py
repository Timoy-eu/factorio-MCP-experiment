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
    """A next step, written as a call the model can copy (tool key=value)."""
    data = err.data
    code = err.code
    item = data.get("item")
    count = data.get("count")
    if code == "no_item":
        if item in PLATE_SOURCES:
            return f"you need {item}: smelt {PLATE_SOURCES[item]} (build_miner ore={PLATE_SOURCES[item]}, or a furnace by hand)"
        if item in GATHERABLE:
            return f"gather item={item} count=10"
        return f"craft item={item} count=1" if item else "craft or gather it first"
    if code == "missing":
        n = f" count={count}" if count else ""
        if item in PLATE_SOURCES:
            return (f"smelt {PLATE_SOURCES[item]}: build_miner ore={PLATE_SOURCES[item]}, or build a stone-furnace, "
                    f"insert {PLATE_SOURCES[item]}, fuel, wait, collect")
        if item in GATHERABLE:
            return f"gather item={item}{n}"
        if item == "rail":
            return f"craft item=rail{n} (1 stone + 1 steel-plate + 1 iron-stick make 2 rail; steel needs a furnace)"
        return f"craft item={item}{n}" if item else "craft or gather the missing parts"
    if code == "blocked":
        suggestion = as_map(data.get("suggestion"))
        entity = data.get("entity")
        if suggestion and entity:
            return f"build entity={entity} x={num(suggestion.get('x'))} y={num(suggestion.get('y'))}"
        if suggestion:
            return f"use x={num(suggestion.get('x'))} y={num(suggestion.get('y'))}"
        return "nearest_buildable entity=... to find a free spot"
    if code in ("not_found", "nothing_found", "no_ore"):
        what = data.get("resource") or data.get("ore") or item
        return f"find what={what}, or look radius=60" if what else "look radius=60 to see what is nearby"
    if code == "locked":
        return "research name=<technology> first (research without a name lists options)"
    if code == "not_by_hand":
        return "this needs a machine: smelt plates in a furnace, other recipes in an assembler"
    if code == "not_gatherable":
        return "gather works for wood, stone, coal, iron-ore, copper-ore"
    if code in ("rotate_failed", "not_rotatable"):
        return "inspect x y to see the entity; some entities cannot rotate"
    if code == "no_site":
        return "resource_patch resource=... then nearest_buildable near its center"
    if code == "no_entity":
        return "list_entities or map to find the exact coordinates"
    if code == "bad_direction":
        return "direction must be north, east, south, west (or auto for build)"
    if code == "use_build_underground":
        return "build_underground x1 y1 x2 y2 places entrance and exit together (same row or column, at most 5 tiles apart)"
    if code == "rotate_underground":
        return "do not rotate underground belts: pick both up with pickup and place a new pair with build_underground"
    if code == "not_in_line":
        return "entrance and exit must share x (vertical) or y (horizontal); items flow from (x1,y1) to (x2,y2)"
    if code == "too_far":
        return f"use a distance of at most {data.get('max')} (count from entrance to exit), or use fast-underground-belt"
    if code == "not_paired":
        return "check the tiles in between with map and look for another underground belt; build_underground again with other coordinates"
    if code == "disconnected":
        return "inspect the piece, or lay the line in shorter parts (connect kind=rail with a waypoint)"
    if code == "no_path":
        return "pick a goal on land, or lay the line in parts via a waypoint; map layers=water,rails shows the area"
    if code == "unknown_entity":
        return "use the full name, e.g. stone-furnace, burner-mining-drill, transport-belt, small-electric-pole"
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


def footer_text(data: dict[str, Any], goal_line: str = "") -> str:
    """Compact state line appended to action replies."""
    inventory = as_map(data.get("inventory"))
    placed = as_map(data.get("placed"))
    nxt = goal_line or ("next: " + (next_steps(inventory, placed, data.get("research"), limit=1) or ["status"])[0])
    return f"[state] at {at(as_map(data.get('position')))} | carry: {inventory_text(inventory, limit=8)} | {nxt}"


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


DIR16_NAMES = ["north", "north-northeast", "northeast", "east-northeast", "east", "east-southeast", "southeast",
               "south-southeast", "south", "south-southwest", "southwest", "west-southwest", "west", "west-northwest",
               "northwest", "north-northwest"]
RAIL_SHORT = {"straight-rail": "straight", "half-diagonal-rail": "half-diagonal", "curved-rail-a": "curve-a", "curved-rail-b": "curve-b"}


def dir16_name(value: Any) -> str:
    try:
        return DIR16_NAMES[int(value) % 16]
    except (TypeError, ValueError):
        return str(value)


def rail_end_text(point: dict[str, Any]) -> str:
    text = at(point)
    if point.get("direction") is not None:
        text += f" facing {dir16_name(point['direction'])} (direction={int(point['direction'])})"
    return text


def rail_connect_text(data: dict[str, Any]) -> str:
    kinds = ", ".join(f"{n} {RAIL_SHORT.get(k, k)}" for k, n in sorted(as_map(data.get("by_type")).items()))
    trees = data.get("trees_to_clear") or data.get("trees_cleared")
    if "enough" in data:
        text = f"rail line: {data.get('pieces')} pieces ({kinds}), needs {data.get('needed')} rail, you have {data.get('have')}"
        text += " (enough)" if data.get("enough") else f" (missing {data['needed'] - data['have']}: craft item=rail count={data['needed'] - data['have']})"
        if data.get("to"):
            text += f"; ends at {rail_end_text(as_map(data['to']))}"
        if trees:
            text += f"; {trees} tree/rock to remove on the way (keep_trees=true avoids that)"
        if data.get("continues_existing"):
            text += "; continues the open rail end you named"
        return text
    text = f"laid {data.get('placed')} rail pieces ({kinds}), used {data.get('rails_used')} rail"
    if data.get("reused"):
        text += f", joined {data['reused']} existing pieces"
    text += f"; end of the line at {rail_end_text(as_map(data.get('to')))}; connection verified by the game"
    if data.get("continues_existing"):
        text += "; continued an existing rail end"
    if data.get("trees_cleared"):
        text += f"; removed {data['trees_cleared']} trees/rocks (wood and stone are in your inventory)"
    return text


def rail_end_list_text(data: dict[str, Any]) -> str:
    ends = as_list(data.get("ends"))
    if not ends:
        return "no open rail end here (a rail that is connected on both sides has none). connect kind=rail x1 y1 x2 y2 starts a new line"
    lines = [f"{len(ends)} open rail end(s), nearest first (shown {len(ends)} of {data.get('count')}):"]
    for e in ends:
        lines.append(f"- {e.get('piece')} at ({num(e.get('x'))},{num(e.get('y'))}): open end at ({num(e.get('end_x'))},{num(e.get('end_y'))}) "
                     f"facing {dir16_name(e.get('end_direction'))} (direction={int(e.get('end_direction', 0))})")
    lines.append("continue with: connect kind=rail x1=<end x> y1=<end y> x2=<goal x> y2=<goal y>")
    return "\n".join(lines)


def underground_text(data: dict[str, Any]) -> str:
    a, b = as_map(data.get("entrance")), as_map(data.get("exit"))
    return (f"placed {data.get('entity')} pair: entrance {at(a)} -> exit {at(b)}, facing {data.get('direction')}, "
            f"{data.get('distance')} tiles apart, paired (checked by the game)")


def connect_text(data: dict[str, Any]) -> str:
    if "by_type" in data:
        return rail_connect_text(data)
    if "enough" in data:
        text = f"{data.get('length')} tiles, needs {data.get('needed')} {data.get('item')}, you have {data.get('have')}"
        return text + (" (enough)" if data.get("enough") else f" (missing {data['needed'] - data['have']})")
    text = (f"laid {data.get('placed')} {data.get('entity')} ({data.get('length')} tiles) from {at(as_map(data.get('from')))} "
            f"to {at(as_map(data.get('to')))}")
    if not data.get("connected"):
        text += ". WARNING: result does not look connected, check with get_entities"
    return text
