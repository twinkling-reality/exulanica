"""The baked texture sets, checked from the bytes on disk up.

``web/packages/loom-texture`` bakes the sets and its own suite proves the committed files are what
the source produces. This file is the backend's half, and it trusts nothing it did not recompute:
every digest is taken again from the bytes, every header is re-serialised through
:func:`exulanica.canonical.canonical_json`, which refuses a float outright, and every channel of
every map is measured across both of its wrap edges. The resolver is held to its two failure modes
and to never producing anything but the catalog's own entry.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import re
import shutil
import textwrap
from dataclasses import dataclass
from pathlib import Path

import pytest
from exulanica.canonical import canonical_json
from exulanica.errors import CanonicalisationError
from exulanica.materials.classes import RELIEF_CLASSES, TEXTURE_SET_PROFILE_V1, class_layout
from exulanica.store.local import LocalContentAddressedStore
from exulanica.world import texture_assets
from exulanica.world.texture_assets import (
    TEXTURE_DIRECTORY,
    MissingTextureSet,
    TextureCatalogError,
    TextureSetUnresolved,
    UnpinnedTextureSet,
    decode_texture_set,
    load_texture_catalog,
    resolve_texture_set,
    seed_texture_sets,
)
from PIL import Image, ImageChops, ImageStat

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = TEXTURE_DIRECTORY / "manifest.json"
DOC = ROOT / "docs" / "texture-package.md"
#: The entries the bake reads, which carry each set's title. The manifest does not.
LIBRARY = ROOT / "web" / "packages" / "loom-texture" / "library"
EVIDENCE_DIRECTORY = ROOT / "web" / "packages" / "loom-texture" / "evidence"
#: The published library's bake on five runtimes, at the commit that published batch 3: every file
#: the directory holds, sets, objects and indexes included. The earlier records are of the library
#: before their own batches and are kept as history, not held to the committed files.
EVIDENCE = EVIDENCE_DIRECTORY / "2026-09-17-determinism-batch3.log.txt"
OBJECT_EVIDENCE = EVIDENCE
HISTORY = (
    EVIDENCE_DIRECTORY / "2026-09-16-determinism.log.txt",
    EVIDENCE_DIRECTORY / "2026-09-16-determinism-objects.log.txt",
    EVIDENCE_DIRECTORY / "2026-09-17-determinism-batch1.log.txt",
)
#: A workspace bake of every published recipe, through the command the bake worker runs.
WORKSPACE_EVIDENCE = EVIDENCE_DIRECTORY / "2026-09-16-workspace-bake-determinism.log.txt"
WORKSPACE_RUNS = ("node24-arm64", "node26-arm64", "node20-x86_64-rosetta")
RUNS = (
    "node24-arm64-a",
    "node24-arm64-b",
    "node26-arm64",
    "node20-arm64",
    "node20-x86_64-rosetta",
)

#: The Melbourne street measurement: rejected on looks, passing every mechanical budget, with
#: 168 MB of decoded texture. Read as 168,000,000 bytes, the smaller reading of "168 MB".
ACCEPTED_DECODED_ENVELOPE_BYTES = 168_000_000
CORRIDOR_SET_COUNT = 6


@pytest.fixture(scope="module")
def catalog():
    return load_texture_catalog()


@pytest.fixture(scope="module")
def manifest():
    return json.loads(MANIFEST.read_bytes())


def _payloads(manifest):
    for entry in manifest["sets"]:
        path = TEXTURE_DIRECTORY / "blobs" / f"{entry['content_sha256']}.ltex"
        yield entry, path.read_bytes()


# -- the manifest ------------------------------------------------------------------------------


def test_the_manifest_is_canonical_json_in_the_agreed_shape(manifest):
    assert MANIFEST.read_bytes() == canonical_json(manifest)
    assert set(manifest) == {"profile", "sets"}
    assert manifest["profile"] == "exulanica.texture-manifest/v2"
    ids = [entry["set_id"] for entry in manifest["sets"]]
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)
    assert len(ids) >= 6
    for entry in manifest["sets"]:
        assert set(entry) == {
            "set_id",
            "version",
            "content_sha256",
            "byte_size",
            "resolution",
            "channels",
            "extent_mm",
            "licence_id",
            "licence_sha256",
            "container_profile",
            "material_class",
        }
        assert re.fullmatch(texture_assets.TEXTURE_SET_ID_PATTERN, entry["set_id"])
        # A stable name: never a version, never a digest.
        assert not re.search(r"v\d|[0-9a-f]{16}", entry["set_id"]), entry["set_id"]
        assert type(entry["version"]) is int and entry["version"] >= 1


def test_every_digest_is_recomputed_from_the_bytes_on_disk(manifest):
    for entry, payload in _payloads(manifest):
        assert hashlib.sha256(payload).hexdigest() == entry["content_sha256"], entry["set_id"]
        assert len(payload) == entry["byte_size"], entry["set_id"]
    licence = {entry["licence_sha256"] for entry in manifest["sets"]}
    assert len(licence) == 1
    (digest,) = licence
    text = (TEXTURE_DIRECTORY / "blobs" / f"{digest}.txt").read_bytes()
    assert hashlib.sha256(text).hexdigest() == digest
    assert text.startswith(b"CC0 1.0 Universal Public Domain Dedication\n")
    assert b"generated by the Exulanica repository" in text


def test_the_directory_holds_nothing_the_indexes_do_not_name(manifest, catalog):
    named = {".gitattributes", "manifest.json", "catalog.json"}
    named |= {f"blobs/{entry['content_sha256']}.ltex" for entry in manifest["sets"]}
    named |= {f"blobs/{entry['licence_sha256']}.txt" for entry in manifest["sets"]}
    named |= {f"objects/{digest}.json" for digest in catalog.materials.object_digests()}
    present = {
        path.relative_to(TEXTURE_DIRECTORY).as_posix()
        for path in TEXTURE_DIRECTORY.rglob("*")
        if path.is_file()
    }
    assert present == named


def test_every_header_value_is_an_integer_by_canonical_round_trip(manifest):
    """``canonical_json`` raises on a float, so a clean round trip is the integer check."""
    assert canonical_json(json.loads(MANIFEST.read_bytes())) == MANIFEST.read_bytes()
    for entry, payload in _payloads(manifest):
        length = int.from_bytes(payload[4:8], "little")
        raw = payload[8 : 8 + length]
        header = json.loads(raw)
        assert canonical_json(header) == raw, entry["set_id"]
    # And the check has teeth: one float anywhere in a header is refused.
    with pytest.raises(CanonicalisationError, match="float"):
        canonical_json({"extent_mm": {"u": 1800.0, "v": 1800}})


def test_every_header_states_extent_seed_packing_and_plane(manifest):
    for entry, payload in _payloads(manifest):
        header = decode_texture_set(payload).header
        where = entry["set_id"]
        # The load-bearing field: the physical size one tile covers, whole millimetres.
        assert header["extent_mm"] == entry["extent_mm"], where
        assert all(type(v) is int and v > 0 for v in header["extent_mm"].values()), where
        assert type(header["seed"]) is int and 0 <= header["seed"] < 2**32, where
        assert header["version"] == entry["version"], where
        assert header["truth"] == "invented", where
        assert header["media_type"] == "application/vnd.exulanica.texture-set", where
        packing = [(m["name"], m["components"], m["holds"], m["srgb"]) for m in header["maps"]]
        if entry["container_profile"] == TEXTURE_SET_PROFILE_V1:
            assert packing == [
                ("base_color", 3, ["red", "green", "blue"], True),
                ("normal", 3, ["normal_x", "normal_y", "normal_z"], False),
                ("orm", 3, ["occlusion", "roughness", "metalness"], False),
                ("height", 1, ["height"], False),
            ], where
        else:
            # A published set of a class is procedural, so it packs its class's smaller layout.
            assert packing == [
                (m.name, m.components, list(m.holds), m.srgb)
                for m in class_layout(
                    entry["material_class"], "procedural", normal=False, height=False
                )
            ], where
        if entry["material_class"] in RELIEF_CLASSES:
            assert type(header["height_range_mm"]) is int and header["height_range_mm"] > 0
        else:
            assert "height_range_mm" not in header, where


def test_sets_are_named_by_surface_not_by_era_or_typology(manifest):
    """Deriving a material from era or typology is the grammar's material stage, not this one."""
    vocabulary = {
        "prewar", "postwar", "victorian", "georgian", "edwardian", "deco", "beaux", "gothic",
        "modern", "historic", "tenement", "brownstone", "loft", "tower", "office", "commercial",
        "residential", "retail", "civic", "corner", "midblock", "height", "storey", "story",
        "class", "era", "century", "early", "late",
    }  # fmt: skip
    for entry in manifest["sets"]:
        words = set(re.split(r"[.-]", entry["set_id"]))
        assert not words & vocabulary, entry["set_id"]


# -- tiling ------------------------------------------------------------------------------------


def _planes(payload):
    decoded = decode_texture_set(payload)
    width = decoded.header["resolution"]["width"]
    height = decoded.header["resolution"]["height"]
    for layout in decoded.header["maps"]:
        raw = bytes(decoded.maps[layout["name"]])
        mode = {1: "L", 2: "LA", 3: "RGB", 4: "RGBA"}[layout["components"]]
        image = Image.frombytes(mode, (width, height), raw)
        for channel, plane in enumerate(image.split()):
            yield f"{layout['name']}[{channel}]", plane


@dataclass(frozen=True)
class Seam:
    seam: int
    interior: int
    count: int

    @property
    def continuous(self) -> bool:
        """At most twice the mean interior neighbour difference, as loom-texture checks it."""
        return self.seam * self.count <= 2 * self.interior


def _seam(plane, axis):
    """Summed absolute difference across the wrap edge, and across every interior neighbour pair.

    ``ImageChops.offset`` wraps, so the difference image holds every neighbour pair along the axis
    including the one across the edge, which lands in the last column (or row). Sums come from the
    histogram, so they are exact integers.
    """
    width, height = plane.size
    if axis == "u":
        neighbour = ImageChops.offset(plane, -1, 0)
        edge_box, count = (width - 1, 0, width, height), width - 1
    else:
        neighbour = ImageChops.offset(plane, 0, -1)
        edge_box, count = (0, height - 1, width, height), height - 1
    difference = ImageChops.difference(plane, neighbour)
    total = int(ImageStat.Stat(difference).sum[0])
    seam = int(ImageStat.Stat(difference.crop(edge_box)).sum[0])
    return Seam(seam=seam, interior=total - seam, count=count)


def test_every_channel_of_every_set_is_continuous_across_both_wrap_edges(manifest):
    checked = 0
    failures = []
    for entry, payload in _payloads(manifest):
        for name, plane in _planes(payload):
            for axis in ("u", "v"):
                result = _seam(plane, axis)
                checked += 1
                if not result.continuous:
                    failures.append(f"{entry['set_id']} {name} {axis}: {result}")
    assert failures == []
    # Every channel of every map, two edges each: ten channels (3 + 3 + 3 + 1) for a v1 set, and
    # its class layout's channels for any other.
    channels = sum(
        channel["components"] for entry in manifest["sets"] for channel in entry["channels"]
    )
    assert checked == 2 * channels


def test_the_continuity_check_flags_a_plane_that_does_not_tile(manifest):
    payload = next(
        payload
        for entry, payload in _payloads(manifest)
        if entry["set_id"] == "cc0.brick-running-bond"
    )
    name, plane = next(_planes(payload))
    width, height = plane.size
    assert _seam(plane, "u").continuous, name
    # The left half stretched over the whole tile: every interior pair is still a neighbour pair,
    # and the wrap edge now joins texels half a tile apart.
    stretched = plane.crop((0, 0, width // 2, height)).resize(
        (width, height), Image.Resampling.NEAREST
    )
    assert not _seam(stretched, "u").continuous


# -- the resolver ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Material:
    """Shaped like the grammar's surface material record: the id is an attribute."""

    texture_set_id: object


@pytest.mark.parametrize(
    "record",
    [
        {"texture_set_id": "cc0.not-a-pinned-set"},
        {"texture_set_id": "cc0.brick-running-bond-v2"},
        {"texture_set_id": "CC0.BRICK-RUNNING-BOND"},
        {"texture_set_id": " cc0.brick-running-bond"},
        {"texture_set_id": "cc0.brick-running-bond "},
        {"texture_set_id": "91791b17a705e45919e38aa42f2dacba961f01c51675efa443bf4a1934650499"},
        {"texture_set_id": 7},
        {"texture_set_id": True},
        {"texture_set_id": ["cc0.brick-running-bond"]},
        Material("cc0.not-a-pinned-set"),
    ],
)
def test_a_material_naming_an_unpinned_set_is_a_schema_error(catalog, record):
    with pytest.raises(UnpinnedTextureSet):
        resolve_texture_set(record, catalog)


@pytest.mark.parametrize(
    "record",
    [
        {},
        {"texture_set_id": None},
        {"texture_set_id": ""},
        {"material": "brick"},
        Material(None),
        Material(""),
        object(),
        None,
    ],
)
def test_a_material_with_no_texture_set_is_a_schema_error_not_a_default(catalog, record):
    with pytest.raises(MissingTextureSet, match="not a default"):
        resolve_texture_set(record, catalog)


def test_both_failures_share_one_schema_error_type():
    assert issubclass(MissingTextureSet, TextureSetUnresolved)
    assert issubclass(UnpinnedTextureSet, TextureSetUnresolved)
    assert not issubclass(MissingTextureSet, UnpinnedTextureSet)
    assert not issubclass(UnpinnedTextureSet, MissingTextureSet)


def test_a_resolved_set_is_the_pinned_entry_itself_and_nothing_else(catalog, manifest):
    for entry in manifest["sets"]:
        for record in ({"texture_set_id": entry["set_id"]}, Material(entry["set_id"])):
            resolved = resolve_texture_set(record, catalog)
            assert resolved is catalog.sets[entry["set_id"]]
            assert resolved.manifest_entry() == entry
            assert dict(resolved.pin()) == {
                "set_id": entry["set_id"],
                "version": entry["version"],
                "content_sha256": entry["content_sha256"],
            }
            assert hashlib.sha256(resolved.read_bytes()).hexdigest() == entry["content_sha256"]


def test_no_code_path_returns_a_placeholder():
    """One return, and it indexes the catalog by the checked id; no parameter has a default."""
    function = ast.parse(textwrap.dedent(inspect.getsource(resolve_texture_set))).body[0]
    returns = [node for node in ast.walk(function) if isinstance(node, ast.Return)]
    assert [ast.unparse(node.value) for node in returns] == ["catalog.sets[set_id]"]
    parameters = inspect.signature(resolve_texture_set).parameters.values()
    assert [parameter.name for parameter in parameters] == ["material", "catalog"]
    assert all(parameter.default is inspect.Parameter.empty for parameter in parameters)
    raised = {
        node.exc.func.id
        for node in ast.walk(function)
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)
    }
    assert raised == {"MissingTextureSet", "UnpinnedTextureSet"}


# -- the catalog refuses a directory that is not what it claims --------------------------------


def _copy(tmp_path):
    target = tmp_path / "textures"
    shutil.copytree(TEXTURE_DIRECTORY, target)
    return target


def test_the_catalog_refuses_bytes_that_do_not_match_their_pin(tmp_path, manifest):
    directory = _copy(tmp_path)
    entry = manifest["sets"][0]
    blob = directory / "blobs" / f"{entry['content_sha256']}.ltex"
    data = bytearray(blob.read_bytes())
    data[-1] ^= 0x01
    blob.chmod(0o644)
    blob.write_bytes(bytes(data))
    with pytest.raises(TextureCatalogError, match="do not hash"):
        load_texture_catalog(directory)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda doc: doc["sets"].reverse(), "sorted"),
        (lambda doc: doc["sets"].append(dict(doc["sets"][-1])), "sorted"),
        (lambda doc: doc["sets"][0].update(version=0), "positive"),
        (lambda doc: doc["sets"][0].update(version=True), "positive"),
        (lambda doc: doc["sets"][0].update(licence_id="CC-BY-4.0"), "CC0"),
        (lambda doc: doc["sets"][0].update(extent_mm={"u": 1800}), "extent"),
        (lambda doc: doc["sets"][0].update(note=1), "keys"),
        (lambda doc: doc["sets"][0].update(content_sha256="0" * 64), "not in"),
        (lambda doc: doc.update(profile="exulanica.texture-manifest/v3"), "profile"),
    ],
)
def test_the_catalog_refuses_a_manifest_that_breaks_the_contract(
    tmp_path, manifest, change, message
):
    directory = _copy(tmp_path)
    document = json.loads(json.dumps(manifest))
    change(document)
    (directory / "manifest.json").write_bytes(canonical_json(document))
    with pytest.raises(TextureCatalogError, match=message):
        load_texture_catalog(directory)


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (lambda good: good.replace(b'"version":1', b'"version":1.0', 1), "fraction"),
        (lambda good: b"[" * 600 + good + b"]" * 600, "nests more than 64 deep"),
        (lambda good: good.replace(b'"version":1', b'"version":' + b"1" * 5000, 1), "safe range"),
        (lambda good: good + b"\n", "canonical"),
        (lambda good: good.replace(b'{"profile"', b'{ "profile"', 1), "canonical"),
    ],
)
def test_the_catalog_refuses_a_manifest_that_is_not_canonical_integers(tmp_path, raw, message):
    directory = _copy(tmp_path)
    path = directory / "manifest.json"
    path.write_bytes(raw(path.read_bytes()))
    with pytest.raises(TextureCatalogError, match=message):
        load_texture_catalog(directory)


def test_the_catalog_refuses_a_header_that_disagrees_with_the_manifest(tmp_path, manifest):
    directory = _copy(tmp_path)
    document = json.loads(json.dumps(manifest))
    first, last = document["sets"][0], document["sets"][-1]
    # Swap two sets' blobs under each other's names in the manifest only: every digest still
    # names real bytes, but the header inside says it is a different set.
    first["content_sha256"], last["content_sha256"] = (
        last["content_sha256"],
        first["content_sha256"],
    )
    first["byte_size"], last["byte_size"] = last["byte_size"], first["byte_size"]
    (directory / "manifest.json").write_bytes(canonical_json(document))
    with pytest.raises(TextureCatalogError, match="header set_id"):
        load_texture_catalog(directory)


# -- seeding, budget, and the prose ------------------------------------------------------------


def test_seeding_writes_the_pinned_bytes_once(tmp_path, catalog):
    store = LocalContentAddressedStore(tmp_path / "store")
    assert seed_texture_sets(store, catalog) is catalog
    stored = {blob_id.hex for blob_id in store.iter_blob_ids()}
    assert stored == {pinned.content_sha256 for pinned in catalog.sets.values()} | {
        catalog.licence_sha256
    }
    seed_texture_sets(store, catalog)
    assert {blob_id.hex for blob_id in store.iter_blob_ids()} == stored


def test_the_corridor_six_decode_under_the_accepted_envelope(manifest):
    """Every map counted as uploaded RGBA8 with a full mip chain, the six costliest sets charged."""

    def mip_texels(width: int, height: int) -> int:
        total = 0
        while True:
            total += width * height
            if width == 1 and height == 1:
                return total
            width, height = max(1, width // 2), max(1, height // 2)

    costs = sorted(
        (
            len(entry["channels"])
            * 4
            * mip_texels(entry["resolution"]["width"], entry["resolution"]["height"])
            for entry in manifest["sets"]
        ),
        reverse=True,
    )
    corridor = sum(costs[:CORRIDOR_SET_COUNT])
    assert corridor == 134_217_696
    assert corridor < ACCEPTED_DECODED_ENVELOPE_BYTES
    without_mips = sum(
        sorted(
            (
                len(entry["channels"])
                * 4
                * entry["resolution"]["width"]
                * entry["resolution"]["height"]
                for entry in manifest["sets"]
            ),
            reverse=True,
        )[:CORRIDOR_SET_COUNT]
    )
    assert without_mips == 100_663_296


def test_the_document_names_every_pinned_set_and_the_evidence_it_cites(manifest):
    text = DOC.read_text(encoding="utf-8")
    for entry in manifest["sets"]:
        row = re.search(rf"^\|\s*`{re.escape(entry['set_id'])}`\s*\|.*$", text, re.MULTILINE)
        assert row is not None, f"{entry['set_id']} has no row in {DOC.name}"
        assert entry["content_sha256"] in row.group(0), entry["set_id"]
        assert re.search(rf"\|\s*{entry['version']}\s*\|", row.group(0)), entry["set_id"]
    assert EVIDENCE.relative_to(ROOT).as_posix() in text
    for record in HISTORY:
        assert record.is_file() and record.relative_to(ROOT).as_posix() in text
    assert WORKSPACE_EVIDENCE.relative_to(ROOT).as_posix() in text
    assert "\u2014" not in text


def test_the_document_describes_every_pinned_set_and_not_only_lists_it(manifest):
    """A row in the table is not a description, and the paragraphs are written one per set by hand.

    The test above holds every pinned set to a row, which is generated from the same numbers, so it
    cannot notice a set that was published with no prose about it: the list of paragraphs is a gate
    that enumerates what it covers. This holds the paragraphs to the pinned sets instead, by each
    set's title as its library entry states it, appearing inside a bold lead-in somewhere in the
    document. What that paragraph should say is a person's judgement; that there is one is not.
    """
    text = DOC.read_text(encoding="utf-8")
    missing = []
    for entry in manifest["sets"]:
        source = (LIBRARY / f"{entry['set_id']}.json").read_text(encoding="utf-8")
        title = json.loads(source)["title"]
        # The class excludes newlines as well as asterisks: with newlines allowed, the pattern
        # matched a bold span paragraphs away and the check could not fail at all.
        if not re.search(rf"\*\*[^*\n]*{re.escape(title)}[^*\n]*\*\*", text, re.IGNORECASE):
            missing.append(f"{entry['set_id']} ({title})")
    assert missing == [], f"{DOC.name} lists these sets but describes none of them: {missing}"


def _run(record, run):
    section = record.split(f"== run {run}\n", 1)[1].split("\n== ", 1)[0]
    assert "exit: 0" in section, run
    return section


def test_the_determinism_record_is_of_the_published_bytes(manifest):
    record = EVIDENCE.read_text(encoding="utf-8")
    digests = {entry["content_sha256"] for entry in manifest["sets"]}
    for run in RUNS:
        section = _run(record, run)
        listed = set(re.findall(r"^([0-9a-f]{64})  \./blobs/\1\.ltex$", section, re.MULTILINE))
        assert listed == digests, run
        manifest_line = re.search(r"^([0-9a-f]{64})  \./manifest\.json$", section, re.MULTILINE)
        assert manifest_line.group(1) == hashlib.sha256(MANIFEST.read_bytes()).hexdigest(), run
    count = sum(1 for path in TEXTURE_DIRECTORY.rglob("*") if path.is_file())
    for run in RUNS[1:]:
        assert f"{run}: 0 of {count} files differ; {count} files present" in record
    assert f"committed: 0 of {count} files differ; {count} files present" in record


def test_the_object_determinism_record_is_of_every_published_file(manifest, catalog):
    record = OBJECT_EVIDENCE.read_text(encoding="utf-8")
    present = sorted(
        path.relative_to(TEXTURE_DIRECTORY).as_posix()
        for path in TEXTURE_DIRECTORY.rglob("*")
        if path.is_file()
    )
    expected = {
        f"./{name}": hashlib.sha256((TEXTURE_DIRECTORY / name).read_bytes()).hexdigest()
        for name in present
    }
    assert {
        name[len("./objects/") : -len(".json")] for name in expected if "/objects/" in name
    } == (catalog.materials.object_digests())
    assert "working tree changes under web/packages/loom-texture and assets/textures: 0" in record
    for run in RUNS:
        section = _run(record, run)
        listed = dict(
            (name, digest)
            for digest, name in re.findall(r"^([0-9a-f]{64})  (\./\S+)$", section, re.MULTILINE)
        )
        assert listed == expected, run
    count = len(present)
    for run in RUNS[1:]:
        assert f"{run}: 0 of {count} files differ; {count} files present" in record
    assert f"committed: 0 of {count} files differ; {count} files present" in record


def test_the_workspace_bake_record_is_every_published_recipe_baked_alike(manifest):
    """The bake worker's command, on three runtimes and two architectures, one bake per set."""
    record = WORKSPACE_EVIDENCE.read_text(encoding="utf-8")
    # What ran comes first, in order: the script, the request writer it calls, then the source.
    sections = re.findall(r"^== (.+)$", record, re.MULTILINE)
    assert sections[:3] == [
        "script",
        "requests.mts, which the script runs from its own directory",
        "source",
    ], sections
    assert "$HERE/requests.mts" in record.split("\n== requests.mts", 1)[0]
    assert re.search(r"^commit [0-9a-f]{40}$", record, re.MULTILINE)
    assert "working tree changes under web/packages/loom-texture and exulanica: 0" in record
    # A workspace bakes only v1 opaque sets in this version, so the record is of those, and the
    # sets published later with a class are not in it.
    v1_sets = [
        entry for entry in manifest["sets"] if entry["container_profile"] == TEXTURE_SET_PROFILE_V1
    ]
    stems = [f"{index:02d}-{entry['set_id']}" for index, entry in enumerate(v1_sets)]
    runs = {}
    for run in WORKSPACE_RUNS:
        section = record.split(f"== run {run}\n", 1)[1].split("\n== ", 1)[0]
        runs[run] = re.findall(r"^exit 0 (\S+) ([0-9a-f]{64}) (\d+)$", section, re.MULTILINE)
        assert [stem for stem, _, _ in runs[run]] == stems, run
    assert runs[WORKSPACE_RUNS[1]] == runs[WORKSPACE_RUNS[0]] == runs[WORKSPACE_RUNS[2]]
    for run in WORKSPACE_RUNS[1:]:
        assert f"{run}: 0 of {len(stems)} containers differ" in record
    for stem in stems:
        assert f"{stem}: identical across 3 runs" in record
    claimed = re.search(r"^package source digests claimed: \['([0-9a-f]{64})'\]$", record, re.M)
    computed = re.search(
        r"^package source digest the backend computes: ([0-9a-f]{64})$", record, re.M
    )
    assert claimed is not None and computed is not None
    assert claimed.group(1) == computed.group(1)
    # A workspace bake states its own set id and licence, so its bytes are never a published set's.
    published = {entry["content_sha256"] for entry in manifest["sets"]}
    assert not published & {digest for _, digest, _ in runs[WORKSPACE_RUNS[0]]}
