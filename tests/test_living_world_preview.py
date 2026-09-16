"""Offline recording replay against actual A/B code, never database persistence evidence."""

import pytest
from exulanica.canonical import canonical_json
from exulanica.world.society import society_state_sha256
from exulanica.world.society_planner import advance_purposeful_society, ordered_events_document
from scripts.prepare_living_world_preview import (
    DEFAULT_BASE,
    DEFAULT_OUTPUT,
    generate_preview,
    main,
    write_preview,
)


@pytest.fixture(scope="module")
def preview():
    return generate_preview(DEFAULT_BASE.read_bytes())


def test_actual_preview_has_contiguous_frames_exact_replay_and_edit_sequence(preview):
    assert [frame["snapshot"]["current_tick"] for frame in preview["frames"]] == list(range(19))
    assert [i["input_seq"] for i in preview["inputs"]] == [1, 2, 3, 4]
    assert [i["authored_state"]["edit_seq"] for i in preview["inputs"]] == [0, 1, 2, 3]
    assert {frame["change"] for frame in preview["frames"] if frame["change"]} == {
        "add_fixture_rest_pad",
        "disable_fixture_rest_pad",
        "restore_fixture_rest_pad",
    }
    assert preview["frames"][5]["authored_objects"][0]["origin"]["role"] == "fictional"
    assert preview["frames"][9]["authored_objects"] == []
    assert preview["frames"][13]["authored_objects"] == preview["frames"][5]["authored_objects"]
    state = preview["frames"][0]["snapshot"]["state"]
    events = []
    for frame in preview["frames"][1:]:
        expected = frame["snapshot"]
        inputs = preview["inputs"][state["input_seq"] - 1 : expected["input_seq"]]
        state, produced = advance_purposeful_society(state, expected["seed"], inputs)
        assert state == expected["state"]
        assert society_state_sha256(state) == expected["state_sha256"]
        assert len(state["inhabitants"]) == 128
        events.extend(ordered_events_document(produced))
    assert events == preview["events"]
    assert "no database persistence" in preview["status"]


def test_output_is_deterministic_and_private_by_default(preview, tmp_path):
    repeated = generate_preview(DEFAULT_BASE.read_bytes())
    assert canonical_json(preview) == canonical_json(repeated)
    assert DEFAULT_OUTPUT.parts[-2] == "briefs"
    assert DEFAULT_OUTPUT.parts[-3] in {".exulanica", ".orimera"}
    output = tmp_path / "preview.json"
    write_preview(preview, output)
    assert output.read_bytes() == canonical_json(repeated) + b"\n"
    assert list(tmp_path.iterdir()) == [output]


def test_default_window_explicitly_discloses_absent_pad_behavior(preview):
    # Existing rest needs are satisfied before the pad appears; edit receipts alone
    # must never be reported as evidence that anybody used or replanned around it.
    for frame in preview["frames"]:
        for person in frame["snapshot"]["state"]["inhabitants"]:
            assert (person.get("target") or {}).get("object_id") != "object:preview-rest-pad"
    assert not [
        event
        for event in preview["events"]
        if (event["document"].get("target") or {}).get("object_id") == "object:preview-rest-pad"
    ]
    assert "input changes only, not a behavioral response to the pad" in preview["status"]


def test_missing_exact_node_fails_without_snapping():
    with pytest.raises(ValueError, match="exact validated node"):
        generate_preview(DEFAULT_BASE.read_bytes(), pad_node_id="not-a-node")


def test_output_cannot_overwrite_input_artifact(tmp_path):
    source = tmp_path / "base.json"
    source.write_bytes(b"source remains unchanged")
    with pytest.raises(SystemExit):
        main(["--base", str(source), "--output", str(source)])
    assert source.read_bytes() == b"source remains unchanged"
