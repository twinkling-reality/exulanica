"""The committed stylized looks are exactly what their pinned sources derive."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import prepare_character_preview as preview  # noqa: E402


def test_committed_list_matches_its_pinned_sources():
    assert preview.STYLIZED_LOOKS.read_text() == preview.render(preview.stylized_looks())
    assert preview.main(["--check"]) == 0


def test_every_look_names_verified_bytes_and_faces_the_world_forward_axis():
    document = json.loads(preview.STYLIZED_LOOKS.read_text())
    assert document["profile"] == "exulanica.character-stylized-looks/v1"
    manifest = (preview.SOURCE / "manifest.json").read_bytes()
    assert document["source"]["manifestSha256"] == hashlib.sha256(manifest).hexdigest()
    looks = document["looks"]
    assert [look["lookId"] for look in looks] == ["hoodie", "casual", "casual-f", "formal-f"]
    for look in looks:
        data = (preview.SOURCE / look["file"]).read_bytes()
        asset = look["descriptor"]["asset"]
        assert (len(data), hashlib.sha256(data).hexdigest()) == (
            asset["byteSize"],
            asset["contentSha256"],
        )
        assert look["descriptor"]["forwardYawDegrees"] == 180
        assert look["gesture"]["descriptor"]["character"] == look["descriptor"]
        assert look["variationSlots"] and set(look["variationSlots"]) <= set(look["defaultColors"])


@pytest.mark.parametrize(
    ("frame", "expected"),
    [
        ({"forward": "+Z", "forward_yaw_radians": 0, "up": "+Y"}, 180),
        ({"forward": "-Z", "forward_yaw_radians": 0, "up": "+Y"}, 0),
    ],
)
def test_source_forward_axis_turns_to_face_the_world(frame, expected):
    assert preview.forward_yaw_degrees(frame) == expected


@pytest.mark.parametrize(
    "frame",
    [
        {"forward": "+X", "forward_yaw_radians": 0, "up": "+Y"},
        {"forward": "+Z", "forward_yaw_radians": 0.5, "up": "+Y"},
        {"forward": "+Z", "forward_yaw_radians": 0, "up": "+Z"},
    ],
)
def test_an_undeclared_source_frame_is_refused(frame):
    with pytest.raises(ValueError, match="Unsupported source frame"):
        preview.forward_yaw_degrees(frame)


def test_check_reports_a_drifted_list(tmp_path, monkeypatch):
    drifted = tmp_path / "stylized-looks.json"
    drifted.write_text(preview.render(preview.stylized_looks()).replace('"Hoodie"', '"Sweater"'))
    monkeypatch.setattr(preview, "STYLIZED_LOOKS", drifted)
    monkeypatch.setattr(preview, "ROOT", tmp_path)
    assert preview.main(["--check"]) == 1
