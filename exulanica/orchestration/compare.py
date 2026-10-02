"""Run the same hour, or day, of a saved world with two open models and score it: the local command.

    EXULANICA_BUDGET_USD=<bound> python -m exulanica.orchestration.compare \\
        --workspace <uuid> --world <world id> --version <uuid> --actor <uuid> \\
        --model <provider>/<model id> [--model <provider>/<model id>] [--control] \\
        [--group-choice <n> | --group <person id> [--group <person id> ...]] \\
        [--seeds <file>] [--seed-count <n>] [--window hour|day]

It defines a comparison over the version's purposeful society as it stands, with the routine and
waiting as its two anchors, one arm per ``--model`` and, with ``--control``, the first model run a
second time; reserves every run, one per arm and seed; plays them, the anchors first; and prints
what the page shows of it: each arm's score with what its model answered, the registered
differences and the server's verdict. Every arm decides for one group: everybody, the people the
world owner's choice ``--group-choice`` named, or the people ``--group`` names; everybody else
keeps what the owner's latest choice for them names, a model or their routine, in every arm. A
comparison this command defines runs on development seeds and is never judged: a judged comparison
is pre-registered, and its record is written by the measurement that registered it.

With ``--window day`` every run plays the society's whole day hour by hour, for a society whose
engine keeps a day, and a run the command stopped part way goes on from the last hour it sealed
when the command is run again with the same ``--comparison``, asking only what it did not record.

The first ``--seed-count`` development seeds, in the seed catalog's order, are run: the catalog
commits their text. ``--seeds`` may name a file of seeds instead, one per line, of which a seed is
used only when the SHA-256 of its text is one the seed catalog commits to the development phase.
Nothing prints a seed.

The model's key is read from the environment by the application's own client, and the bound is
``EXULANICA_BUDGET_USD``, which this command requires rather than defaulting: every ask of every
run is within it, and a run the bound stops is recorded as failed by name. The database is the one
``EXULANICA_DATABASE_URL`` names, as the runtime role.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import uuid
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

from exulanica.api.services import build_services
from exulanica.api.society_comparison_runner import ComparisonArm
from exulanica.api.society_comparison_start import (
    PHASE,
    ComparisonSelection,
    StartRefused,
    comparison_body,
    definition_body,
    window_catalogs,
)
from exulanica.api.society_comparison_start import development_seeds as committed_seeds
from exulanica.models.usage import usd_string
from exulanica.world.society_catalogs import COMPARISON_WINDOWS, load_comparison_catalogs
from exulanica.world.society_comparison_repository import seed_digest
from exulanica.world.society_comparison_result import comparison_result

__all__ = ["comparison_body", "development_seeds", "main", "parser", "selection"]

BUDGET_VARIABLE: Final = "EXULANICA_BUDGET_USD"


def development_seeds(path: Path | None, count: int) -> list[str]:
    """The first ``count`` development seeds the catalog commits to: their committed text, or,
    where ``path`` names a file, read from it.

    Only lines whose digest the catalog commits to the development phase are used, in the
    catalog's order; a committed seed missing from the file, when it is needed, is refused.
    """
    if path is None:
        found_seeds = list(committed_seeds(load_comparison_catalogs())[:count])
        if len(found_seeds) < count:
            raise SystemExit(f"the seed catalog commits fewer than {count} development seeds")
        return found_seeds
    committed = [
        str(entry["seed_digest"])
        for entry in load_comparison_catalogs().seeds.values()
        if entry["phase"] == PHASE
    ]
    found = {
        seed_digest(line.strip()): line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    wanted = committed[:count]
    if len(wanted) < count or any(digest not in found for digest in wanted):
        raise SystemExit(f"{path} does not hold the first {count} committed development seeds")
    return [found[digest] for digest in wanted]


def _summary(result: dict[str, Any]) -> dict[str, Any]:
    """What the page shows of a comparison, with no seed: scores, differences and the verdict."""
    spent = sum(
        (
            Decimal(run["calls"]["cost_usd"])
            for seed in result["seeds"]
            for run in seed["runs"].values()
            if run["calls"] is not None
        ),
        Decimal(0),
    )
    return {
        "comparison_id": result["comparison_id"],
        "group": result["group"],
        "arms": {
            arm["key"]: {
                "description": arm["description"],
                "role": arm["role"],
                "mean_score": result["summaries"][arm["key"]]["mean_score"],
                "interval": result["summaries"][arm["key"]]["interval"],
                "reliability": result["summaries"][arm["key"]]["reliability"],
                "runs": [seed["runs"][arm["key"]]["status"] for seed in result["seeds"]],
            }
            for arm in result["arms"]
        },
        "differences": result["differences"],
        "verdict": result["verdict"],
        "spent_usd": usd_string(spent),
    }


def parser() -> argparse.ArgumentParser:
    """The command's arguments."""
    held = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    held.add_argument("--workspace", type=uuid.UUID, required=True)
    held.add_argument("--world", required=True)
    held.add_argument("--version", type=uuid.UUID, required=True)
    held.add_argument("--actor", type=uuid.UUID, required=True)
    held.add_argument("--model", action="append", required=True, help="<provider>/<model id>")
    held.add_argument("--control", action="store_true", help="run the first model twice")
    chosen = held.add_mutually_exclusive_group()
    chosen.add_argument(
        "--group-choice", type=int, default=None, help="the owner's choice whose people to swap"
    )
    chosen.add_argument(
        "--group", action="append", default=None, help="a person to swap, by subject id"
    )
    held.add_argument("--seeds", type=Path, default=None)
    held.add_argument("--seed-count", type=int, default=1)
    held.add_argument("--comparison", type=uuid.UUID, default=None)
    held.add_argument("--window", choices=COMPARISON_WINDOWS, default="hour")
    return held


def selection(arguments: argparse.Namespace) -> ComparisonSelection:
    """What the arguments compare, as the one definition path takes it; a model not named as
    ``<provider>/<model id>``, and more than two models or no seed, are refused by the command."""
    if not 1 <= len(arguments.model) <= 2 or arguments.seed_count < 1:
        raise SystemExit("one or two models, and at least one seed")
    models = []
    for named in arguments.model:
        provider, _, model_id = named.partition("/")
        if not provider or not model_id:
            raise SystemExit(f"--model {named!r} is not <provider>/<model id>")
        models.append(ComparisonArm(provider=provider, model_id=model_id))
    return ComparisonSelection(
        models=tuple(models),
        control=arguments.control,
        group="owner_choice"
        if arguments.group_choice is not None
        else "named"
        if arguments.group is not None
        else "everyone",
        seed_count=arguments.seed_count,
        choice_seq=arguments.group_choice,
        people=None if arguments.group is None else tuple(arguments.group),
    )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    if not os.environ.get(BUDGET_VARIABLE):
        raise SystemExit(f"{BUDGET_VARIABLE} must state this command's bound")
    selected = selection(arguments)
    services = build_services()
    runner = services.comparison_runner(arguments.workspace, arguments.world, arguments.actor)
    if runner is None:
        raise SystemExit("this environment configures no society runtime")
    with services.database.session(arguments.workspace) as connection:
        society = runner._repository(connection).society._row(arguments.version)
    if society is None:
        raise SystemExit("the version holds no society")
    try:
        runner = dataclasses.replace(
            runner,
            catalogs=window_catalogs(
                services.comparison_catalogs, arguments.window, str(society["engine_version"])
            ),
        )
    except StartRefused as exc:
        raise SystemExit(str(exc)) from exc
    seeds = development_seeds(arguments.seeds, arguments.seed_count)
    comparison_id = arguments.comparison or uuid.uuid4()
    runner.define(
        arguments.version,
        comparison_id=comparison_id,
        body=definition_body(runner, arguments.version, selected, seeds),
    )
    run_ids = runner.reserve_all(comparison_id, seeds)
    runner.run_all(comparison_id, run_ids)
    runner.draw_all(comparison_id)
    with services.database.session(arguments.workspace) as connection:
        repository = runner._repository(connection)
        row = repository.definition(arguments.version, comparison_id)
        result = comparison_result(
            row, repository.runs(comparison_id), model_name=runner.manifest.model_name
        )
    json.dump(_summary(result), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
