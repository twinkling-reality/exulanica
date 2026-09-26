"""A world's open appearance previews are read back until a person decides or they expire.

A preview is held by the server until a person applies or discards it, a new proposal replaces
it, or it outlives ``OPEN_PREVIEW_LIFETIME``; a page keeps only what it read.
``WorldStyleRepository.open_previews`` and ``GET /world/styles/previews`` return the newest of the
world's open previews a page may take up (from another origin than Settings, over the whole world,
younger than the lifetime), newest first, so a page that reloads, or opens the world again after
another, can put a Companion's staged proposal back in front of the person. Read as the runtime
role, which row-level security binds, as the API reads it; the routes are served as a deployment
serves them, writes as the runtime role and reads as a role that can only select.
"""

from __future__ import annotations

import json
import uuid
from urllib.parse import urlencode

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.db.roles import EXECUTOR_ROLE, RUNTIME_ROLE, provision_runtime_role
from exulanica.store.local import LocalContentAddressedStore
from exulanica.world import ExpiredPreview, TopologyContract, WorldStyleRepository
from exulanica.world.models import ProposalOrigin, ProposalProvenance, StyleProposal, StyleScope
from exulanica.world.repository import OPEN_PREVIEW_LIFETIME, OPEN_PREVIEWS_READ
from exulanica.world.worlds import AUTHORED_STARTER
from fastapi.testclient import TestClient

from conftest import scratch_role_database
from test_appearance_proposal_names import SOURCE, world
from test_companion_saved_names import named
from tests_support_api import EVERY_PERMISSION
from world_support import FIXTURE_WORLD_ID, registered_world

pytestmark = pytest.mark.postgres

__all__ = ["named", "world"]

#: The guard that keeps a stored preview's candidate and creation time immutable.
_LIFECYCLE_GUARD = "tg_world_style_preview_lifecycle_only"

#: A second world of the same workspace, an authored starter because a workspace holds one
#: personal-source world; its previews are not the first world's to close.
_OTHER_WORLD = "world:style-previews:other"

#: The scope a page shows a proposal over.
_WHOLE_WORLD = StyleScope("global")


def _propose(
    styles: WorldStyleRepository,
    *,
    companion: bool,
    softness: float,
    scope: StyleScope = _WHOLE_WORLD,
):
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
            scope=scope,
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


def _age(repository, preview_id, world_id=FIXTURE_WORLD_ID) -> None:
    """Make one stored preview a minute older than a preview's lifetime.

    Its creation time is immutable to everyone, so the row is aged here with the guard off for
    this one statement, as the schema owner, and the guard put straight back.
    """
    repository.connection.execute(
        f"alter table world_style_preview disable trigger {_LIFECYCLE_GUARD}"
    )
    try:
        repository.connection.execute(
            "update world_style_preview set created_at = now() - %s - interval '1 minute' "
            "where workspace_id=%s and world_id=%s and preview_id=%s",
            (OPEN_PREVIEW_LIFETIME, repository.workspace_id, world_id, preview_id),
        )
    finally:
        repository.connection.execute(
            f"alter table world_style_preview enable trigger {_LIFECYCLE_GUARD}"
        )


def _lifecycle(repository, preview_id, world_id=FIXTURE_WORLD_ID) -> tuple[str, str, bool]:
    """The stored status of a preview and of its proposal, and whether the preview was closed."""
    row = repository.connection.execute(
        "select v.status as preview, p.status as proposal, v.closed_at is not null as closed "
        "from world_style_preview v join world_style_proposal p "
        "on p.workspace_id=v.workspace_id and p.world_id=v.world_id "
        "and p.proposal_id=v.proposal_id "
        "where v.workspace_id=%s and v.world_id=%s and v.preview_id=%s",
        (repository.workspace_id, world_id, preview_id),
    ).fetchone()
    return row["preview"], row["proposal"], row["closed"]


def _events(repository, preview_id) -> list[dict]:
    return repository.connection.execute(
        "select event_type,origin,origin_reference,details from world_style_audit_event "
        "where workspace_id=%s and world_id=%s and preview_id=%s order by occurred_at, event_id",
        (repository.workspace_id, FIXTURE_WORLD_ID, preview_id),
    ).fetchall()


def _as_runtime(repository, spine_schema):
    """Commit what the owner wrote and open the world as the runtime role reads and writes it."""
    repository.connection.commit()
    provision_runtime_role(repository.connection)
    repository.connection.commit()
    return scratch_role_database(spine_schema[1], RUNTIME_ROLE).session(repository.workspace_id)


def test_the_open_previews_a_page_may_take_up_are_read_back_newest_first(world, spine_schema):
    repository, _, _, _ = world
    styles = WorldStyleRepository(
        repository.connection, repository.workspace_id, world_id=FIXTURE_WORLD_ID
    )
    older = _propose(styles, companion=True, softness=0.8)
    _propose(styles, companion=False, softness=0.6)
    newer = _propose(styles, companion=True, softness=0.5)
    _propose(styles, companion=True, softness=0.3, scope=StyleScope("region", "region-a"))
    closed = _propose(styles, companion=True, softness=0.4)
    styles.discard(closed.preview_id, discarded_by=uuid.uuid4())

    with _as_runtime(repository, spine_schema) as connection:
        found = WorldStyleRepository(
            connection, repository.workspace_id, world_id=FIXTURE_WORLD_ID
        ).open_previews()

    read = [preview for preview, _ in found.readable]
    assert found.unreadable == 0
    # Neither the panel's own Settings draft, nor a regional one no page shows, nor a closed one.
    assert [p.preview_id for p in read] == [newer.preview_id, older.preview_id]
    assert read[1].proposal.provenance.origin == "companion"
    assert read[1].proposal.provenance.origin_reference == "companion-utterance:open-previews"
    assert read[1].proposal.reference_ids == (str(SOURCE),)
    assert read[1].candidate.global_style.parameters["horizon-softness"] == 0.8


def test_newer_settings_previews_never_hide_a_staged_companion_proposal(world):
    """The origin is filtered before the limit, so a limit's worth of drafts hides nothing."""
    repository, _, _, _ = world
    styles = WorldStyleRepository(
        repository.connection, repository.workspace_id, world_id=FIXTURE_WORLD_ID
    )
    staged = _propose(styles, companion=True, softness=0.8)
    for index in range(OPEN_PREVIEWS_READ):
        _propose(styles, companion=False, softness=round(0.1 + 0.05 * index, 2))

    found = styles.open_previews()

    assert [preview.preview_id for preview, _ in found.readable] == [staged.preview_id]
    assert found.unreadable == 0


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
    repository.connection.execute(
        f"alter table world_style_preview disable trigger {_LIFECYCLE_GUARD}"
    )
    try:
        repository.connection.execute(
            "update world_style_preview set candidate = candidate - 'recipe_binding' "
            "where workspace_id=%s and world_id=%s and preview_id=%s",
            (repository.workspace_id, FIXTURE_WORLD_ID, legacy.preview_id),
        )
    finally:
        repository.connection.execute(
            f"alter table world_style_preview enable trigger {_LIFECYCLE_GUARD}"
        )

    with _as_runtime(repository, spine_schema) as connection:
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


# -- a preview's lifetime -------------------------------------------------------------------------


def test_a_preview_past_its_lifetime_is_not_read_back_and_its_proposal_says_expired(
    world, spine_schema
):
    repository, _, _, _ = world
    styles = WorldStyleRepository(
        repository.connection, repository.workspace_id, world_id=FIXTURE_WORLD_ID
    )
    old = _propose(styles, companion=True, softness=0.8)
    fresh = _propose(styles, companion=True, softness=0.6)
    _age(repository, old.preview_id)

    with _as_runtime(repository, spine_schema) as connection:
        reader = WorldStyleRepository(
            connection, repository.workspace_id, world_id=FIXTURE_WORLD_ID
        )
        found = reader.open_previews()
        expired = reader.proposal(old.proposal.proposal_id)
        waiting = reader.proposal(fresh.proposal.proposal_id)

    assert [preview.preview_id for preview, _ in found.readable] == [fresh.preview_id]
    # Said before any write closes it, by the predicate Apply refuses it by.
    assert expired.status == "expired"
    assert waiting.status == "previewed"
    # A read closes nothing.
    assert _lifecycle(repository, old.preview_id) == ("open", "previewed", False)


def test_apply_refuses_a_preview_past_its_lifetime_by_name_and_closes_it(world, spine_schema):
    repository, _, _, _ = world
    styles = WorldStyleRepository(
        repository.connection, repository.workspace_id, world_id=FIXTURE_WORLD_ID
    )
    old = _propose(styles, companion=True, softness=0.8)
    before = styles.current()
    _age(repository, old.preview_id)

    with _as_runtime(repository, spine_schema) as connection:
        writer = WorldStyleRepository(
            connection, repository.workspace_id, world_id=FIXTURE_WORLD_ID
        )
        # Refused by name while it is open past its lifetime, and again once that closed it.
        for _attempt in ("open past its lifetime", "closed as expired"):
            with pytest.raises(ExpiredPreview):
                writer.apply(
                    old.preview_id,
                    base_style_version_id=before.version_id,
                    base_topology_digest=writer.current_topology_digest(),
                    applied_by=uuid.uuid4(),
                )
        after = writer.current()

    assert after.version_id == before.version_id
    assert _lifecycle(repository, old.preview_id) == ("expired", "expired", True)
    assert [event["event_type"] for event in _events(repository, old.preview_id)] == [
        "preview_created",
        "preview_expired",
    ]


def test_a_discard_past_the_lifetime_closes_the_preview_as_expired(world, spine_schema):
    """The proposal read already called it expired; a discard does not record a person's act."""
    repository, _, _, _ = world
    styles = WorldStyleRepository(
        repository.connection, repository.workspace_id, world_id=FIXTURE_WORLD_ID
    )
    old = _propose(styles, companion=True, softness=0.8)
    _age(repository, old.preview_id)

    with _as_runtime(repository, spine_schema) as connection:
        writer = WorldStyleRepository(
            connection, repository.workspace_id, world_id=FIXTURE_WORLD_ID
        )
        # Once past its lifetime, and again once that closed it: neither is an error.
        writer.discard(old.preview_id, discarded_by=uuid.uuid4())
        writer.discard(old.preview_id, discarded_by=uuid.uuid4())

    assert _lifecycle(repository, old.preview_id) == ("expired", "expired", True)
    assert [event["event_type"] for event in _events(repository, old.preview_id)] == [
        "preview_created",
        "preview_expired",
    ]


def test_a_new_preview_closes_the_world_s_previews_past_their_lifetime(world, spine_schema):
    repository, _, _, _ = world
    styles = WorldStyleRepository(
        repository.connection, repository.workspace_id, world_id=FIXTURE_WORLD_ID
    )
    staged = _propose(styles, companion=True, softness=0.8)
    draft = _propose(styles, companion=False, softness=0.6)
    fresh = _propose(styles, companion=True, softness=0.5)
    registered_world(
        repository.connection, repository.workspace_id, _OTHER_WORLD, kind=AUTHORED_STARTER
    )
    other = WorldStyleRepository(
        repository.connection, repository.workspace_id, world_id=_OTHER_WORLD
    )
    other.register_topology(
        TopologyContract("other-topology", ("region-a",), world_id=_OTHER_WORLD)
    )
    elsewhere = _propose(other, companion=False, softness=0.8)
    for preview in (staged, draft):
        _age(repository, preview.preview_id)
    _age(repository, elsewhere.preview_id, world_id=_OTHER_WORLD)

    with _as_runtime(repository, spine_schema) as connection:
        made = _propose(
            WorldStyleRepository(connection, repository.workspace_id, world_id=FIXTURE_WORLD_ID),
            companion=True,
            softness=0.3,
        )

    assert _lifecycle(repository, staged.preview_id) == ("expired", "expired", True)
    assert _lifecycle(repository, draft.preview_id) == ("expired", "expired", True)
    assert _lifecycle(repository, fresh.preview_id) == ("open", "previewed", False)
    assert _lifecycle(repository, made.preview_id) == ("open", "previewed", False)
    # Another world's previews are that world's to close.
    assert _lifecycle(repository, elsewhere.preview_id, _OTHER_WORLD) == (
        "open",
        "previewed",
        False,
    )
    # Each closes with one event carrying its proposal's own provenance.
    expired = _events(repository, staged.preview_id)[-1]
    assert expired == {
        "event_type": "preview_expired",
        "origin": "companion",
        "origin_reference": "companion-utterance:open-previews",
        "details": {"lifetime_seconds": int(OPEN_PREVIEW_LIFETIME.total_seconds())},
    }
    assert [event["event_type"] for event in _events(repository, draft.preview_id)] == [
        "preview_created",
        "preview_expired",
    ]


# -- the routes, served as a deployment serves them -----------------------------------------------

_TOKEN = "style-previews-owner-token-long-enough-for-tests"


@pytest.fixture
def served(world, spine_schema, tmp_path):
    """The application writing as the runtime role and reading as one that can only select."""
    repository, _, _, _ = world
    _psycopg, scratch = spine_schema
    repository.connection.commit()
    provision_runtime_role(repository.connection)
    provision_runtime_role(repository.connection, role=EXECUTOR_ROLE, read_only=True)
    repository.connection.commit()
    grants = {
        _TOKEN: {
            "workspace_id": str(repository.workspace_id),
            "actor": str(uuid.uuid4()),
            "permissions": EVERY_PERMISSION,
        }
    }
    services = Services(
        database=scratch_role_database(scratch, RUNTIME_ROLE),
        readonly_database=scratch_role_database(scratch, EXECUTOR_ROLE),
        store=LocalContentAddressedStore(tmp_path / "blobs"),
        tokens=load_token_directory({"EXULANICA_API_TOKENS": json.dumps(grants)}),
        executor_shares_the_write_role=False,
        model_client=None,
    )
    with TestClient(create_app(services, verify=False)) as client:
        yield client, repository


def test_the_routes_name_a_preview_past_its_lifetime(served):
    client, repository = served
    headers = {"Authorization": f"Bearer {_TOKEN}"}
    world_query = urlencode({"world_id": FIXTURE_WORLD_ID})
    current = client.get(f"/world/styles/current?{world_query}", headers=headers).json()
    base = {
        "baseStyleVersionId": current["current"]["version_id"],
        "baseTopologyDigest": current["current_topology_digest"],
    }
    proposal_id = str(uuid.uuid4())
    # The body the browser's client posts for a Companion proposal (world-style-api.ts).
    made = client.post(
        f"/world/styles/previews?{world_query}",
        headers=headers,
        json={
            "proposalId": proposal_id,
            "origin": "companion",
            "originReference": "companion-utterance:expired",
            "scope": {"kind": "global"},
            **base,
            "profile": {
                "profileId": "origin-landscape",
                "profileVersion": 1,
                "parameters": {"horizon-softness": 0.8},
            },
            "referenceIds": [str(SOURCE)],
            "modelId": "Qwen/Qwen3-235B-A22B-Instruct-2507",
            "promptVersion": "proposal-3",
            "refinesProposalId": None,
        },
    )
    assert made.status_code == 201, made.text
    preview_id = made.json()["preview_id"]
    listed = client.get(f"/world/styles/previews?{world_query}", headers=headers).json()
    assert [row["preview"]["preview_id"] for row in listed["previews"]] == [preview_id], (
        "positive control: read back while it is young"
    )
    _age(repository, uuid.UUID(preview_id))
    repository.connection.commit()

    listed = client.get(f"/world/styles/previews?{world_query}", headers=headers)
    assert listed.status_code == 200, listed.text
    assert listed.json() == {"previews": [], "unreadable": 0}
    read = client.get(f"/world/styles/proposals/{proposal_id}?{world_query}", headers=headers)
    assert read.status_code == 200, read.text
    assert read.json()["status"] == "expired"

    applied = client.post(
        f"/world/styles/previews/{preview_id}/apply?{world_query}", headers=headers, json=base
    )

    assert applied.status_code == 409, applied.text
    assert applied.json()["code"] == "preview_expired"
    after = client.get(f"/world/styles/current?{world_query}", headers=headers).json()
    assert after["current"]["version_id"] == base["baseStyleVersionId"]
    assert _lifecycle(repository, uuid.UUID(preview_id)) == ("expired", "expired", True)
