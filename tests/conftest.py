"""Generated test photographs, a vision model that counts its calls, and the model-client fakes.

Images are generated rather than committed. The repository carries no binary fixture, the
content of every test image is known exactly, and an orientation test can assert on a specific
pixel rather than on a hash somebody once recorded.

Nothing in this directory reaches the network or spends credits. The model client is driven
through ``model_fakes.FakeTransport``, which is the real client running against a scripted
transport rather than a mock of the client.
"""

from __future__ import annotations

import datetime as dt
import io
import struct
import urllib.parse
import uuid
import zlib
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from exulanica.corpus.photograph import TO_SENSOR_TRANSPOSE
from exulanica.db import DATABASE_URL_ENV
from exulanica.ingest.vision import VisionObservation, VisionResult
from exulanica.migrations import migrations
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.manifest import load_manifest
from PIL import Image
from PIL.TiffImagePlugin import IFDRational

from model_fakes import FakeTransport
from pg_harness import migrated_schema, open_scratch_connection

#: Explicit rather than environment-derived, so a developer's exported EXULANICA_BUDGET_USD cannot
#: change what a test asserts.
TEST_CEILING_USD = Decimal("5.00")
TEST_MAX_CALLS = 1000

#: A distinctive, asymmetric layout. The red block sits in the top-left of the UPRIGHT image,
#: which is what makes "was orientation applied" a pixel check rather than a metadata check.
RED = (220, 30, 30)
BLUE = (30, 60, 220)
WHITE = (255, 255, 255)


def upright_pixels(width: int = 160, height: int = 100) -> Image.Image:
    """A landscape image: red block top-left, blue bar along the bottom, white elsewhere."""
    image = Image.new("RGB", (width, height), WHITE)
    pixels = image.load()
    assert pixels is not None
    for y in range(height):
        for x in range(width):
            if x < width // 3 and y < height // 3:
                pixels[x, y] = RED
            elif y > height - height // 6:
                pixels[x, y] = BLUE
    return image


def bomb_png(width: int, height: int) -> bytes:
    """A PNG whose header declares an enormous frame and whose body is a few bytes.

    Built rather than committed, for the same reason every other test image here is: the
    repository carries no binary fixture and the exact declared size is what is being asserted.

    Here rather than in one of the two test modules that feed it to the pipeline, because both
    of them assert against ``MAX_PIXELS`` and a second copy is a second thing to keep in step
    with what Pillow reads out of an IHDR.
    """

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00" * 16))
        + chunk(b"IEND", b"")
    )


def photo_bytes(
    *,
    orientation: int = 1,
    when: str | None = "2026:08:27 10:00:00",
    offset: str | None = "+00:00",
    gps: tuple[float, float] | None = None,
    make: str | None = "Orimera",
    model: str | None = "TestCam 1",
    size: tuple[int, int] = (160, 100),
) -> bytes:
    """A JPEG whose stored pixels need ``orientation`` applied to look like ``upright_pixels``.

    The stored pixels are the inverse of the display transform, exactly as a camera writes
    them: sensor readout plus a tag saying how to display it.
    """
    image = upright_pixels(*size)
    # The display-to-sensor table lives in orimera.corpus.photograph and is imported rather
    # than repeated: four of the eight entries include a mirror, and a second table is a
    # second place for those four to drift.
    inverse = TO_SENSOR_TRANSPOSE.get(orientation)
    stored = image.transpose(inverse) if inverse is not None else image

    exif = Image.Exif()
    exif[0x0112] = orientation
    if make:
        exif[0x010F] = make
    if model:
        exif[0x0110] = model
    if when:
        exif.get_ifd(0x8769)[0x9003] = when
        if offset:
            exif.get_ifd(0x8769)[0x9011] = offset
    if gps is not None:
        latitude, longitude = gps
        gps_ifd = exif.get_ifd(0x8825)
        gps_ifd[1] = "N" if latitude >= 0 else "S"
        gps_ifd[2] = _dms(abs(latitude))
        gps_ifd[3] = "E" if longitude >= 0 else "W"
        gps_ifd[4] = _dms(abs(longitude))

    buffer = io.BytesIO()
    stored.save(buffer, format="JPEG", quality=95, exif=exif)
    return buffer.getvalue()


def _dms(value: float) -> tuple[IFDRational, IFDRational, IFDRational]:
    degrees = int(value)
    minutes_full = (value - degrees) * 60
    minutes = int(minutes_full)
    seconds = round((minutes_full - minutes) * 60 * 1000)
    return (
        IFDRational(degrees, 1),
        IFDRational(minutes, 1),
        IFDRational(seconds, 1000),
    )


def write_photo(directory: Path, name: str, **kwargs: Any) -> Path:
    path = directory / name
    path.write_bytes(photo_bytes(**kwargs))
    return path


def write_point_map(
    repository,
    store,
    blob_id,
    payload: bytes = b"not a real .opm",
    *,
    privacy_screening_id=None,
    read_source_sha256=None,
):
    """Put a point-map artifact of ``blob_id`` in the store and the spine, and return its row.

    The payload is deliberately NOT a valid container. The delivery route serves bytes and
    verifies them against the hash the store holds them under; it does not parse them, and a
    test that fed it a real ``.opm`` would be unable to tell those two things apart. The
    decoder's own contract is tested on the other side of the wire, in
    ``web/packages/atlas-react/test/opm.test.ts``.

    The identity key is the real one from :mod:`exulanica.ingest.stages`, so the row this writes is
    the row the depth stage would write. Writing it by hand rather than running the stage is what
    lets the API tests run with no depth model, a 1.3 GB checkpoint and torch.
    """
    from exulanica.ingest.privacy import (
        authorize_synthetic_capture,
        record_synthetic_exemption,
    )
    from exulanica.ingest.stages import artifact_id_for, idempotency_key, input_digest_of, stage

    if privacy_screening_id is None:
        capture = repository.live_capture_for_blob(blob_id)
        assert capture is not None
        authorization = authorize_synthetic_capture(
            repository,
            capture_id=capture.capture_id,
            actor=uuid.UUID("c936c289-0209-5ea5-b06a-c95535f6677b"),
            generator_manifest={
                "profile": "exulanica.test-point-map-source/v1",
                "notice": "SYNTHETIC TEST FIXTURE",
            },
            authorization_scope={"purpose": "automated test"},
            authorized_at=dt.datetime(2026, 9, 4, tzinfo=dt.UTC),
        )
        privacy_screening_id = record_synthetic_exemption(
            repository,
            authorization_id=authorization.authorization_id,
            screened_at=dt.datetime(2026, 9, 4, tzinfo=dt.UTC),
        ).screening_id

    spec = stage("depth")
    binding = {"model_id": "test/depth-model"}
    input_digest = input_digest_of([])
    key = idempotency_key(blob_id, spec, input_digest, binding=binding)
    stored = store.put_bytes(payload)
    repository.insert_artifact(
        artifact_id=artifact_id_for(key),
        kind=spec.output_kind,
        source_blob=blob_id,
        stage_key=spec.key,
        stage_version=spec.version,
        params_digest=spec.params_digest,
        input_digest=input_digest,
        idempotency_key=key,
        content_sha256=stored.blob_id.digest,
        storage_key=store.key_for(stored.blob_id),
        byte_size=stored.byte_size,
        produced_by_event=None,
        privacy_screening_id=privacy_screening_id,
        # A member whose photograph is masked must name the derivative its depth was read from;
        # migration 0040's trigger refuses the insert otherwise, and refuses a named mask on a
        # capture that needs none. Defaulting to None keeps every existing caller byte-identical.
        read_source_sha256=read_source_sha256,
    )
    return artifact_id_for(key), stored.blob_id


DEFAULT_PAYLOAD: dict[str, Any] = {
    "scene_description": "A red block above a blue bar, photographed head on.",
    "objects": [
        {
            "label": "red block",
            "salience": "primary",
            "confidence": "high",
            "box": {"x": 0.0, "y": 0.0, "w": 0.33, "h": 0.33},
        },
        {"label": "person", "salience": "background", "confidence": "low", "box": None},
    ],
    "legible_text": [
        {
            "text": "GULLFOSS 2 KM",
            "is_signage": True,
            "confidence": "medium",
            "box": {"x": 0.4, "y": 0.5, "w": 0.2, "h": 0.1},
        }
    ],
    "proposed_place": {
        "label": "Gullfoss",
        "basis": "signage",
        "supporting_evidence": "A sign reading GULLFOSS 2 KM.",
        "confidence": "medium",
    },
}


@dataclass
class CountingVisionModel:
    """A vision model that never touches the network and remembers every call.

    The idempotency test is only worth something if a second model call is impossible to miss,
    so the count lives here rather than being inferred from token totals.
    """

    payload: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_PAYLOAD))
    calls: int = 0
    images: list[bytes] = field(default_factory=list)
    model_id: str = "MiniMaxAI/MiniMax-M3"

    def observe(self, *, image_bytes: bytes, media_type: str) -> VisionResult:
        self.calls += 1
        self.images.append(image_bytes)
        payload = dict(self.payload)
        return VisionResult(
            observation=VisionObservation.model_validate(payload),
            payload=payload,
            model_id=self.model_id,
            model_ref={"provider": "test", "model_id": self.model_id, "endpoint": "test"},
            cost={"input_tokens": 772, "output_tokens": 210, "usd_estimate": "0.00048780"},
            attempts=1,
            tried=(self.model_id,),
            latency_ms=12,
        )


@pytest.fixture
def workspace_id() -> uuid.UUID:
    return uuid.uuid4()


# ---------------------------------------------------------------------------------------
# The spine. One migrated throwaway schema per session, wiped between tests.
#
# There is one data layer and it is PostgreSQL, so a test of the ingest path is a test against
# a real server or it is nothing. Applying the migration costs a few hundred milliseconds, so
# it happens once and the tables are truncated between tests instead. Truncation rather than a
# rolled-back transaction, because the pipeline commits on purpose: its whole object-store
# ordering rule is "write the bytes after the transaction commits", and a test that wrapped
# everything in one never-committed transaction would exercise the opposite of the code.
# ---------------------------------------------------------------------------------------

#: Seeded by the migration, not by a test, and every assertion write reads it. Truncating it
#: would empty the vocabulary and every later insert would be refused by a guard doing its job.
_PRESERVED_TABLES = frozenset(
    {
        "predicate",
        "schema_migrations",
        "stage_registry",
        "interaction_capability_registry",
        "world_object_behaviour_registry",
        "world_reviewed_asset",
        "world_art_profile_parameter",
        "world_art_profile_registry",
        "world_style_capability_registry",
        "world_style_module_registry",
        "world_style_module_capability",
        "world_art_profile_module",
    }
)

#: Emptied with DELETE rather than TRUNCATE, because migration 0013 puts a BEFORE TRUNCATE
#: trigger on both. That trigger is not decoration and this is not a workaround for it: measured
#: before it existed, `truncate purge_job cascade` succeeded and lost the record of what had not
#: yet been destroyed while every tombstone still said it had been requested. A test harness is
#: an administrative context and the owner still holds DELETE, which is the distinction the
#: trigger is drawing. The runtime and purge roles hold DELETE on nothing, and
#: `test_purge.py::test_no_runtime_role_can_delete_a_tombstone_or_its_queue` is what holds that.
#:
#: purge_job first: it carries the foreign key.
_APPEND_ONLY_TABLES = ("purge_job", "tombstone")


@pytest.fixture(scope="session")
def spine_schema():
    """The migrated throwaway schema, and the name it lives under."""
    with migrated_schema() as (psycopg, owner):
        scratch = owner.execute("select current_schema()").fetchone()[0]
        yield psycopg, scratch


@pytest.fixture(scope="session")
def _spine_tables(spine_schema):
    psycopg, scratch = spine_schema
    connection = open_scratch_connection(psycopg, scratch)
    rows = connection.execute(
        "select tablename from pg_tables where schemaname = %s", (scratch,)
    ).fetchall()
    connection.close()
    excluded = _PRESERVED_TABLES.union(_APPEND_ONLY_TABLES)
    names = sorted(row[0] for row in rows if row[0] not in excluded)
    return names


@pytest.fixture
def ingest_spine(spine_schema, _spine_tables, workspace_id):
    """A repository over the spine, on a clean schema, scoped to this test's workspace.

    Yields ``(repository, open_another)``. ``open_another()`` returns a repository on a
    genuinely new connection, which is what "reopen the database" now means: a fresh
    repository object over the same connection would prove nothing about what was committed.
    """
    from exulanica.ingest.repository import IngestRepository

    psycopg, scratch = spine_schema
    opened = []

    def open_another() -> IngestRepository:
        connection = open_scratch_connection(psycopg, scratch)
        opened.append(connection)
        return IngestRepository(connection, workspace_id)

    primary = open_another()
    primary.connection.execute(
        "truncate table " + ", ".join(f'"{name}"' for name in _spine_tables) + " cascade"
    )
    for name in _APPEND_ONLY_TABLES:
        primary.connection.execute(f'delete from "{name}"')
    try:
        yield primary, open_another
    finally:
        for connection in opened:
            connection.close()


@pytest.fixture
def repository(ingest_spine):
    """Just the repository, for the tests that never reopen."""
    return ingest_spine[0]


@pytest.fixture
def cli_database(spine_schema, _spine_tables, monkeypatch):
    """Point the command line at the spine schema, through the environment it reads itself.

    The CLI is the one caller that opens its own connections: ``_repository`` calls
    ``Database.from_env()``, which resolves ``EXULANICA_DATABASE_URL`` and connects several times
    over a single command. So the throwaway schema goes on the ``search_path`` inside the URL
    rather than being set with a statement afterwards, because there is no connection object to
    hand it a statement on.

    Two things then have to be arranged before the CLI can run against a schema the harness
    migrated, and neither is guesswork; both were observed:

    *   **``schema_migrations`` is empty even though the schema is fully migrated.** The table
        is created by migration 0001, but the rows that say a version was applied are written
        by :func:`exulanica.db.apply_pending`, and the harness applies the files directly. The
        CLI would therefore find nothing applied, try 0001 again, and fail on ``type
        "assertion_kind" already exists``. Recording what the harness applied makes the
        bookkeeping agree with the schema that is actually there, which is also the only
        honest description of it.
    *   **Workspace scoping alone does not isolate two CLI tests.** ``artifact_id`` is
        ``uuid5`` over the idempotency key, and that key is a hash of the source bytes, the
        stage and its parameters, with no workspace in it. Two tests that ingest byte-identical
        photographs therefore compute the same primary key under different workspaces, and the
        second insert dies on ``artifact_pkey`` rather than being absorbed by ``on conflict
        (workspace_id, idempotency_key)``. Row-level security does not help here: a unique
        index is enforced over rows the policy hides. So the tables are wiped between tests
        exactly as :func:`ingest_spine` wipes them, and a fresh workspace per test is a convenience
        rather than the isolation mechanism.
    """
    psycopg, scratch = spine_schema
    from exulanica.env import env_get

    base = env_get("TEST_DATABASE_URL")
    assert base is not None
    options = urllib.parse.quote(f"-csearch_path={scratch},public", safe="")
    monkeypatch.setenv(DATABASE_URL_ENV, f"{base}{'&' if '?' in base else '?'}options={options}")

    connection = open_scratch_connection(psycopg, scratch)
    try:
        connection.execute(
            "truncate table " + ", ".join(f'"{name}"' for name in _spine_tables) + " cascade"
        )
        for name in _APPEND_ONLY_TABLES:
            connection.execute(f'delete from "{name}"')
        for migration in migrations():
            connection.execute(
                "insert into schema_migrations (version, checksum) values (%s, %s) "
                "on conflict (version) do nothing",
                (migration.version, migration.checksum),
            )
    finally:
        connection.close()


@pytest.fixture
def photo_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "photos"
    directory.mkdir()
    return directory


def iso(hour: int, minute: int = 0, day: int = 27) -> str:
    return dt.datetime(2026, 8, day, hour, minute, tzinfo=dt.UTC).strftime("%Y:%m:%d %H:%M:%S")


# ---------------------------------------------------------------------------------------
# The model client. Fixtures only; the fakes themselves live in tests/model_fakes.py.
# ---------------------------------------------------------------------------------------


@pytest.fixture
def manifest():
    return load_manifest()


@pytest.fixture
def transport() -> FakeTransport:
    return FakeTransport()


@pytest.fixture
def guard() -> BudgetGuard:
    return BudgetGuard(ceiling_usd=TEST_CEILING_USD, max_calls=TEST_MAX_CALLS)


@pytest.fixture
def client(manifest, transport) -> ModelClient:
    """The real client over a scripted transport, with an explicit budget and no cache.

    ``api_key`` is passed so the fixture never reads the developer's ``.env``. Retries are off,
    which is the library default: a test that wants them says so.
    """
    return ModelClient(
        api_key="test-key-not-real",
        manifest=manifest,
        transport=transport,
        budget=BudgetGuard(ceiling_usd=TEST_CEILING_USD, max_calls=TEST_MAX_CALLS),
    )


#: A test that requests any of these cannot run without a server. Collection marks it
#: ``postgres`` on that basis rather than trusting a module-level marker, because a module-level
#: marker also catches the tests in the same file that need no database at all, and because a
#: marker somebody forgot is a test that quietly disappears from the count below. Files with
#: their own migrated-schema fixtures declare the marker themselves.
DATABASE_FIXTURES = frozenset({"spine_schema", "ingest_spine", "repository", "cli_database"})


def pytest_collection_modifyitems(config, items):
    """Mark every test that reaches a real database, by what it asks for rather than by where
    it lives."""
    for item in items:
        if DATABASE_FIXTURES & set(getattr(item, "fixturenames", ())):
            item.add_marker(pytest.mark.postgres)


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Say loudly, and accurately, which guarantees this run did not check.

    A green summary that omits them is the exact failure this codebase already shipped once: a
    test that passes without exercising its case. Silence here would be the same mistake at the
    level of the suite.

    The count comes from the ``postgres`` marker. It used to come from a substring search over
    the skip location and the node id, which reported 19 skips out of 77 real ones: a skip
    raised inside a session-scoped fixture is attributed to the requesting test's own file, and
    most of those file names contain neither "pg_harness" nor "postgres". An undercount here is
    the same class of problem as the silence it replaced.
    """

    from exulanica.env import env_get

    if env_get("TEST_DATABASE_URL"):
        return
    skipped = [
        report
        for report in terminalreporter.stats.get("skipped", [])
        if "postgres" in getattr(report, "keywords", {})
    ]
    if not skipped:
        return
    files = sorted({report.nodeid.split("::")[0] for report in skipped})
    terminalreporter.write_sep("=", "UNVERIFIED INVARIANT", red=True, bold=True)
    terminalreporter.write_line(
        f"{len(skipped)} PostgreSQL tests were skipped, across {len(files)} files. They are the "
        "only executable proof of the guarantees the database carries: that a model cannot write "
        "a name into canonical state, that one workspace cannot read another's rows, and that a "
        "tombstoned address refuses the write."
    )
    for name in files:
        terminalreporter.write_line(f"  {name}")
    terminalreporter.write_line(
        "Run them with:  "
        "EXULANICA_TEST_DATABASE_URL=postgresql://localhost:5433/exulanica_spine_test uv run pytest"
    )


def ingest_observed(pipeline, repository, path, *, batch_id=None):
    """Ingest one photograph with an authorization that permits observing it.

    The vision stage sends a photograph to a hosted model, so from 2026-09-06 it requires an
    eligible privacy screening for those exact bytes, the same receipt the depth stage has always
    required. Without one it reports itself unavailable and nothing is sent.

    Every fixture in this suite works on the synthetic corpus, and ``record_synthetic_exemption``
    is the mechanism this codebase already has for exactly that: it exempts bytes whose durable
    authorization is itself synthetic, and the database enforces that it cannot be applied to
    benchmark or personal media. So this helper is not a way around the gate, it is the gate being
    satisfied honestly by media that has nobody in it.

    Two calls rather than ``ingest_file``, because a screening is keyed to a capture that does not
    exist until intake has committed. That ordering is the point: somebody authorizes these exact
    bytes, and only then is anything sent anywhere.
    """
    from exulanica.ingest.privacy import authorize_synthetic_capture, record_synthetic_exemption

    intake = pipeline.ingest_intake(path.read_bytes(), filename=path.name, batch_id=batch_id)
    assert intake.capture_id is not None, intake.error
    authorization = authorize_synthetic_capture(
        repository,
        capture_id=intake.capture_id,
        actor=uuid.UUID("a244f9d0-9bd9-5f55-a133-2712cd05d720"),
        generator_manifest={
            "profile": "exulanica.synthetic-test-corpus/v1",
            "notice": "SYNTHETIC TEST FIXTURE",
        },
        authorization_scope={"purpose": "test suite"},
    )
    screening = record_synthetic_exemption(
        repository, authorization_id=authorization.authorization_id
    )
    return pipeline.ingest_derivatives(
        intake.capture_id, batch_id=batch_id, privacy_screening_id=screening.screening_id
    )
