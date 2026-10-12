"""End to end: MCP tool function -> RCON -> real control.lua -> mock Factorio."""

import json

import pytest

from factorio_agent_mcp import server
from factorio_agent_mcp.game import GameError


def data(game, fn, *args):
    return game.call(fn, *args)


def test_status_fresh_world(world, game):
    text = server.status()
    assert "carry: nothing" in text
    assert "next: 1) gather coal 20" in text


def test_gather_wood_and_stone(world, game):
    world.exec("mock.add_tree(5, 5); mock.add_tree(8, 3); mock.add_tree(12, 12)")
    assert "got" in server.gather("wood", 8)
    assert world.eval("mock.inventory_count('wood')") >= 8
    world.exec("mock.add_patch('stone', 20, 20, 22, 22, 100)")
    out = server.gather("stone", 10)
    assert out.startswith("got 10 stone"), out
    assert world.eval("mock.inventory_count('stone')") == 10


def test_gather_partial_and_missing(world, game):
    world.exec("mock.add_resource('iron-ore', 6, 6, 3)")
    out = server.gather("iron-ore", 10)
    assert "got 3/10 iron-ore" in out and "nothing_found" in out
    out = server.gather("copper-ore", 5)
    assert out.startswith("ERR nothing_found")
    assert server.gather("diamond", 5).startswith("ERR not_gatherable")


def test_gather_stone_falls_back_to_rock(world, game):
    world.exec("mock.add_rock(10, 10)")
    assert server.gather("stone", 5).startswith("got")
    assert world.eval("mock.inventory_count('coal')") == 10


def test_craft_recursive_uses_intermediates(world, game):
    world.exec("mock.give('iron-plate', 9); mock.give('stone', 5)")
    out = server.craft("burner-mining-drill")
    assert out.startswith("crafted burner-mining-drill"), out
    assert world.eval("mock.inventory_count('burner-mining-drill')") == 1
    assert world.eval("mock.inventory_count('iron-plate')") == 0
    assert world.eval("mock.inventory_count('stone')") == 0


def test_craft_errors_have_hints(world, game):
    world.exec("mock.give('iron-plate', 4)")
    out = server.craft("burner-mining-drill")
    assert out.startswith("ERR missing") and "stone" in out
    world.exec("mock.give('stone', 5)")
    out = server.craft("burner-mining-drill")  # 4 plates are not enough for 3 gears + 3 plates
    assert out.startswith("ERR missing") and "iron-plate" in out and "smelt iron-ore" in out
    assert server.craft("iron-plate").startswith("ERR not_by_hand")
    assert server.craft("assembling-machine-1").startswith("ERR locked")
    assert server.craft("nonsense").startswith("ERR no_recipe")


def test_craft_preview_does_not_consume(world, game):
    out = server.craft("burner-mining-drill", preview=True)
    assert "3 iron-gear-wheel" in out and "by hand: yes" in out


def test_craft_spills_when_bag_is_full(world, game):
    world.exec("mock.give('wood', 4)")
    world.exec("local inv = storage.agent.get_main_inventory(); inv.max_items = 1")
    assert server.craft("wooden-chest", 2).startswith("crafted")
    assert world.eval("#mock.world.spilled") >= 1


def test_build_auto_direction_and_readback(world, game):
    world.exec("mock.give('transport-belt', 3)")
    out = server.build("transport-belt", 10, 10)
    assert "built transport-belt at (10,10)" in out and "facing north" in out
    out = server.build("transport-belt", 12, 10, "east")
    assert "facing east" in out and "WARNING" not in out
    out = server.build("transport-belt", 14, 10, "left")  # alias for west
    assert "facing west" in out


def test_build_requires_item_and_valid_direction(world, game):
    assert server.build("transport-belt", 1, 1).startswith("ERR no_item")
    world.exec("mock.give('transport-belt', 1)")
    assert server.build("transport-belt", 1, 1, "sideways").startswith("ERR bad_direction")
    assert world.eval("mock.inventory_count('transport-belt')") == 1  # nothing consumed


def test_build_uses_free_spot_when_blocked(world, game):
    world.exec("mock.give('wooden-chest', 2); mock.add_rock(10, 10)")
    out = server.build("wooden-chest", 10, 10)
    assert out.startswith("built wooden-chest") and "blocked, used nearest" in out
    assert world.eval("mock.inventory_count('wooden-chest')") == 1


def test_build_reports_blockers_and_suggestion(world, game):
    world.exec("mock.give('wooden-chest', 1); mock.add_rock(10, 10)")
    with pytest.raises(GameError) as exc:
        game.call("build", "wooden-chest", 10.0, 10.0, "auto", 0)
    assert exc.value.code == "blocked"
    assert "rock-big" in exc.value.data["blocked_by"]
    assert exc.value.data["suggestion"]
    assert world.eval("mock.inventory_count('wooden-chest')") == 1  # item returned


def test_rotate_belt_and_unrotatable(world, game):
    world.exec("mock.add_entity('transport-belt', 5.5, 5.5, 0); mock.add_entity('wooden-chest', 8.5, 8.5, 0)")
    assert "now faces east" in server.rotate(5.5, 5.5, "east")
    assert server.rotate(8.5, 8.5, "south").startswith("ERR not_rotatable")
    assert server.rotate(20, 20, "south").startswith("ERR no_entity")
    assert server.rotate(5.5, 5.5, "diagonal").startswith("ERR bad_direction")


def test_rotate_detects_ignored_rotation(world, game):
    world.exec("local e = mock.add_entity('transport-belt', 5.5, 5.5, 0); e.rotatable = false")
    out = server.rotate(5.5, 5.5, "east")
    assert out.startswith("ERR rotate_failed") and "still faces north" in out


def test_rotate_assembler_without_fluid_recipe_is_a_noop(world, game):
    """Factorio 2.0: assemblers have no orientation unless the recipe uses fluids."""
    world.exec("mock.add_entity('assembling-machine-1', 30.5, 30.5, 0)")
    assert "now makes iron-gear-wheel" in server.set_recipe(30.5, 30.5, "iron-gear-wheel")
    world.exec("mock.first('assembling-machine-1').insert{name='iron-plate', count=4}")
    out = server.rotate(30.5, 30.5, "south")
    assert out.startswith("assembling-machine-1") and "no orientation" in out, out
    assert world.eval("mock.first('assembling-machine-1').get_recipe().name") == "iron-gear-wheel"
    assert world.eval("mock.first('assembling-machine-1').get_inventory(5).get_item_count('iron-plate')") == 4
    assert world.eval("mock.entity_count('assembling-machine-1')") == 1


def test_rotate_assembler_with_fluid_recipe_recreates(world, game):
    world.exec("mock.add_entity('assembling-machine-1', 30.5, 30.5, 0)")
    assert "now makes chemical-test" in server.set_recipe(30.5, 30.5, "chemical-test")
    out = server.rotate(30.5, 30.5, "south")
    assert "now faces south" in out, out
    assert world.eval("mock.first('assembling-machine-1').get_recipe().name") == "chemical-test"
    assert world.eval("mock.entity_count('assembling-machine-1')") == 1


def test_build_miner_solves_orientation(world, game):
    world.exec("mock.add_patch('iron-ore', 20, 20, 21, 21, 100)")
    world.exec("mock.give('burner-mining-drill', 1); mock.give('stone-furnace', 1); mock.give('coal', 20)")
    # block north, east and south of the drill center (21, 21): only west can work
    for fx, fy in [(21, 19), (23, 21), (21, 23)]:
        world.exec(f"mock.add_entity('wooden-chest', {fx}, {fy}, 0)")
    out = server.build_miner("iron-ore")
    assert out.startswith("miner on iron-ore"), out
    assert "facing west" in out and "furnace at (19,21)" in out
    assert world.eval("mock.entity_count('burner-mining-drill')") == 1
    assert world.eval("mock.entity_count('stone-furnace')") == 1
    assert world.eval("mock.inventory_count('coal')") == 10  # 5 coal in each machine


def test_build_miner_errors(world, game):
    assert server.build_miner("iron-ore").startswith("ERR no_item")
    world.exec("mock.give('burner-mining-drill', 1); mock.give('stone-furnace', 1)")
    assert server.build_miner("iron-ore").startswith("ERR no_ore")
    world.exec("mock.add_resource('iron-ore', 20, 20, 5)")  # a single tile is not enough
    assert server.build_miner("iron-ore").startswith("ERR no_site")
    assert world.eval("mock.inventory_count('burner-mining-drill')") == 1


def test_fuel_collect_insert_cycle(world, game):
    world.exec("mock.add_entity('stone-furnace', 3, 3, 0); mock.add_entity('burner-mining-drill', 7, 3, 0)")
    world.exec("mock.give('coal', 8); mock.give('iron-ore', 6)")
    out = server.fuel()
    assert "total 8" in out and "0 left" in out
    assert "inserted 6 iron-ore into stone-furnace" in server.insert(3, 3, "iron-ore")
    assert server.insert(3, 3, "iron-ore").startswith("ERR no_item")
    assert server.collect().startswith("nothing to collect")
    world.exec("mock.first('stone-furnace').output.insert{name='iron-plate', count=7}")
    assert server.collect() == "collected iron-plate 7"
    assert world.eval("mock.inventory_count('iron-plate')") == 7


def test_fuel_errors(world, game):
    assert server.fuel().startswith("ERR no_item")
    world.exec("mock.give('coal', 3); mock.add_entity('wooden-chest', 4, 4, 0)")
    assert server.fuel().startswith("ERR nothing_to_fuel")
    assert server.fuel(50, 50).startswith("ERR no_entity")


def test_research_listing_and_queue(world, game):
    out = server.research()
    assert "automation" in out and "logistics" in out and "electronics" not in out
    assert server.research("automation") == "research queued: automation"
    assert server.research("electronics").startswith("ERR cannot_queue")
    assert server.research("nope").startswith("ERR unknown_tech")
    assert "current: automation" in server.research()


def test_look_and_find(world, game):
    world.exec("mock.add_patch('coal', 6, 6, 8, 8, 50); mock.add_tree(10, -5); mock.add_water(15, 15)")
    world.exec("mock.add_entity('stone-furnace', 3, 3, 0)")
    out = server.look(30)
    assert "coal 9 tiles" in out and "trees: 1" in out and "water:" in out
    assert "stone-furnace (3,3) [no_fuel]" in out
    assert "nearest coal" in server.find("coal")
    assert "nearest tree" in server.find("tree") or "nearest" in server.find("tree")
    assert server.find("water").startswith("nearest")
    assert server.find("stone-furnace").startswith("nearest stone-furnace")
    assert server.find("uranium-ore").startswith("ERR not_found")


def test_status_shows_machine_problems_and_next_step(world, game):
    world.exec("mock.add_entity('burner-mining-drill', 4, 4, 0); mock.give('coal', 12)")
    text = server.status()
    assert "burner-mining-drill x1 [no_fuel 1]" in text
    assert "1) fuel" in text


def test_missing_mod_is_reported_clearly():
    from conftest import FakeRconServer, LuaWorld, PASSWORD
    from factorio_agent_mcp.game import Game
    from factorio_agent_mcp.rcon import Rcon

    bare = LuaWorld(load_mod=False)
    srv = FakeRconServer(bare.run)
    try:
        rcon = Rcon("127.0.0.1", srv.port, PASSWORD, timeout=5)
        server.configure(Game(rcon), rcon)
        out = server.status()
        assert out.startswith("ERR mod_missing") and "install mod/fac_agent" in out
        rcon.close()
    finally:
        srv.close()


def test_lua_errors_inside_the_mod_become_readable_errors(world, game):
    world.exec("game.forces.player.recipes = nil")
    out = server.craft("wooden-chest")
    assert out.startswith("ERR lua_error")


def test_replies_are_valid_json_even_for_empty_tables(world, game):
    raw = world.run('/silent-command rcon.print(remote.call("fac_agent", "status"))')
    parsed = json.loads(raw)
    assert parsed["ok"] is True
