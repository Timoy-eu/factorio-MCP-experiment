"""Built-in game knowledge and working method for the model."""

INSTRUCTIONS = """You play Factorio 2.0 through tools. Start with `status` (position, inventory, next steps), call `guide` once for the working method.
Rules of thumb: act in small steps, read each answer, and check the result with `map` or `inspect` before building on it.
Never guess coordinates: use `find`, `look`, `resource_patch`, `nearest_buildable`, `can_place`. When something does not work, use `inspect`, `belt_contents`, `trace_item`, `machine_stats` to find out why. Write goals and locations into `notes`. `run_lua` is a last resort, only when absolutely necessary."""

TOPICS = {
    "method": """WORKING METHOD
1. status: read inventory and the "next:" steps.
2. Plan one small goal (e.g. "first iron plates"), do it, verify, then notes add.
3. After every build: map (around it) or inspect x y. Do not assume it works.
4. If a tool says ERR, read the hint after "try:". Do not repeat the same call.
5. Stuck for 3 tries: look at guide debugging, ask the human, or save a checkpoint before experimenting.
6. Keep coordinates in notes (tags: location, goal, lesson). They survive context resets.
7. Call read_chat now and then: the human may give instructions in the game chat. Use say to report what you do or to ask.
8. Use batch for known sequences (build, fuel, check) to save steps.
9. Build, test, then blueprint_save good layouts together with the human and set status tested.""",
    "start": """EARLY GAME (first 30 minutes)
- Hand-mine: gather coal 20, stone 10 (furnaces), iron-ore 20, wood.
- craft stone-furnace, burner-mining-drill. build_miner on iron-ore: drill feeds a furnace directly. fuel it with coal.
- Every few minutes: collect (plates), fuel again. Build 4 to 8 such miners on iron, 2 on coal, 2 on stone, 2 on copper.
- Craft by hand: iron-gear-wheel, pipe, then offshore-pump, boiler, steam-engine, small-electric-pole for power.
- Research: lab + automation-science-pack (copper plate + gear). First research: automation.
- Burner drills need fuel. Put coal drills facing each other so they feed each other.""",
    "power": """POWER
Chain: offshore-pump (on water shore) -> pipe -> boiler (needs fuel) -> pipe -> steam-engine. 1 offshore pump supports 20 boilers, 1 boiler 2 engines (900 kW each).
Use connect kind=pipe between them, then connect kind=power from the engine to the consumers (poles reach 7.5 tiles, supply area is small). Check with inspect (electric network) and overview (no_power).
Machines with status no_power: no pole nearby or the network has no generator or no fuel in the boiler.""",
    "belts": """BELTS AND INSERTERS
- connect kind=belt x1 y1 x2 y2 lays a routed belt, end_direction sets the last belt's facing. Use dry_run first to count the belts.
- Belts carry items in their arrow direction (map shows ^ > v <). Underground belts need item pairs, avoid them early.
- Inserters move items between a belt and a machine: they pick up from behind and drop to the front (facing = drop side). Check with inspect.
- Verify every line: trace_item at its start. STUCK means blocked or no consumer, "left the belt" at the right place means success.
- Mixed belts block. One belt = one item type, or one item per lane.""",
    "automation": """AUTOMATION
- Mine -> belt -> furnace column (inserter in, inserter out) -> belt of plates -> assemblers.
- Assembler: build, set_recipe, feed by inserter from a belt, output by inserter to a chest or belt.
- Gears, circuits and science packs first, then red science (automation-science-pack), later green.
- Balance: one iron drill (0.5/s electric) feeds roughly 1.6 stone furnaces. Use machine_stats to find the bottleneck: it names the status and a fix.
- Expand only after the previous stage runs. measure_flow with item shows the real production per minute.""",
    "debugging": """DEBUGGING A FACTORY
- Machine not working? machine_stats (diagnosis), or inspect x y (status, inventories, where it outputs).
- no_fuel: fuel. no_power: connect power. no_ingredients: the input belt or inserter is missing or empty (belt_contents). full_output: nothing takes the product away.
- Belt empty at the end: trace_item from the start, then look at the stuck tile with inspect and map layers=belts.
- Wrong rotation: rotate, then verify with inspect. For a drill, inspect shows "outputs into ...".
- Place failed: can_place shows the blocker and a free spot. nearest_buildable finds a free area.
- Enemies near: look shows them. Defend or move away; gun-turret needs ammo (insert).""",
    "tools": """TOOL OVERVIEW
Act: gather, craft, build, build_next_to, rotate, move_entity, pickup, insert, extract, fuel, collect, set_recipe, connect, research, launch_rocket.
See: status, look, find, map (ASCII), inspect, list_entities, inventory, resource_patch, can_place, nearest_buildable, overview.
Measure: belt_contents, trace_item, measure_flow, machine_stats, score, research_info.
Combine: batch (several tools in one call). Talk: say (chat as [Bot]), read_chat (what the human typed).
Remember: notes, blueprint_save/list/show/place/note/delete, checkpoint. For the human only: render_map, say.""",
}

ORDER = ["method", "start", "tools", "belts", "power", "automation", "debugging"]


def text(topic: str = "") -> str:
    key = topic.strip().lower()
    if key in TOPICS:
        return TOPICS[key]
    if key in ("", "all"):
        return "\n\n".join(TOPICS[k] for k in ORDER)
    return f"unknown topic '{topic}'. Topics: {', '.join(ORDER)}, or all"
