"""The draw, the seed and the records: deterministic replay, tested rather than asserted.

What this file holds the generator system to.

*   ``_number`` is **exactly the specified formula**, pinned by a known answer.
*   It is **domain-namespaced**: draws in one domain do not move when another domain, or a whole
    new stage, draws in between.
*   The emitted record set is **byte-stable across two interpreter processes** with different
    hash seeds. A repeat inside one process cannot see a set-iteration or ``id()`` leak.
*   A seed is **64 lowercase hex characters** and nothing else, and it is never defaulted.
*   **No clock, no ``random``, no ``secrets`` and no float** anywhere in the package, by an AST
    scan whose own detector is tested, not by reading the code.
*   Canonical JSON **accepts the whole emitted record set and refuses every float** injected
    into it, at every position.
*   Every city stage **emits nothing and says so**, and every record shape has a validator.

The record instances below named ``_FIXTURES`` are validator inputs written for this test. They
are not stage output, and no stage emits them.
"""

from __future__ import annotations

import ast
import copy
import dataclasses
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest
from exulanica.canonical import canonical_json
from exulanica.errors import CanonicalisationError
from exulanica.grammar import (
    CascadeBinding,
    DeclaredSemantics,
    Grammar,
    StageContext,
    StageEmission,
    generate,
)
from exulanica.grammar.draw import DomainCursor, _number, draw_integer
from exulanica.grammar.errors import (
    InvalidDomainError,
    InvalidParameterError,
    InvalidRecordError,
    InvalidSeedError,
    UnresolvedReferenceError,
)
from exulanica.grammar.grammars import builtin_registry
from exulanica.grammar.grammars.city import CITY_STAGES
from exulanica.grammar.grammars.city.facade import FACADE_RECORD_FIELDS, FacadeRecord
from exulanica.grammar.grammars.city.massing import MassingRecord
from exulanica.grammar.grammars.city.material import SurfaceMaterialRecord, require_texture_set
from exulanica.grammar.grammars.city.parcels import ParcelRecord
from exulanica.grammar.grammars.city.premises import PremisesRecord
from exulanica.grammar.grammars.city.streetlife import StreetFurnitureRecord
from exulanica.grammar.grammars.city.streets import (
    CurbEdgeRecord,
    StreetNodeRecord,
    StreetSegmentRecord,
)
from exulanica.grammar.grammars.city.terrain import TerrainRecord
from exulanica.grammar.grammars.city.tile import TileRecord, tile_inputs_digest
from exulanica.grammar.grammars.city.vitrine import VitrineRecord
from exulanica.grammar.records import MAX_SAFE_INTEGER, record_payload
from exulanica.grammar.seed import require_seed

ROOT = Path(__file__).resolve().parents[1]
_PACKAGE = ROOT / "exulanica" / "grammar"

SEED = hashlib.sha256(b"exulanica grammar draw test").hexdigest()
IDENTITY = "0e3b7f2a-5c1d-5a4b-8e6f-1a2b3c4d5e6f"

_STAGES_BY_ID = {stage.stage_id: stage for stage in CITY_STAGES}

_FIXTURES = {
    "terrain": TerrainRecord(0, 0, 1000, 2, 2, (0, 10, 20, 30), (0, 1, 2, 3)),
    "streets": StreetNodeRecord(0, 0, 0),
    "streets:segment": StreetSegmentRecord(
        0, 0, 1, ((0, 0), (126_000, 0)), "test_hierarchy", 7000, 150, 300, 3000, 4000, (10, 60)
    ),
    "streets:curb": CurbEdgeRecord(0, 0, "left", 1),
    "parcels": ParcelRecord(
        0, 0, "memory_precinct", ((0, 0), (10_000, 0), (10_000, 20_000)), 0, 10_000, 1, 500
    ),
    "massing": MassingRecord(
        IDENTITY,
        0,
        "test_typology",
        "test_era",
        4,
        4500,
        3200,
        ((3, 2000),),
        (0, 2),
        1,
        "test_roof",
        900,
        1,
        1,
    ),
    "facade": FacadeRecord(
        IDENTITY,
        1,
        (("test_integer", 3000), ("test_key", "test_value")),
        SEED,
        "0" * 64,
        DeclaredSemantics("facade", ()),
        0,
    ),
    "material": SurfaceMaterialRecord(
        IDENTITY, 0, "test_material", "test-texture-set", 1_000_000, 0, 75, 10, 0, 0, 0
    ),
    "streetlife": StreetFurnitureRecord(0, "test_item", 0, "right", 5000, 600, 5000, -600),
    "vitrine": VitrineRecord(IDENTITY, 0, 0, 900, "test_fitout"),
    "premises": PremisesRecord(IDENTITY, 0, "test_use", "test_sign"),
    "tile": TileRecord(
        SEED, (("box", 1), ("city", 1)), "1" * 64, 0, 0, 0, 128_000, 64_000, "2" * 64
    ),
}


def _stage_for(fixture_name: str):
    return _STAGES_BY_ID[fixture_name.split(":")[0]]


# ---------------------------------------------------------------------------------------------
# The draw


def test_the_draw_is_the_specified_formula():
    for domain, ordinal in (("streets.hierarchy", 0), ("vitrine.fitout", 7), ("a", 2**40)):
        expected = int.from_bytes(
            hashlib.sha256(f"{SEED}:{domain}:{ordinal}".encode()).digest()[:8], "big"
        )
        assert _number(SEED, domain, ordinal) == expected


def test_the_draw_has_a_pinned_known_answer():
    """Catches a change to the preimage format that a formula re-derived in the test would share."""
    assert _number("0" * 64, "streets.hierarchy", 0) == int.from_bytes(
        hashlib.sha256(("0" * 64 + ":streets.hierarchy:0").encode()).digest()[:8], "big"
    )
    assert _number("0" * 64, "streets.hierarchy", 0) == 14_443_913_048_662_594_536


def test_a_domain_sequence_is_unchanged_when_another_domain_draws_in_between():
    alone = DomainCursor(SEED, "streets.hierarchy")
    expected = [alone.number() for _ in range(32)]

    streets = DomainCursor(SEED, "streets.hierarchy")
    newcomer = DomainCursor(SEED, "vitrine.fitout")
    interleaved = []
    newcomer_values = []
    for _ in range(32):
        newcomer_values.extend(newcomer.number() for _ in range(3))
        interleaved.append(streets.number())
    assert interleaved == expected
    assert [_number(SEED, "streets.hierarchy", ordinal) for ordinal in range(32)] == expected
    assert not set(newcomer_values) & set(expected), "two domains produced the same stream"


def _probe_grammar(tmp_path: Path, stage_ids: tuple[str, ...]) -> Grammar:
    descriptor = tmp_path / "probe.v1.json"
    if not descriptor.exists():
        descriptor.write_text(
            '{"schema_version": 1, "grammar_id": "probe", "grammar_version": 1,'
            ' "subject_kind": "probe", "admissible_uses": [], "cascade_levels": ["probe"],'
            ' "parameters": []}',
            encoding="utf-8",
        )

    @dataclasses.dataclass(frozen=True, slots=True)
    class DrawStage:
        stage_id: str
        stage_version: int = 1

        def emit(self, context: StageContext) -> StageEmission:
            cursor = context.cursor("value")
            records = tuple(
                FacadeRecord(
                    IDENTITY,
                    1,
                    (("draw", cursor.integer(0, 1 << 30)),),
                    SEED,
                    "0" * 64,
                    DeclaredSemantics("probe", ()),
                    index,
                )
                for index in range(8)
            )
            return StageEmission(self.stage_id, 1, "emitted", "", records)

        def validate(self, record: object) -> None:
            return None

    return Grammar.from_descriptor(descriptor, tuple(DrawStage(stage_id) for stage_id in stage_ids))


def test_adding_a_stage_never_reshuffles_an_earlier_stage(tmp_path):
    before = generate(_probe_grammar(tmp_path, ("streets",)), seed=SEED, subject_identity=IDENTITY)
    after = generate(
        _probe_grammar(tmp_path, ("terrain", "streets", "vitrine")),
        seed=SEED,
        subject_identity=IDENTITY,
    )
    [streets_before] = before.emissions
    streets_after = after.emissions[1]
    assert record_payload(streets_before) == record_payload(streets_after)
    assert record_payload(after.emissions[0]) != record_payload(streets_after)


def test_a_bounded_draw_covers_its_range_and_stays_inside_it():
    seen = {draw_integer(SEED, "box.parameters.width_mm", ordinal, 3, 7) for ordinal in range(400)}
    assert seen == {3, 4, 5, 6, 7}
    assert draw_integer(SEED, "a", 0, 5, 5) == 5
    assert -(1 << 32) <= draw_integer(SEED, "a", 1, -(1 << 32), -1) <= -1


@pytest.mark.parametrize("bounds", [(5, 4), (0, 1 << 32), (0.0, 1)])
def test_a_bounded_draw_refuses_an_empty_huge_or_non_integer_range(bounds):
    with pytest.raises(InvalidDomainError):
        draw_integer(SEED, "a", 0, *bounds)


@pytest.mark.parametrize(
    "domain,ordinal",
    [
        ("Streets.hierarchy", 0),
        ("streets:hierarchy", 0),
        ("streets..hierarchy", 0),
        (".streets", 0),
        ("", 0),
        ("streets", -1),
        ("streets", True),
        ("streets", 1.0),
        (b"streets", 0),
    ],
)
def test_a_malformed_domain_or_ordinal_is_refused(domain, ordinal):
    with pytest.raises(InvalidDomainError):
        _number(SEED, domain, ordinal)


# ---------------------------------------------------------------------------------------------
# The seed


def test_a_well_formed_seed_is_returned_unchanged():
    assert require_seed(SEED) is SEED


@pytest.mark.parametrize(
    "seed",
    [
        SEED.upper(),
        SEED.replace("c", "C", 1),
        SEED[:63],
        SEED + "0",
        "g" + SEED[1:],
        " " + SEED[1:],
        SEED[:63] + "\n",
        chr(0x0660) * 64,
        int(SEED, 16),
        bytes.fromhex(SEED),
        None,
    ],
)
def test_a_malformed_seed_is_refused(seed):
    with pytest.raises(InvalidSeedError):
        require_seed(seed)
    with pytest.raises(InvalidSeedError):
        _number(seed, "streets.hierarchy", 0)


def test_a_seed_is_never_defaulted():
    box = builtin_registry().get("box", 1)
    with pytest.raises(TypeError):
        generate(box, subject_identity=IDENTITY)  # type: ignore[call-arg]
    with pytest.raises(InvalidSeedError):
        generate(box, seed=int(SEED, 16), subject_identity=IDENTITY)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------------------------
# Byte stability across processes

_EMIT = r"""
import sys
import exulanica.grammar
from exulanica.canonical import sha256_of_canonical
from exulanica.grammar import generate
from exulanica.grammar.catalogs import catalog_digest
from exulanica.grammar.draw import _number
from exulanica.grammar.grammars import builtin_registry
from exulanica.grammar.grammars.city.catalogs import load_city_catalogs

seed, identity = sys.argv[1], sys.argv[2]
registry = builtin_registry()
emitted = {
    "generations": [
        generate(registry.get(key.grammar_id, key.grammar_version), seed=seed,
                 subject_identity=identity).payload()
        for key in registry.registered_keys()
    ],
    "draws": {
        domain: [str(_number(seed, domain, ordinal)) for ordinal in range(64)]
        for domain in {"streets.hierarchy", "box.parameters.width_mm", "vitrine.fitout"}
    },
    "catalog_digest": catalog_digest(load_city_catalogs(texture_set_ids=frozenset())),
}
print(exulanica.grammar.__file__)
print(sha256_of_canonical(emitted).hex())
"""


def _emit_in_a_new_process(hash_seed: str) -> str:
    result = subprocess.run(
        [sys.executable, "-c", _EMIT, SEED, IDENTITY],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "PYTHONHASHSEED": hash_seed},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    module_path, digest = result.stdout.split()
    # A child that imported another checkout's package would measure the wrong code.
    assert Path(module_path).resolve().is_relative_to(ROOT), module_path
    return digest


def test_the_emitted_record_set_is_byte_stable_across_two_processes():
    first = _emit_in_a_new_process("1")
    second = _emit_in_a_new_process("4294967295")
    assert first == second
    assert len(first) == 64


# ---------------------------------------------------------------------------------------------
# No clock, no random, no secrets, no float

_BANNED_MODULES = frozenset(
    {
        "calendar",
        "cmath",
        "datetime",
        "decimal",
        "fractions",
        "math",
        "numpy",
        "random",
        "secrets",
        "statistics",
        "time",
        "zoneinfo",
    }
)
_BANNED_NAMES = frozenset({"float", "complex"})
_BANNED_CALLS = frozenset({"hash", "id", "pow", "round", "float", "complex"})
_BANNED_ATTRIBUTES = frozenset(
    {
        "environ",
        "fromtimestamp",
        "getenv",
        "getrandbits",
        "monotonic",
        "now",
        "perf_counter",
        "random",
        "SystemRandom",
        "time_ns",
        "today",
        "urandom",
        "utcnow",
        "uuid1",
        "uuid4",
    }
)


def _nondeterminism(source: str, filename: str) -> list[str]:
    problems = []
    tree = ast.parse(source, filename=filename)
    for node in ast.walk(tree):
        where = f"{filename}:{getattr(node, 'lineno', '?')}"
        if isinstance(node, ast.Import):
            problems += [
                f"{where} imports {alias.name}"
                for alias in node.names
                if alias.name.split(".")[0] in _BANNED_MODULES
            ]
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] in _BANNED_MODULES:
                problems.append(f"{where} imports from {node.module}")
            problems += [
                f"{where} imports {alias.name}"
                for alias in node.names
                if alias.name in _BANNED_ATTRIBUTES
            ]
        elif isinstance(node, ast.Name) and node.id in _BANNED_NAMES:
            problems.append(f"{where} names {node.id}")
        elif isinstance(node, ast.Attribute) and node.attr in _BANNED_ATTRIBUTES:
            problems.append(f"{where} reaches .{node.attr}")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in _BANNED_CALLS:
                problems.append(f"{where} calls {node.func.id}()")
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr in {"load", "loads"}
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "json"
                and "parse_float" not in {keyword.arg for keyword in node.keywords}
            ):
                problems.append(f"{where} parses JSON without refusing floats")
        elif isinstance(node, ast.Constant) and type(node.value) in {float, complex}:
            problems.append(f"{where} has a non-integer literal {node.value!r}")
        elif isinstance(node, ast.BinOp | ast.AugAssign) and isinstance(node.op, ast.Div | ast.Pow):
            problems.append(f"{where} uses {type(node.op).__name__}, which can make a float")
    return problems


def test_the_nondeterminism_scan_catches_what_it_claims_to():
    """A scan that finds nothing must be shown able to find something."""
    planted = {
        "x = 1.5": "non-integer literal",
        "import random": "imports random",
        "from time import time": "imports from time",
        "import secrets": "imports secrets",
        "from datetime import datetime": "imports from datetime",
        "y = a / b": "Div",
        "y = a ** b": "Pow",
        "y /= 2": "Div",
        "y = float(a)": "calls float()",
        "y: float = 0": "names float",
        "y = hash(a)": "calls hash()",
        "y = id(a)": "calls id()",
        "y = os.urandom(8)": "reaches .urandom",
        "y = os.environ['A']": "reaches .environ",
        "y = uuid.uuid4()": "reaches .uuid4",
        "y = json.loads(t)": "without refusing floats",
    }
    for source, expected in planted.items():
        found = _nondeterminism(source, "<planted>")
        assert any(expected in problem for problem in found), (source, found)
    assert _nondeterminism("y = a // b << 3\nz = json.loads(t, parse_float=f)", "<clean>") == []


def test_the_grammar_package_has_no_clock_no_random_no_secrets_and_no_float():
    sources = sorted(_PACKAGE.rglob("*.py"))
    assert _PACKAGE.joinpath("draw.py") in sources
    assert len(sources) >= 2
    problems = []
    for path in sources:
        problems += _nondeterminism(path.read_text(encoding="utf-8"), str(path.relative_to(ROOT)))
    assert problems == [], "\n".join(problems)


# ---------------------------------------------------------------------------------------------
# Canonical JSON over the emitted set, and every float refused


def _emitted_set() -> dict[str, object]:
    registry = builtin_registry()
    return {
        "generations": [
            generate(
                registry.get(key.grammar_id, key.grammar_version),
                seed=SEED,
                subject_identity=IDENTITY,
            ).payload()
            for key in registry.registered_keys()
        ],
        "validator_fixtures": {name: record_payload(record) for name, record in _FIXTURES.items()},
    }


def _leaf_paths(value: object, path: tuple = ()) -> list[tuple]:
    if isinstance(value, dict):
        return [path] + [p for key, sub in value.items() for p in _leaf_paths(sub, (*path, key))]
    if isinstance(value, list):
        return [path] + [
            p for index, sub in enumerate(value) for p in _leaf_paths(sub, (*path, index))
        ]
    return [path]


def _inject(document: object, path: tuple, poison: float) -> object:
    """Replace the value at ``path`` with ``poison``; at a container, add it as a new member."""
    copied = copy.deepcopy(document)
    if not path:
        return poison
    parent = copied
    for step in path[:-1]:
        parent = parent[step]  # type: ignore[index]
    target = parent[path[-1]]  # type: ignore[index]
    if isinstance(target, dict):
        target["injected"] = poison
    elif isinstance(target, list):
        target.append(poison)
    else:
        parent[path[-1]] = poison  # type: ignore[index]
    return copied


def test_canonical_json_accepts_the_whole_emitted_record_set():
    emitted = _emitted_set()
    assert canonical_json(emitted)
    kinds = [
        emission["kind"]
        for generation in emitted["generations"]
        for emission in generation["emissions"]
    ]
    assert kinds and set(kinds) == {"grammar.stage_emission"}


@pytest.mark.parametrize("poison", [0.5, 0.0, -0.0, 1e300, float("nan"), float("inf")])
def test_every_float_injected_anywhere_in_the_emitted_set_is_refused(poison):
    emitted = _emitted_set()
    paths = _leaf_paths(emitted)
    assert len(paths) > 200, len(paths)
    for path in paths:
        with pytest.raises(CanonicalisationError):
            canonical_json(_inject(emitted, path, poison))


def _float_variants(record: object):
    """Every field replaced by a float, and for tuple fields, their first leaf."""
    for field in dataclasses.fields(record):
        value = getattr(record, field.name)
        yield field.name, dataclasses.replace(record, **{field.name: 0.5})
        if isinstance(value, tuple) and value:
            first = value[0]
            poisoned = (0.5,) if not isinstance(first, tuple) else ((0.5, *first[1:]),)
            yield (
                f"{field.name}[0]",
                dataclasses.replace(record, **{field.name: poisoned + value[1:]}),
            )


@pytest.mark.parametrize("name", sorted(_FIXTURES))
def test_every_record_validator_refuses_a_float_in_any_field_by_canonical_json(name):
    record = _FIXTURES[name]
    stage = _stage_for(name)
    stage.validate(record)
    variants = list(_float_variants(record))
    assert len(variants) >= len(dataclasses.fields(record))
    for _field, variant in variants:
        with pytest.raises(CanonicalisationError):
            stage.validate(variant)


def test_a_record_integer_a_javascript_reader_would_change_is_refused():
    node = StreetNodeRecord(0, MAX_SAFE_INTEGER, -MAX_SAFE_INTEGER)
    _stage_for("streets").validate(node)
    with pytest.raises(InvalidRecordError):
        _stage_for("streets").validate(StreetNodeRecord(0, MAX_SAFE_INTEGER + 1, 0))


@pytest.mark.parametrize("value", [True, None, [1], {"a": 1}])
def test_a_record_value_that_is_not_an_int_str_tuple_or_record_is_refused(value):
    with pytest.raises(InvalidRecordError):
        record_payload(StreetNodeRecord(0, value, 0))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------------------------
# The stage skeletons

_CITY_STAGE_IDS = (
    "terrain",
    "streets",
    "parcels",
    "massing",
    "facade",
    "material",
    "streetlife",
    "vitrine",
    "premises",
    "tile",
)


def test_the_city_declares_the_ten_stages_in_order_each_versioned():
    assert tuple(stage.stage_id for stage in CITY_STAGES) == _CITY_STAGE_IDS
    assert all(
        type(stage.stage_version) is int and stage.stage_version >= 1 for stage in CITY_STAGES
    )


def test_every_city_stage_emits_nothing_and_says_so():
    city = builtin_registry().get("city", 1)
    generation = generate(city, seed=SEED, subject_identity=IDENTITY)
    assert [emission.stage_id for emission in generation.emissions] == list(_CITY_STAGE_IDS)
    for emission in generation.emissions:
        assert emission.status == "not_implemented"
        assert emission.records == ()
        assert "no generator" in emission.reason
    assert generation.receipt.declared_semantics == DeclaredSemantics("city", ())
    assert generation.receipt.parameters.values == ()


def test_every_city_stage_has_a_validator_for_a_fixture():
    covered = {_stage_for(name).stage_id for name in _FIXTURES}
    assert covered == set(_CITY_STAGE_IDS)


def test_an_unimplemented_stage_cannot_emit_records_and_cannot_stay_silent():
    with pytest.raises(InvalidRecordError):
        StageEmission("streets", 1, "not_implemented", "none yet", (_FIXTURES["streets"],))
    with pytest.raises(InvalidRecordError):
        StageEmission("streets", 1, "not_implemented", "", ())
    with pytest.raises(InvalidRecordError):
        StageEmission("streets", 1, "emitted", "a reason for an emitted stage", ())


def test_the_facade_record_carries_the_six_section_5_1_fields():
    names = [field.name for field in dataclasses.fields(FacadeRecord)]
    assert FACADE_RECORD_FIELDS == (
        "building_identity",
        "grammar_version",
        "parameters",
        "seed",
        "output_digest",
        "declared_semantics",
    )
    assert names[:6] == list(FACADE_RECORD_FIELDS)
    fields = record_payload(_FIXTURES["facade"])["fields"]
    assert set(FACADE_RECORD_FIELDS) <= set(fields)
    assert fields["declared_semantics"]["plane"] == "invented"


def test_the_generic_receipt_carries_the_same_six_facts():
    receipt = generate(
        builtin_registry().get("box", 1), seed=SEED, subject_identity=IDENTITY
    ).receipt
    assert {field.name for field in dataclasses.fields(receipt)} == {
        "subject_identity",
        "grammar_id",
        "grammar_version",
        "parameters",
        "seed",
        "output_digest",
        "declared_semantics",
    }


@pytest.mark.parametrize(
    "name,change",
    [
        ("streets:segment", {"kerb_height_mm": 99}),
        ("streets:segment", {"kerb_height_mm": 181}),
        ("streets:segment", {"end_node": 0}),
        ("streets:segment", {"crossing_offsets_mm": (60, 10)}),
        ("streets:segment", {"centreline_mm": ((0, 0),)}),
        ("streets:segment", {"hierarchy": "Primary"}),
        ("streets:curb", {"side": "middle"}),
        ("parcels", {"frontage_mm": 0}),
        ("parcels", {"lot_class": "hole"}),
        ("parcels", {"boundary_mm": ((0, 0), (1, 0), (0, 0))}),
        ("massing", {"setbacks": ((4, 2000),)}),
        ("massing", {"storeys": 0}),
        ("massing", {"building_identity": "not-a-uuid"}),
        ("facade", {"seed": "0" * 63}),
        ("facade", {"parameters": (("b", 1), ("a", 2))}),
        ("facade", {"output_digest": "A" * 64}),
        ("material", {"texture_set_id": ""}),
        ("material", {"uv_rotation_urad": 6_283_186}),
        ("material", {"soiling_gradient_millionths": 1_000_001}),
        ("vitrine", {"depth_mm": 599}),
        ("vitrine", {"depth_mm": 1501}),
        ("terrain", {"height_mm": (0, 10, 20)}),
        ("tile", {"tile_size_mm": 127_999}),
        ("tile", {"halo_radius_mm": 0}),
        ("tile", {"grammar_versions": (("city", 1), ("box", 1))}),
        ("premises", {"sign": "Sign Text"}),
    ],
)
def test_a_record_outside_its_declared_shape_is_refused(name, change):
    with pytest.raises((InvalidRecordError, InvalidSeedError)):
        _stage_for(name).validate(dataclasses.replace(_FIXTURES[name], **change))


def test_a_stage_refuses_a_record_type_it_does_not_declare():
    with pytest.raises(InvalidRecordError):
        _stage_for("vitrine").validate(_FIXTURES["premises"])


def test_a_material_whose_texture_set_is_not_published_is_refused():
    material = _FIXTURES["material"]
    with pytest.raises(UnresolvedReferenceError):
        require_texture_set(material, frozenset())
    require_texture_set(material, frozenset({"test-texture-set"}))


def test_the_tile_digest_moves_with_the_edit_subsequence():
    tile = _FIXTURES["tile"]
    moved = dataclasses.replace(tile, edit_delta_digest="3" * 64)
    assert tile_inputs_digest(tile) != tile_inputs_digest(moved)
    assert tile_inputs_digest(tile) == tile_inputs_digest(dataclasses.replace(tile))


# ---------------------------------------------------------------------------------------------
# Parameters and the cascade


def _cascade_grammar(tmp_path: Path) -> Grammar:
    descriptor = tmp_path / "cascade.v1.json"
    descriptor.write_text(
        '{"schema_version": 1, "grammar_id": "cascade", "grammar_version": 1,'
        ' "subject_kind": "probe", "admissible_uses": [],'
        ' "cascade_levels": ["outer", "middle", "inner"],'
        ' "parameters": ['
        '  {"name": "size_mm", "kind": "integer", "minimum": 1, "maximum": 100,'
        '   "when_unset": "draw"},'
        '  {"name": "finish", "kind": "choice", "options": ["matte", "gloss"],'
        '   "when_unset": "required"}]}',
        encoding="utf-8",
    )
    return Grammar.from_descriptor(descriptor, _probe_grammar(tmp_path, ("only",)).stages)


def test_the_finest_binding_wins_and_every_value_says_where_it_came_from(tmp_path):
    grammar = _cascade_grammar(tmp_path)
    generation = generate(
        grammar,
        seed=SEED,
        subject_identity=IDENTITY,
        bindings=(
            CascadeBinding.of("inner", {"finish": "gloss"}),
            CascadeBinding.of("outer", {"finish": "matte", "size_mm": 40}),
        ),
    )
    parameters = generation.receipt.parameters
    assert dict(parameters.values) == {"finish": "gloss", "size_mm": 40}
    assert dict(parameters.sources) == {"finish": "inner", "size_mm": "outer"}

    drawn = generate(
        grammar,
        seed=SEED,
        subject_identity=IDENTITY,
        bindings=(CascadeBinding.of("middle", {"finish": "matte"}),),
    ).receipt.parameters
    assert dict(drawn.sources)["size_mm"] == "draw"
    assert dict(drawn.values)["size_mm"] == draw_integer(
        SEED, "cascade.parameters.size_mm", 0, 1, 100
    )


@pytest.mark.parametrize(
    "bindings",
    [
        (),
        (CascadeBinding.of("outer", {"finish": "satin"}),),
        (CascadeBinding.of("outer", {"finish": "matte", "size_mm": 101}),),
        (CascadeBinding.of("outer", {"finish": "matte", "colour": 3}),),
        (CascadeBinding.of("attic", {"finish": "matte"}),),
        (
            CascadeBinding.of("outer", {"finish": "matte"}),
            CascadeBinding.of("outer", {"finish": "gloss"}),
        ),
    ],
)
def test_a_parameter_the_schema_does_not_admit_is_refused(tmp_path, bindings):
    with pytest.raises(InvalidParameterError):
        generate(
            _cascade_grammar(tmp_path), seed=SEED, subject_identity=IDENTITY, bindings=bindings
        )
