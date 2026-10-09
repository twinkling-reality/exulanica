"""A workspace look made of generated pieces, recorded, checked, worn, served and erased.

A derived look (``exulanica.generation.looks``) is a style pack version drawn on a library pack
with generated pieces in place of some of its own. Its files are named by digest in the one shared
store of generated pieces, and the workspace holds each only while a passed output of its own
names it. Against PostgreSQL, as the deployed runtime role writes:

*   recorded through ``record_generated`` only once an output names every piece, checked by the
    style pack check reading each piece from the shared store, then worn and served from it, and
    no longer worn or served once the output is gone;
*   a workspace tombstone erases the version and its file rows as it erases every version, enqueues
    nothing for its pieces and completes without them, and the shared bytes stay;
*   a person's upload bounds count uploads only: a workspace holding its sixteen still records a
    generated look.

The piece is a committed cozy piece standing in for a generated one: its colours are the base's
palette, as a generated piece's are. The outputs are written as the owner with the foreign keys'
triggers off, inside one transaction: what the held clause reads is the output's workspace, digest
and verdict, not how the generation worker came to write it.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

import pytest
from exulanica.deletion import queue
from exulanica.evidence.blob import BlobId
from exulanica.generation.looks import GeneratedVariant, build_derived_look
from exulanica.world.style_pack_checks import StylePackCheckWorker, colour_table, library_palettes
from exulanica.world.style_packs import canonical_json, load_context, read_manifest
from exulanica.world.workspace_style_packs import (
    GeneratedStylePackRefused,
    StylePackQuotaExceeded,
    StylePackWithdrawn,
    WorkspaceStylePackRepository,
)

from test_purge import purged as purged
from test_workspace_style_packs_postgres import Packs, admitted
from test_workspace_style_packs_postgres import packs as packs

pytestmark = pytest.mark.postgres

ROOT = Path(__file__).resolve().parents[1]
COZY = ROOT / "assets/style-packs/packs/exulanica.cozy-town"
PIECE = (COZY / "pieces/tree.glb").read_bytes()
DIGEST = hashlib.sha256(PIECE).hexdigest()


def _look(version: int = 1) -> tuple[bytes, str]:
    """A derived look on the cozy pack dressing its plants with the piece, under a generated id."""
    context = load_context(ROOT)
    base = read_manifest(json.loads((COZY / "manifest.json").read_text("utf-8")), context)
    variant = GeneratedVariant(DIGEST, len(PIECE), (3200, 3200, 6000), "1" * 64)
    look = build_derived_look(
        chain=[base],
        version=version,
        roles={"plant.default": [variant]},
        authors=["a test model"],
        context=context,
    )
    assert look is not None
    manifest = dict(look.manifest, pack_id="generated.cozy-town")
    return canonical_json(manifest).encode("ascii"), look.content_sha256


def _repository(packs: Packs) -> WorkspaceStylePackRepository:
    return WorkspaceStylePackRepository(
        packs.connection,
        packs.workspace_id,
        packs.actor,
        stores=packs.stores,
        generated_pieces=packs.content.generated_pieces,
    )


def _output(packs: Packs, *, within: bool = True) -> None:
    """A passed output of the workspace naming the piece, as the generation worker records one."""
    receipt = canonical_json({"piece_sha256": DIGEST})
    with packs.purged.database().session(packs.workspace_id) as owner, owner.transaction():
        owner.execute("set local session_replication_role = replica")
        owner.execute(
            "insert into piece_output (workspace_id, piece_request_id, variant, cache_key, "
            "  receipt_canonical, receipt_sha256, piece_sha256, within, over_checks) "
            "values (%s, %s, 0, %s, %s, %s, %s, %s, %s)",
            (
                packs.workspace_id,
                uuid.uuid4(),
                "c" * 64,
                receipt,
                hashlib.sha256(receipt.encode("ascii")).hexdigest(),
                DIGEST,
                within,
                [] if within else ["triangles"],
            ),
        )


def _check(packs: Packs) -> None:
    outcome = StylePackCheckWorker(
        packs.runtime,
        packs.stores,
        frozenset({packs.workspace_id}),
        table=colour_table(ROOT),
        library=library_palettes,
        generated_pieces=packs.content.generated_pieces,
    ).drain()
    assert (outcome.ready, outcome.errors) == (1, []), outcome


def test_a_generated_look_is_checked_worn_and_served_from_the_shared_store_while_its_output_holds(
    packs,
):
    manifest, content = _look()
    context = load_context(ROOT)
    repository = _repository(packs)
    packs.content.generated_pieces.put_bytes(PIECE)
    # No output of this workspace names the piece yet, and a failed one does not count.
    _output(packs, within=False)
    with pytest.raises(GeneratedStylePackRefused) as refused:
        repository.record_generated(
            manifest, content_sha256=content, asked_by=packs.actor, context=context
        )
    assert refused.value.code == "piece_not_held"
    _output(packs)
    record, created = repository.record_generated(
        manifest, content_sha256=content, asked_by=packs.actor, context=context
    )
    assert created and (record.origin, record.state, record.pack_id) == (
        "generated",
        "requested",
        "generated.cozy-town",
    )
    assert not repository.wearable(record.manifest_sha256)
    _check(packs)
    assert repository.wearable(record.manifest_sha256)
    served = repository.read_file(record.manifest_sha256, DIGEST)
    try:
        assert b"".join(served.chunks()) == PIECE
    finally:
        served.close()
    # The same pieces on the same base are found again; a new set takes the next version.
    assert repository.generated_version(content) == repository.version(record.manifest_sha256)
    assert repository.next_generated_version("generated.cozy-town") == 2
    # Nothing was written to the workspace's own namespace or its inventory.
    assert not packs.in_namespace(DIGEST)
    assert not packs.owner_rows("select 1 from workspace_style_pack_blob")
    # Once no output of the workspace names the piece, the look is neither worn nor served.
    with packs.purged.database().session(packs.workspace_id) as owner, owner.transaction():
        owner.execute("set local session_replication_role = replica")
        owner.execute("delete from piece_output where workspace_id = %s", (packs.workspace_id,))
    assert not repository.wearable(record.manifest_sha256)
    with pytest.raises(StylePackWithdrawn):
        repository.read_file(record.manifest_sha256, DIGEST)


def test_a_workspace_tombstone_erases_a_generated_look_and_only_the_shared_bytes_stay(packs):
    manifest, content = _look()
    packs.content.generated_pieces.put_bytes(PIECE)
    _output(packs)
    record, _created = _repository(packs).record_generated(
        manifest, content_sha256=content, asked_by=packs.actor, context=load_context(ROOT)
    )
    _check(packs)
    tombstone = packs.purged.repository.insert_tombstone(
        scope="workspace", requested_by=uuid.uuid4(), reason="the person left"
    )
    [version] = packs.owner_rows(
        "select pack_id, manifest_canonical, declaration_canonical, receipt_document, origin, "
        "erased_at from workspace_style_pack_version"
    )
    assert version["pack_id"] == "erased.x" + record.manifest_sha256[:24]
    assert (version["manifest_canonical"], version["declaration_canonical"]) == (None, None)
    assert version["receipt_document"] == {"erased": True} and version["erased_at"] is not None
    assert packs.owner_rows("select path, source from workspace_style_pack_file") == [
        {"path": None, "source": "generated_piece"}
    ]
    # The workspace's outputs go with it (the piece batch migration's own trigger), and nothing is
    # queued for the shared piece: the tombstone completes without it, and the bytes stay.
    assert not packs.owner_rows(
        "select 1 from piece_output where workspace_id = %s", packs.workspace_id
    )
    assert not packs.owner_rows(
        "select 1 from purge_job where tombstone_id = %s and target_ref = %s", tombstone, DIGEST
    )
    outcome = packs.production_purge().drain()
    assert outcome.failed == 0 and outcome.blocked is None, outcome
    assert queue.is_purge_complete(packs.purged.repository.connection, tombstone)
    assert packs.content.generated_pieces.exists(BlobId.from_hex(DIGEST))


def test_a_person_s_upload_bounds_count_their_uploads_only(packs):
    # Each made ready before the next, since at most four checks wait at once.
    for version in range(1, 17):
        packs.ready(admitted(version=version, pieces=1))
    with pytest.raises(StylePackQuotaExceeded, match="16 style pack versions"):
        packs.repository().record(admitted(version=17, pieces=1))
    manifest, content = _look()
    _output(packs)
    record, created = _repository(packs).record_generated(
        manifest, content_sha256=content, asked_by=packs.actor, context=load_context(ROOT)
    )
    assert created and record.origin == "generated"
