"""A creator's style pack upload, built from a committed pack, for the admission and route tests.

The committed ``exulanica.cozy-town`` pack is re-labelled as a creator's own (``maker.cozy-barn``,
origin uploaded, their own work) and given a preview Pillow encodes, since the committed preview
carries an ICC profile an upload may not. Its pieces are the committed pieces, byte for byte, so
everything an upload's admission and check read is real product content.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from exulanica.world import style_packs
from exulanica.world.style_pack_admission import DECLARATION_PROFILE, RIGHTS_STATEMENT

__all__ = ["Upload", "jpeg", "png", "upload"]

ROOT = Path(__file__).resolve().parents[1]
COZY = ROOT / "assets/style-packs/packs/exulanica.cozy-town"


def jpeg(width: int = 64, height: int = 40) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (200, 160, 120)).save(buffer, "JPEG", quality=80)
    return buffer.getvalue()


def png(width: int = 64, height: int = 40) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (90, 140, 200)).save(buffer, "PNG")
    return buffer.getvalue()


@dataclass
class Upload:
    """An upload's three parts: a manifest (as a document), its files by path, and the rights."""

    manifest: dict[str, Any]
    files: dict[str, bytes]
    rights: dict[str, Any] = field(
        default_factory=lambda: {
            "basis": "own_work",
            "licence_id": None,
            "attribution": None,
            "source_reference": None,
            "statement": RIGHTS_STATEMENT,
        }
    )

    def relist(self) -> Upload:
        """List every file at its current bytes, in path order."""
        listed = {file["path"]: file for file in self.manifest["files"]}
        for path, data in self.files.items():
            entry = listed.setdefault(path, {"path": path, "media_type": "image/jpeg"})
            entry["bytes"] = len(data)
            entry["sha256"] = hashlib.sha256(data).hexdigest()
        self.manifest["files"] = [listed[path] for path in sorted(listed)]
        return self

    @property
    def manifest_bytes(self) -> bytes:
        return style_packs.canonical_json(self.manifest).encode("ascii")

    def declaration(self, **overrides: Any) -> dict[str, Any]:
        raw = self.manifest_bytes
        document = {
            "profile": DECLARATION_PROFILE,
            "manifest_sha256": hashlib.sha256(raw).hexdigest(),
            "byte_size": len(raw),
            "rights": dict(self.rights),
        }
        document.update(overrides)
        return document

    def declaration_bytes(self, **overrides: Any) -> bytes:
        return json.dumps(self.declaration(**overrides)).encode()


def upload(pack_id: str = "maker.cozy-barn", version: int = 1) -> Upload:
    """The committed cozy pack as a creator's own upload, with a Pillow JPEG preview."""
    manifest = copy.deepcopy(json.loads((COZY / "manifest.json").read_text("utf-8")))
    files = {file["path"]: (COZY / file["path"]).read_bytes() for file in manifest["files"]}
    files[manifest["preview"]] = jpeg()
    manifest.update(
        pack_id=pack_id,
        version=version,
        origin="uploaded",
        provenance={"kind": "uploaded"},
        licence={"id": style_packs.OWN_WORK, "attribution": None},
        authors=["A maker"],
    )
    return Upload(manifest, files).relist()
