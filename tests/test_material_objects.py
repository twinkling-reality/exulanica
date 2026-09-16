"""Material objects: the shared recipe cases, the strict reader, and the catalog's provenance.

``exulanica.materials`` is the backend's half of ``web/packages/loom-texture``'s recipe checks, and
the two are held together by one file of cases both suites run. The published catalog is then
tampered with in every way the loader should notice: bytes that no longer hash to their names, a
graph that no longer agrees with itself, and a graph that agrees with itself but not with the
containers it claims to account for.

What the backend cannot check is whether a recipe, run through its maker, produces these exact
bytes; that needs the maker, which is TypeScript. The package's own suite rebakes every set from its
recipe and compares byte for byte, so a recipe edited in a way no header shows (a colour, say) is
caught there, not here.
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import MappingProxyType

import pytest
from exulanica.canonical import canonical_json
from exulanica.materials import (
    STRICT_JSON_PROBLEMS,
    MaterialObjectError,
    canonical_bytes,
    check_recipe,
    freeze,
    manifest_problems,
    parse_strict,
    read_object,
    recipe_problems,
    thaw,
)
from exulanica.world.texture_assets import (
    PUBLISHED_MAKER_MANIFESTS,
    TEXTURE_CATALOG_SHA256,
    TEXTURE_DIRECTORY,
    TextureCatalogError,
    load_texture_catalog,
)

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "web" / "packages" / "loom-texture" / "test" / "recipe-cases.json"
CASES = json.loads(CASES_PATH.read_text(encoding="utf-8"))
BRICK = "cc0.brick-running-bond"


@pytest.fixture(scope="module")
def catalog():
    return load_texture_catalog()


def _apply_changes(base, changes):
    """Apply case changes to a copy. The same rules as ``applyChanges`` in recipe.test.ts.

    Anything the two harnesses could read differently is refused: an index is a whole number no
    larger than the list (equal to it only to append), a removal names something that is there,
    and no key is ``__proto__``.
    """
    root = copy.deepcopy(base)
    for change in changes:
        keys = set(change)
        if keys != {"path", "value"} and not (
            keys == {"path", "remove"} and change["remove"] is True
        ):
            raise ValueError(f"a change has a path and either a value or remove: true, not {keys}")
        path = change["path"]
        if "__proto__" in path:
            raise ValueError("a change never names __proto__")
        if not path:
            root = copy.deepcopy(change["value"])
            continue
        parent = root
        for step in path[:-1]:
            parent = parent[step]
        last = path[-1]
        if isinstance(parent, list):
            limit = len(parent) - 1 if "remove" in change else len(parent)
            if type(last) is not int or not 0 <= last <= limit:
                raise ValueError(f"no index {last} to change")
            if "remove" in change:
                del parent[last]
            elif last == len(parent):
                parent.append(copy.deepcopy(change["value"]))
            else:
                parent[last] = copy.deepcopy(change["value"])
        elif type(last) is not str:
            raise ValueError(f"an object is changed by key, not by {last!r}")
        elif "remove" in change:
            if last not in parent:
                raise ValueError(f"nothing to remove at {last}")
            del parent[last]
        else:
            parent[last] = copy.deepcopy(change["value"])
    return root


def _document_bytes(case):
    assert ("text" in case) != ("hex" in case), case["name"]
    return bytes.fromhex(case["hex"]) if "hex" in case else case["text"].encode("utf-8")


def _maker(catalog, maker_id):
    (record,) = [m for (key, _), m in catalog.materials.makers.items() if key == maker_id]
    return record


# -- the shared cases --------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES["recipes"], ids=[c["name"] for c in CASES["recipes"]])
def test_a_recipe_case_is_refused_exactly_as_the_baker_refuses_it(catalog, case):
    record = catalog.materials.sets[case["set"]]
    manifest = _apply_changes(thaw(record.maker.manifest), case.get("manifest_changes", []))
    assert manifest_problems(manifest) == []
    recipe = _apply_changes(thaw(record.recipe), case["changes"])
    assert recipe_problems(recipe, manifest) == case["problems"]


@pytest.mark.parametrize("case", CASES["manifests"], ids=[c["name"] for c in CASES["manifests"]])
def test_a_manifest_case_is_refused_exactly_as_the_baker_refuses_it(catalog, case):
    manifest = _apply_changes(thaw(_maker(catalog, case["maker"]).manifest), case["changes"])
    assert manifest_problems(manifest) == case["problems"]


@pytest.mark.parametrize("case", CASES["documents"], ids=[c["name"] for c in CASES["documents"]])
def test_a_document_case_is_refused_exactly_as_the_baker_refuses_it(case):
    try:
        parse_strict(_document_bytes(case))
    except MaterialObjectError as error:
        problem = str(error)
    else:
        problem = None
    assert problem == case["problem"]
    assert problem is None or problem in STRICT_JSON_PROBLEMS.values()


def test_the_cases_hold_nothing_the_two_languages_read_differently():
    def walk(value):
        if isinstance(value, float):
            assert not value.is_integer(), value
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(CASES)
    assert max(CASES_PATH.read_bytes()) <= 0x7E
    names = [case["name"] for case in CASES["recipes"] + CASES["manifests"] + CASES["documents"]]
    assert len(set(names)) == len(names)


def test_frozen_documents_are_checked_as_their_json_is(catalog):
    record = catalog.materials.sets[BRICK]
    assert recipe_problems(record.recipe, record.maker.manifest) == []
    assert manifest_problems(record.maker.manifest) == []
    assert check_recipe(record.recipe, record.maker.manifest) is record.recipe
    broken = thaw(record.recipe)
    broken["seed"] = -1
    broken["parameters"]["courses"] = 0
    with pytest.raises(MaterialObjectError) as caught:
        check_recipe(broken, record.maker.manifest)
    assert str(caught.value) == (
        "not a valid loom.brick recipe: seed is an unsigned 32-bit integer; "
        "parameters: courses is between 1 and 256"
    )


def test_a_recipe_is_checked_against_the_maker_it_names(catalog):
    materials = catalog.materials
    recipe = thaw(materials.sets[BRICK].recipe)
    assert materials.recipe_problems(recipe) == []
    for maker in ({"id": "loom.brick", "version": 2}, {"id": "loom.brick", "version": True}, None):
        assert materials.recipe_problems({**recipe, "maker": maker}) == [
            "recipe names a maker id and version this catalog has"
        ]
    assert materials.recipe_problems([]) == ["recipe names a maker id and version this catalog has"]
    ashlar = thaw(materials.sets["cc0.limestone-ashlar"].recipe)
    assert materials.recipe_problems({**recipe, "maker": ashlar["maker"]}) != []


# -- the strict reader -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (b'{"a":1.5}', "object: a number is written with a fraction or an exponent"),
        (b'{"a":NaN}', "object: a document is not JSON"),
        (b'{"a":1,"a":2}', "object: an object repeats a key"),
        (b'{"b":1,"a":2}', "object is not canonical JSON"),
        (b'{"a": 1}', "object is not canonical JSON"),
        (b'{"a":1}\n', "object is not canonical JSON"),
        (b'{"a":9007199254740992}', "object: an integer is outside the safe range"),
        (b'{"a":' + b"9" * 5000 + b"}", "object: an integer is outside the safe range"),
        (b"[" * 600 + b"]" * 600, "object: a document nests more than 64 deep"),
        ('{"a":"caf\u00e9"}'.encode(), "object holds a string the baker cannot write"),
        (b'{"a":"\\u0007"}', "object holds a string the baker cannot write"),
        (b"\xff", "object: a document is not JSON"),
        (b"{", "object: a document is not JSON"),
    ],
)
def test_the_reader_refuses_anything_the_baker_would_not_write(raw, message):
    with pytest.raises(MaterialObjectError) as caught:
        read_object(raw, "object")
    assert str(caught.value).startswith(message)


def test_a_document_comes_back_frozen_and_thaws_to_its_json():
    raw = b'{"a":[1,{"b":null}],"c":true}'
    document = read_object(raw, "object")
    assert isinstance(document, MappingProxyType)
    assert document["a"] == (1, MappingProxyType({"b": None}))
    with pytest.raises(TypeError):
        document["c"] = False
    assert canonical_bytes(document) == raw
    assert thaw(document) == json.loads(raw)
    assert freeze(thaw(document)) == document


def test_the_materials_package_loads_no_database_store_evidence_or_numeric_stack():
    probe = (
        "import sys, exulanica.materials\n"
        "print(','.join(sorted(m for m in sys.modules if m.split('.')[0] in "
        "{'torch', 'numpy', 'cv2', 'pycolmap', 'psycopg', 'PIL'} or ("
        "m.startswith('exulanica.') and not m.startswith("
        "('exulanica.materials', 'exulanica.canonical', 'exulanica.errors'))))))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True, cwd=ROOT
    )
    assert result.stdout.strip() == ""


# -- the catalog refuses provenance it cannot account for ---------------------------------------


def _copy(tmp_path):
    target = tmp_path / "textures"
    shutil.copytree(TEXTURE_DIRECTORY, target)
    for path in target.rglob("*"):
        if path.is_file():
            path.chmod(0o644)
    return target


def _read(directory, digest):
    return json.loads((directory / "objects" / f"{digest}.json").read_bytes())


def _write(directory, document):
    raw = canonical_json(document)
    digest = hashlib.sha256(raw).hexdigest()
    (directory / "objects" / f"{digest}.json").write_bytes(raw)
    return digest


def _index(directory):
    return json.loads((directory / "catalog.json").read_bytes())


def _reindex(directory, document):
    (directory / "catalog.json").write_bytes(canonical_json(document))


def _behind_the_pin(directory, **pins):
    """Load with the directory's own catalog digest, to reach the checks the reviewed pin guards."""
    own = hashlib.sha256((directory / "catalog.json").read_bytes()).hexdigest()
    return load_texture_catalog(directory, catalog_sha256=own, **pins)


def _replace_maker(directory, maker_id, change):
    """Swap one maker's manifest for an edited one, re-pointing the catalog and every receipt."""
    index = _index(directory)
    (row,) = [row for row in index["makers"] if row["maker_id"] == maker_id]
    old = row["object_sha256"]
    manifest = _read(directory, old)
    change(manifest)
    row["object_sha256"] = new = _write(directory, manifest)
    for set_row in index["sets"]:
        receipt = _read(directory, set_row["receipt_sha256"])
        if receipt["maker_sha256"] == old:
            receipt["maker_sha256"] = new
            set_row["receipt_sha256"] = _write(directory, receipt)
    _reindex(directory, index)
    return new


def _rebind(directory, set_id, change_recipe=None, change_entry=None, change_receipt=None):
    """Re-point one set at edited objects, every digest kept consistent: a plausible forgery."""
    index = _index(directory)
    (row,) = [row for row in index["sets"] if row["set_id"] == set_id]
    receipt = _read(directory, row["receipt_sha256"])
    entry = _read(directory, receipt["entry_sha256"])
    recipe = _read(directory, receipt["recipe_sha256"])
    if change_recipe is not None:
        change_recipe(recipe)
    recipe_digest = _write(directory, recipe)
    entry["recipe_sha256"] = recipe_digest
    if change_entry is not None:
        change_entry(entry)
    receipt.update(recipe_sha256=recipe_digest, entry_sha256=_write(directory, entry))
    if change_receipt is not None:
        change_receipt(receipt)
    row["receipt_sha256"] = _write(directory, receipt)
    _reindex(directory, index)


def test_a_consistent_rebinding_to_the_same_recipe_still_loads(tmp_path):
    directory = _copy(tmp_path)
    _rebind(directory, BRICK)
    assert load_texture_catalog(directory).sets[BRICK].recipe_sha256 == (
        load_texture_catalog().sets[BRICK].recipe_sha256
    )


@pytest.mark.parametrize(
    ("change_recipe", "message"),
    [
        (lambda recipe: recipe.update(seed=recipe["seed"] + 1), "header seed"),
        (
            lambda recipe: recipe["parameters"].update(height_range_mm=11),
            "header height_range_mm",
        ),
        (
            lambda recipe: recipe["parameters"].update(occlusion_radius_mm=9),
            "header cavity",
        ),
        (
            lambda recipe: recipe.update(resolution={"width": 512, "height": 1024}),
            "header resolution",
        ),
        (lambda recipe: recipe["parameters"].update(courses=23), "not a valid loom.brick recipe"),
        (
            lambda recipe: recipe.update(maker={"id": "loom.ashlar", "version": 1}),
            "not a valid loom.brick recipe",
        ),
    ],
)
def test_the_catalog_refuses_a_recipe_its_bytes_did_not_come_from(tmp_path, change_recipe, message):
    directory = _copy(tmp_path)
    _rebind(directory, BRICK, change_recipe=change_recipe)
    with pytest.raises(TextureCatalogError, match=message):
        _behind_the_pin(directory)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"change_entry": lambda entry: entry.update(title="Brick")}, "header title"),
        ({"change_entry": lambda entry: entry.update(set_id="cc0.other")}, "another set"),
        ({"change_entry": lambda entry: entry.update(summary=" ")}, "title and summary"),
        ({"change_entry": lambda entry: entry.update(licence_id="CC-BY-4.0")}, "licence"),
        (
            {"change_entry": lambda entry: entry.update(recipe_sha256="0" * 64)},
            "different recipes",
        ),
        ({"change_entry": lambda entry: entry.update(note="x")}, "fields other than"),
        ({"change_entry": lambda entry: entry.update(version=True)}, "positive integer version"),
        (
            {"change_receipt": lambda receipt: receipt.update(pipeline="hand made")},
            "baked by",
        ),
        (
            {"change_receipt": lambda receipt: receipt.update(byte_size=1)},
            "byte_size is not the manifest's",
        ),
        (
            {"change_receipt": lambda receipt: receipt.update(maker_sha256="0" * 64)},
            "a maker the catalog lacks",
        ),
        (
            {"change_receipt": lambda receipt: receipt.update(profile="texture-receipt")},
            "is not a exulanica.texture-bake-receipt/v1 object",
        ),
    ],
)
def test_the_catalog_refuses_a_graph_that_disagrees_with_itself(tmp_path, changes, message):
    directory = _copy(tmp_path)
    _rebind(directory, BRICK, **changes)
    with pytest.raises(TextureCatalogError, match=message):
        _behind_the_pin(directory)


def test_the_catalog_refuses_an_object_that_is_not_what_it_is_named(tmp_path):
    directory = _copy(tmp_path)
    (row,) = [row for row in _index(directory)["sets"] if row["set_id"] == BRICK]
    path = directory / "objects" / f"{row['receipt_sha256']}.json"
    path.write_bytes(path.read_bytes().replace(b'"byte_size":', b'"byte_size":1', 1))
    with pytest.raises(TextureCatalogError, match="does not hash to its name"):
        load_texture_catalog(directory)
    path.unlink()
    with pytest.raises(TextureCatalogError, match="is not in"):
        load_texture_catalog(directory)


def test_the_catalog_refuses_an_object_that_is_not_canonical(tmp_path):
    directory = _copy(tmp_path)
    index = _index(directory)
    row = index["sets"][0]
    pretty = json.dumps(_read(directory, row["receipt_sha256"]), indent=1).encode()
    digest = hashlib.sha256(pretty).hexdigest()
    (directory / "objects" / f"{digest}.json").write_bytes(pretty)
    row["receipt_sha256"] = digest
    _reindex(directory, index)
    with pytest.raises(TextureCatalogError, match="not canonical"):
        _behind_the_pin(directory)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda index: index.update(manifest_sha256="0" * 64), "different manifest"),
        (lambda index: index["sets"].pop(), "not the manifest's sets"),
        (lambda index: index["sets"].reverse(), "not the manifest's sets"),
        (lambda index: index["makers"].reverse(), "sorted by id and version"),
        (lambda index: index["makers"].append(index["makers"][0]), "sorted by id and version"),
        (lambda index: index["makers"][0].update(version=2), "different maker"),
        (lambda index: index.update(profile="exulanica.texture-catalog/v2"), "profile"),
        (lambda index: index.update(note="x"), "exactly"),
        (lambda index: index["sets"][0].update(receipt_sha256="nope"), "not a sha256"),
        (lambda index: index["sets"][0].update(version=True), "positive integer version"),
        (lambda index: index["makers"][0].update(version=True), "sorted by id and version"),
    ],
)
def test_the_catalog_refuses_an_index_that_breaks_the_contract(tmp_path, change, message):
    directory = _copy(tmp_path)
    index = _index(directory)
    change(index)
    _reindex(directory, index)
    with pytest.raises(TextureCatalogError, match=message):
        _behind_the_pin(directory)


def test_the_catalog_refuses_a_malformed_maker(tmp_path, catalog):
    directory = _copy(tmp_path)
    index = _index(directory)
    row = index["makers"][0]
    manifest = _read(directory, row["object_sha256"])
    manifest["controls"][0]["group"] = "misc"
    row["object_sha256"] = _write(directory, manifest)
    _reindex(directory, index)
    with pytest.raises(TextureCatalogError, match="malformed manifest: controls"):
        _behind_the_pin(directory)


def test_the_catalog_is_required(tmp_path):
    directory = _copy(tmp_path)
    (directory / "catalog.json").unlink()
    with pytest.raises(TextureCatalogError, match="accounted for by a receipt"):
        load_texture_catalog(directory)


def _forged_courses(recipe):
    recipe["parameters"].update(courses=12, unit_height_mm=140)


def _forged_bond(recipe):
    recipe["parameters"].update(bond="stack")


@pytest.mark.parametrize("forge", [_forged_courses, _forged_bond], ids=["courses", "bond"])
def test_the_reviewed_pin_refuses_a_forgery_that_agrees_with_itself(tmp_path, forge):
    """A valid recipe, re-bound with every digest kept consistent, is still not the reviewed one."""
    directory = _copy(tmp_path)
    _rebind(directory, BRICK, change_recipe=forge)
    with pytest.raises(TextureCatalogError, match="not the reviewed pin"):
        load_texture_catalog(directory)


def test_a_stated_module_that_disagrees_with_its_recipe_is_refused_behind_the_pin(tmp_path):
    directory = _copy(tmp_path)
    _rebind(directory, BRICK, change_recipe=_forged_courses)
    with pytest.raises(TextureCatalogError, match="header parameter courses is 24, but its recipe"):
        _behind_the_pin(directory)


def test_a_published_maker_version_never_names_another_manifest(tmp_path):
    """The deleted-constraint forgery: a weaker brick manifest under the same version."""
    directory = _copy(tmp_path)

    def drop_the_even_rule(manifest):
        manifest["constraints"] = [
            rule for rule in manifest["constraints"] if rule["kind"] != "even"
        ]

    forged = _replace_maker(directory, "loom.brick", drop_the_even_rule)
    with pytest.raises(TextureCatalogError, match="not the reviewed pin"):
        load_texture_catalog(directory)
    with pytest.raises(TextureCatalogError, match=r"loom\.brick version 1 is not the published"):
        _behind_the_pin(directory)
    # Named explicitly as published, the weaker manifest loads, and it is weaker: the recipe the
    # real brick maker refuses passes its check. That is what the pinned table exists to prevent.
    makers = {**PUBLISHED_MAKER_MANIFESTS, ("loom.brick", 1): forged}
    weaker = _behind_the_pin(directory, makers=makers).materials
    odd = thaw(weaker.sets[BRICK].recipe)
    odd["parameters"]["courses"] = 25
    odd["extent_mm"]["v"] = 1875
    assert weaker.recipe_problems(odd) == []
    assert load_texture_catalog().materials.recipe_problems(odd) == [
        "running bond repeats every two courses, so the tile holds an even number"
    ]


def test_the_pins_are_the_committed_library():
    assert hashlib.sha256((TEXTURE_DIRECTORY / "catalog.json").read_bytes()).hexdigest() == (
        TEXTURE_CATALOG_SHA256
    )
    index = json.loads((TEXTURE_DIRECTORY / "catalog.json").read_bytes())
    assert {
        (row["maker_id"], row["version"]): row["object_sha256"] for row in index["makers"]
    } == dict(PUBLISHED_MAKER_MANIFESTS)


def test_every_pinned_set_names_its_maker_and_recipe(catalog):
    for set_id, pinned in catalog.sets.items():
        record = catalog.materials.sets[set_id]
        assert (pinned.maker_id, pinned.maker_version) == (
            record.maker.maker_id,
            record.maker.version,
        )
        assert pinned.recipe_sha256 == record.recipe_sha256
        assert pinned.receipt_sha256 == record.receipt_sha256
        raw = (TEXTURE_DIRECTORY / "objects" / f"{pinned.recipe_sha256}.json").read_bytes()
        assert hashlib.sha256(raw).hexdigest() == pinned.recipe_sha256
        assert read_object(raw, set_id) == record.recipe
