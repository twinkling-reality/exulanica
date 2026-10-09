"""A workspace keeps its own style packs (migration 0173), through the repository, as deployed.

The repository runs as the provisioned runtime role, which neither owns the schema nor bypasses
row-level security; the purge runs as the purge role. The ``purged`` fixture supplies a workspace,
both roles and a tombstone helper. Manifests here are opaque bytes: what a manifest says is the
admission's to decide (``tests/test_style_packs.py``), and this file holds what the database keeps.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from exulanica.db.definer_role import DEFINER_ROLE
from exulanica.db.session import set_workspace
from exulanica.deletion import queue
from exulanica.deletion.worker import PurgeWorker
from exulanica.evidence.blob import BlobId
from exulanica.store.configured import local_content_stores
from exulanica.world.workspace_preparations import retained_bytes_refusal
from exulanica.world.workspace_style_packs import (
    AdmittedStylePack,
    PackBase,
    PackFile,
    StylePackAttemptsExceeded,
    StylePackExists,
    StylePackIsABase,
    StylePackNotCreator,
    StylePackNotReady,
    StylePackPublishLicenceNotHeld,
    StylePackQuotaExceeded,
    StylePackVersionExists,
    StylePackWithdrawn,
    UnknownStylePack,
    WorkspaceStylePackRepository,
)

from test_purge import _APP_PASSWORD, _APP_ROLE, _PURGE_PASSWORD, _PURGE_ROLE
from test_purge import purged as purged

pytestmark = pytest.mark.postgres


def admitted(
    pack_id: str = "maker.cozy-barn",
    version: int = 1,
    *,
    pieces: int = 2,
    salt: str = "",
    base: PackBase | None = None,
    declaration: bytes = b'{"rights":{"basis":"own_work"}}',
) -> AdmittedStylePack:
    """An admitted version with ``pieces`` piece files and a preview, as admission hands it on."""
    contents = {
        f"pieces/p{n}.glb": f"piece {n} of {pack_id} {salt}".encode() for n in range(pieces)
    }
    contents["preview.png"] = f"preview of {pack_id} {version} {salt}".encode()
    files = tuple(
        PackFile(
            path,
            hashlib.sha256(data).hexdigest(),
            len(data),
            "image/png" if path.endswith(".png") else "model/gltf-binary",
        )
        for path, data in sorted(contents.items())
    )
    manifest = json.dumps(
        {"pack_id": pack_id, "version": version, "salt": salt, "files": sorted(contents)},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return AdmittedStylePack(
        manifest_canonical=manifest,
        pack_id=pack_id,
        version=version,
        declaration_canonical=declaration,
        rights_basis="own_work",
        licence_id="LicenseRef-Exulanica-Own-Work",
        base=base,
        files=files,
        contents={file.content_sha256: contents[file.path] for file in files if file.path},
        preview_sha256=next(f.content_sha256 for f in files if f.media_type == "image/png"),
        receipt={"checks": ["body", "declaration", "manifest", "pieces", "preview"]},
    )


def base_of(pack: AdmittedStylePack) -> PackBase:
    return PackBase("workspace", pack.pack_id, pack.version, pack.manifest_sha256)


class Packs:
    """One workspace's style packs as the runtime role writes them, and the owner's view."""

    def __init__(self, purged, tmp_path: Path) -> None:
        self.purged = purged
        self.workspace_id = purged.workspace_id
        self.actor = uuid.uuid4()
        #: The installation's stores as every process builds them; the packs' own namespace is
        #: read through them, as the purge command, maintenance and restore replay read it.
        self.content = local_content_stores(tmp_path / "data")
        self.stores = self.content.workspace_style_packs
        self.runtime = purged.database(role=_APP_ROLE, password=_APP_PASSWORD)
        self._sessions = contextlib.ExitStack()
        self.connection = self._sessions.enter_context(self.runtime.session(self.workspace_id))

    def close(self) -> None:
        self._sessions.close()

    def repository(self, **limits: Any) -> WorkspaceStylePackRepository:
        return WorkspaceStylePackRepository(
            self.connection, self.workspace_id, self.actor, stores=self.stores, **limits
        )

    @staticmethod
    def repository_on(connection: psycopg.Connection, packs: Packs) -> WorkspaceStylePackRepository:
        """The repository over another session of the same workspace, as a fresh request has."""
        return WorkspaceStylePackRepository(
            connection, packs.workspace_id, packs.actor, stores=packs.stores
        )

    def owner_rows(self, statement: str, *parameters: Any) -> list[dict[str, Any]]:
        return self.purged.rows(statement, *parameters)

    def ready(self, pack: AdmittedStylePack) -> None:
        repository = self.repository()
        repository.record(pack)
        claimed = repository.claim("test-worker", 60)
        assert claimed is not None and claimed[0] == pack.manifest_sha256, claimed
        repository.finish_ready(pack.manifest_sha256, claimed[1], {"pieces": "measured"})

    def in_namespace(self, digest: str) -> bool:
        return self.stores.for_workspace(self.workspace_id).exists(BlobId.from_hex(digest))

    def production_purge(self) -> PurgeWorker:
        """The purge worker as the purge command, maintenance and restore replay build it."""
        return PurgeWorker.over(
            self.purged.database(role=_PURGE_ROLE, password=_PURGE_PASSWORD),
            self.content,
            frozenset({self.workspace_id}),
            name="test-style-pack-purge",
        )

    def purge_worker(self) -> PurgeWorker:
        return PurgeWorker(
            self.purged.database(role=_PURGE_ROLE, password=_PURGE_PASSWORD),
            self.purged.store,
            frozenset({self.workspace_id}),
            name="test-style-pack-purge",
            workspace_style_pack_stores=self.stores,
        )


@pytest.fixture
def packs(purged, tmp_path) -> Iterator[Packs]:
    made = Packs(purged, tmp_path)
    yield made
    made.close()


# -- recording ------------------------------------------------------------------------------


def test_a_version_is_recorded_with_its_files_and_waits_for_its_check(packs):
    pack = admitted()
    record, created = packs.repository().record(pack)
    assert created
    assert (record.pack_id, record.version, record.state) == ("maker.cozy-barn", 1, "requested")
    assert (record.file_count, record.manifest_canonical) == (3, pack.manifest_canonical)
    assert not record.ready and not packs.repository().wearable(pack.manifest_sha256)
    listed = packs.repository().files(pack.manifest_sha256)
    assert [file.path for file in listed] == ["pieces/p0.glb", "pieces/p1.glb", "preview.png"]
    assert all(packs.in_namespace(file.content_sha256) for file in listed)

    # The same bytes under the same declaration answer the version held, and write again a file
    # the namespace lost.
    lost = listed[0].content_sha256
    path = next((packs.stores.root / packs.workspace_id.hex).rglob(lost))
    path.unlink()
    again, created_again = packs.repository().record(pack)
    assert not created_again and again.manifest_sha256 == pack.manifest_sha256
    assert packs.in_namespace(lost)


def test_a_held_manifest_or_version_is_never_recorded_twice(packs):
    pack = admitted()
    packs.repository().record(pack)
    with pytest.raises(StylePackExists):
        packs.repository().record(
            admitted(declaration=b'{"rights":{"basis":"own_work","statement":"other"}}')
        )
    with pytest.raises(StylePackVersionExists) as refused:
        packs.repository().record(admitted(salt="another manifest"))
    assert refused.value.held_manifest_sha256 == pack.manifest_sha256


def test_the_runtime_role_appends_and_never_rewrites_a_version(packs):
    pack = admitted()
    packs.repository().record(pack)
    for statement in (
        "update workspace_style_pack_version set version = 2",
        "update workspace_style_pack_file set path = 'elsewhere.glb'",
        "delete from workspace_style_pack_blob",
        "insert into installation_style_pack_day (attempt_day, attempts) values (current_date, 1)",
        "update installation_style_pack_total set retained_bytes = 0",
        "insert into workspace_style_pack_attempt_day (workspace_id, attempt_day, attempts) "
        f"values ('{packs.workspace_id}', current_date, 1)",
    ):
        with (
            pytest.raises(psycopg.errors.InsufficientPrivilege),
            packs.connection.transaction(),
        ):
            packs.connection.execute(statement)


def test_another_workspace_sees_none_of_it(packs, purged):
    pack = admitted()
    packs.repository().record(pack)
    stranger = uuid.uuid4()
    with packs.runtime.session(stranger) as connection:
        other = WorkspaceStylePackRepository(
            connection, stranger, uuid.uuid4(), stores=packs.stores
        )
        assert other.versions() == []
        with pytest.raises(UnknownStylePack):
            other.version(pack.manifest_sha256)
        assert not other.wearable(pack.manifest_sha256)
        assert (
            connection.execute("select count(*) as n from workspace_style_pack_blob").fetchone()[
                "n"
            ]
            == 0
        )


# -- wearing, withdrawing and the base chain -------------------------------------------------


def test_a_ready_version_is_worn_until_it_is_withdrawn(packs):
    pack = admitted()
    packs.ready(pack)
    repository = packs.repository()
    assert repository.version(pack.manifest_sha256).ready
    assert repository.wearable(pack.manifest_sha256)
    assert repository.withdraw(pack.manifest_sha256) is True
    assert repository.withdraw(pack.manifest_sha256) is False
    record = repository.version(pack.manifest_sha256)
    assert (record.withdrawn, record.ready) == (True, False)
    assert not repository.wearable(pack.manifest_sha256)
    with pytest.raises(StylePackWithdrawn):
        repository.record(pack)


def test_a_base_is_not_withdrawn_while_a_live_version_is_drawn_on_it(packs):
    base = admitted("maker.barn")
    packs.ready(base)
    drawn = admitted("maker.barn-night", base=base_of(base))
    packs.repository().record(drawn)
    with pytest.raises(StylePackIsABase, match=r"maker\.barn-night version 1"):
        packs.repository().withdraw(base.manifest_sha256)
    repository = packs.repository()
    claimed = repository.claim("test-worker", 60)
    assert claimed is not None
    repository.finish_ready(drawn.manifest_sha256, claimed[1], {})
    assert repository.wearable(drawn.manifest_sha256)
    # Withdrawing the drawn version releases its base.
    repository.withdraw(drawn.manifest_sha256)
    assert repository.withdraw(base.manifest_sha256) is True


def test_a_ready_version_holds_its_base_against_withdrawal(packs):
    base = admitted("maker.barn")
    packs.ready(base)
    drawn = admitted("maker.barn-night", base=base_of(base))
    packs.ready(drawn)
    with pytest.raises(StylePackIsABase, match=r"maker\.barn-night version 1"):
        packs.repository().withdraw(base.manifest_sha256)


@pytest.mark.parametrize("state", ["running", "interrupted"])
def test_a_running_or_interrupted_version_holds_its_base_against_withdrawal(packs, state):
    base = admitted("maker.barn")
    packs.ready(base)
    drawn = admitted("maker.barn-night", base=base_of(base))
    repository = packs.repository()
    repository.record(drawn)
    claimed = repository.claim("test-worker", 60)
    assert claimed is not None and claimed[0] == drawn.manifest_sha256
    if state == "interrupted":
        repository.finish_failed(drawn.manifest_sha256, claimed[1], "interrupted", "stopped", {})
    with pytest.raises(StylePackIsABase, match=r"maker\.barn-night version 1"):
        repository.withdraw(base.manifest_sha256)


def test_a_version_is_drawn_only_on_a_workspace_base_that_may_be_worn(packs):
    base = admitted("maker.barn")
    packs.repository().record(base)
    with pytest.raises(psycopg.errors.CheckViolation, match="may be worn now"):
        packs.repository().record(admitted("maker.barn-night", base=base_of(base)))


def test_a_version_whose_base_stopped_being_wearable_fails_rather_than_becoming_ready(packs):
    base = admitted("maker.barn")
    packs.ready(base)
    drawn = admitted("maker.barn-night", base=base_of(base))
    repository = packs.repository()
    repository.record(drawn)
    claimed = repository.claim("test-worker", 60)
    assert claimed is not None
    # A withdrawal written past every trigger, which no product path and no restore does (a restore
    # replays through the guard, tests/test_restore_replay_withdrawals.py): the readiness guard is a
    # second wall, asking the chain again rather than trusting what held when the check was claimed.
    with packs.purged.database().session(packs.workspace_id) as owner:
        owner.execute("set session_replication_role = replica")
        owner.execute(
            "insert into workspace_style_pack_withdrawal (workspace_id, manifest_sha256, "
            "withdrawn_by) values (%s, %s, %s)",
            (packs.workspace_id, base.manifest_sha256, packs.actor),
        )
    repository.finish_ready(drawn.manifest_sha256, claimed[1], {})
    record = repository.version(drawn.manifest_sha256)
    assert (record.state, record.failure_class) == ("failed", "base_unavailable")
    assert not repository.wearable(drawn.manifest_sha256)


def test_readiness_and_a_tombstones_lock_order_cannot_deadlock(packs, monkeypatch):
    """A guarded write (a tombstone first among them) takes the 0041 barrier's shared side, then
    the workspace's lifecycle lock. Readiness holds the lifecycle lock; were it then to wait for
    the barrier's exclusive side, the two would wait on each other until PostgreSQL broke one."""
    import threading

    from exulanica.world import workspace_style_packs

    # Once, with no retry: a deadlock PostgreSQL broke would otherwise be retried out of sight.
    monkeypatch.setattr(workspace_style_packs, "retrying", lambda operation: operation())
    pack = admitted()
    repository = packs.repository()
    repository.record(pack)
    claimed = repository.claim("test-worker", 60)
    assert claimed is not None
    held, asked, failures = threading.Event(), threading.Event(), []
    with packs.purged.database().session(packs.workspace_id) as writer:

        def guarded_write() -> None:
            try:
                with writer.transaction():
                    writer.execute("set local lock_timeout = '10s'")
                    assert writer.execute(
                        "select pg_try_advisory_xact_lock_shared(119622341) as held"
                    ).fetchone()["held"]
                    held.set()
                    asked.wait(10)
                    writer.execute(
                        "select workspace_asset_lifecycle_lock(%s)", (packs.workspace_id,)
                    )
            except Exception as error:
                failures.append(error)

        thread = threading.Thread(target=guarded_write)
        thread.start()
        assert held.wait(10)
        timer = threading.Timer(0.5, asked.set)
        timer.start()
        try:
            repository.finish_ready(pack.manifest_sha256, claimed[1], {})
        except Exception as error:
            failures.append(error)
        thread.join(30)
        timer.cancel()
    assert failures == []
    assert repository.version(pack.manifest_sha256).state == "ready"


def test_an_interrupted_check_is_asked_again_and_a_refused_one_is_final(packs):
    interrupted, refused = admitted("maker.one"), admitted("maker.two")
    repository = packs.repository()
    repository.record(interrupted)
    repository.record(refused)
    for pack, failure in ((interrupted, "interrupted"), (refused, "refused")):
        claimed = repository.claim("test-worker", 60)
        assert claimed is not None and claimed[0] == pack.manifest_sha256
        repository.finish_failed(pack.manifest_sha256, claimed[1], failure, "it stopped", {})
    assert repository.request_again(interrupted.manifest_sha256) is True
    assert repository.request_again(refused.manifest_sha256) is False
    assert repository.version(interrupted.manifest_sha256).state == "requested"
    assert repository.version(refused.manifest_sha256).state == "failed"


def test_a_ready_versions_file_is_delivered_only_while_it_may_be_worn(packs):
    pack = admitted()
    repository = packs.repository()
    repository.record(pack)
    piece = pack.files[0]
    with pytest.raises(StylePackNotReady):
        repository.read_file(pack.manifest_sha256, piece.content_sha256)
    claimed = repository.claim("test-worker", 60)
    assert claimed is not None
    repository.finish_ready(pack.manifest_sha256, claimed[1], {})
    output = repository.read_file(pack.manifest_sha256, piece.content_sha256)
    try:
        assert (output.byte_size, output.media_type) == (piece.byte_size, piece.media_type)
        assert b"".join(output.chunks()) == pack.contents[piece.content_sha256]
    finally:
        output.close()
    with pytest.raises(UnknownStylePack):
        repository.read_file(pack.manifest_sha256, "0" * 64)
    repository.withdraw(pack.manifest_sha256)
    with pytest.raises(StylePackWithdrawn):
        repository.read_file(pack.manifest_sha256, piece.content_sha256)


def test_a_check_whose_worker_keeps_stopping_ends_interrupted_and_may_be_asked_again(packs):
    pack = admitted()
    repository = packs.repository()
    repository.record(pack)
    for _ in range(3):
        claimed = repository.claim("a worker that stops", 0, max_attempts=3)
        assert claimed is not None
    assert repository.claim("a worker that stops", 0, max_attempts=3) is None
    assert repository.expire_exhausted(max_attempts=3) == 1
    record = repository.version(pack.manifest_sha256)
    assert (record.state, record.failure_class, record.attempts) == ("failed", "interrupted", 3)
    assert repository.request_again(pack.manifest_sha256) is True
    assert repository.claim("a worker that finishes", 60) is not None


def test_only_the_creator_asks_for_a_ready_version_to_be_published(packs):
    pack = admitted()
    repository = packs.repository()
    repository.record(pack)
    with pytest.raises(StylePackNotReady):
        repository.request_publish(
            pack.manifest_sha256, licence_id="CC0-1.0", attribution=None, statement="mine to give"
        )
    claimed = repository.claim("test-worker", 60)
    assert claimed is not None
    repository.finish_ready(pack.manifest_sha256, claimed[1], {})
    someone = WorkspaceStylePackRepository(
        packs.connection, packs.workspace_id, uuid.uuid4(), stores=packs.stores
    )
    with pytest.raises(StylePackNotCreator):
        someone.request_publish(
            pack.manifest_sha256, licence_id="CC0-1.0", attribution=None, statement="not mine"
        )
    request_id = repository.request_publish(
        pack.manifest_sha256, licence_id="CC-BY-4.0", attribution="A maker", statement="mine"
    )
    assert isinstance(request_id, uuid.UUID)


def test_a_licensed_version_passes_on_only_its_own_licence(packs):
    made = admitted("maker.lent")
    fields = {name: getattr(made, name) for name in AdmittedStylePack.__dataclass_fields__}
    licensed = AdmittedStylePack(**{**fields, "rights_basis": "licensed", "licence_id": "CC0-1.0"})
    packs.ready(licensed)
    repository = packs.repository()
    with pytest.raises(StylePackPublishLicenceNotHeld):
        repository.request_publish(
            licensed.manifest_sha256, licence_id="CC-BY-4.0", attribution="Me", statement="mine"
        )
    repository.request_publish(
        licensed.manifest_sha256, licence_id="CC0-1.0", attribution=None, statement="as it came"
    )


# -- bounds -----------------------------------------------------------------------------------


def test_attempts_are_counted_per_workspace_and_installation_day(packs):
    repository = packs.repository()
    repository.count_attempt(workspace_limit=2, installation_limit=10)
    repository.count_attempt(workspace_limit=2, installation_limit=10)
    with pytest.raises(StylePackAttemptsExceeded) as refused:
        repository.count_attempt(workspace_limit=2, installation_limit=10)
    assert refused.value.bound == "workspace"
    with pytest.raises(StylePackAttemptsExceeded) as refused:
        repository.count_attempt(workspace_limit=5, installation_limit=2)
    assert refused.value.bound == "installation"
    days = packs.owner_rows("select attempts from installation_style_pack_day")
    assert [row["attempts"] for row in days] == [2]


def test_a_limit_below_one_admits_no_attempt_and_counts_none(packs):
    repository = packs.repository()
    for workspace_limit, installation_limit, bound in (
        (0, 10, "workspace"),
        (-1, 10, "workspace"),
        (10, 0, "installation"),
    ):
        with pytest.raises(StylePackAttemptsExceeded) as refused:
            repository.count_attempt(
                workspace_limit=workspace_limit, installation_limit=installation_limit
            )
        assert refused.value.bound == bound
    assert not packs.owner_rows("select attempts from workspace_style_pack_attempt_day")
    assert not packs.owner_rows("select attempts from installation_style_pack_day")
    # A limit of one admits the day's first attempt and no second.
    repository.count_attempt(workspace_limit=1, installation_limit=1)
    with pytest.raises(StylePackAttemptsExceeded):
        repository.count_attempt(workspace_limit=1, installation_limit=1)


def test_the_workspace_and_installation_byte_limits_hold_exactly(packs):
    pack = admitted()
    files = sum(len(data) for data in pack.contents.values())
    # Files and documents both: a version keeps its manifest, declaration and receipt until erased.
    size = files + pack.documents_byte_size
    with pytest.raises(StylePackQuotaExceeded, match="retained-bytes limit"):
        packs.repository(retained_bytes_limit=size - 1).record(pack)
    with pytest.raises(StylePackQuotaExceeded, match="installation"):
        packs.repository(installation_bytes_limit=size - 1).record(pack)
    assert packs.owner_rows("select count(*) as n from workspace_style_pack_version")[0]["n"] == 0
    packs.repository(retained_bytes_limit=size, installation_bytes_limit=size).record(pack)
    [documents] = packs.owner_rows("select documents_byte_size from workspace_style_pack_version")
    assert documents["documents_byte_size"] == pack.documents_byte_size, "the count the check used"
    total = packs.owner_rows("select retained_bytes from installation_style_pack_total")
    assert total == [{"retained_bytes": size}]


def test_assets_and_style_packs_share_one_retained_bytes_limit(packs):
    pack = admitted()
    size = pack.documents_byte_size + sum(len(data) for data in pack.contents.values())
    # An asset object the workspace already holds, recorded as an admission records one.
    with packs.purged.database().session(packs.workspace_id) as owner:
        owner.execute(
            "insert into workspace_asset_blob (workspace_id, content_sha256, byte_size) "
            "values (%s, %s, %s)",
            (packs.workspace_id, "a" * 64, 1000),
        )
    with pytest.raises(StylePackQuotaExceeded, match="retained-bytes limit"):
        packs.repository(retained_bytes_limit=size + 999).record(pack)
    packs.repository(retained_bytes_limit=size + 1000).record(pack)


def test_an_asset_admission_counts_the_style_pack_versions_documents(packs):
    """The limit an asset is admitted under holds the workspace's style pack documents too."""
    pack = admitted()
    packs.repository().record(pack)
    held = pack.documents_byte_size + sum(len(data) for data in pack.contents.values())
    asset = 500

    def refusal(limit: int) -> str | None:
        return retained_bytes_refusal(packs.connection, packs.workspace_id, "b" * 64, asset, limit)

    refused = refusal(held + asset - 1)
    assert refused is not None and "documents" in refused
    assert refusal(held + asset) is None


def test_a_workspace_holds_at_most_sixteen_live_versions(packs):
    # Each made ready before the next, since at most four checks wait at once.
    for version in range(1, 17):
        packs.ready(admitted(version=version, pieces=1))
    repository = packs.repository()
    with pytest.raises(StylePackQuotaExceeded, match="16 style pack versions"):
        repository.record(admitted(version=17, pieces=1))
    repository.withdraw(admitted(version=1, pieces=1).manifest_sha256)
    repository.record(admitted(version=17, pieces=1))


# -- erasure ------------------------------------------------------------------------------------


def test_a_workspace_tombstone_erases_every_text_and_destroys_every_file(packs):
    ready, waiting = admitted("maker.barn"), admitted("maker.field")
    packs.ready(ready)
    repository = packs.repository()
    repository.record(waiting)
    repository.request_publish(
        ready.manifest_sha256, licence_id="CC-BY-4.0", attribution="A maker", statement="mine"
    )
    objects = sorted(
        row["content_sha256"]
        for row in packs.owner_rows("select content_sha256 from workspace_style_pack_blob")
    )
    assert len(objects) == 6
    tombstone = packs.purged.repository.insert_tombstone(
        scope="workspace", requested_by=uuid.uuid4(), reason="the person left"
    )
    versions = packs.owner_rows(
        "select manifest_canonical, declaration_canonical, erased_at "
        "from workspace_style_pack_version"
    )
    assert all(
        (row["manifest_canonical"], row["declaration_canonical"]) == (None, None)
        and row["erased_at"] is not None
        for row in versions
    )
    assert (
        packs.owner_rows(
            "select count(*) as n from workspace_style_pack_file where path is not null"
        )[0]["n"]
        == 0
    )
    assert packs.owner_rows(
        "select attribution, statement from workspace_style_pack_publish_request"
    ) == [{"attribution": None, "statement": None}]
    erased = packs.owner_rows(
        "select manifest_sha256, pack_id, receipt_document, licence_attribution "
        "from workspace_style_pack_version order by manifest_sha256"
    )
    assert [
        (row["pack_id"], row["receipt_document"], row["licence_attribution"]) for row in erased
    ] == [("erased.x" + row["manifest_sha256"][:24], {"erased": True}, None) for row in erased]
    assert packs.owner_rows(
        "select count(*) as n from workspace_style_pack_preparation "
        "where report_document is not null"
    ) == [{"n": 0}]
    states = {
        (row["state"], row["failure_class"])
        for row in packs.owner_rows(
            "select state, failure_class from workspace_style_pack_preparation"
        )
    }
    assert states == {("ready", None), ("cancelled", "deleted")}
    jobs = packs.owner_rows(
        "select target_ref from purge_job where tombstone_id = %s "
        "and target_kind = 'workspace_style_pack' order by target_ref",
        tombstone,
    )
    assert [job["target_ref"] for job in jobs] == objects
    assert not queue.is_purge_complete(packs.purged.repository.connection, tombstone)

    # Drained by the worker the purge command, maintenance and restore replay build.
    outcome = packs.production_purge().drain()
    assert outcome.failed == 0 and outcome.blocked is None, outcome
    assert not any(packs.in_namespace(digest) for digest in objects)
    assert packs.owner_rows("select retained_bytes from installation_style_pack_total") == [
        {"retained_bytes": 0}
    ]
    assert queue.is_purge_complete(packs.purged.repository.connection, tombstone)
    with pytest.raises(StylePackWithdrawn):
        repository.record(admitted("maker.after"))


def test_no_live_version_may_take_an_id_the_erasure_writes(packs):
    """An erased version's id is "erased.x" and 24 hex of its digest. Were a creator free to
    record a version under such an id, the erasure's rewrite would meet it and the workspace's
    tombstone would fail; the prefix is the erasure's alone, and no live version names it as its
    base, a library base included."""
    repository = packs.repository()
    first = admitted("aaa.barn")
    repository.record(first)
    with pytest.raises(psycopg.errors.CheckViolation, match="erased_ids_are_the_erasures"):
        repository.record(admitted("erased.x" + first.manifest_sha256[:24]))
    erased_library = PackBase("library", "erased.x" + "0" * 24, 1, "0" * 64)
    with pytest.raises(psycopg.errors.CheckViolation, match="erased_ids_are_the_erasures"):
        repository.record(admitted("aaa.coop", base=erased_library))
    repository.record(admitted("aaa.barn", version=2))
    packs.purged.repository.insert_tombstone(
        scope="workspace", requested_by=uuid.uuid4(), reason="the person left"
    )
    erased = packs.owner_rows("select manifest_sha256, pack_id from workspace_style_pack_version")
    assert len(erased) == 2
    assert all(row["pack_id"] == "erased.x" + row["manifest_sha256"][:24] for row in erased)


def test_two_versions_whose_erased_ids_meet_are_both_erased(packs):
    """Only live versions are unique by pack id and version. An erased version's id is "erased.x"
    and 24 hex of its digest, so two digests sharing those 24 hex (about 2^48 hashes apart) give
    two erased versions one id, and a uniqueness over erased versions too would make the
    workspace's tombstone fail. The digest's binding to its bytes is lifted inside one transaction,
    rolled back, as the only way to make two digests meet here."""
    first = admitted("aaa.barn")
    packs.repository().record(first)
    met = first.manifest_sha256[:24] + "f" * 40
    assert met != first.manifest_sha256
    owner = packs.purged.repository.connection
    erased: list[dict[str, Any]] = []
    with owner.transaction():
        set_workspace(owner, packs.workspace_id)
        owner.execute(
            "alter table workspace_style_pack_version "
            "drop constraint the_manifest_digest_is_over_its_bytes"
        )
        owner.execute(
            "insert into workspace_style_pack_version select (jsonb_populate_record(v, "
            "jsonb_build_object('pack_id', 'bbb.barn', 'manifest_sha256', %s::text))).* "
            "from workspace_style_pack_version v where v.manifest_sha256 = %s",
            (met, first.manifest_sha256),
        )
        owner.execute(
            "insert into tombstone (workspace_id, scope, requested_by, reason) "
            "values (%s, 'workspace', %s, 'the person left')",
            (packs.workspace_id, uuid.uuid4()),
        )
        erased = owner.execute(
            "select pack_id, version, erased_at is not null as erased "
            "from workspace_style_pack_version order by manifest_sha256"
        ).fetchall()
        raise psycopg.Rollback()
    assert [(row["pack_id"], row["version"], row["erased"]) for row in erased] == [
        ("erased.x" + first.manifest_sha256[:24], 1, True)
    ] * 2


def test_the_erasure_replaces_the_id_of_a_workspace_base(packs):
    base = admitted("maker.barn")
    packs.ready(base)
    drawn = admitted("maker.barn-night", base=base_of(base))
    packs.repository().record(drawn)
    packs.purged.repository.insert_tombstone(
        scope="workspace", requested_by=uuid.uuid4(), reason="the person left"
    )
    assert packs.owner_rows(
        "select base_pack_id, base_manifest_sha256 from workspace_style_pack_version "
        "where base_source = 'workspace'"
    ) == [
        {
            "base_pack_id": "erased.x" + base.manifest_sha256[:24],
            "base_manifest_sha256": base.manifest_sha256,
        }
    ]


def test_completion_and_the_purge_kinds_name_every_destroyable_kind(packs):
    """A later migration restating either must keep every kind, or this fails on a fresh schema."""
    function = packs.owner_rows(
        "select prosrc from pg_proc where proname = 'tombstone_purge_is_complete'"
    )
    constraint = packs.owner_rows(
        "select pg_get_constraintdef(oid) as definition from pg_constraint "
        "where conname = 'purge_job_target_kind_check'"
    )
    assert len(function) == 1 and len(constraint) == 1
    # Written out by hand, not read from the queue's own list, so a kind dropped from both fails.
    for kind in (
        "blob",
        "artifact",
        "embedding",
        "text_chunk",
        "material_bake",
        "workspace_asset",
        "look",
        "workspace_style_pack",
    ):
        assert f"'{kind}'" in constraint[0]["definition"], kind
    for kind in (
        "blob",
        "artifact",
        "embedding",
        "material_bake",
        "workspace_asset",
        "look",
        "workspace_style_pack",
    ):
        assert f"target_kind='{kind}'" in function[0]["prosrc"], kind
    for table in ("workspace_asset_blob", "look_object", "workspace_style_pack_blob"):
        assert function[0]["prosrc"].count(f"from {table}") == 2, table


def test_the_purge_role_holds_exactly_the_style_pack_privileges_it_needs(packs):
    columns = packs.owner_rows(
        "select privilege_type, column_name from information_schema.column_privileges "
        "where grantee = %s and table_schema = current_schema() "
        "  and table_name = 'workspace_style_pack_blob' "
        "order by privilege_type, column_name",
        _PURGE_ROLE,
    )
    assert [(row["privilege_type"], row["column_name"]) for row in columns] == [
        ("SELECT", "content_sha256"),
        ("SELECT", "purged_at"),
        ("SELECT", "workspace_id"),
        ("UPDATE", "purged_at"),
    ]
    signature = "workspace_style_pack_purge_is_authorized(uuid,uuid,text)"
    assert packs.owner_rows(
        "select has_function_privilege(%s, %s, 'execute') as allowed", _PURGE_ROLE, signature
    )[0]["allowed"]
    for function in (
        signature,
        "style_pack_attempt(integer,integer)",
        "style_pack_installation_bytes_admit(bigint,bigint)",
    ):
        assert not packs.owner_rows(
            "select has_function_privilege('public', %s, 'execute') as allowed", function
        )[0]["allowed"], function


def _licensed(
    made: AdmittedStylePack, licence_id: str, attribution: str | None
) -> AdmittedStylePack:
    fields = {name: getattr(made, name) for name in AdmittedStylePack.__dataclass_fields__}
    return AdmittedStylePack(
        **{
            **fields,
            "rights_basis": "licensed",
            "licence_id": licence_id,
            "attribution": attribution,
        }
    )


def test_a_licensed_version_passes_on_only_its_own_attribution(packs):
    lent = _licensed(admitted("maker.lent"), "CC-BY-4.0", "Made by A. Maker")
    packs.ready(lent)
    repository = packs.repository()
    with pytest.raises(StylePackPublishLicenceNotHeld):
        repository.request_publish(
            lent.manifest_sha256, licence_id="CC-BY-4.0", attribution="Someone Else", statement="x"
        )
    repository.request_publish(
        lent.manifest_sha256, licence_id="CC-BY-4.0", attribution="Made by A. Maker", statement="x"
    )


def test_a_check_asked_again_waits_within_the_four_check_bound(packs):
    repository = packs.repository()
    first = admitted("maker.first")
    repository.record(first)
    claimed = repository.claim("test-worker", 60)
    assert claimed is not None
    repository.finish_failed(first.manifest_sha256, claimed[1], "interrupted", "it stopped", {})
    for n in range(4):
        repository.record(admitted(f"maker.waiting-{n}"))
    with pytest.raises(StylePackQuotaExceeded, match="4 style pack checks waiting"):
        repository.request_again(first.manifest_sha256)


def test_a_finished_check_keeps_how_it_ended(packs):
    pack = admitted()
    repository = packs.repository()
    repository.record(pack)
    claimed = repository.claim("test-worker", 60)
    assert claimed is not None
    repository.finish_failed(pack.manifest_sha256, claimed[1], "refused", "a stray colour", {})
    with (
        pytest.raises(psycopg.errors.CheckViolation, match="keeps how it ended"),
        packs.connection.transaction(),
    ):
        packs.connection.execute(
            "update workspace_style_pack_preparation set failure_class = 'interrupted'"
        )


def test_a_chain_is_at_most_eight_versions_deep(packs):
    chain = [admitted("maker.depth-0")]
    packs.ready(chain[0])
    for depth in range(1, 8):
        chain.append(admitted(f"maker.depth-{depth}", base=base_of(chain[-1])))
        packs.ready(chain[-1])
    assert packs.repository().wearable(chain[-1].manifest_sha256)
    with pytest.raises(psycopg.errors.CheckViolation, match="eight versions deep"):
        packs.repository().record(admitted("maker.depth-8", base=base_of(chain[-1])))


def test_the_judge_seed_refuses_a_workspace_holding_a_version_with_no_files(packs):
    from exulanica.orchestration.judge_seed import (
        SeedRefused,
        _refuse_private_workspace_style_packs,
    )

    made = admitted("maker.empty", pieces=0)
    fields = {name: getattr(made, name) for name in AdmittedStylePack.__dataclass_fields__}
    empty = AdmittedStylePack(**{**fields, "files": (), "contents": {}, "preview_sha256": None})
    packs.repository().record(empty)
    assert packs.owner_rows("select count(*) as n from workspace_style_pack_blob") == [{"n": 0}]
    with pytest.raises(SeedRefused, match="style pack version"):
        _refuse_private_workspace_style_packs(packs.connection, packs.workspace_id)


def test_delivery_asks_again_at_its_final_check_and_not_only_before(packs, monkeypatch):
    pack = admitted()
    packs.ready(pack)
    repository = packs.repository()
    before = repository.version(pack.manifest_sha256)
    repository.withdraw(pack.manifest_sha256)
    # As if the withdrawal committed between delivery's first read and its final check.
    monkeypatch.setattr(repository, "version", lambda _digest: before)
    with pytest.raises(StylePackWithdrawn, match="may not be served now"):
        repository.read_file(pack.manifest_sha256, pack.files[0].content_sha256)


def test_the_installation_total_is_read_under_its_row_lock(packs):
    first = packs.purged.database()
    second = packs.purged.database()
    # The total's row exists and is committed first, so the wait below is for its row lock and not
    # for another session's insert of the row.
    with first.session(packs.workspace_id) as setup, setup.transaction():
        setup.execute("select style_pack_installation_bytes_admit(0, 1)")
    with (
        first.session(packs.workspace_id) as holder,
        second.session(packs.workspace_id) as other,
        holder.transaction(),
    ):
        holder.execute("select style_pack_installation_bytes_admit(1, 1000000000)")
        with pytest.raises(psycopg.errors.LockNotAvailable), other.transaction():
            other.execute("set local lock_timeout = '200ms'")
            other.execute("select style_pack_installation_bytes_admit(1, 1000000000)")


def test_erasing_a_workspace_without_style_packs_never_waits_for_the_installation_total(packs):
    """Every admission locks the installation total's row until it commits. A workspace tombstone
    writes the total only when its workspace holds a live version, so the erasure of a workspace
    holding none neither waits for that lock nor takes it."""
    packs.repository().record(admitted())
    erase = (
        "insert into tombstone (workspace_id, scope, requested_by, reason) "
        "values (current_workspace(), 'workspace', %s, 'the person left')",
        (uuid.uuid4(),),
    )
    database = packs.purged.database()
    with (
        database.session(packs.workspace_id) as holder,
        database.session(packs.workspace_id) as holding,
        database.session(uuid.uuid4()) as empty,
        holder.transaction(),
    ):
        holder.execute("select style_pack_installation_bytes_admit(1, 1000000000)")
        # The positive control: this workspace holds a version, so its erasure waits.
        with pytest.raises(psycopg.errors.LockNotAvailable), holding.transaction():
            holding.execute("set local lock_timeout = '200ms'")
            holding.execute(*erase)
        with empty.transaction():
            empty.execute("set local lock_timeout = '200ms'")
            empty.execute(*erase)


def test_a_session_that_bypasses_row_security_cannot_wear_another_workspaces_pack(packs):
    pack = admitted()
    packs.ready(pack)
    # The schema owner bypasses row-level security; only the comparison with the session's
    # workspace stands between it and another workspace's pack.
    with packs.purged.database().session(uuid.uuid4()) as owner:
        row = owner.execute(
            "select workspace_style_pack_wearable(%s, %s) as wearable",
            (packs.workspace_id, pack.manifest_sha256),
        ).fetchone()
    assert row["wearable"] is False
    assert packs.repository().wearable(pack.manifest_sha256), "the positive control"


def test_a_session_that_bypasses_row_security_cannot_purge_another_workspaces_pack(packs):
    pack = admitted()
    packs.repository().record(pack)
    tombstone = packs.purged.repository.insert_tombstone(
        scope="workspace", requested_by=uuid.uuid4(), reason="the person left"
    )
    ask = (
        "select workspace_style_pack_purge_is_authorized(%s, %s, %s) as allowed",
        (packs.workspace_id, tombstone, pack.files[0].content_sha256),
    )
    with packs.purged.database().session(packs.workspace_id) as own:
        assert own.execute(*ask).fetchone()["allowed"] is True, "the positive control"
    with packs.purged.database().session(uuid.uuid4()) as other:
        assert other.execute(*ask).fetchone()["allowed"] is False
    with packs.purged.database().session(uuid.uuid4()) as owner:
        # Row security on the tombstone already hides another workspace's from the definers'
        # owner; the function compares the session's workspace too, so it refuses even for an
        # owner that bypassed row security. Shown in one transaction that is rolled back, so no
        # other session ever sees the owner bypass row security. The ask is this session's
        # first, so no plan made while row security applied can answer it.
        with owner.transaction():
            owner.execute(f"alter role {DEFINER_ROLE} bypassrls")
            assert owner.execute(*ask).fetchone()["allowed"] is False
            raise psycopg.Rollback()
        held = owner.execute(
            "select rolbypassrls from pg_roles where rolname = %s", (DEFINER_ROLE,)
        ).fetchone()
        assert held["rolbypassrls"] is False


def test_a_database_without_the_style_pack_question_claims_every_other_kind(packs):
    """A database one migration behind the code holds no style pack question; the claim leaves
    style packs out rather than failing for every kind. The question is renamed inside a
    transaction that is rolled back."""
    [capture] = packs.owner_rows("select capture_id from capture")
    packs.purged.tombstone_the_capture(capture["capture_id"])
    owner = packs.purged.repository.connection
    with owner.transaction():
        owner.execute(
            "alter function workspace_style_pack_purge_is_authorized(uuid, uuid, text) "
            "rename to workspace_style_pack_purge_is_authorized_not_yet"
        )
        set_workspace(owner, packs.workspace_id)
        target = queue.claim_purge(owner, packs.workspace_id, queue.DESTROYABLE_KINDS)
        assert target is not None and target.target_kind != "workspace_style_pack"
        raise psycopg.Rollback()
