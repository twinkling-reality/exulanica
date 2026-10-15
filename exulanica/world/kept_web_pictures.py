"""The pictures a workspace keeps from picture searches (migration 0215): a stranger's photographs,
each kept for one person's own private world, never a capture.

A picture search passes a person the pictures it found (:mod:`exulanica.references.held_pictures`).
When they pick one and say they may use it, the picture is fetched once and kept here: decoded
within the photograph pipeline's pixel budget, one frame only, turned upright and written again
in its own format with no metadata at all, so nothing its camera, editor or website wrote travels
with it. Only JPEG, PNG and WebP are kept. The kept bytes are held by digest in the workspace's own
web pictures namespace of the content store
(:data:`exulanica.store.namespaces.WEB_PICTURE_NAMESPACE`), recorded in its inventory
(``web_picture_object``) before they are written, and named by one record (``web_picture``): the
digests of what was fetched and what was kept, the picture's address and website, its licence where
its source states one, the person's answer, who answered, and the picture search it came from.

Nothing that reads a person's own photographs reads these: they are not captures, so no library,
admission, scene, world input, export or model hand-over sees one. No hosted provider model ever
receives one (docs/reference-notes-contract.md).

Keeping takes the bytes' own lock, which the purger also takes, then records the object and
commits, writes the bytes, and writes the record in a transaction that asks the workspace's lock and
whether the workspace is being erased again, so a record never names bytes the store lacks and the
store never holds bytes its inventory lacks: the order
:class:`exulanica.world.thing_store.ThingStore` keeps a look's container in.

:func:`keep_held_picture` is how a person keeps a picture a search found: it fetches the picture
once from its address through the guarded fetcher (:mod:`exulanica.references.picture_fetch`), then
keeps it, recording the address and website the person picked, whatever redirects the fetch
followed.

Erasing writes a web picture tombstone and one row naming the picture, its bytes and that tombstone
in one transaction; the row's trigger deletes the record and enqueues the bytes for
``exulanica-purge`` (migration 0215). Asked by the person who kept the picture, or by an owner of
the workspace.
"""

from __future__ import annotations

import hashlib
import io
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final

import psycopg
from PIL import Image, ImageOps
from psycopg.rows import dict_row

from exulanica.corpus.decode import UNREADABLE, decoding, probe
from exulanica.evidence.blob import BlobId
from exulanica.references import picture_fetch
from exulanica.references.adapters.base import WebPicture
from exulanica.store.base import ContentAddressedStore
from exulanica.store.namespaces import web_picture_lock_key
from exulanica.world.workspace_lock import lock_workspace

__all__ = [
    "ANSWERS",
    "KEPT_FORMATS",
    "MAX_PICTURE_BYTES",
    "MAX_PICTURE_SIDE",
    "REFUSALS",
    "CleanPicture",
    "KeptPicture",
    "KeptPictureRefused",
    "KeptWebPictures",
    "clean_picture",
    "keep_held_picture",
]

#: The most bytes a picture may have, fetched or kept.
MAX_PICTURE_BYTES: Final = 10 * 1024 * 1024
#: The longest side a kept picture may have, in pixels; its record holds no larger.
MAX_PICTURE_SIDE: Final = 16384
#: The formats a picture is kept in, by Pillow's name, with the media type its record states.
KEPT_FORMATS: Final = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
#: What a person answered when asked whether they may use the picture for their own world.
ANSWERS: Final = ("made_or_permitted", "licence_allows", "private_world_only")
_ERASURE_REASON: Final = "web_picture_erased"

#: Why a picture is not kept or not erased, by code.
REFUSALS: Final = {
    "picture_not_an_image": "these bytes are not a picture this product reads",
    "picture_format_not_kept": "only JPEG, PNG and WebP pictures are kept",
    "picture_too_large": f"a picture is at most {MAX_PICTURE_BYTES} bytes",
    "picture_too_many_pixels": f"a picture's sides are at most {MAX_PICTURE_SIDE} pixels",
    "answer_unknown": f"the answer is one of {', '.join(ANSWERS)}",
    "licence_missing": "a picture whose licence allows it names that licence",
    "workspace_erased": "this workspace is being erased, and nothing more is kept in it",
    "keep_in_transaction": "a keep commits its own steps and is not run inside a transaction",
    "picture_unknown": "this workspace keeps no such picture",
    "picture_not_yours": "only the person who kept a picture, or an owner, erases it",
    "picture_changed": "the picture changed while it was being erased",
    "restore_sealed": "this installation is sealed for a restore",
}


class KeptPictureRefused(ValueError):
    """A picture not kept, read or erased, by code."""

    def __init__(self, code: str, detail: str | None = None) -> None:
        super().__init__(f"{code}: {detail or REFUSALS[code]}")
        self.code = code
        self.detail = detail or REFUSALS[code]


@dataclass(frozen=True, slots=True)
class CleanPicture:
    """A picture written again with no metadata: its bytes, media type, size and digests."""

    data: bytes = field(repr=False)
    media_type: str
    width: int
    height: int
    sha256: str
    fetched_sha256: str


@dataclass(frozen=True, slots=True)
class KeptPicture:
    """One kept picture's record, as read."""

    picture_id: uuid.UUID
    content_sha256: str
    fetched_sha256: str
    media_type: str
    byte_size: int
    width: int
    height: int
    address: str = field(repr=False)
    website: str
    licence: str | None
    answer: str
    answered_by: uuid.UUID
    reference_id: uuid.UUID | None
    kept_at: datetime


def clean_picture(data: bytes) -> CleanPicture:
    """``data`` decoded within the pixel budget, turned upright and written again in its own format
    with no metadata, or :class:`KeptPictureRefused`. Takes one of the process's decode turns."""
    if not data:
        raise KeptPictureRefused("picture_not_an_image")
    if len(data) > MAX_PICTURE_BYTES:
        raise KeptPictureRefused("picture_too_large")
    try:
        width, height = probe(data)
        with Image.open(io.BytesIO(data)) as opened:
            media_type = KEPT_FORMATS.get(opened.format or "")
            if media_type is None:
                raise KeptPictureRefused("picture_format_not_kept")
            if max(width, height) > MAX_PICTURE_SIDE:
                raise KeptPictureRefused("picture_too_many_pixels")
            with decoding():
                opened.load()
                upright = ImageOps.exif_transpose(opened)
                written = io.BytesIO()
                _write(upright, opened.format or "", written)
    except KeptPictureRefused:
        raise
    except Image.DecompressionBombError as exc:
        raise KeptPictureRefused("picture_too_many_pixels") from exc
    except UNREADABLE as exc:
        raise KeptPictureRefused("picture_not_an_image") from exc
    kept = written.getvalue()
    if len(kept) > MAX_PICTURE_BYTES:
        raise KeptPictureRefused("picture_too_large")
    return CleanPicture(
        data=kept,
        media_type=media_type,
        width=upright.width,
        height=upright.height,
        sha256=hashlib.sha256(kept).hexdigest(),
        fetched_sha256=hashlib.sha256(data).hexdigest(),
    )


def _write(image: Image.Image, format_name: str, into: io.BytesIO) -> None:
    """``image`` in ``format_name`` with nothing but its pixels: every entry of its ``info`` but a
    palette's transparency is dropped first (a PNG writes the ICC profile its info holds unless
    told otherwise), and no EXIF, XMP, ICC profile, text chunk or comment is passed."""
    image.info = {key: value for key, value in image.info.items() if key == "transparency"}
    if format_name == "JPEG":
        pixels = image if image.mode in ("L", "RGB", "CMYK") else image.convert("RGB")
        pixels.save(into, format="JPEG", quality=92)
    elif format_name == "PNG":
        image.save(into, format="PNG")
    else:
        image.save(into, format="WEBP", quality=92)


class KeptWebPictures:
    """One workspace's kept web pictures, on a connection whose session is that workspace's.

    ``store`` is the workspace's own web pictures namespace (``ContentStores.web_pictures``); a
    reader that only lists records may pass None."""

    def __init__(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        store: ContentAddressedStore | None,
    ) -> None:
        self.connection = connection
        self.workspace_id = workspace_id
        self.store = store

    # -- keeping ---------------------------------------------------------------------------------

    def keep(
        self,
        picture: CleanPicture,
        *,
        address: str,
        website: str,
        answer: str,
        answered_by: uuid.UUID,
        reference_id: uuid.UUID | None,
        licence: str | None = None,
    ) -> KeptPicture:
        """Keep ``picture``: record its object, write its bytes, then its record. Refused by name:
        ``answer_unknown``, ``licence_missing``, ``workspace_erased`` and ``keep_in_transaction``,
        each before anything is recorded but the last two, which may leave the object recorded and
        unreferenced until the workspace is erased, as a look's container is."""
        if answer not in ANSWERS:
            raise KeptPictureRefused("answer_unknown")
        if answer == "licence_allows" and not licence:
            raise KeptPictureRefused("licence_missing")
        if self.store is None:
            raise RuntimeError("these pictures were opened to read records, never to keep one")
        if (
            not self.connection.autocommit
            or self.connection.info.transaction_status != psycopg.pq.TransactionStatus.IDLE
        ):
            raise KeptPictureRefused("keep_in_transaction")
        try:
            with self._holding(picture.sha256):
                with self.connection.transaction():
                    self._checked()
                    self.connection.execute(
                        "insert into web_picture_object (workspace_id, content_sha256, byte_size) "
                        "values (%s,%s,%s) on conflict (workspace_id, content_sha256) "
                        "where purged_at is null do nothing",
                        (self.workspace_id, picture.sha256, len(picture.data)),
                    )
                self.store.put_bytes(picture.data)
                with (
                    self.connection.transaction(),
                    self.connection.cursor(row_factory=dict_row) as cursor,
                ):
                    self._checked()
                    row = cursor.execute(
                        "insert into web_picture (workspace_id, content_sha256, fetched_sha256, "
                        "media_type, byte_size, width, height, address, website, licence, answer, "
                        "answered_by, reference_id) "
                        "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                        f"returning {_COLUMNS}",
                        (
                            self.workspace_id,
                            picture.sha256,
                            picture.fetched_sha256,
                            picture.media_type,
                            len(picture.data),
                            picture.width,
                            picture.height,
                            address,
                            website,
                            licence,
                            answer,
                            answered_by,
                            reference_id,
                        ),
                    ).fetchone()
        except psycopg.errors.IntegrityConstraintViolation as exc:
            if (exc.diag.message_primary or "").startswith("tombstoned: write refused"):
                raise KeptPictureRefused("workspace_erased") from exc
            raise
        assert row is not None
        return _kept(row)

    def _checked(self) -> None:
        """The workspace's lock, held to the transaction's end, and whether it is being erased."""
        lock_workspace(self.connection, self.workspace_id)
        with self.connection.cursor(row_factory=dict_row) as cursor:
            row = cursor.execute(
                "select exists (select 1 from tombstone where workspace_id=%s "
                "and scope='workspace' and effective_at <= clock_timestamp()) as erased",
                (self.workspace_id,),
            ).fetchone()
        if row is not None and row["erased"]:
            raise KeptPictureRefused("workspace_erased")

    @contextmanager
    def _holding(self, digest: str) -> Iterator[None]:
        """The bytes' session lock (``web_picture_lock_key``), which the purger takes before it
        destroys a picture's bytes, held from recording the object until the record commits."""
        key = web_picture_lock_key(self.workspace_id, digest)
        self.connection.execute("select pg_advisory_lock(hashtextextended(%s, 0))", (key,))
        try:
            yield
        finally:
            self.connection.execute("select pg_advisory_unlock(hashtextextended(%s, 0))", (key,))

    # -- reading ---------------------------------------------------------------------------------

    def list(self) -> list[KeptPicture]:
        """Every picture this workspace keeps, newest first."""
        with self.connection.cursor(row_factory=dict_row) as cursor:
            rows = cursor.execute(
                f"select {_COLUMNS} from web_picture where workspace_id=%s "
                "order by kept_at desc, picture_id desc",
                (self.workspace_id,),
            ).fetchall()
        return [_kept(row) for row in rows]

    def read(self, picture_id: uuid.UUID) -> KeptPicture | None:
        """One kept picture's record, or None."""
        with self.connection.cursor(row_factory=dict_row) as cursor:
            row = cursor.execute(
                f"select {_COLUMNS} from web_picture where workspace_id=%s and picture_id=%s",
                (self.workspace_id, picture_id),
            ).fetchone()
        return None if row is None else _kept(row)

    def read_bytes(self, picture_id: uuid.UUID) -> tuple[KeptPicture, bytes] | None:
        """One kept picture's record and its kept bytes, verified against their digest, or None."""
        kept = self.read(picture_id)
        if kept is None:
            return None
        if self.store is None:
            raise RuntimeError("these pictures were opened to read records, never their bytes")
        with self.store.open_verified(BlobId.from_hex(kept.content_sha256)) as opened:
            return kept, opened.read()

    # -- erasing ---------------------------------------------------------------------------------

    def erase(
        self, picture_id: uuid.UUID, *, erased_by: uuid.UUID, by_owner: bool = False
    ) -> uuid.UUID:
        """Erase a kept picture and answer the erasure's id: under the workspace's lock, a web
        picture tombstone, then one row naming the picture, its bytes and that tombstone, whose
        trigger deletes the record and enqueues the bytes' purge (migration 0215). Refused by
        name: ``picture_unknown``, ``picture_not_yours``, ``picture_changed`` and
        ``restore_sealed`` (migration 0107)."""
        try:
            with (
                self.connection.transaction(),
                self.connection.cursor(row_factory=dict_row) as cursor,
            ):
                lock_workspace(self.connection, self.workspace_id)
                held = cursor.execute(
                    "select answered_by, content_sha256 from web_picture "
                    "where workspace_id=%s and picture_id=%s",
                    (self.workspace_id, picture_id),
                ).fetchone()
                if held is None:
                    raise KeptPictureRefused("picture_unknown")
                if held["answered_by"] != erased_by and not by_owner:
                    raise KeptPictureRefused("picture_not_yours")
                tombstone = cursor.execute(
                    "insert into tombstone (workspace_id, scope, requested_by, reason) "
                    "values (%s, 'web_picture', %s, %s) returning tombstone_id",
                    (self.workspace_id, erased_by, _ERASURE_REASON),
                ).fetchone()
                assert tombstone is not None
                row = cursor.execute(
                    "insert into web_picture_erasure (workspace_id, picture_id, content_sha256, "
                    "tombstone_id, erased_by) values (%s,%s,%s,%s,%s) returning erasure_id",
                    (
                        self.workspace_id,
                        picture_id,
                        held["content_sha256"],
                        tombstone["tombstone_id"],
                        erased_by,
                    ),
                ).fetchone()
        except psycopg.errors.ObjectNotInPrerequisiteState as exc:
            raise KeptPictureRefused("restore_sealed") from exc
        except psycopg.IntegrityError as exc:
            raise KeptPictureRefused("picture_changed") from exc
        assert row is not None
        return row["erasure_id"]


def keep_held_picture(
    pictures: KeptWebPictures,
    picture: WebPicture,
    *,
    answer: str,
    answered_by: uuid.UUID,
    reference_id: uuid.UUID,
    licence: str | None = None,
    fetch: Callable[[str], picture_fetch.FetchedPicture] | None = None,
) -> KeptPicture:
    """Keep a picture a search found: fetched once from its address under the fetcher's rules,
    cleaned, then kept with the address and website the person picked. Refused by name: the
    answer's refusals before anything is fetched, then the fetcher's
    (:class:`~exulanica.references.picture_fetch.PictureFetchRefused`) and the keeper's."""
    if answer not in ANSWERS:
        raise KeptPictureRefused("answer_unknown")
    if answer == "licence_allows" and not licence:
        raise KeptPictureRefused("licence_missing")
    fetched = (fetch or picture_fetch.fetch_picture)(picture.address)
    return pictures.keep(
        clean_picture(fetched.data),
        address=picture.address,
        website=picture.website,
        answer=answer,
        answered_by=answered_by,
        reference_id=reference_id,
        licence=licence,
    )


_COLUMNS: Final = (
    "picture_id, content_sha256, fetched_sha256, media_type, byte_size, width, height, address, "
    "website, licence, answer, answered_by, reference_id, kept_at"
)


def _kept(row: dict) -> KeptPicture:
    return KeptPicture(
        picture_id=row["picture_id"],
        content_sha256=row["content_sha256"],
        fetched_sha256=row["fetched_sha256"],
        media_type=row["media_type"],
        byte_size=int(row["byte_size"]),
        width=int(row["width"]),
        height=int(row["height"]),
        address=row["address"],
        website=row["website"],
        licence=row["licence"],
        answer=row["answer"],
        answered_by=row["answered_by"],
        reference_id=row["reference_id"],
        kept_at=row["kept_at"],
    )
