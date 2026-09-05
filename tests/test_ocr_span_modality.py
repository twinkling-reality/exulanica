"""Where text read off a photograph lives, and what its coordinates mean.

Two questions that migration 0001 left open and that `modality` being a digest input makes
expensive to answer late:

*   **Which modality.** ADR-0016: text read off a surface is addressed by the pixels it was read
    from, so it is a `frame_region` span carrying an `ocr_text_is` assertion. `transcript_text`
    addresses a character range in a versioned text artifact, which is what an audio transcript
    needs because the media axis alone cannot locate a word. A photograph does not have that
    problem. Re-labelling spans already written under one value changes their digests, so this
    had to be settled before OCR spans were written rather than before they were read.
*   **What the coordinates are relative to.** The upright display space of ADR-0012, clamped to
    the unit square, quantised to parts per million by ADR-0013, and falling back to the
    whole-image span when the model gives no usable box.
"""

from __future__ import annotations

import copy
import uuid

import psycopg
import pytest
from exulanica.errors import InvalidAddressError
from exulanica.evidence import BlobId, EvidenceAddress, Modality, TimeInterval
from exulanica.evidence.address import IMAGE_TRACK_KEY, TextAnchor
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.vision import Box
from exulanica.store.local import LocalContentAddressedStore

from conftest import DEFAULT_PAYLOAD, CountingVisionModel, write_photo

REFUSED = psycopg.errors.CheckViolation

_BLOB = BlobId(bytes(range(32)))


# -- which modality ---------------------------------------------------------------------------


def test_a_transcript_span_cannot_address_a_photograph():
    with pytest.raises(InvalidAddressError, match="has no transcript"):
        EvidenceAddress(
            blob_id=_BLOB,
            track_key=IMAGE_TRACK_KEY,
            interval=TimeInterval(0, 1),
            modality=Modality.TRANSCRIPT_TEXT,
            text_anchor=TextAnchor(uuid.UUID(int=1), 0, 8, exact="OPEN"),
        )


def test_a_transcript_span_over_audio_is_still_the_normal_case():
    """The rule is about photographs, not about transcripts. ASR keeps its shape."""
    address = EvidenceAddress(
        blob_id=_BLOB,
        track_key="a:0",
        interval=TimeInterval(0, 1_000),
        modality=Modality.TRANSCRIPT_TEXT,
        text_anchor=TextAnchor(uuid.UUID(int=1), 0, 8),
    )
    assert address.modality is Modality.TRANSCRIPT_TEXT


def test_the_database_refuses_a_transcript_span_on_the_image_track(repository):
    """The refusal an application bug cannot remove."""
    digest = bytes(range(32))
    repository.connection.execute(
        "insert into blob (blob_sha256, byte_size, media_type) values (%s, 1, 'image/jpeg')",
        (digest,),
    )
    anchor = f'{{"artifact_id":"{uuid.UUID(int=1)}","char_start":0,"char_end":8}}'
    with pytest.raises(REFUSED, match="transcript_is_not_an_image_track"):
        repository.connection.execute(
            "insert into evidence_span (workspace_id, blob_sha256, track_key, t_start_ns, "
            "t_end_ns, modality, text_anchor, span_digest) "
            f"values (%s, %s, 'img', 0, 1, 'transcript_text', '{anchor}', %s)",
            (repository.workspace_id, digest, bytes(32)),
        )


# -- what the coordinates mean ----------------------------------------------------------------


def _ingest(tmp_path, photo_dir, repository, legible):
    payload = copy.deepcopy(DEFAULT_PAYLOAD)
    payload["legible_text"] = legible
    path = write_photo(photo_dir, "sign.jpg")
    store = LocalContentAddressedStore(tmp_path / "blobs")
    outcome = PhotoIngestPipeline(
        repository, store, vision=CountingVisionModel(payload=payload)
    ).ingest_file(path)
    assert outcome.error is None
    return repository.connection.execute(
        "select s.track_key, s.modality, s.region, a.object_value "
        "from assertion a "
        "join predicate p on p.predicate_id = a.predicate_id "
        "join evidence_span s on s.span_id = a.support_span_ids[1] "
        "where p.key = 'ocr_text_is'"
    ).fetchall()


def test_located_text_becomes_a_region_span_in_upright_display_space(
    tmp_path, photo_dir, repository
):
    rows = _ingest(
        tmp_path,
        photo_dir,
        repository,
        [
            {
                "text": "HRAUNFOSSAR",
                "is_signage": True,
                "confidence": "high",
                "box": {"x": 0.25, "y": 0.5, "w": 0.5, "h": 0.125},
            }
        ],
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["modality"] == "frame_region"
    assert row["track_key"] == "img"
    # Parts per million of the unit square, and the display space is upright (ADR-0012).
    assert row["region"]["rect"] == {"x": 250000, "y": 500000, "w": 500000, "h": 125000}
    assert row["region"]["display"]["rotation"] == 0
    assert row["region"]["display"]["w"] == 160 and row["region"]["display"]["h"] == 100


def test_unlocated_text_falls_back_to_the_whole_image_rather_than_inventing_a_box(
    tmp_path, photo_dir, repository
):
    """The claim that the pixels say this still stands. Only its location is missing."""
    rows = _ingest(
        tmp_path,
        photo_dir,
        repository,
        [{"text": "no box here", "is_signage": False, "confidence": "low", "box": None}],
    )
    assert len(rows) == 1
    assert rows[0]["modality"] == "still_image"
    assert rows[0]["region"] is None


def test_a_degenerate_box_falls_back_rather_than_producing_an_empty_region(
    tmp_path, photo_dir, repository
):
    """A zero-area region overlaps nothing, so every overlap guard would pass it."""
    rows = _ingest(
        tmp_path,
        photo_dir,
        repository,
        [
            {
                "text": "flat",
                "is_signage": False,
                "confidence": "low",
                "box": {"x": 0.5, "y": 0.5, "w": 0.0, "h": 0.2},
            }
        ],
    )
    assert len(rows) == 1
    assert rows[0]["modality"] == "still_image"


def test_a_box_over_the_edge_is_clamped_into_the_unit_square(tmp_path, photo_dir, repository):
    """Models routinely emit 1.02 for an edge. The span is built from the clamped box."""
    rows = _ingest(
        tmp_path,
        photo_dir,
        repository,
        [
            {
                "text": "edge",
                "is_signage": True,
                "confidence": "medium",
                "box": {"x": 0.9, "y": 0.1, "w": 0.4, "h": 0.2},
            }
        ],
    )
    rect = rows[0]["region"]["rect"]
    assert rect["x"] + rect["w"] == 1_000_000
    # And the model's own number survives, verbatim, in the artifact it wrote.
    clamped, changed = Box(x=0.9, y=0.1, w=0.4, h=0.2).clamped()
    assert changed and clamped.w == pytest.approx(0.1)
