"""Read the generated tier, kept structurally apart from everything that was observed.

Roadmap Phase 10 capability 2, the read half. This is a separate module and a separate payload
field from :mod:`exulanica.graph.scene_geometry` for one reason: a consumer must have to write
code that reads ``generated_geometry`` before it can draw a generated surface. A boolean on the
trained-geometry row would let a client that ignored one field draw imagination as record, and the
client authors who most need the distinction are the ones least likely to have read this file.

Three guards, all inherited rather than reinvented:

* ``person_withdrawal_blocks_artifact``, so a generation that depended on a withdrawn person's
  photographs stops being served the moment the withdrawal commits;
* the ``artifact_current`` view, so a superseded generation is not offered beside its replacement;
* the receipt's own digest, checked against the bytes, so a corrupted receipt reports ``invalid``
  rather than being parsed into fields nobody verified.

There is deliberately no bytes route here. The generated payload itself is whatever the model
produced, in a container the renderer already validates, and serving it is a decision that belongs
with the proof lens that draws it under a label. Until that lands, the graph reports that the
generation exists, what produced it, and what it was conditioned on, and the world draws nothing.
An unavailable state is an honest answer; a drawn surface with no label is not.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Final

import psycopg

from exulanica.canonical import canonical_json
from exulanica.errors import BlobNotFoundError, IntegrityError
from exulanica.evidence.blob import BlobId
from exulanica.graph.payload import SceneGeneratedGeometryRow, SceneGenerationModelRow
from exulanica.reconstruction.generated import GENERATED_SCENE_KIND, GENERATED_SCENE_PROFILE
from exulanica.store.base import ContentAddressedStore

__all__ = ["generated_geometry_rows"]

_GENERATIONS: Final = """
select a.artifact_id, a.content_sha256, a.created_at
  from artifact_current a
 where a.workspace_id = %s
   and a.scene_id = %s
   and a.kind = %s
   and a.purged_at is null
   and not person_withdrawal_blocks_artifact(a.workspace_id, a.artifact_id)
 order by a.created_at, a.artifact_id
"""


def _invalid(artifact_id: uuid.UUID, reason: str) -> SceneGeneratedGeometryRow:
    """A generation whose receipt does not verify, reported rather than dropped.

    Dropping it would let a corrupt receipt look like an absence of generated content, and the one
    thing a viewer must always be able to trust is that the absence of a generated label means
    nothing was generated.
    """
    return SceneGeneratedGeometryRow(
        artifact_id=artifact_id,
        receipt_sha256=None,
        tier="generated",
        state="invalid",
        state_reason=reason,
        model=None,
        prompt_sha256=None,
        conditioning=[],
        world_read_bundle_sha256=None,
        container=None,
        content_sha256=None,
        byte_size=None,
        seam=None,
    )


def generated_geometry_rows(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    scene_id: uuid.UUID,
    store: ContentAddressedStore | None,
) -> list[SceneGeneratedGeometryRow]:
    """Every current generation for this scene, each carrying what produced it."""
    rows = connection.execute(_GENERATIONS, (workspace, scene_id, GENERATED_SCENE_KIND)).fetchall()
    if not rows:
        return []
    if store is None:
        return [
            _invalid(row["artifact_id"], "the receipt store is not available to this reader")
            for row in rows
        ]

    output: list[SceneGeneratedGeometryRow] = []
    for row in rows:
        digest = bytes(row["content_sha256"]).hex()
        try:
            payload = store.get(BlobId.from_hex(digest))
        except IntegrityError:
            # The store verifies its own keys, so a digest mismatch surfaces here rather than in
            # the check below. The check below stays for a store that does not.
            output.append(_invalid(row["artifact_id"], "the generation receipt bytes are corrupt"))
            continue
        except (BlobNotFoundError, ValueError):
            output.append(_invalid(row["artifact_id"], "the generation receipt bytes are absent"))
            continue
        if hashlib.sha256(payload).hexdigest() != digest:
            output.append(_invalid(row["artifact_id"], "the generation receipt bytes are corrupt"))
            continue
        try:
            output.append(_row(row["artifact_id"], digest, json.loads(payload)))
        except (ValueError, KeyError, TypeError) as error:
            output.append(
                _invalid(row["artifact_id"], f"the generation receipt is malformed: {error}")
            )
    return output


def _row(artifact_id: uuid.UUID, receipt_sha256: str, receipt: Any) -> SceneGeneratedGeometryRow:
    if not isinstance(receipt, dict) or receipt.get("profile") != GENERATED_SCENE_PROFILE:
        raise ValueError(f"a generation receipt must declare {GENERATED_SCENE_PROFILE}")
    if receipt.get("tier") != "generated":
        # The tier is in the bytes as well as in the artifact kind, and disagreement between them
        # is the shape a mislabelled generation would take. Refuse rather than pick a winner.
        raise ValueError("a generation receipt must declare the generated tier")
    # Re-canonicalising and re-hashing catches a receipt whose bytes hash correctly but whose JSON
    # is not the canonical form its producer claimed, which would make one artifact reachable
    # under two serialisations of the same content.
    if hashlib.sha256(canonical_json(receipt)).hexdigest() != receipt_sha256:
        raise ValueError("the receipt is not in the canonical form its digest was taken over")

    model = receipt["model"]
    conditioning = [
        {"role": str(item["role"]), "sha256": str(item["sha256"])}
        for item in receipt["conditioning"]
    ]
    bundle = next(
        (item["sha256"] for item in conditioning if item["role"] == "world-read-bundle"), None
    )
    if bundle is None:
        raise ValueError("a generation receipt must name the world-read bundle it read")
    return SceneGeneratedGeometryRow(
        artifact_id=artifact_id,
        receipt_sha256=receipt_sha256,
        tier="generated",
        state="available",
        state_reason=None,
        model=SceneGenerationModelRow(
            provider=str(model["provider"]),
            model_id=str(model["model_id"]),
            model_version=str(model["model_version"]),
        ),
        prompt_sha256=str(receipt["prompt_sha256"]),
        conditioning=conditioning,
        world_read_bundle_sha256=bundle,
        container=str(receipt["container"]),
        content_sha256=str(receipt["content_sha256"]),
        byte_size=int(receipt["byte_size"]),
        seam=str(receipt["seam"]),
    )
