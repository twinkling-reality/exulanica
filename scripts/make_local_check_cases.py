#!/usr/bin/env python3
"""The requests a model on this computer is checked by before a person may choose it (L1).

    uv run python scripts/make_local_check_cases.py

Writes ``assets/catalogs/local-check/local-check-cases.v1.json``: two requests of the people's role, built exactly as
``scripts/measure_society_mind_probe.py`` builds its first plain case and its first line case, from the tests' own
starter square (a knight alone, whose choice takes no line; a knight beside one person who hears it, whose choice
takes one). No person's data is in them. ``exulanica.models.local_runner`` asks a runner's model these, through the
role's own messages and JSON schema, and offers it only where it answers both as the host takes an answer.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from exulanica.canonical import canonical_json  # noqa: E402

#: The engine the people's role is asked under in a town: the probe's own.
ENGINE: Final = "exulanica-society/v7"
OUTPUT: Final = ROOT / "assets/catalogs/local-check/local-check-cases.v1.json"
#: How far the people who must not hear the knight stand from it, as the probe places them.
FAR_MM: Final = 30_000


def cases() -> list[dict]:
    from exulanica.world.society_decision_contract import (
        choice_options,
        decision_context,
        person_role,
    )
    from exulanica.world.society_things import initial_things_society

    from things_society_support import SEED, SOCIETY, compose, thing

    role = person_role()
    contract = role.contract(role.terms(ENGINE).versions)
    gate = thing("gate", "gate", 1, 0, 9_000, yaw=3_141_593)
    knight = thing("knight", "knight", 1, -6_000, 3_000)
    document = compose((gate, knight))
    built = []
    for plain in (True, False):
        state = copy.deepcopy(initial_things_society(SOCIETY, SEED, document, population=6))
        placed = next(p for p in state["inhabitants"] if p["came_by"] == "placed")
        others = [p for p in state["inhabitants"] if p["came_by"] == "populated"]
        if plain:
            for offset, person in enumerate(others):
                person["position_mm"] = [
                    placed["position_mm"][0] + FAR_MM + 1_000 * offset,
                    placed["position_mm"][1] + FAR_MM,
                ]
        else:
            person = others[0]
            person["position_mm"] = [placed["position_mm"][0] + 1_500, placed["position_mm"][1]]
        options = choice_options(state, document, placed["id"], contract, seed=SEED)
        context = decision_context(state, document, placed["id"], options)
        if role.takes_line(context) == plain:
            raise SystemExit("a case is not the shape its place names")
        built.append(context)
    return built


def document() -> dict:
    """The catalog as this file writes it: the cases, the terms they are asked under and their
    digest."""
    from exulanica.world.society_decision_contract import person_role

    role = person_role()
    built = cases()
    made = {
        "profile": "exulanica.local-check-cases/v1",
        "role": role.key,
        "engine": ENGINE,
        "contract_versions": dict(sorted(role.terms(ENGINE).versions.items())),
        "made_by": "scripts/make_local_check_cases.py",
        "reason": (
            "Two requests of the people's role from the tests' own starter square, built as the recorded mind "
            "probe builds its first plain and first line case: what a model on this computer is checked by "
            "before a person may choose it. No person's data is in them."
        ),
        "cases": built,
    }
    made["cases_sha256"] = hashlib.sha256(canonical_json(built)).hexdigest()
    return made


def main() -> None:
    made = document()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(made, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"wrote {OUTPUT.relative_to(ROOT)}: {len(made['cases'])} cases, "
        f"sha256 {made['cases_sha256'][:12]}"
    )


if __name__ == "__main__":
    main()
