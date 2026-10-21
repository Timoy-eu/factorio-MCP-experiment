"""Trains: geometry (pure Lua under lupa), tool registration and the texts. The game behaviour was verified in a real Factorio."""

from __future__ import annotations

from factorio_agent_mcp import guide, render, server
from factorio_agent_mcp.game import GameError

from conftest import LuaWorld


def test_geometry_stop_is_on_the_right_of_the_travel_direction():
    w = LuaWorld()
    for travel, expect in {"east": (0, 2), "west": (0, -2), "south": (-2, 0), "north": (2, 0)}.items():
        got = w.eval(f'(function() local T = require("scripts.trains") local x, y = T.geometry.stop_position(10, 20, "{travel}") return x .. "," .. y end)()')
        assert got == f"{10 + expect[0]},{20 + expect[1]}", travel


def test_geometry_cars_line_up_behind_the_front():
    w = LuaWorld()
    for travel, step in {"east": (-7, 0), "west": (7, 0), "south": (0, -7), "north": (0, 7)}.items():
        got = w.eval(f'(function() local T = require("scripts.trains") local x, y = T.geometry.stock_position(0, 0, "{travel}", 2) return x .. "," .. y end)()')
        assert got == f"{step[0] * 2},{step[1] * 2}", travel


def test_tools_are_registered_and_in_the_guide():
    for name in ("build_station", "build_train", "train_schedule", "train_status"):
        assert name in server.REGISTRY
    text = guide.text("trains")
    assert "build_station" in text and "ONE station" in text
    assert "trains" in guide.ORDER and "train_status" in guide.tools_text()


def test_texts():
    s = render.station_text({"name": "Mine", "x": 3, "y": 5, "direction": "east", "note": "trains travelling east stop here"})
    assert "'Mine'" in s and "(3,5)" in s and "east" in s
    t = render.train_text({"train_id": 7, "cars": 3, "locomotives": 1, "wagons": 2, "direction": "east", "x": -12, "y": 4, "fuel": 20, "fuel_item": "coal"})
    assert "train 7" in t and "1 locomotive + 2 wagon" in t and "train_schedule" in t
    assert "WARNING" in render.train_text({"train_id": 1, "cars": 1, "locomotives": 1, "direction": "east", "x": 0, "y": 0, "fuel": 0,
                                           "fuel_item": "coal", "warning": "no coal in your inventory, the train has no fuel"})
    sch = render.schedule_text({"train_id": 7, "stations": ["A", "B"], "wait": 5, "state": "on_the_path"})
    assert "A -> B -> A" in sch and "5 s" in sch
    one = render.schedule_text({"train_id": 7, "stations": ["A"], "wait": 2, "state": "on_the_path", "note": "with one station the train drives there and stays"})
    assert "NOTE" in one and "->" not in one
    status = render.train_status_text({"train_id": 7, "state": "wait_station", "station": "A", "speed_kmh": 0, "cars": 2, "locomotives": 1, "fuel": 0,
                                       "x": 1, "y": 2, "manual": False, "schedule": ["A", "B"], "driver": False})
    assert "wait_station at station 'A'" in status and "A -> B" in status and "no fuel" in status


def test_error_hints():
    for code in ("no_rail", "no_site", "bad_count", "not_coupled", "no_train", "no_station"):
        assert " | try:" in render.error_text(GameError(code, "x", {}))
