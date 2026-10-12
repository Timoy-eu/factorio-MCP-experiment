"""MCP server: high level Factorio tools for small local models.

Environment:
  FACTORIO_RCON_HOST (default 127.0.0.1)  FACTORIO_RCON_PORT (default 27015)
  FACTORIO_RCON_PASSWORD                  FACTORIO_MCP_DISABLE_LUA=1 removes the raw run_lua tool
"""

from __future__ import annotations

import functools
import inspect as _inspect
import json
import os
import time
from typing import Any, Callable

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server

from . import asciimap, blueprints, render, svgmap, tracking
from . import guide as guide_module
from .game import Game, GameError
from .rcon import Rcon, RconError

mcp = _Server("factorio-agent", instructions=guide_module.INSTRUCTIONS)

_game: Game | None = None
_rcon: Rcon | None = None

DIRECTION_ALIASES = {
    "up": "north", "n": "north", "right": "east", "e": "east",
    "down": "south", "s": "south", "left": "west", "w": "west",
    "": "auto", "any": "auto",
}


def configure(game: Game, rcon: Rcon | None = None) -> None:
    """Inject the connection (used by main() and by the tests)."""
    global _game, _rcon
    _game, _rcon = game, rcon


def _get_game() -> Game:
    if _game is None:
        raise GameError("no_connection", "server is not configured")
    return _game


def narrated(template: str, skip: Callable[[dict], bool] | None = None):
    """Announce a successful action in the game chat (FACTORIO_MCP_CHAT=0 turns this off)."""
    def deco(fn):
        sig = _inspect.signature(fn)

        @functools.wraps(fn)
        def inner(*args, **kwargs):
            result = fn(*args, **kwargs)
            if os.environ.get("FACTORIO_MCP_CHAT", "1") != "0" and not result.startswith("ERR"):
                try:
                    bound = sig.bind(*args, **kwargs)
                    bound.apply_defaults()
                    if not (skip and skip(bound.arguments)):
                        _get_game().call("say", template.format(**bound.arguments))
                except Exception:
                    pass  # chat is a nice to have, never break the action
            return result
        return inner
    return deco


def direction_name(value: str | None) -> str:
    text = (value or "auto").strip().lower()
    return DIRECTION_ALIASES.get(text, text)


def run(action: Callable[[Game], str]) -> str:
    """Execute a tool body and never raise: small models cope better with one line errors."""
    try:
        return action(_get_game())
    except GameError as err:
        return render.error_text(err)
    except RconError as err:
        return render.error_text(GameError("no_connection", str(err)))


@mcp.tool()
def guide(topic: str = "") -> str:
    """How to play: working method, early game, belts, power, automation, debugging. Read it once at the start. topic = method, start, tools, belts, power, automation, debugging, or empty for everything."""
    return guide_module.text(topic)


@mcp.tool()
def status() -> str:
    """Your position, inventory, nearby buildings and the recommended next steps. Call this first and after each big step."""
    return run(lambda g: render.status_text(g.call("status")))


@mcp.tool()
def look(radius: int = 25) -> str:
    """Scan around you (radius 5 to 60): ore, trees, rocks, water, your buildings with status, enemies."""
    return run(lambda g: render.look_text(g.call("look", radius)))


@mcp.tool()
def find(what: str) -> str:
    """Nearest iron-ore, copper-ore, coal, stone, tree, rock, water, or the name of a building. Returns x, y and distance."""
    return run(lambda g: render.find_text(g.call("find", what.strip().lower())))


@mcp.tool()
@narrated("gathers {count} {item}")
def gather(item: str, count: int = 10) -> str:
    """Mine by hand: wood, stone, coal, iron-ore or copper-ore. You walk there automatically."""
    wanted = max(1, int(count))
    return run(lambda g: render.gather_text(g.call("gather", item.strip().lower(), wanted), wanted))


@mcp.tool()
@narrated("crafts {count} {item}", lambda a: a["preview"])
def craft(item: str, count: int = 1, preview: bool = False) -> str:
    """Hand-craft an item, including needed intermediate parts. preview=true only shows the recipe. Plates cannot be crafted: smelt ore in a furnace."""
    name = item.strip().lower()
    if preview:
        return run(lambda g: render.recipe_text(g.call("recipe", name)))
    return run(lambda g: render.craft_text(g.call("craft", name, max(1, int(count)))))


@mcp.tool()
@narrated("builds {entity} at ({x:g}, {y:g})")
def build(entity: str, x: float, y: float, direction: str = "auto") -> str:
    """Place a building from your inventory. direction: auto (default, the first one that fits), north, east, south, west. Give inserters and belts an explicit direction. If the spot is blocked the nearest free spot is used. The reply states the real position and direction."""
    return run(lambda g: render.build_text(
        g.call("build", entity.strip().lower(), float(x), float(y), direction_name(direction), 2)))


@mcp.tool()
@narrated("rotates the building at ({x:g}, {y:g}) to {direction}")
def rotate(x: float, y: float, direction: str) -> str:
    """Turn the building at x, y to north, east, south or west. The reply confirms the real direction."""
    return run(lambda g: render.rotate_text(g.call("rotate", float(x), float(y), direction_name(direction))))


@mcp.tool()
@narrated("builds a miner on {ore}")
def build_miner(ore: str = "iron-ore") -> str:
    """Place a burner mining drill on ore that drops into a stone furnace, then fuel both with coal. Needs burner-mining-drill and stone-furnace in inventory. Direction is solved for you."""
    return run(lambda g: render.miner_text(g.call("build_miner", ore.strip().lower())))


@mcp.tool()
def fuel(x: float | None = None, y: float | None = None, item: str = "coal", per: int = 5) -> str:
    """Add fuel to the building at x, y, or to every burner machine within 30 tiles if no position is given."""
    return run(lambda g: render.fuel_text(g.call(
        "fuel", None if x is None else float(x), None if y is None else float(y),
        item.strip().lower(), max(1, int(per)))))


@mcp.tool()
def collect(radius: int = 30) -> str:
    """Take finished items (plates, bricks) out of all furnaces and machines within radius."""
    return run(lambda g: render.collect_text(g.call("collect", radius)))


@mcp.tool()
def insert(x: float, y: float, item: str, count: int = 0) -> str:
    """Put items from your inventory into the building at x, y (ore into a furnace, ingredients into an assembler). count 0 means all."""
    return run(lambda g: render.insert_text(g.call(
        "insert", float(x), float(y), item.strip().lower(), int(count) if count > 0 else None)))


@mcp.tool()
@narrated("sets recipe {recipe}")
def set_recipe(x: float, y: float, recipe: str) -> str:
    """Set the recipe of the assembling machine at x, y."""
    return run(lambda g: render.set_recipe_text(g.call("set_recipe", float(x), float(y), recipe.strip().lower())))


@mcp.tool()
@narrated("starts research {name}", lambda a: not a["name"])
def research(name: str = "") -> str:
    """Without a name: list technologies you can research now. With a name: queue it."""
    return run(lambda g: render.research_text(g.call("research", name.strip().lower())))


# ---------------------------------------------------------------- extended tools (FLE parity and more)

def _num(v: float) -> float:
    return float(v)


@mcp.tool()
def can_place(entity: str, x: float, y: float, direction: str = "north") -> str:
    """Check whether an entity fits at x,y without building it. If not, says what blocks it and the nearest free spot."""
    return run(lambda g: render.can_place_text(g.call("can_place", entity.strip().lower(), _num(x), _num(y), direction_name(direction))))


@mcp.tool()
def nearest_buildable(entity: str = "", width: int = 0, height: int = 0, x: float | None = None, y: float | None = None,
                      resource: str = "", radius: int = 30) -> str:
    """Find the nearest free area for an entity (or a width x height block). With resource (e.g. iron-ore) at least half of it must lie on that ore."""
    return run(lambda g: render.site_text(g.call(
        "nearest_buildable", entity.strip().lower() or None, width or None, height or None,
        None if x is None else _num(x), None if y is None else _num(y), resource.strip().lower() or None, radius)))


@mcp.tool()
@narrated("builds {entity} next to ({ref_x:g}, {ref_y:g})")
def build_next_to(entity: str, ref_x: float, ref_y: float, side: str, spacing: int = 0, direction: str = "auto") -> str:
    """Build an entity directly beside one of your buildings (side = north/east/south/west of it, spacing = free tiles between)."""
    return run(lambda g: render.build_text(g.call("build_next_to", entity.strip().lower(), _num(ref_x), _num(ref_y),
                                                  direction_name(side), spacing, direction_name(direction))))


@mcp.tool()
@narrated("picks up the building at ({x:g}, {y:g})")
def pickup(x: float, y: float) -> str:
    """Pick up one of your buildings at x,y. Its contents and the item itself return to your inventory."""
    return run(lambda g: render.pickup_text(g.call("pickup", _num(x), _num(y))))


@mcp.tool()
def move_entity(x: float, y: float, new_x: float, new_y: float) -> str:
    """Move a building to a new position (keeps rotation and recipe where possible, restores it if the target is blocked)."""
    return run(lambda g: render.shift_text(g.call("shift_entity", _num(x), _num(y), _num(new_x), _num(new_y))))


@mcp.tool()
def extract(x: float, y: float, item: str, count: int = 10) -> str:
    """Take items out of a building (furnace output, chest, assembler output) into your inventory."""
    return run(lambda g: render.extract_text(g.call("extract", _num(x), _num(y), item.strip().lower(), count)))


@mcp.tool()
def inventory(x: float | None = None, y: float | None = None) -> str:
    """Without x,y: your inventory. With x,y: all contents of the building there (fuel, input, output, chest)."""
    return run(lambda g: render.inv_view_text(g.call("inventory", None if x is None else _num(x), None if y is None else _num(y))))


@mcp.tool()
def inspect(x: float, y: float) -> str:
    """Details of the entity at x,y: facing, status, recipe, inventories, fluids, where its output goes, belt continuation, power network."""
    return run(lambda g: render.entity_text(g.call("get_entity", _num(x), _num(y))))


@mcp.tool()
def list_entities(names: str = "", x: float | None = None, y: float | None = None, radius: int = 25, limit: int = 60) -> str:
    """List your buildings around x,y (default: you), optionally only some names (comma separated). Also groups belts, pipes and poles into connected lines/networks."""
    wanted = [n.strip().lower() for n in names.split(",") if n.strip()]
    return run(lambda g: render.entities_text(g.call("get_entities", wanted, None if x is None else _num(x),
                                                     None if y is None else _num(y), radius, limit)))


@mcp.tool()
def resource_patch(resource: str, x: float | None = None, y: float | None = None) -> str:
    """Size, total amount, center and bounding box of the nearest patch of an ore (iron-ore, copper-ore, coal, stone, ...)."""
    return run(lambda g: render.patch_text(g.call("resource_patch", resource.strip().lower(),
                                                  None if x is None else _num(x), None if y is None else _num(y))))


@mcp.tool()
def move_to(x: float, y: float) -> str:
    """Go to x,y (teleports to the nearest free spot there)."""
    return run(lambda g: render.move_text(g.call("move_to", _num(x), _num(y))))


@mcp.tool()
@narrated("lays {kind} from ({x1:g}, {y1:g}) to ({x2:g}, {y2:g})", lambda a: a["dry_run"])
def connect(kind: str, x1: float, y1: float, x2: float, y2: float, entity: str = "",
            end_direction: str = "", dry_run: bool = False) -> str:
    """Lay belts, pipes or power poles from (x1,y1) to (x2,y2). kind = belt | pipe | power. Belts and pipes are routed around obstacles; end_direction sets the facing of the last belt. dry_run=true only counts the pieces needed."""
    return run(lambda g: render.connect_text(g.call("connect", kind.strip().lower(), _num(x1), _num(y1), _num(x2), _num(y2),
                                                    entity.strip().lower() or None, direction_name(end_direction) if end_direction else None, dry_run)))


@mcp.tool()
def research_info(name: str = "") -> str:
    """Progress and remaining science packs of a technology (default: the current one)."""
    return run(lambda g: render.research_info_text(g.call("research_info", name.strip().lower())))


@mcp.tool()
def score() -> str:
    """Production statistics: what has been produced so far, items per minute, number of researched technologies."""
    return run(lambda g: render.score_text(g.call("score")))


@mcp.tool()
@narrated("launches the rocket!")
def launch_rocket(x: float | None = None, y: float | None = None) -> str:
    """Launch the rocket of the (nearest) rocket silo, if it is ready."""
    return run(lambda g: _launch(g.call("launch_rocket", None if x is None else _num(x), None if y is None else _num(y))))


def _launch(data: dict) -> str:
    return f"rocket launched from silo at {render.at(data)}"


@mcp.tool()
def say(message: str) -> str:
    """Write a message into the game chat as [Bot] (for the human who plays with you). Use it to report progress, ask for help or explain what you plan."""
    return run(lambda g: f"said: {g.call('say', message)['said']}")


@mcp.tool()
def set_game_speed(speed: float = 1.0) -> str:
    """Change the game speed (1 = normal, 0.1 to 10). Useful to wait for crafting or smelting."""
    return run(lambda g: f"game speed is now {g.call('set_speed', float(speed))['speed']}")


@mcp.tool()
def map(x1: float | None = None, y1: float | None = None, x2: float | None = None, y2: float | None = None,
        layers: str = "all") -> str:
    """ASCII map of any area between two corners (max 100x60 tiles; without coordinates: around you). One character per tile: belts as arrows (^ > v <), machines as letters, i/c/k/s ore, t tree, ~ water, @ you. layers = all or a comma list of machines,belts,pipes,power,ore,trees,water,enemies."""
    def action(g: Game) -> str:
        if None not in (x1, y1, x2, y2):
            problem = asciimap.check_size(x1, y1, x2, y2)  # type: ignore[arg-type]
            if problem:
                return f"ERR too_large: {problem}"
            snap = g.call("snapshot", _num(x1), _num(y1), _num(x2), _num(y2), None)  # type: ignore[arg-type]
        else:
            snap = g.call("snapshot", None, None, None, None, 25)
        return asciimap.render(snap, layers)
    return run(action)


# ---------------------------------------------------------------- picture for the human operator

_viewer = None


def _snapshot_for(q: dict) -> dict:
    g = _get_game()
    keys = ("x1", "y1", "x2", "y2")
    if all(k in q for k in keys):
        return g.call("snapshot", *(float(q[k]) for k in keys), None)
    return g.call("snapshot", None, None, None, None, int(q.get("radius", 30)))


def _ensure_viewer() -> str | None:
    global _viewer
    port = os.environ.get("FACTORIO_MCP_VIEWER_PORT", "8765")
    if port == "0":
        return None
    if _viewer is None:
        from .viewer import Viewer
        try:
            _viewer = Viewer(_snapshot_for, int(port))
        except OSError:
            return None
    return _viewer.url


@mcp.tool()
def render_map(x1: float | None = None, y1: float | None = None, x2: float | None = None, y2: float | None = None,
               scale: int = 16) -> str:
    """Draw a realistic picture of the world as an SVG file for the HUMAN operator (not readable by you). Returns the file path and the link of the live viewer. Without coordinates: around you."""
    def action(g: Game) -> str:
        from pathlib import Path
        if None not in (x1, y1, x2, y2):
            snap = g.call("snapshot", _num(x1), _num(y1), _num(x2), _num(y2), None)  # type: ignore[arg-type]
        else:
            snap = g.call("snapshot", None, None, None, None, 30)
        folder = Path(os.environ.get("FACTORIO_MCP_RENDER_DIR", "renders"))
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"map_{snap['tick']}.svg"
        path.write_text(svgmap.render(snap, scale=scale), encoding="utf-8")
        latest = folder / "latest.svg"
        latest.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        url = _ensure_viewer()
        text = f"picture saved to {path.resolve()} (also {latest.resolve()})."
        if url:
            text += f" Live viewer for the human: {url}"
        return text + " Tell the human to open it; you cannot see it yourself, use map for yourself."
    return run(action)


# ---------------------------------------------------------------- blueprints, notes, overview, checkpoints

def _data_dir():
    from pathlib import Path
    return Path(os.environ.get("FACTORIO_MCP_DATA_DIR", "factorio-data"))


def _store() -> blueprints.Store:
    return blueprints.Store(_data_dir() / "blueprints")


def _notes() -> blueprints.Notes:
    return blueprints.Notes(_data_dir() / "notes.json")


def _bp_preview(bp: dict, quarter_turns: int = 0) -> str:
    ents = blueprints.transformed(bp, quarter_turns)
    sx, sy = blueprints.anchor_shift(bp, quarter_turns)
    w, h = (bp["width"], bp["height"]) if quarter_turns % 2 == 0 else (bp["height"], bp["width"])
    shown = []
    for e in ents:
        shown.append({"n": e["n"], "t": e.get("t", ""), "x": e["dx"] + sx, "y": e["dy"] + sy, "w": e.get("w", 1),
                      "h": e.get("h", 1), "d": e.get("d"), "f": "p"})
    snap = {"area": {"x1": 0, "y1": 0, "x2": w, "y2": h}, "entities": shown}
    return asciimap.render(snap)


@mcp.tool()
def blueprint_save(name: str, x1: float, y1: float, x2: float, y2: float, description: str = "") -> str:
    """Save the buildings of your force inside the area (two corners) as a reusable blueprint. Build and test a layout first, then save it; write in the description what it does and what it needs. Overwrites a blueprint with the same name."""
    def action(g: Game) -> str:
        snap = g.call("snapshot", _num(x1), _num(y1), _num(x2), _num(y2), None)
        data = blueprints.from_snapshot(snap, x1, y1, x2, y2)
        if not data["entities"]:
            return "ERR empty: no buildings of yours in that area | try: check the corners with map"
        store = _store()
        try:
            old = store.load(name)
        except KeyError:
            old = {}
        bp = {"name": blueprints.safe_name(name), "description": description or old.get("description", ""),
              "status": "draft", "notes": old.get("notes", []), **data}
        bp["items"] = blueprints.items_needed(bp["entities"])
        path = store.save(bp)
        need = ", ".join(f"{v} {k}" for k, v in sorted(bp["items"].items()))
        return f"saved blueprint '{bp['name']}' ({bp['width']}x{bp['height']}, {len(bp['entities'])} entities, needs {need}) to {path}"
    return run(action)


@mcp.tool()
def blueprint_list() -> str:
    """List saved blueprints with description and status (draft = untested, tested = worked in practice)."""
    store = _store()
    names = store.names()
    if not names:
        return "no blueprints yet. Build something that works, then use blueprint_save."
    lines = []
    for n in names:
        bp = store.load(n)
        lines.append(f"- {n} [{bp.get('status', 'draft')}] {bp['width']}x{bp['height']}: {bp.get('description') or '(no description)'}")
    return "\n".join(lines)


@mcp.tool()
def blueprint_show(name: str, rotation: int = 0) -> str:
    """Show a blueprint as ASCII picture with required items, description and notes. rotation = 0, 90, 180 or 270 (clockwise)."""
    try:
        bp = _store().load(name)
    except KeyError:
        return f"ERR unknown_blueprint: '{name}' | try: blueprint_list"
    turns = (rotation // 90) % 4
    need = ", ".join(f"{v} {k}" for k, v in sorted(bp["items"].items()))
    text = f"blueprint {bp['name']} [{bp.get('status')}] {bp.get('description', '')}\nneeds: {need}\n"
    text += _bp_preview(bp, turns)
    for n in bp.get("notes", []):
        text += f"\nnote: {n}"
    return text


@mcp.tool()
@narrated("places blueprint {name} at ({x:g}, {y:g})", lambda a: a["dry_run"])
def blueprint_place(name: str, x: float, y: float, rotation: int = 0, dry_run: bool = False) -> str:
    """Build a saved blueprint with its top left corner at x,y. rotation = 0, 90, 180 or 270 clockwise. dry_run=true only checks items and free space. Reports exactly which parts failed so you can fix them."""
    try:
        bp = _store().load(name)
    except KeyError:
        return f"ERR unknown_blueprint: '{name}' | try: blueprint_list"
    turns = (rotation // 90) % 4
    ents = blueprints.transformed(bp, turns)
    sx, sy = blueprints.anchor_shift(bp, turns)
    ents.sort(key=lambda e: (blueprints.layer_of(e), e["dy"], e["dx"]))

    def action(g: Game) -> str:
        have = {}
        inv = g.call("inventory")
        have = {k: v for k, v in render.as_map(inv.get("items")).items()}
        need = blueprints.items_needed(ents)
        short = {k: v - have.get(k, 0) for k, v in need.items() if have.get(k, 0) < v}
        if dry_run:
            blocked = []
            for e in ents:
                ax, ay = x + e["dx"] + sx, y + e["dy"] + sy
                r = g.call("can_place", e["n"], ax, ay, e.get("d") or "north")
                if not r.get("can_place"):
                    blocked.append(f"{e['n']} at ({ax:g},{ay:g})")
            text = "enough items" if not short else "missing: " + ", ".join(f"{v} {k}" for k, v in short.items())
            text += "; all spots free" if not blocked else f"; {len(blocked)} blocked: " + ", ".join(blocked[:10])
            return f"dry run of {bp['name']}: {text}"
        if short:
            return "ERR missing: need " + ", ".join(f"{v} more {k}" for k, v in short.items()) + " | try: craft them first or use dry_run to check"
        placed, failed, warnings = 0, [], []
        for e in ents:
            ax, ay = x + e["dx"] + sx, y + e["dy"] + sy
            try:
                r = g.call("build", e["n"], ax, ay, e.get("d") or "north")
                if r.get("moved"):
                    warnings.append(f"{e['n']} wanted ({ax:g},{ay:g}) got ({r['x']:g},{r['y']:g})")
                if r.get("warning"):
                    warnings.append(f"{e['n']} at ({ax:g},{ay:g}): {r['warning']}")
                placed += 1
                if e.get("r"):
                    try:
                        g.call("set_recipe", r["x"], r["y"], e["r"])
                    except GameError as err:
                        warnings.append(f"recipe {e['r']} at ({ax:g},{ay:g}): {err.message}")
            except GameError as err:
                failed.append(f"{e['n']} at ({ax:g},{ay:g}): {err.code}")
        text = f"placed {placed}/{len(ents)} of {bp['name']}"
        if failed:
            text += f". FAILED: {'; '.join(failed[:12])}"
        if warnings:
            text += f". CHECK: {'; '.join(warnings[:8])}"
        if failed or warnings:
            text += ". Look at the result with map, fix the parts and add what you learned with blueprint_note."
        return text
    return run(action)


@mcp.tool()
def blueprint_note(name: str, note: str = "", status: str = "", description: str = "") -> str:
    """Improve a blueprint together with the human: add a note (what worked, what to watch out for), set status to draft or tested, or change the description."""
    store = _store()
    try:
        bp = store.load(name)
    except KeyError:
        return f"ERR unknown_blueprint: '{name}' | try: blueprint_list"
    if note:
        bp.setdefault("notes", []).append(note)
    if status in ("draft", "tested"):
        bp["status"] = status
    if description:
        bp["description"] = description
    store.save(bp)
    return f"updated '{bp['name']}' [{bp['status']}], {len(bp.get('notes', []))} notes"


@mcp.tool()
def blueprint_delete(name: str) -> str:
    """Delete a saved blueprint."""
    return f"deleted '{name}'" if _store().delete(name) else f"ERR unknown_blueprint: '{name}'"


@mcp.tool()
def notes(action: str = "list", text: str = "", tag: str = "", note_id: int = 0) -> str:
    """Persistent notebook that survives context resets. action = add (text, optional tag like goal/location/lesson), list (optional tag), remove (note_id). Write down goals, coordinates of mines and factories, and lessons learned."""
    book = _notes()
    action = action.strip().lower()
    if action == "add":
        if not text.strip():
            return "ERR no_text: give the text to store"
        return f"note #{book.add(text.strip(), tag.strip().lower())} saved"
    if action == "remove":
        return "removed" if book.remove(note_id) else "ERR unknown_note"
    items = book.list(tag.strip().lower())
    if not items:
        return "no notes yet"
    return "\n".join(f"#{i['id']} [{i['tag'] or '-'}] {i['text']}" for i in items)


@mcp.tool()
def overview(x: float | None = None, y: float | None = None, radius: int = 60) -> str:
    """Factory overview: how many buildings of each kind, and everything that is not running (no fuel, no power, no ingredients, output full) with coordinates."""
    def action(g: Game) -> str:
        d = g.call("diagnose", None if x is None else _num(x), None if y is None else _num(y), radius)
        counts = ", ".join(f"{v} {k}" for k, v in sorted(render.as_map(d.get("counts")).items(), key=lambda kv: -kv[1])) or "nothing built"
        lines = [f"{d.get('total')} buildings: {counts}"]
        problems = render.as_map(d.get("problems"))
        if not problems:
            lines.append("no problems found")
        for status, info in problems.items():
            where = ", ".join(f"{p['name']} ({p['x']:g},{p['y']:g})" for p in render.as_list(info.get("at")))
            lines.append(f"{status}: {info['n']}x, e.g. {where}")
        return "\n".join(lines)
    return run(action)


@mcp.tool()
@narrated("saved a checkpoint")
def checkpoint(name: str = "") -> str:
    """Write a save file of the current game state (snapshot) that the human can load later. Do this before risky experiments."""
    return run(lambda g: f"saved game as '{g.call('save_game', name.strip())['saved']}'")


# ---------------------------------------------------------------- tracking items and machines

_sleep = time.sleep


@mcp.tool()
def belt_contents(x1: float | None = None, y1: float | None = None, x2: float | None = None, y2: float | None = None) -> str:
    """What lies on the belts in an area (two corners, default 15 tiles around you): items per kind, how full and how many belts are empty. Use it to see whether a belt is running empty or backed up."""
    return run(lambda g: tracking.belt_text(g.call("belt_contents", *(None if v is None else _num(v) for v in (x1, y1, x2, y2)))))


@mcp.tool()
def trace_item(x: float, y: float, item: str = "wood", wait_seconds: int = 15) -> str:
    """Put one item (you must carry it, a cheap one like wood is best) on the belt at x,y and follow it. Tells you how far it got and whether it is stuck, left the belt, or is still travelling. Proves that a belt is connected and runs in the right direction."""
    seconds = min(max(wait_seconds, 2), 90)
    return run(lambda g: tracking.trace(g, _num(x), _num(y), item.strip().lower(), seconds, _sleep))


@mcp.tool()
def measure_flow(x: float, y: float, seconds: int = 10, item: str = "") -> str:
    """Measure over some seconds of game time what one machine or belt tile does: crafts per minute and how often it works (machine), average belt load (belt). With item: production per minute of that item in the whole factory."""
    secs = min(max(seconds, 3), 120)
    return run(lambda g: tracking.flow(g, _num(x), _num(y), secs, item.strip().lower(), _sleep))


@mcp.tool()
def machine_stats(x: float | None = None, y: float | None = None, radius: int = 20, seconds: int = 10) -> str:
    """Observe all machines around x,y (default you) for some seconds: share of time working, crafts per minute, and a diagnosis of what holds the production back (no fuel, no power, missing input, blocked output)."""
    secs = min(max(seconds, 4), 120)
    return run(lambda g: tracking.machine_stats(g, None if x is None else _num(x), None if y is None else _num(y), radius, secs, _sleep))


# ---------------------------------------------------------------- chat and batch

@mcp.tool()
def read_chat(keep: bool = False) -> str:
    """Read new chat messages that human players typed in the game since you last looked. The human can give you instructions this way. Check it now and then."""
    def action(g: Game) -> str:
        msgs = as_list_(g.call("read_chat", keep).get("messages"))
        if not msgs:
            return "no new chat messages"
        return "\n".join(f"{m['player']}: {m['text']}" for m in msgs)
    return run(action)


as_list_ = render.as_list
BATCH_DENY = {"batch", "run_lua", "guide", "trace_item", "measure_flow", "machine_stats"}
BATCH_MAX = 25


@mcp.tool()
def batch(actions: list[dict[str, Any]], stop_on_error: bool = True) -> str:
    """Run several tools in one call, in order. actions = list of {"tool": "<name>", "args": {...}}, e.g. [{"tool":"build","args":{"entity":"stone-furnace","x":10,"y":5}},{"tool":"fuel","args":{"x":10,"y":5}}]. Stops at the first error unless stop_on_error is false. Max 25 actions; slow measuring tools, run_lua and batch itself are not allowed inside."""
    if not actions:
        return "ERR no_actions: give a list of {tool, args}"
    if len(actions) > BATCH_MAX:
        return f"ERR too_many: at most {BATCH_MAX} actions per batch"
    try:
        known = set(mcp._tool_manager._tools)
    except AttributeError:
        known = {n for n, f in globals().items() if callable(f) and not n.startswith("_")}
    lines, failed = [], 0
    for i, act in enumerate(actions, 1):
        name = str(act.get("tool", "")).strip()
        args = act.get("args") or {}
        if name in BATCH_DENY or name not in known:
            lines.append(f"{i}. {name or '?'}: ERR not_allowed: unknown tool or not usable in a batch")
            failed += 1
        else:
            try:
                result = globals()[name](**args)
            except TypeError as err:
                result = f"ERR bad_args: {err}"
            lines.append(f"{i}. {name}: {result}")
            failed += 1 if result.startswith("ERR") else 0
        if failed and stop_on_error:
            lines.append(f"stopped after action {i} because of the error; {len(actions) - i} not run")
            break
    return "\n".join(lines)


@mcp.tool()
def selftest(x: float | None = None, y: float | None = None) -> str:
    """Developer check, run once after installing: tests the mod's assumptions about the game (placing, rotating, belts, poles, crafting, mining, statistics, chat, saving) in a free sandbox area and removes everything again. Not part of normal play."""
    return run(lambda g: tracking.selftest_text(g.call("selftest", None if x is None else _num(x), None if y is None else _num(y))))


if os.environ.get("FACTORIO_MCP_DISABLE_LUA") != "1":

    @mcp.tool()
    def run_lua(code: str) -> str:
        """LAST RESORT: runs raw Lua code in the game. Use ONLY when it is absolutely necessary, i.e. when no other tool can do the job and you have already tried them. Prefer build, connect, inspect, map and the other tools: they verify their work, this does not. Mistakes can break the save, so keep the code short, never delete things you did not build, and use rcon.print(...) to return a value."""
        def action(_: Game) -> str:
            if _rcon is None:
                raise GameError("no_connection", "raw access is not available")
            return _rcon.command("/silent-command " + code) or "(no output)"
        return run(action)


def main() -> None:
    rcon = Rcon(
        host=os.environ.get("FACTORIO_RCON_HOST", "127.0.0.1"),
        port=int(os.environ.get("FACTORIO_RCON_PORT", "27015")),
        password=os.environ.get("FACTORIO_RCON_PASSWORD", ""),
    )
    configure(Game(rcon), rcon)
    mcp.run()


if __name__ == "__main__":
    main()
