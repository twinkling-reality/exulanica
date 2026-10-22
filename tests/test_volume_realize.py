"""A volume's surface by chunk: closed and consistently turned across chunk seams, on the surface,
facing out, pinned by digest, and read back only as the chunk its digest names."""

from __future__ import annotations

import copy
import hashlib
from collections import Counter

import pytest
from exulanica.canonical import canonical_json, sha256_of_canonical
from exulanica.grammar.geometry import integer_sqrt
from exulanica.grammar.volumes import (
    CHUNK_MM,
    PROFILE,
    SERVED_VOLUME_RULES,
    VolumeChunk,
    VolumeField,
    VolumeRefused,
    read_volume_chunk,
    read_volume_document,
    realize_chunk,
    realize_volume,
    volume_chunks,
)

from test_volume_field import SEED, golden_field

#: The stack's chunks at 4 m under each served volume rules version (``golden_field``): how many
#: hold surface, and the digest of their digests in order. A change that moves one vertex is a new
#: rules version.
GOLDEN_CHUNKS = {
    1: {"count": 12, "digest": "b7aa34e5b2d548e8b2c3fe3652515d8b189cbb641dd4924d70cc63c9b89895f4"},
    2: {"count": 12, "digest": "d78797a384722dca7cf50621f2c2c4d8289089b510b7454293b2cff9b98102c1"},
    3: {"count": 12, "digest": "ee2b0b587b302b38745db6aaa26911077adcd2d1d62fb8ff704c17c173984207"},
    # Version 3's rock vertex for vertex; its chunks name version 4.
    4: {"count": 12, "digest": "649f3cd450d1604151376286f68b995ae46df9a02792810f7a2cf89f33089593"},
}


def field_of(*parts: dict, **top: object) -> VolumeField:
    raw = {"profile": PROFILE, "id": "probe", **top, "parts": list(parts)}
    return VolumeField(read_volume_document(raw), SEED)


BALL = field_of({"id": "ball", "shape": "sphere", "at_mm": [3000, -2000, 5000], "radius_mm": 6000})


def welded(chunks: tuple[VolumeChunk, ...]) -> tuple[Counter, Counter, Counter]:
    """Every edge across all chunks by vertex position, undirected and directed, and every
    triangle by its corners' positions."""
    undirected: Counter = Counter()
    directed: Counter = Counter()
    faces: Counter = Counter()
    for chunk in chunks:
        p = chunk.positions_mm
        point = [tuple(p[3 * n : 3 * n + 3]) for n in range(chunk.vertex_count)]
        t = chunk.triangles
        for a, b, c in zip(t[0::3], t[1::3], t[2::3], strict=True):
            faces[frozenset((point[a], point[b], point[c]))] += 1
            for u, v in ((a, b), (b, c), (c, a)):
                undirected[frozenset((point[u], point[v]))] += 1
                directed[(point[u], point[v])] += 1
    return undirected, directed, faces


def assert_closed(chunks: tuple[VolumeChunk, ...]) -> None:
    undirected, directed, faces = welded(chunks)
    assert undirected, "no surface"
    # Every edge borders an even number of triangles (two, or four where two sheets pinch), no
    # edge collapses to a point, each is crossed as often one way as the other, and no triangle is
    # drawn twice (as it would be by two chunks owning one seam edge).
    assert all(count == 1 for count in faces.values())
    assert all(count % 2 == 0 for count in undirected.values())
    assert all(len(edge) == 2 for edge in undirected)
    assert all(directed[(v, u)] == count for (u, v), count in directed.items())


def test_a_sphere_meshes_closed_on_its_surface_and_facing_out():
    chunks = realize_volume(BALL, 1000)
    assert len(chunks) > 1  # the ball crosses chunk seams, which the closure check then covers
    assert_closed(chunks)
    for chunk in chunks:
        for n in range(chunk.vertex_count):
            x, y, z = chunk.positions_mm[3 * n : 3 * n + 3]
            dx, dy, dz = x - 3000, y + 2000, z - 5000
            assert abs(integer_sqrt(dx * dx + dy * dy + dz * dz) - 6000) <= 1000
            nx, ny, nz = chunk.normals[3 * n : 3 * n + 3]
            assert nx * dx + ny * dy + nz * dz > 0


@pytest.mark.parametrize("version", sorted(SERVED_VOLUME_RULES))
def test_the_stack_meshes_closed_across_its_chunks_at_every_level(version):
    field = golden_field(version)
    for cell in (4000, 2000):
        assert_closed(realize_volume(field, cell))


def test_the_stack_chunks_are_pinned_and_name_their_rules():
    assert set(GOLDEN_CHUNKS) == set(SERVED_VOLUME_RULES)
    for version, golden in GOLDEN_CHUNKS.items():
        chunks = realize_volume(golden_field(version), 4000)
        assert len(chunks) == golden["count"]
        assert sha256_of_canonical([chunk.sha256 for chunk in chunks]).hex() == golden["digest"]
        assert {chunk.document()["rules_version"] for chunk in chunks} == {version}
        assert read_volume_chunk(chunks[0].document(), chunks[0].sha256) == chunks[0]


def test_space_with_no_surface_gives_an_empty_chunk_that_a_volume_leaves_out():
    far = realize_chunk(BALL, (5, 5, 5), 2000)
    assert (far.positions_mm, far.triangles) == ((), ())
    searched = volume_chunks(BALL, 2000)
    kept = realize_volume(BALL, 2000)
    assert (5, 5, 5) not in searched
    assert {chunk.chunk for chunk in kept} <= set(searched)
    with pytest.raises(VolumeRefused, match="cell of"):
        realize_chunk(BALL, (0, 0, 0), 3000)


def test_every_vertex_takes_the_look_of_the_nearest_added_part():
    field = field_of(
        {"id": "rock", "shape": "box", "at_mm": [-8000, 0, 0], "size_mm": [8000, 8000, 8000]},
        {"id": "built", "shape": "box", "at_mm": [8000, 0, 0], "size_mm": [8000, 8000, 8000],
         "look": "wall"},
    )  # fmt: skip
    for chunk in realize_volume(field, 1000):
        for n in range(chunk.vertex_count):
            x = chunk.positions_mm[3 * n]
            assert chunk.looks[chunk.vertex_looks[n]] == ("wall" if x > 0 else "rock")


def test_a_chunk_reads_back_only_as_the_chunk_its_digest_names():
    chunk = next(chunk for chunk in realize_volume(BALL, 2000) if chunk.vertex_count > 3)
    assert read_volume_chunk(copy.deepcopy(chunk.document()), chunk.sha256) == chunk
    assert chunk.sha256 == hashlib.sha256(canonical_json(chunk.document())).hexdigest()
    with pytest.raises(VolumeRefused) as caught:
        read_volume_chunk(chunk.document(), "0" * 64)
    assert caught.value.code == "volume_digest_mismatch"


def _changed(chunk: VolumeChunk, name: str, value: object) -> dict:
    document = copy.deepcopy(chunk.document())
    document[name] = value(document[name]) if callable(value) else value
    return document


@pytest.mark.parametrize(
    ("name", "value", "path", "code"),
    [
        ("profile", "exulanica.volume-chunk/v2", "profile", "volume_invalid"),
        ("rules_version", 5, "rules_version", "volume_rules_changed"),
        ("rules_version", True, "rules_version", "volume_rules_changed"),
        ("volume_sha256", "ABC", "volume_sha256", "volume_invalid"),
        ("cell_mm", 3000, "cell_mm", "volume_invalid"),
        ("cell_mm", 2000.0, "cell_mm", "volume_invalid"),
        ("chunk", [0, 0], "chunk", "volume_invalid"),
        ("looks", ["rock"], "looks", "volume_invalid"),
        ("positions_mm", lambda p: [p[0] + 3 * CHUNK_MM, *p[1:]], "positions_mm", "volume_invalid"),
        ("positions_mm", lambda p: p[:-1], "positions_mm", "volume_invalid"),
        ("normals", lambda n: n[:-3], "normals", "volume_invalid"),
        ("normals", lambda n: [40000, *n[1:]], "normals", "volume_invalid"),
        ("triangles", lambda t: [*t[:-1], 10**6], "triangles", "volume_invalid"),
        ("vertex_looks", lambda v: [2, *v[1:]], "vertex_looks", "volume_invalid"),
    ],
)  # fmt: skip
def test_a_chunk_that_breaks_its_profile_is_refused_by_path(name, value, path, code):
    chunk = next(chunk for chunk in realize_volume(BALL, 2000) if chunk.vertex_count > 3)
    with pytest.raises(VolumeRefused) as caught:
        read_volume_chunk(_changed(chunk, name, value))
    assert (caught.value.path, caught.value.code) == (path, code)
