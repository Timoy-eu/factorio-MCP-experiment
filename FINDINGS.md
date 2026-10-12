# Findings from the reference repos

Analyzed (all cloned, as of October 2026): Factorio Learning Environment (FLE, MIT),
lveillard/factorio-ai-companion (MIT), thedemon117/ai-player-v3 (MIT according to its README),
phiresky/factorio-mcp (ISC according to package.json), JackHopkins/claude-code-plays-factorio (prompt only).
No code was copied; only patterns were adopted and rewritten.

## 1. RCON connection (phiresky/factorio-mcp)

- Factorio ignores the Valve trick "mirror an empty RESPONSE_VALUE packet". For multi-part
  replies, a real follow-up command (`rcon.print("")`) has to be sent after the actual command as a
  boundary. Everything up to the reply to the boundary belongs to the first reply.
- Lua arguments must be escaped properly (tagged-template approach), otherwise a player name
  or item name with quotes breaks the command.
- An RCON socket is not thread-safe: serialize all calls behind a lock
  (ai-player-v3 does the same).
- Critical: `/silent-command` with huge Lua per call runs into packet limits. Better a
  small mod with `remote.add_interface` and short calls (`remote.call(...)`), as the
  companion variant does with `/fac_api`.

## 2. Rotation and placement (cause of the FLE problems)

- FLE converts internally between its own direction enum, 8 directions (Factorio 1.x) and
  16 directions (Factorio 2.0: 0, 4, 8, 12). `place_entity/server.lua` still contains
  comments like "0 -> 4" from the 1.x era next to mappings that are now identity.
  This mix is a plausible source of errors (my assessment, not confirmed).
- In 2.0, assemblers without a fluid recipe cannot be turned with `rotate()`. FLE solves this by
  destroying and recreating them (saving recipe, inventory, health). The pattern is necessary.
- `set_recipe` can change the direction. Afterwards force the direction again and read it back.
- After rotating, FLE checks whether `entity.direction` really matches the target and raises
  an error otherwise. This read-back is the most important robust pattern.

## 3. Let the server solve orientation instead of the model guessing (companion)

- The `pick_orientation` step tries all four sides, checks each side with
  `can_place_entity` (main object and neighbor) and takes the first valid one. The model does not
  have to give a direction. That is exactly what a small local model needs.
- `find_patch` additionally checks whether the drill footprint really lies on the ore.
- `ensure_item` obtains missing materials automatically (recursive crafting/gathering).

## 4. Tool design for small models

- Companion offers 70 tools. Far too many for small models. FLE requires the model to write Python code,
  also too much.
- Worth adopting: async jobs with a `*_status` query, bounded world snapshots
  (`world_observe`), blueprint tools, a help function.
- Own approach: about 12 high-level tools, compact text output, error messages with a
  suggested action, `status` additionally returns a recommended next step.

## 5. Licenses

All sources used are permissive (MIT/ISC). Even so, only the patterns were adopted.
