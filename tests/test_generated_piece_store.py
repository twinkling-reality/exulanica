"""The shared store of generated pieces: its boundary takes catalog pieces only, and its bound.

The piece is the well's (``fixture.well`` in the default look), with warm session 1's first well
receipt (``ml/appearance/evidence/generated-assets-session-1``) restated for the request and its
seed, and piece bytes of the size that receipt measured. Each refusal changes one thing about a
piece the boundary otherwise takes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from exulanica.evidence.blob import BlobId
from exulanica.generation.pieces import (
    DEFAULT_MAX_BYTES,
    PieceRefused,
    admit_piece,
    max_bytes,
    store_piece,
)
from exulanica.generation.requests import LookReference, generation_catalogs, plan_requests
from exulanica.store.local import LocalContentAddressedStore
from exulanica.things.kinds import shipped_thing_kinds
from exulanica.world.style_pack_library import style_pack_library
from exulanica_pieces.canonical import canonical_bytes, sha256_hex
from exulanica_pieces.records import POSTPROCESS_VERSION, build_receipt, read_job, seed_for

ROOT = Path(__file__).resolve().parents[1]
SESSION_1 = ROOT / "ml/appearance/evidence/generated-assets-session-1"
LIBRARY = style_pack_library()
CATALOGS = generation_catalogs()
SHIPPED = shipped_thing_kinds()
COMPONENTS = read_job(min((SESSION_1 / "jobs").glob("*.json")).read_bytes())["components_sha256"]


def _well_request() -> dict:
    pack = LIBRARY.default_pack
    look = LookReference(pack.pack_id, pack.version, pack.manifest_sha256)
    [planned] = plan_requests([("well", 1)], look, library=LIBRARY)
    return json.loads(planned.request)


def _template() -> dict:
    return min(
        (
            json.loads(path.read_bytes())
            for path in (SESSION_1 / "receipts").glob("*.json")
            if json.loads(path.read_bytes())["request_sha256"].startswith("4743c0a6")
        ),
        key=lambda receipt: receipt["variant"],
    )


def _piece(
    request: dict, *, components: str = COMPONENTS, postprocess: str | None = None
) -> tuple[bytes, bytes, bytes]:
    """The request's, the receipt's and the piece's bytes for variant 0."""
    request_raw = canonical_bytes(request)
    template = _template()
    if postprocess is not None:
        template["postprocess"] = {**template["postprocess"], "version": postprocess}
    piece = b"\x01" * template["measured"]["glb_bytes"]
    request_sha256 = sha256_hex(request_raw)
    receipt = build_receipt(
        {
            **template,
            "components_sha256": components,
            "output": {"bytes": len(piece), "sha256": sha256_hex(piece)},
            "request_sha256": request_sha256,
            "seed": seed_for(request_sha256, 0),
            "variant": 0,
        },
        request,
    )
    return request_raw, receipt, piece


def _admit(request_raw: bytes, receipt_raw: bytes, piece: bytes, components: str = COMPONENTS):
    return admit_piece(
        request_raw=request_raw,
        receipt_raw=receipt_raw,
        piece=piece,
        components_sha256=components,
        catalogs=CATALOGS,
        library=LIBRARY,
        shipped=SHIPPED,
    )


def _refused(code: str, request_raw: bytes, receipt_raw: bytes, piece: bytes, **kw) -> None:
    with pytest.raises(PieceRefused) as refused:
        _admit(request_raw, receipt_raw, piece, **kw)
    assert refused.value.code == code


def _store(store, request_raw: bytes, receipt_raw: bytes, piece: bytes, *, bound: int):
    return store_piece(
        store,
        request_raw=request_raw,
        receipt_raw=receipt_raw,
        piece=piece,
        components_sha256=COMPONENTS,
        catalogs=CATALOGS,
        library=LIBRARY,
        shipped=SHIPPED,
        bound=bound,
    )


def test_a_catalog_piece_is_admitted_and_kept_once(tmp_path) -> None:
    store = LocalContentAddressedStore(tmp_path / "generated-pieces")
    request_raw, receipt_raw, piece = _piece(_well_request())
    admitted = _store(store, request_raw, receipt_raw, piece, bound=DEFAULT_MAX_BYTES)
    blob = BlobId.from_hex(admitted.piece_sha256)
    assert store.exists(blob) and store.size(blob) == len(piece)
    # Kept under the cache key of its request, the session's models and the post-process version,
    # recomputed here from the parts the records module's docstring names.
    expected = sha256_hex(
        canonical_bytes(
            {
                "components_sha256": COMPONENTS,
                "postprocess": "exulanica.generated-asset-postprocess/v2",
                "request_sha256": sha256_hex(request_raw),
            }
        )
    )
    assert admitted.cache_key == expected
    # The same piece again is the same object: nothing is written twice.
    names = sorted(
        path.name for path in (tmp_path / "generated-pieces").rglob("*") if path.is_file()
    )
    _store(store, request_raw, receipt_raw, piece, bound=DEFAULT_MAX_BYTES)
    assert names == sorted(
        path.name for path in (tmp_path / "generated-pieces").rglob("*") if path.is_file()
    )


def test_the_store_writes_only_what_passes_its_own_boundary(tmp_path) -> None:
    # The one write path admits the piece itself: a piece the boundary refuses is never written,
    # whatever the caller checked before.
    store = LocalContentAddressedStore(tmp_path / "generated-pieces")
    request = {**_well_request(), "description": "a well like the one at my grandmother's"}
    with pytest.raises(PieceRefused) as refused:
        _store(store, *_piece(request), bound=DEFAULT_MAX_BYTES)
    assert refused.value.code == "piece_not_catalog"
    assert not list(store.iter_blob_ids())


def test_a_piece_post_processed_under_another_version_is_refused() -> None:
    assert POSTPROCESS_VERSION == "exulanica.generated-asset-postprocess/v2"
    _refused(
        "piece_not_catalog",
        *_piece(_well_request(), postprocess="exulanica.generated-asset-postprocess/v1"),
    )


def test_a_request_carrying_words_no_catalog_holds_is_refused() -> None:
    request = {**_well_request(), "description": "a well like the one at my grandmother's"}
    _refused("piece_not_catalog", *_piece(request))


def test_style_words_other_than_the_style_catalogs_are_refused() -> None:
    request = _well_request()
    request["pack"] = {**request["pack"], "style": "in the style of my own photographs"}
    _refused("piece_not_catalog", *_piece(request))


def test_a_thing_kind_not_shipped_at_its_digest_is_refused() -> None:
    request = _well_request()
    request["thing_kind"] = {**request["thing_kind"], "sha256": "0" * 64}
    _refused("piece_not_catalog", *_piece(request))


def test_a_look_this_server_does_not_serve_at_its_digest_is_refused() -> None:
    request = _well_request()
    request["pack"] = {**request["pack"], "sha256": "0" * 64}
    _refused("piece_not_catalog", *_piece(request))


def test_a_piece_made_by_other_models_than_the_sessions_is_refused() -> None:
    _refused("piece_not_catalog", *_piece(_well_request(), components="1" * 64))


def test_a_receipt_for_another_request_is_refused() -> None:
    request_raw, _, piece = _piece(_well_request())
    other = _well_request()
    other["variants"] = other["variants"] - 1
    _, receipt_raw, _ = _piece(other)
    _refused("receipt_unreadable", request_raw, receipt_raw, piece)


def test_bytes_other_than_the_receipts_are_refused() -> None:
    request_raw, receipt_raw, piece = _piece(_well_request())
    _refused("piece_not_its_bytes", request_raw, receipt_raw, b"\x02" * len(piece))
    _refused("piece_not_its_bytes", request_raw, receipt_raw, piece + b"\x01")


def test_a_piece_past_the_bound_is_refused_and_nothing_is_written(tmp_path) -> None:
    store = LocalContentAddressedStore(tmp_path / "generated-pieces")
    request_raw, receipt_raw, piece = _piece(_well_request())
    store.put_bytes(b"already kept")
    bound = len(b"already kept") + len(piece) - 1
    with pytest.raises(PieceRefused) as refused:
        _store(store, request_raw, receipt_raw, piece, bound=bound)
    assert refused.value.code == "pieces_store_full"
    assert not store.exists(BlobId.from_hex(sha256_hex(piece)))
    admitted = _store(store, request_raw, receipt_raw, piece, bound=bound + 1)
    assert store.exists(BlobId.from_hex(admitted.piece_sha256))


def test_the_bound_is_the_deployments_or_two_gibibytes() -> None:
    assert max_bytes({}) == DEFAULT_MAX_BYTES == 2 << 30
    assert max_bytes({"EXULANICA_GENERATED_PIECES_MAX_BYTES": ""}) == DEFAULT_MAX_BYTES
    assert max_bytes({"EXULANICA_GENERATED_PIECES_MAX_BYTES": "1048576"}) == 1 << 20
    for raw in ("0", "-1", "1.5", "2GiB"):
        with pytest.raises(ValueError):
            max_bytes({"EXULANICA_GENERATED_PIECES_MAX_BYTES": raw})
