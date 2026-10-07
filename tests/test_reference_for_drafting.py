"""A drafter's notes from a finished reference request, on a migrated database (migration 0148).

What is checked is what a drafter is promised: the caller's own finished request made for the
drafter's purpose gives the quoted block and a provenance that names the notes without their text;
anything else is a named refusal, and another person's request reads as one that does not exist.
"""

from __future__ import annotations

import json
import uuid

import pytest
from exulanica.references import store
from exulanica.references.bundle import BundleNote, BundlePicture
from exulanica.references.for_drafting import (
    NOTES_REFUSALS,
    REFERENCE_BASES,
    NotesRefused,
    notes_for_draft,
)

from reference_fixtures import (
    REFERENCE_ACTOR,
    WEB_NOTES,
    WEB_NOTES_BLOCK,
    finished_reference,
    queued_reference,
    scripted_bundle,
)

pytestmark = pytest.mark.postgres

STRANGER = uuid.UUID("5e1f0c2a-7b3d-4e8f-9a01-b2c3d4e5f6ff")


def _refused(connection, workspace_id, reference_id, *, actor=REFERENCE_ACTOR, purpose="kind"):
    with pytest.raises(NotesRefused) as refused:
        notes_for_draft(connection, workspace_id, actor, reference_id, purpose=purpose)
    assert refused.value.detail == NOTES_REFUSALS[refused.value.code]
    return refused.value.code


@pytest.mark.parametrize("status", ["complete", "partial"])
def test_a_finished_request_gives_the_quoted_block_and_names_its_notes_without_their_text(
    repository, status
) -> None:
    connection, workspace_id = repository.connection, repository.workspace_id
    reference_id = finished_reference(connection, workspace_id, status=status)
    notes = notes_for_draft(connection, workspace_id, REFERENCE_ACTOR, reference_id, purpose="kind")
    assert notes.rendered.text == WEB_NOTES_BLOCK
    assert notes.rendered.photographs == frozenset()
    kept = store.read_request(connection, workspace_id, reference_id)
    assert kept is not None and kept.status == status
    assert dict(notes.provenance) == {
        "reference_id": str(reference_id),
        "bundle_sha256": kept.bundle_sha256,
        "notes": 3,
        "basis": ["web_description"],
    }
    written = json.dumps(dict(notes.provenance))
    assert not any(note.text in written for note in WEB_NOTES)
    assert set(notes.provenance["basis"]) <= set(REFERENCE_BASES)


def test_only_the_requester_is_given_the_notes(repository) -> None:
    connection, workspace_id = repository.connection, repository.workspace_id
    reference_id = finished_reference(connection, workspace_id)
    notes_for_draft(connection, workspace_id, REFERENCE_ACTOR, reference_id, purpose="kind")
    assert _refused(connection, workspace_id, reference_id, actor=STRANGER) == "reference_unknown"
    assert _refused(connection, uuid.uuid4(), reference_id) == "reference_unknown"
    assert _refused(connection, workspace_id, uuid.uuid4()) == "reference_unknown"


def test_a_request_without_a_bundle_gives_no_notes(repository) -> None:
    connection, workspace_id = repository.connection, repository.workspace_id
    ended = [
        finished_reference(connection, workspace_id, status=s) for s in ("failed", "cancelled")
    ]
    queued = queued_reference(connection, workspace_id)
    running = queued_reference(connection, workspace_id)
    assert store.claim(connection, workspace_id, worker="test") is not None
    for reference_id in (*ended, queued, running):
        assert _refused(connection, workspace_id, reference_id) == "reference_not_finished"


def test_notes_made_for_another_purpose_are_not_given(repository) -> None:
    connection, workspace_id = repository.connection, repository.workspace_id
    reference_id = finished_reference(connection, workspace_id, purpose="look")
    notes_for_draft(connection, workspace_id, REFERENCE_ACTOR, reference_id, purpose="look")
    code = _refused(connection, workspace_id, reference_id, purpose="kind")
    assert code == "reference_purpose_differs"


def test_a_request_that_kept_no_notes_gives_none(repository) -> None:
    connection, workspace_id = repository.connection, repository.workspace_id
    empty = scripted_bundle(workspace_id, notes=(), missed=("search",))
    reference_id = finished_reference(connection, workspace_id, bundle=empty, status="partial")
    assert _refused(connection, workspace_id, reference_id) == "reference_has_no_notes"


def test_the_provenance_counts_only_the_notes_the_block_holds(repository) -> None:
    connection, workspace_id = repository.connection, repository.workspace_id
    wide = BundleNote("buildings", "ü" * 80, "web_description", None)
    bundle = scripted_bundle(workspace_id, notes=(wide,) * 24)
    reference_id = finished_reference(connection, workspace_id, bundle=bundle)
    notes = notes_for_draft(connection, workspace_id, REFERENCE_ACTOR, reference_id, purpose="kind")
    assert notes.rendered.cut > 0
    assert notes.provenance["notes"] == notes.rendered.used == 24 - notes.rendered.cut


def test_a_drafter_takes_web_notes_only_unless_it_names_picture_notes(repository) -> None:
    connection, workspace_id = repository.connection, repository.workspace_id
    picture = uuid.UUID("5e1f0c2a-7b3d-4e8f-9a01-b2c3d4e5f6a1")
    seen = BundleNote("buildings", "blue painted doors", "own_picture", picture)
    bundle = scripted_bundle(
        workspace_id,
        notes=(*WEB_NOTES, seen),
        pictures=(
            BundlePicture(
                picture,
                (uuid.UUID("5e1f0c2a-7b3d-4e8f-9a01-b2c3d4e5f6a2"),),
                ("nebius_token_factory", "reference_vision", "openbmb/MiniCPM-V-4_5"),
            ),
        ),
    )
    reference_id = finished_reference(connection, workspace_id, bundle=bundle)
    web = notes_for_draft(connection, workspace_id, REFERENCE_ACTOR, reference_id, purpose="kind")
    assert web.rendered.text == WEB_NOTES_BLOCK
    assert web.rendered.photographs == frozenset()
    assert (web.provenance["notes"], web.provenance["basis"]) == (3, ["web_description"])
    both = notes_for_draft(
        connection,
        workspace_id,
        REFERENCE_ACTOR,
        reference_id,
        purpose="kind",
        bases=REFERENCE_BASES,
    )
    assert both.rendered.photographs == frozenset({picture})
    assert (both.provenance["notes"], both.provenance["basis"]) == (
        4,
        ["web_description", "own_picture"],
    )
