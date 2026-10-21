"""Underground belts: always a pair, built with the right types, verified, never as a lone piece."""

from __future__ import annotations

from factorio_agent_mcp import asciimap, render, server
from factorio_agent_mcp.game import GameError


def test_pair_is_built_with_entrance_and_exit(world, game):
    world.exec("mock.give('underground-belt', 2)")
    out = server.build_underground(2.5, 0.5, 6.5, 0.5)
    assert out.startswith("placed underground-belt pair"), out
    assert "facing east" in out and "4 tiles apart" in out and "paired" in out
    types = sorted(world.eval("(function() local t = {} for _, e in ipairs(game.surfaces.nauvis.find_entities_filtered{name='underground-belt'}) do t[#t+1] = e.position.x .. ':' .. e.belt_to_ground_type end return table.concat(t, ',') end)()").split(","))
    assert types == ["2.5:input", "6.5:output"]
    assert world.eval("mock.inventory_count('underground-belt')") == 0


def test_direction_follows_entrance_to_exit(world, game):
    world.exec("mock.give('underground-belt', 2)")
    assert "facing north" in server.build_underground(4.5, 6.5, 4.5, 2.5)
    assert world.eval("game.surfaces.nauvis.find_entities_filtered{name='underground-belt'}[1].direction") == 0


def test_errors_and_nothing_left_behind(world, game):
    world.exec("mock.give('underground-belt', 2)")
    assert server.build_underground(0.5, 0.5, 3.5, 2.5).startswith("ERR not_in_line")
    assert server.build_underground(0.5, 0.5, 0.5, 0.5).startswith("ERR not_in_line")
    too_far = server.build_underground(0.5, 0.5, 8.5, 0.5)
    assert too_far.startswith("ERR too_far") and "at most 5" in too_far
    assert server.build_underground(0.5, 0.5, 3.5, 0.5, entity="stone-furnace").startswith("ERR unknown_entity")
    assert world.eval("mock.entity_count('underground-belt')") == 0
    assert world.eval("mock.inventory_count('underground-belt')") == 2


def test_missing_items(world, game):
    world.exec("mock.give('underground-belt', 1)")
    out = server.build_underground(0.5, 0.5, 3.5, 0.5)
    assert out.startswith("ERR missing") and "craft item=underground-belt" in out
    assert world.eval("mock.entity_count('underground-belt')") == 0


def test_blocked_exit_picks_the_entrance_up_again(world, game):
    world.exec("mock.give('underground-belt', 2); mock.add_entity('stone-furnace', 6.5, 0.5, 0)")
    out = server.build_underground(2.5, 0.5, 6.5, 0.5)
    assert out.startswith("ERR blocked") and "exit" in out
    assert world.eval("mock.entity_count('underground-belt')") == 0
    assert world.eval("mock.inventory_count('underground-belt')") == 2


def test_build_and_rotate_refuse_single_pieces(world, game):
    world.exec("mock.give('underground-belt', 3)")
    out = server.build("underground-belt", 3.5, 3.5, "east")
    assert out.startswith("ERR use_build_underground") and "build_underground" in out
    assert world.eval("mock.entity_count('underground-belt')") == 0
    server.build_underground(2.5, 0.5, 5.5, 0.5)
    assert server.rotate(2.5, 0.5, "west").startswith("ERR rotate_underground")


def test_ascii_map_shows_entrance_and_exit():
    snap = {"tick": 1, "area": {"x1": 0, "y1": 0, "x2": 8, "y2": 3}, "palette": {}, "rows": [], "resources": {}, "trees": [],
            "agent": {}, "entities": [
                {"n": "underground-belt", "t": "underground-belt", "x": 1.5, "y": 1.5, "w": 1, "h": 1, "d": "east", "u": "input", "f": "p"},
                {"n": "underground-belt", "t": "underground-belt", "x": 5.5, "y": 1.5, "w": 1, "h": 1, "d": "east", "u": "output", "f": "p"}]}
    text = asciimap.render(snap)
    assert "u=underground entrance" in text and "U=underground exit" in text


def test_hints_for_underground_errors():
    for code in ("use_build_underground", "rotate_underground", "not_in_line", "too_far", "not_paired"):
        assert " | try:" in render.error_text(GameError(code, "x", {"max": 5}))
