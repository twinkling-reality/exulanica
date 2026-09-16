"""Bytes baked for one workspace never leave it: every path that publishes refuses their licence.

A workspace bake is under ``LicenseRef-Exulanica-Workspace-Private``. The paths that could carry
content outside the workspace are refused here one by one, each with the check it actually runs;
the ones that need a database (the judge seed, the reviewed asset registry) are in
``tests/test_material_recipes.py``, the loom-texture publisher, library and dataset plan in
``web/packages/loom-texture/test/workspace.test.ts``, and the bake route's private, uncached
answer in ``tests/test_material_routes.py``.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from exulanica.grammar.catalogs import Licence
from exulanica.grammar.errors import CatalogError
from exulanica.materials import MaterialObjectError, read_texture_manifest
from exulanica.materials.workspace import (
    WORKSPACE_LICENCE_ID,
    WORKSPACE_LICENCE_SHA256,
    PrivateLicenceRefused,
    refuse_private_licence,
)
from exulanica.world.texture_assets import TEXTURE_DIRECTORY
from exulanica.world_package.package import ProhibitedContentError, scan_payload

ROOT = Path(__file__).resolve().parents[1]
LICENCE_TEXT = ROOT / "web" / "packages" / "loom-texture" / "licences" / "workspace-private.txt"


def test_the_pinned_digest_is_the_committed_text():
    raw = LICENCE_TEXT.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == WORKSPACE_LICENCE_SHA256
    assert raw.endswith(b"\n") and b"\r" not in raw
    assert raw.isascii()
    attributes = (LICENCE_TEXT.parent / ".gitattributes").read_text(encoding="ascii")
    assert "* -text -ident -filter -working-tree-encoding" in attributes


def test_the_check_every_path_calls_refuses_only_the_private_licence():
    with pytest.raises(PrivateLicenceRefused, match="never published"):
        refuse_private_licence(WORKSPACE_LICENCE_ID, "a set")
    for other in ("CC0-1.0", "Apache-2.0", "LicenseRef-Something-Else", None, 1):
        refuse_private_licence(other, "a set")


def test_the_published_manifest_refuses_it():
    raw = (TEXTURE_DIRECTORY / "manifest.json").read_bytes()
    forged = raw.replace(
        b'"licence_id":"CC0-1.0"', f'"licence_id":"{WORKSPACE_LICENCE_ID}"'.encode(), 1
    )
    assert forged != raw
    with pytest.raises(MaterialObjectError, match="published sets only"):
        read_texture_manifest(forged)


def test_a_grammar_catalog_refuses_it_even_with_a_shipping_verdict():
    entry = {
        "spdx": WORKSPACE_LICENCE_ID,
        "verdict": "SHIP",
        "origin": "derived",
        "licence_source": "workspace",
        "content_source": "a workspace bake",
    }
    with pytest.raises(CatalogError, match="never"):
        Licence.read("material.v1.json entries[0].licence", entry)
    entry["spdx"] = "LicenseRef-Some-Other-Shipping-Licence"
    Licence.read("material.v1.json entries[0].licence", entry)


@pytest.mark.parametrize(
    "value",
    [
        {"licence_id": WORKSPACE_LICENCE_ID},
        {"assets": [{"licence": {"id": WORKSPACE_LICENCE_ID, "sha256": WORKSPACE_LICENCE_SHA256}}]},
        [WORKSPACE_LICENCE_ID],
    ],
)
def test_a_world_memory_package_refuses_it_anywhere_in_a_payload(value):
    with pytest.raises(ProhibitedContentError, match="stay in their workspace"):
        scan_payload("world/structure.json", value)


def test_a_world_memory_package_refuses_a_texture_container_outright():
    with pytest.raises(ProhibitedContentError, match="suffix"):
        scan_payload("extensions/materials/ws.bake.ltex", None)
    scan_payload("world/structure.json", {"licence_id": "CC0-1.0", "license": "Apache-2.0"})
