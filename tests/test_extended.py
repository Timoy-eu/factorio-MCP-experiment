"""Extended tools: placement helpers, inspection, connect, snapshot and ASCII map."""

from factorio_agent_mcp import server


def test_can_place_and_blocked(world, game):
    assert server.can_place("wooden-chest", 5.5, 5.5).startswith("yes")
    world.exec("mock.add_entity('wooden-chest', 5.5, 5.5)")
    out = server.can_place("wooden-chest", 5.5, 5.5)
    assert out.startswith("no") and "nearest free spot" in out


def test_nearest_buildable_on_ore(world, game):
    world.exec("mock.add_patch('iron-ore', 20, 20, 26, 26, 100)")
    out = server.nearest_buildable("burner-mining-drill", resource="iron-ore")
    assert out.startswith("free 2x2") and "ore tiles" in out


def test_pickup_and_inventory_and_inspect(world, game):
    world.exec("mock.add_entity('wooden-chest', 5.5, 5.5); mock.first('wooden-chest').insert{name='coal', count=7}")
    assert "wooden-chest (container) at (5.5,5.5)" in server.inspect(5.5, 5.5)
    assert "coal 7" in server.inventory(5.5, 5.5)
    out = server.pickup(5.5, 5.5)
    assert "picked up wooden-chest" in out
    assert world.eval("mock.inventory_count('coal')") == 7
    assert "your inventory" in server.inventory()


def test_extract_from_furnace(world, game):
    world.exec("mock.add_entity('stone-furnace', 6, 6); mock.first('stone-furnace').output.insert{name='iron-plate', count=5}")
    assert "took 5 iron-plate" in server.extract(6, 6, "iron-plate", 5)


def test_move_entity(world, game):
    world.exec("mock.add_entity('wooden-chest', 5.5, 5.5)")
    out = server.move_entity(5.5, 5.5, 9.5, 9.5)
    assert "(9.5,9.5)" in out, out


def test_build_next_to(world, game):
    world.exec("mock.add_entity('stone-furnace', 10, 10); mock.give('wooden-chest', 1)")
    out = server.build_next_to("wooden-chest", 10, 10, "east")
    assert out.startswith("built wooden-chest"), out


def test_resource_patch_and_move(world, game):
    world.exec("mock.add_patch('coal', 20, 20, 24, 23, 50)")
    out = server.resource_patch("coal")
    assert "20 tiles" in out and "1000 total" in out
    assert "you are now at" in server.move_to(30, 30)


def test_connect_belt_dry_run_and_real(world, game):
    world.exec("mock.give('transport-belt', 3)")
    dry = server.connect("belt", 0, 0, 10, 0, dry_run=True)
    assert "needs" in dry and "missing" in dry
    world.exec("mock.give('transport-belt', 20)")
    out = server.connect("belt", 0.5, 0.5, 8.5, 0.5, end_direction="east")
    assert out.startswith("laid 9"), out
    listing = server.list_entities("transport-belt")
    assert "belt line of 9 pieces" in listing, listing


def test_connect_belt_routes_around_obstacle(world, game):
    world.exec("mock.give('transport-belt', 40); mock.add_entity('stone-furnace', 4, 0)")
    out = server.connect("belt", 0.5, 0.5, 8.5, 0.5)
    assert out.startswith("laid"), out
    assert world.eval("mock.entity_count('transport-belt')") > 9


def test_connect_power(world, game):
    world.exec("mock.give('small-electric-pole', 10)")
    out = server.connect("power", 0, 0, 20, 0)
    assert out.startswith("laid"), out
    assert "WARNING" not in out
    assert "power network" in server.list_entities("small-electric-pole")


def test_connect_missing_items(world, game):
    assert server.connect("belt", 0.5, 0.5, 5.5, 0.5).startswith("ERR missing")
    assert server.connect("rail", 0, 0, 1, 1).startswith("ERR bad_kind")


def test_score_and_research_info(world, game):
    assert "researched" in server.score()
    assert "logistics: 50" in server.research_info("logistics")
    assert server.research_info("nonsense").startswith("ERR unknown_tech")


def test_ascii_map(world, game):
    world.exec("""
      mock.add_patch('iron-ore', 3, 2, 5, 3, 100)
      mock.add_water(8, 1); mock.add_tree(7.5, 4.5)
      mock.add_entity('transport-belt', 0.5, 0.5, 4)
      mock.add_entity('transport-belt', 1.5, 0.5, 8)
      mock.add_entity('stone-furnace', 10, 10)
      mock.give('wooden-chest', 1)
    """)
    out = server.map(0, 0, 14, 14)
    assert ">" in out and "v" in out and "iii" in out and "~" in out and "t" in out
    assert out.split("legend:")[0].count("F") == 4  # 2x2 furnace footprint
    assert "@" in out and "legend:" in out
    only_belts = server.map(0, 0, 14, 14, layers="belts")
    assert "F" not in only_belts and "i" not in only_belts.split("legend:")[0].split("\n", 1)[1]
    assert server.map(0, 0, 500, 500).startswith("ERR too_large")
    assert "@" in server.map()


def test_svg_and_render_map(world, game, tmp_path, monkeypatch):
    import urllib.request
    monkeypatch.setenv("FACTORIO_MCP_RENDER_DIR", str(tmp_path))
    monkeypatch.setenv("FACTORIO_MCP_VIEWER_PORT", "0")
    world.exec("""
      mock.add_patch('copper-ore', 3, 6, 8, 9, 100); mock.add_water(14,1); mock.add_tree(11.5,4.5)
      for i=0,8 do mock.add_entity('transport-belt', 0.5+i, 0.5, 4) end
      mock.add_entity('stone-furnace', 12, 8); mock.add_entity('small-electric-pole', 10.5,10.5)
      mock.add_entity('small-electric-pole', 14.5,10.5)
    """)
    out = server.render_map(0, 0, 20, 14)
    assert "picture saved" in out
    svg = (tmp_path / "latest.svg").read_text()
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    assert "stone-furnace" in svg and "copper-ore" in svg and "polyline" in svg
    import xml.dom.minidom
    xml.dom.minidom.parseString(svg)  # well formed

    from factorio_agent_mcp.viewer import Viewer
    v = Viewer(server._snapshot_for, 0)
    try:
        page = urllib.request.urlopen(v.url).read().decode()
        assert "Factorio Viewer" in page
        body = urllib.request.urlopen(v.url + "map.svg?radius=10&scale=12").read().decode()
        assert body.startswith("<svg")
        body = urllib.request.urlopen(v.url + "map.svg?x1=0&y1=0&x2=10&y2=10").read().decode()
        assert "<svg" in body
    finally:
        v.close()


def test_blueprint_roundtrip(world, game, tmp_path, monkeypatch):
    monkeypatch.setenv("FACTORIO_MCP_DATA_DIR", str(tmp_path))
    world.exec("""
      mock.add_entity('stone-furnace', 11, 11)
      mock.add_entity('transport-belt', 10.5, 13.5, 4)
      mock.add_entity('transport-belt', 11.5, 13.5, 4)
      mock.add_entity('small-electric-pole', 13.5, 11.5)
    """)
    assert server.blueprint_save("Smelt Row", 10, 10, 15, 15, "furnace with belt").startswith("saved")
    assert "smelt-row" in server.blueprint_list()
    shown = server.blueprint_show("smelt-row")
    assert "F" in shown and ">" in shown
    rot = server.blueprint_show("smelt-row", 90)
    assert "v" in rot
    # empty area is rejected
    assert server.blueprint_save("nothing", 100, 100, 105, 105).startswith("ERR empty")
    # place far away, first without items
    assert server.blueprint_place("smelt-row", 40, 40).startswith("ERR missing")
    world.exec("mock.give('stone-furnace',1); mock.give('transport-belt',2); mock.give('small-electric-pole',1)")
    assert "all spots free" in server.blueprint_place("smelt-row", 40, 40, dry_run=True)
    out = server.blueprint_place("smelt-row", 40, 40)
    assert out.startswith("placed 4/4"), out
    assert world.eval("mock.entity_count('transport-belt')") == 4
    out = server.blueprint_note("smelt-row", "needs coal first", "tested")
    assert "[tested]" in out and "needs coal first" in server.blueprint_show("smelt-row")
    assert server.blueprint_delete("smelt-row").startswith("deleted")


def test_blueprint_rotation_math():
    from factorio_agent_mcp import blueprints as b
    assert b.rotate_dir("north", 1) == "east" and b.rotate_dir("west", 1) == "north"
    assert b.rotate_offset(1, 0, 1) == (0, 1)  # east -> south
    bp = {"width": 4, "height": 2, "entities": []}
    assert b.anchor_shift(bp, 1) == (2, 0)


def test_notes_overview_checkpoint(world, game, tmp_path, monkeypatch):
    monkeypatch.setenv("FACTORIO_MCP_DATA_DIR", str(tmp_path))
    assert server.notes("add", "iron mine at 40,12", "location").startswith("note #1")
    assert "iron mine" in server.notes("list", tag="location")
    assert server.notes("remove", note_id=1) == "removed"
    world.exec("mock.add_entity('burner-mining-drill', 5, 5)")
    out = server.overview()
    assert "1 buildings" in out and "no_fuel" in out
    assert "saved game" in server.checkpoint("test")
    assert world.eval("mock.world.saved") == "test"


def test_run_lua_available_with_warning(world, rcon_server):
    from factorio_agent_mcp.game import Game
    from factorio_agent_mcp.rcon import Rcon
    assert "ABSOLUTELY" in (server.run_lua.__doc__ or "").upper() or "ONLY when it is absolutely necessary" in server.run_lua.__doc__
    r = Rcon("127.0.0.1", rcon_server.port, "secret")
    server.configure(Game(r), r)
    try:
        assert server.run_lua("rcon.print(1+1)") == "2"
    finally:
        r.close()


def _clock(world, monkeypatch):
    """Sleeping in a test advances the fake world instead of waiting."""
    monkeypatch.setattr(server, "_sleep", lambda seconds: world.exec(f"mock.advance({int(seconds * 60)})"))


def _belt_line(world, n=6, direction=4):
    world.exec(f"for i=0,{n - 1} do mock.add_entity('transport-belt', 0.5+i, 0.5, {direction}) end")


def test_belt_contents(world, game):
    _belt_line(world, 4)
    assert "Belt is empty" in server.belt_contents(0, 0, 10, 2)
    world.exec("mock.give('wood', 3); mock.world.entities[1].get_transport_line(1).insert_at_back{name='iron-plate', count=3}")
    out = server.belt_contents(0, 0, 10, 2)
    assert "3 iron-plate" in out and "3 empty" in out
    assert "no belts" in server.belt_contents(50, 50, 60, 60)


def test_trace_item_stuck_at_end(world, game, monkeypatch):
    _clock(world, monkeypatch)
    _belt_line(world, 6)
    world.exec("mock.give('wood', 1)")
    out = server.trace_item(0.5, 0.5, "wood", 30)
    assert out.startswith("STUCK") and "(5.5,0.5)" in out, out
    assert world.eval("mock.inventory_count('wood')") == 0


def test_trace_item_left_belt_and_errors(world, game, monkeypatch):
    _clock(world, monkeypatch)
    _belt_line(world, 6)
    world.exec("mock.give('wood', 1)")
    # an inserter-like pickup: remove the tracer from the last belt as soon as it arrives
    monkeypatch.setattr(server, "_sleep", lambda s: world.exec(
        "mock.advance(%d); mock.world.entities[6].get_transport_line(1).remove{name='wood', count=1}" % int(s * 60)))
    out = server.trace_item(0.5, 0.5, "wood", 30)
    assert "left the belt" in out, out
    assert server.trace_item(0.5, 0.5, "wood").startswith("ERR no_item")
    world.exec("mock.give('wood', 1)")
    assert server.trace_item(20.5, 20.5, "wood").startswith("ERR no_belt")


def test_machine_stats_diagnosis(world, game, monkeypatch):
    _clock(world, monkeypatch)
    world.exec("""
      mock.add_entity('stone-furnace', 10, 10)
      local f = mock.add_entity('stone-furnace', 14, 10)
      f.insert{name='coal', count=5}
    """)
    out = server.machine_stats(10, 10, 15, 6)
    assert "2 machines" in out and "no_fuel" in out and "fuel tool" in out
    assert "working 100%" in out


def test_measure_flow_machine_and_item(world, game, monkeypatch):
    _clock(world, monkeypatch)
    world.exec("local f = mock.add_entity('stone-furnace', 10, 10); f.insert{name='coal', count=5}")
    mon = monkeypatch
    mon.setattr(server, "_sleep", lambda s: world.exec(
        "mock.advance(%d); mock.first('stone-furnace').products_finished = (mock.first('stone-furnace').products_finished or 0) + 1; "
        "mock.world.production['iron-plate'] = (mock.world.production['iron-plate'] or 0) + 2" % int(s * 60)))
    out = server.measure_flow(10, 10, 6, "iron-plate")
    assert "finished" in out and "/min" in out and "iron-plate:" in out, out
    _belt_line(world, 3)
    assert "belt tile holds" in server.measure_flow(1.5, 0.5, 3)


def test_guide_topics():
    assert "WORKING METHOD" in server.guide("method")
    full = server.guide()
    for word in ("EARLY GAME", "POWER", "BELTS", "AUTOMATION", "DEBUGGING", "TOOL OVERVIEW"):
        assert word in full
    assert server.guide("nonsense").startswith("unknown topic")
    # every tool named in the guide really exists
    import re
    names = {t for t in re.findall(r"\b([a-z_]{4,})\b", server.guide("tools"))}
    registered = set(server.mcp._tool_manager._tools) if hasattr(server.mcp, "_tool_manager") else None
    if registered:
        mentioned = {n for n in names if "_" in n} - {"blueprint_save", "list", "show", "place", "note", "delete"}
        assert mentioned <= registered, mentioned - registered


def test_batch_runs_in_order_and_stops(world, game):
    world.exec("mock.give('stone-furnace', 1)")
    acts = [
        {"tool": "build", "args": {"entity": "stone-furnace", "x": 5, "y": 5}},
        {"tool": "inspect", "args": {"x": 5, "y": 5}},
        {"tool": "build", "args": {"entity": "stone-furnace", "x": 9, "y": 9}},  # no item left
        {"tool": "status", "args": {}},
    ]
    out = server.batch(acts)
    assert "1. build: built stone-furnace" in out and "2. inspect: stone-furnace" in out
    assert "3. build: ERR no_item" in out and "stopped after action 3" in out and "4. status" not in out
    out = server.batch(acts, stop_on_error=False)
    assert "4. status" in out


def test_batch_rejects_bad_input(world, game):
    assert server.batch([]).startswith("ERR no_actions")
    assert "not_allowed" in server.batch([{"tool": "batch", "args": {}}])
    assert "not_allowed" in server.batch([{"tool": "nonsense"}])
    assert "bad_args" in server.batch([{"tool": "build", "args": {"entity": "x"}}])
    assert server.batch([{"tool": "status"}] * 30).startswith("ERR too_many")


def test_bot_chat_out_and_in(world, game, monkeypatch):
    world.exec("mock.give('stone-furnace', 1)")
    server.build("stone-furnace", 5, 5)
    msgs = world.eval("table.concat(mock.world.messages, '|')")
    assert "[Bot] builds stone-furnace at (5, 5)" in msgs
    server.say("hallo")
    assert "[Bot] hallo" in world.eval("table.concat(mock.world.messages, '|')")
    # failures are not announced, and chat can be switched off
    before = world.eval("#mock.world.messages")
    server.build("stone-furnace", 8, 8)
    assert world.eval("#mock.world.messages") == before
    monkeypatch.setenv("FACTORIO_MCP_CHAT", "0")
    world.exec("mock.give('stone-furnace', 1)")
    server.build("stone-furnace", 12, 12)
    assert world.eval("#mock.world.messages") == before
    # human to bot
    assert server.read_chat() == "no new chat messages"
    world.exec("mock.chat('Timo', 'bau bitte mehr Oefen')")
    assert server.read_chat() == "Timo: bau bitte mehr Oefen"
    assert server.read_chat() == "no new chat messages"


def test_selftest_in_mock(world, game):
    world.exec("mock.add_patch('iron-ore', 60, 60, 66, 66, 100); mock.add_water(-40, -40); mock.add_tree(70, 70)")
    out = server.selftest()
    print(out)
    assert "result:" in out
    assert "FAIL" not in out.replace("0 failed", ""), out
    # cleanup: no belts or poles left, inventory empty again
    assert world.eval("mock.entity_count('transport-belt')") == 0
    assert world.eval("mock.entity_count('small-electric-pole')") == 0
    assert world.eval("mock.inventory_count('iron-plate')") == 0
