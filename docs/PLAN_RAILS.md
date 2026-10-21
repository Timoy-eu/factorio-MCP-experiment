# Plan: building rails (including curves) as tools

As of 2026-10-13. Goal: the model can lay a working rail line between two points, including curves,
add stations and signals, and run a train, with the same reliability rules as the other tools
(server does the geometry, every placement is read back, clear errors with copyable `try:` calls).

## Status (2026-10-13)

| Phase | Status |
|---|---|
| 0 API spike | done against a real Factorio 2.0.77 server, findings below |
| 4 Display | done: ASCII layer `rails`, SVG with curves from the learned table, signals, stops, trains |
| 1 Calibration | done: `tools/calibrate_rails.py` learns the table from the game (24 pieces, reproducible), `tools/gen_rail_table.py` makes `rail_table.lua` |
| 2 Router | done, in Lua inside the mod (`scripts/rails.lua`) instead of Python: exact `can_place_entity`, no RCON round trips |
| 3 Tools | partly: `connect kind=rail` and `rail_end` done, a train ran 2 laps on a built loop (stations, schedule and loco placed by console, not yet by tools); `build_station`, `build_signals`, `build_train`, `train_schedule` open |
| 5 Guide, planner, eval | guide topic `rails` done; planner and eval scenario S6 open |

Deviations from the plan: the router lives in the mod, and it also removes trees and rocks in the way (cost per tree,
`keep_trees=true` turns that off). ASCII glyphs differ from the plan because `=`, `s` and `B` were taken: `|` `-` `/` `\` rails, `!` signal,
`?` chain signal, `Z` train stop, `M` locomotive, `w` wagon.

## Findings of the API spike (real game, 2.0.77)

- Items: `straight-rail` needs 1 `rail`, `half-diagonal-rail` 2, `curved-rail-a` and `curved-rail-b` 3 each.
- `create_entity` snaps position and direction itself (a straight rail with direction 1 becomes direction 0), so always read
  `entity.position` and `entity.direction` back. Direction values are 0..15 (north = 0, clockwise).
- Connectivity: `entity.get_rail_end(defines.rail_direction.front|back)` returns a `LuaRailEnd`. `location` has `position`, `direction`,
  `rail_layer`. `move_forward(defines.rail_connection_direction.left|straight|right)` only moves along rails that exist and returns
  `false` otherwise; `rail` is the piece it landed on. That is the connectivity check used by the tools.
- Learned geometry: every end of every piece has exactly one `straight`, one `left` and one `right` continuation, and the way back
  is always listed (`tests/test_rails.py` checks both). `curved-rail-a` joins orthogonal pieces, `curved-rail-b` diagonal ones, a
  straight piece can be followed by a half-diagonal one through a curve pair.
- `can_place_entity` with `build_check_type.ghost_place` does not ignore trees, so trees are found with `find_entities_filtered`
  and cut one by one (`entity.mine{inventory=...}`).
- Closed loop test (real game, 2026-10-21): four `connect kind=rail` legs formed a loop of 67 pieces (curves a and b, straights, half-diagonals).
  The last leg ended exactly at the open end of the first piece (`goal` = that end, `end_direction` = the way the first piece continues).
  Checks: no open rail end left, and walking `move_forward` from the first piece returns to it after 67 steps.
- Trains: `train-stop` sits on the RIGHT side of the travel direction (east travel: stop south of the rail, facing east; west travel: north
  of the rail, facing west). Find the spot by trying offsets and keep the one where `stop.connected_rail` is not nil.
  `locomotive` created with the rail direction gets `orientation` 0.25 for east; `train.schedule = {current=1, records={{station=..., wait_conditions={{type="time", ticks=..., compare_type="and"}}}}}`
  and `train.manual_mode = false` start it; fuel with `get_fuel_inventory().insert`.
- A schedule with ONE station never leaves it (the next stop would be the same station). Two stations are needed for a lap.
- `defines.train_state` in 2.0.77: on_the_path 0, no_schedule 1, no_path 2, arrive_signal 3, wait_signal 4, arrive_station 5, wait_station 6,
  manual_control_stop 7, manual_control 8, destination_full 9. There is no `train.front_rail`; use `train.get_rails()`.
- `loco.set_driver(character)` works for the agent character; the seated character no longer shows up in `find_entities_filtered{name="character"}`,
  use `loco.get_driver()`. Result: 2.05 laps in 1782 ticks with 4 station stops, top speed 0.66 tiles/tick (143 km/h).
- Bug found by this test and fixed (mod 0.3.3): when trees stood next to the line, `scan_box` counted our own neighbouring rails as blockers and the
  piece failed with `blocked`. Rails of our force are harmless neighbours now.
- Performance: a 150 tile line searches and builds in about 2 s, a 250 tile U-turn in about 5 s (the game is blocked meanwhile),
  a failed search up to about 5 s at the node limit (40000).

## Why curves are the hard part

Rails in Factorio 2.0 are not tile pieces like belts:

- They sit on a 2x2 grid and use 16 directions (straight, half-diagonal and diagonal pieces).
- 2.0 has four ground rail types: `straight-rail`, `half-diagonal-rail`, `curved-rail-a`, `curved-rail-b`.
  A 90 degree turn is a chain of several pieces; the exact positions and directions of each piece
  are not obvious and are easy to get wrong by hand.
- Elevated rails and ramps (Space Age) are out of scope for this plan.

Hard-coding the geometry from memory is the main risk. Small errors produce rails that look connected
but are not. The plan therefore lets the game itself tell us which piece connects where.

## Core idea: learn the rail geometry from the game

Instead of writing the transition table by hand, a calibration routine in the mod builds it once:

1. In a free sandbox area, place one seed rail of each type and direction.
2. For each rail end and each turn option (straight, left, right), try candidate pieces
   (all rail types, all 16 directions, positions within a small radius on the 2x2 grid).
3. Keep a candidate only if the game reports it as the connected neighbour of the seed
   (`LuaEntity.get_connected_rail{rail_direction=..., rail_connection_direction=...}`, or the 2.0
   `LuaRailEnd` API, whichever works; to be checked in phase 0).
4. Store the result as a table: `(type, direction, end, turn) -> (type, dx, dy, direction)`, plus the
   resulting end state. Cache it in `storage` and as JSON in the data folder, keyed by game version.

The router and all tools only use this table. If a game update changes the geometry, a recalibration
fixes it without code changes. The selftest gets a rail check that verifies a few table entries.

## Phase 0: API spike (small, needs the real game)

Verify in a real Factorio 2.0 (selftest extension plus a few `run_lua` checks):

- `surface.create_entity` / `can_place_entity` for each rail type and 16 directions, valid positions
  (which coordinates are accepted, even or odd grid).
- How to query connectivity: `get_connected_rail`, `LuaRailEnd` (`get_rail_end`, `move_forward`,
  `location`), `defines.rail_direction`, `defines.rail_connection_direction`.
- Items: which item places which rail entity (`rail` item for ground rails in 2.0).
- Train stop and signal placement rules (side of the track, offset to the rail).
- Locomotive placement on a rail, fuel, `train.manual_mode`, schedule API in 2.0
  (`train.schedule` table or the newer schedule object).

Output: a short findings section in this file, and selftest checks `rail_place`, `rail_connect`,
`train_stop`, `rail_signal`, `locomotive`. Everything below depends on these answers.

## Phase 1: calibration and geometry table (medium)

- `scripts/rails.lua`: `M.calibrate()` builds the transition table as described above and returns
  how many transitions it found per rail type.
- Sanity checks: every straight piece has exactly one straight continuation per end; left and right
  turns are mirror images; following four 90 degree turns returns to the start direction.
- Python `rails.py`: load the table, helpers to walk a path and compute end states.
- Tests: the mock gets a small synthetic rail model (straight plus one curve family) so the router and
  placement logic are tested independent of the real geometry.

## Phase 2: rail router (medium to high)

A* over rail states instead of tiles:

- State: rail end position on the 2x2 grid plus one of 16 directions.
- Moves: the transitions from the table (straight, left curve, right curve).
- Costs: piece length, a penalty for curves and for changing between diagonal and orthogonal,
  a bigger penalty near water and buildings, so lines stay simple.
- Heuristic: octile distance on the rail grid plus a direction term.
- Collision: each candidate piece is checked with `can_place_entity` (cached per position and piece),
  existing own rails can be reused (like pipes today).
- Limits: node budget (for example 20,000), search box around start and goal with a margin; clear error
  `ERR no_path` with the blocking area if it fails.
- Goal condition: reach the goal point with the requested end direction (or any direction if not given).
- Output: list of pieces (type, position, direction).

## Phase 3: tools (medium)

| Tool | What it does |
|---|---|
| `connect kind=rail x1 y1 x2 y2 end_direction=... dry_run=...` | routes and lays the line; `dry_run` returns the number of rail items and a preview |
| `rail_end x y` | shows the open ends of the rail at x,y and where a continuation must start (helps the model join lines) |
| `build_station name x y side=right` | places a train stop on the correct side of an existing straight rail and names it |
| `build_signals x1 y1 x2 y2 spacing=...` | places rail signals along a line on the correct side |
| `build_train x y locomotives=1 wagons=2` | places locomotive and cargo wagons on a straight section, fuels the locomotive |
| `train_schedule x y stations="A; B" wait=...` | sets the schedule of the train at x,y and switches it to automatic |
| `inspect` (extended) | for rails: connected neighbours in both directions; for trains: state, schedule, current station |

Placement rules as everywhere else: place piece by piece, read back position and direction, verify the
whole line with the connectivity API, roll back everything on failure, report the first broken piece
with a `try:` call. All rail tools are in the `full` profile; `connect kind=rail` also works in `core`.

## Phase 4: display (small, can be done first)

- ASCII `map`: straight rails as `=` (east-west) and `|` (north-south), diagonals as `/` and `\`,
  curves with the nearest of these, signals `s`, train stops `B`, locomotives `L`, wagons `W`.
- SVG `render_map`: rails as tracks with sleepers along the real piece shape (curves as arcs from the
  calibrated table), signals with their colour, stations with their name, trains as long vehicles.
- `snapshot` adds rail type and direction (already in the data) plus train stop names.

## Phase 5: guide, planner, eval (small)

- `guide topic=trains`: when trains are worth it, a minimal working layout (two stations, one train,
  signals at junctions), how to check it (`inspect`, `map layers=rails`).
- Planner: suggest trains only after power, automation and a second ore field exist.
- Eval scenario S6: a train runs between two stations and delivers ore.

## Order and effort

| Phase | Effort | Depends on |
|---|---|---|
| 0 API spike | small | real Factorio 2.0 |
| 4 Display | small | none (can be done now) |
| 1 Calibration | medium | phase 0 |
| 2 Router | medium to high | phase 1 |
| 3 Tools | medium | phase 2 |
| 5 Guide, planner, eval | small | phase 3 |

Recommended start: phase 4 (display) and phase 0 (spike) in parallel, because both are small and the
spike decides how phases 1 to 3 are built.

## Risks

- The 2.0 rail API differs from what this plan assumes. Mitigation: phase 0 first, calibration instead
  of hard-coded geometry.
- Router performance with 16 directions on large maps. Mitigation: node budget, search box, coarse
  pre-routing on a larger grid for long distances.
- The mock cannot prove real rail behaviour; correctness is only shown by the selftest and the eval in
  the real game.
- Small models may struggle with signal logic. Mitigation: `build_signals` places them automatically;
  the first goal is a single train between two stations without junctions.
