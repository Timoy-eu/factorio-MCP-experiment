# Plan: optimizing factorio-agent-mcp for Qwen3.8

As of 2026-10-12. Target models, both running locally:

| | Qwen3.8 (27B) | Qwen3.8-Flash-Next |
|---|---|---|
| Architecture | dense, 27B | MoE, 125B total, about 6B active per token |
| Context | 262k native | 262k |
| Input | text + image | text + image + video |
| Tool calling | Qwen XML format (`--jinja` required in llama.cpp) | `qwen3_coder` parser (vLLM/SGLang), supported by llama.cpp |
| Local | Q4_K_M about 14 to 17 GB, 24 GB GPU | needs a lot of RAM, fast because only 6B are active |

The numbers come from the official Flash-Next GitHub page and from secondary sources for the
27B variant. I found no official sampling values for Qwen3.8; check the model cards on
Hugging Face before fine-tuning settings.

Starting point in the code: 50 tools with about 5,700 tokens of schema in total, `INSTRUCTIONS` about 200 tokens,
the full `guide` about 1,350 tokens. The example configuration uses 64k context.

## Principle: measure first, then optimize

So far there is no way to measure whether a change helps a model. Without that, every further
step is guesswork. That is why evaluation comes first.

## Phase 1: Evaluation (prerequisite for everything else)

1. **Agent runner** `tools/eval_run.py`: a lean agent loop that talks directly to the
   OpenAI-compatible endpoint (llama-server/vLLM) and runs the MCP server as a subprocess.
   Independent of OpenCode so runs are reproducible (fixed seed, fixed map, fixed sampling values).
2. **Scenarios** with a clear success criterion, read via RCON:
   - S1 "first plates": 10 iron-plate in the inventory
   - S2 "mining": 4 running burner miners on iron
   - S3 "power": a steam engine powers a network with at least one consumer
   - S4 "research": automation researched
   - S5 "belt": ore arrives at a furnace by belt (trace_item succeeds)
3. **Metrics per run**, as a JSONL log:
   - share of malformed tool calls (invalid JSON/XML, wrong parameters, unknown tool)
   - share of `ERR` replies and repeated identical calls after errors
   - tool calls and game time until the goal, tokens per run
   - which tools are never used or used wrongly
4. **Baseline**: both models, 3 runs per scenario each, with the current state. Every later change
   is compared against these numbers.

## Phase 2: Robustness of the tool interface

Qwen's XML tool format transmits parameter values as text. Smaller models also like to send
variants (number as string, list as JSON string, wrong parameter names).

1. **Lenient arguments**: already handled by the MCP framework (tested: `batch` with `actions`
   as a JSON string and `look radius="20"` both work). Gap: inside `batch` the
   `args` are passed to the functions without validation, so strings arrive unchanged.
2. **Aliases for common mix-ups**, e.g. `name`/`item`/`entity`, `pos`/`position` as `"x,y"`.
   The eval logs show which aliases are needed; do not add them on suspicion.
3. **Error messages for wrong arguments** in the same style as the game errors:
   `ERR bad_args: ... | try: build entity=stone-furnace x=10 y=5`. Today validation errors
   return the MCP framework's message, not our own.
4. **Tests**: unit tests with typical malformed calls from the logs.

## Phase 3: Smaller tool selection

50 tools fit into 262k context, but many similar tools make tool selection worse. This mainly
affects Flash-Next with only about 6B active parameters.

1. **Profiles** via the environment variable `FACTORIO_MCP_PROFILE`:
   - `core` (about 20 tools): status, look, find, gather, craft, build, build_miner, rotate, fuel,
     collect, insert, extract, set_recipe, connect, research, map, inspect, can_place,
     machine_stats, notes, guide, say, read_chat
   - `full`: everything, as today
2. **Merge** tools that overlap (candidates, depending on eval data):
   - the 6 blueprint tools into one `blueprint action=save|list|show|place|note|delete`
   - `belt_contents`/`trace_item`/`measure_flow` as `measure kind=...`
3. **Shorten descriptions**: trim the longest schemas (map, connect, nearest_buildable, render_map,
   batch) to the essentials and move details into `guide`.
4. Compare with the eval: `core` against `full`, per model. The better profile becomes the default in
   the example configuration.

## Phase 4: More planning on the server side

`planner.py` only covers the beginning (coal, stone, first miners, research "automation").
Small models plan poorly, so extending the "next:" steps pays off:

1. Power: find water, build pump/boiler/steam engine, lay poles
2. Set up and supply a lab, red science by hand, then automated
3. First belts: miners onto a belt, a furnace row, plates into a chest
4. Problems from `overview` (no_power, full_output) as prioritized steps

Both models benefit, Flash-Next probably more.

## Phase 5: Use image input (experiment)

Both models understand images. Today `render_map` only creates an SVG for the human; the model
works with the ASCII map.

1. New tool `see` (or an option on `map`): renders the area as PNG and returns it as
   MCP image content. SVG to PNG: either `cairosvg` or draw directly with Pillow.
2. **Check first** whether the chain passes images in tool replies through at all: OpenCode,
   llama-server with `--mmproj`, chat template. If not, the experiment ends for this setup.
3. Compare with the eval: ASCII alone against ASCII plus image, especially for S5 (belts).
   Images cost many tokens; only use them if they help measurably.

## Phase 6: Model configuration and docs

1. Add two ready-made profiles to `INSTALL_OPENCODE.md`:
   - Qwen3.8-27B: `llama-server ... --jinja -c 131072`, note on current GGUFs with a fixed
     chat template
   - Qwen3.8-Flash-Next: MoE offload to RAM (`--n-cpu-moe` or `-ot`), RAM requirement per the GGUF page
2. Sampling: start with the Qwen3 values (temperature 0.6, top_p 0.95, top_k 20, min_p 0,
   presence_penalty up to 1.5 against repetition) and compare via eval against 0.7 and against the
   model card values.
3. Decide **thinking on or off** via eval. Thinking costs tokens per step but may help with
   planning (S3, S5). With thinking, make sure the client handles reasoning blocks
   between tool calls correctly.
4. Context: 262k native is possible, but the KV cache costs memory. Test 128k as the default;
   `notes` remains the way to keep knowledge across context resets.
5. Two example `opencode.json` files (one per model) in `examples/`.

## Order and effort

| Phase | Effort | Benefit | Depends on |
|---|---|---|---|
| 1 Evaluation | medium to high | prerequisite | headless Factorio on Linux |
| 2 Robustness | small | medium (framework already covers the most common case) | logs from phase 1 |
| 3 Tool selection | medium | high for Flash-Next | phase 1 |
| 4 Planner | medium | medium to high | – |
| 5 Images | medium | unclear, experiment | client support |
| 6 Configuration/docs | small | medium | results from 1 to 3 |

Recommendation: first let Qwen3.8 play with the MCP unchanged and only improve where it
visibly struggles. Phase 1 only pays off once several variants should be compared systematically.

## Open questions

- Does OpenCode stay the client, or may the eval runner also be used for normal play?
- Does headless Factorio run on the same Linux machine as the model?
