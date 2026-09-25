"""A world's open appearance previews are read back, so a staged proposal outlives its page.

A preview is held by the server until a person applies or discards it; a page keeps only what it
read. ``WorldStyleRepository.open_previews`` and ``GET /world/styles/previews`` return the world's
previews nobody has closed, newest first, so a page that reloads, or opens the world again after
another, can put a Companion's staged proposal back in front of the person. Read as the runtime
role, which row-level security binds, as the API reads it.
"""

from __future__ import annotations

import uuid

import pytest
from exulanica.db.roles import RUNTIME_ROLE, provision_runtime_role
from exulanica.world import WorldStyleRepository
from exulanica.world.models import ProposalOrigin, ProposalProvenance, StyleProposal, StyleScope
from exulanica.world.repository import OPEN_PREVIEWS_READ

from conftest import scratch_role_database
from test_appearance_proposal_names import SOURCE, world
from test_companion_saved_names import named
from world_support import FIXTURE_WORLD_ID

pytestmark = pytest.mark.postgres

__all__ = ["named", "world"]


def _propose(styles: WorldStyleRepository, *, companion: bool, softness: float):
    current = styles.current()
    reference = current.global_style
    actor = uuid.uuid4()
    return styles.preview(
        StyleProposal(
            proposal_id=uuid.uuid4(),
            provenance=ProposalProvenance(
                ProposalOrigin.COMPANION if companion else ProposalOrigin.SETTINGS,
                actor,
                "companion-utterance:open-previews" if companion else "appearance-panel",
            ),
            scope=StyleScope("global"),
            base_style_version_id=current.version_id,
            base_topology_digest=styles.current_topology_digest(),
            profile=type(reference)(
                reference.profile_id,
                reference.profile_version,
                {**reference.parameters, "horizon-softness": softness},
            ),
            reference_ids=(str(SOURCE),) if companion else (),
            model_id="Qwen/Qwen3-235B-A22B-Instruct-2507" if companion else None,
            prompt_version="proposal-3" if companion else None,
        )
    )


def test_the_open_previews_are_read_back_newest_first_and_closed_ones_are_not(world, spine_schema):
    repository, _, _, _ = world
    styles = WorldStyleRepository(
        repository.connection, repository.workspace_id, world_id=FIXTURE_WORLD_ID
    )
    companion = _propose(styles, companion=True, softness=0.8)
    settings = _propose(styles, companion=False, softness=0.6)
    closed = _propose(styles, companion=True, softness=0.4)
    styles.discard(closed.preview_id, discarded_by=uuid.uuid4())
    repository.connection.commit()
    provision_runtime_role(repository.connection)
    repository.connection.commit()

    with scratch_role_database(spine_schema[1], RUNTIME_ROLE).session(
        repository.workspace_id
    ) as connection:
        found = WorldStyleRepository(
            connection, repository.workspace_id, world_id=FIXTURE_WORLD_ID
        ).open_previews()

    read = [preview for preview, _ in found.readable]
    assert found.unreadable == 0
    assert [p.preview_id for p in read] == [settings.preview_id, companion.preview_id]
    assert read[1].proposal.provenance.origin == "companion"
    assert read[1].proposal.provenance.origin_reference == "companion-utterance:open-previews"
    assert read[1].proposal.reference_ids == (str(SOURCE),)
    assert read[1].candidate.global_style.parameters["horizon-softness"] == 0.8


def test_another_workspace_s_runtime_role_sees_none_of_them(world, spine_schema):
    """Row-level security, not the query's own filter: read with no workspace in the statement."""
    repository, _, _, _ = world
    styles = WorldStyleRepository(
        repository.connection, repository.workspace_id, world_id=FIXTURE_WORLD_ID
    )
    _propose(styles, companion=True, softness=0.8)
    repository.connection.commit()
    provision_runtime_role(repository.connection)
    repository.connection.commit()
    count = "select count(*) as n from world_style_preview where world_id=%s"

    with scratch_role_database(spine_schema[1], RUNTIME_ROLE).session(
        repository.workspace_id
    ) as owner:
        assert owner.execute(count, (FIXTURE_WORLD_ID,)).fetchone()["n"] == 1, "positive control"
    with scratch_role_database(spine_schema[1], RUNTIME_ROLE).session(uuid.uuid4()) as stranger:
        assert stranger.execute(count, (FIXTURE_WORLD_ID,)).fetchone()["n"] == 0


def test_a_row_this_code_cannot_read_is_counted_and_skipped_not_refused(world, spine_schema):
    """A preview from before the recipe-binding contract (0023) never stops a world opening."""
    repository, _, _, _ = world
    styles = WorldStyleRepository(
        repository.connection, repository.workspace_id, world_id=FIXTURE_WORLD_ID
    )
    kept = _propose(styles, companion=True, softness=0.8)
    legacy = _propose(styles, companion=True, softness=0.6)
    # A candidate is immutable to everyone, so the row an older version wrote is made here with
    # the guard off for this one statement, as the schema owner, and the guard put straight back.
    guard = "tg_world_style_preview_lifecycle_only"
    repository.connection.execute(f"alter table world_style_preview disable trigger {guard}")
    try:
        repository.connection.execute(
            "update world_style_preview set candidate = candidate - 'recipe_binding' "
            "where workspace_id=%s and world_id=%s and preview_id=%s",
            (repository.workspace_id, FIXTURE_WORLD_ID, legacy.preview_id),
        )
    finally:
        repository.connection.execute(f"alter table world_style_preview enable trigger {guard}")
    repository.connection.commit()
    provision_runtime_role(repository.connection)
    repository.connection.commit()

    with scratch_role_database(spine_schema[1], RUNTIME_ROLE).session(
        repository.workspace_id
    ) as connection:
        found = WorldStyleRepository(
            connection, repository.workspace_id, world_id=FIXTURE_WORLD_ID
        ).open_previews()

    assert [preview.preview_id for preview, _ in found.readable] == [kept.preview_id]
    assert found.unreadable == 1


def test_a_world_opening_reads_back_only_the_newest_open_previews(world):
    repository, _, _, _ = world
    styles = WorldStyleRepository(
        repository.connection, repository.workspace_id, world_id=FIXTURE_WORLD_ID
    )
    made = [
        _propose(styles, companion=True, softness=round(0.1 + 0.05 * index, 2))
        for index in range(OPEN_PREVIEWS_READ + 2)
    ]

    found = styles.open_previews()

    newest = [preview.preview_id for preview in reversed(made)][:OPEN_PREVIEWS_READ]
    assert [preview.preview_id for preview, _ in found.readable] == newest
    assert found.unreadable == 0


def test_a_fault_that_is_not_an_unreadable_row_surfaces(world, monkeypatch):
    """Only the named data errors are counted; anything else is a fault and says so."""
    repository, _, _, _ = world
    styles = WorldStyleRepository(
        repository.connection, repository.workspace_id, world_id=FIXTURE_WORLD_ID
    )
    _propose(styles, companion=True, softness=0.8)

    def broken(self, value):
        raise TypeError("a fault in this code, not an old row")

    monkeypatch.setattr(WorldStyleRepository, "_candidate_from_document", broken)
    with pytest.raises(TypeError):
        styles.open_previews()
