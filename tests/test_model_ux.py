"""Features that make the server easier for small local models (Qwen3.8 and similar)."""

import asyncio

from factorio_agent_mcp import planner, render, server
from factorio_agent_mcp.game import GameError


def test_action_replies_carry_a_state_footer(world, game):
    world.exec("mock.give('stone-furnace', 1); mock.give('coal', 3)")
    out = server.build("stone-furnace", 5, 5)
    first, footer = out.split("\n")[0], out.split("\n")[-1]
    assert first.startswith("built stone-furnace")
    assert footer.startswith("[state] at (") and "carry: coal 3" in footer and "next:" in footer
    # read tools stay short
    assert "[state]" not in server.inspect(5, 5)


def test_names_are_normalised(world, game):
    world.exec("mock.give('stone-furnace', 2)")
    assert server.build("Stone Furnace", 5, 5).startswith("built stone-furnace")
    assert server.build("furnace", 9, 9).startswith("built stone-furnace")
    assert server._name("stone_furnace") == "stone-furnace" and server._name("belt") == "transport-belt"
    assert server._slug("Iron Ore") == "iron-ore"


def test_repeated_failures_trigger_stop(world, game):
    for _ in range(2):
        assert server.build("stone-furnace", 5, 5).startswith("ERR no_item")
    third = server.build("stone-furnace", 5, 5)
    assert third.startswith("STOP: this exact build call failed 3 times"), third
    # a success resets the guard
    world.exec("mock.give('stone-furnace', 1)")
    assert server.build("stone-furnace", 5, 5).startswith("built")
    assert server.build("stone-furnace", 9, 9).startswith("ERR no_item")


def test_same_tool_failing_with_different_args_also_stops(world, game):
    outs = [server.build("stone-furnace", 5 + 3 * i, 5) for i in range(4)]
    assert outs[-1].startswith("STOP: build failed 4 times in a row"), outs[-1]


def test_hints_are_ready_to_copy_calls():
    err = GameError("blocked", "cannot place", {"entity": "stone-furnace", "suggestion": {"x": 7, "y": 8}})
    assert "try: build entity=stone-furnace x=7 y=8" in render.error_text(err)
    assert "gather item=stone count=5" in render.error_text(GameError("missing", "m", {"item": "stone", "count": 5}))
    assert "craft item=iron-gear-wheel count=2" in render.error_text(
        GameError("missing", "m", {"item": "iron-gear-wheel", "count": 2}))
    assert "build_miner ore=iron-ore" in render.error_text(GameError("missing", "m", {"item": "iron-plate", "count": 4}))


def test_batch_coerces_string_arguments_and_shows_signature(world, game):
    world.exec("mock.give('stone-furnace', 1); mock.give('coal', 10)")
    out = server.batch([
        {"tool": "build", "args": {"entity": "furnace", "x": "5", "y": "5"}},
        {"tool": "fuel", "args": '{"x": "5", "y": "5", "per": "3"}'},
    ])
    assert "1. build: built stone-furnace" in out and "2. fuel: fueled" in out, out
    assert out.count("[state]") == 1 and out.rstrip().split("\n")[-1].startswith("[state]")
    bad = server.batch([{"tool": "build", "args": {"thing": "x"}}])
    assert "bad_args" in bad and "try: build(entity, x, y, direction='auto')" in bad
    # actions as a JSON string and inline args
    out = server.batch('[{"tool": "status"}]')
    assert "1. status:" in out
    out = server.batch([{"tool": "find", "what": "tree"}])
    assert "1. find:" in out


def test_profiles_change_the_tool_list():
    try:
        core = server.apply_profile("core")
        assert "build" in core and "goal" in core and "blueprint" not in core and "score" not in core
        assert len(core) < 30
        tools = asyncio.run(server.mcp.list_tools())
        assert {t.name for t in tools} == set(core)
        assert "blueprint" not in server.guide("tools") and "build_miners" in server.guide("tools")
        full = server.apply_profile("full")
        assert "blueprint" in full and len(full) > len(core)
    finally:
        server.apply_profile("full")


def test_goal_tracker(world, game, tmp_path, monkeypatch):
    monkeypatch.setenv("FACTORIO_MCP_DATA_DIR", str(tmp_path))
    assert server.goal().startswith("no goal set")
    out = server.goal("set", "automate iron", "4 miners; belt to chest; check with trace_item")
    assert "[0/3] next step 1: 4 miners" in out
    assert "goal: automate iron [0/3]" in server.status()
    world.exec("mock.give('stone-furnace', 1)")
    assert "next step 1: 4 miners" in server.build("stone-furnace", 5, 5).split("\n")[-1]
    assert "step 1 done" in server.goal("done") and "[1/3]" in server._goal_line()
    assert "2. [ ] belt to chest" in server.goal("show")
    server.goal("done", step=2)
    server.goal("done", step=3)
    assert "all 3 steps done" in server._goal_line()
    assert server.goal("clear") == "goal cleared" and server._goal_line() == ""


def test_build_miners_builds_several(world, game):
    world.exec("""
      mock.add_patch('iron-ore', 20, 20, 30, 30, 100)
      mock.give('burner-mining-drill', 2); mock.give('stone-furnace', 2); mock.give('coal', 40)
    """)
    out = server.build_miners("iron", 3)
    assert out.startswith("built 2/3 miners on iron-ore"), out
    assert "ERR no_item" in out
    assert world.eval("mock.entity_count('burner-mining-drill')") == 2
    assert server.build_miners("iron-ore", 1).startswith("ERR no_item")


def test_planner_covers_power_lab_and_problems():
    placed = {"burner-mining-drill": {"n": 4}, "stone-furnace": {"n": 4}}
    steps = planner.next_steps({"coal": 50, "stone": 20, "iron-plate": 50}, placed, None, limit=5)
    assert any("prepare power" in s for s in steps), steps
    steps = planner.next_steps({"coal": 50, "stone": 20, "offshore-pump": 1, "boiler": 1, "steam-engine": 1},
                               placed, None, limit=5)
    assert any("build power" in s for s in steps), steps
    placed2 = dict(placed, **{"steam-engine": {"n": 1}, "lab": {"n": 1}})
    steps = planner.next_steps({"coal": 50, "stone": 20}, placed2, None, limit=5)
    assert any("automation-science-pack" in s for s in steps), steps
    placed3 = dict(placed, **{"assembling-machine-1": {"n": 1, "status": {"no_power": 1}}})
    steps = planner.next_steps({"coal": 50, "stone": 20}, placed3, None, limit=5)
    assert any("kind=power" in s for s in steps), steps
