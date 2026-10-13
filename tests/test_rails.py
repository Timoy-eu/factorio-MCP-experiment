"""Rails: the geometry table learned from the game, the router (real Lua, fake obstacles) and the displays."""

from __future__ import annotations

import json
import math
import pathlib

import pytest

from factorio_agent_mcp import asciimap, render
from factorio_agent_mcp.game import GameError

from conftest import LuaWorld

ROOT = pathlib.Path(__file__).resolve().parents[1]
TABLE = json.loads((ROOT / "src" / "factorio_agent_mcp" / "data" / "rail_table.json").read_text())["pieces"]


def key(name: str, direction: int) -> str:
    return f"{name}|{direction}"


# ------------------------------------------------------------------ the learned table

def test_table_every_end_has_left_straight_right():
    assert len(TABLE) == 24
    for k, piece in TABLE.items():
        for end in ("front", "back"):
            turns = sorted(n[0] for n in piece[end]["next"])
            assert turns == ["left", "right", "straight"], (k, end, turns)


def test_table_targets_exist_and_connect_back():
    """If B follows A, then A must follow B at the end where they touch (offsets mirrored)."""
    for k, piece in TABLE.items():
        for end in ("front", "back"):
            for turn, name, direction, dx, dy, edir, edx, edy in piece[end]["next"]:
                target = TABLE[key(name, direction)]
                exits = [e for e in ("front", "back")
                         if target[e]["end_dir"] == edir
                         and target[e]["end_rel"][0] + dx == edx and target[e]["end_rel"][1] + dy == edy]
                assert len(exits) == 1, (k, end, name, direction)
                entered = "back" if exits[0] == "front" else "front"
                back_links = [n for n in target[entered]["next"]
                              if n[1] == k.split("|")[0] and n[2] == int(k.split("|")[1]) and n[3] == -dx and n[4] == -dy]
                assert back_links, f"{k} {end} -> {name}|{direction} has no way back"


def test_table_curve_families():
    """curved-rail-a joins orthogonal pieces, curved-rail-b joins diagonal ones."""
    straight_north = TABLE["straight-rail|0"]["front"]["next"]
    assert {n[1] for n in straight_north if n[0] != "straight"} == {"curved-rail-a"}
    straight_diag = TABLE["straight-rail|2"]["front"]["next"]
    assert {n[1] for n in straight_diag if n[0] != "straight"} == {"curved-rail-b"}


# ------------------------------------------------------------------ router (real Lua, fake world)

@pytest.fixture(scope="module")
def world():
    return LuaWorld()


def search(world, start, goal, blocked=(), goal_dir=None, existing=False, reusable=()):
    """Run the mod's A* with a fake world; blocked = list of (x1, y1, x2, y2) rectangles."""
    rects = "{" + ",".join("{%s,%s,%s,%s}" % r for r in blocked) + "}"
    reuse = "{" + ",".join('["%s|%s|%s|%s"]=true' % r for r in reusable) + "}"
    gdir = "nil" if goal_dir is None else str(goal_dir)
    sname, sdir, sx, sy, sexit = start
    code = f"""
    local R = require("scripts.rails")
    local rects, reusable = {rects}, {reuse}
    local function hit(name, dir, x, y)
      local p = R.PIECES[name .. "|" .. dir]
      local pts = {{ {{x, y}}, {{x + p.front.end_rel[1], y + p.front.end_rel[2]}}, {{x + p.back.end_rel[1], y + p.back.end_rel[2]}} }}
      for _, r in ipairs(rects) do
        for _, q in ipairs(pts) do
          if q[1] >= r[1] and q[1] <= r[3] and q[2] >= r[2] and q[2] <= r[4] then return true end
        end
      end
      return false
    end
    local path, why = R.search {{
      starts = {{ {{ name = "{sname}", dir = {sdir}, x = {sx}, y = {sy}, exit = "{sexit}", existing = {str(existing).lower()} }} }},
      goal = {{ x = {goal[0]}, y = {goal[1]}, dir = {gdir} }},
      can_place = function(name, dir, x, y) return not hit(name, dir, x, y), 0 end,
      reuse = function(name, dir, x, y) return reusable[name .. "|" .. dir .. "|" .. x .. "|" .. y] == true end,
    }}
    if not path then return "nil:" .. tostring(why) end
    local out = {{}}
    for _, n in ipairs(path) do out[#out + 1] = table.concat({{n.name, n.dir, n.x, n.y, n.exit}}, ",") end
    return table.concat(out, ";")
    """
    result = world.exec(code)
    if str(result).startswith("nil:"):
        return None, str(result)[4:]
    return [tuple(int(v) if v.lstrip("-").isdigit() else v for v in item.split(",")) for item in str(result).split(";")], None


def exit_point(piece):
    name, direction, x, y, end = piece
    e = TABLE[key(name, direction)][end]
    return x + e["end_rel"][0], y + e["end_rel"][1], e["end_dir"]


def assert_connected_chain(path, start=None):
    """Independent check of a path: each piece must be a listed continuation of the previous one.
    start = an existing piece the path continues from (None: the first piece is the new start)."""
    prev = start
    for piece in path:
        if prev is not None:
            name, direction, x, y, end = prev
            options = TABLE[key(name, direction)][end]["next"]
            nxt = [n for n in options if n[1] == piece[0] and n[2] == piece[1] and x + n[3] == piece[2] and y + n[4] == piece[3]]
            assert nxt, f"{piece} does not follow {prev}"
            expect_exit = [e for e in ("front", "back")
                           if TABLE[key(piece[0], piece[1])][e]["end_dir"] == nxt[0][5]
                           and piece[2] + TABLE[key(piece[0], piece[1])][e]["end_rel"][0] == x + nxt[0][6]
                           and piece[3] + TABLE[key(piece[0], piece[1])][e]["end_rel"][1] == y + nxt[0][7]]
            assert piece[4] in expect_exit, f"{piece} leaves through the end it came in by"
        prev = piece


START = ("straight-rail", 4, 1, 1, "front")


def test_router_straight_line(world):
    path, _ = search(world, START, (41, 1))
    assert path[0] == START
    assert path is not None
    assert all(p[0] == "straight-rail" for p in path)
    assert_connected_chain(path)
    ex, ey, _ = exit_point(path[-1])
    assert math.hypot(ex - 41, ey - 1) <= 1.0


def test_router_diagonal_target_uses_diagonals_and_curves(world):
    path, _ = search(world, START, (40, 30))
    assert path is not None
    assert_connected_chain(path)
    assert {p[0] for p in path} & {"curved-rail-a", "curved-rail-b", "half-diagonal-rail"}
    ex, ey, _ = exit_point(path[-1])
    assert math.hypot(ex - 40, ey - 30) <= 1.0


def test_router_goes_around_a_wall(world):
    wall = (20, -10, 27, 14)
    path, _ = search(world, START, (45, 1), blocked=[wall])
    assert path is not None
    assert_connected_chain(path)
    for p in path:
        name, direction, x, y, _end = p
        piece = TABLE[key(name, direction)]
        pts = [(x, y), (x + piece["front"]["end_rel"][0], y + piece["front"]["end_rel"][1]),
               (x + piece["back"]["end_rel"][0], y + piece["back"]["end_rel"][1])]
        assert not any(wall[0] <= px <= wall[2] and wall[1] <= py <= wall[3] for px, py in pts)
    assert max(p[3] for p in path) > 14 or min(p[3] for p in path) < -10  # it really detoured


def test_router_end_direction_is_respected(world):
    for goal_dir in (4, 8):
        path, _ = search(world, START, (30, 20), goal_dir=goal_dir)
        assert path is not None, goal_dir
        assert exit_point(path[-1])[2] == goal_dir


def test_router_continues_from_an_existing_piece(world):
    existing = ("straight-rail", 4, 11, 1, "front")
    path, _ = search(world, existing, (40, 12), existing=True)
    assert path is not None
    assert_connected_chain(path, existing)
    assert path[0][2] > 11  # the existing piece itself is not part of the result


def test_router_reuses_identical_existing_pieces(world):
    path, _ = search(world, START, (21, 1), reusable=[("straight-rail", 4, 3, 1), ("straight-rail", 4, 5, 1)])
    assert path is not None
    assert_connected_chain(path)


def test_router_reports_unreachable_goal(world):
    box = [(30, -10, 37, 12), (30, -10, 70, -3), (30, 5, 70, 12), (63, -10, 70, 12)]  # goal is inside a closed box
    path, why = search(world, START, (45, 1), blocked=box)
    assert path is None
    assert why in ("no_path", "limit"), why


def test_router_blocked_start(world):
    path, why = search(world, START, (30, 1), blocked=[(-5, -5, 5, 5)])
    assert path is None and why == "no_start"


# ------------------------------------------------------------------ displays and texts

def snapshot_with(entities):
    return {"tick": 1, "area": {"x1": 0, "y1": 0, "x2": 12, "y2": 8}, "palette": {}, "rows": [], "resources": {},
            "trees": [], "entities": entities, "agent": {}}


def test_ascii_map_draws_rails():
    ents = [
        {"n": "straight-rail", "t": "straight-rail", "x": 2, "y": 2, "w": 2, "h": 2, "d": "0", "f": "p"},
        {"n": "straight-rail", "t": "straight-rail", "x": 5, "y": 2, "w": 2, "h": 2, "d": "4", "f": "p"},
        {"n": "straight-rail", "t": "straight-rail", "x": 8, "y": 2, "w": 2, "h": 2, "d": "2", "f": "p"},
        {"n": "curved-rail-a", "t": "curved-rail-a", "x": 10, "y": 6, "w": 2, "h": 2, "d": "6", "f": "p"},
        {"n": "rail-signal", "t": "rail-signal", "x": 6.5, "y": 5.5, "w": 1, "h": 1, "d": "4", "f": "p"},
        {"n": "train-stop", "t": "train-stop", "x": 3.5, "y": 6.5, "w": 1, "h": 1, "f": "p", "bn": "Iron"},
        {"n": "locomotive", "t": "locomotive", "x": 6, "y": 7, "w": 6, "h": 2, "o": 0.25, "f": "p"},
    ]
    text = asciimap.render(snapshot_with(ents))
    for glyph in ("|", "-", "/", "\\", "!", "Z", "M"):
        assert glyph in text, glyph
    assert "rail north-south" in text and "train stop" in text and "locomotive" in text
    only = asciimap.render(snapshot_with(ents), layers="rails")
    assert "|" in only
    assert asciimap.render(snapshot_with(ents), layers="belts").count("|") == 0 or "rail north-south" not in asciimap.render(snapshot_with(ents), layers="belts")


def test_dir16_names_and_numbers():
    assert asciimap.dir16("north") == 0 and asciimap.dir16("2") == 2 and asciimap.dir16(14) == 14
    assert asciimap.dir16("west") == 12 and asciimap.dir16("bogus") is None


def test_rail_texts():
    dry = {"item": "rail", "needed": 23, "have": 5, "enough": False, "pieces": 14,
           "by_type": {"straight-rail": 9, "curved-rail-a": 2}, "to": {"x": 40, "y": 2, "direction": 2}, "trees_to_clear": 3}
    text = render.connect_text(dry)
    assert "14 pieces" in text and "missing 18" in text and "northeast" in text and "3 tree" in text
    real = {"placed": 14, "rails_used": 23, "by_type": {"straight-rail": 14}, "connected": True,
            "to": {"x": 40, "y": 2, "direction": 4}, "continues_existing": True, "trees_cleared": 2}
    text = render.connect_text(real)
    assert "laid 14 rail pieces" in text and "verified by the game" in text and "continued" in text and "removed 2" in text
    ends = {"count": 1, "ends": [{"piece": "straight-rail", "x": 19, "y": 1, "end_x": 20, "end_y": 1, "end_direction": 4}]}
    assert "facing east" in render.rail_end_list_text(ends)
    assert "no open rail end" in render.rail_end_list_text({"ends": [], "count": 0})


def test_rail_error_hints():
    missing = GameError("missing", "missing 5 rail", {"item": "rail", "count": 5})
    assert "steel" in render.error_text(missing)
    assert "waypoint" in render.error_text(GameError("no_path", "no rail route", {}))


def test_svg_draws_rails_signals_stops_and_trains(world):
    import xml.dom.minidom

    from factorio_agent_mcp import svgmap

    path, _ = search(world, START, (40, 22), blocked=[(14, -4, 21, 14)])
    assert path is not None
    ents = [{"n": n, "t": n, "x": x, "y": y, "w": 2, "h": 2, "d": str(d), "f": "p"} for n, d, x, y, _e in path]
    ents += [
        {"n": "rail-signal", "t": "rail-signal", "x": 6.5, "y": 3.5, "w": 1, "h": 1, "d": "4", "f": "p"},
        {"n": "train-stop", "t": "train-stop", "x": 9.5, "y": 3.5, "w": 1, "h": 1, "f": "p", "bn": "Iron <A&B>"},
        {"n": "locomotive", "t": "locomotive", "x": 12, "y": 1, "w": 6, "h": 2, "o": 0.25, "f": "p"},
        {"n": "cargo-wagon", "t": "cargo-wagon", "x": 18, "y": 1, "w": 6, "h": 2, "o": 0.25, "f": "p"},
    ]
    snap = {"tick": 1, "area": {"x1": -2, "y1": -6, "x2": 46, "y2": 28}, "palette": {}, "rows": [], "resources": {},
            "trees": [], "entities": ents, "agent": {}}
    svg = svgmap.render(snap, scale=14)
    xml.dom.minidom.parseString(svg)  # valid XML, so the station name was escaped
    assert svg.count("C") >= len(path)  # one Bezier per rail piece
    assert "rail signal" in svg and "train stop" in svg and "locomotive" in svg and "wagon" in svg
    pth = pathlib.Path(__file__).resolve().parents[1] / "renders"
    pth.mkdir(exist_ok=True)
    (pth / "rails_demo.svg").write_text(svg, encoding="utf-8")
