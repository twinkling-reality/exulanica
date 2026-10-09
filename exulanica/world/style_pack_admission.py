"""A creator's style pack, admitted: every check the upload request makes, in a fixed order.

``POST /workspace-style-packs`` reads its body after its caller is authenticated, holds the upload
permission and its workspace's share, and has counted the attempt; then :func:`admit` decides,
from the declaration, the manifest and the files, everything that needs no accessor data. What it
returns is recorded by ``WorkspaceStylePackRepository.record``
(:mod:`exulanica.world.workspace_style_packs`), and the pack check worker reads each piece's
colours later. ``docs/style-pack-contract.md`` section 11 is the contract.

The order, so one upload always answers the same first refusal:

1. The declaration (``exulanica.workspace-style-pack-admission/v1``): the manifest's digest and
   size, the rights (own work, or licensed under CC0 or CC-BY with its attribution), the source the
   creator names (text, never fetched), and the rights statement they affirm.
2. The manifest's bytes: at most 256 KiB, the declared digest and size, UTF-8 JSON with no
   duplicate key, no ``NaN`` or ``Infinity`` and bounded nesting, and exactly its canonical bytes.
3. The manifest, through the authoritative reader (``style_packs.read_manifest``), then what an
   uploaded pack must also be: origin ``uploaded``, an id outside ``exulanica.``, the licence the
   declaration states, and a base the workspace may draw on.
4. The parts: exactly the manifest's files by path, each its listed size and digest, a piece within
   its family's file size before it is opened.
5. Each piece's profile (:func:`exulanica.world.style_pack_pieces.check_piece_profile`) and its
   family's triangle and material budget, read from accessor counts.
6. The preview, walked to its end (:func:`exulanica.world.style_pack_preview.walk_preview`).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError

from exulanica.world import style_packs
from exulanica.world.style_pack_pieces import StylePieceRefused, check_piece_profile
from exulanica.world.style_pack_preview import PreviewRefused, walk_preview
from exulanica.world.workspace_style_packs import (
    GENERATED_PREFIX,
    AdmittedStylePack,
    PackBase,
    PackFile,
    WorkspaceStylePackError,
)

__all__ = [
    "ADMITTED_LICENCES",
    "DECLARATION_PROFILE",
    "MAX_DECLARATION_BYTES",
    "MAX_MANIFEST_BYTES",
    "RECEIPT_PROFILE",
    "RIGHTS_STATEMENT",
    "StylePackAdmissionRefused",
    "StylePackDeclaration",
    "admit",
    "parse_declaration",
]

DECLARATION_PROFILE: Final = "exulanica.workspace-style-pack-admission/v1"
RECEIPT_PROFILE: Final = "exulanica.workspace-style-pack-receipt/v1"
#: The fixed statement a creator affirms. Its words are the experience owner's to write.
RIGHTS_STATEMENT: Final = "exulanica.workspace-style-pack-rights-statement/v1"
#: The prefix a workspace's erasure gives the pack ids of the versions it erases, which the schema
#: reserves for them (``erased_ids_are_the_erasures``); no upload takes it.
ERASED_PREFIX: Final = "erased."
#: The licences a licensed upload may state; own work states the own-work id.
ADMITTED_LICENCES: Final = ("CC0-1.0", "CC-BY-4.0")
MAX_DECLARATION_BYTES: Final = 64 * 1024
#: About twenty times the largest committed manifest: room for 512 file entries.
MAX_MANIFEST_BYTES: Final = 256 * 1024
#: How deep a manifest may nest before it is refused rather than read.
_MAX_DEPTH: Final = 32

_Text = Annotated[str, Field(min_length=1, max_length=400)]


class StylePackAdmissionRefused(WorkspaceStylePackError):
    """An upload refused before anything was written: a code, and what the first fault was."""

    def __init__(self, code: str, detail: str, *, path: str | None = None) -> None:
        self.code = code
        self.detail = detail
        self.path = path
        super().__init__(detail if path is None else f"{path}: {detail}")


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class StylePackRights(_Body):
    basis: Literal["own_work", "licensed"]
    licence_id: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    attribution: _Text | None = None
    #: Where the creator says it came from. Provenance text: never fetched, never followed.
    source_reference: _Text | None = None
    statement: Literal["exulanica.workspace-style-pack-rights-statement/v1"]


class StylePackDeclaration(_Body):
    profile: Literal["exulanica.workspace-style-pack-admission/v1"]
    manifest_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    byte_size: Annotated[StrictInt, Field(ge=2, le=MAX_MANIFEST_BYTES)]
    rights: StylePackRights


def parse_declaration(raw: bytes) -> StylePackDeclaration:
    """The declaration, checked, or a refusal naming the first problem."""
    if not 0 < len(raw) <= MAX_DECLARATION_BYTES:
        raise StylePackAdmissionRefused(
            "invalid_declaration", f"a declaration is 1 to {MAX_DECLARATION_BYTES} bytes"
        )
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise StylePackAdmissionRefused(
            "invalid_declaration", "the declaration is not UTF-8 JSON"
        ) from None
    try:
        declaration = StylePackDeclaration.model_validate(value)
    except ValidationError as error:
        first = error.errors(include_url=False, include_input=False)[0]
        where = ".".join(str(part) for part in first["loc"]) or "declaration"
        raise StylePackAdmissionRefused("invalid_declaration", f"{where}: {first['msg']}") from None
    rights = declaration.rights
    for name, text in (
        ("attribution", rights.attribution),
        ("source_reference", rights.source_reference),
    ):
        if text is not None and not style_packs.is_plain_text(text, 400):
            raise StylePackAdmissionRefused(
                "invalid_declaration", f"rights.{name}: trimmed plain text"
            )
    if rights.basis == "own_work":
        if rights.licence_id is not None or rights.attribution is not None:
            raise StylePackAdmissionRefused(
                "invalid_declaration", "rights: own work names no licence and no attribution"
            )
    elif rights.licence_id not in ADMITTED_LICENCES:
        raise StylePackAdmissionRefused(
            "licence_not_admitted",
            f"a licensed pack is one of {', '.join(ADMITTED_LICENCES)}",
        )
    elif rights.licence_id == "CC-BY-4.0" and rights.attribution is None:
        raise StylePackAdmissionRefused(
            "attribution_required", "CC-BY-4.0 is admitted with the attribution it requires"
        )
    elif rights.licence_id == "CC0-1.0" and rights.attribution is not None:
        raise StylePackAdmissionRefused(
            "invalid_declaration", "rights.attribution: CC0-1.0 states none"
        )
    return declaration


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"the key {key!r} appears twice")
        out[key] = value
    return out


def _refuse_constant(name: str) -> Any:
    raise ValueError(f"{name} is not a number a manifest may hold")


def _depth(value: Any) -> int:
    deepest, pending = 0, [(value, 1)]
    while pending:
        item, depth = pending.pop()
        deepest = max(deepest, depth)
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
    return deepest


def _manifest_value(raw: bytes, declaration: StylePackDeclaration) -> Any:
    if len(raw) > MAX_MANIFEST_BYTES:
        raise StylePackAdmissionRefused(
            "invalid_style_data", f"a manifest is at most {MAX_MANIFEST_BYTES} bytes"
        )
    if len(raw) != declaration.byte_size or (
        hashlib.sha256(raw).hexdigest() != declaration.manifest_sha256
    ):
        raise StylePackAdmissionRefused(
            "content_digest_mismatch", "the manifest is not the bytes the declaration names"
        )
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_no_duplicates,
            parse_constant=_refuse_constant,
        )
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise StylePackAdmissionRefused(
            "invalid_style_data", f"the manifest is not UTF-8 JSON: {error}"
        ) from None
    if _depth(value) > _MAX_DEPTH:
        raise StylePackAdmissionRefused(
            "invalid_style_data", f"a manifest nests at most {_MAX_DEPTH} deep"
        )
    try:
        canonical = style_packs.canonical_json(value)
    except style_packs.StylePackRefused as refused:
        raise StylePackAdmissionRefused(
            "invalid_style_data", str(refused), path=refused.path
        ) from None
    if canonical.encode("ascii") != raw:
        raise StylePackAdmissionRefused(
            "invalid_style_data", "a manifest is sent as exactly its canonical JSON"
        )
    return value


#: What a base is asked: the base the manifest names, answered with where it is held
#: (``library`` or ``workspace``), or a refusal message when the workspace may not draw on it.
BaseResolver = Callable[[Mapping[str, Any]], str]


def admit(
    declaration_raw: bytes,
    manifest_raw: bytes,
    files: Mapping[str, bytes],
    *,
    context: style_packs.StylePackContext,
    budgets: Mapping[str, style_packs.PieceBudget],
    lod1_share_permille: int,
    resolve_base: BaseResolver,
) -> AdmittedStylePack:
    """Every check that needs no accessor data, in the order above, or the first refusal."""
    declaration = parse_declaration(declaration_raw)
    value = _manifest_value(manifest_raw, declaration)
    try:
        manifest = style_packs.read_manifest(value, context)
    except style_packs.StylePackRefused as refused:
        raise StylePackAdmissionRefused(
            "invalid_style_data", str(refused), path=refused.path
        ) from None
    if manifest["origin"] != "uploaded":
        raise StylePackAdmissionRefused(
            "invalid_style_data", "an uploaded pack's origin is uploaded", path="origin"
        )
    if manifest["pack_id"].startswith("exulanica."):
        raise StylePackAdmissionRefused(
            "invalid_style_data",
            "an uploaded pack's id is the creator's, never in the exulanica. namespace",
            path="pack_id",
        )
    if manifest["pack_id"].startswith(ERASED_PREFIX):
        raise StylePackAdmissionRefused(
            "invalid_style_data",
            f"an uploaded pack's id never begins {ERASED_PREFIX}, which a workspace's erasure "
            "gives the versions it erases",
            path="pack_id",
        )
    if manifest["pack_id"].startswith(GENERATED_PREFIX):
        raise StylePackAdmissionRefused(
            "invalid_style_data",
            f"an uploaded pack's id never begins {GENERATED_PREFIX}, which the looks made of "
            "generated pieces take",
            path="pack_id",
        )
    rights = declaration.rights
    stated = (
        (style_packs.OWN_WORK, None)
        if rights.basis == "own_work"
        else (rights.licence_id, rights.attribution)
    )
    if (manifest["licence"]["id"], manifest["licence"]["attribution"]) != stated:
        raise StylePackAdmissionRefused(
            "licence_mismatch",
            "the manifest's licence and attribution are the ones the declaration states",
            path="licence",
        )
    base = None
    if manifest["base"] is not None:
        named = manifest["base"]
        source = resolve_base(named)
        base = PackBase(source, named["pack_id"], named["version"], named["manifest_sha256"])

    listed = {file["path"]: file for file in manifest["files"]}
    if set(files) != set(listed):
        missing, unknown = sorted(set(listed) - set(files)), sorted(set(files) - set(listed))
        raise StylePackAdmissionRefused(
            "invalid_style_pack_body",
            "the body's files are exactly the manifest's paths"
            + (f"; missing {', '.join(missing)}" if missing else "")
            + (f"; not listed {', '.join(unknown)}" if unknown else ""),
        )
    pieces: dict[str, tuple[str, Mapping[str, Any], bool]] = {}
    for role, module in manifest["modules"].items():
        family = role.split(".", 1)[0]
        for variant in module["variants"]:
            pieces[variant["file"]] = (family, variant, False)
            if variant["lod1"] is not None:
                pieces[variant["lod1"]] = (family, variant, True)
    for path, file in listed.items():
        data = files[path]
        if len(data) != file["bytes"] or hashlib.sha256(data).hexdigest() != file["sha256"]:
            raise StylePackAdmissionRefused(
                "content_digest_mismatch",
                "a file is not the size and digest its manifest lists",
                path=path,
            )
        if path in pieces and len(data) > budgets[pieces[path][0]].glb_bytes:
            raise StylePackAdmissionRefused(
                "over_budget", "a piece is over its family's file size", path=path
            )
    measured: dict[str, int] = {}
    for path, (family, variant, lod1) in sorted(pieces.items()):
        try:
            profile = check_piece_profile(files[path])
        except StylePieceRefused as refused:
            raise StylePackAdmissionRefused(
                "style_pack_piece_refused", f"{refused.reason}: {refused}", path=path
            ) from None
        budget = budgets[family]
        limit = budget.triangle_limit(variant["size_mm"][0])
        if lod1:
            first = measured.get(variant["file"])
            if first is None:
                first = check_piece_profile(files[variant["file"]]).triangles
            limit = first * lod1_share_permille // 1000
        if profile.triangles > limit or profile.materials > budget.materials:
            raise StylePackAdmissionRefused(
                "over_budget",
                f"{profile.triangles} triangles and {profile.materials} materials, over "
                f"{limit} and {budget.materials}",
                path=path,
            )
        measured[path] = profile.triangles
    preview = manifest.get("preview")
    preview_sha256 = None
    preview_size = None
    if preview is not None:
        try:
            size = walk_preview(files[preview], listed[preview]["media_type"])
        except PreviewRefused as refused:
            raise StylePackAdmissionRefused(
                "style_pack_preview_refused", f"{refused.reason}: {refused}", path=preview
            ) from None
        preview_sha256 = listed[preview]["sha256"]
        preview_size = [size.width_px, size.height_px]
    ordered = tuple(
        PackFile(file["path"], file["sha256"], file["bytes"], file["media_type"])
        for file in manifest["files"]
    )
    declaration_canonical = json.dumps(
        declaration.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode()
    return AdmittedStylePack(
        manifest_canonical=manifest_raw,
        pack_id=manifest["pack_id"],
        version=manifest["version"],
        declaration_canonical=declaration_canonical,
        rights_basis=rights.basis,
        licence_id=manifest["licence"]["id"],
        base=base,
        files=ordered,
        contents={file["sha256"]: files[file["path"]] for file in manifest["files"]},
        preview_sha256=preview_sha256,
        attribution=rights.attribution if rights.basis == "licensed" else None,
        receipt={
            "profile": RECEIPT_PROFILE,
            "reader": style_packs.PROFILE,
            "checks": [
                "declaration",
                "manifest_bytes",
                "manifest",
                "uploaded_rules",
                "base",
                "parts",
                "piece_profiles",
                "piece_budgets",
                "preview",
            ],
            "piece_triangles": {path: measured[path] for path in sorted(pieces)},
            "preview_px": preview_size,
        },
    )
