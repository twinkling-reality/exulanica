"""What a model's decisions came to for the beings it decided for, from the stored receipts alone.

The models read (:func:`~exulanica.api.routes.society_models.society_models_view`) serves these
measures per model and per (being, model), and is their one authority: a page reads them, never
recomputes them. Every rate carries its numerator, denominator and the minimum sample it needs, and
its value is ``None`` below that minimum, never 0. Nothing here is combined into one score, and
nothing sets a threshold: repetition, timeouts and latency are reported as found.

Each row is one receipt as :meth:`SocietyDecisionRepository.role_decisions
<exulanica.world.society_decision_repository.SocietyDecisionRepository.role_decisions>` reads it,
in decision order.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal
from itertools import pairwise
from typing import Any, Final

from exulanica.models.usage import usd_string

#: The fewest receipts with a definite status before an acceptance rate is stated.
ACCEPTANCE_MINIMUM: Final = 5
#: The fewest accepted answers a minute has taken up before an applied rate is stated.
APPLIED_MINIMUM: Final = 5
#: The fewest consecutive pairs (of one being's answers, or of its lines) before a repeat rate.
REPETITION_MINIMUM: Final = 4
#: The fewest timed calls before latency percentiles are stated.
LATENCY_MINIMUM: Final = 5
#: The receipt reason a call that did not answer in time records.
TIMED_OUT: Final = "model_timed_out"


def nearest_rank(values: Sequence[int], share: int) -> int | None:
    """The value at ``share`` percent of ``values`` by nearest rank, or None for none."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, -(-share * len(ordered) // 100) - 1)]


def rate(numerator: int, denominator: int, minimum: int) -> dict[str, Any]:
    """A rate with what it is made of: its value is None below ``minimum``, never 0."""
    return {
        "numerator": numerator,
        "denominator": denominator,
        "minimum": minimum,
        "value": None if denominator < minimum else round(numerator / denominator, 4),
    }


def _by_subject(rows: Iterable[Mapping[str, Any]]) -> list[list[Mapping[str, Any]]]:
    """Each being's rows, in decision order."""
    held: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        held.setdefault(row["subject_id"], []).append(row)
    return list(held.values())


def _runs(values: Sequence[Any]) -> tuple[int, int]:
    """(identical consecutive pairs, longest run of one value) in ``values``."""
    pairs = sum(1 for earlier, later in pairwise(values) if earlier == later)
    longest = run = 0
    for index, value in enumerate(values):
        run = run + 1 if index and value == values[index - 1] else 1
        longest = max(longest, run)
    return pairs, longest


def _streaks(rows: Sequence[Mapping[str, Any]]) -> tuple[int, int]:
    """(longest, current trailing) run of timed-out receipts in one being's rows."""
    longest = current = 0
    for row in rows:
        current = current + 1 if row["reason"] == TIMED_OUT else 0
        longest = max(longest, current)
    return longest, current


def measures(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Counts, gated rates, timeouts, repetition, latency and cost for ``rows``.

    ``rows`` are the receipts of one model, or of one being under one model. Repetition and
    timeout streaks are counted within each being, in decision order, and summed or taken at their
    largest across beings: one being's answer is never compared with another's.
    """
    answered = [row for row in rows if row["status"] == "accepted"]
    refused = sum(1 for row in rows if row["status"] == "rejected")
    consumed = [row for row in answered if row["disposition"] is not None]
    applied = sum(1 for row in rows if row["disposition"] == "applied")
    choice_pairs = choice_repeats = choice_longest = 0
    line_pairs = line_repeats = line_longest = 0
    longest_streak = current_streak = 0
    for own in _by_subject(rows):
        chosen = [row["chose"] for row in own if row["status"] == "accepted"]
        repeats, longest = _runs(chosen)
        choice_pairs += max(0, len(chosen) - 1)
        choice_repeats += repeats
        choice_longest = max(choice_longest, longest)
        # A line is said only where a minute applied the choice that carried it.
        said = [row["line"] for row in own if row["disposition"] == "applied" and row.get("line")]
        repeats, longest = _runs(said)
        line_pairs += max(0, len(said) - 1)
        line_repeats += repeats
        line_longest = max(line_longest, longest)
        streak, trailing = _streaks(own)
        longest_streak = max(longest_streak, streak)
        current_streak = max(current_streak, trailing)
    asked = [row for row in rows if row["asked_model"]]
    latencies = [row["latency_ms"] for row in asked if row["latency_ms"] is not None]
    enough = len(latencies) >= LATENCY_MINIMUM
    known = sum((Decimal(row["cost_usd"]) for row in asked if row["cost_known"]), Decimal(0))
    reserved = sum((Decimal(row["cost_usd"]) for row in asked if not row["cost_known"]), Decimal(0))
    unknown = sum(1 for row in asked if not row["cost_known"])
    return {
        "counts": {
            "decisions": len(rows),
            "answered": len(answered),
            "refused": refused,
            "unavailable": sum(1 for row in rows if row["status"] == "unavailable"),
            "timeouts": sum(1 for row in rows if row["reason"] == TIMED_OUT),
            "stale": sum(1 for row in rows if row["disposition"] == "stale"),
            "applied": applied,
            "not_applied": sum(
                1 for row in answered if row["disposition"] in ("rejected", "superseded")
            ),
            # An answer no minute has taken up yet. An ask left without an answer is counted under
            # unavailable (and timeouts), never as waiting, whether or not a minute took it up.
            "pending": sum(1 for row in answered if row["disposition"] is None),
        },
        "rates": {
            # Answers the engine could judge; an unavailable call is counted apart, not as refused.
            "acceptance": rate(len(answered), len(answered) + refused, ACCEPTANCE_MINIMUM),
            "applied": rate(applied, len(consumed), APPLIED_MINIMUM),
            "repeated_choice": rate(choice_repeats, choice_pairs, REPETITION_MINIMUM),
            "repeated_line": rate(line_repeats, line_pairs, REPETITION_MINIMUM),
        },
        "timeouts": {"longest_streak": longest_streak, "current_streak": current_streak},
        "repetition": {"longest_choice_run": choice_longest, "longest_line_run": line_longest},
        "latency_ms": {
            "n": len(latencies),
            "minimum": LATENCY_MINIMUM,
            "p50": nearest_rank(latencies, 50) if enough else None,
            "p95": nearest_rank(latencies, 95) if enough else None,
            "longest": max(latencies) if enough else None,
        },
        "cost": {
            "usd": usd_string(known + reserved),
            # The two parts of usd: computed from reported tokens, and charged as reservations.
            "known_usd": usd_string(known),
            "reserved_usd": usd_string(reserved),
            # Computed from the provider's reported tokens at the manifest's listed price; bounded
            # where a call's tokens were not reported and its reservation, the most it can have
            # cost, was charged instead. Never a provider's bill.
            "basis": "computed" if unknown == 0 else "bounded",
            "unknown_calls": unknown,
            "calls": len(asked),
        },
    }


def by_being(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The measures of each (being, model), in subject then model order."""
    grouped: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((row["subject_id"], row["provider"], row["model_id"]), []).append(row)
    return [
        {
            "subject_id": subject,
            "provider": provider,
            "model_id": model_id,
            "measures": measures(group),
        }
        for (subject, provider, model_id), group in sorted(grouped.items())
    ]
