"""Built-in game knowledge and working method for the model."""

INSTRUCTIONS = """You play Factorio 2.0 through tools, together with a human. Start with `status` (position, inventory, next steps), then call `guide` once for the working method.
Rules of thumb: act in small steps, read every reply, and verify the result with `map` or `inspect` before you build on it. A reply starting with ERR names the problem and a fix after "try:"; never repeat the same failing call.
Never guess coordinates: use `find`, `look`, `resource_patch`, `nearest_buildable`, `can_place`. When something does not work, use `inspect`, `belt_contents`, `trace_item`, `machine_stats` to find out why. Write goals and locations with `notes`, check `read_chat` now and then for instructions from the human. `run_lua` is a last resort, only when no other tool can do the job."""

TOPICS = {
    "method": """WORKING METHOD
1. status: read your inventory and the "next:" steps.
2. Pick one small goal (e.g. "first iron plates"), do it, verify it, then save progress with notes action=add.
3. After every build: map (around it) or inspect x y. Never assume it works.
4. A reply starting with ERR: read the hint after "try:" and follow it. Do not repeat the same call.
5. Stuck after 3 tries: read guide topic=debugging, ask the human with say, or save a checkpoint before experimenting.
6. Keep coordinates in notes (tag = location, goal or lesson). Notes survive context resets; read them with notes action=list.
7. Call read_chat now and then: the human may give instructions in the game chat. Use say to report what you do or to ask.
8. Use batch for known sequences (build, fuel, check) to save steps.
9. Good layout? blueprint_save it, test it, then blueprint_note status=tested. Reuse it with blueprint_place.""",
    "start": """EARLY GAME (first 30 minutes)
- Check status first: freeplay starts with a burner-mining-drill, a stone-furnace and a few iron plates.
- gather coal 20, stone 10 (5 per stone-furnace), iron-ore 20. Wood also works as fuel.
- First plates: build a stone-furnace, insert iron-ore, fuel it, wait, collect.
- build_miner iron-ore: a burner drill drops straight into a furnace and both get coal. It needs a burner-mining-drill (3 gears, 3 iron plates, 1 stone-furnace) and a stone-furnace.
- Every few minutes: collect (plates), fuel again. Aim for 4 to 8 miners on iron, 2 on copper, 2 on stone, 2 on coal.
- Craft by hand: iron-gear-wheel, pipe, then offshore-pump, boiler, steam-engine, small-electric-pole for power (guide topic=power).
- Research: build a lab, power it, insert automation-science-pack (1 copper-plate + 1 iron-gear-wheel). First research: automation.
- Burner drills need fuel. Two coal drills facing each other feed each other.""",
    "power": """POWER
Chain: offshore-pump (on the water shore) -> pipe -> boiler (needs fuel) -> pipe -> steam-engine. 1 offshore pump supplies 20 boilers, 1 boiler feeds 2 steam engines (900 kW each).
Use connect kind=pipe between them, then connect kind=power from the steam engine to the consumers. small-electric-pole: wires reach 7.5 tiles, but it only powers machines in the 5x5 area around it.
Check with inspect (electric network) and overview (no_power). no_power means: no pole close enough, no generator in the network, or the boiler has no fuel or water.""",
    "belts": """BELTS AND INSERTERS
- connect kind=belt x1 y1 x2 y2 lays a routed belt; end_direction sets the facing of the last belt. Use dry_run=true first to count the belts.
- Belts carry items in their arrow direction (map shows ^ > v <). Underground belts need pairs, avoid them early.
- Inserters move items from one side to the other (belt -> machine, machine -> belt or chest). Give them an explicit direction (auto just takes the first one that fits), then inspect: "outputs into ..." must name the target you want. If it names the wrong side, rotate to the opposite direction.
- Verify every line: trace_item at its start. STUCK means blocked or nothing takes the items; "left the belt" at the expected place means success.
- Mixed belts block. One belt = one item type, or one item per lane.""",
    "automation": """AUTOMATION
- Mine -> belt -> furnace column (inserter in, inserter out) -> belt of plates -> assemblers.
- Assembler: build, set_recipe, feed it by inserter from a belt, output by inserter to a chest or belt. It needs power.
- Order: automate iron-gear-wheel, then red science (automation-science-pack), then green science (logistic-science-pack: inserter + transport-belt) and electronic-circuit.
- Ratios: an electric drill (0.5 ore/s) feeds about 1.6 stone furnaces, a burner drill (0.25 ore/s) about 0.8. machine_stats finds the bottleneck and names a fix.
- Expand only when the previous stage runs. measure_flow with item shows the real production per minute.""",
    "debugging": """DEBUGGING A FACTORY
- Machine not working? machine_stats (diagnosis), or inspect x y (status, inventories, where it outputs). overview lists every problem in an area.
- no_fuel: fuel. no_power: connect kind=power, see guide topic=power. no_ingredients: the input belt or inserter is missing or empty (belt_contents). full_output: nothing takes the product away.
- Belt empty at the end: trace_item from the start, then look at the stuck tile with inspect and map layers=belts.
- Wrong direction: rotate, then verify with inspect. For drills and inserters inspect shows "outputs into ...".
- Place failed: can_place shows the blocker and a free spot. nearest_buildable finds a free area.
- Enemies near (look shows them): move away or defend; a gun-turret needs ammo (insert firearm-magazine).""",
    "tools": """TOOL OVERVIEW
Act: gather, craft, build, build_next_to, build_miner, rotate, move_entity, move_to, pickup, insert, extract, fuel, collect, set_recipe, connect, research, launch_rocket, set_game_speed.
See: status, look, find, map (ASCII), inspect, list_entities, inventory, resource_patch, can_place, nearest_buildable, overview.
Measure: belt_contents, trace_item, measure_flow, machine_stats, score, research_info.
Combine: batch (several tools in one call). Talk: say (chat as [Bot]), read_chat (what the human typed).
Remember: notes, checkpoint, blueprint_save, blueprint_list, blueprint_show, blueprint_place, blueprint_note, blueprint_delete.
For the human only: render_map (you cannot see the picture, use map yourself).""",
}

ORDER = ["method", "start", "tools", "belts", "power", "automation", "debugging"]


def text(topic: str = "") -> str:
    key = topic.strip().lower()
    if key in TOPICS:
        return TOPICS[key]
    if key in ("", "all"):
        return "\n\n".join(TOPICS[k] for k in ORDER)
    return f"unknown topic '{topic}'. Topics: {', '.join(ORDER)}, or all"
