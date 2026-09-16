"""A workspace's own material recipes and bakes: the repository the routes and the worker share.

Migration 0066 is the schema and says why it has this shape. What this module adds is the half
that decides before anything is written:

**A recipe is checked before it is stored.** It must be canonical, portable JSON; it must name a
maker version :data:`~exulanica.world.texture_assets.PUBLISHED_MAKER_MANIFESTS` pins; and
:func:`exulanica.materials.recipe_problems` must find nothing wrong with it against that maker's
manifest, the same check the baker makes and the published library passes. A recipe varied from a
published set must use that set's maker. The person's label is checked and kept outside every
digest.

**Photo-derived recipes are inert.** :meth:`MaterialRepository.create_recipe` refuses that origin
before the database does, and neither path can be talked past until the personal model right
(0073) exists and the service that checks it is written.

**Reads ask the schema whether a recipe is still readable,** through
``tombstone_blocks_material_recipe`` in the query itself, and tell "never existed here" (404) from
"withdrawn or deleted" (410). Bytes are read from the workspace's own store namespace, hash-checked,
and released only after the 0041 final check has seen the bake still current under the asset-read
lock, so a withdrawal cannot slip between the check and the bytes.

**A bake is requested here and made elsewhere.** :meth:`MaterialRepository.request_bake` puts a
row in the queue and records the request, which the schema counts against the workspace's quota;
``exulanica.world.material_bakes`` is the worker that claims it. A bake whose bytes have gone
missing is re-queued by asking again, and the worker must reproduce the digest already recorded.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Final, Literal, TypeVar

import psycopg
from psycopg.types.json import Jsonb

from exulanica.errors import (
    BlobNotFoundError,
    CanonicalisationError,
    ExulanicaError,
    IntegrityError,
)
from exulanica.evidence.blob import BlobId
from exulanica.materials import (
    MaterialCatalog,
    MaterialObjectError,
    canonical_bytes,
    read_object,
    recipe_problems,
    thaw,
)
from exulanica.materials.workspace import WORKSPACE_LICENCE_ID, workspace_set_id
from exulanica.store.namespaces import WorkspaceStores
from exulanica.world.texture_assets import PUBLISHED_MAKER_MANIFESTS, TEXTURE_SET_MEDIA_TYPE

_T = TypeVar("_T")

__all__ = [
    "AUTHORABLE_ORIGINS",
    "AuthorizedBake",
    "BakeBytesMissing",
    "BakeNotReady",
    "BakeQuotaExceeded",
    "BakeRecord",
    "InvalidRecipe",
    "MaterialBusy",
    "MaterialError",
    "MaterialRepository",
    "MaterialRuntime",
    "MaterialWithdrawn",
    "PhotoDerivedRecipeInert",
    "RecipeRecord",
    "UnknownMaterial",
]

#: The origins a recipe may be created with today. `photo_derived` waits for migration 0073.
AUTHORABLE_ORIGINS: Final = ("authored", "proposed")
_LABEL_LIMIT: Final = 200
_CONTROL: Final = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_TOMBSTONED: Final = "tombstoned: write refused"
#: How often a write that met a delivery in progress is tried, in all.
_ATTEMPTS: Final = 5


class MaterialError(ExulanicaError):
    """Base class for the material repository's refusals. Each maps to one API problem."""


class InvalidRecipe(MaterialError):
    """The recipe, its maker, origin, base or label is not one this workspace may hold."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = tuple(problems)


class PhotoDerivedRecipeInert(MaterialError):
    """No recipe comes from a personal photograph before the personal model right exists."""


class UnknownMaterial(MaterialError):
    """No such recipe in this workspace."""


class MaterialWithdrawn(MaterialError):
    """The recipe was withdrawn, or a deletion reached it, so it and its bake are not served."""


class BakeNotReady(MaterialError):
    """The recipe has no finished bake: never requested, waiting, running or failed."""


class BakeBytesMissing(MaterialError):
    """The bake is recorded but its bytes are not in the store. Requesting it again re-bakes it."""


class BakeQuotaExceeded(MaterialError):
    """The workspace has used its bake requests for the day, or has too many waiting."""


class MaterialBusy(MaterialError):
    """A delivery held the 0041 read lock through every retry. Asking again shortly succeeds."""


@dataclass(frozen=True, slots=True)
class MaterialRuntime:
    """What a process serving recipes holds: the published makers and sets, and the namespaces."""

    catalog: MaterialCatalog
    stores: WorkspaceStores


@dataclass(frozen=True, slots=True)
class RecipeRecord:
    recipe_id: uuid.UUID
    origin: str
    maker_id: str
    maker_version: int
    maker_sha256: str
    recipe_sha256: str
    recipe: Mapping[str, Any]
    based_on: tuple[str, int] | None
    label: str | None
    created_by: uuid.UUID
    created_at: dt.datetime


@dataclass(frozen=True, slots=True)
class BakeRecord:
    bake_id: uuid.UUID
    recipe_id: uuid.UUID
    set_id: str
    state: str
    attempts: int
    requested_at: dt.datetime
    content_sha256: str | None
    byte_size: int | None
    receipt: Mapping[str, Any] | None
    baked_at: dt.datetime | None
    failure_class: str | None
    failure_message: str | None
    licence_id: str = WORKSPACE_LICENCE_ID


@dataclass(frozen=True, slots=True)
class AuthorizedBake:
    """A container this workspace may be sent now, checked and still current."""

    data: bytes
    content_sha256: str
    set_id: str
    media_type: str = TEXTURE_SET_MEDIA_TYPE
    licence_id: str = WORKSPACE_LICENCE_ID


_RECIPE_COLUMNS: Final = (
    "r.recipe_id, r.origin, r.maker_id, r.maker_version, r.maker_sha256, r.recipe_canonical, "
    "r.recipe_sha256, r.based_on_set_id, r.based_on_version, r.label, r.created_by, r.created_at"
)
_BAKE_COLUMNS: Final = (
    "b.bake_id, b.recipe_id, b.set_id, b.state, b.attempts, b.requested_at, b.content_sha256, "
    "b.byte_size, b.receipt_canonical, b.baked_at, b.failure_class, b.failure_message, "
    "b.purged_at"
)


def _hex(value: bytes | memoryview | None) -> str | None:
    return None if value is None else bytes(value).hex()


def _recipe(row: Mapping[str, Any]) -> RecipeRecord:
    based_on = row["based_on_set_id"]
    return RecipeRecord(
        recipe_id=row["recipe_id"],
        origin=row["origin"],
        maker_id=row["maker_id"],
        maker_version=row["maker_version"],
        maker_sha256=bytes(row["maker_sha256"]).hex(),
        recipe_sha256=bytes(row["recipe_sha256"]).hex(),
        recipe=read_object(bytes(row["recipe_canonical"]), "stored recipe"),
        based_on=None if based_on is None else (based_on, row["based_on_version"]),
        label=row["label"],
        created_by=row["created_by"],
        created_at=row["created_at"],
    )


def _bake(row: Mapping[str, Any]) -> BakeRecord:
    receipt = row["receipt_canonical"]
    return BakeRecord(
        bake_id=row["bake_id"],
        recipe_id=row["recipe_id"],
        set_id=row["set_id"],
        state=row["state"],
        attempts=row["attempts"],
        requested_at=row["requested_at"],
        content_sha256=_hex(row["content_sha256"]),
        byte_size=row["byte_size"],
        receipt=None if receipt is None else read_object(bytes(receipt), "stored receipt"),
        baked_at=row["baked_at"],
        failure_class=row["failure_class"],
        failure_message=row["failure_message"],
    )


def _label_problem(label: object) -> str | None:
    if label is None:
        return None
    if (
        not isinstance(label, str)
        or not 1 <= len(label) <= _LABEL_LIMIT
        or label != label.strip()
        or _CONTROL.search(label) is not None
    ):
        return f"a label is 1 to {_LABEL_LIMIT} characters, trimmed, with no control characters"
    return None


@contextmanager
def _refusals() -> Iterator[None]:
    """The schema's refusals, as the repository's own."""
    try:
        yield
    except psycopg.errors.ProgramLimitExceeded as error:
        raise BakeQuotaExceeded(error.diag.message_primary or "bake quota exceeded") from error
    except psycopg.errors.IntegrityConstraintViolation as error:
        if (error.diag.message_primary or "").startswith(_TOMBSTONED):
            raise MaterialWithdrawn("a deletion or a withdrawal reached this recipe") from error
        raise
    except psycopg.errors.InsufficientPrivilege as error:
        if "personal model right" in (error.diag.message_primary or ""):
            raise PhotoDerivedRecipeInert(error.diag.message_primary or "") from error
        raise


def _retrying(operation: Callable[[], _T]) -> _T:
    """Run a write again when a delivery held the 0041 read lock, which fails it fast.

    ``aaa_asset_read_mutation`` refuses a write while any delivery holds the read lock rather than
    letting it wait, so the write is safe to repeat as a whole, and it is.
    """
    for attempt in range(_ATTEMPTS):
        try:
            return operation()
        except psycopg.errors.SerializationFailure as error:
            if attempt == _ATTEMPTS - 1:
                raise MaterialBusy("a delivery was in progress; ask again") from error
            time.sleep(0.05 * (attempt + 1))
    raise AssertionError("unreachable")


class MaterialRepository:
    """Recipes and bakes in one workspace, through a connection scoped to that workspace.

    **Lock order.** Every write that can touch a bake row takes the workspace's lifecycle lock
    (``material_bake_lifecycle_lock``) first, before any row lock, because a tombstone takes that
    lock and then updates bake rows. Taking a row lock first and the lifecycle lock second, which
    is what the bake guard alone would do, can deadlock against a deletion.
    """

    def __init__(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        actor: uuid.UUID,
        *,
        catalog: MaterialCatalog,
        stores: WorkspaceStores,
    ) -> None:
        self.connection = connection
        self.workspace_id = workspace_id
        self.actor = actor
        self.catalog = catalog
        self.stores = stores

    # -- recipes ------------------------------------------------------------------------

    def create_recipe(
        self,
        document: object,
        *,
        origin: Literal["authored", "proposed", "photo_derived"] = "authored",
        based_on: tuple[str, int] | None = None,
        label: str | None = None,
    ) -> RecipeRecord:
        """Check a recipe against its published maker and store it, or refuse with every reason."""
        if origin == "photo_derived":
            raise PhotoDerivedRecipeInert(
                "a recipe may not be derived from a personal photograph before the personal "
                "model right exists"
            )
        if origin not in AUTHORABLE_ORIGINS:
            raise InvalidRecipe([f"origin is one of {', '.join(AUTHORABLE_ORIGINS)}"])
        try:
            raw = canonical_bytes(document)
            recipe = read_object(raw, "recipe")
        except (CanonicalisationError, MaterialObjectError) as error:
            raise InvalidRecipe([str(error)]) from error
        maker = recipe.get("maker") if isinstance(recipe, Mapping) else None
        identity: tuple[str, int] | None = None
        if (
            isinstance(maker, Mapping)
            and type(maker.get("id")) is str
            and type(maker.get("version")) is int
        ):
            identity = (maker["id"], maker["version"])
        pinned = None if identity is None else PUBLISHED_MAKER_MANIFESTS.get(identity)
        published = None if identity is None else self.catalog.makers.get(identity)
        if pinned is None or published is None or published.sha256 != pinned:
            raise InvalidRecipe(["recipe names a published maker id and version"])
        problems = list(recipe_problems(recipe, published.manifest))
        if based_on is not None:
            source = self.catalog.sets.get(based_on[0])
            if source is None or source.version != based_on[1]:
                problems.append("based_on names a published set and its pinned version")
            elif (source.maker.maker_id, source.maker.version) != identity:
                problems.append("a variant of a published set uses that set's maker")
        label_problem = _label_problem(label)
        if label_problem is not None:
            problems.append(label_problem)
        if problems:
            raise InvalidRecipe(problems)
        with _refusals():
            row = _retrying(
                lambda: self._insert_recipe(origin, published, raw, recipe, based_on, label)
            )
        return self.recipe(row["recipe_id"])

    def _insert_recipe(
        self,
        origin: str,
        published: Any,
        raw: bytes,
        recipe: Any,
        based_on: tuple[str, int] | None,
        label: str | None,
    ) -> Mapping[str, Any]:
        row = self.connection.execute(
            "insert into material_recipe (workspace_id, origin, maker_id, maker_version, "
            "  maker_sha256, recipe_canonical, recipe_document, recipe_sha256, "
            "  based_on_set_id, based_on_version, label, created_by) "
            "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "returning recipe_id",
            (
                self.workspace_id,
                origin,
                published.maker_id,
                published.version,
                bytes.fromhex(published.sha256),
                raw,
                Jsonb(thaw(recipe)),
                hashlib.sha256(raw).digest(),
                None if based_on is None else based_on[0],
                None if based_on is None else based_on[1],
                label,
                self.actor,
            ),
        ).fetchone()
        assert row is not None
        return row

    def _recipe_row(self, recipe_id: uuid.UUID, *, lock: bool = False) -> Mapping[str, Any]:
        row = self.connection.execute(
            f"select {_RECIPE_COLUMNS}, "
            "  tombstone_blocks_material_recipe(r.workspace_id, r.recipe_id) as blocked "
            "from material_recipe r where r.workspace_id = %s and r.recipe_id = %s"
            + (" for update" if lock else ""),
            (self.workspace_id, recipe_id),
        ).fetchone()
        if row is None:
            raise UnknownMaterial(f"no recipe {recipe_id} in this workspace")
        if row["blocked"]:
            raise MaterialWithdrawn(f"recipe {recipe_id} was withdrawn or deleted")
        return row

    def recipe(self, recipe_id: uuid.UUID) -> RecipeRecord:
        return _recipe(self._recipe_row(recipe_id))

    def recipes(self) -> list[RecipeRecord]:
        """Every readable recipe, oldest first."""
        rows = self.connection.execute(
            f"select {_RECIPE_COLUMNS} from material_recipe r "
            "where r.workspace_id = %s "
            "  and not tombstone_blocks_material_recipe(r.workspace_id, r.recipe_id) "
            "order by r.created_at, r.recipe_id",
            (self.workspace_id,),
        ).fetchall()
        return [_recipe(row) for row in rows]

    def withdraw_recipe(self, recipe_id: uuid.UUID) -> None:
        """Hide a recipe and its bake now. The row is kept; the bytes wait for the workspace."""

        def withdraw() -> None:
            with self.connection.transaction():
                self._lifecycle_lock()
                self._recipe_row(recipe_id, lock=True)
                self.connection.execute(
                    "insert into material_recipe_withdrawal (workspace_id, recipe_id, "
                    "  withdrawn_by) values (%s, %s, %s) "
                    "on conflict (workspace_id, recipe_id) do nothing",
                    (self.workspace_id, recipe_id, self.actor),
                )

        with _refusals():
            _retrying(withdraw)

    def _lifecycle_lock(self) -> None:
        self.connection.execute("select material_bake_lifecycle_lock(%s)", (self.workspace_id,))

    # -- bakes --------------------------------------------------------------------------

    def _bake_row(self, recipe_id: uuid.UUID, *, lock: bool = False) -> Mapping[str, Any] | None:
        return self.connection.execute(
            f"select {_BAKE_COLUMNS} from material_bake b "
            "where b.workspace_id = %s and b.recipe_id = %s" + (" for update" if lock else ""),
            (self.workspace_id, recipe_id),
        ).fetchone()

    def bake(self, recipe_id: uuid.UUID) -> BakeRecord | None:
        """The recipe's bake, or None when nobody has asked for one."""
        self._recipe_row(recipe_id)
        row = self._bake_row(recipe_id)
        return None if row is None else _bake(row)

    def _count_request(self, bake_id: uuid.UUID) -> None:
        self.connection.execute(
            "insert into material_bake_request (workspace_id, bake_id, requested_by) "
            "values (%s, %s, %s)",
            (self.workspace_id, bake_id, self.actor),
        )

    def request_bake(self, recipe_id: uuid.UUID) -> BakeRecord:
        """Queue the recipe's bake, unless it is already queued, running, or baked and present."""
        with _refusals():
            return _retrying(lambda: self._request_bake(recipe_id))

    def _request_bake(self, recipe_id: uuid.UUID) -> BakeRecord:
        with self.connection.transaction():
            self._lifecycle_lock()
            self._recipe_row(recipe_id, lock=True)
            row = self._bake_row(recipe_id, lock=True)
            if row is None:
                created = self.connection.execute(
                    "insert into material_bake (workspace_id, recipe_id, set_id, requested_by) "
                    "values (%s, %s, %s, %s) returning bake_id",
                    (self.workspace_id, recipe_id, workspace_set_id(recipe_id), self.actor),
                ).fetchone()
                assert created is not None
                self._count_request(created["bake_id"])
            elif row["state"] == "cancelled":
                raise MaterialWithdrawn("this recipe's bake was cancelled by a withdrawal")
            elif row["state"] == "failed" or (
                row["state"] == "baked" and not self._bytes_present(row)
            ):
                self.connection.execute(
                    "update material_bake set state = 'requested', attempts = 0, "
                    "  failure_class = null, failure_message = null "
                    "where workspace_id = %s and bake_id = %s",
                    (self.workspace_id, row["bake_id"]),
                )
                self._count_request(row["bake_id"])
            refreshed = self._bake_row(recipe_id)
        assert refreshed is not None
        return _bake(refreshed)

    def _bytes_present(self, row: Mapping[str, Any]) -> bool:
        if row["content_sha256"] is None or row["purged_at"] is not None:
            return False
        store = self.stores.for_workspace(self.workspace_id)
        return store.exists(BlobId(bytes(row["content_sha256"])))

    def read_bake(self, recipe_id: uuid.UUID) -> AuthorizedBake:
        """The container, hash-checked, released only if the bake is still current afterwards."""
        self._recipe_row(recipe_id)
        row = self._bake_row(recipe_id)
        if row is None or row["state"] != "baked" or row["content_sha256"] is None:
            raise BakeNotReady(f"recipe {recipe_id} has no finished bake")
        if row["purged_at"] is not None:
            raise MaterialWithdrawn(f"the bake of recipe {recipe_id} was erased")
        digest = bytes(row["content_sha256"])
        try:
            data = self.stores.for_workspace(self.workspace_id).get(BlobId(digest))
        except BlobNotFoundError as error:
            raise BakeBytesMissing(
                f"the bake of recipe {recipe_id} is recorded but its bytes are missing; "
                "request it again to re-bake it"
            ) from error
        if len(data) != row["byte_size"]:
            raise IntegrityError(f"the bake of recipe {recipe_id} is not the length recorded")
        self._final_check(recipe_id, row)
        return AuthorizedBake(data=data, content_sha256=digest.hex(), set_id=row["set_id"])

    def _final_check(self, recipe_id: uuid.UUID, seen: Mapping[str, Any]) -> None:
        """The 0041 final check: under the asset-read lock, the bake is exactly what was read."""
        if self.connection.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
            raise ValueError("a final bake authorization needs an idle connection")
        with self.connection.transaction():
            self.connection.execute("set transaction read only")
            self.connection.execute("select asset_read_lock()")
            # A separate statement, so READ COMMITTED sees whatever committed during the wait.
            current = self.connection.execute(
                "select b.content_sha256, b.state, b.purged_at, "
                "  tombstone_blocks_material_bake(b.workspace_id, b.bake_id) as blocked "
                "from material_bake b where b.workspace_id = %s and b.recipe_id = %s",
                (self.workspace_id, recipe_id),
            ).fetchone()
        if (
            current is None
            or current["blocked"]
            or current["purged_at"] is not None
            or current["state"] != "baked"
            or bytes(current["content_sha256"]) != bytes(seen["content_sha256"])
        ):
            raise MaterialWithdrawn(f"the bake of recipe {recipe_id} stopped being current")
