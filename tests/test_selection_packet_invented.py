"""A generated subject reaches a model under its own truth class, not as ``"other"``.

The five wire keys a consumer must name before it can draw are ``recorded``, ``interpreted``,
``authored``, ``invented`` and ``simulated``. ``build_content_packet`` is the one place a model
reads the class of a content result, so a hole in its map is a hole in the plane typing exactly
where it matters.

No database row is involved, deliberately. Nothing in the schema emits ``origin_kind =
'invented'`` yet, and inventing such a row here would be a fabricated fact in a migration this
test does not own. ``SelectedContent`` is constructed directly.
"""

from __future__ import annotations

import uuid

import pytest
from exulanica.selection.executor import SelectedContent, SelectionResult
from exulanica.selection.packet import build_content_packet
from exulanica.selection.plan import Intent

PLACE = uuid.UUID("3f1c6e2a-8d4b-4c1e-9a57-2b6d0e8f4a13")

#: The pinned string. Changing it is a wire change, and this test is where that is noticed.
INVENTED_TRUTH_CLASS = "invented_world"


def _content(origin_kind: str) -> SelectedContent:
    return SelectedContent(
        result_kind=f"{origin_kind}_fixture",
        origin_kind=origin_kind,
        content_kind="content",
        authored_role=None,
        place_relationship="admitted_for",
        match_reason="fixture",
        memory_place_entity_id=PLACE,
        canonical_place_id=None,
        world_id=None,
        version_id=None,
        source_id=f"source:{origin_kind}",
        lineage_ids=(f"lineage:{origin_kind}",),
        label=None,
        availability="available",
        personal_visit_evidence=False,
    )


def _classes(*origin_kinds: str) -> list[str]:
    content = tuple(_content(kind) for kind in origin_kinds)
    packet = build_content_packet(
        SelectionResult(
            intent=Intent.CONTENT,
            captures=(),
            entities=(),
            total_matched=len(content),
            includes_proposals=False,
            content=content,
        )
    )
    return [item.truth_class for item in packet.items]


def test_invented_content_has_the_pinned_truth_class():
    assert _classes("invented") == [INVENTED_TRUTH_CLASS]


def test_the_invented_class_is_distinct_from_every_other_class():
    classes = _classes("personal", "imported", "authored", "invented", "simulated")
    assert len(set(classes)) == len(classes), classes
    assert "other" not in classes


@pytest.mark.parametrize("origin_kind", ["", "Invented", "generated", "synthetic", "unknown"])
def test_an_origin_the_map_does_not_know_is_still_other(origin_kind):
    """The fallback keeps meaning "I do not know". It is not dead code, and it is not invented."""
    assert _classes(origin_kind) == ["other"]
