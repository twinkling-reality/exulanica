"""A world's look taking its passed generated pieces in as they arrive, and giving them back.

Asking for pieces is the consent to the world's look taking each passed piece in (contract:
generated pieces). Each pass of the generation worker looks at every world
of the workspace with a made request not yet taken in, or a take-back asked and not yet done, and
moves that world's look one step (:meth:`LookStepper.run`):

1. **What the world wears.** The pack its current appearance names: a library pack (the base, with
   no generated piece), or its own look of generated pieces drawn on a library base (that base,
   with the pieces its modules list). A world naming no pack wears the library's default. A world
   whose own look may no longer be worn (withdrawn) wears its base. A world wearing anything else
   (a creator's own pack) takes nothing in.
2. **What it should wear.** Each made request drawn on that same base sets its look role to its
   passed pieces (at most :data:`~exulanica.world.style_packs.MAX_VARIANTS`, in variant order; a
   newer request for the same role replaces an older one); each take-back removes a role while the
   world still wears that request's pieces. A request drawn on another base is not applied
   (``look_changed``); one with no passed piece is not applied (``no_piece_within``).
3. **The look.** No generated piece left: the base itself. Otherwise the derived look
   (:mod:`exulanica.generation.looks`): the version already made of the same pieces on the same base
   when the workspace holds one, else a new version recorded through
   :meth:`~exulanica.world.workspace_style_packs.WorkspaceStylePackRepository.record_generated`,
   whose check (the asset preparation process) reads every piece again before any world wears it.
   While it is checked the step waits for a later pass; a check that ends failed ends the step
   (``look_refused``, or ``look_check_failed``), and one still waiting after a day ends it too.
4. **The write.** The world's next appearance version names that look, through the same preview
   and Apply a person's change takes (origin ``user``, the asker as actor, the reference
   ``generated-pieces:<request>``), with every saved entry resting on the replaced version moved
   to the new one in that same write, so the person's next change is not refused as stale. A
   write refused as busy or stale is tried again on the next pass, for at most a day.
5. **The record.** One step per request (``piece_look_step``): applied, naming the look and the
   appearance version, or not applied with its reason; taken back, naming them, or with
   ``not_worn`` when the world no longer wore the request's pieces.

Nothing here deletes a piece or a request: taking back writes a new appearance version, and the
world's appearance history rolls back as it always does. A step that fails in one world is logged
by its kind and tried again on the next pass; it never stops another world's.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any, Final

from exulanica.generation import looks
from exulanica.generation.store import generated_looks_full, workspace_deleted
from exulanica.store.base import ContentAddressedStore
from exulanica.store.namespaces import WorkspaceStores
from exulanica.world.errors import (
    InvalidPreviewState,
    StaleStyleVersion,
    StyleWriteBusy,
)
from exulanica.world.models import (
    ProposalOrigin,
    ProposalProvenance,
    StylePackBinding,
    StyleProposal,
    StyleScope,
    StyleVersion,
)
from exulanica.world.repository import WorldStyleRepository
from exulanica.world.saved_entries import SavedWorldEntryRepository, StaleSavedWorldEntry
from exulanica.world.style_pack_library import StylePackLibrary
from exulanica.world.style_packs import (
    MAX_VARIANTS,
    StylePackContext,
    StylePackRefused,
    read_manifest,
)
from exulanica.world.workspace_preparations import DEFAULT_RETAINED_BYTES
from exulanica.world.workspace_style_packs import (
    GeneratedStylePackRefused,
    StylePackQuotaExceeded,
    StylePackVersionRecord,
    WorkspaceStylePackError,
    WorkspaceStylePackRepository,
)

__all__ = ["GIVE_UP_AFTER", "REFERENCE_PREFIX", "LookStepper"]

_LOG = logging.getLogger(__name__)

#: The origin reference of an appearance version a look step writes: the request it took in or
#: back follows it.
REFERENCE_PREFIX: Final = "generated-pieces:"
#: How long a step waits for its look's check or a free write before it ends not applied.
GIVE_UP_AFTER: Final = timedelta(days=1)
_REQUEST_COLUMNS: Final = (
    "p.piece_request_id, p.requested_by, p.world_id, p.look_role, p.pack_id, p.pack_version, "
    "p.pack_manifest_sha256, p.finished_at"
)
#: The quota bounds that are retained bytes, which end a step by name (``look_bytes_limit``).
_BYTES_BOUNDS: Final = frozenset({"workspace_bytes", "installation_bytes"})
#: Limits that end pieces taken in but leave a take-back asked: a withdrawn look frees its slot.
_TAKE_BACK_WAITS: Final = frozenset({"look_limit"})
#: The authors a derived look names: the shape model of every piece (route A, the THINGS mapping).
_AUTHORS: Final = ("TRELLIS-image-large",)


@dataclass(frozen=True, slots=True)
class _Request:
    piece_request_id: uuid.UUID
    requested_by: uuid.UUID
    world_id: str
    look_role: str
    base: StylePackBinding
    #: When it was made (``finished_at``), from which a step's day is counted.
    since: datetime


@dataclass(frozen=True, slots=True)
class _TakeBack:
    request: _Request
    asked_by: uuid.UUID
    since: datetime


@dataclass
class _Plan:
    """One world's step: what it wears, what it should wear, and what each request's step says."""

    base: StylePackBinding | None
    roles: dict[str, list[looks.GeneratedVariant]]
    applied: list[_Request] = field(default_factory=list)
    not_applied: list[tuple[_Request, str]] = field(default_factory=list)
    taken_back: list[_TakeBack] = field(default_factory=list)
    #: Take-backs done with nothing written: the world no longer wore the request's pieces.
    not_worn: list[_TakeBack] = field(default_factory=list)
    #: Take-backs that cannot be done, with the permanent reason (``not_taken_back``).
    not_taken_back: list[tuple[_TakeBack, str]] = field(default_factory=list)


@dataclass
class LookStepper:
    """Moves each world's look one step per pass; every collaborator is injected."""

    library: StylePackLibrary
    context: StylePackContext
    stores: WorkspaceStores
    generated_pieces: ContentAddressedStore | None
    #: The workspace's retained-bytes limit, as the deployment configures it for the API.
    retained_bytes_limit: int = DEFAULT_RETAINED_BYTES

    def run(self, connection: Any, workspace_id: uuid.UUID, now: datetime) -> list[str]:
        """Step every world of the workspace that has one waiting; the worlds stepped. Nothing is
        written in a deleted workspace (one still named in a static workspace list)."""
        if workspace_deleted(connection, workspace_id):
            return []
        stepped = []
        made, asked = _waiting(connection, workspace_id)
        worlds = sorted({r.world_id for r in made} | {t.request.world_id for t in asked})
        for world_id in worlds:
            try:
                if self._step(
                    connection,
                    workspace_id,
                    world_id,
                    [r for r in made if r.world_id == world_id],
                    [t for t in asked if t.request.world_id == world_id],
                    now,
                ):
                    stepped.append(world_id)
            except Exception as failure:  # one world's fault never stops another's
                _LOG.warning(
                    "a world's look was not stepped this pass: %s", type(failure).__qualname__
                )
        for world_id, manifest_sha256 in _unwearable(connection, workspace_id):
            if world_id in worlds:
                continue  # stepped above, on its base
            try:
                if self._fall_back(connection, workspace_id, world_id, manifest_sha256):
                    stepped.append(world_id)
            except Exception as failure:
                _LOG.warning(
                    "a world's look did not fall back this pass: %s", type(failure).__qualname__
                )
        return stepped

    def _fall_back(
        self, connection: Any, workspace_id: uuid.UUID, world_id: str, manifest_sha256: str
    ) -> bool:
        """A world whose current appearance names its own look of generated pieces after that look
        may no longer be worn (withdrawn) names its library base in the next version (none when
        the library no longer holds it), recorded as ``fell_back`` for each request of the world
        whose pieces that look held (taken in, not taken back), or, when none is found, for the
        request whose step named the look. A busy write is tried again on the next pass."""
        row = connection.execute(
            f"select {_REQUEST_COLUMNS} from piece_look_step s join piece_request p "
            "  on p.workspace_id = s.workspace_id and p.piece_request_id = s.piece_request_id "
            "where s.workspace_id = %s and s.world_id = %s and s.manifest_sha256 = %s "
            "  and s.kind in ('applied', 'taken_back') "
            "  and exists (select 1 from piece_look_step a where a.workspace_id = s.workspace_id "
            "               and a.piece_request_id = s.piece_request_id and a.kind = 'applied') "
            "  and not exists (select 1 from piece_look_step f "
            "                   where f.workspace_id = s.workspace_id "
            "                     and f.piece_request_id = s.piece_request_id "
            "                     and f.kind = 'fell_back') "
            "order by s.recorded_at desc limit 1",
            (workspace_id, world_id, manifest_sha256),
        ).fetchone()
        if row is None:
            return False  # no step of a request named that look: nothing to record it against
        styles = WorldStyleRepository(
            connection, workspace_id, world_id=world_id, style_packs=self.library
        )
        current = styles.current()
        worn = current.style_pack
        if worn is None or worn.manifest_sha256 != manifest_sha256 or worn.wearable:
            return False
        holders = self._holders(connection, workspace_id, world_id, manifest_sha256) or [
            _request(row)
        ]
        request = holders[0]
        target = (
            None
            if worn.base is None
            else StylePackBinding(worn.base.pack_id, worn.base.version, worn.base.manifest_sha256)
        )
        try:
            written = _write(
                connection, workspace_id, styles, current, target, request.requested_by, request
            )
        except (StyleWriteBusy, StaleStyleVersion, StaleSavedWorldEntry):
            return False
        with connection.transaction():
            for holder in holders:
                connection.execute(
                    "insert into piece_look_step (workspace_id, piece_request_id, world_id, kind, "
                    "  reason, style_version_id) "
                    "values (%s, %s, %s, 'fell_back', 'look_withdrawn', %s)",
                    (workspace_id, holder.piece_request_id, world_id, written.version_id),
                )
        return True

    def _holders(
        self, connection: Any, workspace_id: uuid.UUID, world_id: str, manifest_sha256: str
    ) -> list[_Request]:
        """The world's requests taken in and not taken back or fallen back whose passed pieces
        the look's modules list for their role, oldest first."""
        own = WorkspaceStylePackRepository(
            connection,
            workspace_id,
            uuid.UUID(int=0),
            stores=self.stores,
            generated_pieces=self.generated_pieces,
            retained_bytes_limit=self.retained_bytes_limit,
        )
        held = _worn_roles(connection, workspace_id, own.version(manifest_sha256))
        rows = connection.execute(
            f"select {_REQUEST_COLUMNS} from piece_request p "
            "where p.workspace_id = %s and p.world_id = %s "
            "  and exists (select 1 from piece_look_step a where a.workspace_id = p.workspace_id "
            "               and a.piece_request_id = p.piece_request_id and a.kind = 'applied') "
            "  and not exists (select 1 from piece_look_step e "
            "                   where e.workspace_id = p.workspace_id "
            "                     and e.piece_request_id = p.piece_request_id "
            "                     and e.kind in ('taken_back', 'fell_back')) "
            "order by p.finished_at, p.piece_request_id",
            (workspace_id, world_id),
        ).fetchall()
        holders = []
        for request in map(_request, rows):
            listed = [piece.piece_sha256 for piece in held.get(request.look_role, [])]
            passed = _passed(connection, workspace_id, request.piece_request_id)
            if listed and listed == [piece.piece_sha256 for piece in passed]:
                holders.append(request)
        return holders

    # -- one world -----------------------------------------------------------------------------

    def _step(
        self,
        connection: Any,
        workspace_id: uuid.UUID,
        world_id: str,
        made: Sequence[_Request],
        asked: Sequence[_TakeBack],
        now: datetime,
    ) -> bool:
        styles = WorldStyleRepository(
            connection, workspace_id, world_id=world_id, style_packs=self.library
        )
        current = styles.current()
        own = WorkspaceStylePackRepository(
            connection,
            workspace_id,
            uuid.UUID(int=0),
            stores=self.stores,
            generated_pieces=self.generated_pieces,
            retained_bytes_limit=self.retained_bytes_limit,
        )
        plan = self._plan(connection, workspace_id, own, current, made, asked)
        # The day pieces taken in may wait: a take-back waits however long, so it never counts.
        oldest = min((r.since for r in made), default=now)
        if plan.base is None or not (plan.applied or plan.taken_back):
            # Nothing to write: every waiting step ends as it stands.
            self._record(connection, workspace_id, plan, None, None)
            return True
        target, failure = self._look(own, plan, made, asked)
        if failure in _PASSING:
            # A take-back waits however long it takes: it stays asked and the next pass tries it
            # again. Pieces taken in wait a day, then end not applied.
            if not plan.applied or now - oldest <= GIVE_UP_AFTER:
                return False
            plan.taken_back = []
            failure = "look_not_ready"
        if failure is not None:
            plan.not_applied.extend((request, failure) for request in plan.applied)
            plan.applied = []
            if failure not in _PASSING and failure not in _TAKE_BACK_WAITS:
                plan.not_taken_back.extend((take, failure) for take in plan.taken_back)
            plan.taken_back = []
            self._record(connection, workspace_id, plan, None, None)
            return True
        assert target is not None
        if target == current.style_pack:
            written = current
        else:
            actor = plan.applied[0].requested_by if plan.applied else plan.taken_back[0].asked_by
            reference = (plan.applied or [t.request for t in plan.taken_back])[0]
            try:
                written = _write(
                    connection, workspace_id, styles, current, target, actor, reference
                )
            except (StyleWriteBusy, StaleStyleVersion, StaleSavedWorldEntry):
                # A busy or stale write passes: take-backs stay asked, pieces wait a day.
                if not plan.applied or now - oldest <= GIVE_UP_AFTER:
                    return False
                plan.not_applied.extend((request, "look_write_busy") for request in plan.applied)
                plan.applied = []
                plan.taken_back = []
                self._record(connection, workspace_id, plan, None, None)
                return True
        manifest = None if target.source == "library" else target.manifest_sha256
        self._record(connection, workspace_id, plan, manifest, written.version_id)
        return True

    def _plan(
        self,
        connection: Any,
        workspace_id: uuid.UUID,
        own: WorkspaceStylePackRepository,
        current: StyleVersion,
        made: Sequence[_Request],
        asked: Sequence[_TakeBack],
    ) -> _Plan:
        worn = current.style_pack
        if worn is None:
            default = self.library.default_pack
            base: StylePackBinding | None = StylePackBinding(
                default.pack_id, default.version, default.manifest_sha256
            )
            roles: dict[str, list[looks.GeneratedVariant]] = {}
        elif worn.source == "library":
            base, roles = worn, {}
        else:
            record = own.version(worn.manifest_sha256)
            if record.origin != "generated":
                base, roles = None, {}
            elif not worn.wearable:
                base, roles = worn.base, {}
            else:
                base, roles = worn.base, _worn_roles(connection, workspace_id, record)
        plan = _Plan(base=base, roles=roles)
        for request in sorted(made, key=lambda r: (r.since, str(r.piece_request_id))):
            if base is None or request.base != base:
                plan.not_applied.append((request, "look_changed"))
                continue
            pieces = _passed(connection, workspace_id, request.piece_request_id)
            if not pieces:
                plan.not_applied.append((request, "no_piece_within"))
                continue
            replaced = [r for r in plan.applied if r.look_role == request.look_role]
            for older in replaced:
                plan.applied.remove(older)
                plan.not_applied.append((older, "replaced"))
            plan.roles[request.look_role] = pieces
            plan.applied.append(request)
        for take in asked:
            role = take.request.look_role
            pieces = _passed(connection, workspace_id, take.request.piece_request_id)
            worn_pieces = [p.piece_sha256 for p in plan.roles.get(role, [])]
            if not worn_pieces or worn_pieces != [p.piece_sha256 for p in pieces]:
                plan.not_worn.append(take)
            elif base is None:
                # The world wears the pieces, but the library no longer holds the look they were
                # taken into, so no look without them can be made: refused by name, never not worn.
                plan.not_taken_back.append((take, "base_not_library"))
            else:
                del plan.roles[role]
                plan.taken_back.append(take)
        return plan

    def _look(
        self,
        own: WorkspaceStylePackRepository,
        plan: _Plan,
        made: Sequence[_Request],
        asked: Sequence[_TakeBack],
    ) -> tuple[StylePackBinding | None, str | None]:
        """The pack the world should name, or why not: ``waiting`` while its check runs."""
        base = plan.base
        assert base is not None
        if not plan.roles:
            return base, None
        served = self.library.content.get(base.manifest_sha256)
        if served is None:
            return None, "base_not_library"
        try:
            chain = [read_manifest(json.loads(served.data), self.context)]
            content = looks.content_sha256(chain, plan.roles)
            record = own.generated_version(content)
            if record is not None and _interrupted(record):
                # An interrupted check may be asked again: the same pieces take the next version.
                record = None
            since = min([r.since for r in plan.applied] + [t.since for t in plan.taken_back])
            if record is None and own.generated_withdrawn_since(content, since):
                # The owner withdrew the look made for these requests while they waited on it; a
                # later ask of the same pieces is made again.
                return None, "look_withdrawn"
            if record is None:
                pack_id = looks.derived_pack_id(base.pack_id)
                built = looks.build_derived_look(
                    chain=chain,
                    version=own.next_generated_version(pack_id),
                    roles=plan.roles,
                    authors=_AUTHORS,
                    context=self.context,
                )
                assert built is not None
                asker = (
                    plan.applied[0].requested_by if plan.applied else plan.taken_back[0].asked_by
                )
                record, _ = own.record_generated(
                    built.canonical,
                    content_sha256=built.content_sha256,
                    asked_by=asker,
                    context=self.context,
                )
        except looks.DerivedLookRefused as refused:
            return None, refused.code
        except GeneratedStylePackRefused as refused:
            return None, refused.code
        except StylePackQuotaExceeded as full:
            # The retained bytes the workspace or the installation may hold are a limit by name; of
            # the count limits, either the workspace holds as many looks of generated pieces as it
            # may, for good (new asks are then refused by name before anything is spent), or its
            # four checks are all waiting, which passes.
            if full.bound in _BYTES_BOUNDS:
                return None, "look_bytes_limit"
            if generated_looks_full(own.connection, own.workspace_id):
                return None, "look_limit"
            return None, "waiting"
        except WorkspaceStylePackError:
            return None, "look_not_recorded"
        except StylePackRefused:
            return None, "base_unreadable"
        return _ready(record)

    def _record(
        self,
        connection: Any,
        workspace_id: uuid.UUID,
        plan: _Plan,
        manifest_sha256: str | None,
        style_version_id: uuid.UUID | None,
    ) -> None:
        rows: list[tuple[Any, ...]] = []
        for request in plan.applied:
            rows.append((request, "applied", None, manifest_sha256, style_version_id))
        for request, reason in plan.not_applied:
            rows.append((request, "not_applied", reason, None, None))
        for take in plan.taken_back:
            rows.append((take.request, "taken_back", None, manifest_sha256, style_version_id))
        for take in plan.not_worn:
            rows.append((take.request, "taken_back", "not_worn", None, None))
        for take, reason in plan.not_taken_back:
            rows.append((take.request, "not_taken_back", reason, None, None))
        with connection.transaction():
            for request, kind, reason, manifest, version in rows:
                connection.execute(
                    "insert into piece_look_step (workspace_id, piece_request_id, world_id, kind, "
                    "  reason, manifest_sha256, style_version_id) "
                    "values (%s, %s, %s, %s, %s, %s, %s)",
                    (
                        workspace_id,
                        request.piece_request_id,
                        request.world_id,
                        kind,
                        reason,
                        manifest,
                        version,
                    ),
                )


#: What ends a look step for now but not for good: its check still running, or interrupted.
_PASSING: Final = frozenset({"waiting"})


def _interrupted(record: StylePackVersionRecord) -> bool:
    return record.state == "failed" and record.failure_class == "interrupted"


def _ready(record: StylePackVersionRecord) -> tuple[StylePackBinding | None, str | None]:
    if record.withdrawn or record.erased:
        return None, "look_withdrawn"
    if record.state == "ready":
        return (
            StylePackBinding(record.pack_id, record.version, record.manifest_sha256, "workspace"),
            None,
        )
    if record.state in ("failed", "cancelled"):
        return None, "look_refused" if record.failure_class == "refused" else "look_check_failed"
    return None, "waiting"


def _write(
    connection: Any,
    workspace_id: uuid.UUID,
    styles: WorldStyleRepository,
    current: StyleVersion,
    target: StylePackBinding | None,
    actor: uuid.UUID,
    request: _Request,
) -> StyleVersion:
    """The world's next appearance version naming ``target``, through a preview and Apply, with the
    saved entries resting on ``current`` moved to it in the same write."""
    entries = SavedWorldEntryRepository(connection, workspace_id)
    resting = [
        entry
        for entry in entries.entries()
        if entry.world_id == request.world_id and entry.style_version_id == current.version_id
    ]
    # A world's own setting stays with it when its look takes generated pieces in or gives them
    # back: such a look states pieces alone, so the setting is drawn over it as over its base.
    worn = current.style_pack
    if target is not None and worn is not None and worn.setting is not None:
        target = replace(target, setting=worn.setting)
    preview = styles.preview(
        StyleProposal(
            proposal_id=uuid.uuid4(),
            provenance=ProposalProvenance(
                ProposalOrigin.USER, actor, f"{REFERENCE_PREFIX}{request.piece_request_id}"
            ),
            scope=StyleScope("global"),
            base_style_version_id=current.version_id,
            base_topology_digest=current.topology_digest,
            profile=current.global_style,
            style_pack_stated=True,
            style_pack=target,
        )
    )

    def before() -> None:
        for entry in resting:
            entries.lock_style_advance_base(
                entry.entry_id,
                base_revision=entry.revision,
                world_id=request.world_id,
                authored_state_sha256=entry.authored_state_sha256,
                authored_edit_seq=entry.authored_edit_seq,
                style_version_id=entry.style_version_id,
            )

    def after(version: StyleVersion) -> None:
        for entry in resting:
            entries.advance_style_locked(
                entry.entry_id,
                base_revision=entry.revision,
                world_id=request.world_id,
                style_version_id=version.version_id,
            )

    try:
        return styles.apply(
            preview.preview_id,
            base_style_version_id=current.version_id,
            base_topology_digest=current.topology_digest,
            applied_by=actor,
            before_write=before,
            after_write=after,
        )
    except BaseException as failed:
        _close(styles, preview.preview_id, actor, failed)
        raise


def _close(
    styles: WorldStyleRepository, preview_id: uuid.UUID, actor: uuid.UUID, failed: BaseException
) -> None:
    """Close the look step's own preview after its Apply failed, so the page never offers it to
    the person as a change of theirs: as stale when a saved entry moved (as the Apply route closes
    one), not at all when the Apply closed it already, else discarded. Best effort: a preview this
    cannot close lapses with its lifetime."""
    try:
        if isinstance(failed, StaleSavedWorldEntry):
            styles.close_stale_preview(preview_id, failed, error_code="stale_saved_world_entry")
        else:
            styles.discard(preview_id, discarded_by=actor)
    except InvalidPreviewState:
        pass  # the Apply closed it (stale or expired)
    except Exception as unclosed:
        _LOG.warning("a look step's preview was not closed: %s", type(unclosed).__qualname__)


def _passed(
    connection: Any, workspace_id: uuid.UUID, piece_request_id: uuid.UUID
) -> list[looks.GeneratedVariant]:
    """A request's passed pieces in variant order, at most a module's worth."""
    rows = connection.execute(
        "select o.piece_sha256, o.receipt_sha256, o.receipt_canonical, g.piece_bytes "
        "from piece_output o join generated_piece g "
        "  on g.cache_key = o.cache_key and g.variant = o.variant "
        "where o.workspace_id = %s and o.piece_request_id = %s and o.within "
        "order by o.variant limit %s",
        (workspace_id, piece_request_id, MAX_VARIANTS),
    ).fetchall()
    return [
        looks.GeneratedVariant(
            piece_sha256=row["piece_sha256"],
            piece_bytes=int(row["piece_bytes"]),
            size_mm=_size(json.loads(row["receipt_canonical"])["measured"]["size_mm"]),
            receipt_sha256=row["receipt_sha256"],
        )
        for row in rows
    ]


def _size(size_mm: Mapping[str, int]) -> tuple[int, int, int]:
    return int(size_mm["width"]), int(size_mm["depth"]), int(size_mm["height"])


def _worn_roles(
    connection: Any, workspace_id: uuid.UUID, record: StylePackVersionRecord
) -> dict[str, list[looks.GeneratedVariant]]:
    """The generated pieces a worn derived look lists, by look role, in its variant order."""
    if record.manifest_canonical is None:
        return {}
    manifest = json.loads(record.manifest_canonical)
    files = {file["path"]: file for file in manifest["files"]}
    digests = sorted({file["sha256"] for file in files.values()})
    receipts = {
        row["piece_sha256"]: row["receipt_sha256"]
        for row in connection.execute(
            "select piece_sha256, min(receipt_sha256) as receipt_sha256 from piece_output "
            "where workspace_id = %s and within and piece_sha256 = any(%s) group by piece_sha256",
            (workspace_id, digests),
        ).fetchall()
    }
    roles: dict[str, list[looks.GeneratedVariant]] = {}
    for role, module in manifest["modules"].items():
        roles[role] = [
            looks.GeneratedVariant(
                piece_sha256=files[variant["file"]]["sha256"],
                piece_bytes=int(files[variant["file"]]["bytes"]),
                size_mm=(
                    int(variant["size_mm"][0]),
                    int(variant["size_mm"][1]),
                    int(variant["size_mm"][2]),
                ),
                receipt_sha256=receipts.get(files[variant["file"]]["sha256"], ""),
            )
            for variant in module["variants"]
        ]
    return roles


def _unwearable(connection: Any, workspace_id: uuid.UUID) -> list[tuple[str, str]]:
    """The workspace's worlds whose current appearance names an own look of generated pieces that
    may no longer be worn, with that look's manifest digest."""
    return [
        (row["world_id"], row["style_pack_manifest_sha256"])
        for row in connection.execute(
            "select s.world_id, v.style_pack_manifest_sha256 from world_style_state s "
            "join world_style_version v on v.workspace_id = s.workspace_id "
            "  and v.world_id = s.world_id and v.version_id = s.current_style_version_id "
            "where s.workspace_id = %s and v.style_pack_source = 'workspace' "
            "  and v.style_pack_id like 'generated.%%' "
            "  and workspace_style_pack_wearable(s.workspace_id, v.style_pack_manifest_sha256) "
            "      is not true "
            "order by s.world_id",
            (workspace_id,),
        ).fetchall()
    ]


def _waiting(connection: Any, workspace_id: uuid.UUID) -> tuple[list[_Request], list[_TakeBack]]:
    """The workspace's made requests with no decided step, and its take-backs not yet done."""
    made = [
        _request(row)
        for row in connection.execute(
            f"select {_REQUEST_COLUMNS} from piece_request p "
            "where p.workspace_id = %s and p.state = 'made' "
            "  and not exists (select 1 from piece_look_step s "
            "                   where s.workspace_id = p.workspace_id "
            "                     and s.piece_request_id = p.piece_request_id "
            "                     and s.kind in ('applied', 'not_applied')) "
            "order by p.finished_at, p.piece_request_id",
            (workspace_id,),
        ).fetchall()
    ]
    asked = [
        _TakeBack(request=_request(row), asked_by=row["asked_by"], since=row["asked_at"])
        for row in connection.execute(
            f"select {_REQUEST_COLUMNS}, s.asked_by, s.recorded_at as asked_at "
            "from piece_look_step s join piece_request p "
            "  on p.workspace_id = s.workspace_id and p.piece_request_id = s.piece_request_id "
            "where s.workspace_id = %s and s.kind = 'take_back_asked' "
            "  and not exists (select 1 from piece_look_step t "
            "                   where t.workspace_id = s.workspace_id "
            "                     and t.piece_request_id = s.piece_request_id "
            "                     and t.kind in ('taken_back', 'not_taken_back')) "
            "order by s.recorded_at, s.piece_request_id",
            (workspace_id,),
        ).fetchall()
    ]
    return made, asked


def _request(row: Mapping[str, Any]) -> _Request:
    return _Request(
        piece_request_id=row["piece_request_id"],
        requested_by=row["requested_by"],
        world_id=row["world_id"],
        look_role=row["look_role"],
        base=StylePackBinding(row["pack_id"], row["pack_version"], row["pack_manifest_sha256"]),
        since=row["finished_at"],
    )
