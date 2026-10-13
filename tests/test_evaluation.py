"""The eval runner with a scripted fake model instead of a real LLM."""

import json

from factorio_agent_mcp import evaluation, server


def scripted(world, calls):
    """Fake chat: returns the given tool calls one step after another, then plain text."""
    steps = iter(calls)

    def chat(messages, tools):
        assert tools and all(t["type"] == "function" for t in tools)
        try:
            name, args, side_effect = next(steps)
        except StopIteration:
            return {"choices": [{"message": {"role": "assistant", "content": "DONE"}}], "usage": {}}
        if side_effect:
            world.exec(side_effect)
        tc = {"id": f"c{name}", "type": "function", "function": {"name": name, "arguments": json.dumps(args) if isinstance(args, dict) else args}}
        return {"choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [tc]}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 10}}
    return chat


def test_eval_run_success_and_metrics(world, game):
    chat = scripted(world, [
        ("status", {}, None),
        ("nonexistent_tool", {}, None),
        ("build", "{not json", None),
        ("build", {"entity": "stone-furnace", "x": 5, "y": 5}, None),
        ("inspect", {"x": 1, "y": 1}, "mock.give('iron-plate', 10)"),
    ])
    r = evaluation.run_scenario(evaluation.SCENARIOS["S1"], game, chat, max_steps=10, profile="core")
    server.apply_profile("full")
    assert r.success and r.end_reason == "goal reached"
    assert r.tool_calls == 5 and r.bad_calls == 2
    assert r.err_replies >= 3  # bad calls + build without item + inspect on nothing
    assert r.prompt_tokens == 500 and r.tools_used["build"] == 2


def test_eval_run_stops_when_model_gives_up(world, game):
    chat = scripted(world, [("status", {}, None)])
    r = evaluation.run_scenario(evaluation.SCENARIOS["S4"], game, chat, max_steps=10)
    server.apply_profile("full")
    assert not r.success and r.end_reason == "model stopped"
    assert "S4: 0/1 success" in evaluation.summary([r])


def test_scenario_checks_in_mock(world, game):
    world.exec("mock.add_patch('iron-ore', 20, 20, 30, 30, 100)")
    world.exec("for i=0,5 do mock.add_entity('transport-belt', 0.5+i, 0.5, 4) end")
    world.exec("mock.add_entity('stone-furnace', 10, 10); mock.add_entity('burner-mining-drill', 21, 21)")
    assert evaluation.s5_belt(game)
    assert not evaluation.s2_miners(game)
    assert not evaluation.s3_power(game)
