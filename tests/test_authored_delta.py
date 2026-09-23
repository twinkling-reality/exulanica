"""Golden digests for the authored delta of every schema version.

The digest is every stored version's compare-and-swap token, so a change to how the delta is
composed that moved one byte would refuse the next edit on every world that holds that shape.
These digests were computed on the tree before the composition moved out of
``exulanica.world.objects`` and must be identical after: one per schema version and one per
source selection, including a version 3 that holds point maps and no environment instances.
"""

from __future__ import annotations

import dataclasses
import inspect

import pytest
from exulanica.canonical import canonical_json
from exulanica.world.authored_delta import (
    DELTA_SECTIONS,
    AlternateVersion,
    canonical_delta_document,
    delta_sha256,
    version_delta_sha256,
)
from exulanica.world.edit_kinds import EditSubject

from authored_delta_fixtures import DELTAS

#: The order the fixtures list their sections in.
KEYS = ("objects", "element_overrides", "environment_instances", "point_map_instances")

GOLDEN = {
    "empty": ("b42557ee1fc8f83170fd24e88748dcbbcf5879fbc45f02df62b6c298b420f8fa", 1),
    "v1": ("a9cb68db4bb25f78aeaaff1e87185d16ba4901a450f8d5c57b19710372f2b758", 1),
    "v2-whole-asset": ("cbf857c526653688a8c9eceb8c183a64719595d67cf2d6b527f47446ccda67c4", 2),
    "v2-feature": ("81c9ff7fb16600034ddfea8e4722c1d412ca5619bd6cbb278393dbcc68affb83", 2),
    "v3-point-maps-only": ("1901b0a7634d4e35b391a0ce83d4fe5eaa5ceb81e940a5f536c860b3bcfb3ec1", 3),
    "v3-with-environments": (
        "9bd86fdf1f1da5ec369912bc1653b5182b96ef7c3f96e70871bf6ae338b70049",
        3,
    ),
}


def _sections(name):
    return dict(zip(KEYS, DELTAS[name], strict=True))


def _document(name):
    return canonical_delta_document(**_sections(name))


def _digest(name):
    return delta_sha256(**_sections(name))


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_every_schema_version_digests_to_its_golden(name):
    digest, schema_version = GOLDEN[name]
    assert _digest(name) == digest
    assert _document(name)["schema_version"] == schema_version


def test_an_empty_section_is_omitted_rather_than_written_empty():
    """Load-bearing: an empty section written out would move every existing world's token."""
    assert canonical_json(_document("empty")) == (
        b'{"element_overrides":[],"objects":[],"schema_version":1}'
    )
    assert "environment_instances" not in _document("v3-point-maps-only")
    assert "point_map_instances" not in _document("v2-feature")


def test_each_section_is_sorted_by_its_subject_id_whatever_order_it_arrives_in():
    reversed_sections = {
        key: values[::-1] for key, values in _sections("v3-with-environments").items()
    }
    assert delta_sha256(**reversed_sections) == GOLDEN["v3-with-environments"][0]
    document = _document("v3-with-environments")
    assert [o["object_id"] for o in document["objects"]] == ["object:bench", "object:lantern"]
    assert [o["element_id"] for o in document["element_overrides"]] == [
        "element:region-a:root",
        "element:region-b:root",
    ]
    assert [i["instance_id"] for i in document["environment_instances"]] == [
        "environment:building",
        "environment:corridor",
    ]


# -- the sections are required, and there is one for every kind ----------------------------------


@pytest.mark.parametrize("missing", KEYS)
def test_a_caller_that_leaves_out_a_section_fails_at_the_call(missing):
    """The trap this module removes: an empty default digested less than the world held."""
    sections = _sections("v3-with-environments")
    del sections[missing]
    for compose in (canonical_delta_document, delta_sha256):
        with pytest.raises(TypeError, match=missing):
            compose(**sections)


def test_the_sections_cannot_be_passed_by_position():
    for compose in (canonical_delta_document, delta_sha256):
        parameters = inspect.signature(compose).parameters.values()
        assert {p.kind for p in parameters} == {inspect.Parameter.KEYWORD_ONLY}
        assert all(p.default is inspect.Parameter.empty for p in parameters)
        assert [p.name for p in parameters] == [section.key for section in DELTA_SECTIONS]


def test_every_edit_subject_has_one_delta_section():
    assert [section.subject for section in DELTA_SECTIONS] == list(EditSubject)


def test_every_section_field_of_a_version_is_a_delta_section():
    """A field holding a new kind's instances without a section would be dropped from the token.

    ``edits`` is the one tuple field that is not authored state: it is the log, and the digest
    deliberately covers what the log produced rather than the log itself.
    """
    sequences = {
        field.name
        for field in dataclasses.fields(AlternateVersion)
        if field.default == () and field.name != "edits"
    }
    assert sequences == {section.key for section in DELTA_SECTIONS}


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_a_whole_version_digests_every_section_it_holds(name):
    sections = _sections(name)
    version = AlternateVersion(
        version_id=None,
        world_id="atlas:default",
        source_snapshot_id=None,
        parent_version_id=None,
        title="Golden",
        style_version_id=None,
        state_sha256="",
        edit_seq=0,
        source_invalidated=False,
        created_by=None,
        created_at="2026-09-23T00:00:00+00:00",
        **sections,
    )
    assert version_delta_sha256(version) == GOLDEN[name][0]
