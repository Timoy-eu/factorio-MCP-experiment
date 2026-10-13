"""Rule based "what should I do next" for the early game.

Small models plan badly, so the server does the planning and only asks them to execute.
"""

from __future__ import annotations

from typing import Any

from .game import as_map

SMELT_PLAN = "craft stone-furnace, build it, insert iron-ore, fuel it, wait a bit, collect"


def _placed_count(placed: dict[str, Any], name: str) -> int:
    return int(as_map(placed.get(name)).get("n", 0))


def _problem_count(placed: dict[str, Any], problem: str) -> int:
    total = 0
    for entry in placed.values():
        total += int(as_map(as_map(entry).get("status")).get(problem, 0))
    return total


def next_steps(inventory: dict[str, int], placed: dict[str, Any], research: str | None,
               limit: int = 3) -> list[str]:
    inv = as_map(inventory)
    placed = as_map(placed)

    def have(name: str) -> int:
        return int(inv.get(name, 0))

    drills = _placed_count(placed, "burner-mining-drill")
    drills_total = drills + have("burner-mining-drill")
    furnaces_placed = _placed_count(placed, "stone-furnace")
    furnaces_total = furnaces_placed + have("stone-furnace")
    plates = have("iron-plate")
    steps: list[str] = []

    if _problem_count(placed, "no_fuel") > 0:
        steps.append("fuel (some machines are out of fuel)" if have("coal") + have("wood") > 0
                     else "gather coal 20, then fuel (some machines are out of fuel)")
    if have("coal") < 10 and not steps:
        steps.append("gather coal 20")
    if have("stone") < 10 and furnaces_total < 2:
        steps.append("gather stone 10")
    if have("iron-ore") + plates < 20 and drills_total == 0:
        steps.append("gather iron-ore 20")
    if have("iron-ore") >= 5 and plates < 10 and furnaces_placed == 0:
        steps.append("smelt iron: " + SMELT_PLAN)
    if drills_total == 0 and plates >= 9 and furnaces_total >= 1:
        steps.append("craft burner-mining-drill")
    if have("burner-mining-drill") > 0 and have("stone-furnace") > 0:
        steps.append("build_miner iron-ore")
    if _problem_count(placed, "no_power") > 0:
        steps.append("connect kind=power from your steam-engine to the machines with no_power (overview shows them)")
    if _problem_count(placed, "full_output") > 0:
        steps.append("collect, or add an inserter/belt that takes items out (some machines have full_output)")
    if drills >= 1 and drills < 4:
        steps.append("collect plates, then craft burner-mining-drill and build_miners ore=iron-ore count=2 (aim for 4)")
    has_power = _placed_count(placed, "steam-engine") > 0
    if drills >= 4 and not has_power:
        parts = ("offshore-pump", "boiler", "steam-engine")
        missing = [p for p in parts if have(p) == 0]
        if missing:
            steps.append("prepare power: craft " + ", ".join(missing) + " and 10 small-electric-pole (guide topic=power)")
        else:
            steps.append("build power: find what=water, build offshore-pump at the shore, boiler, steam-engine, "
                         "connect kind=pipe, fuel the boiler (guide topic=power)")
    labs = _placed_count(placed, "lab")
    if has_power and labs == 0:
        steps.append("craft lab, build it near a pole, connect kind=power")
    if labs > 0 and have("automation-science-pack") < 10 and not research:
        steps.append("craft item=automation-science-pack count=10, insert it into the lab, research name=automation")
    elif labs > 0 and not research:
        steps.append("research name=automation (or research to list options)")
    if not steps:
        steps.append("look around, then gather what is missing for your next craft")
    return steps[:limit]
