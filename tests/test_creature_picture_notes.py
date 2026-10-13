"""Selected captures through real intake, current consent and guarded creature publication."""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import threading
import uuid
from pathlib import Path

import psycopg
import pytest
from exulanica.api.composer_rights import photograph_text_right
from exulanica.api.reference_pictures import reference_picture_source
from exulanica.db.definer_role import assert_definer_role, shipped_versions
from exulanica.db.roles import RUNTIME_ROLE, provision_runtime_role
from exulanica.epistemics.hosted_requests import WorkspaceRequestPolicy, no_place_released
from exulanica.evidence.blob import BlobId
from exulanica.ingest import personal_admission as admission
from exulanica.ingest.model_rights import grant_model_right, withdraw_model_right
from exulanica.ingest.repository import IngestRepository
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.manifest import load_manifest
from exulanica.references import drafting, store
from exulanica.references.adapters.tavily import TavilySearch
from exulanica.references.bundle import (
    THINGS_PICTURE_PROFILE,
    THINGS_PROFILE,
    BundleError,
    BundleNote,
    BundlePicture,
    read_bundle,
)
from exulanica.references.catalogs import load_reference_catalogs
from exulanica.references.render import render_reference_notes
from exulanica.references.worker import ReferenceWorker
from exulanica.selection import creature_drafts as drafts
from exulanica.store.configured import local_content_stores
from exulanica.world.thing_store import ThingStore
from psycopg.types.json import Jsonb

from conftest import scratch_role_database
from creature_support import form_of
from model_fakes import FakeTransport, RecordingPolicy
from reference_fixtures import scripted_bundle
from test_creature_drafts_postgres import _transport
from test_intake_upload import upload as upload
from test_personal_admission_route import batch, post
from test_reference_worker import _Gate, _Spending, _structured, _tavily_answer
from test_reference_worker_pictures import _reading


def test_selected_picture_version_preserves_legacy_prompts_and_closed_bundles():
    legacy = drafting.reference_prompts()
    web = drafting.reference_prompts(drafting.THINGS_PROMPT_PATH)
    picture = drafting.prompts_for_request("things", pictures=True)
    assert drafting.prompts_for_request("things").sha256 == web.sha256
    assert (
        picture.version == 4 and picture.planning == web.planning and picture.reading == web.reading
    )
    for prompt in (legacy, web, picture):
        assert drafting.prompts_for_request("things", prompt.sha256).sha256 == prompt.sha256
    assert drafting.prompts_for_request("kind", pictures=True) == legacy
    old = scripted_bundle(uuid.uuid4(), purpose="things")
    source = BundlePicture(uuid.uuid4(), (uuid.uuid4(),), ("nebius", "reference_vision", "model"))
    values = dict(
        pictures=(source,),
        notes=(BundleNote("anatomy", "rounded torso", "own_picture", source.picture_id),),
    )
    for profile in (old.profile, THINGS_PROFILE):
        with pytest.raises(BundleError):
            dataclasses.replace(old, profile=profile, **values)
    new = dataclasses.replace(old, profile=THINGS_PICTURE_PROFILE, **values)
    assert read_bundle(new.document()).canonical_bytes() == new.canonical_bytes()
    assert render_reference_notes(new).photographs == frozenset({source.picture_id})
    with pytest.raises(BundleError):
        read_bundle(
            dataclasses.replace(old, profile=THINGS_PROFILE).document()
            | {"notes": new.document()["notes"], "pictures": new.document()["pictures"]},
            catalogs=load_reference_catalogs(aspect_version=2, picture_version=2),
        )
    v1 = admission.load_model_right_uses(
        Path(admission.__file__).with_name("model-right-uses.v1.json")
    )
    assert v1.use("creature_drafter") is None
    raw = json.loads(Path(admission.__file__).with_name("model-right-uses.v1.json").read_text())
    raw["uses"][0]["consent_use"] = "creature_picture_notes/v1"
    with pytest.raises(ValueError):
        admission.parse_model_right_uses(raw)


@pytest.fixture
def selected(upload, spine_schema, tmp_path, request):
    provision_runtime_role(upload.repository.connection)
    provision_runtime_role(
        upload.repository.connection, role="exulanica_picture_notes_ro", read_only=True
    )
    assert_definer_role(upload.repository.connection, applied=shipped_versions())
    upload.repository.connection.commit()
    runtime = scratch_role_database(spine_schema[1], RUNTIME_ROLE)
    readonly = scratch_role_database(spine_schema[1], "exulanica_picture_notes_ro")
    services = dataclasses.replace(
        upload.client.app.state.services, database=runtime, readonly_database=readonly
    )
    upload.client.app.state.services = services
    upload.database = runtime
    body = batch(upload, count=1)
    until = body["authority"]["valid_until"]
    if getattr(request, "param", None) == "short":
        until = (dt.datetime.now(dt.UTC) + dt.timedelta(seconds=3)).isoformat()
    body["model_rights"] = [
        {"role": role, "valid_until": until, "notice": admission.role_notices()[role]}
        for role in (
            request.param
            if isinstance(getattr(request, "param", None), tuple)
            else ("reference_vision", "creature_drafter")
        )
    ]
    response = post(upload, "/personal-admission", body)
    assert response.status_code == 202, response.text
    upload.personal_body = body
    capture = uuid.UUID(body["members"][0]["capture_id"])
    actor = upload.rows("select distinct granted_by from personal_model_right")[0]["granted_by"]
    upload.drain(screened=False)
    notes = {
        "refuse": None,
        "notes": [
            {"aspect": "anatomy", "text": "broad bill above a rounded torso"},
            {"aspect": "part_layout", "text": "two short hind limbs below the torso"},
            {"aspect": "materials_and_colour", "text": "yellow feathers and a pale bill"},
        ],
    }
    mixed = getattr(request, "param", None) == "mixed"
    replies = [_reading(notes)]
    if mixed:
        replies.extend(
            [
                _structured(
                    {"subjects": [{"aspect": "anatomy", "text": "water creature visible anatomy"}]}
                ),
                _structured(
                    {
                        "notes": [
                            {
                                "aspect": "scale",
                                "text": "upright proportions relative to nearby reeds",
                            }
                        ]
                    }
                ),
            ]
        )
    transport = FakeTransport(responses=replies)
    manifest = load_manifest()
    client = ModelClient(
        api_key="test-key",
        manifest=manifest,
        transport=transport,
        budget=BudgetGuard(),
        policy=RecordingPolicy(),
    )

    def policy_for(workspace):
        return WorkspaceRequestPolicy(
            workspace,
            connection=lambda: readonly.session(workspace),
            photograph_right=photograph_text_right,
            released_places=no_place_released,
        )

    words = "an invented giant green water creature with a broad bill, ten metres tall"
    with runtime.session(upload.workspace_id) as connection:
        reference, _ = store.create_request(
            connection,
            upload.workspace_id,
            offered_to={upload.workspace_id},
            owner_actor_id=actor,
            purpose="things",
            web=mixed,
            description=words,
            withheld_words=(),
            pictures=(capture,),
            prompts_sha256=drafting.prompts_for_request("things", pictures=True).sha256,
        )
    worker = ReferenceWorker(
        runtime,
        client=client,
        policy_for=policy_for,
        spending=_Spending(_Gate()),
        adapter_for=lambda source: (
            TavilySearch(
                source, transport=FakeTransport(responses=[_tavily_answer()]), credential="test-key"
            )
            if mixed
            else pytest.fail("no web lookup")
        ),
        workspaces=lambda: (upload.workspace_id,),
        picture_source=reference_picture_source(readonly.session, upload.store),
    )
    assert worker.run_once(upload.workspace_id) == "complete"
    with runtime.session(upload.workspace_id) as connection:
        reference = store.read_request(connection, upload.workspace_id, reference.reference_id)
        assert reference.bundle["profile"] == THINGS_PICTURE_PROFILE
        assert len(reference.bundle["notes"]) == (4 if mixed else 3)
    stores = local_content_stores(tmp_path / "creatures")
    services = dataclasses.replace(
        services,
        model_client=client,
        content_stores=stores,
        creature_workspaces=(upload.workspace_id,),
        reference_workspaces=(upload.workspace_id,),
        reference_pictures=True,
        runs_creature_worker=True,
        runs_reference_worker=True,
    )
    upload.client.app.state.services = services
    return upload, services, capture, actor, reference, words, transport


def queue(selected):
    upload, services, _capture, actor, reference, words, _ = selected
    with services.database.session(upload.workspace_id) as connection:
        made = drafts.create_draft(
            connection,
            upload.workspace_id,
            offered_to={upload.workspace_id},
            owner_actor_id=actor,
            words=words,
            sent=words,
            placeholders={},
            reference_id=reference.reference_id,
        )
    return made


def creature_worker(selected, transport=None):
    _upload, services, *_ = selected
    transport = transport or _transport(form_of("horse", label="invented green giant"))
    client = ModelClient(
        api_key="test-key",
        manifest=load_manifest(),
        transport=transport,
        budget=BudgetGuard(),
        policy=RecordingPolicy(),
    )
    wired = dataclasses.replace(services, model_client=client)
    worker = wired.build_creature_worker()
    assert worker is not None
    worker.test_services = wired
    return worker, transport


@pytest.mark.postgres
def test_selected_notes_reach_creature_with_authority_and_explicit_edits(selected):
    upload, services, _capture, _actor, reference, words, reader = selected
    made = queue(selected)
    worker, transport = creature_worker(selected)
    assert worker.run_once(upload.workspace_id) == "kept"
    messages = transport.requests[0]["payload"]["messages"]
    assert words in messages[1]["content"] and "yellow feathers" in messages[1]["content"]
    assert "explicit changes take precedence" in messages[1]["content"]
    assert "yellow feathers" not in messages[0]["content"]
    assert "image_url" not in json.dumps(messages)  # semantic notes, no pixel input to drafter
    assert "image_url" in json.dumps(reader.requests[0]["payload"]["messages"])
    with services.database.session(upload.workspace_id) as connection:
        done = drafts.read_draft(connection, upload.workspace_id, made.draft_id)
        assert done.reference_usage["basis"] == ["own_picture"]
        kind = ThingStore(connection, upload.workspace_id, None).kind_by_digest(done.kind_sha256)
        assert reference.bundle_sha256 in kind.document["origin"]["lineage"]["ingredients"]
        row = connection.execute(
            "select row_to_json(d)::text as value from creature_draft d where draft_id=%s",
            (made.draft_id,),
        ).fetchone()["value"]
        assert words not in row and "yellow feathers" not in row
        assert connection.execute(
            "select payload from job where job_id=%s", (made.job_id,)
        ).fetchone()["payload"] == {"draft_id": str(made.draft_id)}
    # Scripted forms prove transmitted semantics and validation, never model visual matching.


def stop(selected, role):
    upload, services, _capture, actor, *_ = selected
    with services.database.session(upload.workspace_id) as connection:
        right = connection.execute(
            "select right_id from personal_model_right where model_role=%s limit 1", (role,)
        ).fetchone()["right_id"]
        withdraw_model_right(
            IngestRepository(connection, upload.workspace_id), right_id=right, withdrawn_by=actor
        )


@pytest.mark.postgres
@pytest.mark.parametrize("role", ["reference_vision", "creature_drafter"])
def test_stop_before_dispatch_sends_nothing_and_keeps_nothing(selected, role):
    upload, services, *_ = selected
    made = queue(selected)
    stop(selected, role)
    worker, transport = creature_worker(selected)
    assert worker.run_once(upload.workspace_id) == "failed"
    assert not transport.requests
    with services.database.session(upload.workspace_id) as connection:
        done = drafts.read_draft(connection, upload.workspace_id, made.draft_id)
        assert done.failure == "reference_withdrawn" and done.kind_sha256 is None


@pytest.mark.postgres
@pytest.mark.parametrize("role", ["reference_vision", "creature_drafter"])
def test_stop_while_provider_runs_discards_response(selected, role):
    upload, services, *_ = selected
    made = queue(selected)
    transport = _transport(form_of("horse", label="green giant"))
    original_post = transport.post_json

    def intercepted(*args, **kwargs):
        stop(selected, role)
        return original_post(*args, **kwargs)

    transport.post_json = intercepted
    worker, _ = creature_worker(selected, transport)
    assert worker.run_once(upload.workspace_id) == "failed"
    assert len(transport.requests) == 1
    with services.database.session(upload.workspace_id) as connection:
        done = drafts.read_draft(connection, upload.workspace_id, made.draft_id)
        assert done.failure == "reference_withdrawn" and done.kind_sha256 is None
        assert done.reference_usage["state"] == "used"


@pytest.mark.postgres
def test_binding_is_readonly_and_new_typed_grant_cannot_retrofit(selected, spine_schema):
    upload, services, *_ = selected
    with services.database.session(upload.workspace_id) as connection:
        row = connection.execute(
            "select r.*,u.use_context from personal_model_right r "
            "join personal_model_right_use u using(workspace_id,right_id) limit 1"
        ).fetchone()
        for command in [
            "insert into personal_model_right_use select * from personal_model_right_use",
            "update personal_model_right_use set use_context=use_context",
            "delete from personal_model_right_use",
        ]:
            with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
                connection.execute(command)
        with pytest.raises(psycopg.errors.UniqueViolation), connection.transaction():
            connection.execute(
                "select grant_creature_note_model_right(%s,%s,%s,%s)",
                (
                    upload.workspace_id,
                    row["right_id"],
                    Jsonb(row["receipt_record"]),
                    Jsonb(row["use_context"]),
                ),
            )
        with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
            connection.execute(
                "select grant_creature_note_model_right(%s,%s,%s,%s)",
                (
                    uuid.uuid4(),
                    uuid.uuid4(),
                    Jsonb(row["receipt_record"]),
                    Jsonb(row["use_context"]),
                ),
            )
        context = row["use_context"] | {"notice": "invented notice"}
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            connection.execute(
                "select grant_creature_note_model_right(%s,%s,%s,%s)",
                (upload.workspace_id, uuid.uuid4(), Jsonb(row["receipt_record"]), Jsonb(context)),
            )
        assert connection.execute("select count(*) as n from personal_model_right_use").fetchone()[
            "n"
        ] == len(admission.role_handoff("creature_drafter").identities)
    readonly = scratch_role_database(spine_schema[1], "exulanica_picture_notes_ro")
    with (
        readonly.session(upload.workspace_id) as connection,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
        connection.transaction(),
    ):
        connection.execute(
            "select grant_creature_note_model_right(%s,%s,%s,%s)",
            (
                upload.workspace_id,
                row["right_id"],
                Jsonb(row["receipt_record"]),
                Jsonb(row["use_context"]),
            ),
        )


@pytest.mark.postgres
@pytest.mark.parametrize("selected", [("reference_vision",)], indirect=True)
@pytest.mark.parametrize("legacy_grant", [False, True])
def test_vision_right_and_unbound_creature_right_do_not_authorize_new_use(selected, legacy_grant):
    upload, services, capture, actor, *_ = selected
    if legacy_grant:
        with services.database.session(upload.workspace_id) as connection:
            authority = connection.execute(
                "select authorization_id,valid_until from capture_reconstruction_authorization "
                "where capture_id=%s order by authorized_at desc limit 1",
                (capture,),
            ).fetchone()
            handoff = admission.role_handoff("creature_drafter")
            for identity in handoff.identities:
                grant_model_right(
                    IngestRepository(connection, upload.workspace_id),
                    capture_id=capture,
                    authorization_id=authority["authorization_id"],
                    identity=identity,
                    destination=handoff.destination,
                    granted_by=actor,
                    purpose="legacy undeclared grant",
                    valid_until=authority["valid_until"],
                )
            assert (
                connection.execute("select count(*) as n from personal_model_right_use").fetchone()[
                    "n"
                ]
                == 0
            )
    queue(selected)
    worker, transport = creature_worker(selected)
    assert worker.run_once(upload.workspace_id) == "failed" and not transport.requests


@pytest.mark.postgres
@pytest.mark.parametrize("change", ["feature", "notice", "person", "erase"])
def test_current_use_and_source_are_rechecked_after_provider(selected, monkeypatch, change):
    from exulanica.ingest.person_review import record_region_edits

    upload, services, capture, actor, *_ = selected
    queue(selected)
    worker, transport = creature_worker(selected)
    original_post = transport.post_json

    def intercepted(*args, **kwargs):
        if change == "feature":
            # Dynamic callback reads the same Services instance's installation settings.
            object.__setattr__(worker.test_services, "reference_pictures", False)
        elif change == "notice":
            uses = admission.MODEL_RIGHT_USES
            monkeypatch.setattr(
                admission,
                "MODEL_RIGHT_USES",
                dataclasses.replace(
                    uses,
                    uses=tuple(
                        dataclasses.replace(use, detail=use.detail + " New words.")
                        if use.role == "creature_drafter"
                        else use
                        for use in uses.uses
                    ),
                ),
            )
        else:
            with services.database.session(upload.workspace_id) as connection:
                if change == "person":
                    record_region_edits(
                        IngestRepository(connection, upload.workspace_id),
                        capture_id=capture,
                        actor=actor,
                        edits=[
                            {
                                "action": "add",
                                "region_key": "bc" * 32,
                                "silhouette": {
                                    "kind": "polygon",
                                    "points": [[0, 0], [400000, 0], [400000, 400000], [0, 400000]],
                                },
                            }
                        ],
                    )
                else:
                    connection.execute(
                        "insert into tombstone(workspace_id,scope,capture_id,requested_by,reason) "
                        "values(%s,'capture',%s,%s,'erase source')",
                        (upload.workspace_id, capture, actor),
                    )
        return original_post(*args, **kwargs)

    transport.post_json = intercepted
    assert worker.run_once(upload.workspace_id) == "failed"
    assert len(transport.requests) == 1


@pytest.mark.postgres
@pytest.mark.parametrize("role", ["reference_vision", "creature_drafter"])
def test_already_kept_invented_definition_survives_stop(selected, role):
    upload, services, *_ = selected
    made = queue(selected)
    worker, _ = creature_worker(selected)
    assert worker.run_once(upload.workspace_id) == "kept"
    stop(selected, role)
    with services.database.session(upload.workspace_id) as connection:
        done = drafts.read_draft(connection, upload.workspace_id, made.draft_id)
        assert (
            ThingStore(connection, upload.workspace_id, None).kind_by_digest(done.kind_sha256)
            is not None
        )


@pytest.mark.postgres
@pytest.mark.parametrize("phase", [1, 2])
@pytest.mark.parametrize("mutation", ["reference_vision", "creature_drafter", "person"])
def test_publication_orders_actual_concurrent_mutation(selected, monkeypatch, phase, mutation):
    """A privacy mutation waits on the guard and is seen by the next publication phase.

    Each actual mutation and both checked transactions are exercised. Timeouts are failure;
    pg_stat_activity proves the mutation reached its database lock, avoiding timing guesses.
    """
    import time
    from concurrent.futures import ThreadPoolExecutor

    from exulanica.ingest.person_review import record_region_edits

    upload, services, capture, actor, *_ = selected
    queue(selected)
    worker, _ = creature_worker(selected)
    guarded = threading.Event()
    release = threading.Event()
    started = threading.Event()
    original = drafts._guard_reference
    seen = [0]
    backend = []

    def paused(*args, **kwargs):
        original(*args, **kwargs)
        seen[0] += 1
        if seen[0] == phase:
            guarded.set()
            assert release.wait(10), "publication was not released"

    monkeypatch.setattr(drafts, "_guard_reference", paused)

    def mutate():
        with services.database.session(upload.workspace_id) as connection:
            connection.execute("set lock_timeout='8s'")
            backend.append(connection.execute("select pg_backend_pid() as pid").fetchone()["pid"])
            started.set()
            if mutation in ("reference_vision", "creature_drafter"):
                right = connection.execute(
                    "select right_id from personal_model_right where model_role=%s limit 1",
                    (mutation,),
                ).fetchone()["right_id"]
                withdraw_model_right(
                    IngestRepository(connection, upload.workspace_id),
                    right_id=right,
                    withdrawn_by=actor,
                )
            else:
                record_region_edits(
                    IngestRepository(connection, upload.workspace_id),
                    capture_id=capture,
                    actor=actor,
                    edits=[
                        {
                            "action": "add",
                            "region_key": "bc" * 32,
                            "silhouette": {
                                "kind": "polygon",
                                "points": [[0, 0], [400000, 0], [400000, 400000], [0, 400000]],
                            },
                        }
                    ],
                )

    with ThreadPoolExecutor(max_workers=2) as pool:
        played = pool.submit(worker.run_once, upload.workspace_id)
        assert guarded.wait(10)
        changed = pool.submit(mutate)
        try:
            assert started.wait(5)
            limit = time.monotonic() + 5
            while time.monotonic() < limit:
                row = upload.repository.connection.execute(
                    "select wait_event_type from pg_stat_activity where pid=%s", (backend[0],)
                ).fetchone()
                if row and row["wait_event_type"] == "Lock":
                    break
                time.sleep(0.01)
            else:
                pytest.fail("mutation did not reach a database lock")
        finally:
            release.set()
        changed.result(timeout=10)
        result = played.result(timeout=10)
    # If phase 2 already passed, the definition committed before the stop, as the notice says.
    assert result == ("kept" if phase == 2 else "failed")


def _erase_selected_picture(connection, workspace, capture, actor):
    """One ordinary runtime deletion statement, without retrying a refusal."""
    return connection.execute(
        "insert into tombstone(workspace_id,scope,capture_id,requested_by,reason) "
        "values(%s,'capture',%s,%s,'erase source') returning tombstone_id",
        (workspace, capture, actor),
    ).fetchone()["tombstone_id"]


@pytest.mark.postgres
def test_accepted_source_erasure_between_store_phases_prevents_publication(selected, monkeypatch):
    """Pause in the real CAS write gap, after inventory commit and before the final transaction."""
    from concurrent.futures import ThreadPoolExecutor

    upload, services, capture, actor, reference, *_ = selected
    made = queue(selected)
    worker, _ = creature_worker(selected)
    looks = worker._looks_for(upload.workspace_id)
    written, release = threading.Event(), threading.Event()
    original_put = looks.put_bytes

    def paused_put(data):
        result = original_put(data)
        written.set()
        assert release.wait(10), "the CAS write gap was not released"
        return result

    monkeypatch.setattr(looks, "put_bytes", paused_put)
    monkeypatch.setattr(worker, "_looks_for", lambda _workspace: looks)
    with ThreadPoolExecutor(max_workers=1) as pool:
        played = pool.submit(worker.run_once, upload.workspace_id)
        try:
            assert written.wait(10), "the inventory committed but no CAS write was observed"
            with services.database.session(upload.workspace_id) as connection:
                connection.execute("set lock_timeout='5s'")
                inventory = connection.execute(
                    "select content_sha256 from look_object where workspace_id=%s",
                    (upload.workspace_id,),
                ).fetchall()
                assert len(inventory) == 1
                assert looks.exists(BlobId.from_hex(inventory[0]["content_sha256"]))
                assert connection.execute("select 1 from thing_kind_version").fetchone() is None
                _erase_selected_picture(connection, upload.workspace_id, capture, actor)
                withdrawn = store.read_request(
                    connection, upload.workspace_id, reference.reference_id
                )
                assert withdrawn.status == "withdrawn" and withdrawn.bundle is None
        finally:
            release.set()
        assert played.result(timeout=10) == "failed"
    with services.database.session(upload.workspace_id) as connection:
        done = drafts.read_draft(connection, upload.workspace_id, made.draft_id)
        assert done.failure == "reference_withdrawn" and done.kind_sha256 is None
        assert done.reference_usage["state"] == "used"
        for table in (
            "body_recipe_version",
            "body_plan_version",
            "look_version",
            "thing_kind_version",
        ):
            assert connection.execute(f"select 1 from {table}").fetchone() is None
        # The committed inventory and bytes remain reachable by ordinary workspace erasure.
        assert connection.execute("select 1 from look_object").fetchone() is not None


@pytest.mark.postgres
def test_source_erasure_is_busy_with_publication_workspace_lock_and_resend_is_ordered(
    selected, monkeypatch
):
    """A tombstone cannot wait for the publisher's workspace lock (0137): it rolls back 40001.

    After that exact refusal, publish under unchanged authority, then send the deletion once
    after the publisher finishes. The committed invented definition has ordinary retention.
    """
    from concurrent.futures import ThreadPoolExecutor

    upload, services, capture, actor, reference, *_ = selected
    made = queue(selected)
    worker, _ = creature_worker(selected)
    held, release = threading.Event(), threading.Event()
    original_guard = drafts._guard_reference
    phases = [0]

    def paused_guard(*args, **kwargs):
        phases[0] += 1
        if phases[0] == 2:
            # ThingStore already acquired workspace, but this guard has not taken privacy or
            # lifecycle. The deletion can reach its workspace try-lock and return busy.
            held.set()
            assert release.wait(10), "the publication workspace lock was not released"
        return original_guard(*args, **kwargs)

    monkeypatch.setattr(drafts, "_guard_reference", paused_guard)
    with ThreadPoolExecutor(max_workers=1) as pool:
        played = pool.submit(worker.run_once, upload.workspace_id)
        try:
            assert held.wait(10), "the final publication transaction was not reached"
            with services.database.session(upload.workspace_id) as connection:
                connection.execute("set lock_timeout='5s'")
                with (
                    pytest.raises(psycopg.errors.SerializationFailure) as busy,
                    connection.transaction(),
                ):
                    _erase_selected_picture(connection, upload.workspace_id, capture, actor)
                assert busy.value.sqlstate == "40001"
                assert busy.value.diag.message_primary == "workspace in use; retry the deletion"
                assert (
                    connection.execute(
                        "select 1 from tombstone where capture_id=%s", (capture,)
                    ).fetchone()
                    is None
                )
                current = store.read_request(
                    connection, upload.workspace_id, reference.reference_id
                )
                assert (
                    current.status == "complete"
                    and current.bundle_sha256 == reference.bundle_sha256
                )
                assert current.bundle is not None
                assert connection.execute("select 1 from thing_kind_version").fetchone() is None
        finally:
            release.set()
        assert played.result(timeout=10) == "kept"
    with services.database.session(upload.workspace_id) as connection:
        done = drafts.read_draft(connection, upload.workspace_id, made.draft_id)
        assert done.kind_sha256 is not None and done.reference_usage["state"] == "used"
        deletion = _erase_selected_picture(connection, upload.workspace_id, capture, actor)
        assert connection.execute(
            "select tombstone_id from tombstone where capture_id=%s", (capture,)
        ).fetchall() == [{"tombstone_id": deletion}]
        withdrawn = store.read_request(connection, upload.workspace_id, reference.reference_id)
        assert withdrawn.status == "withdrawn" and withdrawn.bundle is None
        assert (
            ThingStore(connection, upload.workspace_id, None).kind_by_digest(done.kind_sha256)
            is not None
        )


@pytest.mark.postgres
def test_picture_declarations_reach_policy_and_never_read_or_write_cache(selected):
    class RefusesCache:
        def get(self, _key):
            pytest.fail("image-derived request consulted response cache")

        def put(self, _key, _entry):
            pytest.fail("image-derived request retained cached note-derived content")

    upload, services, capture, *_ = selected
    queue(selected)
    policy = RecordingPolicy()
    transport = _transport(form_of("horse", label="green giant"))
    client = ModelClient(
        api_key="test-key",
        manifest=load_manifest(),
        transport=transport,
        budget=BudgetGuard(),
        policy=policy,
        cache=RefusesCache(),
    )
    worker = dataclasses.replace(services, model_client=client).build_creature_worker()
    assert worker.run_once(upload.workspace_id) == "kept"
    assert policy.requests and all(
        request.photographs == frozenset({capture}) for request in policy.requests
    )


@pytest.mark.postgres
def test_typed_grant_rolls_back_right_if_binding_fails_and_rejects_wrong_actor(selected):
    upload, services, *_ = selected
    with services.database.session(upload.workspace_id) as connection:
        row = connection.execute(
            "select r.receipt_record,u.use_context from personal_model_right r "
            "join personal_model_right_use u using(workspace_id,right_id) limit 1"
        ).fetchone()
        identifier = uuid.uuid4()
        fresh = row["receipt_record"] | {"purpose": "atomic binding rejection"}
        oversized = row["use_context"] | {"models": row["use_context"]["models"] * 9}
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            connection.execute(
                "select grant_creature_note_model_right(%s,%s,%s,%s)",
                (upload.workspace_id, identifier, Jsonb(fresh), Jsonb(oversized)),
            )
        assert (
            connection.execute(
                "select 1 from personal_model_right where right_id=%s", (identifier,)
            ).fetchone()
            is None
        )
        wrong_actor = fresh | {"granted_by": str(uuid.uuid4())}
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            connection.execute(
                "select grant_creature_note_model_right(%s,%s,%s,%s)",
                (upload.workspace_id, identifier, Jsonb(wrong_actor), Jsonb(row["use_context"])),
            )
        assert (
            connection.execute(
                "select 1 from personal_model_right_use where right_id=%s", (identifier,)
            ).fetchone()
            is None
        )


@pytest.mark.postgres
@pytest.mark.parametrize("role", ["reference_vision", "creature_drafter"])
def test_restore_replayed_stop_refuses_bound_picture_notes(selected, role):
    """Real replay applies a carried stop to the prior state, not a fabricated flag."""
    from exulanica.deletion.withdrawals import Carried, reapply
    from exulanica.orchestration.restore import WRITERS

    upload, services, _capture, actor, *_ = selected
    with services.database.session(upload.workspace_id) as connection:
        right_id = connection.execute(
            "select right_id from personal_model_right where model_role=%s limit 1", (role,)
        ).fetchone()["right_id"]
        binding = connection.execute(
            "select right_id,context_sha256 from personal_model_right_use"
        ).fetchall()
        with connection.transaction(force_rollback=True):
            withdraw_model_right(
                IngestRepository(connection, upload.workspace_id),
                right_id=right_id,
                withdrawn_by=actor,
            )
            stopped = connection.execute(
                "select workspace_id,right_id,withdrawn_at,withdrawn_by from personal_model_right "
                "where right_id=%s",
                (right_id,),
            ).fetchone()
            carried = Carried("model_right", {key: str(value) for key, value in stopped.items()})
        # Rollback represents a backup predating the stop, including the valid binding.
        assert reapply(connection, carried, WRITERS) == "carried"
        assert reapply(connection, carried, WRITERS) == "present"
        assert (
            connection.execute(
                "select right_id,context_sha256 from personal_model_right_use"
            ).fetchall()
            == binding
        )
    queue(selected)
    worker, transport = creature_worker(selected)
    assert worker.run_once(upload.workspace_id) == "failed" and not transport.requests


@pytest.mark.parametrize("refusal", ["shows_people", "shows_text", "not_a_thing"])
def test_creature_picture_reader_refuses_people_writing_and_non_things(refusal):
    from exulanica.references.pictures import read_picture

    transport = FakeTransport(
        responses=[
            _reading({"refuse": refusal, "notes": [{"aspect": "anatomy", "text": "rounded torso"}]})
        ]
    )
    client = ModelClient(
        api_key="test-key",
        manifest=load_manifest(),
        transport=transport,
        budget=BudgetGuard(),
        policy=RecordingPolicy(),
    )
    words = drafting.prompts_for_request("things", pictures=True)
    read = read_picture(
        client,
        b"\xff\xd8 synthetic rendition",
        capture_id=uuid.uuid4(),
        prompts=words,
        catalogs=drafting.catalogs_for_prompts(words),
    )
    assert read.refused == refusal and not read.notes
    assert "any part or depiction" in transport.requests[0]["payload"]["messages"][0]["content"]
    schema = json.dumps(transport.requests[0]["payload"]["response_format"])
    assert "not_a_thing" in schema and "not_a_place" not in schema


@pytest.mark.postgres
@pytest.mark.parametrize("selected", ["short"], indirect=True)
def test_right_expiry_while_provider_runs_prevents_keep(selected):
    import time

    upload, services, *_ = selected
    queue(selected)
    worker, transport = creature_worker(selected)
    original = transport.post_json

    def delayed(*args, **kwargs):
        with services.database.session(upload.workspace_id) as connection:
            remaining = connection.execute(
                "select greatest(0,extract(epoch from max(valid_until)-clock_timestamp())) "
                "as seconds "
                "from personal_model_right"
            ).fetchone()["seconds"]
        time.sleep(float(remaining) + 0.02)
        return original(*args, **kwargs)

    transport.post_json = delayed
    assert worker.run_once(upload.workspace_id) == "failed" and len(transport.requests) == 1


@pytest.mark.postgres
def test_entire_current_model_chain_is_required_even_for_primary_dispatch(selected):
    upload, services, _capture, actor, *_ = selected
    handoff = admission.role_handoff("creature_drafter")
    assert len(handoff.identities) > 1, "this fixture exercises the declared primary/fallback chain"
    fallback = handoff.identities[-1]
    with services.database.session(upload.workspace_id) as connection:
        right = connection.execute(
            "select right_id from personal_model_right where model_role=%s and model_id=%s",
            ("creature_drafter", fallback.model_id),
        ).fetchone()["right_id"]
        withdraw_model_right(
            IngestRepository(connection, upload.workspace_id), right_id=right, withdrawn_by=actor
        )
    queue(selected)
    worker, transport = creature_worker(selected)
    assert worker.run_once(upload.workspace_id) == "failed" and not transport.requests


@pytest.mark.postgres
@pytest.mark.parametrize("selected", ["mixed"], indirect=True)
def test_mixed_web_and_selected_picture_bases_are_kept_in_canonical_order(selected):
    upload, services, *_ = selected
    made = queue(selected)
    worker, transport = creature_worker(selected)
    assert worker.run_once(upload.workspace_id) == "kept"
    with services.database.session(upload.workspace_id) as connection:
        done = drafts.read_draft(connection, upload.workspace_id, made.draft_id)
        assert done.reference_usage["basis"] == ["web_description", "own_picture"]
        assert done.reference_usage["notes"] == 4
    assert "nearby reeds" in transport.requests[0]["payload"]["messages"][1]["content"]


@pytest.mark.postgres
def test_duplicate_unkeyed_admission_refuses_without_rebinding_or_partial_grant(selected):
    upload, *_ = selected
    before = upload.rows(
        "select right_id,context_sha256 from personal_model_right_use order by right_id"
    )
    response = post(upload, "/personal-admission", upload.personal_body)
    assert response.status_code == 409, response.text
    assert "fresh right" in response.json()["detail"]
    assert (
        upload.rows(
            "select right_id,context_sha256 from personal_model_right_use order by right_id"
        )
        == before
    )
