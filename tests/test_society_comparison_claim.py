"""A comparison claims a difference between two models only when its protocol says it may.

``exulanica/world/society_comparison_claim.py`` reads paired differences over seeds with a
percentile bootstrap drawn from SHA-256, holds the family of registered hypotheses to its error rate
by Holm's procedure, and bounds what run-to-run variation alone produces by a control: one model
run twice. These tests hold the words the page may show: ``different`` for a difference Holm
rejects and larger than the control's bound, and ``no_measured_difference`` for one inside its
interval, or no larger than the same model's variation, whatever its mean.
"""

from __future__ import annotations

from fractions import Fraction

import pytest
from exulanica.world.society_catalogs import load_comparison_catalogs
from exulanica.world.society_comparison_claim import (
    Protocol,
    Resamples,
    family_differences,
    holm,
    judge,
)
from exulanica.world.society_comparison_result import protocol_values

VALUES = protocol_values(load_comparison_catalogs())
PROTOCOL = Protocol(
    resamples=VALUES["bootstrap_resamples"],
    interval_per_mille=VALUES["interval_per_mille"],
    family_alpha_per_mille=VALUES["family_alpha_per_mille"],
)
SEEDS = [f"seed-{index}" for index in range(8)]
FAMILY = [("a", "b"), ("routine", "a"), ("routine", "b")]


def _arm(values) -> dict[str, Fraction | None]:
    return {
        seed: None if value is None else Fraction(value)
        for seed, value in zip(SEEDS, values, strict=True)
    }


def _scores(b, *, control=None) -> dict[str, dict[str, Fraction | None]]:
    a = ["0.40", "0.35", "0.52", "0.30", "0.45", "0.38", "0.41", "0.50"]
    return {
        "routine": _arm(["1"] * 8),
        "a": _arm(a),
        "b": _arm(b),
        "a_again": _arm(control if control is not None else a),
    }


def _judge(scores):
    return judge(
        scores,
        primary=("a", "b"),
        family=FAMILY,
        control=("a", "a_again"),
        key="test-comparison",
        protocol=PROTOCOL,
    )


def test_a_model_better_on_every_seed_than_the_control_varies_is_different():
    verdict = _judge(_scores(["0.80", "0.70", "0.90", "0.60", "0.85", "0.75", "0.72", "0.95"]))
    assert verdict.code == "different"
    assert verdict.higher == "b"
    assert verdict.primary.low > 0
    assert ("a", "b") in verdict.rejected
    # The same model run twice identically varies by nothing, so its bound is zero.
    assert verdict.control_bound == 0


def test_a_difference_inside_its_interval_is_no_measured_difference():
    verdict = _judge(_scores(["0.45", "0.30", "0.55", "0.28", "0.40", "0.41", "0.39", "0.52"]))
    assert verdict.code == "no_measured_difference"
    assert verdict.higher is None
    assert verdict.primary.low < 0 < verdict.primary.high
    assert ("a", "b") not in verdict.rejected


def test_a_difference_no_larger_than_the_same_model_varies_is_no_measured_difference():
    """Holm rejects the primary hypothesis, and its mean is still inside what the control shows
    one model's hour varies by: no difference is claimed."""
    scores = _scores(
        ["0.50", "0.45", "0.62", "0.40", "0.55", "0.48", "0.51", "0.60"],
        control=["0.60", "0.20", "0.70", "0.10", "0.55", "0.20", "0.70", "0.10"],
    )
    verdict = _judge(scores)
    assert ("a", "b") in verdict.rejected
    assert abs(verdict.primary.mean) <= verdict.control_bound
    assert verdict.code == "no_measured_difference"


def test_the_same_scores_give_the_same_verdict_and_another_key_other_draws():
    scores = _scores(["0.45", "0.30", "0.55", "0.28", "0.40", "0.41", "0.39", "0.52"])
    assert _judge(scores) == _judge(scores)
    first = Resamples("one", 8, PROTOCOL).draws
    assert first == Resamples("one", 8, PROTOCOL).draws
    assert first != Resamples("two", 8, PROTOCOL).draws


def test_holm_steps_down_and_stops_at_the_first_hypothesis_it_keeps():
    alpha = Fraction(5, 100)
    assert holm({("x", "y"): Fraction(1, 100), ("x", "z"): Fraction(3, 100)}, alpha) == {
        ("x", "y"),
        ("x", "z"),
    }
    # 0.01 <= 0.05/3, then 0.03 > 0.05/2: the second is kept, and so is every larger one.
    assert holm(
        {
            ("x", "y"): Fraction(1, 100),
            ("x", "z"): Fraction(3, 100),
            ("y", "z"): Fraction(4, 100),
        },
        alpha,
    ) == {("x", "y")}


def test_seeds_an_arm_did_not_score_are_left_out_of_every_difference_that_reads_it():
    scores = _scores(["0.80", "0.70", None, "0.60", "0.85", "0.75", "0.72", "0.95"])
    found, _rejected = family_differences(
        scores, family=FAMILY, key="test-comparison", protocol=PROTOCOL
    )
    assert all(len(difference.seeds) == 7 for difference in found.values())
    assert "seed-2" not in found[("a", "b")].seeds


def test_an_interval_is_read_over_two_seeds_at_least():
    with pytest.raises(ValueError, match="two seeds"):
        Resamples("one", 1, PROTOCOL)
