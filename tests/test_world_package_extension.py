"""The authored-world extension to WMP 1.0, and the compatibility it must not cost.

The fixture ``tests/fixtures/wmp-1.0-before-authored-world`` was written by the unmodified
projector at 90edb49, before any extension code existed, and signed with a key derived from a
fixed test string. It is a real 1.0 package from before this change, not a reconstruction of
one, and ``wmp-1.0-before-authored-world.expected.json`` holds what that commit's verifier said
about it. Nothing in this file may edit either.

Ed25519 signatures are deterministic, so the same key over the same manifest reproduces the
signature byte for byte. That is what lets the writer test below prove the projector's 1.0 path
is unchanged: rebuilt from the fixture's own components, every file comes back identical.
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from exulanica.world.assets import reviewed_assets
from exulanica.world.objects import (
    AuthoredObject,
    ObjectBehaviour,
    ObjectOrigin,
    Transform,
    canonical_delta_document,
)
from exulanica.world.objects import delta_sha256 as product_delta_sha256
from exulanica.world_package import authored
from exulanica.world_package.cli import main
from exulanica.world_package.diff import diff_packages
from exulanica.world_package.package import (
    MANIFEST_PATH,
    PROFILE_VERSION,
    SIGNATURE_PATH,
    PackageError,
    build_manifest,
    canonical_file,
    import_check_package,
    inspect_package,
    sign_manifest,
    verify_package,
)
from exulanica.world_package.projector import _crate_files

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
GOLDEN = _FIXTURES / "wmp-1.0-before-authored-world"
GOLDEN_EXPECTED = json.loads(
    (_FIXTURES / "wmp-1.0-before-authored-world.expected.json").read_text(encoding="utf-8")
)
#: The fixture's signing key. Test material derived from a public string, never a trust root.
GOLDEN_KEY = Ed25519PrivateKey.from_private_bytes(
    hashlib.sha256(b"exulanica-wmp-1.0 golden fixture test key; not a trust root").digest()
)
BASE_LOADER = frozenset(
    {"style-profile:origin-landscape@1"}
    | {
        f"interaction:{key}"
        for key in GOLDEN_EXPECTED["import_check_undeclared"]["required_interaction_capabilities"]
    }
)
EXTENSION_LOADER = BASE_LOADER | {
    authored.EXTENSION_CAPABILITY,
    authored.ASSET_RESOLUTION_CAPABILITY,
    "asset-media:model/gltf-binary",
    "behaviour:motion.bounded-path@1",
}
CUBE = next(asset for asset in reviewed_assets() if asset.asset_key == "cc0.marker-cube")
MOTION = {
    "behaviour_key": "motion.bounded-path",
    "behaviour_version": 1,
    "parameters": {
        "axis": {"choices": ["x", "y", "z"], "default": "x", "kind": "choice"},
        "easing": {"choices": ["linear", "smooth"], "default": "smooth", "kind": "choice"},
        "period_milliseconds": {
            "default": 4000,
            "kind": "integer",
            "maximum": 60000,
            "minimum": 500,
        },
        "travel_mm": {"default": 1000, "kind": "integer", "maximum": 10000, "minimum": 100},
    },
    "summary": "Bounded reversing travel along one axis, with renderer trigger, stop and reset "
    "controls.",
}
_NOT_1_0_PAYLOADS = {"ro-crate-metadata.json", "wmp/profile.json", MANIFEST_PATH, SIGNATURE_PATH}


def _golden_copy(tmp_path: Path) -> Path:
    destination = tmp_path / "golden"
    shutil.copytree(GOLDEN, destination)
    return destination


def _golden_components() -> dict[str, Any]:
    """The component documents the projector handed ``_crate_files`` when it wrote the fixture."""
    return {
        str(path.relative_to(GOLDEN)): json.loads(path.read_bytes())
        for path in sorted(GOLDEN.rglob("*.json"))
        if str(path.relative_to(GOLDEN)) not in _NOT_1_0_PAYLOADS
    }


def _urn(kind: str, value: str) -> str:
    return f"urn:exulanica:wmp:{kind}:{hashlib.sha256(f'{kind}:{value}'.encode()).hexdigest()}"


def _sections(*, behaviour: bool = True, removed: bool = False) -> dict[str, Any]:
    """One alternate version of the fixture's current snapshot: one object, added then moved."""
    structure = json.loads((GOLDEN / "world/structure.json").read_bytes())
    topology = json.loads((GOLDEN / "world/topology.json").read_bytes())
    placed = AuthoredObject(
        object_id="object:lantern",
        asset_sha256=CUBE.content_sha256,
        region_id="region-a",
        transform=Transform(1_200, 0, -450, 785_398, 1_000),
        origin=ObjectOrigin("authored", "fictional"),
        behaviour=(
            ObjectBehaviour(
                "motion.bounded-path",
                1,
                {"axis": "x", "easing": "smooth", "period_milliseconds": 4000, "travel_mm": 2000},
            )
            if behaviour
            else None
        ),
    )
    moved = replace(placed, transform=Transform(2_400, 0, -450, 785_398, 1_000))
    final = replace(moved, removed=removed)
    added_state = product_delta_sha256([placed], [])
    moved_state = product_delta_sha256([moved], [])
    edits = [
        _edit(1, "add_object", authored.EMPTY_DELTA_SHA256, added_state),
        _edit(2, "move_object", added_state, moved_state),
    ]
    if removed:
        edits.append(_edit(3, "remove_object", moved_state, product_delta_sha256([final], [])))
    version = {
        "created_at": "2026-09-11T10:00:00Z",
        "delta": canonical_delta_document([final], []),
        "edit_seq": len(edits),
        "edits": edits,
        "origin": "authored",
        "parent_version_id": None,
        "source_snapshot_id": structure["lineage"]["snapshot_id"],
        "state_sha256": product_delta_sha256([final], []),
        "style_version_id": None,
        "title": "Evening study",
        "version_id": _urn("alternate-version", "one"),
    }
    return authored.build_sections(
        versions=[version],
        source_snapshots=[
            {
                "current": True,
                "element_ids": sorted(e["element_id"] for e in topology["elements"]),
                "region_ids": sorted(r["region_id"] for r in topology["regions"]),
                "snapshot_id": structure["lineage"]["snapshot_id"],
                "snapshot_sha256": structure["digests"]["snapshot_sha256"],
            }
        ],
        assets=[
            {
                "asset_key": CUBE.asset_key,
                "byte_size": CUBE.byte_size,
                "content_sha256": CUBE.content_sha256,
                "licence_id": CUBE.licence_id,
                "licence_sha256": CUBE.licence_sha256,
                "media_type": CUBE.media_type,
                "ni_uri": authored.ni_uri(CUBE.content_sha256),
                "retrieval": authored.ASSET_RETRIEVAL,
                "summary": CUBE.summary,
                "title": CUBE.title,
            }
        ],
        behaviours=[MOTION] if behaviour else [],
        withheld_versions=0,
    )


def _edit(seq: int, kind: str, base: str, result: str) -> dict[str, Any]:
    return {
        "base_state_sha256": base,
        "edit_id": _urn("alternate-edit", str(seq)),
        "edit_seq": seq,
        "element_id": None,
        "kind": kind,
        "object_id": "object:lantern",
        "recorded_at": f"2026-09-11T10:0{seq}:00Z",
        "result_state_sha256": result,
        "undone_edit_id": None,
    }


def _write_signed(
    root: Path, components: dict[str, Any], *, extra_files: dict[str, bytes] | None = None
) -> Path:
    files = _crate_files(components)
    files.update(extra_files or {})
    manifest = canonical_file(build_manifest(files))
    files[MANIFEST_PATH] = manifest
    files[SIGNATURE_PATH] = canonical_file(sign_manifest(manifest, GOLDEN_KEY))
    for path, data in files.items():
        destination = root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    return root


def _extended(
    root: Path,
    *,
    mutate: Callable[[dict[str, Any]], None] | None = None,
    extra_files: dict[str, bytes] | None = None,
    **options: bool,
) -> Path:
    """The fixture plus the extension, re-signed. ``mutate`` edits a section before signing,
    so a refusal it provokes is the extension's rule and never a broken signature."""
    components = _golden_components()
    components.update(copy.deepcopy(_sections(**options)))
    if mutate is not None:
        mutate(components)
    return _write_signed(root, components, extra_files=extra_files)


# -- compatibility --------------------------------------------------------------------------


def test_a_1_0_package_written_before_the_extension_still_verifies_unchanged(tmp_path: Path):
    package = _golden_copy(tmp_path)
    before = {path: path.read_bytes() for path in sorted(package.rglob("*")) if path.is_file()}
    report = verify_package(package).as_dict()
    for key, value in GOLDEN_EXPECTED["verify"].items():
        assert report[key] == value, key
    assert report["profile_version"] == PROFILE_VERSION
    assert report["extensions"] == [] and report["uninterpreted_paths"] == []
    after = {path: path.read_bytes() for path in sorted(package.rglob("*")) if path.is_file()}
    assert after == before, "verification must not touch the package it verifies"


def test_the_pre_extension_inspect_and_import_check_answers_are_preserved(tmp_path: Path):
    package = _golden_copy(tmp_path)
    inspected = inspect_package(package)
    for key, value in GOLDEN_EXPECTED["inspect"].items():
        assert inspected[key] == value, key
    for name, declared in (
        ("import_check_undeclared", {}),
        (
            "import_check_declared",
            {
                "supported_style_profiles": frozenset({"origin-landscape@1"}),
                "supported_interaction_capabilities": frozenset({"comfort.vignette@1"}),
            },
        ),
    ):
        checked = import_check_package(package, **declared)
        for key, value in GOLDEN_EXPECTED[name].items():
            assert checked[key] == value, (name, key)
        assert checked["extensions"] == []


def test_the_1_0_writer_reproduces_the_pre_extension_package_byte_for_byte(tmp_path: Path):
    """Catches any change to the 1.0 write path: crate layout, canonical form, manifest or
    signature payload. Rebuilt from its own components with its own key, the fixture comes back
    identical in every file, including the signature."""
    rebuilt = _write_signed(tmp_path / "rebuilt", _golden_components())
    expected = {
        str(path.relative_to(GOLDEN)): path.read_bytes()
        for path in GOLDEN.rglob("*")
        if path.is_file()
    }
    actual = {
        str(path.relative_to(rebuilt)): path.read_bytes()
        for path in rebuilt.rglob("*")
        if path.is_file()
    }
    assert actual == expected


def test_the_extension_leaves_every_1_0_payload_byte_identical_but_the_crate(tmp_path: Path):
    package = _extended(tmp_path / "extended")
    for path in GOLDEN.rglob("*.json"):
        relative = str(path.relative_to(GOLDEN))
        if relative in {"ro-crate-metadata.json", MANIFEST_PATH, SIGNATURE_PATH}:
            continue
        assert (package / relative).read_bytes() == path.read_bytes(), relative
    crate = json.loads((package / "ro-crate-metadata.json").read_bytes())
    nodes = {node["@id"]: node for node in crate["@graph"]}
    # A 1.0 verifier requires the root to conform to exactly the 1.0 profile.
    assert nodes["./"]["conformsTo"] == {
        "@id": "https://exulanica.local/profiles/world-memory-package/1.0"
    }
    assert nodes[authored.DECLARATION_PATH]["conformsTo"] == {"@id": authored.EXTENSION_PROFILE_ID}
    assert "Profile" in nodes[authored.EXTENSION_PROFILE_ID]["@type"]
    assert {path for path in authored.EXTENSION_PATHS} <= {
        part["@id"] for part in nodes["./"]["hasPart"]
    }
    changed = diff_packages(GOLDEN, package)
    assert changed.added_files == tuple(sorted(authored.EXTENSION_PATHS))
    assert changed.changed_files == ("ro-crate-metadata.json",)
    assert changed.removed_files == ()


def test_a_verifier_that_knows_no_extension_still_verifies_an_extended_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The 1.0 path an older verifier takes: inventory, bytes, scan, profile and signature.

    With the extension rules switched off the package still verifies, which is the property
    that makes this an extension rather than a break. The evaluation record additionally runs
    the verifier from the commit before this change over a package projected from the copy.
    """
    from exulanica.world_package import package as package_module

    extended = _extended(tmp_path / "extended")
    monkeypatch.setattr(package_module, "_verify_extensions", lambda files, paths: ())
    report = verify_package(extended)
    assert report.profile_version == PROFILE_VERSION
    assert report.file_count == 18 + len(authored.EXTENSION_PATHS)


# -- verification ---------------------------------------------------------------------------


def test_verify_checks_the_extension_and_says_it_did_not_assess_loading(tmp_path: Path):
    report = verify_package(_extended(tmp_path / "extended")).as_dict()
    assert report["verified"] is True
    [extension] = report["extensions"]
    assert extension["extension"] == authored.EXTENSION_NAME
    assert extension["extension_version"] == "1.0"
    assert extension["rules"] == "checked by this verifier"
    assert extension["required_loader_capabilities"] == sorted(EXTENSION_LOADER - BASE_LOADER)
    assert report["runtime_loadability"].startswith("not assessed")
    assert "Runtime loadability was not assessed." in report["summary"]
    assert "does not prove the signer was authorized" in report["summary"]
    assert authored.EXTENSION_NAME in report["summary"]


def test_verify_output_text_separates_verification_from_loadability(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    package = _extended(tmp_path / "extended")
    assert main(["verify", str(package)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["verified"] is True
    assert printed["runtime_loadability"].startswith("not assessed: verify never loads a world")


def test_the_exported_digest_rederives_without_the_product_code(tmp_path: Path):
    """The verifier's digest uses only the canonical JSON rule; the product's uses domain types.
    They must agree, or a package the product wrote would fail an independent verifier."""
    sections = _sections()
    [version] = sections[authored.VERSIONS_PATH]["items"]
    assert authored.delta_sha256(version["delta"]) == version["state_sha256"]
    assert authored.delta_sha256(authored.EMPTY_DELTA) == product_delta_sha256([], [])


def test_asset_bytes_are_not_embedded_and_references_overstate_nothing(tmp_path: Path):
    package = _extended(tmp_path / "extended")
    extension_files = sorted(
        str(path.relative_to(package)) for path in (package / authored.EXTENSION_DIR).rglob("*")
    )
    assert extension_files == sorted(authored.EXTENSION_PATHS)
    [asset] = json.loads((package / authored.ASSETS_PATH).read_bytes())["items"]
    assert "url" not in asset
    assert asset["retrieval"] == "requires an authorized content-addressed resolver"
    assert asset["ni_uri"].startswith("ni:///sha-256;")
    declaration = json.loads((package / authored.DECLARATION_PATH).read_bytes())
    assert declaration["asset_bytes"].startswith("not embedded")
    assert declaration["runtime_code"].startswith("not carried")


def _set(path: str, *keys: Any, value: Any) -> Callable[[dict[str, Any]], None]:
    def mutate(components: dict[str, Any]) -> None:
        node = components[path]
        for key in keys[:-1]:
            node = node[key]
        node[keys[-1]] = value

    return mutate


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            _set(
                authored.VERSIONS_PATH,
                "items",
                0,
                "delta",
                "objects",
                0,
                "transform",
                "x_mm",
                value=9_999,
            ),
            "does not re-derive",
        ),
        (
            _set(
                authored.VERSIONS_PATH,
                "items",
                0,
                "delta",
                "objects",
                0,
                "region_id",
                value="region-z",
            ),
            "region its source snapshot does not have",
        ),
        (
            _set(
                authored.VERSIONS_PATH,
                "items",
                0,
                "delta",
                "objects",
                0,
                "behaviour",
                "parameters",
                "travel_mm",
                value=50_000,
            ),
            "outside its reviewed bound",
        ),
        (
            _set(
                authored.VERSIONS_PATH,
                "items",
                0,
                "delta",
                "objects",
                0,
                "origin",
                "kind",
                value="captured",
            ),
            "origin must be authored",
        ),
        (
            _set(
                authored.VERSIONS_PATH, "items", 0, "edits", 1, "base_state_sha256", value="0" * 64
            ),
            "not made against the state before it",
        ),
        (
            _set(
                authored.DECLARATION_PATH,
                "required_loader_capabilities",
                value=[authored.EXTENSION_CAPABILITY],
            ),
            "does not match the sections it declares",
        ),
        (
            _set(authored.VERSIONS_PATH, "source_snapshots", 0, "snapshot_sha256", value="0" * 64),
            "disagrees with world/structure.json",
        ),
        (
            _set(authored.ASSETS_PATH, "items", 0, "ni_uri", value="https://example.org/cube"),
            "is malformed",
        ),
    ],
)
def test_a_signed_but_inconsistent_extension_is_refused(
    tmp_path: Path, mutate: Callable[[dict[str, Any]], None], message: str
):
    package = _extended(tmp_path / "extended", mutate=mutate)
    with pytest.raises(PackageError, match=message):
        verify_package(package)


def test_the_unmutated_control_for_the_refusals_above_verifies(tmp_path: Path):
    """Negative control: every refusal above is the rule it names, not a broken builder."""
    assert verify_package(_extended(tmp_path / "extended")).extensions[0].rules_checked


def test_an_embedded_asset_cannot_ride_along_inside_the_extension(tmp_path: Path):
    package = _extended(
        tmp_path / "extended",
        extra_files={f"{authored.EXTENSION_DIR}/{CUBE.content_sha256}.glb": CUBE.payload},
    )
    with pytest.raises(PackageError, match="must hold exactly"):
        verify_package(package)


def test_an_extension_directory_without_a_declaration_is_refused(tmp_path: Path):
    def mutate(components: dict[str, Any]) -> None:
        components["extensions/somebody-else-1.0/data.json"] = {"items": []}

    with pytest.raises(PackageError, match=r"no valid extension\.json"):
        verify_package(_extended(tmp_path / "extended", mutate=mutate))


def test_an_unknown_extension_verifies_and_is_named_as_unchecked_and_unsupported(tmp_path: Path):
    def mutate(components: dict[str, Any]) -> None:
        components["extensions/weather-2.0/extension.json"] = {
            "base_profile": PROFILE_VERSION,
            "extension": "example-weather",
            "extension_version": "2.0",
            "required_loader_capabilities": ["weather:rain@1"],
        }

    package = _extended(tmp_path / "extended", mutate=mutate)
    report = verify_package(package).as_dict()
    unknown = next(e for e in report["extensions"] if e["extension"] == "example-weather")
    assert unknown["rules"].startswith("not known to this verifier")
    assert "Not checked by this verifier: example-weather@2.0." in report["summary"]
    checked = import_check_package(package, loader_capabilities=EXTENSION_LOADER)
    assert checked["loadability"] == "partial"
    assert set(checked["unsupported_capabilities"]) == {
        "weather:rain@1",
        "wmp-extension:example-weather@2.0",
    }


# -- loaders --------------------------------------------------------------------------------


def test_a_loader_with_no_extension_support_loads_the_base_and_names_what_it_leaves(
    tmp_path: Path,
):
    package = _extended(tmp_path / "extended")
    checked = import_check_package(package, loader_capabilities=BASE_LOADER)
    assert checked["compatible"] is True, "the 1.0 base is still fully loadable"
    assert checked["loadability"] == "partial"
    assert checked["mutated"] is False
    [extension] = checked["extensions"]
    assert extension["load"] == "not loaded"
    assert authored.EXTENSION_CAPABILITY in extension["unsupported_capabilities"]
    assert "1 alternate version(s) and 1 present authored object(s)" in extension["not_loaded"]
    assert extension["not_loaded"] in checked["warnings"]
    assert set(checked["unsupported_capabilities"]) == EXTENSION_LOADER - BASE_LOADER
    assert checked["declared_loader_capabilities"] == sorted(BASE_LOADER)


def test_a_loader_with_extension_support_loads_everything(tmp_path: Path):
    package = _extended(tmp_path / "extended")
    checked = import_check_package(package, loader_capabilities=EXTENSION_LOADER)
    assert checked["loadability"] == "complete"
    assert checked["unsupported_capabilities"] == []
    [extension] = checked["extensions"]
    assert extension["load"] == "loaded"
    assert extension["objects_not_drawable"] == []
    assert extension["objects_with_unsupported_behaviour"] == []


def test_a_loader_without_the_behaviour_shows_it_as_unsupported_rather_than_dropping_it(
    tmp_path: Path,
):
    package = _extended(tmp_path / "extended")
    checked = import_check_package(
        package, loader_capabilities=EXTENSION_LOADER - {"behaviour:motion.bounded-path@1"}
    )
    assert checked["loadability"] == "partial"
    [extension] = checked["extensions"]
    assert extension["load"] == "loaded with unsupported parts named"
    assert extension["objects_with_unsupported_behaviour"] == [
        {
            "behaviour": "behaviour:motion.bounded-path@1",
            "object_id": "object:lantern",
            "shown_as": "present, with its behaviour marked unsupported",
            "version_id": _urn("alternate-version", "one"),
        }
    ]


def test_a_removed_object_requires_nothing_of_a_loader(tmp_path: Path):
    package = _extended(tmp_path / "extended", removed=True)
    declaration = json.loads((package / authored.DECLARATION_PATH).read_bytes())
    assert declaration["required_loader_capabilities"] == [authored.EXTENSION_CAPABILITY]
    assert declaration["counts"]["authored_objects_present"] == 0
    checked = import_check_package(
        package, loader_capabilities=BASE_LOADER | {authored.EXTENSION_CAPABILITY}
    )
    assert checked["loadability"] == "complete"


def test_undeclared_loader_capabilities_stay_indeterminate(tmp_path: Path):
    checked = import_check_package(_extended(tmp_path / "extended"))
    assert checked["loadability"] == "indeterminate"
    assert checked["compatible"] is None
    assert checked["unsupported_capabilities"] == []
    [extension] = checked["extensions"]
    assert extension["load"].startswith("indeterminate")
    assert extension["unsupported_capabilities"] == []


def test_import_check_cli_reports_unsupported_capabilities(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    package = _extended(tmp_path / "extended")
    arguments = ["import-check", str(package)]
    for capability in sorted(BASE_LOADER):
        arguments += ["--loader-capability", capability]
    assert main(arguments) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["loadability"] == "partial"
    assert authored.EXTENSION_CAPABILITY in printed["unsupported_capabilities"]
