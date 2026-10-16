"""Everything generated from a world kind, made in a worker process of its own and bounded.

Stage B of a kind's checks (:func:`~exulanica.world.kinds.samples.check_samples`) builds up to 48
sample worlds, making a world of a kind (:func:`~exulanica.world.composers.site_plan.compose_kind`)
tries up to four candidates, reading a site world's drawing, or the place its society walks
(:func:`~exulanica.world.composers.site_plan.society_place`), generates its records again from its
receipt (:func:`~exulanica.world.composers.site_plan.records`), and drawing a site's landscape
(:func:`~exulanica.world.landscape_drawing.landscape_drawing`) realizes its volumes. All are pure
Python, and pure Python on a request's thread holds the interpreter's lock from every other
request. So each runs in one spawned worker process
(:func:`~exulanica.world.episode_worker.worker_pool`), as a town's sample does
(:mod:`exulanica.world.specification_samples`), and no site is generated on a request's thread. A
request waits for its job without holding the lock, within these bounds:

- **a time limit per job** (:data:`CHECK_SECONDS`, :data:`COMPOSE_SECONDS`,
  :data:`DRAWING_SECONDS`, :data:`LANDSCAPE_SECONDS`): a job not done by then is answered
  ``overran``;
- **one request waits for a job**: asking for a job already running is answered ``overran`` at
  once, rather than holding another thread, admission place and connection for it;
- **a bound on jobs waiting** (:data:`JOBS_WAITING`) and **on one workspace's jobs**
  (:data:`WORKSPACE_JOBS`, a job counting until it finishes, whoever stopped waiting for it): past
  either a request is answered ``busy`` rather than queued;
- **finished checks, drawings, landscape drawings and places are kept** by their workspace and
  what they are made from (:data:`CHECKS_KEPT`, :data:`DRAWINGS_KEPT`, :data:`LANDSCAPES_KEPT`,
  :data:`PLACES_KEPT`; :func:`check_key`, :func:`drawing_key`, :func:`landscape_key`,
  :func:`place_key`), so asking again after ``overran`` reads the finished work and no workspace
  reads or waits on another's; a composed world is never kept, since each is made for a fresh
  identity, but its drawing and its society's place are, made with it. A site's landscape is not
  drawn with it: its drawing is a job of its own, made when it is first read. A kept place is
  handed out as a copy of its own, so no request changes what another reads;
- a worker that dies answers ``unavailable``, and the next job starts a new process; at every
  request, one whose oldest job runs past :data:`STUCK_SECONDS` is replaced and its process stopped.

Nothing is handed to the pool, or taken from it, while this module's own lock is held: the pool
runs its callbacks under a lock of its own, and they take this one.

What a job answers is plain data: ``{"status": "done", ...}`` with the report, the composed world,
the drawing or the landscape drawing, or ``{"status": "refused", ...}`` with the refusal's code and
words.
"""

from __future__ import annotations

import copy
import functools
import hashlib
import json
import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from concurrent.futures import CancelledError, Executor, Future
from concurrent.futures import TimeoutError as FutureTimeout
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from typing import Any, Final, Literal

from exulanica.world.specification_samples import sample_process_pool
from exulanica.world.terrain_authoring import TERRAIN_COMPOSER_VERSIONS

__all__ = [
    "CHECKS_KEPT",
    "CHECK_SECONDS",
    "COMPOSE_SECONDS",
    "DRAWINGS_KEPT",
    "DRAWING_SECONDS",
    "JOBS_WAITING",
    "LANDSCAPES_KEPT",
    "LANDSCAPE_SECONDS",
    "PLACES_KEPT",
    "PLACE_SECONDS",
    "STUCK_SECONDS",
    "WORKSPACE_JOBS",
    "JobOutcome",
    "Kept",
    "KindWorkWaiting",
    "KindWorker",
    "WorkerComposer",
    "check_job",
    "check_key",
    "close_kind_worker",
    "compose_job",
    "drawing_job",
    "drawing_key",
    "kind_worker",
    "landscape_job",
    "landscape_key",
    "part_check_key",
    "part_job",
    "parts_job",
    "place_job",
    "place_key",
    "site_ground_place_id",
]

#: The longest a request waits for a kind's sample checks. Measured 2026-10-06 on the development
#: machine at a load of about 16 to 23: one sample world of a heavy kind (twelve zones, 480
#: fixtures, about 930 walking places, near the 962 its graph may hold) is laid out, checked and
#: walked in about 0.09 s, with its layout within the bounds catalog's ``layout_trials``. A check
#: builds at most 48 samples of up to four candidates, 192 such worlds, about 17 s, and
#: ``check_layout_trials`` bounds the layouts of the whole check. The limit is more than twice that,
#: rounded up to a whole 5 s, the rule the town's samples derive theirs by.
CHECK_SECONDS: Final = 40.0
#: The longest a request waits for one identity's world: up to four candidates of one sample's
#: work; the town's sample limit, 15 s, holds it many times over.
COMPOSE_SECONDS: Final = 15.0
#: The longest a request waits for a site world's drawing: its one kept candidate generated again,
#: within the layout budget it was made under.
DRAWING_SECONDS: Final = 15.0
#: The longest a request waits for the place a site world's society walks: its one kept candidate
#: generated again, as for its drawing, and its walking graph built (about 0.03 s near its 962
#: places, measured 2026-10-06).
PLACE_SECONDS: Final = 15.0
#: The longest a request waits for a site's landscape drawing: its volumes realized at every level
#: the landscape states, and their tops searched. Measured 2026-10-15 on the development machine:
#: the largest landscapes made, five volumes of up to nine parts at the default 2 m finest cell
#: (103 and 104 chunks), were drawn in 17.9 and 19.4 s at a load of 56 to 86. The limit is more
#: than twice the slowest, rounded up to a whole 5 s, the rule the checks' limit is derived by, and
#: is no more than that limit, so :data:`STUCK_SECONDS` stays four times the longest. A landscape
#: the catalog admits beyond these (up to 64 volumes, cells down to 0.5 m) can take far longer:
#: past this it is answered ``overran`` and read once finished, and past :data:`STUCK_SECONDS` its
#: process is replaced.
LANDSCAPE_SECONDS: Final = 40.0
#: Jobs waiting for the worker besides the one it computes.
JOBS_WAITING: Final = 4
#: Jobs one workspace may have waiting or computing: a person's own work is one job at a time, and
#: two lets a world's drawing be read while another world is being made.
WORKSPACE_JOBS: Final = 2
#: Finished checks kept by the kind document's digest: a creator sending one kind twice reads it
#: once.
CHECKS_KEPT: Final = 32
#: Finished drawings kept by their receipt's digest: the site worlds being looked at.
DRAWINGS_KEPT: Final = 16
#: Finished landscape drawings, with every chunk and top they name, kept by their receipt's digest:
#: the site worlds on a landscape being looked at, as many as their drawings. The largest made
#: keeps about 0.8 MB (measured 2026-10-15, with the limit above).
LANDSCAPES_KEPT: Final = DRAWINGS_KEPT
#: Finished places kept by their receipt's digest and place: the site worlds people live in.
PLACES_KEPT: Final = 16
#: How long a job may run before its process is taken for stuck and replaced: four times the
#: longest limit. A request stops waiting at its limit; this bounds how long a process that never
#: finishes holds the queue.
STUCK_SECONDS: Final = 4 * CHECK_SECONDS

_log = logging.getLogger(__name__)

JobStatus = Literal["done", "overran", "busy", "unavailable"]


class Kept:
    """Finished jobs kept by what they were made from, the least recently read dropped past
    ``size``; safe to share between threads. With ``copies``, each read hands out a copy of its
    own, for answers a reader goes on to build from."""

    def __init__(self, size: int, *, copies: bool = False) -> None:
        self._size = size
        self._copies = copies
        self._lock = threading.Lock()
        self._items: OrderedDict[str, dict[str, Any]] = OrderedDict()

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            found = self._items.get(key)
            if found is not None:
                self._items.move_to_end(key)
        if found is not None and self._copies:
            return copy.deepcopy(found)
        return found

    def put(self, key: str, value: dict[str, Any]) -> None:
        with self._lock:
            self._items[key] = value
            self._items.move_to_end(key)
            while len(self._items) > self._size:
                self._items.popitem(last=False)

    def forget(self, prefixes: tuple[str, ...]) -> None:
        """Remove retained answers under exact namespaces, without retaining their digests."""
        with self._lock:
            for key in list(self._items):
                if key.startswith(prefixes):
                    del self._items[key]


@dataclass(frozen=True, slots=True)
class JobOutcome:
    """A job's answer: ``done`` with what the job returned, or why there is none (``busy`` says
    ``workspace`` when it is this workspace's own bound)."""

    status: JobStatus
    value: dict[str, Any] | None = None
    reason: str = ""


class KindWorkWaiting(RuntimeError):
    """A kind job the worker did not answer in time, or could not take: ``overran``, ``busy`` or
    ``unavailable``, with words a person reads and how many seconds to wait before asking again."""

    def __init__(self, status: str, *, kept: bool = True, reason: str = "") -> None:
        if status == "overran":
            words = (
                "This takes longer than a request waits. Ask again shortly: the finished work is "
                "kept and read."
                if kept
                else "Making this world takes longer than a request waits. Ask again shortly."
            )
            retry = 2
        elif status == "busy":
            words = (
                "This workspace is already building worlds of its kinds. Ask again when they are "
                "done."
                if reason == "workspace"
                else "The server is building other worlds of kinds. Ask again shortly."
            )
            retry = 2
        else:
            status = "unavailable"
            words = "Worlds of kinds could not be built here just now."
            retry = 5
        super().__init__(words)
        self.status = status
        self.code = f"kind_work_{status}"
        self.retry_seconds = retry


def check_key(workspace: str, document_sha256: str) -> str:
    """Where a kind's finished check is kept: by its workspace and its document."""
    return f"check:{workspace}:{document_sha256}"


def drawing_key(workspace: str, receipt_sha256: str, parts_sha256: str = "") -> str:
    """Where a site world's drawing is kept: by its workspace, its receipt and the digest of the
    changes a person made to its parts (:func:`~exulanica.world.site_parts.changes_sha256`), which
    is empty, and leaves the key as it was, for a world nobody changed."""
    key = f"drawing:{workspace}:{receipt_sha256}"
    return f"{key}:{parts_sha256}" if parts_sha256 else key


def town_land_key(workspace: str, receipt_sha256: str) -> str:
    """Where a town on its land's land is kept: by its workspace and its receipt alone, since a
    town's land is graded before its buildings and no change to them moves it."""
    return f"town-land:{workspace}:{receipt_sha256}"


def landscape_key(workspace: str, receipt_sha256: str, parts_sha256: str = "") -> str:
    """Where a site world's landscape drawing is kept: by its workspace, its receipt and the digest
    of the changes made to its parts (empty, the key unchanged, for none), as its drawing is, since
    the landscape drawing names that drawing."""
    key = f"landscape:{workspace}:{receipt_sha256}"
    return f"{key}:{parts_sha256}" if parts_sha256 else key


def place_key(workspace: str, receipt_sha256: str, place_id: str, parts_sha256: str = "") -> str:
    """Where the place a site world's society walks is kept: by its workspace, its receipt, its
    place and the digest of the changes made to its parts (empty, the key unchanged, for none)."""
    key = f"place:{workspace}:{receipt_sha256}:{place_id}"
    return f"{key}:{parts_sha256}" if parts_sha256 else key


def part_check_key(
    workspace: str, receipt_sha256: str, place_id: str, parts_sha256: str, part_id: str
) -> str:
    """Where one part change's check is kept: under its world's place, so forgetting a receipt's
    places forgets its checks."""
    return f"{place_key(workspace, receipt_sha256, place_id, parts_sha256)}:check:{part_id}"


# -- in the worker process -----------------------------------------------------------------------

#: The records of the site worlds this process made or read last, by workspace and receipt
#: digest: the drawing read just after a world is made finds the records its making generated.
_RECORDS_KEPT: Final = 8
_records: OrderedDict[str, tuple[object, ...]] = OrderedDict()
_records_lock = threading.Lock()


def _keep_records(workspace: str, receipt_sha256: str, records: tuple[object, ...]) -> None:
    key = f"{workspace}:{receipt_sha256}"
    with _records_lock:
        _records[key] = records
        _records.move_to_end(key)
        while len(_records) > _RECORDS_KEPT:
            _records.popitem(last=False)


def _records_of(
    workspace: str,
    receipt: Mapping[str, Any],
    receipt_sha256: str,
    changes: list[dict[str, Any]] | None = None,
) -> Any:
    """The records a receipt generates again, or the ones this process kept for it, with the
    changes a person made to its parts applied (:func:`~exulanica.world.site_parts.apply_changes`);
    a refusal's words when its receipt no longer reads or a change no longer applies."""
    from exulanica.world.composers.site_plan import records
    from exulanica.world.errors import InvalidStructuralData

    with _records_lock:
        found = _records.get(f"{workspace}:{receipt_sha256}")
    if found is None:
        try:
            found = tuple(records(receipt))
        except InvalidStructuralData as exc:
            return str(exc)
        _keep_records(workspace, receipt_sha256, found)
    if changes:
        from exulanica.world.errors import ThingLandingRefused
        from exulanica.world.site_parts import apply_changes, changes_from_document

        try:
            found = apply_changes(found, changes_from_document(changes))
        except ThingLandingRefused as exc:
            return f"generated_world_part_changes_refused: {exc}"
    return found


def _drawn(
    world_id: str, receipt: Mapping[str, Any], receipt_sha256: str, records: tuple[object, ...]
) -> dict[str, Any]:
    """The drawing as the bytes a response carries (written as the API writes JSON, here rather
    than on the request's thread) and its digest. A site on a landscape's landscape drawing is not
    made here: realizing its volumes is a job of its own (:func:`landscape_job`)."""
    from exulanica.world.composers.site_plan import ON_LAND_VERSIONS, receipt_land
    from exulanica.world.site_drawing import site_drawing, site_drawing_sha256

    drawing = site_drawing(
        world_id=world_id, receipt=receipt, receipt_sha256=receipt_sha256, records=records
    )
    body = json.dumps(
        drawing, ensure_ascii=False, allow_nan=False, indent=None, separators=(",", ":")
    ).encode("utf-8")
    drawn: dict[str, Any] = {"body": body, "sha256": site_drawing_sha256(drawing)}
    if receipt["composer"]["version"] in ON_LAND_VERSIONS:
        # A site on land keeps its chunks and backdrop with its drawing: the land routes serve
        # them by the digests the drawing names.
        drawn["land"] = receipt_land(receipt, records).documents()
    return drawn


def site_ground_place_id() -> str:
    """The place a site world's society walks: its one region's, as every saved world's ground
    names its region's place."""
    from exulanica.world.composers.site_plan import REGION_ID
    from exulanica.world.society_authored_ground import ground_place_id

    return ground_place_id(REGION_ID)


def _placed(
    place_id: str, receipt: Mapping[str, Any], records: tuple[object, ...]
) -> dict[str, Any]:
    """The place a site world's society walks, made from its records within the walking graph's
    budget, or why it cannot be, by name. With the place goes ``blocked``, the site's blocked
    boxes as plain figures: what a society of things keeps a placed thing's standing places clear
    of, which only the records state and the place does not carry; and ``blocked_parts``, the same
    boxes each with what it is and its words, which a move of a placed thing is kept off and told
    about by name."""
    from exulanica.grammar.errors import CatalogError
    from exulanica.world.composers.site_plan import society_place
    from exulanica.world.errors import InvalidStructuralData
    from exulanica.world.society_site_place import (
        GraphOverBudget,
        site_blocked_boxes,
        site_blocked_parts,
    )

    try:
        if receipt["composer"]["version"] in TERRAIN_COMPOSER_VERSIONS:
            from exulanica.world.composers.site_plan import receipt_terrain

            receipt_terrain(receipt)
            return {
                "status": "refused",
                "code": "terrain_society_projection_unavailable",
                "detail": "This terrain has no society projection.",
            }
        return {
            "status": "done",
            "place": society_place(place_id, receipt, records),
            "blocked": site_blocked_boxes(records),
            "blocked_parts": site_blocked_parts(records, _part_uses(receipt)),
        }
    except GraphOverBudget as exc:
        return {
            "status": "refused",
            "code": "kind_graph_over_budget",
            "detail": f"kind_graph_over_budget: {exc}",
        }
    except (CatalogError, InvalidStructuralData, ValueError) as exc:
        return {"status": "refused", "code": "kind_place_refused", "detail": str(exc)}


def _part_uses(receipt: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """The words a site's kind gives each part, from the receipt, or None where it states none."""
    from exulanica.world.society_site_place import SiteSociety

    society = receipt.get("society")
    if not isinstance(society, Mapping):
        return None
    try:
        return SiteSociety.read(society).uses
    except (KeyError, TypeError, ValueError):
        return None


def check_job(document: dict[str, Any]) -> dict[str, Any]:
    """Read the kind and build its sample worlds: the report, or the refusal by name."""
    from exulanica.world.kinds.document import KindRefused, read_kind
    from exulanica.world.kinds.samples import check_samples

    try:
        return {"status": "done", "report": check_samples(read_kind(document))}
    except KindRefused as refused:
        return {
            "status": "refused",
            "code": refused.code,
            "detail": refused.detail,
            "where": refused.where,
            "report": getattr(refused, "report", None),
        }


def compose_job(
    workspace: str,
    document: dict[str, Any],
    values: dict[str, int],
    world_id: str,
    support: dict[str, Any] | None = None,
    land: dict[str, Any] | None = None,
    landscape: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compose the world the kind makes with ``values`` for ``world_id`` and draw it, with the
    place its society walks (the one its checks built), or say why not. A site on a landscape is
    drawn without its landscape's: :func:`landscape_job` realizes its volumes when it is read."""
    from exulanica.grammar.landform import LandformRefused
    from exulanica.grammar.landscape import LandscapeRefused
    from exulanica.world.composers.site_plan import compose_kind
    from exulanica.world.kinds.document import read_kind
    from exulanica.world.kinds.samples import SiteRefused
    from exulanica.world.society_site_place import site_blocked_boxes, site_blocked_parts
    from exulanica.world.support_surfaces import SupportRefused

    place_id = site_ground_place_id()
    try:
        composed = compose_kind(
            read_kind(document),
            values,
            world_id,
            place_id=place_id,
            support=support,
            land=land,
            landscape=landscape,
        )
    except LandscapeRefused as refused:
        return {
            "status": "landscape_refused",
            "code": refused.code,
            "detail": refused.detail,
            "path": refused.path,
        }
    except LandformRefused as refused:
        return {
            "status": "land_refused",
            "code": refused.code,
            "detail": refused.detail,
            "path": refused.path,
        }
    except SupportRefused as refused:
        return {
            "status": "support_refused",
            "code": refused.code,
            "detail": refused.detail,
            "where": refused.where,
        }
    except SiteRefused as refused:
        return {"status": "refused", "code": refused.code, "refusals": list(refused.refusals)}
    records = tuple(composed.records)
    _keep_records(workspace, composed.receipt_sha256, records)
    return {
        "status": "done",
        "composed": composed,
        **_drawn(world_id, composed.receipt, composed.receipt_sha256, records),
        "place_id": place_id,
        # Kept as the place job keeps it: the place, and the site's blocked boxes beside it.
        "placed": {
            "status": "done",
            "place": composed.place,
            "blocked": site_blocked_boxes(records),
            "blocked_parts": site_blocked_parts(records, _part_uses(composed.receipt)),
        },
    }


def compose_terrain_job(workspace: str, authoring: dict, world_id: str) -> dict[str, Any]:
    """Admit and draw retained terrain in the existing bounded process worker."""
    from exulanica.world.composers.site_plan import compose_terrain
    from exulanica.world.terrain_authoring import TerrainAuthoringRefused

    try:
        composed = compose_terrain(authoring, world_id)
    except TerrainAuthoringRefused as exc:
        return {"status": "terrain_refused", "code": exc.code, "detail": exc.detail}
    records = tuple(composed.records)
    _keep_records(workspace, composed.receipt_sha256, records)
    place_id = site_ground_place_id()
    return {
        "status": "done",
        "composed": composed,
        **_drawn(world_id, composed.receipt, composed.receipt_sha256, records),
        "place_id": place_id,
        "placed": _placed(place_id, composed.receipt, records),
    }


def drawing_job(
    workspace: str,
    world_id: str,
    receipt: dict[str, Any],
    receipt_sha256: str,
    changes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """A site world's drawing, from the records its receipt generates again (or the ones its making
    left here) with ``changes`` to its parts applied, or the reason it cannot be drawn."""
    found = _records_of(workspace, receipt, receipt_sha256, changes)
    if isinstance(found, str):
        return {"status": "refused", "detail": found}
    return {"status": "done", **_drawn(world_id, receipt, receipt_sha256, found)}


def landscape_job(
    world_id: str, receipt: dict[str, Any], receipt_sha256: str, site_drawing_sha256: str
) -> dict[str, Any]:
    """A site on a landscape's landscape drawing, naming the site's drawing by
    ``site_drawing_sha256``: its volumes realized from the receipt alone, the drawing as the bytes
    a response carries with its digest, and every chunk and top it names as bytes by its digest
    (``chunks``, ``tops``), which the landscape routes serve; or the reason the receipt's
    landscape no longer reads."""
    from exulanica.world.errors import InvalidStructuralData
    from exulanica.world.landscape_drawing import landscape_drawing, landscape_drawing_sha256

    try:
        landscape, bodies = landscape_drawing(
            world_id, receipt, receipt_sha256, site_drawing_sha256
        )
    except InvalidStructuralData as exc:
        return {"status": "refused", "detail": str(exc)}
    return {
        "status": "done",
        "body": json.dumps(
            landscape, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8"),
        "sha256": landscape_drawing_sha256(landscape),
        **{
            kind: {
                digest: json.dumps(document, separators=(",", ":")).encode("utf-8")
                for digest, document in bodies.items()
                if document["profile"] == profile
            }
            for kind, profile in (
                ("chunks", "exulanica.volume-chunk/v1"),
                ("tops", "exulanica.volume-sheet/v1"),
            )
        },
    }


#: The profile of a town on its land's land section (``GET /world/versions/{version_id}/land``).
TOWN_LAND_PROFILE: Final = "exulanica.town-land/v1"


def town_land_job(world_id: str, receipt: dict[str, Any], receipt_sha256: str) -> dict[str, Any]:
    """A town on its land's land, from the records its receipt generates again: its section (the
    chunks, backdrop and water it names, as the bytes a response carries, and their digest) and
    every chunk and the backdrop it names, or the reason it cannot be read."""
    from exulanica.canonical import canonical_json
    from exulanica.world.composers.city_grammar_town import graded_land, records
    from exulanica.world.errors import InvalidStructuralData

    try:
        land = graded_land(receipt, records(receipt))
    except InvalidStructuralData as exc:
        return {"status": "refused", "detail": str(exc)}
    body = canonical_json(
        {
            "profile": TOWN_LAND_PROFILE,
            "world_id": world_id,
            "receipt_sha256": receipt_sha256,
            "land": land.drawing_section(),
        }
    )
    return {
        "status": "done",
        "body": body,
        "sha256": hashlib.sha256(body).hexdigest(),
        "land": land.documents(),
    }


def place_job(
    workspace: str,
    receipt: dict[str, Any],
    receipt_sha256: str,
    place_id: str,
    changes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The place a site world's society walks, from the records its receipt generates again (or
    the ones its making left here) with ``changes`` to its parts applied, or the reason it cannot
    be made."""
    found = _records_of(workspace, receipt, receipt_sha256, changes)
    if isinstance(found, str):
        return {"status": "refused", "code": "kind_place_refused", "detail": found}
    return _placed(place_id, receipt, found)


def part_job(
    workspace: str,
    receipt: dict[str, Any],
    receipt_sha256: str,
    place_id: str,
    changes: list[dict[str, Any]],
    part_id: str,
) -> dict[str, Any]:
    """Whether one part may stand as ``changes`` leave it (:func:`~exulanica.world.site_parts.
    check_change`), and whether people still reach every place of the world it makes from the
    entry: its place, as :func:`place_job` answers for the same changes, or the refusal by code
    with what refused it (``where``) and a sentence a person reads."""
    from exulanica.world.errors import ThingLandingRefused
    from exulanica.world.kinds.samples import first_unreached
    from exulanica.world.site_parts import (
        apply_changes,
        changeable_parts,
        changes_from_document,
        check_change,
        check_storeys,
        receipt_storeys_bound,
    )

    found = _records_of(workspace, receipt, receipt_sha256)
    if isinstance(found, str):
        return {"status": "refused", "code": "kind_place_refused", "detail": found}
    uses = _part_uses(receipt)
    made = changeable_parts(found, uses)
    try:
        stated = changes_from_document(changes)
        storeys = next((c.storeys for c in stated if c.identity == part_id), None)
        if storeys is not None:
            check_storeys(storeys, receipt_storeys_bound(receipt), part_id)
        changed = apply_changes(found, stated)
        check_change(
            changed,
            part_id,
            root_identity=str(receipt["subject_identity"]),
            uses=uses,
        )
    except ThingLandingRefused as exc:
        return {"status": "refused", "code": exc.code, "where": exc.where, "detail": str(exc)}
    graded = _graded(receipt, changed, part_id)
    if graded is not None:
        return graded
    placed = _placed(place_id, receipt, changed)
    if placed["status"] != "done":
        return placed
    unreached = first_unreached(placed["place"])
    if unreached is not None:
        return {
            "status": "refused",
            "code": "part_strands_people",
            "where": {"part_id": part_id, "destination_id": unreached["destination_id"]},
            "detail": f"Not here: people could no longer reach the {unreached['label']} from "
            "the entry.",
        }
    return {
        **placed,
        "part_ids": [part.identity for part in made],
        "label": next((part.label for part in made if part.identity == part_id), ""),
    }


def _graded(
    receipt: Mapping[str, Any], changed: tuple[object, ...], part_id: str
) -> dict[str, Any] | None:
    """On a world on land, whether its land takes the changed layout: None where it does (or the
    world stands on level ground), else the refusal by the land grader's code with a sentence a
    person reads (:data:`~exulanica.world.site_parts.LAND_WORDS`) and the grader's own detail in
    ``where``. The graded land is kept by the records' digest, so the drawing and the place that
    follow read it again rather than grading twice."""
    from exulanica.grammar.landform import LandformRefused
    from exulanica.world.composers.site_plan import ON_LAND_VERSIONS, receipt_routine
    from exulanica.world.errors import InvalidStructuralData
    from exulanica.world.site_land import site_land_of
    from exulanica.world.site_parts import LAND_WORDS, LAND_WORDS_OTHERWISE, PART_CODES

    if receipt["composer"]["version"] not in ON_LAND_VERSIONS:
        return None
    try:
        site_land_of(
            receipt, changed, receipt_routine(receipt).policy["footway_station_spacing_mm"]
        )
    except InvalidStructuralData as exc:
        # The receipt's land no longer reads under this code (its rules or document): the world's
        # refusal, as its records' would be, not the move's. Regenerating its records reads the
        # same land first, so this is not met after they read.
        return {"status": "refused", "code": "kind_place_refused", "detail": str(exc)}
    except LandformRefused as exc:
        return {
            "status": "refused",
            "code": exc.code if exc.code in PART_CODES else "landform_invalid",
            "where": {"part_id": part_id, "landform_code": exc.code, "landform": exc.detail},
            "detail": LAND_WORDS.get(exc.code, LAND_WORDS_OTHERWISE),
        }
    return None


def parts_job(
    workspace: str,
    receipt: dict[str, Any],
    receipt_sha256: str,
    changes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The parts of a site world a person may change, as they stand with ``changes`` applied
    (:func:`~exulanica.world.site_parts.changeable_parts`), or the reason its records do not
    read."""
    from exulanica.world.errors import ThingLandingRefused
    from exulanica.world.site_parts import changeable_parts, receipt_storeys_bound

    found = _records_of(workspace, receipt, receipt_sha256, changes)
    if isinstance(found, str):
        return {"status": "refused", "detail": found}
    try:
        most: int | None = receipt_storeys_bound(receipt)[1]
    except ThingLandingRefused:
        most = None
    return {
        "status": "done",
        "parts": [part.document() for part in changeable_parts(found, _part_uses(receipt))],
        "storeys_most": most,
    }


# -- in the server ------------------------------------------------------------------------------


class _Running:
    """A job handed to the pool: the pool, when, whose, where it is kept, and its future once the
    pool has taken it."""

    __slots__ = ("executor", "future", "invalidated", "kept", "started", "workspace")

    def __init__(
        self, executor: Executor, started: float, workspace: str, kept: Kept | None
    ) -> None:
        self.executor = executor
        self.started = started
        self.workspace = workspace
        self.kept = kept
        self.invalidated = False
        self.future: Future[dict[str, Any]] | None = None


def _terminate(executor: Executor) -> None:
    """Let a pool go without waiting on it, and stop any process it still runs (as the town's
    samples do: no public way to stop a pool's processes before Python 3.14)."""
    processes = list((getattr(executor, "_processes", None) or {}).values())
    executor.shutdown(wait=False, cancel_futures=True)
    for process in processes:
        if process.is_alive():
            process.terminate()


class KindWorker:
    """Kind jobs one worker computes, bounded and kept; safe to share between threads."""

    def __init__(
        self,
        executor: Callable[[], Executor] = sample_process_pool,
        *,
        waiting: int = JOBS_WAITING,
        per_workspace: int = WORKSPACE_JOBS,
        stuck_seconds: float = STUCK_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._make = executor
        self._waiting = waiting
        self._per_workspace = per_workspace
        self._stuck = stuck_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._executor: Executor | None = None
        self._running: dict[str, _Running] = {}
        self._closed = False
        self._epoch = 0
        #: Finished checks, by their workspace and the kind document's digest.
        self.checks = Kept(CHECKS_KEPT)
        #: Finished drawings, by their workspace and receipt's digest.
        self.drawings = Kept(DRAWINGS_KEPT)
        #: Finished landscape drawings and the chunks and tops they name, by their workspace and
        #: receipt's digest.
        self.landscapes = Kept(LANDSCAPES_KEPT)
        #: Finished places, by their workspace, receipt's digest and place, each read a copy.
        self.places = Kept(PLACES_KEPT, copies=True)

    @property
    def epoch(self) -> int:
        with self._lock:
            return self._epoch

    def forget_receipts(self, workspace: str, digests: frozenset[str]) -> None:
        """Evict erased worlds' parent answers and discard the owned child holding documents.

        This worker uses one shared child, so its other in-flight jobs become unavailable and
        can retry from durable inputs. Other worlds' finished parent answers stay available.
        Late results cannot refill caches; no removed content digest is retained by this method.
        Other API processes still require their own invalidation.
        """
        if not digests:
            return
        with self._lock:
            self._epoch += 1
            self.drawings.forget(
                tuple(drawing_key(workspace, digest) for digest in digests)
                + tuple(town_land_key(workspace, digest) for digest in digests)
            )
            self.landscapes.forget(tuple(landscape_key(workspace, digest) for digest in digests))
            self.checks.forget((f"terrain-coverage:v1:{workspace}:",))
            self.places.forget(tuple(f"place:{workspace}:{digest}:" for digest in digests))
            executor, self._executor = self._executor, None
            for running in self._running.values():
                running.invalidated = True
            self._running.clear()
        if executor is not None:
            _terminate(executor)

    def forget_kind(self, workspace: str, digest: str) -> None:
        """Discard a kept kind's checks and owned child, invalidating late completions."""
        with self._lock:
            self._epoch += 1
            self.checks.forget((check_key(workspace, digest),))
            executor, self._executor = self._executor, None
            for running in self._running.values():
                running.invalidated = True
            self._running.clear()
        if executor is not None:
            _terminate(executor)

    def keep_composed(
        self,
        epoch: int,
        drawn: tuple[str, dict[str, Any]] | None,
        placed: tuple[str, dict[str, Any]] | None,
    ) -> None:
        """Publish a completed composition only while its worker generation is still current."""
        with self._lock:
            if self._closed or epoch != self._epoch:
                return
            if drawn is not None:
                self.drawings.put(*drawn)
            if placed is not None:
                self.places.put(*placed)

    def run(
        self,
        key: str,
        seconds: float,
        job: Callable[..., dict[str, Any]],
        *args: Any,
        workspace: str,
        kept: Kept | None = None,
    ) -> JobOutcome:
        """``job(*args)`` in the worker for ``workspace``, waited for at most ``seconds``; kept in
        ``kept`` under ``key`` when it finishes, if given."""
        self._let_stuck_go()
        with self._lock:
            if self._closed:
                # Closed with its server: a job still asking (a draft's thread) starts no process.
                return JobOutcome("unavailable", reason="closed")
            found = None if kept is None else kept.get(key)
            if found is not None:
                return JobOutcome("done", found)
            if key in self._running:
                return JobOutcome("overran")
            if len(self._running) > self._waiting:
                return JobOutcome("busy")
            mine = sum(1 for running in self._running.values() if running.workspace == workspace)
            if mine >= self._per_workspace:
                return JobOutcome("busy", reason="workspace")
            executor = self._executor
            if executor is None:
                executor = self._executor = self._make()
            running = self._running[key] = _Running(executor, self._clock(), workspace, kept)
        try:
            future = executor.submit(job, *args)
        except Exception as failed:
            # A pool that cannot take the job (broken, shut down, or unable to start its process)
            # leaves no job behind, counted against the workspace and the queue, and is let go.
            with self._lock:
                if self._running.get(key) is running:
                    del self._running[key]
            if not isinstance(failed, BrokenProcessPool | RuntimeError):
                _log.exception("the kind worker could not take a job")
            self._discard(executor)
            return JobOutcome("unavailable")
        running.future = future
        # Added once the future is recorded: a future already done runs it at once, here.
        future.add_done_callback(functools.partial(self._finished, key, running))
        try:
            value = future.result(timeout=seconds)
            with self._lock:
                if running.invalidated:
                    return JobOutcome("unavailable")
            return JobOutcome("done", value)
        except FutureTimeout:
            return JobOutcome("overran")
        except (BrokenProcessPool, CancelledError):
            self._discard(executor)
            return JobOutcome("unavailable")
        except Exception:
            # A defect in the job, not a refusal: said at ERROR, answered as unavailable.
            _log.exception("a world kind job failed")
            return JobOutcome("unavailable")

    def _let_stuck_go(self) -> None:
        with self._lock:
            if not self._running:
                return
            oldest = min(self._running.values(), key=lambda running: running.started)
            if self._clock() - oldest.started <= self._stuck:
                return
            executor = oldest.executor
        _log.error("a world kind job ran past %s s; its worker is replaced", self._stuck)
        self._discard(executor)

    def _discard(self, executor: Executor) -> None:
        with self._lock:
            if self._executor is executor:
                self._executor = None
            for key in [k for k, running in self._running.items() if running.executor is executor]:
                self._running[key].invalidated = True
                del self._running[key]
        _terminate(executor)

    def _finished(self, key: str, running: _Running, future: Future[dict[str, Any]]) -> None:
        with self._lock:
            if self._running.get(key) is running:
                # Publish and retire under one lock. An obsolete pool's late callback may
                # neither restore discarded content nor overwrite a replacement job's answer.
                if (
                    not future.cancelled()
                    and future.exception() is None
                    and running.kept is not None
                ):
                    running.kept.put(key, future.result())
                del self._running[key]

    def close(self) -> None:
        """Stop the worker without waiting on a stuck job, for good: a later job is answered
        ``unavailable`` and starts no process. The server's lifespan calls this."""
        with self._lock:
            self._closed = True
            executor, self._executor = self._executor, None
            for running in self._running.values():
                running.invalidated = True
            self._running.clear()
        if executor is not None:
            _terminate(executor)


#: This server's kind jobs and the worker process computing them, started at the first job.
_worker = KindWorker()


def kind_worker() -> KindWorker:
    """This server's kind worker."""
    return _worker


def close_kind_worker() -> None:
    """Stop the worker process; the server's lifespan calls this as it ends. The worker is closed
    for good and a fresh one, which starts nothing until its first job, takes its place, so a
    caller that took the closed worker earlier (a draft still running) starts no process, and a
    server started later in the same process (a test's) has a worker."""
    global _worker
    closed, _worker = _worker, KindWorker()
    closed.close()


class WorkerComposer:
    """Composes one identity's world of a kind in the kind worker for one workspace, and keeps the
    drawing and the society's place of the last world it made, which is the world saved when the
    making succeeds. What makes a world of a kind hands this to the saved entries, so no
    generation runs on a request's thread or a draft's, and then keeps :attr:`drawn` and
    :attr:`placed` with :meth:`keep`."""

    def __init__(
        self,
        workspace: Any,
        *,
        support: Mapping[str, Any] | None = None,
        land: Mapping[str, Any] | None = None,
        landscape: Mapping[str, Any] | None = None,
        seconds: float = COMPOSE_SECONDS,
    ) -> None:
        self.workspace = str(workspace)
        #: How long a making waits for its world: a request's limit unless the caller holds no
        #: request (a draft's job), which may wait longer for a world on land.
        self._seconds = seconds
        self._worker = kind_worker()
        self._epoch = self._worker.epoch
        self._support = None if support is None else copy.deepcopy(dict(support))
        self._support_key = ""
        self._land = None if land is None else copy.deepcopy(dict(land))
        self._land_key = ""
        if self._land is not None:
            from exulanica.canonical import sha256_of_canonical
            from exulanica.grammar.landform import LandformRefused

            try:
                self._land_key = f":land:{sha256_of_canonical(self._land).hex()}"
            except (TypeError, ValueError) as exc:
                raise LandformRefused("land is canonical integer JSON", path="land") from exc
        self._landscape = None if landscape is None else copy.deepcopy(dict(landscape))
        if self._landscape is not None:
            from exulanica.canonical import sha256_of_canonical
            from exulanica.grammar.landscape import LandscapeRefused

            try:
                self._land_key += f":landscape:{sha256_of_canonical(self._landscape).hex()}"
            except (TypeError, ValueError) as exc:
                raise LandscapeRefused(
                    "landscape is canonical integer JSON", path="landscape"
                ) from exc
        if self._support is not None:
            from exulanica.canonical import sha256_of_canonical
            from exulanica.world.support_surfaces import SupportRefused

            try:
                self._support_key = f":support:{sha256_of_canonical(self._support).hex()}"
            except (TypeError, ValueError) as exc:
                raise SupportRefused("support", "is canonical integer JSON") from exc
        #: The last world's drawing and its society's place, each by where the worker keeps it.
        self.drawn: tuple[str, dict[str, Any]] | None = None
        self.placed: tuple[str, dict[str, Any]] | None = None

    def __call__(self, kind: Any, values: Mapping[str, int], world_id: str) -> Any:
        from exulanica.grammar.landform import LandformRefused
        from exulanica.world.kinds.samples import SiteRefused
        from exulanica.world.support_surfaces import SupportRefused

        outcome = self._worker.run(
            f"compose:{self.workspace}:{kind.sha256}:{world_id}:"
            f"{json.dumps(dict(values), sort_keys=True)}" + self._support_key + self._land_key,
            self._seconds,
            compose_job,
            self.workspace,
            dict(kind.document),
            dict(values),
            world_id,
            self._support,
            *(
                ()
                if self._land is None and self._landscape is None
                else (self._land, self._landscape)
            ),
            workspace=self.workspace,
        )
        if outcome.status != "done" or outcome.value is None:
            raise KindWorkWaiting(outcome.status, kept=False, reason=outcome.reason)
        answer = outcome.value
        if answer["status"] == "landscape_refused":
            from exulanica.grammar.landscape import LandscapeRefused

            raise LandscapeRefused(answer["detail"], path=answer["path"], code=answer["code"])
        if answer["status"] == "land_refused":
            raise LandformRefused(answer["detail"], path=answer["path"], code=answer["code"])
        if answer["status"] == "support_refused":
            raise SupportRefused(answer["where"], answer["detail"])
        if answer["status"] == "refused":
            raise SiteRefused(answer["code"], answer["refusals"])
        composed = answer["composed"]
        drawn = {"status": "done", "body": answer["body"], "sha256": answer["sha256"]}
        if "land" in answer:
            drawn["land"] = answer["land"]
        self.drawn = (drawing_key(self.workspace, composed.receipt_sha256), drawn)
        self.placed = (
            place_key(self.workspace, composed.receipt_sha256, answer["place_id"]),
            answer["placed"],
        )
        return composed

    def keep(self) -> None:
        """Keep the made world's drawing and its society's place where the worker reads them:
        the page reads the drawing next, and bringing people in reads the place."""
        self._worker.keep_composed(self._epoch, self.drawn, self.placed)


class TerrainWorkerComposer:
    """Compose explicit terrain using the existing workspace cache and erasure epoch."""

    def __init__(self, workspace: Any) -> None:
        self.workspace = str(workspace)
        self._worker = kind_worker()
        self._epoch = self._worker.epoch
        self.drawn: tuple[str, dict[str, Any]] | None = None
        self.placed: tuple[str, dict[str, Any]] | None = None

    def __call__(self, authoring: dict, world_id: str) -> Any:
        from exulanica.canonical import sha256_of_canonical
        from exulanica.world.terrain_authoring import TerrainAuthoringRefused

        try:
            source_sha = sha256_of_canonical(authoring).hex()
        except (TypeError, ValueError) as exc:
            raise TerrainAuthoringRefused("Terrain source must be canonical integer JSON") from exc
        outcome = self._worker.run(
            f"compose-terrain:{self.workspace}:{source_sha}:{world_id}",
            COMPOSE_SECONDS,
            compose_terrain_job,
            self.workspace,
            copy.deepcopy(authoring),
            world_id,
            workspace=self.workspace,
        )
        if outcome.status != "done" or outcome.value is None:
            raise KindWorkWaiting(outcome.status, kept=False, reason=outcome.reason)
        answer = outcome.value
        if answer["status"] == "terrain_refused":
            raise TerrainAuthoringRefused(answer["detail"])
        composed = answer["composed"]
        drawn = {"status": "done", "body": answer["body"], "sha256": answer["sha256"]}
        if "land" in answer:
            drawn["land"] = answer["land"]
        self.drawn = (drawing_key(self.workspace, composed.receipt_sha256), drawn)
        self.placed = (
            place_key(self.workspace, composed.receipt_sha256, answer["place_id"]),
            answer["placed"],
        )
        return composed

    def keep(self) -> None:
        """Retain results only while their workspace erasure epoch still matches."""
        self._worker.keep_composed(self._epoch, self.drawn, self.placed)


def terrain_dressing_coverage_job(document: dict, components: dict[str, bytes]) -> dict[str, Any]:
    """Pure bounded decoding and exact coverage; it grants no current source authority."""
    from exulanica.world.asset_preparation import decode_texture
    from exulanica.world.terrain_dressing import compile_terrain_dressing, read_terrain_dressing

    try:
        coverage = compile_terrain_dressing(
            read_terrain_dressing(document), components, decode_image=decode_texture
        )
    except ValueError as exc:
        return {"status": "refused", "detail": str(exc)}
    return {"status": "done", "coverage": coverage}


class TerrainDressingWorkerCompiler:
    """Cache pure coverage in existing bounded kind checks, scoped to a workspace and source."""

    def __init__(self, workspace: Any) -> None:
        self.workspace = str(workspace)
        self.worker = kind_worker()

    def __call__(self, dressing: Any, components: dict[str, bytes]) -> Any:
        from exulanica.world.terrain_authoring import TerrainAuthoringRefused

        outcome = self.worker.run(
            f"terrain-coverage:v1:{self.workspace}:{dressing.sha256}",
            DRAWING_SECONDS,
            terrain_dressing_coverage_job,
            dressing.document(),
            components,
            workspace=self.workspace,
            kept=self.worker.checks,
        )
        if outcome.status != "done" or outcome.value is None:
            raise KindWorkWaiting(outcome.status, kept=True, reason=outcome.reason)
        if outcome.value["status"] != "done":
            raise TerrainAuthoringRefused(outcome.value["detail"])
        return outcome.value["coverage"]
