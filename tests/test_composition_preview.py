"""The composition transport, and the reason vocabulary the contract documents.

No database here. What the server decides from stored rows and bytes is covered by
``test_composition_authority_postgres.py``. This file holds the request shape, which is the only
place a readiness claim could enter, and checks that the documented reasons are the reasons the
code can report.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest
from exulanica.api.routes.world import CompositionApplyBody, CompositionPreviewBody
from exulanica.world import composition_preview
from exulanica.world.composition_preview import BLOCKED_REASONS
from exulanica.world.style_structure import (
    CompatibilityIntent,
    StyleStructureFacts,
    classify_structure_style_compatibility,
)
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
BASE = "c" * 64
TRANSFORM = {"x_mm": 0, "y_mm": 0, "z_mm": 0, "yaw_microradians": 0, "scale_milli": 1_000}
ANCHOR = {"frame_name": "nyc-grid", "coordinate_scale": 1000, "coordinates": [10, 20, 0]}
REVIEWED = {"kind": "reviewed_asset", "asset_key": "cc0.marker-cube"}
WHOLE = {
    "kind": "environment_admission",
    "admission_id": str(uuid.uuid4()),
    "render_asset_id": str(uuid.uuid4()),
    "publication_id": None,
    "selection": {"kind": "whole_asset"},
}
ATTACHMENT = {
    "kind": "source_attachment",
    "entry_id": str(uuid.uuid4()),
    "attachment_id": str(uuid.uuid4()),
}


def placement(**extra):
    return {
        "subject_id": "object:lantern",
        "region_id": "region-a",
        "transform": TRANSFORM,
        "origin_role": "fictional",
        **extra,
    }


def body(source, place=None, **extra):
    return {"base_state_sha256": BASE, "source": source, "placement": place, **extra}


def _property_names(schema: dict) -> set[str]:
    names: set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            names.update(node.get("properties", {}))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)
    return names


REFERENCE_AND_INTENT = {
    "base_state_sha256",
    "source",
    "placement",
    "kind",
    "asset_key",
    "admission_id",
    "render_asset_id",
    "publication_id",
    "selection",
    "feature_id",
    "render_batch_id",
    "entry_id",
    "attachment_id",
    "subject_id",
    "region_id",
    "transform",
    "x_mm",
    "y_mm",
    "z_mm",
    "yaw_microradians",
    "scale_milli",
    "origin_role",
    "behaviour",
    "behaviour_key",
    "behaviour_version",
    "parameters",
    "source_anchor",
    "frame_name",
    "coordinate_scale",
    "coordinates",
}
SAVED_ENTRY = {
    "saved_entry",
    "entry_id",
    "base_revision",
    "authored_state_sha256",
    "authored_edit_seq",
}


def test_the_request_carries_references_and_intent_and_nothing_else():
    """Every field either body can carry, named. A readiness field would have to appear here."""
    preview_names = _property_names(CompositionPreviewBody.model_json_schema())
    apply_names = _property_names(CompositionApplyBody.model_json_schema())
    assert preview_names == REFERENCE_AND_INTENT
    assert apply_names == REFERENCE_AND_INTENT | SAVED_ENTRY


def test_every_object_in_either_body_refuses_unknown_fields():
    for model in (CompositionPreviewBody, CompositionApplyBody):
        schema = model.model_json_schema()
        objects = [schema, *schema.get("$defs", {}).values()]
        closed = [node for node in objects if "properties" in node]
        assert len(closed) >= 8, [node.get("title") for node in closed]
        for node in closed:
            assert node.get("additionalProperties") is False, node.get("title")


def test_the_facts_body_is_refused_whole():
    legacy = {
        "source": {"kind": "reviewed_asset", "source_id": "cc0.marker-cube"},
        "state_sha256": BASE,
        "edit_seq": 0,
        "facts": {"intent": "classify", "world_id": "world:authored:x"},
        "representation": {"present_content_digests": [BASE], "produced": True},
        "resource": {"source_withdrawn": False},
        "existing_subject_ids": [],
        "subject_id": "object:lantern",
    }
    for model in (CompositionPreviewBody, CompositionApplyBody):
        with pytest.raises(ValidationError):
            model.model_validate(legacy)


def test_a_selection_names_its_publication_exactly_when_it_is_a_feature():
    feature = {"kind": "feature", "feature_id": "a" * 32, "render_batch_id": 7}
    with pytest.raises(ValidationError, match="names its publication"):
        CompositionPreviewBody.model_validate(body(WHOLE | {"selection": feature}))
    with pytest.raises(ValidationError, match="names its publication"):
        CompositionPreviewBody.model_validate(body(WHOLE | {"publication_id": str(uuid.uuid4())}))
    accepted = CompositionPreviewBody.model_validate(
        body(WHOLE | {"selection": feature, "publication_id": str(uuid.uuid4())})
    )
    assert accepted.domain().source.selection.kind == "feature"


@pytest.mark.parametrize(
    ("source", "place", "accepted"),
    [
        (REVIEWED, placement(), True),
        (REVIEWED, placement(behaviour=None), True),
        (REVIEWED, placement(source_anchor=ANCHOR), False),
        (WHOLE, placement(source_anchor=ANCHOR), True),
        (WHOLE, placement(), False),
        (
            WHOLE,
            placement(
                source_anchor=ANCHOR,
                behaviour={"behaviour_key": "k", "behaviour_version": 1, "parameters": {}},
            ),
            False,
        ),
        (ATTACHMENT, placement(), True),
        (ATTACHMENT, placement(source_anchor=ANCHOR), False),
    ],
)
def test_a_placement_field_the_source_would_ignore_is_refused(source, place, accepted):
    if accepted:
        CompositionPreviewBody.model_validate(body(source, place))
    else:
        with pytest.raises(ValidationError):
            CompositionPreviewBody.model_validate(body(source, place))


def test_apply_needs_a_placement_and_preview_takes_no_saved_entry():
    with pytest.raises(ValidationError):
        CompositionApplyBody.model_validate(body(REVIEWED))
    binding = {
        "entry_id": str(uuid.uuid4()),
        "base_revision": 1,
        "authored_state_sha256": BASE,
        "authored_edit_seq": 0,
    }
    with pytest.raises(ValidationError):
        CompositionPreviewBody.model_validate(body(REVIEWED, placement(), saved_entry=binding))
    applied = CompositionApplyBody.model_validate(body(REVIEWED, placement(), saved_entry=binding))
    assert applied.saved_entry is not None


def _documented_reasons() -> set[str]:
    text = (ROOT / "docs" / "world-composition-contract.md").read_text(encoding="utf-8")
    section = text.split("## Composition preview and apply", 1)[1].split("\n## ", 1)[0]
    return set(re.findall(r"^\| \d+ \| `([a-z_]+)` \|", section, flags=re.MULTILINE))


def test_the_documented_reasons_are_the_reasons_the_code_can_report():
    documented = _documented_reasons()
    # The parse found the table before anything is compared against it.
    assert len(documented) >= 10
    assert documented == BLOCKED_REASONS

    source = Path(composition_preview.__file__).read_text(encoding="utf-8")
    literal = set(re.findall(r'blocked\(\s*"([a-z_]+)"', source))
    tabled = {
        reason
        for name in dir(composition_preview)
        if name.endswith("_REFUSALS")
        for _kind, reason in getattr(composition_preview, name)
    }
    assert literal and tabled
    assert literal | tabled <= BLOCKED_REASONS

    # Attachment refusals are the classifier's own COMPOSE tokens.
    for expired in (False, True):
        decision = classify_structure_style_compatibility(
            StyleStructureFacts(
                intent=CompatibilityIntent.COMPOSE,
                world_id="world:authored:synthetic",
                attachments_named=True,
                attachments_expired=expired,
            )
        )
        assert decision.outcome == "refuse"
        assert decision.token in BLOCKED_REASONS
