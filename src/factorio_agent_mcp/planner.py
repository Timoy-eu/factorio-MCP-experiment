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
    if drills >= 1:
        steps.append("collect plates from the furnaces, then craft more burner-mining-drill (aim for 4)")
    if not research and drills >= 2:
        steps.append("research automation (needs a lab and power, check research)")
    if not steps:
        steps.append("look around, then gather what is missing for your next craft")
    return steps[:limit]
