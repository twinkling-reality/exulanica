"""The two gates that stand in front of personal media and in front of video.

Neither is a policy document here. Each is the half of a gate that code can hold, written so that
crossing it is a test failure rather than a judgement call somebody makes under deadline.

**Video.** A photograph is modelled as a single-sample ``img`` track carrying ``[0, 1)``. A motion
photograph, a burst or an animation is not that: it carries a real sequence with real presentation
times. Ingesting one today would keep frame one, store a `capture` whose EXIF and `pixel_size_is`
describe the whole file, and address every span at `img` on a blob whose other frames nothing can
cite. That is wrong evidence rather than missing evidence, so it is refused.

**Personal media.** Open item P-1, when a biometric template may exist at all, is unanswered, and
`docs/domain-and-evidence-model.md` section 9.2 says identity work must not begin before it is.
The line the system draws is at the template: a detected person becomes a scene-local occurrence
with an evidence address and nothing else. The `embedding` table has a deletion path and no writer,
and that is the fact this file pins, because the day it acquires one is the day P-1 has been
answered by accident.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import pytest
from exulanica.ingest.decode import UNREADABLE, open_upright, probe
from exulanica.ingest.vision import OBSERVATION_SCHEMA
from PIL import Image

_PACKAGE = Path(__file__).resolve().parents[1] / "exulanica"


# -- the video gate ---------------------------------------------------------------------------


def _animation(fmt: str) -> bytes:
    frames = [Image.new("RGB", (48, 32), colour) for colour in ((220, 30, 30), (30, 60, 220))]
    buffer = io.BytesIO()
    frames[0].save(
        buffer, format=fmt, save_all=True, append_images=frames[1:], duration=100, loop=0
    )
    return buffer.getvalue()


@pytest.mark.parametrize("fmt", ["GIF", "WEBP"])
def test_a_multi_frame_container_is_refused_by_the_header_probe(fmt):
    """Refused for the price of a header parse, before any decode."""
    with pytest.raises(UNREADABLE, match="holds 2 frames"):
        probe(_animation(fmt))


@pytest.mark.parametrize("fmt", ["GIF", "WEBP"])
def test_a_multi_frame_container_is_refused_by_the_decode_too(fmt):
    """Both entry points, because a caller that reached the second bypassed the first."""
    with pytest.raises(UNREADABLE, match="holds 2 frames"):
        open_upright(_animation(fmt))


def test_the_refusal_names_the_video_path_rather_than_calling_the_file_corrupt():
    """An operator who is told "unreadable" will re-export the file and try again."""
    try:
        probe(_animation("GIF"))
    except UNREADABLE as exc:
        message = str(exc)
    assert "v:0 track" in message
    assert "video path applies to it unchanged" in message


def test_an_ordinary_single_frame_photograph_still_passes(photo_dir):
    from conftest import photo_bytes

    assert probe(photo_bytes(orientation=6)) == (100, 160)


def test_the_capture_pipeline_reaches_the_refusal_rather_than_ingesting_frame_one(
    tmp_path, photo_dir, repository
):
    from exulanica.ingest.pipeline import PhotoIngestPipeline
    from exulanica.store.local import LocalContentAddressedStore

    path = photo_dir / "burst.gif"
    path.write_bytes(_animation("GIF"))
    store = LocalContentAddressedStore(tmp_path / "blobs")
    outcome = PhotoIngestPipeline(repository, store).ingest_file(path)

    assert outcome.error is not None
    assert repository.connection.execute("select count(*) as n from capture").fetchone()["n"] == 0
    assert (
        repository.connection.execute("select count(*) as n from evidence_span").fetchone()["n"]
        == 0
    )


# -- the personal-media gate ------------------------------------------------------------------


def test_nothing_in_the_package_writes_an_embedding():
    """P-1 is unanswered, so the table that would hold a biometric template has no writer.

    The deletion path can destroy an `embedding` row and nothing can create one. That asymmetry
    is deliberate and is the whole of the current answer to "when may a template exist": never
    yet. A writer appearing here means P-1 was answered by somebody adding a feature, which is
    the one way it must not be answered.
    """
    writers = []
    for path in sorted(_PACKAGE.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"insert\s+into\s+embedding\b", text, re.IGNORECASE):
            line = text[: match.start()].count("\n") + 1
            writers.append(f"{path.relative_to(_PACKAGE.parent)}:{line}")
    assert not writers, f"an embedding writer appeared: {writers}"


def test_the_vision_schema_has_no_field_a_name_could_arrive_in():
    """A model cannot propose an identity if the schema has nowhere to put one."""
    encoded = repr(OBSERVATION_SCHEMA)
    for forbidden in ("name", "identity", "person_id", "who", "embedding"):
        assert f"'{forbidden}'" not in encoded, forbidden


def test_a_person_occurrence_carries_an_address_and_no_template(
    tmp_path, photo_dir, repository
):
    """The line is at the template. "Somebody is here" is a box; it is not face geometry."""
    import copy

    from exulanica.ingest.pipeline import PhotoIngestPipeline
    from exulanica.store.local import LocalContentAddressedStore

    from conftest import DEFAULT_PAYLOAD, CountingVisionModel, write_photo

    payload = copy.deepcopy(DEFAULT_PAYLOAD)
    located = [entry for entry in payload["objects"] if entry["label"] == "person"]
    assert len(located) == 1
    located[0]["box"] = {"x": 0.55, "y": 0.1, "w": 0.2, "h": 0.6}

    path = write_photo(photo_dir, "a.jpg")
    store = LocalContentAddressedStore(tmp_path / "blobs")
    outcome = PhotoIngestPipeline(
        repository, store, vision=CountingVisionModel(payload=payload)
    ).ingest_file(path)
    assert outcome.error is None

    rows = repository.connection.execute(
        "select o.identity_key, o.quality, s.modality from occurrence o "
        "join evidence_span s on s.span_id = o.primary_span_id "
        "where o.class = 'person'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["modality"] == "frame_region"
    assert rows[0]["identity_key"] is not None
    # The detector's own word for what it saw is evidence about the detection. It is not a name,
    # and there is no column for one.
    assert set(rows[0]["quality"]) <= {"confidence_band", "salience", "label", "trust_tier"}
    assert repository.connection.execute(
        "select count(*) as n from embedding"
    ).fetchone()["n"] == 0
