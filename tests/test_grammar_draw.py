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
*   A city stage with a generator **emits records**, every other city stage **emits nothing and
    says so**, and every record kind has a validator.

The record instances below named ``_FIXTURES`` are validator inputs: one record of every city
record kind, taken from the hand-written city v2 fixture (``tests/fixtures/city-v2``). They are
not stage output, and no stage emits them.
"""

from __future__ import annotations

import ast
import copy
import dataclasses
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import ClassVar

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
from exulanica.grammar.contract import UnimplementedStage
from exulanica.grammar.draw import DomainCursor, _number, draw_integer
from exulanica.grammar.errors import (
    CatalogError,
    InvalidDomainError,
    InvalidParameterError,
    InvalidRecordError,
    InvalidSeedError,
    UnresolvedReferenceError,
)
from exulanica.grammar.grammars import builtin_registry
from exulanica.grammar.grammars.city import CITY_STAGES
from exulanica.grammar.grammars.city.facade import FACADE_RECORD_FIELDS, FacadeRecord
from exulanica.grammar.grammars.city.material import require_texture_set
from exulanica.grammar.grammars.city.tile import tile_inputs_digest
from exulanica.grammar.records import MAX_SAFE_INTEGER, record_payload
from exulanica.grammar.seed import require_seed
from exulanica.grammar.textures import read_texture_manifest

from city_v2_fixture import BUILDER_PATH, builder, records_by_kind, stage_of_kind

ROOT = Path(__file__).resolve().parents[1]
_PACKAGE = ROOT / "exulanica" / "grammar"

SEED = hashlib.sha256(b"exulanica grammar draw test").hexdigest()
IDENTITY = "0e3b7f2a-5c1d-5a4b-8e6f-1a2b3c4d5e6f"

_STAGES_BY_ID = {stage.stage_id: stage for stage in CITY_STAGES}
_STAGE_OF_KIND = stage_of_kind()

#: One record of every city record kind the stages validate, keyed by kind. The tile record is
#: the fixture document's envelope, not one of its records.
_FIXTURES = {
    **{kind: records[0] for kind, records in records_by_kind().items()},
    "city.tile": builder().tile,
}
#: The one parameter nothing may choose silently, and a small city the generators can lay out:
#: two tiles by one, level, with the gutter the streets stage reads bound.
_CITY_VALUES = {
    "driving_side": "right",
    "city_extent_x_mm": 256_000,
    "city_extent_y_mm": 128_000,
    "terrain_relief_mm": 0,
    "block_length_mm": 60_000,
    "block_depth_mm": 40_000,
    "gutter_width_mm": 300,
    "front_setback_mm": 0,
    "memory_precinct_lots": 1,
}
_CITY_BINDINGS = (CascadeBinding.of("city", _CITY_VALUES),)
#: What generating each registered grammar needs besides a seed and a subject.
_BINDINGS = {"box": (), "city": _CITY_BINDINGS}


def _stage_for(kind: str):
    return _STAGES_BY_ID[_STAGE_OF_KIND[kind]]


def _fixture(kind: str, **changes):
    return dataclasses.replace(_FIXTURES[kind], **changes)


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


@dataclasses.dataclass(frozen=True, slots=True)
class _DrawRecord:
    """A probe record: which draw it is, and the value the stage's cursor gave it."""

    RECORD_KIND: ClassVar[str] = "probe.draw"
    RECORD_VERSION: ClassVar[int] = 1

    ordinal: int
    value: int


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
            records = tuple(_DrawRecord(index, cursor.integer(0, 1 << 30)) for index in range(8))
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
import hashlib
import importlib.util
import sys
import exulanica.grammar
from exulanica.canonical import sha256_of_canonical
from exulanica.grammar import CascadeBinding, generate
from exulanica.grammar.catalogs import catalog_digest
from exulanica.grammar.draw import _number
from exulanica.grammar.grammars import builtin_registry
from exulanica.grammar.grammars.city.catalogs import load_city_catalogs
from exulanica.grammar.grammars.city.document import document_bytes

seed, identity, builder_path = sys.argv[1], sys.argv[2], sys.argv[3]
bindings = {"box": (), "city": (CascadeBinding.of("city", {
    "driving_side": "right", "city_extent_x_mm": 256000, "city_extent_y_mm": 128000,
    "terrain_relief_mm": 0, "block_length_mm": 60000, "block_depth_mm": 40000,
    "gutter_width_mm": 300, "front_setback_mm": 0, "memory_precinct_lots": 1,
}),)}
spec = importlib.util.spec_from_file_location("city_v2_fixture_builder", builder_path)
fixture = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = fixture
spec.loader.exec_module(fixture)
registry = builtin_registry()
emitted = {
    "generations": [
        generate(registry.get(key.grammar_id, key.grammar_version), seed=seed,
                 subject_identity=identity, bindings=bindings[key.grammar_id]).payload()
        for key in registry.registered_keys()
    ],
    "draws": {
        domain: [str(_number(seed, domain, ordinal)) for ordinal in range(64)]
        for domain in {"streets.hierarchy", "box.parameters.width_mm", "vitrine.fitout"}
    },
    "catalog_digest": catalog_digest(load_city_catalogs()),
    "fixture_document": hashlib.sha256(document_bytes(fixture.build_document())).hexdigest(),
}
print(exulanica.grammar.__file__)
print(sha256_of_canonical(emitted).hex())
"""


def _emit_in_a_new_process(hash_seed: str) -> str:
    result = subprocess.run(
        [sys.executable, "-c", _EMIT, SEED, IDENTITY, str(BUILDER_PATH)],
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


def _generations() -> list[dict[str, object]]:
    registry = builtin_registry()
    return [
        generate(
            registry.get(key.grammar_id, key.grammar_version),
            seed=SEED,
            subject_identity=IDENTITY,
            bindings=_BINDINGS[key.grammar_id],
        ).payload()
        for key in registry.registered_keys()
    ]


def _emitted_set() -> dict[str, object]:
    return {
        "generations": _generations(),
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
    """Part by part: the generations, then each fixture record's payload on its own.

    Canonical JSON walks the whole value, so a float found inside one part is found inside the
    whole; injecting per part (each receipt, the first emitted record of each kind, each fixture
    record) covers every position of every record shape without copying a generated city once
    per leaf. A record of one kind has the same positions as any other of that kind.
    """
    emitted = _emitted_set()
    first_of_each_kind: dict[str, object] = {}
    for generation in emitted["generations"]:
        for emission in generation["emissions"]:
            for record in emission["fields"]["records"]:
                first_of_each_kind.setdefault(record["kind"], record)
    parts = [
        *(generation["receipt"] for generation in emitted["generations"]),
        *first_of_each_kind.values(),
        *emitted["validator_fixtures"].values(),
    ]
    paths = [(index, path) for index, part in enumerate(parts) for path in _leaf_paths(part)]
    assert len(paths) > 2_000, len(paths)
    for index, path in paths:
        with pytest.raises(CanonicalisationError):
            canonical_json(_inject(parts[index], path, poison))


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


def _node_at(x_mm: int):
    node = _FIXTURES["city.street_node"]
    extent = dataclasses.replace(node.extent, min_x_mm=x_mm, max_x_mm=x_mm)
    return dataclasses.replace(node, x_mm=x_mm, extent=extent)


def test_a_record_integer_a_javascript_reader_would_change_is_refused():
    stage = _stage_for("city.street_node")
    stage.validate(_node_at(MAX_SAFE_INTEGER))
    stage.validate(_node_at(-MAX_SAFE_INTEGER))
    with pytest.raises(InvalidRecordError):
        stage.validate(_node_at(MAX_SAFE_INTEGER + 1))


@pytest.mark.parametrize("value", [True, None, [1], {"a": 1}])
def test_a_record_value_that_is_not_an_int_str_tuple_or_record_is_refused(value):
    with pytest.raises(InvalidRecordError):
        record_payload(_fixture("city.street_node", x_mm=value))


# ---------------------------------------------------------------------------------------------
# The stage skeletons

_CITY_STAGE_IDS = (
    "terrain",
    "districts",
    "streets",
    "parcels",
    "massing",
    "facade",
    "streetlife",
    "vitrine",
    "premises",
    "material",
    "tile",
)


def test_the_city_declares_the_eleven_stages_in_order_each_versioned():
    assert tuple(stage.stage_id for stage in CITY_STAGES) == _CITY_STAGE_IDS
    assert all(
        type(stage.stage_version) is int and stage.stage_version >= 1 for stage in CITY_STAGES
    )


def test_only_city_version_2_is_registered():
    keys = [(key.grammar_id, key.grammar_version) for key in builtin_registry().registered_keys()]
    assert keys == [("box", 1), ("city", 2)]


def test_a_city_stage_with_a_generator_emits_records_and_every_other_says_it_has_none():
    city = builtin_registry().get("city", 2)
    generation = generate(city, seed=SEED, subject_identity=IDENTITY, bindings=_CITY_BINDINGS)
    assert [emission.stage_id for emission in generation.emissions] == list(_CITY_STAGE_IDS)
    for stage, emission in zip(CITY_STAGES, generation.emissions, strict=True):
        if isinstance(stage, UnimplementedStage):
            assert emission.status == "not_implemented"
            assert emission.records == ()
            assert "no generator" in emission.reason
        else:
            assert emission.status == "emitted"
            assert emission.records
            assert emission.reason == ""
    assert generation.receipt.declared_semantics == DeclaredSemantics(
        "city", ("render_batch", "collision_proxy", "nav_envelope", "pick_geometry")
    )
    parameters = generation.receipt.parameters
    assert parameters.values == tuple(sorted(_CITY_VALUES.items()))
    sources = dict(parameters.sources)
    for name in _CITY_VALUES:
        assert sources.pop(name) == "city"
    assert len(sources) == 76 - len(_CITY_VALUES)
    assert set(sources.values()) == {"derive"}


def test_a_city_is_refused_when_nothing_states_the_side_of_the_road():
    with pytest.raises(InvalidParameterError):
        generate(builtin_registry().get("city", 2), seed=SEED, subject_identity=IDENTITY)


def test_every_city_stage_has_a_validator_for_a_fixture():
    covered = {_stage_for(name).stage_id for name in _FIXTURES}
    assert covered == set(_CITY_STAGE_IDS)
    assert set(_FIXTURES) == set(_STAGE_OF_KIND)


def test_an_unimplemented_stage_cannot_emit_records_and_cannot_stay_silent():
    node = _FIXTURES["city.street_node"]
    with pytest.raises(InvalidRecordError):
        StageEmission("streets", 2, "not_implemented", "none yet", (node,))
    with pytest.raises(InvalidRecordError):
        StageEmission("streets", 2, "not_implemented", "", ())
    with pytest.raises(InvalidRecordError):
        StageEmission("streets", 2, "emitted", "a reason for an emitted stage", ())


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
    fields = record_payload(_FIXTURES["city.facade"])["fields"]
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
        ("city.curb_edge", {"kerb_height_mm": 99}),
        ("city.curb_edge", {"kerb_height_mm": 181}),
        ("city.curb_edge", {"side": "middle"}),
        ("city.street_segment", {"end_node_identity": None}),
        ("city.street_segment", {"centreline_mm": ((20_000, 40_000, 0),)}),
        ("city.street_segment", {"hierarchy": "Primary"}),
        ("city.street_segment", {"length_mm": 39_999}),
        ("city.parcel", {"frontage_mm": 0}),
        ("city.parcel", {"lot_class": "hole"}),
        ("city.parcel", {"boundary_mm": ((0, 0), (1, 0), (0, 0))}),
        ("city.massing", {"storeys": 0}),
        ("city.massing", {"parcel_identity": "not-a-uuid"}),
        ("city.massing", {"ground_storey_height_mm": 3_999}),
        ("city.facade", {"seed": "0" * 63}),
        ("city.facade", {"parameters": ()}),
        ("city.facade", {"output_digest": "A" * 64}),
        ("city.surface_material", {"texture_set_id": ""}),
        ("city.surface_material", {"texture_set_id": "Test_Set"}),
        ("city.surface_material", {"texture_set_id": "a" * 64 + "@1"}),
        ("city.surface_material", {"uv_rotation_urad": 6_283_186}),
        ("city.surface_material", {"soiling_gradient_millionths": 1_000_001}),
        ("city.vitrine", {"depth_mm": 599}),
        ("city.vitrine", {"depth_mm": 1501}),
        ("city.terrain", {"height_mm": (0, 10, 20)}),
        ("city.tile", {"tile_size_mm": 127_999}),
        ("city.tile", {"halo_radius_mm": 0}),
        ("city.tile", {"ownership_rule": "nearest_centre"}),
        ("city.premises", {"sign": "Sign Text"}),
    ],
)
def test_a_record_outside_its_declared_shape_is_refused(name, change):
    with pytest.raises((InvalidRecordError, InvalidParameterError, InvalidSeedError)):
        _stage_for(name).validate(_fixture(name, **change))


def test_a_stage_refuses_a_record_type_it_does_not_declare():
    with pytest.raises(InvalidRecordError):
        _stage_for("city.vitrine").validate(_FIXTURES["city.premises"])


def test_a_material_whose_texture_set_is_not_published_is_refused():
    material = _FIXTURES["city.surface_material"]
    with pytest.raises(UnresolvedReferenceError):
        require_texture_set(material, {})
    require_texture_set(material, read_texture_manifest())


def test_the_tile_digest_moves_with_the_edit_subsequence_and_the_descriptor_pin():
    tile = _FIXTURES["city.tile"]
    moved = dataclasses.replace(tile, edit_delta_digest="3" * 64)
    assert tile_inputs_digest(tile) != tile_inputs_digest(moved)
    assert tile_inputs_digest(tile) == tile_inputs_digest(dataclasses.replace(tile))
    [pin] = tile.grammar_versions
    repinned = dataclasses.replace(
        tile, grammar_versions=(dataclasses.replace(pin, descriptor_sha256="4" * 64),)
    )
    assert tile_inputs_digest(tile) != tile_inputs_digest(repinned)


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


_MISSING = object()


@pytest.mark.parametrize(
    "change",
    [
        {"grammar_id": "other"},
        {"grammar_version": 2},
        {"grammar_version": True},
        {"schema_version": True},
        {"schema_version": 2},
        {"extra": 1},
        {"parameters": _MISSING},
        {"subject_kind": "Box"},
        {"admissible_uses": ["walkable"]},
        {"admissible_uses": ["render_batch", "render_batch"]},
        {"cascade_levels": []},
        {"cascade_levels": ["draw"]},
        {"cascade_levels": ["item", "item"]},
        {"parameters": [{"name": "x_mm", "kind": "integer", "maximum": -1, "when_unset": "draw"}]},
        {"parameters": [{"name": "x_mm", "kind": "integer", "when_unset": "default"}]},
        {"parameters": [{"name": "x_mm", "kind": "integer", "when_unset": "draw", "default": 0}]},
        {"parameters": [{"name": "finish", "kind": "choice", "options": [], "when_unset": "draw"}]},
        {
            "parameters": [{"name": "x_mm", "kind": "integer", "maximum": 1, "when_unset": "draw"}]
            * 2
        },
    ],
)
def test_a_grammar_descriptor_outside_its_shape_is_refused(tmp_path, change):
    """Including any attempt to give a parameter a default value: there is no such thing."""
    source = _PACKAGE / "grammars" / "box.v1.json"
    document = json.loads(source.read_text(encoding="utf-8"))
    for key, value in change.items():
        if value is _MISSING:
            del document[key]
        else:
            document[key] = value
    path = tmp_path / "box.v1.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    box = builtin_registry().get("box", 1)
    with pytest.raises((InvalidRecordError, InvalidParameterError)):
        Grammar.from_descriptor(path, box.stages)


def test_a_grammar_descriptor_must_be_named_for_its_id_and_version(tmp_path):
    box = builtin_registry().get("box", 1)
    source = (_PACKAGE / "grammars" / "box.v1.json").read_text(encoding="utf-8")
    Grammar.from_descriptor(_write_text(tmp_path / "box.v1.json", source), box.stages)
    for name in ("box.json", "box.v2.json", "crate.v1.json", "Box.v1.json"):
        with pytest.raises((InvalidRecordError, CatalogError)):
            Grammar.from_descriptor(_write_text(tmp_path / name, source), box.stages)


def _write_text(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path
