import pytest

from factorio_agent_mcp.game import Game, GameError, parse_reply
from factorio_agent_mcp.luacall import lua_literal, lua_string, remote_call
from factorio_agent_mcp.planner import next_steps
from factorio_agent_mcp.rcon import Rcon, RconError

from conftest import PASSWORD, FakeRconServer


def test_lua_string_escapes_quotes_and_control_chars():
    assert lua_string('a"b\\c\nd') == '"a\\"b\\\\c\\nd"'
    assert lua_string("x\x00y") == '"x\\000y"'


def test_lua_literal_types():
    assert lua_literal(None) == "nil"
    assert lua_literal(True) == "true"
    assert lua_literal(3) == "3"
    assert lua_literal(2.5) == "2.5"
    with pytest.raises(ValueError):
        lua_literal(float("nan"))
    with pytest.raises(TypeError):
        lua_literal({1})


def test_remote_call_format():
    cmd = remote_call("build", "stone-furnace", 1.0, -2.5, "auto", 2)
    assert cmd == ('/silent-command rcon.print(remote.call("fac_agent", "build", '
                   '"stone-furnace", 1.0, -2.5, "auto", 2))')
    with pytest.raises(ValueError):
        remote_call('x"); os.exit(')


def test_rcon_reassembles_multi_packet_answers():
    big = "x" * 9500
    server = FakeRconServer(lambda body: big if "big" in body else "", chunk=4000)
    try:
        rcon = Rcon("127.0.0.1", server.port, PASSWORD, timeout=5)
        assert rcon.command("/silent-command big") == big
        assert rcon.command("/silent-command small") == ""
        rcon.close()
    finally:
        server.close()


def test_rcon_wrong_password():
    server = FakeRconServer(lambda body: "")
    try:
        rcon = Rcon("127.0.0.1", server.port, "nope", timeout=5)
        with pytest.raises(RconError, match="authentication"):
            rcon.command("/silent-command rcon.print('x')")
    finally:
        server.close()


def test_rcon_reconnects_after_dropped_connection():
    server = FakeRconServer(lambda body: "pong")
    try:
        rcon = Rcon("127.0.0.1", server.port, PASSWORD, timeout=5)
        assert rcon.command("/silent-command ping") == "pong"
        rcon._sock.close()  # simulate a dead socket on our side
        assert rcon.command("/silent-command ping") == "pong"
        assert server.connections == 2
        rcon.close()
    finally:
        server.close()


def test_rcon_connect_failure_is_reported():
    rcon = Rcon("127.0.0.1", 1, "x", timeout=1)
    with pytest.raises(RconError, match="cannot connect"):
        rcon.command("/silent-command x")


def test_parse_reply_errors():
    with pytest.raises(GameError) as exc:
        parse_reply("")
    assert exc.value.code == "no_response"
    with pytest.raises(GameError) as exc:
        parse_reply("Cannot execute command. Error: Unknown interface: fac_agent")
    assert exc.value.code == "mod_missing"
    with pytest.raises(GameError) as exc:
        parse_reply("garbage")
    assert exc.value.code == "bad_response"


def test_game_wraps_failure_replies():
    class Fake:
        def command(self, text):
            return '{"ok":false,"code":"blocked","message":"nope","blocked_by":["rock-big"]}'

    with pytest.raises(GameError) as exc:
        Game(Fake()).call("build", "x", 1, 2, "auto")
    assert exc.value.code == "blocked"
    assert exc.value.data["blocked_by"] == ["rock-big"]


def test_planner_early_game_order():
    assert next_steps({}, {}, None)[0] == "gather coal 20"
    steps = next_steps({"coal": 20}, {}, None)
    assert "gather stone 10" in steps
    steps = next_steps({"coal": 20, "stone": 10, "iron-ore": 10}, {}, None)
    assert any(s.startswith("smelt iron") for s in steps)
    assert "craft burner-mining-drill" in next_steps(
        {"coal": 20, "stone": 20, "iron-plate": 12, "stone-furnace": 1}, {}, None)
    assert "build_miner iron-ore" in next_steps(
        {"coal": 20, "burner-mining-drill": 1, "stone-furnace": 1, "iron-plate": 25}, {}, None)


def test_planner_prioritises_refuelling():
    placed = {"burner-mining-drill": {"n": 1, "status": {"no_fuel": 1}}}
    assert next_steps({"coal": 12}, placed, None)[0].startswith("fuel")
    assert next_steps({}, placed, None)[0].startswith("gather coal 20, then fuel")
