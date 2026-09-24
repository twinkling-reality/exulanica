"""The two source authorities an authored edit consults, pinned before they left the repository.

An environment instance and a placed photo point map each pin a source, and the object repository
asks a source authority, inside the edit's own transaction, whether that source may be used. This
file holds what those authorities must keep whatever module they live in:

* **lock order.** An edit takes the workspace advisory lock, then the version row, writes the log
  row and the version token, reaches the society hook, and only then takes the global asset read
  lock for its final authorization. A saved-world edit takes the saved entry's row between the
  workspace lock and the version row. Pinned twice: by the order of the statements the edit's own
  connection runs, and by probing, from a second connection at the society hook and after the
  asset read lock, which locks are actually held. Probing held locks rather than outcomes is
  deliberate: a writer that retries on deadlock passes an outcome test in the wrong order.
* **exact refusal classes.** Composition preview maps a refusal to its blocked reason by class, so
  each resolver refusal is asserted with ``type(...) is``, not ``isinstance``.
* **availability without a store.** An environment instance whose bindings stand reads ``unknown``
  without a store; a point map whose permissions stand reads ``available``, because its byte check
  runs only when a store is present. The asymmetry is today's behaviour, pinned so a move cannot
  change it silently.
* **the pinned reference agrees with the saved world.** A saved world's attachment and a point map
  resolved through it judge the same rows. For every state a person can reach (a deleted
  photograph, an expired authority, a removed reference) the two must refuse together.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest
from exulanica.ingest.spine.scope import WorkspaceScope
from exulanica.world import (
    EnvironmentBindingDrift,
    EnvironmentCompositionDenied,
    EnvironmentSelection,
    EnvironmentSourceWithdrawn,
    InvalidEnvironmentData,
    ObjectOrigin,
    SavedWorldEntryRepository,
    Transform,
    UnavailableAsset,
    UnknownWorldResource,
    WorldObjectRepository,
)
from exulanica.world.errors import (
    PointMapNotPermitted,
    SourceAuthorityExpired,
    SourceNotCurrentMembership,
)
from exulanica.world.photo_point_maps import PointMapPlacement

from pg_harness import open_scratch_connection
from test_photo_point_map_composition import Placed
from test_photo_point_map_composition import placed as imported_placed  # noqa: F401
from test_saved_world_entries_api import _attachment_body, _create_starter, _reviewed_source
from test_world_environment_composition_postgres import composed as imported_composed  # noqa: F401
from test_world_objects_api import objects_api as imported_objects_api  # noqa: F401

pytestmark = pytest.mark.postgres

#: The global asset read lock ``asset_read_lock()`` takes (migration 0041).
ASSET_READ_LOCK_KEY = 119_622_341


@pytest.fixture(name="composed")
def _composed_alias(request):
    return request.getfixturevalue("imported_composed")


@pytest.fixture(name="objects_api")
def _objects_api_alias(request):
    return request.getfixturevalue("imported_objects_api")


@pytest.fixture(name="placed")
def _placed_alias(request):
    return request.getfixturevalue("imported_placed")


# -- lock order ----------------------------------------------------------------------------------


class _Recording:
    """An edit's connection, recording each statement it runs and calling ``before`` first."""

    def __init__(self, connection, before=None) -> None:
        self._connection = connection
        self.statements: list[str] = []
        self.before = before

    def execute(self, query, params=None, **kwargs):
        text = " ".join(str(query).split())
        if self.before is not None:
            self.before(self.statements)
        self.statements.append(text)
        return self._connection.execute(query, params, **kwargs)

    def transaction(self, *args, **kwargs):
        return self._connection.transaction(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._connection, name)


class _Probe:
    """A second connection that asks which of the editor's locks are held right now."""

    def __init__(self, spine_schema, workspace_id, world_id, version_id) -> None:
        psycopg_module, scratch = spine_schema
        self.connection = open_scratch_connection(psycopg_module, scratch)
        WorkspaceScope(self.connection, workspace_id)
        self.workspace_id, self.world_id, self.version_id = workspace_id, world_id, version_id

    def held(self) -> dict[str, bool]:
        try:
            workspace_free = self.connection.execute(
                "select pg_try_advisory_xact_lock(hashtextextended(%s::text,880024)) as free",
                (self.workspace_id,),
            ).fetchone()["free"]
            asset_free = self.connection.execute(
                "select pg_try_advisory_xact_lock_shared(%s) as free", (ASSET_READ_LOCK_KEY,)
            ).fetchone()["free"]
            try:
                with self.connection.transaction():
                    self.connection.execute(
                        "select 1 from world_alternate_version where workspace_id=%s "
                        "and world_id=%s and version_id=%s for update nowait",
                        (self.workspace_id, self.world_id, self.version_id),
                    )
                version_free = True
            except psycopg.errors.LockNotAvailable:
                version_free = False
        finally:
            self.connection.rollback()
        return {
            "workspace": not workspace_free,
            "version_row": not version_free,
            "asset_read": not asset_free,
        }

    def close(self) -> None:
        self.connection.close()


def _first(statements: list[str], *needles: str) -> int:
    for index, statement in enumerate(statements):
        if all(needle in statement for needle in needles):
            return index
    raise AssertionError(f"no statement contains {needles}")


def _recorded_edit(worlds, spine_schema, version_id, edit, *, saved_entry=None):
    """Run ``edit(worlds)`` on a recording connection, probing locks at the two moments that matter.

    ``saved_entry`` is ``(entry, version)``: the saved world's lock is taken first, as the edit
    route takes it, and advanced after the edit.
    """
    probe = _Probe(spine_schema, worlds.workspace_id, worlds.world_id, version_id)
    observed: dict[str, dict[str, bool]] = {}

    def after_asset_lock(statements):
        if statements and statements[-1] == "select asset_read_lock()":
            observed.setdefault("after_asset_read_lock", probe.held())

    recording = _Recording(worlds.connection, before=after_asset_lock)

    def society_hook(_version_id):
        recording.statements.append("SOCIETY HOOK")
        observed["society_hook"] = probe.held()

    editor = WorldObjectRepository(
        recording,
        worlds.workspace_id,
        world_id=worlds.world_id,
        store=worlds.store,
        on_edit=society_hook,
    )
    entries = SavedWorldEntryRepository(recording, worlds.workspace_id)
    try:
        with recording.transaction():
            if saved_entry is not None:
                entry, version = saved_entry
                entries.lock_authored_advance_base(
                    uuid.UUID(entry["entry_id"]),
                    base_revision=entry["revision"],
                    world_id=worlds.world_id,
                    authored_version_id=version.version_id,
                    authored_state_sha256=version.state_sha256,
                    authored_edit_seq=version.edit_seq,
                    mutation_base_state_sha256=version.state_sha256,
                )
            result = edit(editor)
            if saved_entry is not None:
                entries.advance_authored_locked(
                    uuid.UUID(entry["entry_id"]),
                    base_revision=entry["revision"],
                    world_id=worlds.world_id,
                    authored_version_id=result.version_id,
                    result_state_sha256=result.state_sha256,
                    result_edit_seq=result.edit_seq,
                )
    finally:
        probe.close()
    return recording.statements, observed


def _assert_edit_lock_order(statements, observed):
    workspace = _first(statements, "pg_advisory_xact_lock(hashtextextended(")
    version_row = _first(statements, "from world_alternate_version where", "for update")
    edit_row = _first(statements, "insert into world_alternate_version_edit")
    token = _first(statements, "update world_alternate_version set state_sha256")
    hook = statements.index("SOCIETY HOOK")
    asset_read = statements.index("select asset_read_lock()")
    assert workspace < version_row < edit_row < token < hook < asset_read, statements
    # Held, not merely issued: the workspace and the version row belong to this edit by the time
    # its society hook runs, while the global asset read lock is still free.
    assert observed["society_hook"] == {"workspace": True, "version_row": True, "asset_read": False}
    assert observed["after_asset_read_lock"] == {
        "workspace": True,
        "version_row": True,
        "asset_read": True,
    }
    return workspace


def test_an_environment_edit_takes_its_locks_in_order(composed, spine_schema):
    composed.worlds.connection.commit()
    version = composed.version
    statements, observed = _recorded_edit(
        composed.worlds,
        spine_schema,
        version.version_id,
        lambda editor: editor.add_environment(
            version.version_id,
            composed.placement("environment:ordered", feature=True),
            base_state_sha256=version.state_sha256,
            actor=uuid.uuid4(),
        ),
    )
    _assert_edit_lock_order(statements, observed)


def test_a_saved_world_point_map_edit_takes_its_locks_in_order(placed, spine_schema):
    worlds = placed.worlds()
    version = worlds.version(uuid.UUID(placed.version_id))
    entry = placed.stored_entry()
    statements, observed = _recorded_edit(
        worlds,
        spine_schema,
        version.version_id,
        lambda editor: editor.add_point_map(
            version.version_id,
            _point_map_placement(placed),
            base_state_sha256=version.state_sha256,
            actor=uuid.uuid4(),
        ),
        saved_entry=(entry, version),
    )
    workspace = _assert_edit_lock_order(statements, observed)
    saved_row = _first(statements, "from saved_world_entry where", "for update")
    version_row = _first(statements, "from world_alternate_version where", "for update")
    advance = _first(statements, "update saved_world_entry")
    assert workspace < saved_row < version_row, statements
    assert statements.index("select asset_read_lock()") < advance, statements


# -- exact refusal classes -----------------------------------------------------------------------


def _environment_refusal(composed, case):
    worlds = composed.worlds
    whole = composed.placement("environment:refused")
    if case == "unknown binding":
        return lambda: worlds.validate_environment_source(
            composed.source.admission_id, uuid.uuid4(), None, EnvironmentSelection("whole_asset")
        )
    if case == "no store":
        storeless = WorldObjectRepository(
            worlds.connection, worlds.workspace_id, world_id=worlds.world_id, store=None
        )
        return lambda: storeless.validate_environment_source(
            whole.admission_id, whole.render_asset_id, None, whole.selection
        )
    if case == "whole asset naming a publication":
        return lambda: worlds.validate_environment_source(
            whole.admission_id,
            whole.render_asset_id,
            composed.publication.publication_id,
            whole.selection,
        )
    if case == "resolved source for another placement":
        resolved = worlds.validate_environment_source(
            whole.admission_id, whole.render_asset_id, None, whole.selection
        )
        feature = composed.placement("environment:other", feature=True)
        return lambda: worlds.validate_environment_placement(
            composed.version.version_id,
            feature,
            base_state_sha256=composed.version.state_sha256,
            resolved_source=resolved,
        )
    if case == "withdrawn":
        composed.environments.withdraw("asset", composed.render.asset_id)
    elif case == "drifted publication":
        return _drifted(composed)
    return lambda: worlds.validate_environment_source(
        whole.admission_id, whole.render_asset_id, None, whole.selection
    )


def _drifted(composed):
    from exulanica.environment import FeatureIndexPublication

    old = composed.publication.publication_id
    composed.worlds.connection.commit()
    composed.environments.publish_feature_index(
        composed.source.admission_id,
        FeatureIndexPublication(render_asset_id=composed.render.asset_id, features=()),
        actor=uuid.uuid4(),
    )
    feature = composed.placement("environment:drifted", feature=True, publication_id=old)
    return lambda: composed.worlds.validate_environment_source(
        feature.admission_id, feature.render_asset_id, old, feature.selection
    )


@pytest.mark.parametrize(
    ("case", "refusal"),
    [
        ("unknown binding", UnknownWorldResource),
        ("no store", UnavailableAsset),
        ("whole asset naming a publication", InvalidEnvironmentData),
        ("resolved source for another placement", ValueError),
        ("withdrawn", EnvironmentSourceWithdrawn),
        ("drifted publication", EnvironmentBindingDrift),
    ],
)
def test_each_environment_source_refusal_is_its_exact_class(composed, case, refusal):
    call = _environment_refusal(composed, case)
    with pytest.raises(Exception) as refused:
        call()
    assert type(refused.value) is refusal, (case, type(refused.value), refused.value)


def test_a_render_asset_without_compose_rights_is_refused_with_its_exact_class(composed, tmp_path):
    """The rights check, reached through an asset registered with compose withheld."""
    import hashlib

    from exulanica.environment import DerivedEnvironmentAsset

    from test_world_environment_composition_postgres import _bounds, _frame, _rights

    denied_bytes = b"render registered without compose"
    denied_path = tmp_path / "denied.glb"
    denied_path.write_bytes(denied_bytes)
    denied = DerivedEnvironmentAsset(
        admission_id=composed.source.admission_id,
        expected_sha256=hashlib.sha256(denied_bytes).hexdigest(),
        expected_byte_size=len(denied_bytes),
        media_type="model/gltf-binary",
        derivation_kind="denied",
        derivation_lineage={
            "method": "fixture/v1",
            "input_sha256": [composed.source.expected_sha256],
        },
        geographic_frame=_frame(),
        geographic_bounds=_bounds(),
        operation_rights=_rights(compose=False),
        attribution="Synthetic fixture",
        modification_notice="Denied composition fixture",
        local_path=denied_path,
    )
    composed.environments.register_derived(denied, actor=uuid.uuid4())
    with pytest.raises(Exception) as refused:
        composed.worlds.validate_environment_source(
            composed.source.admission_id, denied.asset_id, None, EnvironmentSelection("whole_asset")
        )
    assert type(refused.value) is EnvironmentCompositionDenied


def _point_map_placement(placed, instance_id="point-map:pinned") -> PointMapPlacement:
    return PointMapPlacement(
        instance_id=instance_id,
        entry_id=uuid.UUID(placed.entry["entry_id"]),
        attachment_id=uuid.UUID(placed.attachment_id),
        region_id=placed.region_id,
        transform=Transform(1_200, 0, -450, 785_398, 1_000),
        origin=ObjectOrigin("authored", "personal"),
    )


def test_each_point_map_source_refusal_is_its_exact_class(placed):
    from exulanica.ingest.model_rights import withdraw_model_right

    worlds = placed.worlds()
    entry_id, attachment_id = uuid.UUID(placed.entry["entry_id"]), uuid.UUID(placed.attachment_id)
    storeless = _with_store(worlds, None)
    cases = [
        (lambda: worlds.validate_point_map_source(entry_id, uuid.uuid4()), UnknownWorldResource),
        (lambda: storeless.validate_point_map_source(entry_id, attachment_id), UnavailableAsset),
    ]
    for call, refusal in cases:
        with pytest.raises(Exception) as refused:
            call()
        assert type(refused.value) is refusal, (refusal, refused.value)
    withdraw_model_right(
        placed.repository, right_id=placed.right.right_id, withdrawn_by=placed.api.actor
    )
    with pytest.raises(Exception) as refused:
        worlds.validate_point_map_source(entry_id, attachment_id)
    assert type(refused.value) is PointMapNotPermitted
    assert placed.detach().status_code == 200
    with pytest.raises(Exception) as refused:
        worlds.validate_point_map_source(entry_id, attachment_id)
    assert type(refused.value) is SourceNotCurrentMembership


def _with_store(worlds: WorldObjectRepository, store) -> WorldObjectRepository:
    return WorldObjectRepository(
        worlds.connection, worlds.workspace_id, world_id=worlds.world_id, store=store
    )


# -- availability without a store ----------------------------------------------------------------


def test_availability_without_a_store_is_unknown_for_an_environment(composed):
    version = composed.worlds.add_environment(
        composed.version.version_id,
        composed.placement("environment:storeless"),
        base_state_sha256=composed.version.state_sha256,
        actor=uuid.uuid4(),
    )
    storeless = _with_store(composed.worlds, None)
    [instance] = storeless.version(version.version_id).environment_instances
    assert instance.availability == "unknown"
    [with_store] = composed.worlds.version(version.version_id).environment_instances
    assert with_store.availability == "available"


def test_availability_without_a_store_is_available_for_a_point_map(placed):
    worlds = placed.worlds()
    version = worlds.version(uuid.UUID(placed.version_id))
    version = worlds.add_point_map(
        version.version_id,
        _point_map_placement(placed),
        base_state_sha256=version.state_sha256,
        actor=uuid.uuid4(),
    )
    [instance] = _with_store(worlds, None).version(version.version_id).point_map_instances
    assert (instance.availability, instance.unavailable_reason) == ("available", None)


# -- the pinned reference agrees with the saved world --------------------------------------------


def _saved_verdict(placed) -> tuple[str, str | None]:
    attachments = {
        item["attachment_id"]: item for item in placed.stored_entry()["source_attachments"]
    }
    current = attachments.get(placed.attachment_id)
    if current is None:
        return ("not_current", None)
    return (current["availability"], current["unavailable_reason"])


def _resolver_verdict(placed) -> type[Exception] | None:
    try:
        placed.worlds().validate_point_map_source(
            uuid.UUID(placed.entry["entry_id"]), uuid.UUID(placed.attachment_id)
        )
    except Exception as exc:  # the class is the verdict
        return type(exc)
    return None


def test_a_standing_reference_is_available_to_both(placed):
    assert _saved_verdict(placed) == ("available", None)
    assert _resolver_verdict(placed) is None


def test_a_deleted_photograph_is_refused_by_both(placed):
    placed.repository.connection.execute(
        "update capture set deleted_at=clock_timestamp() where workspace_id=%s and capture_id=%s",
        (placed.repository.workspace_id, uuid.UUID(placed.source["capture_id"])),
    )
    placed.repository.connection.commit()
    assert _saved_verdict(placed) == ("unavailable", "source_unavailable")
    assert _resolver_verdict(placed) is UnknownWorldResource


def test_a_removed_reference_is_refused_by_both(placed):
    assert placed.detach().status_code == 200
    assert _saved_verdict(placed) == ("not_current", None)
    assert _resolver_verdict(placed) is SourceNotCurrentMembership


def test_an_expired_authority_is_refused_by_both(repository, objects_api):
    """Receipts are append-only, so the authority is recorded with a short term and waited out."""
    entry = _create_starter(objects_api)
    source = _reviewed_source(repository, objects_api, minute=8, valid_for_seconds=2)
    entry = objects_api.post(
        f"/world-entries/{entry['entry_id']}/source-attachments", _attachment_body(entry, source)
    ).json()
    repository.connection.commit()
    expiring = Placed(objects_api, repository, entry, source, None)
    # The control: while it stands, both pass the reference checks and the resolver stops later,
    # at the missing depth permission.
    assert _saved_verdict(expiring) == ("available", None)
    assert _resolver_verdict(expiring) is PointMapNotPermitted
    expiry = repository.connection.execute(
        "select valid_until from capture_reconstruction_authorization "
        "where workspace_id=%s and authorization_id=%s",
        (repository.workspace_id, uuid.UUID(source["authorization_id"])),
    ).fetchone()["valid_until"]
    repository.connection.execute(
        "select pg_sleep(greatest(0,extract(epoch from (%s-clock_timestamp())))+0.05)", (expiry,)
    )
    repository.connection.commit()
    assert _saved_verdict(expiring) == ("unavailable", "authorization_expired")
    assert _resolver_verdict(expiring) is SourceAuthorityExpired
