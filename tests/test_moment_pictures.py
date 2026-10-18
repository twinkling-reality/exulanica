"""A History picture's rules without a database (exulanica/world/moment_pictures.py, 0223).

A portrait is a square JPEG or WebP walked whole, from 128 to 512 pixels a side and at most 128 KiB;
a recipe is a name and a version; a kept picture serves its digest and size; the moments read names
a kept picture only to a grant the picture route's plain requirement admits. The routes, the store
and erasure are ``test_moment_pictures_postgres.py``.
"""

from __future__ import annotations

import hashlib

import pytest
from exulanica.api.permissions import BrowserRequires, Granted, Permission, Requires
from exulanica.api.routes import world_history_moments
from exulanica.world.moment_pictures import (
    PORTRAIT_MAX_BYTES,
    RECIPE_PATTERN,
    checked_portrait,
)
from exulanica.world.saved_entry_pictures import PictureRefused

from style_pack_upload_support import jpeg


def test_the_moments_read_names_a_picture_only_under_the_picture_route_s_plain_requirement(
    monkeypatch,
):
    write, read = frozenset({Permission.WORLD_WRITE}), frozenset({Permission.WORLD_READ})
    # The control: the picture route's own rule today admits a grant holding world.write alone.
    assert world_history_moments._reads_pictures(write)
    assert not world_history_moments._reads_pictures(read)
    for rule, told in (
        (Requires(frozenset({Permission.WORLD_WRITE})), True),
        # A kind that asks more than the permissions is not read here: it names no picture.
        (Granted(frozenset({Permission.WORLD_WRITE})), False),
        (BrowserRequires(frozenset({Permission.WORLD_WRITE}), owner_only=True), False),
    ):
        monkeypatch.setattr(world_history_moments, "rule_for", lambda *_route, rule=rule: rule)
        assert world_history_moments._reads_pictures(write) is told, rule
        assert not world_history_moments._reads_pictures(read)


def test_a_portrait_is_a_square_picture_walked_whole():
    data = jpeg(256, 256)
    assert checked_portrait(data, "image/jpeg") == (256, 256, hashlib.sha256(data).hexdigest())
    for size in ((640, 360), (96, 96), (600, 600)):
        with pytest.raises(PictureRefused) as refused:
            checked_portrait(jpeg(*size), "image/jpeg")
        assert refused.value.code == "picture_size" and refused.value.status == 422
    with pytest.raises(PictureRefused) as png:
        checked_portrait(b"\x89PNG", "image/png")
    assert png.value.code == "picture_media_type" and png.value.status == 415
    with pytest.raises(PictureRefused) as large:
        checked_portrait(b"\xff" * (PORTRAIT_MAX_BYTES + 1), "image/jpeg")
    assert large.value.code == "picture_too_large" and large.value.status == 413
    with pytest.raises(PictureRefused) as tail:
        checked_portrait(jpeg(256, 256) + b"after the end", "image/jpeg")
    assert tail.value.code == "picture_refused"


def test_a_recipe_is_a_name_and_a_version():
    for good in ("moment-framing/v1", "portrait/v12"):
        assert RECIPE_PATTERN.match(good)
    for bad in ("Framing/v1", "framing", "framing/v0", "framing/1", "a/b/v1", "-x/v1"):
        assert not RECIPE_PATTERN.match(bad), bad
