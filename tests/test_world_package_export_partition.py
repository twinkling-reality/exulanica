"""The export plan: an allowlist read from the edit-kind registry and each extension format.

Pure tests of :mod:`exulanica.world_package.export_partition`; the projector's own reading of the
plane and the packages it writes are held by the golden and PostgreSQL tests.
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import pytest
from exulanica.world.authored_delta import DELTA_SECTIONS
from exulanica.world.edit_kinds import EDIT_KINDS, EditKind, EditSubject
from exulanica.world_package import extension_formats, extension_projection
from exulanica.world_package.export_partition import (
    REASON_KIND_NOT_ADMITTED,
    REASON_SECTION_NOT_CARRIED,
    REASON_SOURCE_INVALIDATED,
    PlaneVersion,
    WithheldVersion,
    plan_export,
)
from exulanica.world_package.extension_formats import (
    AUTHORED_WORLD_1_0,
    ENVIRONMENT_INSTANCES_1_0,
    ExtensionFormat,
)
from exulanica.world_package.package import PackageError

ROOT = Path(__file__).resolve().parents[1]
BOTH = [AUTHORED_WORLD_1_0, ENVIRONMENT_INSTANCES_1_0]
AUTHORED = AUTHORED_WORLD_1_0.key
ENVIRONMENTS = ENVIRONMENT_INSTANCES_1_0.key
#: A kind no migration admits, for a registry copy to hold.
COLOUR = EditKind("set_object_colour", EditSubject.OBJECT, "0105_an_object_s_colour_can_change")
ENVIRONMENT = frozenset({"environment_instances"})


def _version(version_id, parent=None, *, kinds=(), subjects=(), sections=(), invalidated=False):
    return PlaneVersion(
        version_id,
        parent,
        source_invalidated=invalidated,
        chain_kinds=frozenset(kinds),
        chain_subjects=frozenset(subjects),
        state_sections=frozenset(sections),
    )


def _lineage_with(kind: str) -> tuple[PlaneVersion, ...]:
    return (
        _version("root", kinds={"add_object", "move_object"}, sections={"objects"}),
        _version("carrying", "root", kinds={"add_object", kind}, sections={"objects"}),
        _version("branch", "carrying", sections={"objects"}),
        _version("sibling", "root", sections={"objects"}),
    )


def test_a_kind_added_to_a_copy_of_the_registry_is_withheld_by_name():
    registry = (*EDIT_KINDS, COLOUR)
    plan = plan_export(_lineage_with(COLOUR.name), BOTH, registry=registry)
    assert plan.exported[AUTHORED] == ("root", "sibling")
    assert plan.exported[ENVIRONMENTS] == ()
    assert plan.withheld[AUTHORED] == (
        WithheldVersion("carrying", REASON_KIND_NOT_ADMITTED, (COLOUR.name,)),
        WithheldVersion("branch", REASON_KIND_NOT_ADMITTED, (COLOUR.name,)),
    )
    assert plan.withheld[ENVIRONMENTS] == ()

    # The control: the same lineage with a kind both formats admit is exported whole.
    control = plan_export(_lineage_with("remove_object"), BOTH, registry=registry)
    assert control.exported[AUTHORED] == ("root", "carrying", "branch", "sibling")
    assert control.withheld[AUTHORED] == ()


def test_the_new_kind_is_exported_once_a_format_admits_it():
    """Fail closed until admitted: the same lineage, judged by a format that names the kind."""
    admitting = dataclasses.replace(
        AUTHORED_WORLD_1_0,
        edit_kinds={
            **AUTHORED_WORLD_1_0.edit_kinds,
            "object": AUTHORED_WORLD_1_0.kinds_changing("object") | {COLOUR.name},
        },
    )
    plan = plan_export(
        _lineage_with(COLOUR.name),
        [admitting, ENVIRONMENT_INSTANCES_1_0],
        registry=(*EDIT_KINDS, COLOUR),
    )
    assert plan.exported[AUTHORED] == ("root", "carrying", "branch", "sibling")
    assert plan.withheld[AUTHORED] == ()


def test_a_kind_the_registry_does_not_hold_is_refused_by_name():
    with pytest.raises(PackageError) as refused:
        plan_export(_lineage_with(COLOUR.name), BOTH)
    assert str(refused.value) == (
        "the edit kind 'set_object_colour' is not registered, so no extension can say whether it "
        "admits it"
    )


def test_a_section_no_format_carries_is_withheld_by_name_with_no_kind_behind_it():
    """A state section is judged even when the chain that wrote it is not in the plane."""
    plan = plan_export((_version("holding", sections={"objects", "point_map_instances"}),), BOTH)
    assert plan.withheld[AUTHORED] == (
        WithheldVersion("holding", REASON_SECTION_NOT_CARRIED, ("point_map_instances",)),
    )


def test_an_undo_counts_with_the_subject_it_reverses():
    """The log's subject columns, not the kind alone: an undo repeats the undone edit's subject."""
    plan = plan_export(
        (_version("undone", kinds={"undo"}, subjects={EditSubject.POINT_MAP_INSTANCE}),),
        BOTH,
    )
    assert plan.withheld[AUTHORED] == (
        WithheldVersion("undone", REASON_SECTION_NOT_CARRIED, ("point_map_instances",)),
    )


def test_an_invalidated_source_is_the_reason_before_any_kind():
    plan = plan_export((_version("gone", kinds={"add_point_map"}, invalidated=True),), BOTH)
    assert plan.withheld[AUTHORED] == (WithheldVersion("gone", REASON_SOURCE_INVALIDATED, ()),)


def test_authored_world_alone_counts_what_the_environment_family_withholds():
    plan = plan_export(
        (
            _version(
                "moving plaza",
                kinds={"add_environment", "add_object", "set_object_behaviour"},
                sections=ENVIRONMENT | {"objects"},
            ),
        ),
        [AUTHORED_WORLD_1_0],
    )
    assert plan.exported == {AUTHORED: ()}
    assert [w.version_id for w in plan.withheld[AUTHORED]] == ["moving plaza"]
    assert plan.unrequested == {}


def test_environment_instances_alone_leaves_authored_versions_out_of_scope():
    plan = plan_export(
        (
            _version("kept", sections={"objects"}),
            _version("withheld", kinds={"set_object_behaviour"}),
        ),
        [ENVIRONMENT_INSTANCES_1_0],
    )
    assert plan.exported == {ENVIRONMENTS: ()}
    assert plan.withheld == {ENVIRONMENTS: ()}
    assert plan.unrequested == {}


def test_authored_world_alone_reports_a_kept_environment_version_rather_than_drop_it():
    plan = plan_export(
        (
            _version("parent", sections={"objects"}),
            _version("plaza", "parent", kinds={"add_environment"}, sections=ENVIRONMENT),
        ),
        [AUTHORED_WORLD_1_0],
    )
    assert plan.exported == {AUTHORED: ("parent",)}
    assert plan.unrequested == {ENVIRONMENTS: ("plaza",)}


def test_a_lineage_that_loops_ends():
    plan = plan_export((_version("a", "b"), _version("b", "a")), BOTH)
    assert plan.exported[AUTHORED] == ("a", "b")


def test_every_section_of_the_delta_has_a_table_the_projector_reads():
    migrations = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / "exulanica" / "migrations").glob("[0-9]*.sql"))
    )
    assert set(extension_projection._SECTION_TABLES) == {section.key for section in DELTA_SECTIONS}
    for table in extension_projection._SECTION_TABLES.values():
        assert re.search(rf"create table {table} \(", migrations), table


def test_every_format_carries_sections_the_delta_defines():
    keys = {section.key for section in DELTA_SECTIONS}
    for format_ in extension_formats.FORMATS:
        assert format_.sections <= keys, format_.key


def _renamed(format_: ExtensionFormat, **changes) -> ExtensionFormat:
    return dataclasses.replace(format_, **changes)


@pytest.mark.parametrize(
    ("formats", "message"),
    [
        ((AUTHORED_WORLD_1_0, AUTHORED_WORLD_1_0), "share a key"),
        (
            (
                AUTHORED_WORLD_1_0,
                _renamed(AUTHORED_WORLD_1_0, version="1.1", sections=ENVIRONMENT),
                ENVIRONMENT_INSTANCES_1_0,
            ),
            "carries other sections than its family",
        ),
        (
            (
                AUTHORED_WORLD_1_0,
                _renamed(ENVIRONMENT_INSTANCES_1_0, sections=frozenset({"objects", "extra"})),
            ),
            "does not carry every section of the family below it",
        ),
        (
            (
                AUTHORED_WORLD_1_0,
                _renamed(AUTHORED_WORLD_1_0, version="1.1"),
                ENVIRONMENT_INSTANCES_1_0,
            ),
            "define different versions",
        ),
    ],
)
def test_broken_format_data_stops_the_import(formats, message):
    """The positive control for the rules the plan relies on, checked when the module loads."""
    with pytest.raises(ValueError, match=message):
        extension_formats._checked(formats)
    extension_formats._checked(extension_formats.FORMATS)
