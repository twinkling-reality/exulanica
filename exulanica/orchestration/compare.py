"""Run the same hour of a saved world with two open models and score it: the local command.

    EXULANICA_BUDGET_USD=<bound> python -m exulanica.orchestration.compare \\
        --workspace <uuid> --world <world id> --version <uuid> --actor <uuid> \\
        --model <provider>/<model id> [--model <provider>/<model id>] [--control] \\
        --seeds <file> [--seed-count <n>]

It defines a comparison over the version's purposeful society as it stands, with the routine and
waiting as its two anchors, one arm per ``--model`` and, with ``--control``, the first model run a
second time; reserves every run, one per arm and seed; plays them; and prints what the page shows
of it: each arm's score, the registered differences and the server's verdict. A comparison this
command defines runs on development seeds and is never judged: a judged comparison is
pre-registered, and its record is written by the measurement that registered it.

``--seeds`` names a file of seeds, one per line. A seed is used only when the SHA-256 of its text
is one the seed catalog commits to the development phase; the first ``--seed-count`` of those,
in the catalog's order, are run. Nothing prints a seed.

The model's key is read from the environment by the application's own client, and the bound is
``EXULANICA_BUDGET_USD``, which this command requires rather than defaulting: every ask of every
run is within it, and a run the bound stops is recorded as failed by name. The database is the one
``EXULANICA_DATABASE_URL`` names, as the runtime role.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

from exulanica.api.services import build_services
from exulanica.api.society_comparison_runner import ComparisonArm, SocietyComparisonRunner
from exulanica.models.usage import usd_string
from exulanica.world.society_catalogs import load_comparison_catalogs
from exulanica.world.society_comparison_repository import seed_digest
from exulanica.world.society_comparison_result import comparison_result, protocol_value

__all__ = ["comparison_body", "development_seeds", "main"]

BUDGET_VARIABLE: Final = "EXULANICA_BUDGET_USD"
#: The phase a comparison this command defines runs on.
PHASE: Final = "development"
#: The anchor arms every comparison runs, by key.
ROUTINE_ARM: Final = "routine"
WAIT_ARM: Final = "wait"


def development_seeds(path: Path, count: int) -> list[str]:
    """The first ``count`` development seeds the catalog commits to, read from ``path``.

    Only lines whose digest the catalog commits to the development phase are used, in the
    catalog's order; a committed seed missing from the file, when it is needed, is refused.
    """
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


def comparison_body(
    runner: SocietyComparisonRunner,
    models: Sequence[ComparisonArm],
    seeds: Sequence[str],
    *,
    control: bool,
    phase: str = PHASE,
    preregistration: dict[str, str] | None = None,
) -> dict[str, Any]:
    """A definition's body: the anchors, one arm per model, the control, and the claim."""
    catalogs = runner.catalogs
    arms: dict[str, dict[str, Any]] = {
        ROUTINE_ARM: {
            "role": "one",
            "decider": {"kind": "routine"},
            "provider_config": None,
            "description": "Their own routine",
        },
        WAIT_ARM: {
            "role": "zero",
            "decider": {"kind": "wait"},
            "provider_config": None,
            "description": "Waiting where they are",
        },
    }
    keys = []
    for index, model in enumerate(models):
        key = f"model_{chr(ord('a') + index)}"
        arms[key] = runner.model_arm(model, "candidate")
        keys.append(key)
    control_pair = None
    if control:
        arms[f"{keys[0]}_again"] = runner.model_arm(models[0], "control")
        control_pair = [keys[0], f"{keys[0]}_again"]
    family = [[ROUTINE_ARM, key] for key in keys]
    primary = family[0]
    if len(keys) >= 2:
        primary = [keys[0], keys[1]]
        family = [primary, *family]
    return {
        "window_ticks": protocol_value(catalogs, "window_ticks"),
        "phase": phase,
        "seeds": [seed_digest(seed) for seed in seeds],
        "arms": arms,
        "claim": {"primary": primary, "family": family, "control": control_pair},
        "preregistration": preregistration,
    }


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
        "arms": {
            arm["key"]: {
                "description": arm["description"],
                "role": arm["role"],
                "mean_score": result["summaries"][arm["key"]]["mean_score"],
                "interval": result["summaries"][arm["key"]]["interval"],
                "runs": [seed["runs"][arm["key"]]["status"] for seed in result["seeds"]],
            }
            for arm in result["arms"]
        },
        "differences": result["differences"],
        "verdict": result["verdict"],
        "spent_usd": usd_string(spent),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--workspace", type=uuid.UUID, required=True)
    parser.add_argument("--world", required=True)
    parser.add_argument("--version", type=uuid.UUID, required=True)
    parser.add_argument("--actor", type=uuid.UUID, required=True)
    parser.add_argument("--model", action="append", required=True, help="<provider>/<model id>")
    parser.add_argument("--control", action="store_true", help="run the first model twice")
    parser.add_argument("--seeds", type=Path, required=True)
    parser.add_argument("--seed-count", type=int, default=1)
    parser.add_argument("--comparison", type=uuid.UUID, default=None)
    arguments = parser.parse_args(argv)
    if not os.environ.get(BUDGET_VARIABLE):
        raise SystemExit(f"{BUDGET_VARIABLE} must state this command's bound")
    if not 1 <= len(arguments.model) <= 2 or arguments.seed_count < 1:
        raise SystemExit("one or two models, and at least one seed")
    models = []
    for named in arguments.model:
        provider, _, model_id = named.partition("/")
        if not provider or not model_id:
            raise SystemExit(f"--model {named!r} is not <provider>/<model id>")
        models.append(ComparisonArm(provider=provider, model_id=model_id))
    services = build_services()
    runner = services.comparison_runner(arguments.workspace, arguments.world, arguments.actor)
    if runner is None:
        raise SystemExit("this environment configures no society runtime")
    seeds = development_seeds(arguments.seeds, arguments.seed_count)
    comparison_id = arguments.comparison or uuid.uuid4()
    runner.define(
        arguments.version,
        comparison_id=comparison_id,
        body=comparison_body(runner, models, seeds, control=arguments.control),
    )
    runner.run_all(comparison_id, runner.reserve_all(comparison_id, seeds))
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
