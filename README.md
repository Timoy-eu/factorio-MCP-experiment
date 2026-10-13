# factorio-agent-mcp

MCP server that lets even small local models play Factorio 2.0. Instead of 70 low-level tools it offers
47 high-level actions (13 core actions plus FLE parity, maps, blueprints), or 27 in the `core` profile for small models. The server handles planning, orientation and verification;
the model only has to call the tools. Background and sources: `FINDINGS.md`.

```
Model <-> MCP client <-stdio-> factorio-agent-mcp (Python) <-RCON-> Factorio + mod fac_agent (Lua)
```

## Important: test status

Everything is tested against a mock of the Factorio API (`pytest`): Python, the RCON protocol
(including multi-part replies), the real mod Lua code, orientation search, read-back, recursive
crafting. The self-test has been run once against a real Factorio 2.0.77 server: 14 of 16 checks passed,
the assembler rotation failure is fixed (assemblers only have a direction with fluid recipes), the drill check
was skipped (no ore near the sandbox). Most tools have not been used in a real game yet; expect small
adjustments (see "Known uncertainties").

## Installation

Step by step with OpenCode on Linux: **`INSTALL_OPENCODE.md`** (with examples in `examples/`).

Short version:

1. Install the mod: put `dist/fac_agent_0.3.0.zip` into the Factorio `mods/` folder
   (or copy the folder `mod/fac_agent`). The mod requires Factorio 2.0.
2. Start a server with RCON:
   `factorio --start-server my-map.zip --rcon-port 27015 --rcon-password secret`
   (Note: commands via `/silent-command` disable achievements.)
3. Install the MCP server: `pip install -e .` (Python 3.10+, package `mcp`).
4. Add it to your MCP client (example `mcp.example.json`):

```json
{
  "mcpServers": {
    "factorio": {
      "command": "factorio-agent-mcp",
      "env": {
        "FACTORIO_RCON_HOST": "127.0.0.1",
        "FACTORIO_RCON_PORT": "27015",
        "FACTORIO_RCON_PASSWORD": "secret"
      }
    }
  }
}
```

The raw `run_lua` tool is included. Its description tells the model to use it only as a last resort, when no other tool can do the job. `FACTORIO_MCP_DISABLE_LUA=1` removes it.

## Tools

| Tool | Purpose |
|---|---|
| `status` | position, inventory, buildings with status, recommended next steps |
| `look` | scan the surroundings (ore, trees, rocks, water, own buildings, enemies) |
| `find` | nearest ore, tree, rock, water or building |
| `gather` | mine by hand (wood, stone, coal, iron, copper), walks there automatically |
| `craft` | hand-craft including intermediate products, `preview` shows the recipe |
| `build` | place a building; direction `auto` takes the first one that fits, falls back to a free spot if blocked |
| `rotate` | rotate a building, the result is read back (assemblers are recreated) |
| `build_miner` | drill on ore that feeds a furnace directly, the side is found automatically |
| `fuel` | add fuel (one building or all burners within 30 tiles) |
| `collect` | take finished plates and bricks out of furnaces and machines |
| `insert` | put items into a building |
| `set_recipe` | set an assembler recipe |
| `research` | list or queue research |

### Extended tools (FLE parity and more)

| Tool | Purpose | FLE equivalent |
|---|---|---|
| `can_place` | checks space, names blockers and the nearest free spot | `can_place_entity` |
| `nearest_buildable` | nearest free area, optionally on ore | `nearest_buildable` |
| `build_next_to` | build right next to a building (side, spacing) | `place_entity_next_to` |
| `pickup` | pick up a building | `pickup_entity` |
| `move_entity` | move a building (rolls back on failure) | `shift_entity` |
| `extract` | take items out of a building | `extract_item` |
| `inventory` | own inventory or that of a building | `inspect_inventory` |
| `inspect` | details: direction, status, recipe, inventories, output target, power | `get_entity` |
| `list_entities` | nearby buildings plus connected belt, pipe and power networks | `get_entities` |
| `resource_patch` | size, amount, center, bounding box of an ore patch | `get_resource_patch` |
| `move_to` | go to a position | `move_to` |
| `connect` | lay belts, pipes, power poles or **rails** (A* around obstacles), `dry_run` counts the pieces. `kind=rail` routes straight, diagonal and curved pieces, continues an open rail end, removes trees in the way (`keep_trees=true` avoids that) and lets the game verify the connection | `connect_entities`, `get_connection_amount` |
| `rail_end` | open rail ends near a point: where a line stops and which way it points (start of the next `connect kind=rail`) | |
| `research_info` | progress and missing science packs | `get_research_progress` |
| `score` | production statistics | `score` |
| `launch_rocket` | launch the rocket | `launch_rocket` |
| `say`, `set_game_speed` | chat message, game speed | `send_message`, `sleep` (replacement) |
| `craft`, `gather`, `build`, `rotate`, `insert`, `set_recipe`, `research`, `find`, `look` | see above | `craft_item`, `harvest_resource`, `place_entity`, `rotate_entity`, `insert_item`, `set_entity_recipe`, `set_research`, `nearest`, `print` |

Not adopted: having the model write Python code (FLE REPL). Instead there are fixed tools,
with `run_lua` as a last resort.

### Self-test

`selftest` checks the mod's assumptions about the Factorio API in a free sandbox area and cleans up afterwards.
Run it on the first start in real Factorio and report the `FAIL` lines. Details in `INSTALL_OPENCODE.md`.

### Game guide for the model

On connect the server sends short `instructions` (working method, rules). The `guide` tool
holds the detailed knowledge: working method, early game, belts and inserters, power, automation,
debugging and a tool overview (`guide topic=belts` etc.). Some local clients ignore `instructions`,
so `status` also points to it and the model can call `guide` itself. You can edit the content
in `src/factorio_agent_mcp/guide.py`. For a local model it also helps to copy the
`INSTRUCTIONS` into the client's system prompt.

### Chat and batch

| Tool | Purpose |
|---|---|
| `say` | message as `[Bot]` in the game chat (light blue) |
| `read_chat` | reads new chat lines that players typed in the game, so the human can give the bot instructions |
| `batch` | several tools in one call (`[{"tool":"build","args":{...}}, ...]`), stops at the first error, at most 25 actions |

The bot briefly announces successful actions (building, laying, crafting, research, placing blueprints, ...)
in the game chat. `FACTORIO_MCP_CHAT=0` turns this off.

### Maps

| Tool | Purpose |
|---|---|
| `map` | ASCII map for the model, any area between two corners (max. 100x60), belts as arrows `^ > v <`, machines as letters, ore `i c k s`, `t` tree, `~` water, `@` you, rails `| - / \`, signals `! ?`, train stop `Z`, locomotive `M`, wagon `w`. `layers` filters (`belts,pipes,power,rails,machines,ore,trees,water,enemies`) |
| `render_map` | realistic SVG for the **human** (terrain, ore density, trees, machines with status ring, belts with direction, pipes, poles with wires, legend). Saves to `renders/` and starts a live viewer at `http://127.0.0.1:8765/` (follows the agent, zoom, free area). `FACTORIO_MCP_VIEWER_PORT=0` turns the viewer off |

### Watching items and machines

| Tool | Purpose |
|---|---|
| `belt_contents` | what lies on the belts in an area (items, fill level, empty pieces), with a hint about empty or backed-up belts |
| `trace_item` | puts an item (wood is best) on a belt and follows it: travel time, distance, "STUCK" with location, or "left the belt". Proves that a belt is connected and runs the right way |
| `measure_flow` | measures a machine (crafts per minute, share of working time) or a belt (average load) over N seconds of game time; with `item` the production of the whole factory per minute |
| `machine_stats` | observes all machines in a radius, shows working share and rate per machine and a diagnosis (no fuel, no power, missing input, blocked output) |

Measuring works through repeated queries (`sample`, `trace_probe`) from Python; the mod needs
no tick handler for it. Rates are computed from game ticks, not real time. The throughput of a
belt is an estimate (average load), not an exact count. Not yet checked against real Factorio:
`LuaTransportLine.insert_at_back`, `get_item_count` on belt lines and `products_finished`.

### Model and human working together

| Tool | Purpose |
|---|---|
| `blueprint` | `action=save` an area as a blueprint (file `factorio-data/blueprints/<name>.json`, editable by hand), `list`, `show` as ASCII (also rotated), `place` with rotation 0/90/180/270 and `dry_run`, `note` (notes and status `draft/tested`), `delete` |
| `goal` | current goal with a checklist (`action=set text=... steps="a; b; c"`, `done`, `show`, `clear`), shown in `status` and after every action |
| `notes` | persistent notebook (goals, coordinates, lessons), survives context loss |
| `overview` | count of all buildings and everything that is not running (no fuel, no power, ...) |
| `checkpoint` | save the game so the human can load it later |

Blueprints are deliberately not pre-made. The model builds something, tests it, saves it,
and you improve it together through notes and status. The folder is set via
`FACTORIO_MCP_DATA_DIR` (default `factorio-data`).

Replies are short texts with a suggested action on errors, for example
`ERR blocked: cannot place stone-furnace at 10,5 | try: build entity=stone-furnace x=12 y=5`.

### Help for small models

- **Profiles:** `FACTORIO_MCP_PROFILE=core` offers 27 tools (about 2,900 tokens of descriptions) instead of 47
  (about 5,300). `full` is the default.
- **State line:** every action reply ends with `[state] at (x,y) | carry: ... | next: ...` (or the current goal step),
  so the model rarely needs an extra `status` call.
- **Copyable hints:** errors end with `try:` followed by a call with parameters (`build entity=... x=... y=...`,
  `gather item=coal count=20`).
- **Loop guard:** the third identical failing call, or the fourth failure of the same tool in a row, gets a
  `STOP:` reply that tells the model to change its approach.
- **Lenient names and arguments:** `Stone Furnace`, `stone_furnace` and `furnace` all mean `stone-furnace`;
  inside `batch`, numbers sent as text are converted and wrong arguments return the correct signature.
- **Bigger steps:** `build_miners ore=iron-ore count=4` builds several fueled drill-furnace pairs in one call; the
  planner in `status` now also covers power, the lab, the first research and machines with `no_power`/`full_output`.
- **Example session** in `examples/AGENTS.md`: a short, realistic sequence of calls; examples work better than rule lists.
- **Eval runner:** `factorio-agent-eval` lets a model play fixed scenarios and logs success, steps, malformed calls,
  ERR/STOP replies and tokens (see `INSTALL_OPENCODE.md`, section 11).

## Design decisions for small models

- Few tools, clear names, short descriptions.
- The server solves directions (`auto`), every placement and rotation is read back.
- `status` contains rule-based planning (`src/factorio_agent_mcp/planner.py`), so the
  model does not need to keep a build order in mind.
- Errors name the cause and the next step instead of just "failed".
- Movement (teleport) and mining (instant) are deliberately simplified. This is not "honest"
  play. To change that, adapt `move_near` and `gather` in `mod/fac_agent/control.lua`.

## Tests

```
pip install -e ".[test]"
pytest
```

`tests/mock_factorio.lua` is a small fake world (collisions, inventories, recipes, drill output).
It checks the mod's logic, but not the behavior of the real engine.

## Known uncertainties (check on the first run in Factorio)

- `LuaEntity.supports_direction`, `drop_target`, `get_output_inventory` and
  `defines.inventory.crafter_input` are derived from the 2.0 docs and the reference repos,
  not checked live.
- The character is created by script (`create_entity`) and moved by teleport.
  Whether a script character can mine and use its inventory in all cases will only show in practice.
- `connect` for belts, pipes and power (router), `snapshot`, `belt_neighbours`, `get_max_wire_distance`, offshore pump placement and `game.server_save` are only tested against the mock.
- The boundary command for multi-part RCON replies comes from phiresky/factorio-mcp
  (used against real Factorio there), but is only tested against a fake server here.

## Ideas for later

See also `docs/PLAN_QWEN38.md` (status of each phase).


Trains (stations, signals, schedules; rail laying is done, see `docs/PLAN_RAILS.md`), oil and chemistry, defense, event messages from the mod
(attack, research finished), importing real blueprint strings, async jobs with `*_status` for longer actions (pattern from the
companion repo), honest walking with pathfinding. Optimization ideas for Qwen3.8: `docs/PLAN_QWEN38.md`.

## Rails

`connect kind=rail` is checked against a real Factorio 2.0.77 (not only the mock): the piece geometry is learned from the game
by `tools/calibrate_rails.py` (`src/factorio_agent_mcp/data/rail_table.json`, turned into `mod/fac_agent/scripts/rail_table.lua` by
`tools/gen_rail_table.py`). After a Factorio update run both scripts again. Details and open points: `docs/PLAN_RAILS.md`.
