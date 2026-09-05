"""Upright display space, enforced where a wrong region would otherwise become permanent.

ADR-0004 chose to normalise EXIF orientation at ingest rather than widen ``media_track.rotation``
to the eight EXIF values. ADR-0012 closes the consequences that were left conventional:

*   ``media_track.rotation`` means "clockwise degrees still to APPLY", the ordinary ffprobe
    reading, and after normalisation that is always zero on an image track. It used to hold the
    rotation that WAS applied, sitting next to ``disp_w``/``disp_h`` that already had it baked
    in, so the two halves of one row disagreed.
*   A photograph's display space IS its upright pixel space, so an ``img`` region carrying a
    rotated display geometry denotes the wrong pixels. ``region`` is inside ``span_digest``, so
    that is not a stale row to repair later; it is a permanent citation address pointing a right
    angle away from its evidence.

The application refusal and the database refusal are both asserted, and neither subsumes the
other: the first is the error message, the second is what an application bug cannot remove.
"""

from __future__ import annotations

import io

import psycopg
import pytest
from exulanica.errors import InvalidAddressError
from exulanica.evidence import BlobId, EvidenceAddress, Modality, TimeInterval
from exulanica.evidence.region import DisplayGeometry, Rect, Region
from exulanica.ingest.exif import extract_exif_facts
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.store.local import LocalContentAddressedStore
from PIL import Image

from conftest import CountingVisionModel, photo_bytes, write_photo

REFUSED = psycopg.errors.CheckViolation

ALL_ORIENTATIONS = list(range(1, 9))


# -- the address layer ----------------------------------------------------------------------


def _rect() -> Rect:
    return Rect.from_normalised(0.25, 0.25, 0.5, 0.5)


def test_an_image_region_claiming_a_rotated_display_space_is_refused():
    """The whole point: this address would name the wrong pixels, forever."""
    with pytest.raises(InvalidAddressError, match=r"display\.rotation 0"):
        EvidenceAddress.photograph(
            BlobId(bytes(range(32))),
            region=Region(rect=_rect(), display=DisplayGeometry(w=4032, h=3024, rotation=90)),
        )


def test_a_video_frame_region_may_still_carry_a_rotated_display_space():
    """The invariant is about normalised photographs, not about rotation in general.

    A video track is not normalised at ingest, has no equivalent of the EXIF transform applied
    to its samples, and its display space genuinely can be rotated. Refusing it here would be
    tightening a rule that has no reason behind it.
    """
    address = EvidenceAddress(
        blob_id=BlobId(bytes(range(32))),
        track_key="v:0",
        interval=TimeInterval(0, 1_000),
        modality=Modality.FRAME_REGION,
        region=Region(rect=_rect(), display=DisplayGeometry(w=1920, h=1080, rotation=270)),
    )
    assert address.region is not None
    assert address.region.display.rotation == 270


def test_the_upright_image_region_this_pipeline_writes_is_accepted():
    address = EvidenceAddress.photograph(
        BlobId(bytes(range(32))),
        region=Region(rect=_rect(), display=DisplayGeometry(w=4032, h=3024, rotation=0)),
    )
    assert address.modality is Modality.FRAME_REGION
    assert address.to_uri().endswith("disp=4032x3024,0,1:1")


@pytest.mark.parametrize("orientation", ALL_ORIENTATIONS)
def test_every_orientation_produces_an_upright_display_geometry(orientation):
    """All eight, including the four mirrored ones that used to be refused outright."""
    with Image.open(io.BytesIO(photo_bytes(orientation=orientation))) as opened:
        opened.load()
        _, facts = extract_exif_facts(opened)
    display = DisplayGeometry(w=facts.display_width, h=facts.display_height, rotation=0)
    assert (display.w, display.h) == (160, 100)
    assert display.as_digest_input()["rotation"] == 0


# -- the database ---------------------------------------------------------------------------


@pytest.mark.parametrize("orientation", ALL_ORIENTATIONS)
def test_a_real_ingest_stores_no_rotation_left_to_apply(
    orientation, tmp_path, photo_dir, repository
):
    path = write_photo(photo_dir, f"o{orientation}.jpg", orientation=orientation)
    store = LocalContentAddressedStore(tmp_path / "blobs")
    outcome = PhotoIngestPipeline(repository, store, vision=CountingVisionModel()).ingest_file(
        path
    )
    assert outcome.error is None

    row = repository.connection.execute(
        "select rotation, disp_w, disp_h, probe_json from media_track where track_key = 'img'"
    ).fetchone()
    assert row["rotation"] == 0
    # disp_w/disp_h are already upright, which is what makes a non-zero rotation a contradiction.
    assert (row["disp_w"], row["disp_h"]) == (160, 100)
    assert row["probe_json"]["orientation"]["exif_orientation"] == orientation
    assert row["probe_json"]["orientation"]["normalised_at_ingest"] is True


def test_the_database_refuses_an_image_track_that_did_not_record_normalisation(repository):
    """Without the flag a reader cannot tell sensor space from display space."""
    digest = bytes(range(32))
    repository.connection.execute(
        "insert into blob (blob_sha256, byte_size, media_type) values (%s, 1, 'image/jpeg')",
        (digest,),
    )
    with pytest.raises(REFUSED, match="media_track_image_is_upright"):
        repository.connection.execute(
            "insert into media_track (blob_sha256, track_key, kind, time_base_num, "
            "time_base_den, start_pts, duration_ns, disp_w, disp_h, rotation, codec, probe_json) "
            "values (%s, 'img', 'image', 1, 1000000000, 0, 1, 160, 100, 0, 'JPEG', '{}')",
            (digest,),
        )


def test_the_database_refuses_an_image_track_with_a_rotation_still_to_apply(repository):
    digest = bytes(range(1, 33))
    probe = (
        '{"orientation":{"exif_orientation":6,"rotation_degrees_clockwise":90,'
        '"mirrored":false,"normalised_at_ingest":true}}'
    )
    repository.connection.execute(
        "insert into blob (blob_sha256, byte_size, media_type) values (%s, 1, 'image/jpeg')",
        (digest,),
    )
    with pytest.raises(REFUSED, match="media_track_image_is_upright"):
        repository.connection.execute(
            "insert into media_track (blob_sha256, track_key, kind, time_base_num, "
            "time_base_den, start_pts, duration_ns, disp_w, disp_h, rotation, codec, probe_json) "
            f"values (%s, 'img', 'image', 1, 1000000000, 0, 1, 100, 160, 90, 'JPEG', '{probe}')",
            (digest,),
        )


def test_the_database_refuses_an_image_span_region_in_a_rotated_display_space(repository):
    """The application refuses this too. This is the refusal an application bug cannot remove."""
    digest = bytes(range(2, 34))
    repository.connection.execute(
        "insert into blob (blob_sha256, byte_size, media_type) values (%s, 1, 'image/jpeg')",
        (digest,),
    )
    region = (
        '{"kind":"rect","rect":{"x":250000,"y":250000,"w":500000,"h":500000},'
        '"display":{"w":4032,"h":3024,"rotation":90,"sar_num":1,"sar_den":1}}'
    )
    with pytest.raises(REFUSED, match="evidence_span_image_region_is_upright"):
        repository.connection.execute(
            "insert into evidence_span (workspace_id, blob_sha256, track_key, t_start_ns, "
            "t_end_ns, modality, region, span_digest) "
            f"values (%s, %s, 'img', 0, 1, 'frame_region', '{region}', %s)",
            (repository.workspace_id, digest, bytes(32)),
        )
