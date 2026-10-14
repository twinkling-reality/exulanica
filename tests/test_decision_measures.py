"""What a model's decisions came to, per model and per being, from receipt rows alone.

Rows are synthetic, in the shape ``SocietyDecisionRepository.role_decisions`` reads them.
"""

from __future__ import annotations

from typing import Any

from exulanica.world.decision_measures import (
    ACCEPTANCE_MINIMUM,
    LATENCY_MINIMUM,
    REPETITION_MINIMUM,
    by_being,
    measures,
    rate,
)

MODEL = ("open-provider", "open/model-small")


def _row(subject: str, seq: int, **fields: Any) -> dict[str, Any]:
    row = {
        "subject_id": subject,
        "decision_seq": seq,
        "provider": MODEL[0],
        "model_id": MODEL[1],
        "status": "accepted",
        "reason": "validated_choice",
        "disposition": "applied",
        "chose": "wait here a minute",
        "line": None,
        "asked_model": True,
        "latency_ms": 1000 + seq,
        "cost_usd": "0.00010000",
        "cost_known": True,
    }
    return {**row, **fields}


def test_a_rate_states_its_parts_and_is_null_below_its_minimum_never_zero() -> None:
    assert rate(0, 4, 5) == {"numerator": 0, "denominator": 4, "minimum": 5, "value": None}
    assert rate(0, 5, 5)["value"] == 0.0
    assert rate(2, 3, 1)["value"] == 0.6667


def test_counts_keep_refused_unavailable_stale_and_pending_apart() -> None:
    rows = [
        _row("a", 1),
        _row("a", 2, status="rejected", reason="answer_not_offered", disposition="rejected"),
        _row("a", 3, status="unavailable", reason="model_timed_out", disposition=None, chose=None),
        _row("a", 4, disposition="stale"),
        _row("a", 5, disposition="superseded"),
        _row("a", 6, disposition=None),
    ]
    found = measures(rows)
    assert found["counts"] == {
        "decisions": 6,
        "answered": 4,
        "refused": 1,
        "unavailable": 1,
        "timeouts": 1,
        "stale": 1,
        "applied": 1,
        "not_applied": 1,
        # Only the accepted answer no minute has taken up waits; the unanswered ask is a timeout.
        "pending": 1,
    }
    counts = found["counts"]
    assert counts["decisions"] == counts["answered"] + counts["refused"] + counts["unavailable"]
    assert counts["answered"] == (
        counts["applied"] + counts["not_applied"] + counts["stale"] + counts["pending"]
    )
    # Unavailable is not counted against acceptance: five judged answers, four accepted.
    assert found["rates"]["acceptance"] == {
        "numerator": 4,
        "denominator": 5,
        "minimum": ACCEPTANCE_MINIMUM,
        "value": 0.8,
    }
    # Applied over answers a minute took up: the pending one is not in the denominator.
    assert (found["rates"]["applied"]["numerator"], found["rates"]["applied"]["denominator"]) == (
        1,
        3,
    )
    assert found["rates"]["applied"]["value"] is None


def test_repetition_is_counted_within_each_being_never_across_beings() -> None:
    rows = [
        # Being a: wait, wait, wait, stand. Being b: wait, wait. Interleaved in decision order.
        _row("a", 1),
        _row("b", 2),
        _row("a", 3),
        _row("b", 4),
        _row("a", 5),
        _row("a", 6, chose="stand a while nearby"),
    ]
    found = measures(rows)
    # a: 3 pairs, 2 identical; b: 1 pair, 1 identical.
    assert found["rates"]["repeated_choice"] == {
        "numerator": 3,
        "denominator": 4,
        "minimum": REPETITION_MINIMUM,
        "value": 0.75,
    }
    assert found["repetition"]["longest_choice_run"] == 3
    per_being = {entry["subject_id"]: entry["measures"] for entry in by_being(rows)}
    assert per_being["b"]["rates"]["repeated_choice"]["value"] is None
    assert per_being["b"]["repetition"]["longest_choice_run"] == 2


def test_only_lines_a_minute_applied_are_said_and_compared() -> None:
    rows = [
        _row("a", 1, chose="say hello", line="Hello."),
        _row("a", 2, chose="say hello", line="Hello."),
        # Proposed but not applied: never said, so never a repeat.
        _row("a", 3, chose="say hello", line="Hello.", disposition="rejected"),
        _row("a", 4, chose="say hello", line="Hello again."),
    ]
    found = measures(rows)
    assert (
        found["rates"]["repeated_line"]["numerator"],
        found["rates"]["repeated_line"]["denominator"],
    ) == (1, 2)
    assert found["repetition"]["longest_line_run"] == 2


def test_timeout_streaks_are_per_being_longest_and_current() -> None:
    def timed_out(subject: str, seq: int) -> dict[str, Any]:
        return _row(
            subject,
            seq,
            status="unavailable",
            reason="model_timed_out",
            disposition="unavailable",
            chose=None,
        )

    rows = [
        timed_out("a", 1),
        timed_out("b", 2),
        timed_out("a", 3),
        _row("a", 4),
        timed_out("b", 5),
    ]
    found = measures(rows)
    # a: two in a row then an answer; b: two in a row, still running.
    assert found["timeouts"] == {"longest_streak": 2, "current_streak": 2}
    per_being = {entry["subject_id"]: entry["measures"]["timeouts"] for entry in by_being(rows)}
    assert per_being == {
        "a": {"longest_streak": 2, "current_streak": 0},
        "b": {"longest_streak": 2, "current_streak": 2},
    }


def test_latency_is_null_below_its_minimum_and_cost_says_computed_or_bounded() -> None:
    few = [_row("a", seq) for seq in range(1, LATENCY_MINIMUM)]
    found = measures(few)
    assert found["latency_ms"] == {
        "n": LATENCY_MINIMUM - 1,
        "minimum": LATENCY_MINIMUM,
        "p50": None,
        "p95": None,
        "longest": None,
    }
    assert found["cost"] == {
        "usd": "0.00040000",
        "known_usd": "0.00040000",
        "reserved_usd": "0.00000000",
        "basis": "computed",
        "unknown_calls": 0,
        "calls": 4,
    }
    enough = [*few, _row("a", 9, cost_known=False, cost_usd="0.00050000", latency_ms=19000)]
    found = measures(enough)
    assert (found["latency_ms"]["p50"], found["latency_ms"]["longest"]) == (1003, 19000)
    assert found["cost"]["basis"] == "bounded"
    assert found["cost"]["unknown_calls"] == 1
    # The reservation is kept apart from what reported tokens priced, and the two make the total.
    assert (found["cost"]["known_usd"], found["cost"]["reserved_usd"], found["cost"]["usd"]) == (
        "0.00040000",
        "0.00050000",
        "0.00090000",
    )
    # A decision no model was asked for (a person played the being) costs and times nothing.
    played = measures([_row("a", 1, asked_model=False, latency_ms=None)])
    assert played["cost"]["calls"] == 0
    assert played["latency_ms"]["n"] == 0


def test_no_measure_combines_others_into_one_score() -> None:
    found = measures([_row("a", 1)])
    assert set(found) == {"counts", "rates", "timeouts", "repetition", "latency_ms", "cost"}
    assert not any("score" in key for key in found)
