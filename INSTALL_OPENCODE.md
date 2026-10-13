# Installation with OpenCode (Linux)

Goal: a local model (e.g. Qwen 27B) plays Factorio 2.0 through OpenCode. You can play along at the same time.

```
OpenCode + local model <-stdio-> factorio-agent-mcp <-RCON-> Factorio server (Linux, headless) + mod fac_agent
                                                                   ^ you join as a player
```

Status: everything is tested against a mock, not yet against a real Factorio. The OpenCode and
Factorio steps below are written from the documentation, not tried on your machine.

## 1. Requirements

- Linux, Python 3.10 or newer (`python3 --version`), `git`, `unzip`
- Factorio 2.0 (the full game to play along) and the headless version for the server
  (download: factorio.com, "Download", Headless, Linux). Both must have the same version.
- A local model with tool calling behind an OpenAI-compatible API
  (llama.cpp `llama-server`, Ollama or LM Studio)

## 2. Install OpenCode

```bash
curl -fsSL https://opencode.ai/install | bash
# alternatively: npm i -g opencode-ai
opencode --version
```

## 3. Install the MCP server

```bash
cd ~
unzip factorio-agent-mcp.zip
cd factorio-agent-mcp
python3 -m venv .venv
.venv/bin/pip install -e .
```

The command `~/factorio-agent-mcp/.venv/bin/factorio-agent-mcp` is the `command` in OpenCode later.

## 4. Factorio server with mod and RCON

1. Unpack the headless version, e.g. to `~/factorio`.
2. Install the mod (the `mods/` folder is in the Factorio directory):
   ```bash
   cp ~/factorio-agent-mcp/dist/fac_agent_0.3.0.zip ~/factorio/mods/
   ```
   To play along, put the same zip into the `mods/` folder of your game client.
3. Create `~/factorio/server-settings.json` (template: `~/factorio/data/server-settings.example.json` in the Factorio folder) and set these values:
   ```json
   {
     "name": "Agent-Server",
     "visibility": { "public": false, "lan": true },
     "auto_pause": false,
     "allow_commands": "admins-only",
     "autosave_interval": 5
   }
   ```
   `"auto_pause": false` is important. Otherwise the game pauses as soon as no player is connected, and the agent
   only notices it from messages like "no game time passed".
4. Start the server:
   ```bash
   cp ~/factorio-agent-mcp/examples/start_factorio.sh ~/start_factorio.sh
   RCON_PASSWORD=secret ~/start_factorio.sh
   ```
   On the first start the map `saves/agent.zip` is created. The output should show the mod `fac_agent 0.2.0`
   being loaded and RCON listening on port 27015.
5. Optional as a service: a `systemd` unit that runs `start_factorio.sh` (`Restart=on-failure`).

Playing along: in the game "Multiplayer", "Connect to address", `server-ip` (locally `localhost`).

## 5. Serve the local model

Ready-made settings for the two Qwen3.8 variants (llama.cpp `llama-server`). The sampling values are
the usual Qwen3 starting values; check the model card on Hugging Face and compare with the eval runner (section 11).

**Qwen3.8 27B (dense, fits a 24 GB GPU at Q4_K_M):**

```bash
llama-server -m /path/to/qwen3.8-27b-Q4_K_M.gguf --port 8080 --jinja -c 131072 \
  --temp 0.6 --top-p 0.95 --top-k 20 --min-p 0 -ngl 99
```

Config: `examples/opencode.qwen38-27b.json` (profile `full`).

**Qwen3.8 Flash-Next (MoE, about 6B active parameters):** keep the experts in RAM, the rest on the GPU.

```bash
llama-server -m /path/to/qwen3.8-flash-next-Q4_K_M.gguf --port 8080 --jinja -c 131072 \
  --temp 0.6 --top-p 0.95 --top-k 20 --min-p 0 -ngl 99 --n-cpu-moe 40
```

Lower `--n-cpu-moe` until the GPU memory is full; the RAM need is listed on the GGUF page.
Config: `examples/opencode.qwen38-flash-next.json` (profile `core`, fewer tools, easier to choose from).

Notes:
- `--jinja` enables the tool-calling template; without it Qwen's tool calls break.
- Thinking mode: costs tokens on every step but can help with planning (power, belts). Measure both with the eval runner.
- Ollama: set the context to at least 32k (`num_ctx`), otherwise tool calls break off.

## 6. Configure OpenCode

In the project folder where you start OpenCode (e.g. `~/factorio-play`), create these files:

```bash
mkdir -p ~/factorio-play && cd ~/factorio-play
cp ~/factorio-agent-mcp/examples/opencode.json .
cp ~/factorio-agent-mcp/examples/AGENTS.md .
```

In `opencode.json` replace `YOU` with your user name, set the RCON password and adjust the
model block (port, name, context size). The most important parts:

```json
"mcp": {
  "factorio": {
    "type": "local",
    "command": ["/home/YOU/factorio-agent-mcp/.venv/bin/factorio-agent-mcp"],
    "environment": {
      "FACTORIO_RCON_HOST": "127.0.0.1",
      "FACTORIO_RCON_PORT": "27015",
      "FACTORIO_RCON_PASSWORD": "secret"
    },
    "enabled": true,
    "timeout": 15000
  }
}
```

- OpenCode prefixes every tool with the server name, so the model sees `factorio_status`, `factorio_build` etc.
- OpenCode reads `AGENTS.md` automatically; it contains the short guide for the model. The detailed
  guide comes from the `factorio_guide` tool.
- Models in Ollama or LM Studio: adjust the `provider` block accordingly (`baseURL` `http://localhost:11434/v1`
  or `http://127.0.0.1:1234/v1`).

## 7. Self-test (run this first)

On the first run in real Factorio, run the self-test once. It checks the mod's API assumptions
(placing, rotating, belts, power poles, crafting, mining, statistics, chat, saving) in a free sandbox area
and removes everything afterwards. Inventory and position are restored.

In the OpenCode chat: "Call `factorio_selftest` and show me the full report." Every line starts with
`OK`, `WARN`, `FAIL` or `SKIP`. Send me the report, especially all `FAIL` lines, and I will adjust the mod.
`SKIP` only means that e.g. no water or ore was nearby. Run the test close to ore and water,
ideally with a save in which buildings like drills and pumps are already unlocked.

## 8. Testing

```bash
cd ~/factorio-play
opencode
```

Then in the chat, for example:

1. "Call `factorio_status`." Expected: position, inventory and "next:" steps.
   If you get `ERR no_connection`, the server is not running or port/password are wrong.
   If you get `mod_missing`, the mod is not loaded.
2. "Read `factorio_guide` and start: gather coal and stone and build a drill on iron."
3. Messages appear in the game as `[Bot] ...`. You can reply in the game chat; the agent
   reads it with `factorio_read_chat`.

Open the live viewer for yourself after `factorio_render_map` at `http://127.0.0.1:8765/`.

## 9. Tips for local models

- Tool profile: `FACTORIO_MCP_PROFILE=core` offers about 27 tools instead of 47 (about 2,900 instead of
  5,300 tokens of tool descriptions) and makes the choice easier for small models. `full` adds blueprints,
  measuring tools, maps for the human and more.
- Every action reply ends with a `[state]` line (position, carried items, next step), and `goal` keeps a
  checklist that is shown there. Repeated failing calls get a `STOP` reply so the model does not loop.
- If context gets tight: enable fewer tools. In OpenCode you can turn off single tools:
  ```json
  "tools": { "factorio_run_lua": false, "factorio_render_map": false }
  ```
  or set `FACTORIO_MCP_DISABLE_LUA=1` to remove `run_lua` entirely.
- Small steps work better. Give the model goals like "automate iron plates", not "win the game".
- For repetition: `factorio_batch`. For debugging: `factorio_machine_stats`, `factorio_trace_item`.
- Save with `factorio_checkpoint` before experiments.

## 10. Troubleshooting

| Problem | Cause and fix |
|---|---|
| Tools do not appear in OpenCode | `command` wrong or venv missing. Test the command in a terminal. Increase `timeout` (e.g. 15000). |
| `ERR no_connection` | Server not running, wrong password or port. `ss -ltn \| grep 27015`. |
| `ERR mod_missing` | Mod not in the server's `mods/` folder or wrong Factorio version. |
| "no game time passed" | `auto_pause` is on or nobody is connected. Set it to `false` in `server-settings.json`. |
| Model calls tools incorrectly | Context too small, missing `--jinja`, or a model without good tool calling. |
| Achievements disabled | Normal: console commands via RCON disable achievements. |
| Error in a tool | The message contains `try:` with a hint. Otherwise read the server log (`factorio-current.log`). |

On the first run in real Factorio small API differences may show up (see README, "Known uncertainties").
Send me the error message and the log, and I will adjust the mod.


## 11. Measuring with the eval runner

To compare settings (profile, sampling, thinking, model) systematically:

```bash
factorio-agent-eval --base-url http://127.0.0.1:8080/v1 --model qwen38-27b --scenario S1 --runs 3 --profile core --label "27b core"
factorio-agent-eval --scenario all --runs 3 --profile full --label "27b full"
```

Scenarios: S1 10 iron plates, S2 4 working burner miners, S3 steam power for a machine, S4 research automation,
S5 a belt of 5 pieces between drill and furnace. Each run appends a line to `eval-runs.jsonl` (success, steps,
tool calls, malformed calls, ERR and STOP replies, tokens, game time, tools used). The world is not reset
between runs: load a fresh save before each run, for example with `--reset-cmd "./reload_save.sh"`.
