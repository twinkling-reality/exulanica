"""The offline v4 preview recording is the engine's own output, frame for frame."""

from __future__ import annotations

import copy
import json

import pytest
from scripts.record_living_society import main, record, verify_recording


@pytest.fixture(scope="module")
def recording():
    return record(12)


def test_recording_presents_engine_states_and_replays_exactly(recording):
    verify_recording(recording)
    assert recording["engine_profile"] == "exulanica-society/v4"
    assert [frame["tick"] for frame in recording["frames"]] == list(range(13))
    assert recording["population"]["size"] == len(recording["roster"]) == 46
    assert recording["place"]["capacity"] == 93
    assert all(len(f["inhabitants"]) == 46 for f in recording["frames"])
    assert recording["frames"][0]["minute_of_day"] == 480
    assert {e["subject_id"] for e in recording["events"]} <= {p["id"] for p in recording["roster"]}
    assert all(p["role"] is None and p["synthetic"] for p in recording["roster"])
    assert recording["environment"]["weather"]["availability"] == "unavailable"


def test_a_tampered_recording_is_refused(recording):
    moved = copy.deepcopy(recording)
    moved["frames"][3]["inhabitants"][0]["position_mm"][0] += 1
    with pytest.raises(ValueError, match="frame 3"):
        verify_recording(moved)
    renamed = copy.deepcopy(recording)
    renamed["events"][0]["summary"] = "Emi Fox visited."
    with pytest.raises(ValueError, match="events"):
        verify_recording(renamed)


def test_recording_writes_compact_json(tmp_path):
    output = tmp_path / "recording.json"
    assert main(["--ticks", "2", "--output", str(output)]) == 0
    document = json.loads(output.read_text(encoding="utf-8"))
    assert len(document["frames"]) == 3
    with pytest.raises(ValueError, match="1 to 1440"):
        record(0)
