"""What tests of a comparison of models share: seeds of their own, and a development definition.

A comparison runs only seeds the seed catalog commits to its phase, and the committed catalog names
its seeds by digest alone. Tests commit seeds of their own to a copy of the catalogs, which the
runner and the repository take in place of the committed ones; nothing here changes a file.
"""

from __future__ import annotations

import dataclasses
import hashlib
from typing import Any

from exulanica.models.manifest import Role, load_manifest
from exulanica.world.society_catalogs import ComparisonCatalogs, load_comparison_catalogs
from exulanica.world.society_decision_contract import PROMPT_VERSION, decision_contract

#: The seeds tests run, committed to the development phase of a test copy of the catalogs.
SEEDS = ("d1" * 32, "d2" * 32)


def seeded_catalogs(*, population_maximum: int | None = None) -> ComparisonCatalogs:
    """The committed catalogs with :data:`SEEDS` committed to the development phase, and, for a
    society larger than a saved world's, a larger population bound."""
    committed = load_comparison_catalogs()
    seeds = {
        f"test_{index}": {
            "phase": "development",
            "seed_digest": hashlib.sha256(seed.encode()).hexdigest(),
            "reason": "A seed the tests run.",
        }
        for index, seed in enumerate(SEEDS, 1)
    }
    protocol = dict(committed.protocol)
    if population_maximum is not None:
        protocol["population_maximum"] = {
            **protocol["population_maximum"],
            "value": population_maximum,
        }
    return dataclasses.replace(committed, seeds=seeds, protocol=protocol)


def model_arm(role: str) -> dict[str, Any]:
    """An arm run by the first model the manifest offers a person's decisions."""
    contract = decision_contract()
    spec = load_manifest().offered_models(Role.SOCIETY_DECISION)[0]
    mechanism = contract.mechanism_for(spec)
    assert mechanism is not None
    return {
        "role": role,
        "decider": {"kind": "model", "provider": spec.provider, "model_id": spec.model_id},
        "provider_config": {
            "provider": spec.provider,
            "model_id": spec.model_id,
            "mechanism": mechanism.value,
            "choice_seq": None,
            "manifest_sha256": "a" * 64,
            "prompt_version": PROMPT_VERSION,
            "contract": contract.binding(),
            "deadline_ms": contract.value("decision_deadline_ms"),
        },
        "description": spec.description,
    }


def development_body(catalogs: ComparisonCatalogs) -> dict[str, Any]:
    """A development comparison of one model against its anchors over :data:`SEEDS`."""
    return {
        "window_ticks": int(catalogs.protocol["window_ticks"]["value"]),  # type: ignore[call-overload]
        "phase": "development",
        "seeds": [hashlib.sha256(seed.encode()).hexdigest() for seed in SEEDS],
        "arms": {
            "routine": {
                "role": "one",
                "decider": {"kind": "routine"},
                "provider_config": None,
                "description": "Their own routine",
            },
            "wait": {
                "role": "zero",
                "decider": {"kind": "wait"},
                "provider_config": None,
                "description": "Waiting where they are",
            },
            "model_a": model_arm("candidate"),
        },
        "claim": {
            "primary": ["routine", "model_a"],
            "family": [["routine", "model_a"]],
            "control": None,
        },
        "preregistration": None,
    }
