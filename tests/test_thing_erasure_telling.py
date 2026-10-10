"""The budget of an erasure's inline telling is stated as data, with its class and its reason."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from exulanica.api.routes import thing_store

POLICY = Path(__file__).resolve().parents[1] / "exulanica/world/thing-erasure-telling.v1.json"


def test_the_policy_states_a_chosen_budget_of_whole_seconds_with_its_reason():
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    assert policy["policy_id"] == "exulanica.thing-erasure-telling" and policy["version"] == 1
    assert policy["values"] == {"seconds_maximum": 2}
    assert policy["classes"] == {"seconds_maximum": "chosen_budget"}
    # The reason says what the figure does not decide: whether an erased creature runs again.
    reason = policy["reasons"]["seconds_maximum"]
    assert "tell themselves" in reason and "never whether an erased creature is run" in reason
    assert thing_store.TELLING_SECONDS == thing_store._telling_seconds(POLICY) == 2


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p.update(policy_id="exulanica.something-else"),
        lambda p: p.update(version=2),
        lambda p: p["values"].update(seconds_maximum=-1),
        lambda p: p["values"].update(seconds_maximum=31),
        lambda p: p["reasons"].update(seconds_maximum="  "),
        lambda p: p["values"].update(seconds_maximum=2.5),
        lambda p: p["values"].update(seconds_maximum=True),
        lambda p: p["values"].pop("seconds_maximum"),
        lambda p: p["classes"].update(seconds_maximum="leftover"),
        lambda p: p["reasons"].pop("seconds_maximum"),
    ],
)
def test_a_policy_out_of_shape_is_refused_by_name(tmp_path, change):
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    path = tmp_path / POLICY.name
    path.write_text(json.dumps(policy), encoding="utf-8")
    assert thing_store._telling_seconds(path) == 2  # positive control: an unchanged copy reads
    change(policy)
    path.write_text(json.dumps(policy), encoding="utf-8")
    with pytest.raises(ValueError, match="telling budget"):
        thing_store._telling_seconds(path)


def test_a_budget_of_no_seconds_reads_as_none(tmp_path):
    """A host may tell nobody inline: every society then tells itself."""
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    policy["values"]["seconds_maximum"] = 0
    path = tmp_path / POLICY.name
    path.write_text(json.dumps(policy), encoding="utf-8")
    assert thing_store._telling_seconds(path) == 0
