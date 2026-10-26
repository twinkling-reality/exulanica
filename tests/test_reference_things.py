"""Versioned creature notes across the actual worker and consumer, with scripted providers."""

from __future__ import annotations

import dataclasses
import json
import uuid
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.manifest import load_manifest
from exulanica.references import drafting, store
from exulanica.references.adapters.tavily import TavilySearch
from exulanica.references.bundle import (
    PROFILE,
    THINGS_PROFILE,
    BundleError,
    BundleNote,
    BundlePicture,
    read_bundle,
)
from exulanica.references.catalogs import load_reference_catalogs
from exulanica.references.for_drafting import NotesRefused, notes_for_draft
from exulanica.references.render import render_reference_notes
from exulanica.references.worker import ReferenceWorker
from exulanica.selection import creature_drafts
from exulanica.world.thing_store import ThingStore

from creature_support import form_of
from model_fakes import FakeTransport, RecordingPolicy
from reference_fixtures import finished_reference, scripted_bundle
from test_creature_drafts_postgres import _transport, _worker
from test_creature_drafts_postgres import served as served
from test_reference_worker import ACTOR, READING, _Gate, _Spending, _structured, _tavily_answer
from test_reference_worker import PLAN as LEGACY_PLAN
from test_reference_worker import scene as scene

PLAN = {"subjects": [{"aspect": "anatomy", "text": "water bird bill body shape"}]}
NOTES = {
    "notes": [
        {"aspect": "anatomy", "text": "broad bill on a rounded head"},
        {"aspect": "part_layout", "text": "two hind feet below a compact torso"},
        {"aspect": "materials_and_colour", "text": "yellow feathers and a pale bill"},
        {"aspect": "scale", "text": "short body relative to the head"},
    ]
}


def test_bundle_version_owns_closed_vocabulary_and_old_bytes():
    old = scripted_bundle(uuid.uuid4(), purpose="things")
    before = old.canonical_bytes()
    assert read_bundle(old.document()).canonical_bytes() == before
    new_notes = (BundleNote("anatomy", "broad bill on a rounded head", "web_description", None),)
    with pytest.raises(BundleError, match="aspect"):
        dataclasses.replace(old, notes=new_notes)
    widened = old.document() | {
        "notes": [
            {
                "aspect": "anatomy",
                "text": "broad bill",
                "basis": "web_description",
                "picture_id": None,
            }
        ]
    }
    with pytest.raises(BundleError, match="aspect"):
        read_bundle(widened, catalogs=load_reference_catalogs(aspect_version=2))
    new = dataclasses.replace(old, profile=THINGS_PROFILE, notes=new_notes)
    assert read_bundle(new.document()).digest == new.digest
    assert "Anatomy: broad bill" in render_reference_notes(new).text
    with pytest.raises(BundleError, match="serves things"):
        dataclasses.replace(new, purpose="world_draft")
    picture = BundlePicture(uuid.uuid4(), (uuid.uuid4(),), ("nebius", "reference_vision", "model"))
    with pytest.raises(BundleError, match="not open to pictures"):
        dataclasses.replace(
            new,
            pictures=(picture,),
            notes=(BundleNote("anatomy", "broad bill", "own_picture", picture.picture_id),),
        )


@pytest.mark.postgres
@pytest.mark.parametrize("version", ["old", "things", "unknown", "wrong_purpose"])
def test_queued_request_uses_its_pinned_words_or_refuses_before_dispatch(scene, version):
    connection, workspace, models, tavily, gate, worker, request = scene
    words = drafting.prompts_for_request("things")
    purpose = "kind" if version == "wrong_purpose" else "things"
    digest = (
        drafting.reference_prompts().sha256
        if version == "old"
        else "a" * 64
        if version == "unknown"
        else words.sha256
    )
    made = request(purpose=purpose, prompts_sha256=digest)
    if version in ("unknown", "wrong_purpose"):
        assert worker().run_once(workspace) == "failed"
        ended = store.read_request(connection, workspace, made.reference_id)
        assert ended.failure == "reference_prompts_unavailable"
        assert not models.requests and not tavily.requests and not gate.admitted
        return
    models.responses = (
        [_structured(LEGACY_PLAN), _structured(READING)]
        if version == "old"
        else [_structured(PLAN), _structured(NOTES)]
    )
    tavily.responses = [_tavily_answer(), _tavily_answer()]
    outcome = worker().run_once(workspace)
    ended = store.read_request(connection, workspace, made.reference_id)
    assert models.requests[0]["payload"]["messages"][0]["content"] == (
        drafting.reference_prompts().planning if version == "old" else words.planning
    )
    if version == "old":
        assert outcome == "complete"
        assert ended.bundle["profile"] == PROFILE
        assert "anatomy" not in json.dumps(models.requests[0]["payload"]["response_format"])
        assert len(tavily.requests) == 2
    else:
        assert outcome == "complete"
        assert ended.bundle["profile"] == THINGS_PROFILE
        notes = notes_for_draft(connection, workspace, ACTOR, made.reference_id, purpose="things")
        assert notes.rendered.used == 4
        assert notes.provenance["bundle_sha256"] == ended.bundle_sha256
        assert "Part layout" in notes.rendered.text


@pytest.mark.postgres
def test_reference_worker_v2_reaches_creature_consumer_and_keeps_explicit_edits(served):
    database, workspace, stores = served
    actor = uuid.uuid4()
    words = "a giant green water creature with a broad bill, ten metres tall"
    models = FakeTransport(responses=[_structured(PLAN), _structured(NOTES)])
    tavily = FakeTransport(responses=[_tavily_answer()])
    client = ModelClient(
        api_key="test-key",
        manifest=load_manifest(),
        transport=models,
        budget=BudgetGuard(ceiling_usd=Decimal("1"), max_calls=20),
        policy=RecordingPolicy(),
    )
    with database.session(workspace) as connection:
        made, _ = store.create_request(
            connection,
            workspace,
            offered_to={workspace},
            owner_actor_id=actor,
            purpose="things",
            web=True,
            description=words,
            withheld_words=(),
            prompts_sha256=drafting.prompts_for_request("things").sha256,
        )
    worker = ReferenceWorker(
        database,
        client=client,
        policy_for=lambda _: RecordingPolicy(),
        spending=_Spending(_Gate()),
        adapter_for=lambda source: TavilySearch(source, transport=tavily, credential="test-key"),
        workspaces=lambda: (workspace,),
    )
    assert worker.run_once(workspace) == "complete"
    with database.session(workspace) as connection:
        ref = store.read_request(connection, workspace, made.reference_id)
        assert ref.bundle["profile"] == THINGS_PROFILE
        with pytest.raises(NotesRefused, match="reference_unknown"):
            notes_for_draft(
                connection, workspace, uuid.uuid4(), made.reference_id, purpose="things"
            )
        queued = creature_drafts.create_draft(
            connection,
            workspace,
            offered_to={workspace},
            owner_actor_id=actor,
            words=words,
            sent=words,
            placeholders={},
            reference_id=made.reference_id,
        )
    # This fixture proves transmission and provenance, not model compliance or visual quality.
    transport = _transport(form_of("horse", label="hill walker"))
    assert _worker(database, workspace, stores, transport).run_once(workspace) == "kept"
    messages = transport.requests[0]["payload"]["messages"]
    assert words in messages[1]["content"]
    assert "yellow feathers" in messages[1]["content"]
    # Creature drafting v5: the person's own words win over the notes, and requested changes too.
    assert "The person's own words win over the notes" in messages[0]["content"]
    assert "explicit requested changes also take precedence" in messages[0]["content"]
    with database.session(workspace) as connection:
        draft = creature_drafts.read_draft(connection, workspace, queued.draft_id)
        assert draft.reference_usage["bundle_sha256"] == ref.bundle_sha256
        assert draft.reference_usage["notes"] == 4
        held = ThingStore(connection, workspace, None).kind_by_digest(draft.kind_sha256)
        assert ref.bundle_sha256 in held.document["origin"]["lineage"]["ingredients"]


@pytest.mark.postgres
def test_populated_upgrade_preserves_v1_and_constrains_v2(repository):
    connection, workspace = repository.connection, repository.workspace_id
    old = scripted_bundle(workspace, purpose="things")
    reference_id = finished_reference(connection, workspace, purpose="things", bundle=old)
    connection.execute(
        "alter table reference_request drop constraint reference_request_bundle_check"
    )
    connection.execute("""alter table reference_request
        add constraint reference_request_bundle_check
        check (bundle is null or (bundle->>'profile' = 'exulanica.reference-bundle/v1') is true)""")
    before = store.read_request(connection, workspace, reference_id)
    migration = Path(
        "exulanica/migrations/0204_reference_bundles_version_the_things_vocabulary.sql"
    )
    connection.execute(migration.read_text())
    after = store.read_request(connection, workspace, reference_id)
    assert before.bundle == after.bundle and before.bundle_sha256 == after.bundle_sha256
    assert read_bundle(after.bundle).canonical_bytes() == old.canonical_bytes()
    new = dataclasses.replace(old, profile=THINGS_PROFILE)
    finished_reference(connection, workspace, purpose="things", bundle=new)
    for purpose, profile, inner in [
        ("kind", THINGS_PROFILE, "things"),
        ("things", THINGS_PROFILE, "kind"),
        ("things", "exulanica.reference-bundle/v3", "things"),
        ("things", None, "things"),
    ]:
        document = new.document() | {"profile": profile, "purpose": inner}
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            connection.execute(
                "insert into reference_request "
                "(workspace_id, owner_actor_id, purpose, web, job_id, "
                "prompts_sha256, bundle, bundle_sha256, status) "
                "values (%s,%s,%s,true,%s,%s,%s::jsonb,%s,'complete')",
                (
                    workspace,
                    uuid.uuid4(),
                    purpose,
                    uuid.uuid4(),
                    "a" * 64,
                    json.dumps(document),
                    "b" * 64,
                ),
            )
