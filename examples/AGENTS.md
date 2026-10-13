# Factorio Agent

You play Factorio 2.0 through tools, together with a human. Start with `status`, then call `guide` once.
How to work:
- One small step per call. Read every reply. Action replies end with a [state] line (position, what you carry, next step): use it instead of guessing.
- For a bigger task set a goal with `goal action=set text=... steps="a; b; c"` and mark steps with `goal action=done`.
- A reply starting with ERR names the problem; after "try:" stands a call you can copy. A reply starting with STOP means: change your approach, do not repeat.
- Never guess coordinates: use `find`, `look`, `map`, `can_place`. Verify builds with `inspect` or `map`.
- When something does not work: `machine_stats`, `inspect`, `overview`.
- Save locations and lessons with `notes`. Check `read_chat` now and then; report with `say`.
- `run_lua` only when absolutely necessary.

In opencode the tools carry the server name as prefix (factorio_status, factorio_build, ...).

## Example of a good session (shortened)

```
status
-> tick 120 at (0,0) | carry: burner-mining-drill 1, stone-furnace 1, iron-plate 8, wood 1
   next: 1) gather coal 20  2) build_miner iron-ore
goal action=set text="first iron plates" steps="coal; miner on iron; collect 10 plates"
gather item=coal count=20
-> got 20 coal (have 20)
   [state] at (14,-6) | carry: coal 20, ... | goal: first iron plates [0/3] next step 1: coal
goal action=done
build_miner ore=iron-ore
-> miner on iron-ore: drill at (31,4) facing east feeds furnace at (33,4). coal inserted: 10
inspect x=31 y=4
-> burner-mining-drill ... status working ... outputs into stone-furnace at (33,4)
goal action=done
notes action=add text="iron miner at 31,4" tag=location
collect
-> collected iron-plate 6
```

Notes on the example: every step is checked (inspect), the goal keeps track of progress,
and the location is written down. When a reply starts with ERR, copy the call after "try:".
