"""The shared store of generated pieces, and the one path that writes to it.

A generated piece is kept once, in the ``generated-pieces`` namespace every workspace shares
(:data:`exulanica.store.namespaces.GENERATED_PIECE_NAMESPACE`), because it is made only from catalog
content: a shipped thing kind, a recipe catalog's words or the kind's look role, a committed style
pack's palette and style words, the session's pinned models and a seed drawn from the request. It
holds nothing of any workspace's, so no workspace's erasure reaches it; the workspace rows that name
it (``piece_batch``, ``piece_output``) are erased under the workspace's tombstone.

That guarantee is checked here, at the store's own boundary, and does not rest on the check the
request store made when the request was asked (:func:`admit_piece`):

- the request reads strictly and its words are the catalogs' (a description, when it has one, is
  the recipe catalog's words for the entry it names, and its style words are the style catalog's:
  :func:`exulanica.generation.requests.assert_catalog_words`), so it is catalog content;
- its thing kind is a shipped kind version at the digest it names, and its pack a committed pack
  version this server serves at the digest it names;
- the receipt reads against the request (its digest, its variant's seed, its licence, its verdict)
  and names the session's components digest, the pinned models it ran;
- the bytes hash to the receipt's output digest and are the size it states;
- the receipt's post-process version is the one this code makes pieces under, and the piece's
  cache key (the request's digest, the session's components and that version:
  :func:`exulanica_pieces.records.cache_key`) is computed here and returned with it, so the index of
  kept pieces (``generated_piece``) and each output name the key the piece was checked under.

:func:`store_piece` is the one write path: it takes the raw request, receipt and bytes and runs
:func:`admit_piece` itself, so no piece reaches the store without passing it. A piece failing any
of these is refused and nothing is written. A request carrying a person's own
words, should one ever be accepted, is therefore refused here by construction: its pieces belong in
the asking workspace's own namespace.

The namespace is bounded (:data:`MAX_BYTES_ENV`, default :data:`DEFAULT_MAX_BYTES`): a piece that
would take it past the bound is refused. Removing pieces no row names is the operator's, by a
command planned for a later package.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from exulanica_pieces.canonical import Refused, sha256_hex
from exulanica_pieces.records import POSTPROCESS_VERSION, cache_key, read_receipt, read_request

from exulanica.env import env_get, env_name
from exulanica.evidence.blob import BlobId
from exulanica.generation.requests import (
    GenerationCatalogs,
    PieceAskRefused,
    assert_catalog_words,
)
from exulanica.things.kinds import ThingKind
from exulanica.world.style_pack_library import StylePackLibrary

__all__ = [
    "DEFAULT_MAX_BYTES",
    "MAX_BYTES_ENV",
    "AdmittedPiece",
    "PieceRefused",
    "admit_piece",
    "max_bytes",
    "store_piece",
]

MAX_BYTES_ENV: Final = env_name("GENERATED_PIECES_MAX_BYTES")
#: Two gibibytes: about 13,000 pieces of the 154 KB a piece measured in the warm sessions.
DEFAULT_MAX_BYTES: Final = 2 << 30


class PieceRefused(ValueError):
    """A piece the shared store does not take, with a code."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


@dataclass(frozen=True, slots=True)
class AdmittedPiece:
    """A piece checked at the store's boundary: its request and receipt documents and its bytes."""

    request: Mapping[str, Any]
    receipt: Mapping[str, Any]
    receipt_raw: bytes
    piece_sha256: str
    piece: bytes
    #: What the piece is kept under: never generated twice under the same key.
    cache_key: str


def max_bytes(environ: Mapping[str, str] | None = None) -> int:
    """The namespace's bound in bytes, from the deployment, or the default."""
    raw = env_get("GENERATED_PIECES_MAX_BYTES", environ)
    if raw is None or raw == "":
        return DEFAULT_MAX_BYTES
    if not raw.isdigit() or int(raw) <= 0:
        raise ValueError(f"{MAX_BYTES_ENV} is a positive whole number of bytes")
    return int(raw)


def admit_piece(
    *,
    request_raw: bytes,
    receipt_raw: bytes,
    piece: bytes,
    components_sha256: str,
    catalogs: GenerationCatalogs,
    library: StylePackLibrary,
    shipped: Mapping[tuple[str, int], ThingKind],
) -> AdmittedPiece:
    """Check a piece at the shared store's boundary, or refuse it (:class:`PieceRefused`)."""
    try:
        request = read_request(request_raw, catalogs.budgets)
    except Refused as refused:
        raise PieceRefused("request_unreadable", str(refused)) from refused
    try:
        assert_catalog_words(request, catalogs)
    except PieceAskRefused as refused:
        raise PieceRefused("piece_not_catalog", refused.detail) from refused
    kind = request.get("thing_kind")
    if kind is None:
        raise PieceRefused("piece_not_catalog", "a shared piece is made to a shipped thing kind")
    shipped_kind = shipped.get((kind["key"], kind["version"]))
    if shipped_kind is None or shipped_kind.sha256 != kind["sha256"]:
        raise PieceRefused("piece_not_catalog", "the piece's thing kind is not a shipped kind")
    pack = request["pack"]
    if not library.holds(pack["id"], pack["version"], pack["sha256"]):
        raise PieceRefused("piece_not_catalog", "the piece's pack is not a committed pack version")
    try:
        receipt = read_receipt(receipt_raw, request)
    except Refused as refused:
        raise PieceRefused("receipt_unreadable", str(refused)) from refused
    if receipt["components_sha256"] != components_sha256:
        raise PieceRefused(
            "piece_not_catalog", "the piece was made by other models than the session's"
        )
    output = receipt["output"]
    if sha256_hex(piece) != output["sha256"] or len(piece) != output["bytes"]:
        raise PieceRefused("piece_not_its_bytes", "the piece is not the bytes its receipt states")
    version = receipt["postprocess"].get("version")
    if version != POSTPROCESS_VERSION:
        raise PieceRefused(
            "piece_not_catalog", "the piece was post-processed under another version than this code"
        )
    return AdmittedPiece(
        request=request,
        receipt=receipt,
        receipt_raw=receipt_raw,
        piece_sha256=output["sha256"],
        piece=piece,
        cache_key=cache_key(receipt["request_sha256"], components_sha256, version),
    )


def _stored_bytes(store: Any) -> int:
    return sum(store.size(blob) for blob in store.iter_blob_ids())


def store_piece(
    store: Any,
    *,
    request_raw: bytes,
    receipt_raw: bytes,
    piece: bytes,
    components_sha256: str,
    catalogs: GenerationCatalogs,
    library: StylePackLibrary,
    shipped: Mapping[tuple[str, int], ThingKind],
    bound: int,
) -> AdmittedPiece:
    """Admit a piece at the boundary (:func:`admit_piece`) and keep it in the shared store, or
    refuse it (:class:`PieceRefused`). A piece already there is not written again; one that would
    take the namespace past ``bound`` is refused. Returns what was admitted."""
    admitted = admit_piece(
        request_raw=request_raw,
        receipt_raw=receipt_raw,
        piece=piece,
        components_sha256=components_sha256,
        catalogs=catalogs,
        library=library,
        shipped=shipped,
    )
    blob = BlobId.from_hex(admitted.piece_sha256)
    if store.exists(blob):
        return admitted
    if _stored_bytes(store) + len(admitted.piece) > bound:
        raise PieceRefused("pieces_store_full", "the generated pieces store is at its bound")
    store.put_bytes(admitted.piece)
    return admitted
