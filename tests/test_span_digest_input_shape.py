"""The database refuses a span whose digest input has the wrong shape.

Migration 0001 described the region and text-anchor tuples in comments and enforced neither. A
comment cannot stop a writer storing `0.312` where it meant `312000`, or storing the `prefix` and
`suffix` keys that comment mentions and no writer has ever produced. Either row hashes to a
`span_digest` a second implementation computes differently from the same address, and the citation
token verified against it then fails for a reason nothing in the row explains.

`exulanica.evidence` already refuses every shape below in Python. These tests are the other half:
the refusal on a route that does not go through that class. Neither subsumes the other.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest

REFUSED = psycopg.errors.CheckViolation

_UPRIGHT_DISPLAY = '"display":{"w":4032,"h":3024,"rotation":0,"sar_num":1,"sar_den":1}'
_ANCHOR = f'"artifact_id":"{uuid.UUID(int=7)}","char_start":0,"char_end":12'


@pytest.fixture
def blob(repository):
    digest = bytes(range(32))
    repository.connection.execute(
        "insert into blob (blob_sha256, byte_size, media_type) values (%s, 1, 'image/jpeg')",
        (digest,),
    )
    return digest


def _digest(seed: int) -> bytes:
    """A distinct 32 bytes per row. `evidence_span_digest_uniq` is not what is under test."""
    return bytes([seed]) + bytes(31)


def _insert_region(repository, blob, region: str, *, track: str = "v:0", seed: int = 1) -> None:
    repository.connection.execute(
        "insert into evidence_span (workspace_id, blob_sha256, track_key, t_start_ns, "
        f"t_end_ns, modality, region, span_digest) values (%s, %s, '{track}', 0, 1, "
        "'frame_region', %s, %s)",
        (repository.workspace_id, blob, region, _digest(seed)),
    )


def _insert_anchor(repository, blob, anchor: str, *, seed: int = 1) -> None:
    repository.connection.execute(
        "insert into evidence_span (workspace_id, blob_sha256, track_key, t_start_ns, "
        "t_end_ns, modality, text_anchor, span_digest) "
        "values (%s, %s, 'a:0', 0, 1000, 'transcript_text', %s, %s)",
        (repository.workspace_id, blob, anchor, _digest(seed)),
    )


def test_the_shape_this_pipeline_writes_is_accepted(repository, blob):
    """A constraint that refused a real row would be worse than no constraint."""
    _insert_region(
        repository,
        blob,
        '{"kind":"rect","rect":{"x":312000,"y":220000,"w":184000,"h":401000},'
        f"{_UPRIGHT_DISPLAY}}}",
        track="img",
        seed=1,
    )
    # The whole unit square, the largest legal region, and the boundary the ppm sum tests.
    _insert_region(
        repository,
        blob,
        '{"kind":"rect","rect":{"x":0,"y":0,"w":1000000,"h":1000000},' f"{_UPRIGHT_DISPLAY}}}",
        track="img",
        seed=2,
    )
    _insert_anchor(repository, blob, f'{{{_ANCHOR},"exact":"café"}}', seed=3)
    _insert_anchor(repository, blob, f"{{{_ANCHOR}}}", seed=4)


@pytest.mark.parametrize(
    ("why", "region"),
    [
        (
            "a float coordinate has no canonical rendering two writers agree on",
            '{"kind":"rect","rect":{"x":0.312,"y":0.22,"w":0.184,"h":0.401},'
            f"{_UPRIGHT_DISPLAY}}}",
        ),
        (
            "a negative origin is outside the normalised unit square",
            '{"kind":"rect","rect":{"x":-1,"y":220000,"w":184000,"h":401000},'
            f"{_UPRIGHT_DISPLAY}}}",
        ),
        (
            "a zero-area region overlaps nothing, so every overlap guard would pass it",
            '{"kind":"rect","rect":{"x":312000,"y":220000,"w":0,"h":401000},'
            f"{_UPRIGHT_DISPLAY}}}",
        ),
        (
            "a region may not extend past one million parts per million",
            '{"kind":"rect","rect":{"x":900000,"y":220000,"w":200000,"h":401000},'
            f"{_UPRIGHT_DISPLAY}}}",
        ),
        (
            "an unknown key changes the canonical bytes",
            '{"kind":"rect","rect":{"x":1,"y":1,"w":1,"h":1,"z":1},' f"{_UPRIGHT_DISPLAY}}}",
        ),
        (
            "an unknown kind is not the rectangle tuple this version froze",
            '{"kind":"polygon","rect":{"x":1,"y":1,"w":1,"h":1},' f"{_UPRIGHT_DISPLAY}}}",
        ),
        (
            "a missing display space is the difference between two different addresses",
            '{"kind":"rect","rect":{"x":1,"y":1,"w":1,"h":1}}',
        ),
        (
            "a rotation outside the four allowed values cannot be applied by anything",
            '{"kind":"rect","rect":{"x":1,"y":1,"w":1,"h":1},'
            '"display":{"w":4032,"h":3024,"rotation":45,"sar_num":1,"sar_den":1}}',
        ),
        (
            "a zero sample aspect ratio is not a ratio",
            '{"kind":"rect","rect":{"x":1,"y":1,"w":1,"h":1},'
            '"display":{"w":4032,"h":3024,"rotation":0,"sar_num":0,"sar_den":1}}',
        ),
    ],
)
def test_a_malformed_region_tuple_is_refused(repository, blob, why, region):
    with pytest.raises(REFUSED, match="evidence_span_region_shape"):
        _insert_region(repository, blob, region)


@pytest.mark.parametrize(
    ("why", "anchor"),
    [
        (
            "prefix and suffix were named in 0001's comment and never written; they stay out",
            f'{{{_ANCHOR},"prefix":"before","suffix":"after"}}',
        ),
        ("an empty character range highlights nothing", f'{{"artifact_id":"{uuid.UUID(int=7)}",'
         '"char_start":12,"char_end":12}'),
        ("a reversed character range is not half-open", f'{{"artifact_id":"{uuid.UUID(int=7)}",'
         '"char_start":12,"char_end":4}'),
        ("a float character offset is not an offset", f'{{"artifact_id":"{uuid.UUID(int=7)}",'
         '"char_start":0.5,"char_end":12}'),
        ("an anchor without its artifact points at nothing", '{"char_start":0,"char_end":12}'),
    ],
)
def test_a_malformed_text_anchor_is_refused(repository, blob, why, anchor):
    with pytest.raises(REFUSED, match="evidence_span_text_anchor_shape"):
        _insert_anchor(repository, blob, anchor)
