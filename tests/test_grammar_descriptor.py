"""Grammar descriptors: pinned by digest per version, and schema 2 held to its contract.

A tile pins each grammar by the SHA-256 of its descriptor file (``GrammarPin``), so a descriptor
edited without a version bump would change every tile key built on it and nothing else would
notice. The digest of every shipped descriptor is written here, per version: editing one fails
this file, which is the prompt to bump the version instead.

Schema 2 states the frame, the stages and the record kinds each validates, declared parameters
and one representation contract per admitted projection. Each refusal below edits one thing in a
copy of ``city.v2.json`` and loads it against the city's real stages.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from exulanica.grammar.contract import (
    PROJECTION_OWN_USE,
    PROJECTION_USES,
    REFUSED_USES,
    Grammar,
    ParameterSurface,
)
from exulanica.grammar.errors import InvalidParameterError, InvalidRecordError
from exulanica.grammar.grammars import builtin_registry
from exulanica.grammar.grammars.box import BOX_GRAMMAR
from exulanica.grammar.grammars.city import CITY_GRAMMAR, CITY_SHAPES, CITY_STAGES
from exulanica.grammar.grammars.city.descriptor import (
    CITY_DESCRIPTOR_PATH,
    CITY_SURFACE,
    CITY_V1_DESCRIPTOR_PATH,
    CITY_V1_SURFACE,
)

ROOT = Path(__file__).resolve().parents[1]
_GRAMMARS = ROOT / "exulanica" / "grammar" / "grammars"

#: The SHA-256 of every descriptor file this repository ships, by grammar and version. A changed
#: digest is a changed grammar: bump the version rather than this line.
DESCRIPTOR_SHA256 = {
    ("box", 1): "2c2c8481c90e3a33021a014e7a7d5ece016b34fbbaed779a76979f8793d08e46",
    ("city", 1): "1e580ada17333e886ad1067e65585ebd7014006749ba4f84a26ae0f9f673d273",
    ("city", 2): "b5527d2cc9519c07fdca512c46ea686ff98b209a0af05e1f654d80dce0109a0e",
}


def _descriptor_files() -> dict[tuple[str, int], Path]:
    found = {}
    for path in sorted(_GRAMMARS.rglob("*.v*.json")):
        stem, _, rest = path.name.partition(".v")
        if "-migration" in stem:
            continue
        found[(stem, int(rest.removesuffix(".json")))] = path
    return found


def test_every_shipped_descriptor_is_pinned_by_its_digest():
    files = _descriptor_files()
    assert set(files) == set(DESCRIPTOR_SHA256)
    for key, path in files.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == DESCRIPTOR_SHA256[key], key
    assert files[("city", 2)] == CITY_DESCRIPTOR_PATH
    assert files[("city", 1)] == CITY_V1_DESCRIPTOR_PATH


def test_the_registered_grammars_are_exactly_the_pinned_current_versions():
    keys = {(key.grammar_id, key.grammar_version) for key in builtin_registry().registered_keys()}
    assert keys == {("box", 1), ("city", 2)}
    assert (BOX_GRAMMAR.descriptor_schema, CITY_GRAMMAR.descriptor_schema) == (1, 2)


def test_the_grammar_and_the_parameter_surface_read_the_descriptor_alike():
    assert CITY_SURFACE.key == CITY_GRAMMAR.key
    assert CITY_SURFACE.parameters == CITY_GRAMMAR.parameters
    assert CITY_SURFACE.cascade == CITY_GRAMMAR.cascade
    assert CITY_SURFACE.descriptor_schema == 2
    assert (CITY_V1_SURFACE.descriptor_schema, CITY_V1_SURFACE.parameters.parameters) == (1, ())
    assert CITY_V1_SURFACE.cascade == CITY_SURFACE.cascade


def test_the_city_descriptor_states_its_frame_stages_parameters_and_contracts():
    assert CITY_GRAMMAR.frame is not None
    assert (CITY_GRAMMAR.frame.name, CITY_GRAMMAR.frame.metric_class) == (
        "city_local",
        "metric_authored",
    )
    assert CITY_GRAMMAR.cascade.levels == ("city", "district", "block", "lot", "building", "face")
    declared = {kind for stage in CITY_GRAMMAR.declared_stages for kind, _ in stage.records}
    assert declared == {shape.kind for shape in CITY_SHAPES}
    assert len(CITY_GRAMMAR.parameters.parameters) == 69
    assert {spec.when_unset for spec in CITY_GRAMMAR.parameters.parameters} == {
        "derive",
        "required",
    }
    assert [
        spec.name for spec in CITY_GRAMMAR.parameters.parameters if spec.when_unset == "required"
    ] == ["driving_side"]
    assert CITY_GRAMMAR.semantics.admissible_uses == (
        "render_batch",
        "collision_proxy",
        "nav_envelope",
        "pick_geometry",
    )


@pytest.mark.parametrize("projection", CITY_GRAMMAR.semantics.admissible_uses)
def test_each_contract_admits_its_own_use_and_evaluation_and_refuses_the_rest(projection):
    contract = CITY_GRAMMAR.projection(projection)
    verdicts = {row.use: row.verdict for row in contract.uses}
    admitted = {use for use, verdict in verdicts.items() if verdict == "admitted"}
    assert admitted == {PROJECTION_OWN_USE[projection], "evaluation"}
    assert tuple(verdicts) == PROJECTION_USES
    preserved = {row.property for row in contract.preserved}
    unsupported = {row.property for row in contract.unsupported}
    assert preserved and unsupported and not preserved & unsupported
    assert "subject_identity" in preserved
    assert contract.dependencies == ()


def test_no_contract_can_admit_a_personal_world_or_a_citation():
    assert set(REFUSED_USES) == {"personal_world", "citation"}


# -------------------------------------------------------------------------------------------
# Schema 2 refusals


def _city_document() -> dict[str, Any]:
    return json.loads(CITY_DESCRIPTOR_PATH.read_text(encoding="utf-8"))


def _load(tmp_path: Path, document: dict[str, Any]) -> Grammar:
    path = tmp_path / "city.v2.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return Grammar.from_descriptor(path, CITY_STAGES)


def test_an_unchanged_copy_of_the_city_descriptor_loads(tmp_path):
    grammar = _load(tmp_path, _city_document())
    assert grammar.parameters == CITY_GRAMMAR.parameters
    assert grammar.projections == CITY_GRAMMAR.projections


def _contract(document: dict[str, Any], projection: str) -> dict[str, Any]:
    return next(item for item in document["projections"] if item["projection"] == projection)


def _use(document: dict[str, Any], projection: str, use: str) -> dict[str, Any]:
    return next(row for row in _contract(document, projection)["uses"] if row["use"] == use)


def _parameter(document: dict[str, Any], name: str) -> dict[str, Any]:
    return next(item for item in document["parameters"] if item["name"] == name)


def _admit(projection: str, use: str) -> Callable[[dict[str, Any]], None]:
    def change(document: dict[str, Any]) -> None:
        _use(document, projection, use)["verdict"] = "admitted"

    change.__name__ = f"_{projection}_admits_{use}"
    return change


def _drop_contract(document: dict[str, Any]) -> None:
    document["projections"] = [
        item for item in document["projections"] if item["projection"] != "pick_geometry"
    ]


def _extra_contract(document: dict[str, Any]) -> None:
    document["admissible_uses"] = document["admissible_uses"][:-1]


def _swap_stages(document: dict[str, Any]) -> None:
    stages = document["stages"]
    stages[0], stages[1] = stages[1], stages[0]


def _stage_version(document: dict[str, Any]) -> None:
    document["stages"][0]["stage_version"] = 3


def _drop_stage(document: dict[str, Any]) -> None:
    document["stages"] = document["stages"][:-1]


def _record_kind_elsewhere(document: dict[str, Any]) -> None:
    streets = next(stage for stage in document["stages"] if stage["stage_id"] == "streets")
    moved = streets["records"].pop()
    document["stages"][0]["records"].append(moved)


def _record_version(document: dict[str, Any]) -> None:
    document["stages"][0]["records"][0]["version"] = 1


def _record_kind_unknown(document: dict[str, Any]) -> None:
    document["stages"][0]["records"].append({"kind": "city.hedge", "version": 1})


def _level_unknown(document: dict[str, Any]) -> None:
    _parameter(document, "bay_pitch_mm")["level"] = "storey"


def _stage_unknown(document: dict[str, Any]) -> None:
    _parameter(document, "bay_pitch_mm")["stage"] = "bays"


def _derive_without_stage(document: dict[str, Any]) -> None:
    _parameter(document, "bay_pitch_mm")["stage"] = ""


def _basis_missing(document: dict[str, Any]) -> None:
    _parameter(document, "bay_pitch_mm")["basis"] = ""


def _choice_in_millimetres(document: dict[str, Any]) -> None:
    _parameter(document, "typology")["unit"] = "mm"


def _integer_with_vocabulary(document: dict[str, Any]) -> None:
    _parameter(document, "bay_pitch_mm")["vocabulary"] = "typology"


def _parameter_default(document: dict[str, Any]) -> None:
    _parameter(document, "bay_pitch_mm")["default"] = 2_800


def _measured_frame(document: dict[str, Any]) -> None:
    document["frame"]["metric_class"] = "metric_measured"


def _frame_in_metres(document: dict[str, Any]) -> None:
    document["frame"]["units"] = "m"


def _frame_missing(document: dict[str, Any]) -> None:
    del document["frame"]


def _own_use_refused(document: dict[str, Any]) -> None:
    _use(document, "render_batch", "display")["verdict"] = "refused"


def _uses_reordered(document: dict[str, Any]) -> None:
    uses = _contract(document, "render_batch")["uses"]
    uses[0], uses[1] = uses[1], uses[0]


def _use_missing(document: dict[str, Any]) -> None:
    _contract(document, "render_batch")["uses"].pop()


def _dependency(document: dict[str, Any]) -> None:
    _contract(document, "render_batch")["dependencies"] = ["consent"]


def _property_both_ways(document: dict[str, Any]) -> None:
    contract = _contract(document, "render_batch")
    contract["unsupported"].append(copy.deepcopy(contract["preserved"][0]))


def _nothing_unsupported(document: dict[str, Any]) -> None:
    _contract(document, "render_batch")["unsupported"] = []


def _time_scope(document: dict[str, Any]) -> None:
    _contract(document, "render_batch")["time_scope"] = "dated"


@pytest.mark.parametrize(
    "change",
    [
        _admit("render_batch", "personal_world"),
        _admit("collision_proxy", "citation"),
        _drop_contract,
        _extra_contract,
        _swap_stages,
        _stage_version,
        _drop_stage,
        _record_kind_elsewhere,
        _record_version,
        _record_kind_unknown,
        _level_unknown,
        _stage_unknown,
        _derive_without_stage,
        _basis_missing,
        _choice_in_millimetres,
        _integer_with_vocabulary,
        _parameter_default,
        _measured_frame,
        _frame_in_metres,
        _frame_missing,
        _own_use_refused,
        _uses_reordered,
        _use_missing,
        _dependency,
        _property_both_ways,
        _nothing_unsupported,
        _time_scope,
    ],
    ids=lambda change: getattr(change, "__name__", "admit").lstrip("_"),
)
def test_a_schema_2_descriptor_outside_its_contract_is_refused(tmp_path, change):
    document = _city_document()
    change(document)
    with pytest.raises((InvalidRecordError, InvalidParameterError)):
        _load(tmp_path, document)


@pytest.mark.parametrize("use", ["personal_world", "citation"])
def test_the_refusal_of_a_forbidden_use_names_why(tmp_path, use):
    document = _city_document()
    _use(document, "nav_envelope", use)["verdict"] = "admitted"
    with pytest.raises(InvalidRecordError, match=REFUSED_USES[use].split(" (")[0]):
        _load(tmp_path, document)


def test_the_parameter_surface_refuses_what_the_grammar_refuses_without_stage_code(tmp_path):
    for change in (_level_unknown, _parameter_default, _basis_missing):
        document = _city_document()
        change(document)
        path = tmp_path / "city.v2.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        with pytest.raises((InvalidRecordError, InvalidParameterError)):
            ParameterSurface.read(path)


def test_a_schema_1_derived_parameter_must_name_its_stage(tmp_path):
    path = tmp_path / "probe.v1.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "grammar_id": "probe",
                "grammar_version": 1,
                "subject_kind": "probe",
                "admissible_uses": [],
                "cascade_levels": ["probe"],
                "parameters": [
                    {
                        "name": "size_mm",
                        "kind": "integer",
                        "minimum": 1,
                        "maximum": 2,
                        "when_unset": "derive",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(InvalidParameterError, match="names its stage"):
        ParameterSurface.read(path)
