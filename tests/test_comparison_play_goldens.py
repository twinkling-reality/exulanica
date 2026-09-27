"""A comparison's runs, byte for byte: what each arm's hour records, pinned.

``exulanica/world/society_comparison.py`` plays one hour of the small square with one arm deciding
for its people, and replays it from what it stored. This file plays each kind of arm over the same
genesis and seed, with scripted answers for the model's people, and pins the SHA-256 of what every
run recorded: its requests, its receipts, every minute's state, its events and how many minutes
each person began at a choice point; then it replays each run and holds the replay to the same
bytes. The arms: the routine, waiting, a model deciding for everybody, and a model deciding for a
group while one person outside it keeps the model their owner chose and the rest their routine.
``EXULANICA_COMPARISON_PLAY_GOLDENS=print`` prints the digests this tree produces.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from typing import Any

import pytest
from exulanica.canonical import canonical_json
from exulanica.world.society_comparison import PlayedRun, RunPlan, play, replay
from exulanica.world.society_decision_contract import decision_contract

import living_square_support as square

CONTRACT = decision_contract()
DOCUMENT = square.compose(square.square_objects())
SEED = "c4" * 32
TICKS = 45


def _config(model: str) -> dict[str, Any]:
    return {
        "provider": "nebius_token_factory",
        "model_id": model,
        "mechanism": "tool_call",
        "choice_seq": None,
        "manifest_sha256": "0" * 64,
        "prompt_version": "society-person-choice/v1",
        "contract": CONTRACT.binding(),
        "deadline_ms": 20_000,
    }


#: The digests this file pins, per arm.
EXPECTED: dict[str, Any] = {
    "group": {
        "choice_points": {
            "1b349beb-a79e-5af1-80ff-f21fe7c58cc3": 4,
            "3a749531-02bf-5147-8481-80a64706b73e": 8,
            "638b0e11-1236-5a5b-81e5-db97257c2aaa": 6,
            "6dc4e300-40dd-506a-b719-b9df96670e7e": 6,
            "7476b7ad-ebb3-5d47-826b-3b5109d35efe": 8,
            "7e8daa84-6d7c-5c92-8d21-3dae63020f5a": 8,
            "e3f040c7-a355-542a-ad6b-530108797cdb": 6,
            "ee0bb89e-aefb-5e54-bb09-5b71ab6810bc": 7,
        },
        "counts": {"receipts": 32, "requests": 32},
        "events": "849d97d50ba446ab79b1ade2909659104a68bdcbec94bc232b21cab254ca0b46",
        "receipts": "141509733e3c159bca87b67406232ac5616168a5f7ca4722c7c5dd02bc1ab8b3",
        "requests": "e7749d10596b36640007304f55442af483a7ee5265a5c15b2324f0624155222a",
        "states": "2eb870c8f72af5ed06a845d0a91bb02f0a2d12422cf9a1768359cce540da025f",
    },
    "model": {
        "choice_points": {
            "1b349beb-a79e-5af1-80ff-f21fe7c58cc3": 5,
            "3a749531-02bf-5147-8481-80a64706b73e": 5,
            "638b0e11-1236-5a5b-81e5-db97257c2aaa": 6,
            "6dc4e300-40dd-506a-b719-b9df96670e7e": 7,
            "7476b7ad-ebb3-5d47-826b-3b5109d35efe": 9,
            "7e8daa84-6d7c-5c92-8d21-3dae63020f5a": 11,
            "e3f040c7-a355-542a-ad6b-530108797cdb": 3,
            "ee0bb89e-aefb-5e54-bb09-5b71ab6810bc": 8,
        },
        "counts": {"receipts": 54, "requests": 54},
        "events": "527d4ad3126f1bb1e107c5ad83d41dbf9055981a84c83e268b01c07a0fb30b80",
        "receipts": "d63afa258136d25c2851f93a65273fc82f97a4cd73753e94e12ff0bd01a33e03",
        "requests": "3db46dc3ba5986456dc7d119270fea939e56ccdcd86949376a213f3484c4d447",
        "states": "c51351651209d07a7a873a2f5daa024246624b303646fc9c7fe9522499270017",
    },
    "routine": {
        "choice_points": {
            "1b349beb-a79e-5af1-80ff-f21fe7c58cc3": 6,
            "3a749531-02bf-5147-8481-80a64706b73e": 6,
            "638b0e11-1236-5a5b-81e5-db97257c2aaa": 8,
            "6dc4e300-40dd-506a-b719-b9df96670e7e": 8,
            "7476b7ad-ebb3-5d47-826b-3b5109d35efe": 9,
            "7e8daa84-6d7c-5c92-8d21-3dae63020f5a": 10,
            "e3f040c7-a355-542a-ad6b-530108797cdb": 8,
            "ee0bb89e-aefb-5e54-bb09-5b71ab6810bc": 8,
        },
        "counts": {"receipts": 0, "requests": 0},
        "events": "377428d7476bfc716322e12e2cde8b6a2d1eb40b43c0b2fa30e6291385028f9d",
        "receipts": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
        "requests": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
        "states": "096afd9139ebc5ea197723f055eee2a809286de3aa568eb14ffd7ff31eadeba9",
    },
    "wait": {
        "choice_points": {
            "1b349beb-a79e-5af1-80ff-f21fe7c58cc3": 45,
            "3a749531-02bf-5147-8481-80a64706b73e": 45,
            "638b0e11-1236-5a5b-81e5-db97257c2aaa": 45,
            "6dc4e300-40dd-506a-b719-b9df96670e7e": 45,
            "7476b7ad-ebb3-5d47-826b-3b5109d35efe": 45,
            "7e8daa84-6d7c-5c92-8d21-3dae63020f5a": 45,
            "e3f040c7-a355-542a-ad6b-530108797cdb": 45,
            "ee0bb89e-aefb-5e54-bb09-5b71ab6810bc": 45,
        },
        "counts": {"receipts": 0, "requests": 0},
        "events": "038ca29a9fe12f6345f1e88c5b8e1a53fb3308094f52bfb61179953215cbfdbd",
        "receipts": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
        "requests": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
        "states": "4a5b63c72b901f31cadf93cef8a31e38e750786e88f2d07a3e03688bfafef12a",
    },
}


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


class _Scripted:
    """Answers decided by each request's own digest: mostly an offered option, sometimes an
    answer never offered, sometimes a call that timed out; every option offered to all but one
    person, whose talk options are held back as a rule would."""

    def __init__(self, held_back: str | None) -> None:
        self.held_back = held_back

    def offerable(self, tick, due):
        return {
            subject: frozenset(
                o.label for o in options if not (subject == self.held_back and o.kind == "talk")
            )
            for subject, options in due.items()
        }

    def answers(self, requests):
        results = []
        for request in requests:
            number = int(request["document_sha256"][:12], 16)
            options = request["context"]["options"]
            if number % 7 == 5:
                results.append(
                    {
                        "status": "rejected",
                        "reason": "answer_not_offered",
                        "proposal": None,
                        "provider": None,
                    }
                )
                continue
            if number % 7 == 6:
                results.append(
                    {
                        "status": "unavailable",
                        "reason": "model_timed_out",
                        "proposal": None,
                        "provider": None,
                    }
                )
                continue
            option = options[(number // 7) % len(options)]
            results.append(
                {
                    "status": "accepted",
                    "reason": "validated_choice",
                    "proposal": {"label": option["label"], "option": option},
                    "provider": None,
                }
            )
        return results


def _plans() -> dict[str, RunPlan]:
    people = _people()
    group = frozenset(people[:4])
    others = {
        people[4]: {
            "decider": {"kind": "model", "provider": "nebius_token_factory", "model_id": "b/one"},
            "provider_config": _config("b/one"),
        },
        people[5]: {"decider": {"kind": "routine"}, "provider_config": None},
    }
    base = {
        "society_id": square.SOCIETY,
        "seed": SEED,
        "population": 8,
        "inputs": (DOCUMENT,),
        "ticks": TICKS,
        "contract": CONTRACT,
    }
    model = {"kind": "model", "provider": "nebius_token_factory", "model_id": "a/one"}
    return {
        "routine": RunPlan(
            run_id=uuid.uuid5(uuid.NAMESPACE_URL, "golden:routine"),
            decider={"kind": "routine"},
            provider_config=None,
            **base,
        ),
        "wait": RunPlan(
            run_id=uuid.uuid5(uuid.NAMESPACE_URL, "golden:wait"),
            decider={"kind": "wait"},
            provider_config=None,
            **base,
        ),
        "model": RunPlan(
            run_id=uuid.uuid5(uuid.NAMESPACE_URL, "golden:model"),
            decider=model,
            provider_config=_config("a/one"),
            **base,
        ),
        "group": RunPlan(
            run_id=uuid.uuid5(uuid.NAMESPACE_URL, "golden:group"),
            decider=model,
            provider_config=_config("a/one"),
            group=group,
            others=others,
            **base,
        ),
    }


def _people() -> list[str]:
    """The run's people by identity, as its genesis names them."""
    from exulanica.world.society_planner import PURPOSEFUL_PROFILE, initial_purposeful_society

    state = initial_purposeful_society(
        square.SOCIETY, SEED, DOCUMENT, population=8, engine_profile=PURPOSEFUL_PROFILE
    )
    return sorted(person["id"] for person in state["inhabitants"])


def _digests(played: PlayedRun) -> dict[str, Any]:
    return {
        "requests": _digest(played.requests),
        "receipts": _digest(played.receipts),
        "states": _digest(played.minute_digests),
        "events": played.events_sha256,
        "choice_points": dict(sorted(played.choice_points.items())),
        "counts": {"requests": len(played.requests), "receipts": len(played.receipts)},
    }


@pytest.mark.parametrize("arm", sorted(EXPECTED))
def test_each_arm_records_and_replays_the_same_bytes(arm):
    plan = _plans()[arm]
    people = _people()
    played = play(plan, _Scripted(held_back=people[1]))
    found = _digests(played)
    if os.environ.get("EXULANICA_COMPARISON_PLAY_GOLDENS") == "print":
        print(f"\n{arm} = {json.dumps(found, indent=4, sort_keys=True)}")
    stored = list(zip(played.requests, played.receipts, strict=True))
    again = replay(plan, stored, minute_digests=played.minute_digests)
    assert _digests(again) == found
    # The positive control: the model's arms asked people, and the anchors asked nobody.
    assert (found["counts"]["requests"] > 0) == (arm in ("group", "model"))
    assert found == EXPECTED[arm]
