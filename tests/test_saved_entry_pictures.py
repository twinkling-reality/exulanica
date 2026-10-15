"""A saved world's picture, held to what the server can check, with no database (0218).

The picture's bounds, its walk and what it may be of: the cases the store and the route rest on.
The store itself, the route and the erasure are in ``test_saved_entry_pictures_postgres.py``.
"""

from __future__ import annotations

import hashlib
import io
import uuid
from types import SimpleNamespace

import pytest
from exulanica.world.saved_entry_pictures import (
    PICTURE_LEAST,
    PICTURE_MAX_BYTES,
    PICTURE_MOST,
    PictureRefused,
    PictureShows,
    checked_picture,
    refuse_a_world_of_photographs,
)

from style_pack_upload_support import jpeg, png


def _webp(width: int, height: int) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (40, 90, 160)).save(buffer, "WEBP", quality=70)
    return buffer.getvalue()


def _refused(data: bytes, media_type: str) -> tuple[str, int]:
    with pytest.raises(PictureRefused) as refused:
        checked_picture(data, media_type)
    return refused.value.code, refused.value.status


def test_a_picture_of_a_card_s_shape_is_kept_with_its_size_and_the_server_s_own_digest():
    data = jpeg(1280, 720)
    assert checked_picture(data, "image/jpeg") == (1280, 720, hashlib.sha256(data).hexdigest())
    least = _webp(*PICTURE_LEAST)
    assert checked_picture(least, "image/webp")[:2] == PICTURE_LEAST


def test_a_picture_is_refused_by_its_type_its_bytes_its_size_and_anything_hidden_in_it():
    assert _refused(png(640, 360), "image/png") == ("picture_media_type", 415)
    assert _refused(b"", "image/jpeg") == ("picture_too_large", 413)
    assert _refused(b"\xff" * (PICTURE_MAX_BYTES + 1), "image/jpeg") == ("picture_too_large", 413)
    # Smaller than a card's least, larger than a page's frame, and of no card's shape.
    assert _refused(jpeg(319, 180), "image/jpeg") == ("picture_size", 422)
    assert _refused(jpeg(PICTURE_MOST[0] + 2, 720), "image/jpeg") == ("picture_size", 422)
    assert _refused(jpeg(640, 721), "image/jpeg") == ("picture_size", 422)
    # Anything after the picture, or a picture that is not what it says it is.
    assert _refused(jpeg(640, 360) + b"after the end", "image/jpeg") == ("picture_refused", 422)
    assert _refused(_webp(640, 360), "image/jpeg") == ("picture_refused", 422)


def test_a_picture_with_camera_data_in_it_is_refused():
    from PIL import Image

    buffer = io.BytesIO()
    exif = Image.Exif()
    exif[0x010F] = "A camera"  # Make
    Image.new("RGB", (640, 360), (120, 120, 120)).save(buffer, "JPEG", exif=exif.tobytes())
    assert _refused(buffer.getvalue(), "image/jpeg") == ("picture_refused", 422)


def _entry(**changes: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "source_kind": "generated",
        "source_attachments": (),
        "previous_source_attachments": (),
        "authored_version_id": uuid.UUID(int=1),
        "authored_state_sha256": "a" * 64,
        "current_authored_state_sha256": "c" * 64,
        "style_version_id": uuid.UUID(int=2),
    }
    values.update(changes)
    return SimpleNamespace(**values)


def test_no_world_that_holds_or_held_a_photograph_is_given_a_picture():
    refuse_a_world_of_photographs(_entry())  # type: ignore[arg-type]
    refuse_a_world_of_photographs(_entry(source_kind="authored"))  # type: ignore[arg-type]
    for photographed in (
        _entry(source_kind="personal"),
        _entry(source_kind="authored", source_attachments=(object(),)),
        _entry(source_kind="authored", previous_source_attachments=(object(),)),
    ):
        with pytest.raises(PictureRefused) as refused:
            refuse_a_world_of_photographs(photographed)  # type: ignore[arg-type]
        assert (refused.value.code, refused.value.status) == ("picture_of_photographs", 422)


def test_a_picture_shows_the_world_as_opening_its_entry_draws_it():
    entry = _entry()
    assert PictureShows.of(entry) == PictureShows(uuid.UUID(int=1), "a" * 64, uuid.UUID(int=2))  # type: ignore[arg-type]
    # The state the entry is saved at, which a reopen draws; a later state of its branch is not it.
    assert PictureShows.of(_entry(authored_state_sha256="b" * 64)) != PictureShows.of(entry)  # type: ignore[arg-type]
    assert PictureShows.of(_entry(current_authored_state_sha256="b" * 64)) == PictureShows.of(entry)  # type: ignore[arg-type]
