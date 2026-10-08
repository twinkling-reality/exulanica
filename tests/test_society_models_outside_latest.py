"""Which receipt an outside entry of the world's models read gives as its subject's latest: the
subject's own, under the entry's own grant, the last in decision order; a model's never."""

from __future__ import annotations

from typing import Any

from exulanica.api.routes.society_models import _with_latest

GRANT = "6d2f9c2e-6c1b-4c55-9d7a-8e6f0a1b2c3d"
OTHER_GRANT = "0b6c2f4e-1d3a-4e5f-8a9b-7c6d5e4f3a2b"


def _external(grant_id: str) -> dict[str, str]:
    return {"kind": "external", "bridge": "agents", "grant_id": grant_id}


def _decision(
    seq: int, subject: str, decider: dict[str, str], status: str, reason: str
) -> dict[str, Any]:
    return {
        "decision_seq": seq,
        "subject_id": subject,
        "base_tick": 10 + seq,
        "consumed_tick": None,
        "decider": decider,
        "status": status,
        "reason": reason,
    }


def test_an_entry_reads_its_own_subject_s_latest_receipt_under_its_own_grant() -> None:
    outside = [
        {"subject_id": "a", "came": "run", "grant_id": GRANT},
        {"subject_id": "b", "came": "crossed", "grant_id": GRANT},
        {"subject_id": "c", "came": "run", "grant_id": OTHER_GRANT},
    ]
    model = {"kind": "model", "provider": "nebius_token_factory", "model_id": "a-model"}
    decisions = [
        _decision(1, "a", _external(GRANT), "unavailable", "no_answer_in_time"),
        _decision(2, "a", _external(GRANT), "accepted", "validated_choice"),
        # Another grant's decision for c, a model's for a, and nothing at all for b.
        _decision(3, "c", _external(GRANT), "accepted", "validated_choice"),
        _decision(4, "a", model, "accepted", "validated_choice"),
    ]
    read = _with_latest(outside, decisions)
    assert [{k: v for k, v in entry.items() if k != "latest"} for entry in read] == outside
    assert [entry["latest"] for entry in read] == [
        {
            "decision_seq": 2,
            "base_tick": 12,
            "consumed_tick": None,
            "status": "accepted",
            "reason": "validated_choice",
        },
        None,
        None,
    ]
