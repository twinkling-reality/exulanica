"""A picture a person kept from a picture search: written again with no metadata, kept apart from
their own photographs, and erased whole (migration 0215).

What is shown, against PostgreSQL as the deployed writer (the runtime role) unless said:

*   a kept picture is decoded, turned upright and written again in its own format with no EXIF, ICC
    profile or text; its record holds the digests of what was fetched and what was kept; only
    JPEG, PNG and WebP are kept, one frame, within the pixel budget;
*   keeping records the object, then writes the bytes, then the record; the record is read back,
    and its bytes verified against their digest;
*   keeping one writes nothing a reader of the person's own photographs reads: no capture, blob,
    artifact or intake batch, and the judge seed refuses a workspace that keeps one;
*   an erasure writes a `web_picture` tombstone and its row, deletes the record and enqueues the
    bytes, which the purge destroys, completing the tombstone; bytes another kept picture names
    stay until that one is erased too; only the keeper or an owner erases;
*   a workspace's tombstone deletes every record and enqueues every object; nothing more is kept;
*   records go only through an erasure; another workspace reads none;
*   a capture tombstone may not destroy a kept picture's bytes, and a worker without the web
    pictures namespaces leaves its tombstone open;
*   an erasure a restore carries before its tombstone deletes the record, and the tombstone,
    replayed after it, enqueues the bytes.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import uuid
from pathlib import Path

import psycopg
import pytest
from exulanica.db.session import set_workspace
from exulanica.deletion import queue
from exulanica.deletion.worker import PurgeWorker
from exulanica.evidence.blob import BlobId
from exulanica.orchestration.judge_seed import SeedRefused, _refuse_held_things
from exulanica.store.namespaces import LocalWorkspaceStores
from exulanica.world.kept_web_pictures import (
    MAX_PICTURE_BYTES,
    KeptPictureRefused,
    KeptWebPictures,
    clean_picture,
)
from PIL import Image, PngImagePlugin
from psycopg.rows import dict_row

from test_purge import _APP_PASSWORD, _APP_ROLE, _PURGE_PASSWORD, _PURGE_ROLE
from test_purge import purged as purged

KEEPER = uuid.UUID("5a1e2b3c-4d5e-4f60-8a71-92b3c4d5e6a1")
ADDRESS = "https://pictures.example/yellow-duck.jpg"


def _jpeg_with_metadata(colour=(250, 220, 40)) -> bytes:
    """A JPEG carrying a camera, a place and an ICC profile, as a photograph from the web may."""
    image = Image.new("RGB", (40, 30), colour)
    exif = Image.Exif()
    exif[0x010F] = "Planted Camera Maker"  # Make
    exif[0x0112] = 6  # Orientation: turned a quarter
    exif[0x8825] = {1: "N", 2: (40.0, 44.0, 0.0)}  # GPS
    written = io.BytesIO()
    image.save(written, format="JPEG", exif=exif, icc_profile=b"planted-icc-profile" * 8)
    return written.getvalue()


def _png_with_text() -> bytes:
    image = Image.new("RGBA", (16, 12), (10, 120, 200, 255))
    text = PngImagePlugin.PngInfo()
    text.add_text("Author", "Planted Author Name")
    written = io.BytesIO()
    image.save(written, format="PNG", pnginfo=text, icc_profile=b"planted-icc-profile" * 8)
    return written.getvalue()


def _webp_with_exif() -> bytes:
    exif = Image.Exif()
    exif[0x010F] = "Planted Camera Maker"
    written = io.BytesIO()
    Image.new("RGB", (20, 20), (30, 30, 30)).save(written, format="WEBP", exif=exif)
    return written.getvalue()


# -- what is kept: pixels only -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("made", "media_type"),
    [
        (_jpeg_with_metadata, "image/jpeg"),
        (_png_with_text, "image/png"),
        (_webp_with_exif, "image/webp"),
    ],
)
def test_a_kept_picture_holds_its_pixels_and_no_metadata(made, media_type) -> None:
    fetched = made()
    clean = clean_picture(fetched)
    assert clean.media_type == media_type
    assert clean.fetched_sha256 != clean.sha256
    with Image.open(io.BytesIO(clean.data)) as kept:
        assert dict(kept.getexif()) == {}
        assert "icc_profile" not in kept.info and "exif" not in kept.info
        assert "Author" not in kept.info
    for planted in (b"Planted Camera Maker", b"planted-icc-profile", b"Planted Author Name"):
        assert planted not in clean.data


def test_a_picture_is_kept_upright() -> None:
    # The planted orientation turns the 40 by 30 frame a quarter: it is kept 30 by 40.
    clean = clean_picture(_jpeg_with_metadata())
    assert (clean.width, clean.height) == (30, 40)


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"", "picture_not_an_image"),
        (b"not a picture at all", "picture_not_an_image"),
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * 40, "picture_not_an_image"),
        (b"x" * (MAX_PICTURE_BYTES + 1), "picture_too_large"),
    ],
)
def test_bytes_that_are_not_a_kept_picture_are_refused_by_name(data, code) -> None:
    with pytest.raises(KeptPictureRefused) as refused:
        clean_picture(data)
    assert refused.value.code == code


def test_only_jpeg_png_and_webp_are_kept_and_one_frame_only() -> None:
    written = io.BytesIO()
    Image.new("RGB", (8, 8)).save(written, format="GIF")
    with pytest.raises(KeptPictureRefused) as refused:
        clean_picture(written.getvalue())
    assert refused.value.code == "picture_format_not_kept"
    frames = [Image.new("RGB", (8, 8), (n * 40, 0, 0)) for n in range(3)]
    animated = io.BytesIO()
    frames[0].save(animated, format="WEBP", save_all=True, append_images=frames[1:])
    with pytest.raises(KeptPictureRefused) as refused:
        clean_picture(animated.getvalue())
    assert refused.value.code == "picture_not_an_image"


def test_an_answer_outside_the_three_or_a_licence_answer_without_its_licence_is_refused() -> None:
    pictures = KeptWebPictures(None, uuid.uuid4(), None)  # type: ignore[arg-type]
    clean = clean_picture(_png_with_text())
    for answer, code in (("maybe", "answer_unknown"), ("licence_allows", "licence_missing")):
        with pytest.raises(KeptPictureRefused) as refused:
            pictures.keep(
                clean,
                address=ADDRESS,
                website="pictures.example",
                answer=answer,
                answered_by=KEEPER,
                reference_id=None,
            )
        assert refused.value.code == code


# -- keeping and erasing, on PostgreSQL ---------------------------------------------------------


class Pictures:
    """Pictures kept and erased in the ``purged`` fixture's workspace, and its purge."""

    def __init__(self, purged, tmp_path: Path) -> None:
        self.purged = purged
        self.workspace_id = purged.workspace_id
        self.stores = LocalWorkspaceStores(tmp_path / "web-pictures")
        self._sessions = contextlib.ExitStack()
        runtime = purged.database(role=_APP_ROLE, password=_APP_PASSWORD)
        self.connection = self._sessions.enter_context(runtime.session(self.workspace_id))
        self.kept = KeptWebPictures(
            self.connection, self.workspace_id, self.stores.for_workspace(self.workspace_id)
        )

    def close(self) -> None:
        self._sessions.close()

    def keep(self, data: bytes | None = None, *, by: uuid.UUID = KEEPER):
        return self.kept.keep(
            clean_picture(data or _jpeg_with_metadata()),
            address=ADDRESS,
            website="pictures.example",
            answer="private_world_only",
            answered_by=by,
            reference_id=uuid.uuid4(),
        )

    def rows(self, sql: str, *params):
        with self.connection.cursor(row_factory=dict_row) as cursor:
            return cursor.execute(sql, params).fetchall()

    def count(self, table: str) -> int:
        return self.purged.rows(f"select count(*) as n from {table}")[0]["n"]

    def in_namespace(self, digest: str) -> bool:
        return self.stores.for_workspace(self.workspace_id).exists(BlobId.from_hex(digest))

    def purge_worker(self, *, with_namespaces: bool = True) -> PurgeWorker:
        return PurgeWorker(
            self.purged.database(role=_PURGE_ROLE, password=_PURGE_PASSWORD),
            self.purged.store,
            frozenset({self.workspace_id}),
            name="test-web-picture-purge",
            web_picture_stores=self.stores if with_namespaces else None,
        )

    def jobs(self, tombstone: uuid.UUID) -> list[dict]:
        return self.purged.rows(
            "select target_kind, target_ref, state from purge_job where tombstone_id = %s "
            "order by target_ref",
            tombstone,
        )

    def anchor(self, erasure: uuid.UUID) -> uuid.UUID:
        [row] = self.rows(
            "select tombstone_id from web_picture_erasure where erasure_id = %s", erasure
        )
        return row["tombstone_id"]


@pytest.fixture
def pictures(purged, tmp_path):
    made = Pictures(purged, tmp_path)
    yield made
    made.close()


@pytest.mark.postgres
def test_a_kept_picture_is_read_back_and_its_bytes_verified(pictures) -> None:
    kept = pictures.keep()
    assert pictures.kept.list() == [kept]
    assert pictures.kept.read(kept.picture_id) == kept
    record, data = pictures.kept.read_bytes(kept.picture_id)
    assert record == kept and hashlib.sha256(data).hexdigest() == kept.content_sha256
    assert pictures.in_namespace(kept.content_sha256)
    [obj] = pictures.rows("select content_sha256, purged_at from web_picture_object")
    assert (obj["content_sha256"], obj["purged_at"]) == (kept.content_sha256, None)
    assert ADDRESS not in repr(kept)
    assert pictures.kept.read(uuid.uuid4()) is None


@pytest.mark.postgres
def test_a_kept_picture_is_nothing_a_reader_of_the_person_s_photographs_reads(pictures) -> None:
    tables = ("capture", "blob", "artifact", "intake_batch")
    before = {table: pictures.count(table) for table in tables}
    pictures.keep()
    pictures.keep(_png_with_text())
    assert {table: pictures.count(table) for table in tables} == before
    owner = pictures.purged.repository.connection
    set_workspace(owner, pictures.workspace_id)
    with pytest.raises(SeedRefused, match="keeps pictures from the web"):
        _refuse_held_things(owner, pictures.workspace_id)
    owner.rollback()


@pytest.mark.postgres
def test_an_erasure_deletes_the_record_and_the_purge_destroys_its_bytes(pictures) -> None:
    kept = pictures.keep()
    erasure = pictures.kept.erase(kept.picture_id, erased_by=KEEPER)
    assert pictures.kept.read(kept.picture_id) is None
    [row] = pictures.rows("select * from web_picture_erasure")
    assert set(row) == {
        "workspace_id",
        "erasure_id",
        "picture_id",
        "content_sha256",
        "tombstone_id",
        "erased_by",
        "erased_at",
    }
    assert (row["erasure_id"], row["picture_id"], row["erased_by"]) == (
        erasure,
        kept.picture_id,
        KEEPER,
    )
    tombstone = pictures.anchor(erasure)
    [stone] = pictures.purged.rows(
        "select scope::text as scope, requested_by, reason, capture_id from tombstone "
        "where tombstone_id = %s",
        tombstone,
    )
    assert (stone["scope"], stone["requested_by"], stone["capture_id"]) == (
        "web_picture",
        KEEPER,
        None,
    )
    assert pictures.jobs(tombstone) == [
        {"target_kind": "web_picture", "target_ref": kept.content_sha256, "state": "queued"}
    ]
    assert not queue.is_purge_complete(pictures.connection, tombstone)
    outcome = pictures.purge_worker().drain()
    assert outcome.failed == 0 and outcome.blocked is None, outcome
    assert not pictures.in_namespace(kept.content_sha256)
    [obj] = pictures.rows("select purged_at from web_picture_object")
    assert obj["purged_at"] is not None
    assert queue.is_purge_complete(pictures.connection, tombstone)
    with pytest.raises(KeptPictureRefused) as refused:
        pictures.kept.erase(kept.picture_id, erased_by=KEEPER)
    assert refused.value.code == "picture_unknown"


@pytest.mark.postgres
def test_bytes_two_kept_pictures_name_stay_until_both_are_erased(pictures) -> None:
    first, second = pictures.keep(), pictures.keep()
    assert first.content_sha256 == second.content_sha256
    one = pictures.anchor(pictures.kept.erase(first.picture_id, erased_by=KEEPER))
    assert pictures.jobs(one) == []
    pictures.purge_worker().drain()
    assert pictures.in_namespace(second.content_sha256)
    two = pictures.anchor(pictures.kept.erase(second.picture_id, erased_by=KEEPER))
    assert [job["target_ref"] for job in pictures.jobs(two)] == [second.content_sha256]
    pictures.purge_worker().drain()
    assert not pictures.in_namespace(second.content_sha256)


@pytest.mark.postgres
def test_only_the_keeper_or_an_owner_erases_and_nothing_is_written_otherwise(pictures) -> None:
    kept = pictures.keep()
    with pytest.raises(KeptPictureRefused) as refused:
        pictures.kept.erase(kept.picture_id, erased_by=uuid.uuid4())
    assert refused.value.code == "picture_not_yours"
    assert pictures.rows("select 1 from web_picture_erasure") == []
    assert pictures.purged.rows("select 1 from tombstone where scope::text = 'web_picture'") == []
    pictures.kept.erase(kept.picture_id, erased_by=uuid.uuid4(), by_owner=True)
    assert pictures.kept.list() == []


@pytest.mark.postgres
def test_a_workspace_tombstone_erases_every_kept_picture_and_nothing_more_is_kept(pictures) -> None:
    first, second = pictures.keep(), pictures.keep(_png_with_text())
    tombstone = pictures.purged.repository.insert_tombstone(
        scope="workspace", requested_by=uuid.uuid4(), reason="the person left"
    )
    pictures.purged.repository.connection.commit()
    assert pictures.kept.list() == []
    assert sorted(
        job["target_ref"] for job in pictures.jobs(tombstone) if job["target_kind"] == "web_picture"
    ) == sorted([first.content_sha256, second.content_sha256])
    pictures.purge_worker().drain()
    assert not pictures.in_namespace(first.content_sha256)
    assert not pictures.in_namespace(second.content_sha256)
    with pytest.raises(KeptPictureRefused) as refused:
        pictures.keep(_webp_with_exif())
    assert refused.value.code == "workspace_erased"


@pytest.mark.postgres
def test_records_go_only_through_an_erasure_and_another_workspace_reads_none(pictures) -> None:
    pictures.keep()
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        pictures.connection.execute("delete from web_picture")
    owner = pictures.purged.repository.connection
    set_workspace(owner, pictures.workspace_id)
    owner.commit()
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="append-only"):
        owner.execute("delete from web_picture")
    owner.rollback()
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="append-only"):
        owner.execute("update web_picture set website = 'elsewhere.example'")
    owner.rollback()
    runtime = pictures.purged.database(role=_APP_ROLE, password=_APP_PASSWORD)
    with runtime.session(uuid.uuid4()) as elsewhere:
        for table in ("web_picture", "web_picture_object", "web_picture_erasure"):
            assert elsewhere.execute(f"select count(*) as n from {table}").fetchone()["n"] == 0


@pytest.mark.postgres
def test_a_capture_tombstone_may_not_destroy_a_kept_picture(pictures) -> None:
    kept = pictures.keep()
    capture_id = pictures.purged.rows("select capture_id from capture")[0]["capture_id"]
    tombstone = pictures.purged.tombstone_the_capture(capture_id)
    pictures.purged.repository.connection.commit()
    purge = pictures.purged.database(role=_PURGE_ROLE, password=_PURGE_PASSWORD)
    with purge.session(pictures.workspace_id) as connection:
        row = connection.execute(
            "select web_picture_purge_is_authorized(%s, %s, %s) as allowed",
            (pictures.workspace_id, tombstone, kept.content_sha256),
        ).fetchone()
    assert row["allowed"] is False
    assert [job for job in pictures.jobs(tombstone) if job["target_kind"] == "web_picture"] == []
    assert pictures.kept.read(kept.picture_id) == kept


@pytest.mark.postgres
def test_a_worker_without_the_web_pictures_namespaces_leaves_the_tombstone_open(pictures) -> None:
    kept = pictures.keep()
    tombstone = pictures.anchor(pictures.kept.erase(kept.picture_id, erased_by=KEEPER))
    pictures.purge_worker(with_namespaces=False).drain()
    assert not queue.is_purge_complete(pictures.connection, tombstone)
    pictures.purge_worker().drain()
    assert queue.is_purge_complete(pictures.connection, tombstone)


@pytest.mark.postgres
def test_an_erasure_a_restore_carries_before_its_tombstone_still_purges(pictures) -> None:
    kept = pictures.keep()
    owner = pictures.purged.repository.connection
    set_workspace(owner, pictures.workspace_id)
    tombstone = uuid.uuid4()
    with owner.transaction():
        owner.execute(
            "insert into restore_control (checkpoint_id, checkpoint_sha256, state, restore_id) "
            "values (%s, %s, 'replaying', %s)",
            (uuid.uuid4(), "a" * 64, uuid.uuid4()),
        )
        # Carried first: the record is deleted, and with no tombstone held nothing is enqueued.
        owner.execute(
            "insert into web_picture_erasure (workspace_id, picture_id, content_sha256, "
            "tombstone_id, erased_by) values (%s, %s, %s, %s, %s)",
            (pictures.workspace_id, kept.picture_id, kept.content_sha256, tombstone, KEEPER),
        )
        assert owner.execute("select count(*) as n from web_picture").fetchone()["n"] == 0
        assert (
            owner.execute(
                "select count(*) as n from purge_job where tombstone_id = %s", (tombstone,)
            ).fetchone()["n"]
            == 0
        )
        # Replayed after it, the tombstone enqueues the bytes.
        owner.execute(
            "insert into tombstone (tombstone_id, workspace_id, scope, requested_by, reason) "
            "values (%s, %s, 'web_picture', %s, 'web_picture_erased')",
            (tombstone, pictures.workspace_id, KEEPER),
        )
        [job] = owner.execute(
            "select target_kind, target_ref from purge_job where tombstone_id = %s", (tombstone,)
        ).fetchall()
        assert (job["target_kind"], job["target_ref"]) == ("web_picture", kept.content_sha256)
        raise psycopg.Rollback()
