"""MCP server: high level Factorio tools for small local models.

Environment:
  FACTORIO_RCON_HOST (default 127.0.0.1)  FACTORIO_RCON_PORT (default 27015)
  FACTORIO_RCON_PASSWORD                  FACTORIO_MCP_DISABLE_LUA=1 removes the raw run_lua tool
  FACTORIO_MCP_PROFILE=core|full (default full)   FACTORIO_MCP_CHAT=0 no chat announcements
  FACTORIO_MCP_DATA_DIR (notes, goal, blueprints)  FACTORIO_MCP_RENDER_DIR, FACTORIO_MCP_VIEWER_PORT
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
    _history.clear()


def _get_game() -> Game:
    if _game is None:
        raise GameError("no_connection", "server is not configured")
    return _game


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


# ---------------------------------------------------------------- tool registry, profiles, guard rails

# Tools in the "core" profile: enough to play the early and mid game, few enough for small models.
CORE_TOOLS = {
    "guide", "status", "look", "find", "gather", "craft", "build", "build_miner", "build_miners", "rotate", "fuel",
    "collect", "insert", "extract", "set_recipe", "connect", "research", "map", "inspect", "can_place",
    "machine_stats", "overview", "goal", "notes", "say", "read_chat", "batch",
}
# Action tools get a one line state footer so the model rarely needs an extra status call.
FOOTER_TOOLS = {
    "gather", "craft", "build", "build_miner", "build_miners", "rotate", "fuel", "collect", "insert", "extract",
    "set_recipe", "connect", "build_next_to", "pickup", "move_entity", "move_to", "blueprint",
}
REGISTRY: dict[str, Callable[..., str]] = {}
_registered: list[str] = []
_history: list[tuple[str, str, str]] = []  # (tool, args key, result code) of recent calls
_in_batch = False

NAME_ALIASES = {
    "furnace": "stone-furnace", "drill": "burner-mining-drill", "miner": "burner-mining-drill",
    "burner-drill": "burner-mining-drill", "electric-drill": "electric-mining-drill",
    "belt": "transport-belt", "conveyor": "transport-belt", "pole": "small-electric-pole",
    "chest": "wooden-chest", "assembler": "assembling-machine-1", "gear": "iron-gear-wheel",
    "gears": "iron-gear-wheel", "plate": "iron-plate", "iron-plates": "iron-plate", "copper-plates": "copper-plate",
    "pump": "offshore-pump", "engine": "steam-engine", "red-science": "automation-science-pack",
    "green-science": "logistic-science-pack", "circuit": "electronic-circuit", "circuits": "electronic-circuit",
    "trees": "wood", "tree": "wood", "logs": "wood", "rock": "stone", "iron": "iron-ore", "copper": "copper-ore",
}


def _slug(value: str | None) -> str:
    text = (value or "").strip().lower().replace("_", "-").replace(" ", "-")
    while "--" in text:
        text = text.replace("--", "-")
    return text


def _name(value: str | None) -> str:
    """Normalise item and entity names: 'Stone Furnace', 'stone_furnace', 'furnace' -> 'stone-furnace'."""
    text = _slug(value)
    return NAME_ALIASES.get(text, text)


def _args_key(arguments: dict[str, Any]) -> str:
    return json.dumps(arguments, sort_keys=True, default=str)


def _guard(tool_name: str, arguments: dict[str, Any], result: str) -> str:
    """Stop small models from looping: repeated identical failures get a clear STOP message."""
    code = result.split(":", 1)[0][4:] if result.startswith("ERR ") else "ok"
    key = _args_key(arguments)
    _history.append((tool_name, key, code))
    del _history[:-12]
    if code == "ok":
        return result
    same_call = 0
    for t, k, c in reversed(_history):
        if (t, k, c) != (tool_name, key, code):
            break
        same_call += 1
    same_tool = 0
    for t, _, c in reversed(_history):
        if t != tool_name or c != code:
            break
        same_tool += 1
    if same_call >= 3:
        return (f"STOP: this exact {tool_name} call failed {same_call} times with {code}. Repeating it will not help. "
                f"Do something different: follow the 'try:' hint, check with inspect/map, or ask the human with say.\n" + result)
    if same_tool >= 4:
        return (f"STOP: {tool_name} failed {same_tool} times in a row with {code}. Step back: read guide topic=debugging, "
                f"call status, or choose another approach.\n" + result)
    return result


def _footer() -> str:
    """One line with position, carried items, goal and next step."""
    try:
        data = _get_game().call("status")
    except Exception:
        return ""
    return "\n" + render.footer_text(data, _goal_line())


def tool(narrate: str | None = None, skip: Callable[[dict], bool] | None = None):
    """Register a tool function with chat narration, loop guard and state footer."""
    def deco(fn):
        sig = _inspect.signature(fn)

        @functools.wraps(fn)
        def inner(*args, **kwargs):
            try:
                bound = sig.bind(*args, **kwargs)
                bound.apply_defaults()
                arguments = dict(bound.arguments)
            except TypeError:
                arguments = dict(kwargs)
            result = fn(*args, **kwargs)
            ok = not result.startswith("ERR")
            if narrate and ok and os.environ.get("FACTORIO_MCP_CHAT", "1") != "0":
                try:
                    if not (skip and skip(arguments)):
                        _get_game().call("say", narrate.format(**arguments))
                except Exception:
                    pass  # chat is a nice to have, never break the action
            result = _guard(fn.__name__, arguments, result)
            if fn.__name__ in FOOTER_TOOLS and not _in_batch and not result.startswith("ERR no_connection"):
                result += _footer()
            return result

        REGISTRY[fn.__name__] = inner
        return inner
    return deco


def active_profile() -> str:
    value = os.environ.get("FACTORIO_MCP_PROFILE", "full").strip().lower()
    return value if value in ("core", "full") else "full"


def apply_profile(profile: str | None = None) -> list[str]:
    """(Re)register the tools of a profile with the MCP server. Returns the registered names."""
    profile = profile or active_profile()
    for name in list(_registered):
        try:
            mcp.remove_tool(name)
        except Exception:
            pass
    _registered.clear()
    for name, fn in REGISTRY.items():
        if profile == "core" and name not in CORE_TOOLS:
            continue
        mcp.add_tool(fn)
        _registered.append(name)
    return list(_registered)


@tool()
def guide(topic: str = "") -> str:
    """How to play. topic: method, start, tools, belts, power, automation, debugging, or empty for all. Read once at the start."""
    return guide_module.text(topic, set(_registered) or None)


@tool()
def status() -> str:
    """Your position, inventory, nearby buildings and the recommended next steps. Call this first and after each big step."""
    return run(lambda g: render.status_text(g.call("status")) + (("\n" + _goal_line()) if _goal_line() else ""))


@tool()
def look(radius: int = 25) -> str:
    """Scan around you (radius 5 to 60): ore, trees, rocks, water, your buildings with status, enemies."""
    return run(lambda g: render.look_text(g.call("look", radius)))


@tool()
def find(what: str) -> str:
    """Nearest iron-ore, copper-ore, coal, stone, tree, rock, water, or the name of a building. Returns x, y and distance."""
    return run(lambda g: render.find_text(g.call("find", _slug(what))))


@tool("gathers {count} {item}")
def gather(item: str, count: int = 10) -> str:
    """Mine by hand: wood, stone, coal, iron-ore or copper-ore. You walk there automatically."""
    wanted = max(1, int(count))
    return run(lambda g: render.gather_text(g.call("gather", _name(item), wanted), wanted))


@tool("crafts {count} {item}", lambda a: a["preview"])
def craft(item: str, count: int = 1, preview: bool = False) -> str:
    """Hand-craft an item, including needed intermediate parts. preview=true only shows the recipe. Plates cannot be crafted: smelt ore in a furnace."""
    name = _name(item)
    if preview:
        return run(lambda g: render.recipe_text(g.call("recipe", name)))
    return run(lambda g: render.craft_text(g.call("craft", name, max(1, int(count)))))


@tool("builds {entity} at ({x:g}, {y:g})")
def build(entity: str, x: float, y: float, direction: str = "auto") -> str:
    """Place a building from your inventory. direction: auto (first that fits) or north/east/south/west; give belts and inserters an explicit one. A blocked spot moves to the nearest free one; the reply states the real position."""
    return run(lambda g: render.build_text(
        g.call("build", _name(entity), float(x), float(y), direction_name(direction), 2)))


@tool("rotates the building at ({x:g}, {y:g}) to {direction}")
def rotate(x: float, y: float, direction: str) -> str:
    """Turn the building at x, y to north, east, south or west. The reply confirms the real direction."""
    return run(lambda g: render.rotate_text(g.call("rotate", float(x), float(y), direction_name(direction))))


@tool("builds a miner on {ore}")
def build_miner(ore: str = "iron-ore") -> str:
    """Place a burner mining drill on ore that drops into a stone furnace, then fuel both with coal. Needs burner-mining-drill and stone-furnace in inventory. Direction is solved for you."""
    return run(lambda g: render.miner_text(g.call("build_miner", _name(ore))))


@tool()
def fuel(x: float | None = None, y: float | None = None, item: str = "coal", per: int = 5) -> str:
    """Add fuel to the building at x, y, or to every burner machine within 30 tiles if no position is given."""
    return run(lambda g: render.fuel_text(g.call(
        "fuel", None if x is None else float(x), None if y is None else float(y),
        _name(item), max(1, int(per)))))


@tool()
def collect(radius: int = 30) -> str:
    """Take finished items (plates, bricks) out of all furnaces and machines within radius."""
    return run(lambda g: render.collect_text(g.call("collect", radius)))


@tool()
def insert(x: float, y: float, item: str, count: int = 0) -> str:
    """Put items from your inventory into the building at x, y (ore into a furnace, ingredients into an assembler). count 0 means all."""
    return run(lambda g: render.insert_text(g.call(
        "insert", float(x), float(y), _name(item), int(count) if count > 0 else None)))


@tool("sets recipe {recipe}")
def set_recipe(x: float, y: float, recipe: str) -> str:
    """Set the recipe of the assembling machine at x, y."""
    return run(lambda g: render.set_recipe_text(g.call("set_recipe", float(x), float(y), _name(recipe))))


@tool("starts research {name}", lambda a: not a["name"])
def research(name: str = "") -> str:
    """Without a name: list technologies you can research now. With a name: queue it."""
    return run(lambda g: render.research_text(g.call("research", _slug(name))))


# ---------------------------------------------------------------- extended tools (FLE parity and more)

def _num(v: float) -> float:
    return float(v)


@tool()
def can_place(entity: str, x: float, y: float, direction: str = "north") -> str:
    """Check whether an entity fits at x,y without building it. If not, says what blocks it and the nearest free spot."""
    return run(lambda g: render.can_place_text(g.call("can_place", _name(entity), _num(x), _num(y), direction_name(direction))))


@tool()
def nearest_buildable(entity: str = "", width: int = 0, height: int = 0, x: float | None = None, y: float | None = None,
                      resource: str = "", radius: int = 30) -> str:
    """Find the nearest free area for an entity (or a width x height block). With resource (e.g. iron-ore) at least half of it must lie on that ore."""
    return run(lambda g: render.site_text(g.call(
        "nearest_buildable", _name(entity) or None, width or None, height or None,
        None if x is None else _num(x), None if y is None else _num(y), _name(resource) or None, radius)))


@tool("builds {entity} next to ({ref_x:g}, {ref_y:g})")
def build_next_to(entity: str, ref_x: float, ref_y: float, side: str, spacing: int = 0, direction: str = "auto") -> str:
    """Build an entity directly beside one of your buildings (side = north/east/south/west of it, spacing = free tiles between)."""
    return run(lambda g: render.build_text(g.call("build_next_to", _name(entity), _num(ref_x), _num(ref_y),
                                                  direction_name(side), spacing, direction_name(direction))))


@tool("picks up the building at ({x:g}, {y:g})")
def pickup(x: float, y: float) -> str:
    """Pick up one of your buildings at x,y. Its contents and the item itself return to your inventory."""
    return run(lambda g: render.pickup_text(g.call("pickup", _num(x), _num(y))))


@tool()
def move_entity(x: float, y: float, new_x: float, new_y: float) -> str:
    """Move a building to a new position (keeps rotation and recipe where possible, restores it if the target is blocked)."""
    return run(lambda g: render.shift_text(g.call("shift_entity", _num(x), _num(y), _num(new_x), _num(new_y))))


@tool()
def extract(x: float, y: float, item: str, count: int = 10) -> str:
    """Take items out of a building (furnace output, chest, assembler output) into your inventory."""
    return run(lambda g: render.extract_text(g.call("extract", _num(x), _num(y), _name(item), count)))


@tool()
def inventory(x: float | None = None, y: float | None = None) -> str:
    """Without x,y: your inventory. With x,y: all contents of the building there (fuel, input, output, chest)."""
    return run(lambda g: render.inv_view_text(g.call("inventory", None if x is None else _num(x), None if y is None else _num(y))))


@tool()
def inspect(x: float, y: float) -> str:
    """Details of the entity at x,y: facing, status, recipe, inventories, fluids, where its output goes, belt continuation, power network."""
    return run(lambda g: render.entity_text(g.call("get_entity", _num(x), _num(y))))


@tool()
def list_entities(names: str = "", x: float | None = None, y: float | None = None, radius: int = 25, limit: int = 60) -> str:
    """List your buildings around x,y (default: you), optionally only some names (comma separated). Also groups belts, pipes and poles into connected lines/networks."""
    wanted = [_name(n) for n in names.split(",") if n.strip()]
    return run(lambda g: render.entities_text(g.call("get_entities", wanted, None if x is None else _num(x),
                                                     None if y is None else _num(y), radius, limit)))


@tool()
def resource_patch(resource: str, x: float | None = None, y: float | None = None) -> str:
    """Size, total amount, center and bounding box of the nearest patch of an ore (iron-ore, copper-ore, coal, stone, ...)."""
    return run(lambda g: render.patch_text(g.call("resource_patch", _name(resource),
                                                  None if x is None else _num(x), None if y is None else _num(y))))


@tool()
def move_to(x: float, y: float) -> str:
    """Go to x,y (teleports to the nearest free spot there)."""
    return run(lambda g: render.move_text(g.call("move_to", _num(x), _num(y))))


@tool("lays {kind} from ({x1:g}, {y1:g}) to ({x2:g}, {y2:g})", lambda a: a["dry_run"])
def connect(kind: str, x1: float, y1: float, x2: float, y2: float, entity: str = "",
            end_direction: str = "", dry_run: bool = False) -> str:
    """Lay belt, pipe or power poles from (x1,y1) to (x2,y2); belts and pipes route around obstacles. end_direction: facing of the last belt. dry_run=true only counts the pieces."""
    return run(lambda g: render.connect_text(g.call("connect", kind.strip().lower(), _num(x1), _num(y1), _num(x2), _num(y2),
                                                    _name(entity) or None, direction_name(end_direction) if end_direction else None, dry_run)))


@tool()
def research_info(name: str = "") -> str:
    """Progress and remaining science packs of a technology (default: the current one)."""
    return run(lambda g: render.research_info_text(g.call("research_info", _slug(name))))


@tool()
def score() -> str:
    """Production statistics: what has been produced so far, items per minute, number of researched technologies."""
    return run(lambda g: render.score_text(g.call("score")))


@tool("launches the rocket!")
def launch_rocket(x: float | None = None, y: float | None = None) -> str:
    """Launch the rocket of the (nearest) rocket silo, if it is ready."""
    return run(lambda g: _launch(g.call("launch_rocket", None if x is None else _num(x), None if y is None else _num(y))))


def _launch(data: dict) -> str:
    return f"rocket launched from silo at {render.at(data)}"


@tool()
def say(message: str) -> str:
    """Write a message into the game chat as [Bot] (for the human who plays with you). Use it to report progress, ask for help or explain what you plan."""
    return run(lambda g: f"said: {g.call('say', message)['said']}")


@tool()
def set_game_speed(speed: float = 1.0) -> str:
    """Change the game speed (1 = normal, 0.1 to 10). Useful to wait for crafting or smelting."""
    return run(lambda g: f"game speed is now {g.call('set_speed', float(speed))['speed']}")


@tool()
def map(x1: float | None = None, y1: float | None = None, x2: float | None = None, y2: float | None = None,
        layers: str = "all") -> str:
    """ASCII map between two corners (max 100x60; default: around you). Belts ^ > v <, machines as letters, i/c/k/s ore, t tree, ~ water, @ you. layers: all or e.g. belts,machines."""
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


@tool()
def render_map(x1: float | None = None, y1: float | None = None, x2: float | None = None, y2: float | None = None,
               scale: int = 16) -> str:
    """Draw an SVG picture for the HUMAN (you cannot see it; use map). Returns file path and live viewer link."""
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


def _bp_save(name: str, x1: float, y1: float, x2: float, y2: float, description: str = "") -> str:
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


def _bp_list() -> str:
    """List saved blueprints with description and status (draft = untested, tested = worked in practice)."""
    store = _store()
    names = store.names()
    if not names:
        return "no blueprints yet. Build something that works, then use blueprint action=save."
    lines = []
    for n in names:
        bp = store.load(n)
        lines.append(f"- {n} [{bp.get('status', 'draft')}] {bp['width']}x{bp['height']}: {bp.get('description') or '(no description)'}")
    return "\n".join(lines)


def _bp_show(name: str, rotation: int = 0) -> str:
    """Show a blueprint as ASCII picture with required items, description and notes. rotation = 0, 90, 180 or 270 (clockwise)."""
    try:
        bp = _store().load(name)
    except KeyError:
        return f"ERR unknown_blueprint: '{name}' | try: blueprint action=list"
    turns = (rotation // 90) % 4
    need = ", ".join(f"{v} {k}" for k, v in sorted(bp["items"].items()))
    text = f"blueprint {bp['name']} [{bp.get('status')}] {bp.get('description', '')}\nneeds: {need}\n"
    text += _bp_preview(bp, turns)
    for n in bp.get("notes", []):
        text += f"\nnote: {n}"
    return text


def _bp_place(name: str, x: float, y: float, rotation: int = 0, dry_run: bool = False) -> str:
    """Build a saved blueprint with its top left corner at x,y. rotation = 0, 90, 180 or 270 clockwise. dry_run=true only checks items and free space. Reports exactly which parts failed so you can fix them."""
    try:
        bp = _store().load(name)
    except KeyError:
        return f"ERR unknown_blueprint: '{name}' | try: blueprint action=list"
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
            text += ". Look at the result with map, fix the parts and add what you learned with blueprint action=note."
        return text
    return run(action)


def _bp_note(name: str, note: str = "", status: str = "", description: str = "") -> str:
    """Improve a blueprint together with the human: add a note (what worked, what to watch out for), set status to draft or tested, or change the description."""
    store = _store()
    try:
        bp = store.load(name)
    except KeyError:
        return f"ERR unknown_blueprint: '{name}' | try: blueprint action=list"
    if note:
        bp.setdefault("notes", []).append(note)
    if status in ("draft", "tested"):
        bp["status"] = status
    if description:
        bp["description"] = description
    store.save(bp)
    return f"updated '{bp['name']}' [{bp['status']}], {len(bp.get('notes', []))} notes"


def _bp_delete(name: str) -> str:
    """Delete a saved blueprint."""
    return f"deleted '{name}'" if _store().delete(name) else f"ERR unknown_blueprint: '{name}'"



@tool("places blueprint {name} at ({x:g}, {y:g})", lambda a: a["action"] != "place" or a["dry_run"])
def blueprint(action: str = "list", name: str = "", x1: float = 0, y1: float = 0, x2: float = 0, y2: float = 0,
              x: float = 0, y: float = 0, rotation: int = 0, dry_run: bool = False,
              note: str = "", status: str = "", description: str = "") -> str:
    """Reusable layouts you develop with the human. action: save (name, area x1 y1 x2 y2, description), list, show (name, rotation), place (name, top left x y, rotation 0/90/180/270, dry_run), note (name, note, status draft/tested), delete (name)."""
    act = _slug(action)
    if act != "list" and not name.strip():
        return "ERR no_name: give the blueprint name | try: blueprint action=list"
    if act == "save":
        return _bp_save(name, x1, y1, x2, y2, description)
    if act == "show":
        return _bp_show(name, rotation)
    if act == "place":
        return _bp_place(name, x, y, rotation, dry_run)
    if act == "note":
        return _bp_note(name, note, status, description)
    if act == "delete":
        return _bp_delete(name)
    if act == "list":
        return _bp_list()
    return "ERR bad_action: action must be save, list, show, place, note or delete"


@tool()
def notes(action: str = "list", text: str = "", tag: str = "", note_id: int = 0) -> str:
    """Notebook that survives context resets. action: add (text, tag goal/location/lesson), list (tag), remove (note_id)."""
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



# ---------------------------------------------------------------- goal tracker

def _goal_file():
    return _data_dir() / "goal.json"


def _goal_load() -> dict[str, Any]:
    try:
        return json.loads(_goal_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _goal_save(goal_data: dict[str, Any]) -> None:
    f = _goal_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(goal_data, indent=1, ensure_ascii=False), encoding="utf-8")


def _goal_line() -> str:
    g = _goal_load()
    if not g.get("text"):
        return ""
    steps = g.get("steps", [])
    done = sum(1 for s in steps if s.get("done"))
    open_steps = [i for i, s in enumerate(steps, 1) if not s.get("done")]
    if not steps:
        return f"goal: {g['text']}"
    if not open_steps:
        return f"goal: {g['text']} [all {len(steps)} steps done: check it, then goal action=clear]"
    i = open_steps[0]
    return f"goal: {g['text']} [{done}/{len(steps)}] next step {i}: {steps[i - 1]['t']}"


@tool()
def goal(action: str = "show", text: str = "", steps: str = "", step: int = 0) -> str:
    """Your current goal with a checklist; shown in status and after every action. action: set (text, steps separated by ;), done (step number, default the next open one), show, clear."""
    act = _slug(action)
    g = _goal_load()
    if act == "set":
        if not text.strip():
            return "ERR no_text: give the goal text, e.g. goal action=set text=\"automate iron plates\" steps=\"4 miners; belt; furnaces\""
        parts = [s.strip() for s in steps.replace("\n", ";").split(";") if s.strip()]
        _goal_save({"text": text.strip(), "steps": [{"t": s, "done": False} for s in parts]})
        return "goal set. " + _goal_line()
    if act == "done":
        items = g.get("steps", [])
        open_steps = [i for i, s in enumerate(items, 1) if not s.get("done")]
        if not open_steps:
            return "ERR no_step: no open step | try: goal action=show"
        n = step or open_steps[0]
        if not 1 <= n <= len(items):
            return f"ERR bad_step: step must be 1 to {len(items)}"
        items[n - 1]["done"] = True
        _goal_save(g)
        return f"step {n} done. " + _goal_line()
    if act == "clear":
        _goal_save({})
        return "goal cleared"
    if not g.get("text"):
        return "no goal set. Set one: goal action=set text=... steps=\"a; b; c\""
    lines = [f"goal: {g['text']}"]
    for i, s in enumerate(g.get("steps", []), 1):
        lines.append(f"{i}. [{'x' if s.get('done') else ' '}] {s['t']}")
    return "\n".join(lines)


@tool("builds {count} miners on {ore}")
def build_miners(ore: str = "iron-ore", count: int = 2) -> str:
    """Build several burner miners (drill feeding a furnace, both fueled) on one ore in one call. Needs one burner-mining-drill and one stone-furnace per miner."""
    wanted = max(1, min(int(count), 10))

    def action(g: Game) -> str:
        built, lines = 0, []
        for _ in range(wanted):
            try:
                lines.append(render.miner_text(g.call("build_miner", _name(ore))))
                built += 1
            except GameError as err:
                lines.append(render.error_text(err))
                break
        if built == 0:
            return lines[0]
        return f"built {built}/{wanted} miners on {_name(ore)}\n" + "\n".join(lines)
    return run(action)


@tool()
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


@tool("saved a checkpoint")
def checkpoint(name: str = "") -> str:
    """Write a save file of the current game state (snapshot) that the human can load later. Do this before risky experiments."""
    return run(lambda g: f"saved game as '{g.call('save_game', name.strip())['saved']}'")


# ---------------------------------------------------------------- tracking items and machines

_sleep = time.sleep


@tool()
def belt_contents(x1: float | None = None, y1: float | None = None, x2: float | None = None, y2: float | None = None) -> str:
    """Items on the belts in an area (two corners, default around you): kinds, fill level, empty pieces."""
    return run(lambda g: tracking.belt_text(g.call("belt_contents", *(None if v is None else _num(v) for v in (x1, y1, x2, y2)))))


@tool()
def trace_item(x: float, y: float, item: str = "wood", wait_seconds: int = 15) -> str:
    """Put one carried item (wood is best) on the belt at x,y and follow it: reports STUCK with position, left the belt, or still moving. Proves a belt works."""
    seconds = min(max(wait_seconds, 2), 90)
    return run(lambda g: tracking.trace(g, _num(x), _num(y), _name(item), seconds, _sleep))


@tool()
def measure_flow(x: float, y: float, seconds: int = 10, item: str = "") -> str:
    """Measure a machine or belt tile at x,y over some game seconds: crafts per minute and working share, or average belt load. item: factory-wide production per minute."""
    secs = min(max(seconds, 3), 120)
    return run(lambda g: tracking.flow(g, _num(x), _num(y), secs, _name(item), _sleep))


@tool()
def machine_stats(x: float | None = None, y: float | None = None, radius: int = 20, seconds: int = 10) -> str:
    """Watch the machines around x,y for some seconds: working share, crafts per minute and a diagnosis of what holds production back."""
    secs = min(max(seconds, 4), 120)
    return run(lambda g: tracking.machine_stats(g, None if x is None else _num(x), None if y is None else _num(y), radius, secs, _sleep))


# ---------------------------------------------------------------- chat and batch

@tool()
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


def _coerce(fn: Callable[..., str], args: dict[str, Any]) -> dict[str, Any]:
    """Batch arguments bypass the MCP validation, so convert "10" -> 10.0 etc. by the annotations."""
    sig = _inspect.signature(fn)
    out = {}
    for key, value in args.items():
        param = sig.parameters.get(key)
        ann = str(param.annotation) if param else ""
        if isinstance(value, str) and param is not None:
            text = value.strip()
            if text.lower() in ("", "none", "null") and "None" in ann:
                value = None
            elif ann.startswith("float"):
                value = float(text)
            elif ann.startswith("int"):
                value = int(float(text))
            elif ann.startswith("bool"):
                value = text.lower() in ("1", "true", "yes", "on")
        out[key] = value
    return out


def _signature_hint(name: str) -> str:
    fn = REGISTRY[name]
    parts = []
    for p in _inspect.signature(fn).parameters.values():
        parts.append(p.name if p.default is _inspect.Parameter.empty else f"{p.name}={p.default!r}")
    return f"{name}({', '.join(parts)})"


@tool()
def batch(actions: list[dict[str, Any]], stop_on_error: bool = True) -> str:
    """Run up to 25 tools in order in one call. actions = [{"tool":"build","args":{"entity":"stone-furnace","x":10,"y":5}}, {"tool":"fuel","args":{"x":10,"y":5}}]. Stops at the first error unless stop_on_error=false."""
    global _in_batch
    if isinstance(actions, str):
        try:
            actions = json.loads(actions)
        except json.JSONDecodeError:
            return "ERR bad_args: actions must be a JSON list of {tool, args}"
    if isinstance(actions, dict):
        actions = [actions]
    if not actions:
        return "ERR no_actions: give a list of {tool, args}"
    if len(actions) > BATCH_MAX:
        return f"ERR too_many: at most {BATCH_MAX} actions per batch"
    known = set(_registered) or set(REGISTRY)
    lines, failed = [], 0
    _in_batch = True
    try:
        for i, act in enumerate(actions, 1):
            act = dict(act) if isinstance(act, dict) else {}
            name = str(act.pop("tool", "") or act.pop("name", "")).strip()
            args = act.pop("args", None) or act.pop("arguments", None) or act.pop("params", None) or act
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            if name in BATCH_DENY or name not in known:
                lines.append(f"{i}. {name or '?'}: ERR not_allowed: unknown tool or not usable in a batch")
                failed += 1
            else:
                try:
                    result = REGISTRY[name](**_coerce(REGISTRY[name], dict(args)))
                except (TypeError, ValueError) as err:
                    result = f"ERR bad_args: {err} | try: {_signature_hint(name)}"
                lines.append(f"{i}. {name}: {result}")
                failed += 1 if result.startswith("ERR") or result.startswith("STOP") else 0
            if failed and stop_on_error:
                lines.append(f"stopped after action {i} because of the error; {len(actions) - i} not run")
                break
    finally:
        _in_batch = False
    return "\n".join(lines) + _footer()


@tool()
def selftest(x: float | None = None, y: float | None = None) -> str:
    """Developer check after installing: tests the mod's game assumptions in a free sandbox area and removes everything again."""
    return run(lambda g: tracking.selftest_text(g.call("selftest", None if x is None else _num(x), None if y is None else _num(y))))


if os.environ.get("FACTORIO_MCP_DISABLE_LUA") != "1":

    @tool()
    def run_lua(code: str) -> str:
        """LAST RESORT, use ONLY when absolutely necessary and no other tool can do it: runs raw Lua in the game, unchecked. Keep it short, never delete what you did not build, return values with rcon.print(...)."""
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


apply_profile()


if __name__ == "__main__":
    main()
