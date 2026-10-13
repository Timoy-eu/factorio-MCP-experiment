"""Reproducible evaluation: let a local model play fixed scenarios and log what went wrong.

Usage (Factorio server with the mod running, model behind an OpenAI-compatible endpoint):

    factorio-agent-eval --base-url http://127.0.0.1:8080/v1 --model qwen --scenario S1 --runs 3

Every run appends one JSON line to the log (default eval-runs.jsonl). Compare variants (profile,
sampling, thinking on/off, tool changes) by their success rate, steps and error rates.
The world is NOT reset between runs: load a fresh save before each run (--reset-cmd helps).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable

from . import guide as guide_module
from .game import Game, GameError, as_list, as_map

ChatFn = Callable[[list[dict[str, Any]], list[dict[str, Any]]], dict[str, Any]]


# ---------------------------------------------------------------- scenarios

def _inv(game: Game) -> dict[str, int]:
    return as_map(game.call("inventory").get("items"))


def _counts(game: Game) -> tuple[dict[str, int], dict[str, Any]]:
    d = game.call("diagnose", None, None, None)
    return as_map(d.get("counts")), as_map(d.get("problems"))


def s1_plates(game: Game) -> bool:
    return int(_inv(game).get("iron-plate", 0)) >= 10


def s2_miners(game: Game) -> bool:
    data = game.call("get_entities", ["burner-mining-drill"], None, None, 80, 200)
    working = [e for e in as_list(data.get("entities")) if e.get("status") == "working"]
    return len(working) >= 4


def s3_power(game: Game) -> bool:
    counts, problems = _counts(game)
    consumers = sum(int(counts.get(n, 0)) for n in ("lab", "assembling-machine-1", "inserter", "electric-mining-drill"))
    return int(counts.get("steam-engine", 0)) >= 1 and consumers >= 1 and "no_power" not in problems


def s4_research(game: Game) -> bool:
    try:
        return bool(game.call("research_info", "automation").get("researched"))
    except GameError:
        return False


def s5_belt(game: Game) -> bool:
    data = game.call("get_entities", ["transport-belt"], None, None, 80, 200)
    lines = as_list(as_map(data.get("groups")).get("belts"))
    if not any(int(g.get("n", 0)) >= 5 for g in lines):
        return False
    counts, _ = _counts(game)
    return int(counts.get("stone-furnace", 0)) >= 1 and int(counts.get("burner-mining-drill", 0)) >= 1


@dataclass
class Scenario:
    key: str
    prompt: str
    check: Callable[[Game], bool]


SCENARIOS = {
    "S1": Scenario("S1", "Goal: have at least 10 iron-plate in your inventory.", s1_plates),
    "S2": Scenario("S2", "Goal: 4 burner mining drills on iron ore that are working (fueled, output into furnaces).",
                   s2_miners),
    "S3": Scenario("S3", "Goal: build steam power (offshore pump, boiler, steam engine) that powers at least one machine.",
                   s3_power),
    "S4": Scenario("S4", "Goal: research the technology automation.", s4_research),
    "S5": Scenario("S5", "Goal: a belt of at least 5 pieces that carries ore from a burner drill towards a furnace.",
                   s5_belt),
}


# ---------------------------------------------------------------- model access

def http_chat(base_url: str, model: str, sampling: dict[str, Any], api_key: str = "", timeout: float = 600) -> ChatFn:
    url = base_url.rstrip("/") + "/chat/completions"

    def chat(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        body = {"model": model, "messages": messages, "tools": tools, "tool_choice": "auto", **sampling}
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json",
                                              **({"Authorization": f"Bearer {api_key}"} if api_key else {})})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())

    return chat


def openai_tools(registry: dict[str, Callable[..., str]], names: list[str]) -> list[dict[str, Any]]:
    """Tool schemas in the OpenAI format, taken from the MCP server so both stay identical."""
    import asyncio

    from . import server
    listed = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    out = []
    for name in names:
        t = listed.get(name)
        if t is None:
            continue
        out.append({"type": "function", "function": {
            "name": name, "description": t.description or "", "parameters": t.input_schema}})
    return out


# ---------------------------------------------------------------- one run

@dataclass
class RunResult:
    scenario: str
    success: bool = False
    steps: int = 0
    tool_calls: int = 0
    bad_calls: int = 0
    err_replies: int = 0
    stop_replies: int = 0
    repeated_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    game_ticks: int = 0
    seconds: float = 0.0
    tools_used: dict[str, int] = field(default_factory=dict)
    end_reason: str = ""
    errors: list[str] = field(default_factory=list)


def run_scenario(scenario: Scenario, game: Game, chat: ChatFn, max_steps: int = 60,
                 profile: str = "core", system_extra: str = "") -> RunResult:
    from . import server

    server.configure(game)
    server.apply_profile(profile)
    names = list(server._registered)
    tools = openai_tools(server.REGISTRY, names)
    result = RunResult(scenario.key)
    usage = Counter()
    start_tick = int(game.call("status").get("tick", 0))
    started = time.time()
    system = guide_module.INSTRUCTIONS + ("\n" + system_extra if system_extra else "")
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": scenario.prompt + " Work step by step with the tools. Say DONE when the goal is reached."},
    ]
    last_call = None
    nudged = False
    for step in range(1, max_steps + 1):
        result.steps = step
        reply = chat(messages, tools)
        for k in ("prompt_tokens", "completion_tokens"):
            usage[k] += int(as_map(reply.get("usage")).get(k, 0))
        msg = reply["choices"][0]["message"]
        calls = msg.get("tool_calls") or []
        messages.append({k: v for k, v in msg.items() if k in ("role", "content", "tool_calls")} | {"role": "assistant"})
        if not calls:
            if scenario.check(game):
                result.success, result.end_reason = True, "done"
                break
            if nudged:
                result.end_reason = "model stopped"
                break
            nudged = True
            messages.append({"role": "user", "content": "The goal is not reached yet. Call status and continue."})
            continue
        for call in calls:
            fn = call.get("function", {})
            name = fn.get("name", "")
            raw = fn.get("arguments") or "{}"
            result.tool_calls += 1
            result.tools_used[name] = result.tools_used.get(name, 0) + 1
            try:
                args = json.loads(raw) if isinstance(raw, str) else dict(raw)
                if name not in names:
                    raise KeyError(name)
                text = server.REGISTRY[name](**server._coerce(server.REGISTRY[name], args))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as err:
                result.bad_calls += 1
                result.errors.append(f"{name}: {type(err).__name__}: {err}"[:200])
                text = f"ERR bad_call: {err}"
            key = (name, raw)
            if key == last_call:
                result.repeated_calls += 1
            last_call = key
            if text.startswith("ERR"):
                result.err_replies += 1
            if text.startswith("STOP"):
                result.stop_replies += 1
            messages.append({"role": "tool", "tool_call_id": call.get("id", name), "content": text})
        if scenario.check(game):
            result.success, result.end_reason = True, "goal reached"
            break
    else:
        result.end_reason = "max steps"
    result.prompt_tokens, result.completion_tokens = usage["prompt_tokens"], usage["completion_tokens"]
    result.game_ticks = int(game.call("status").get("tick", 0)) - start_tick
    result.seconds = round(time.time() - started, 1)
    return result


# ---------------------------------------------------------------- CLI

def summary(results: list[RunResult]) -> str:
    lines = []
    by: dict[str, list[RunResult]] = {}
    for r in results:
        by.setdefault(r.scenario, []).append(r)
    for key, runs in sorted(by.items()):
        ok = sum(r.success for r in runs)
        calls = sum(r.tool_calls for r in runs) or 1
        lines.append(f"{key}: {ok}/{len(runs)} success, avg steps {sum(r.steps for r in runs) / len(runs):.1f}, "
                     f"bad calls {100 * sum(r.bad_calls for r in runs) / calls:.0f}%, "
                     f"ERR {100 * sum(r.err_replies for r in runs) / calls:.0f}%, "
                     f"STOP {sum(r.stop_replies for r in runs)}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    from .rcon import Rcon

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default=os.environ.get("EVAL_BASE_URL", "http://127.0.0.1:8080/v1"))
    ap.add_argument("--model", default=os.environ.get("EVAL_MODEL", "qwen"))
    ap.add_argument("--api-key", default=os.environ.get("EVAL_API_KEY", ""))
    ap.add_argument("--scenario", default="S1", help="S1..S5 or all")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--max-steps", type=int, default=60)
    ap.add_argument("--profile", default="core", choices=["core", "full"])
    ap.add_argument("--temperature", type=float, default=0.6)
    ap.add_argument("--top-p", type=float, default=0.95)
    ap.add_argument("--top-k", type=int, default=20)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--log", default="eval-runs.jsonl")
    ap.add_argument("--label", default="", help="free text stored with each run, e.g. 'thinking off'")
    ap.add_argument("--reset-cmd", default="", help="shell command run before each run, e.g. a script that loads a fresh save")
    args = ap.parse_args(argv)

    rcon = Rcon(os.environ.get("FACTORIO_RCON_HOST", "127.0.0.1"), int(os.environ.get("FACTORIO_RCON_PORT", "27015")),
                os.environ.get("FACTORIO_RCON_PASSWORD", ""))
    game = Game(rcon)
    sampling = {"temperature": args.temperature, "top_p": args.top_p, "top_k": args.top_k, "seed": args.seed}
    chat = http_chat(args.base_url, args.model, sampling, args.api_key)
    keys = list(SCENARIOS) if args.scenario.lower() == "all" else [k.strip().upper() for k in args.scenario.split(",")]
    results = []
    for key in keys:
        for i in range(args.runs):
            if args.reset_cmd:
                subprocess.run(args.reset_cmd, shell=True, check=False)
            r = run_scenario(SCENARIOS[key], game, chat, args.max_steps, args.profile)
            results.append(r)
            row = {"label": args.label, "model": args.model, "profile": args.profile, "sampling": sampling,
                   "run": i + 1, **r.__dict__}
            with open(args.log, "a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
            print(f"{key} run {i + 1}: {'OK' if r.success else 'FAIL'} ({r.end_reason}), {r.steps} steps, "
                  f"{r.tool_calls} calls, {r.err_replies} ERR, {r.bad_calls} bad", flush=True)
    print(summary(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
