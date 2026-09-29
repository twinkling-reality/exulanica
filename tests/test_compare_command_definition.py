"""The local command defines what it always defined, through the one definition path.

The command (``python -m exulanica.orchestration.compare``) and the application's start route
define a comparison through one path (:mod:`exulanica.api.society_comparison_start`). For every set
of the command's existing flags, the body it defines is held here to the one its own steps defined
before that path existed (main at 3bf3ce4b): parsing the models, resolving the group from an
owner's choice or the people named, everybody else from the owner's latest choices, then the arms
and the claim. :class:`_Reference` is a frozen copy of those steps, never imported from the code it
checks; it was checked to reproduce the command's bodies at 3bf3ce4b byte for byte over the same
world. Both sides read the live manifest and contract, so a change to a model's entry moves both,
and only a change to how the command defines a comparison fails here. The world's facts, its people
and the owner's choices, are fixed, since reading them is the repository's, checked where a
definition is stored.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from typing import Any

import pytest
from exulanica.api.society_comparison_runner import ComparisonArm, SocietyComparisonRunner
from exulanica.api.society_comparison_start import definition_body
from exulanica.models.errors import ManifestError
from exulanica.models.manifest import load_manifest
from exulanica.orchestration import compare
from exulanica.world.society_comparison_repository import seed_digest
from exulanica.world.society_comparison_result import protocol_value
from exulanica.world.society_decision_contract import (
    PROMPT_VERSION,
    decision_contract,
    person_role,
)

MANIFEST = load_manifest()
OFFERED = MANIFEST.offered_models(person_role().chosen)
M1 = f"{OFFERED[0].provider}/{OFFERED[0].model_id}"
M2 = f"{OFFERED[1].provider}/{OFFERED[1].model_id}"
SEEDS = ["d1" * 32, "d2" * 32]
VERSION = uuid.UUID("00000000-0000-4000-8000-000000000001")
PEOPLE = sorted(str(uuid.uuid5(uuid.NAMESPACE_URL, f"person:{index}")) for index in range(8))
CHOICE = {"choice_seq": 3, "document_sha256": "c" * 64}
#: The command's existing flags, beyond the world, the actor and the seeds file, in each case.
CASES = {
    "one_model": ["--model", M1],
    "two_models": ["--model", M1, "--model", M2],
    "two_models_control": ["--model", M1, "--model", M2, "--control"],
    "one_model_control": ["--model", M1, "--control"],
    "same_model_twice": ["--model", M1, "--model", M1],
    "owner_choice": ["--model", M1, "--model", M2, "--group-choice", "3"],
    "named": ["--model", M2, "--group", PEOPLE[6], "--group", PEOPLE[2], "--group", PEOPLE[6]],
}
REQUIRED = [
    "--workspace",
    str(uuid.UUID(int=0)),
    "--world",
    "world:fixed",
    "--version",
    str(VERSION),
    "--actor",
    str(uuid.UUID(int=0)),
    "--seeds",
    "seeds.txt",
]


def _others(model: Any) -> Any:
    """The world's owner's choices for everybody outside a group: the second model for the first
    of them, by choice 4, and their routine for the rest. ``model`` is the side's own reading of a
    model a person outside the group is asked of."""

    def others(group: Sequence[str] | None) -> list[dict[str, Any]]:
        if group is None:
            return []
        outside = sorted(set(PEOPLE) - set(group))
        provider, _, model_id = M2.partition("/")
        decider, config, answering, _spec = model(ComparisonArm(provider, model_id), 4)
        return [
            {
                "id": subject,
                "decider": decider if index == 0 else {"kind": "routine"},
                "provider_config": config if index == 0 else None,
                "answering": answering if index == 0 else None,
                "choice": {"choice_seq": 4, "document_sha256": "e" * 64} if index == 0 else None,
            }
            for index, subject in enumerate(outside)
        ]

    return others


class _World(SocietyComparisonRunner):
    """The runner of today, over the fixed world: its own reading of models, the world's facts
    fixed."""

    def group_of_choice(self, version_id, choice_seq, *, connection=None):
        assert (version_id, choice_seq) == (VERSION, CHOICE["choice_seq"])
        return {"people": PEOPLE[:4], "source": {"kind": "owner_choice", **CHOICE}}

    def others_for(self, version_id, group, *, connection=None):
        assert version_id == VERSION
        return _others(self._model)(group)


def _runner() -> _World:
    return _World(
        database=None,  # type: ignore[arg-type]
        runtime=None,  # type: ignore[arg-type]
        client=None,
        policy_for=None,  # type: ignore[arg-type]
        manifest=MANIFEST,
        manifest_sha256="a" * 64,
        workspace_id=uuid.UUID(int=0),
        world_id="world:fixed",
        actor=uuid.UUID(int=0),
    )


class _Reference:
    """The command's definition steps at 3bf3ce4b, frozen: how it read a model, an arm and the
    body, and how its main() resolved the group, over the same fixed world."""

    catalogs = _runner().catalogs

    @staticmethod
    def model(arm: ComparisonArm, choice_seq: int | None) -> tuple[dict, dict, dict, Any]:
        contract = decision_contract()
        try:
            spec = MANIFEST.offered(person_role().chosen, arm.model_id)
        except ManifestError as exc:
            raise ValueError(f"{arm.model_id} is not offered for a person's decisions") from exc
        mechanism = contract.mechanism_for(spec)
        answering = contract.answering(spec)
        if spec.provider != arm.provider or mechanism is None or answering is None:
            raise ValueError(f"{arm.provider}/{arm.model_id} is not askable under the contract")
        decider = {"kind": "model", "provider": spec.provider, "model_id": spec.model_id}
        config = {
            "provider": spec.provider,
            "model_id": spec.model_id,
            "mechanism": mechanism.value,
            "choice_seq": choice_seq,
            "manifest_sha256": "a" * 64,
            "prompt_version": PROMPT_VERSION,
            "contract": contract.binding(),
            "deadline_ms": contract.value("decision_deadline_ms"),
        }
        return decider, config, answering, spec

    @classmethod
    def model_arm(cls, arm: ComparisonArm, role: str) -> dict[str, Any]:
        decider, config, answering, spec = cls.model(arm, None)
        return {
            "role": role,
            "decider": decider,
            "provider_config": config,
            "answering": answering,
            "description": spec.description,
        }

    @classmethod
    def body(cls, flags: list[str]) -> dict[str, Any]:
        arguments = compare.parser().parse_args([*REQUIRED, *flags])
        models = []
        for named in arguments.model:
            provider, _, model_id = named.partition("/")
            models.append(ComparisonArm(provider=provider, model_id=model_id))
        group = None
        if arguments.group_choice is not None:
            assert arguments.group_choice == CHOICE["choice_seq"]
            group = {"people": PEOPLE[:4], "source": {"kind": "owner_choice", **CHOICE}}
        elif arguments.group is not None:
            group = {"people": sorted(set(arguments.group)), "source": {"kind": "named"}}
        others = _others(cls.model)(None if group is None else group["people"])
        arms: dict[str, dict[str, Any]] = {
            "routine": {
                "role": "one",
                "decider": {"kind": "routine"},
                "provider_config": None,
                "answering": None,
                "description": "Their own routine",
            },
            "wait": {
                "role": "zero",
                "decider": {"kind": "wait"},
                "provider_config": None,
                "answering": None,
                "description": "Waiting where they are",
            },
        }
        keys = []
        for index, model in enumerate(models):
            key = f"model_{chr(ord('a') + index)}"
            arms[key] = cls.model_arm(model, "candidate")
            keys.append(key)
        control_pair = None
        if arguments.control:
            arms[f"{keys[0]}_again"] = cls.model_arm(models[0], "control")
            control_pair = [keys[0], f"{keys[0]}_again"]
        family = [["routine", key] for key in keys]
        primary = family[0]
        if len(keys) >= 2:
            primary = [keys[0], keys[1]]
            family = [primary, *family]
        return {
            "window_ticks": protocol_value(cls.catalogs, "window_ticks"),
            "phase": "development",
            "seeds": [seed_digest(seed) for seed in SEEDS],
            "group": dict(
                {"people": None, "source": {"kind": "everyone"}} if group is None else group
            ),
            "others": [dict(other) for other in others],
            "arms": arms,
            "claim": {"primary": primary, "family": family, "control": control_pair},
            "preregistration": None,
        }


def _defined(flags: list[str]) -> dict[str, Any]:
    """What the command defines today for ``flags``, through the one definition path."""
    arguments = compare.parser().parse_args([*REQUIRED, *flags])
    return definition_body(_runner(), VERSION, compare.selection(arguments), SEEDS)


def _bytes(body: dict[str, Any]) -> bytes:
    return json.dumps(body, sort_keys=True).encode()


@pytest.mark.parametrize("case", sorted(CASES))
def test_the_command_defines_what_it_did_for_each_of_its_flags(case):
    assert _bytes(_defined(CASES[case])) == _bytes(_Reference.body(CASES[case]))


def test_the_check_sees_a_changed_definition():
    """The positive control: a body that differs in one arm's words is told apart."""
    defined = _defined(CASES["two_models_control"])
    defined["arms"]["model_b"]["description"] += "."
    assert _bytes(defined) != _bytes(_Reference.body(CASES["two_models_control"]))
