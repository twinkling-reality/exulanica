"""A workspace's own bake: its name, its licence, the request the baker runs, and its receipt.

A person's recipe is baked by the same maker, sampling and container as a published set, and only
four things differ, all decided here and never by the baker:

- **The set id** is ``ws.`` and the recipe row's 32 hex digits, and the version is always 1,
  because a recipe row is immutable and so is its container. No published set id begins ``ws.``.
- **The title and summary** are derived mechanically from the maker and the recipe digest. They
  are not prose, and the person's own label for a recipe never reaches a container.
- **The licence** is :data:`WORKSPACE_LICENCE_ID`, whose text says the bytes are private to that
  workspace. Its digest is pinned here and the text is
  ``web/packages/loom-texture/licences/workspace-private.txt``. Every path that publishes or exports
  refuses it; :func:`refuse_private_licence` is the check those paths call.
- **The receipt** (:data:`WORKSPACE_BAKE_RECEIPT_PROFILE`) names the request, the maker manifest,
  the recipe, the licence, the bytes, the Node version that baked them and the digest of the
  package source, so a bake can be reproduced and its code named.

The request is an object with a profile, canonical like every object here, and the bake worker
(``exulanica/world/material_bakes.py``) writes it only after the recipe has passed
:func:`exulanica.materials.recipe_problems` against the published maker.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from exulanica.materials.objects import (
    BAKE_PIPELINE,
    SAFE_INTEGER,
    MaterialObjectError,
    canonical_bytes,
    is_sha256,
    read_object,
    sha256_hex,
    thaw,
)
from exulanica.materials.recipes import MAXIMUM_RESOLUTION

__all__ = [
    "BAKE_REQUEST_PROFILE",
    "BAKE_RESULT_PROFILE",
    "MAXIMUM_WORKSPACE_TEXELS",
    "WORKSPACE_BAKE_RECEIPT_PROFILE",
    "WORKSPACE_LICENCE_ID",
    "WORKSPACE_LICENCE_SHA256",
    "WORKSPACE_SET_ID",
    "WORKSPACE_VERSION",
    "BakeResult",
    "PrivateLicenceRefused",
    "bake_receipt",
    "bake_request",
    "read_bake_result",
    "refuse_private_licence",
    "workspace_set_id",
    "workspace_summary",
    "workspace_title",
]

WORKSPACE_LICENCE_ID: Final = "LicenseRef-Exulanica-Workspace-Private"
#: The sha256 of ``web/packages/loom-texture/licences/workspace-private.txt``. A changed text is a
#: changed licence, and ``tests/test_material_bakes.py`` fails until this moves with it.
WORKSPACE_LICENCE_SHA256: Final = "43420eded959a3b449ca0f5bdd27746c5393f504d51583ce0afc495be0aabf49"
WORKSPACE_VERSION: Final = 1
WORKSPACE_SET_ID: Final = re.compile(r"ws\.[0-9a-f]{32}")
BAKE_REQUEST_PROFILE: Final = "exulanica.texture-bake-request/v1"
BAKE_RESULT_PROFILE: Final = "exulanica.texture-bake-result/v1"
WORKSPACE_BAKE_RECEIPT_PROFILE: Final = "exulanica.workspace-texture-bake-receipt/v1"
#: The most texels a workspace bake holds: the recipe ceiling on both axes, as the baker states it.
MAXIMUM_WORKSPACE_TEXELS: Final = MAXIMUM_RESOLUTION * MAXIMUM_RESOLUTION

_RESULT_KEYS: Final = frozenset({"profile", "content_sha256", "byte_size", "runtime"})
_RUNTIME_KEYS: Final = frozenset({"node", "package_sha256"})
_NODE_VERSION: Final = re.compile(r"v[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}")


class PrivateLicenceRefused(MaterialObjectError):
    """Something tried to publish, export or package bytes that are private to a workspace."""


def refuse_private_licence(licence_id: object, where: str) -> None:
    """Raise when ``licence_id`` names a workspace's private bytes. Publishing paths call this."""
    if licence_id == WORKSPACE_LICENCE_ID:
        raise PrivateLicenceRefused(
            f"{where} is under {WORKSPACE_LICENCE_ID}: bytes baked for one workspace are never "
            "published, exported or packaged"
        )


def workspace_set_id(recipe_id: uuid.UUID) -> str:
    if not isinstance(recipe_id, uuid.UUID):
        raise TypeError(f"a workspace set id names a recipe row id, not {type(recipe_id).__name__}")
    return f"ws.{recipe_id.hex}"


def workspace_title(maker_id: str, maker_version: int) -> str:
    return f"Workspace variant of {maker_id} version {maker_version}"


def workspace_summary(recipe_sha256: str) -> str:
    if not is_sha256(recipe_sha256):
        raise MaterialObjectError("a workspace summary names a recipe by its sha256")
    return f"Baked in one workspace from recipe {recipe_sha256}."


def bake_request(
    *, recipe_id: uuid.UUID, recipe: Mapping[str, Any], maker_sha256: str
) -> dict[str, Any]:
    """The request for one recipe row. Its canonical bytes are what the baker reads."""
    if not is_sha256(maker_sha256):
        raise MaterialObjectError("a bake request names its maker manifest by sha256")
    document = thaw(recipe)
    maker = document.get("maker") if isinstance(document, dict) else None
    if not isinstance(maker, dict):
        raise MaterialObjectError("a bake request carries a recipe that names its maker")
    return {
        "profile": BAKE_REQUEST_PROFILE,
        "set_id": workspace_set_id(recipe_id),
        "version": WORKSPACE_VERSION,
        "title": workspace_title(maker["id"], maker["version"]),
        "summary": workspace_summary(sha256_hex(canonical_bytes(document))),
        "licence": {"id": WORKSPACE_LICENCE_ID, "sha256": WORKSPACE_LICENCE_SHA256},
        "maker_sha256": maker_sha256,
        "recipe": document,
    }


@dataclass(frozen=True, slots=True)
class BakeResult:
    """What the baker says it wrote. Checked against the bytes before anything believes it."""

    content_sha256: str
    byte_size: int
    node: str
    package_sha256: str


def read_bake_result(raw: bytes) -> BakeResult:
    """The baker's result line, read strictly and held to its shape, or a refusal."""
    document = read_object(raw, "bake result")
    if not isinstance(document, Mapping) or set(document) != _RESULT_KEYS:
        raise MaterialObjectError(f"a bake result has exactly {sorted(_RESULT_KEYS)}")
    runtime = document["runtime"]
    if (
        document["profile"] != BAKE_RESULT_PROFILE
        or not is_sha256(document["content_sha256"])
        or type(document["byte_size"]) is not int
        or not 1 <= document["byte_size"] <= SAFE_INTEGER
        or not isinstance(runtime, Mapping)
        or set(runtime) != _RUNTIME_KEYS
        or not isinstance(runtime["node"], str)
        or _NODE_VERSION.fullmatch(runtime["node"]) is None
        or not is_sha256(runtime["package_sha256"])
    ):
        raise MaterialObjectError(
            f"a bake result is {BAKE_RESULT_PROFILE} with a sha256, a positive size, a Node "
            "version and the package source digest"
        )
    return BakeResult(
        content_sha256=document["content_sha256"],
        byte_size=document["byte_size"],
        node=runtime["node"],
        package_sha256=runtime["package_sha256"],
    )


def bake_receipt(
    *,
    request: Mapping[str, Any],
    maker_sha256: str,
    recipe_sha256: str,
    result: BakeResult,
) -> dict[str, Any]:
    """The receipt a verified bake is recorded with. The caller checked every digest in it."""
    return {
        "profile": WORKSPACE_BAKE_RECEIPT_PROFILE,
        "pipeline": BAKE_PIPELINE,
        "set_id": request["set_id"],
        "version": request["version"],
        "request_sha256": sha256_hex(canonical_bytes(request)),
        "maker_sha256": maker_sha256,
        "recipe_sha256": recipe_sha256,
        "licence_id": WORKSPACE_LICENCE_ID,
        "licence_sha256": WORKSPACE_LICENCE_SHA256,
        "content_sha256": result.content_sha256,
        "byte_size": result.byte_size,
        "runtime": {"node": result.node, "package_sha256": result.package_sha256},
    }
