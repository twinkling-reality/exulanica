"""Baking a generated world's tiles, off the request that made the world.

A generated world queues one ``bake_generated_tile`` job per tile when it is made
(:func:`exulanica.world.generated_worlds.create_generated_authorities`). :class:`GeneratedTileBaker`
drains them one workspace at a time:

1. It **claims** a job as the runtime role, in the job's own workspace, and reads the world's
   records through its receipt (:func:`~exulanica.world.generated_worlds.town_records`), the one
   interface a generated world's records are read by, and the tile documents they make.
2. It **bakes** the tile with the tessellator's Node build (``web/packages/loom-tess``) twice, in
   a child process each, under a wall-clock timeout, as the offline bake does. The child is given
   only the environment :func:`child_environment` allows, so no database URL, credential or key
   this worker holds reaches Node or a web dependency.
3. It **publishes** each bake through the owner connection, the only role migration 0072 lets
   write a baked tile, and nothing else: the first answer is ``stored`` (or ``identical`` when the
   same tile was baked for another world), and the second must be ``identical``. A publish the
   database refuses for the moment (SQLSTATE 40001 from migration 0041's guard while a reader holds
   the asset read lock, or a dropped connection) is tried again after a short jittered wait, and a
   publish still refused goes back to the queue with a later ``run_after``, bounded by
   :data:`MAXIMUM_CLAIMS` as the derivative queue bounds its own retries: a lock race never fails
   a tile for good.
4. It marks the job done, or failed with the reason, in the job's workspace as the runtime role.
   A tile is drawn only once its job is done, both bakes agreed and stored
   (:func:`~exulanica.world.generated_worlds.generated_tiles`).

A baked tile is keyed by the digest over its inputs, so a tile two worlds share is baked and stored
once. A tile whose second bake differs is marked by the database and is never served.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import subprocess
import tempfile
import time
import uuid
from collections.abc import Callable, Iterable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from exulanica.grammar.grammars.city.tile import tile_inputs_digest
from exulanica.grammar.records import record_payload
from exulanica.ingest.stages import STAGES, baked_tile_id
from exulanica.store.base import ContentAddressedStore
from exulanica.world.baked_tiles import BakedTileRepository
from exulanica.world.composers import composer_module
from exulanica.world.generated_worlds import BAKE_JOB_KIND, town_records

__all__ = [
    "BAKE_TIMEOUT_SECONDS",
    "MAXIMUM_CLAIMS",
    "PUBLISH_RETRY_DELAYS",
    "REQUEUE_SECONDS",
    "BakeOutcome",
    "GeneratedTileBaker",
    "PublishRefused",
    "abandon_stranded",
    "child_environment",
    "claim_bake",
]

#: How long one tessellator run may take before it is stopped. One bake of the small town's tile
#: took 13.3 s on the development machine under load; a tile that takes twenty times that is not
#: making progress, and the job is failed with the reason rather than left running.
BAKE_TIMEOUT_SECONDS: Final = 300.0
#: How long a claim holds a job before another worker may take it: two bakes and their writes.
LEASE_SECONDS: Final = 2 * BAKE_TIMEOUT_SECONDS + 60.0
#: The most times a job is claimed before it is left failed: a tile that failed three bakes will
#: not bake on a fourth without a change.
MAXIMUM_CLAIMS: Final = 3
#: The waits, in seconds, before each further try of a publish the database refused for the
#: moment, each stretched by up to as much again at random so workers do not retry in step. A
#: final read check holds the asset read lock for one read; about three seconds of tries outlast
#: it, and a publish still refused goes back to the queue rather than holding its claim.
PUBLISH_RETRY_DELAYS: Final = (0.05, 0.1, 0.2, 0.4, 0.8, 1.6)
#: How long a job whose publish was still refused waits before its next claim, times the claims it
#: has had: a reader that held the lock through every try is given longer each time.
REQUEUE_SECONDS: Final = 30.0
#: What a publish may meet and be tried again for. SQLSTATE 40001 (``SerializationFailure``, an
#: ``OperationalError``) is migration 0041's refusal while a reader holds the asset read lock; the
#: rest of ``OperationalError`` is a connection that dropped. The write is one function call, so a
#: refused try wrote nothing and the next is the same write (:meth:`BakedTileRepository.record`).
TRANSIENT_PUBLISH_REFUSALS: Final = (psycopg.OperationalError,)
#: The names of this process's environment a tessellator child is given: where its programs are,
#: its home and temporary directory, its locale and Node's own settings. The list allows rather
#: than refuses, so no database URL, credential or key reaches Node or a web dependency, and a
#: secret added to the worker's environment later needs no entry here to stay out.
CHILD_ENVIRONMENT: Final = frozenset(
    {"PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE", "NODE_OPTIONS", "NODE_ENV"}
)


class PublishRefused(Exception):
    """A publish the database kept refusing for the moment through every try."""


def child_environment(environ: Mapping[str, str]) -> dict[str, str]:
    """The environment a tessellator child is given: only the names :data:`CHILD_ENVIRONMENT`
    allows, from ``environ``."""
    return {name: value for name, value in environ.items() if name in CHILD_ENVIRONMENT}


def _pause(seconds: float) -> None:
    """Wait before trying a refused publish again; a test replaces it to act at that moment."""
    time.sleep(seconds)


@dataclass(frozen=True, slots=True)
class BakeOutcome:
    job_id: uuid.UUID
    world_id: str
    tile: tuple[int, int]
    #: ``baked`` with the two answers the store gave, ``failed`` with the reason, or
    #: ``requeued`` when a publish was refused for the moment through every try.
    status: str
    detail: str
    baked_tile_id: uuid.UUID | None = None


def claim_bake(
    connection: psycopg.Connection, workspace_id: uuid.UUID, *, worker: str
) -> Mapping[str, Any] | None:
    """Take the next queued bake of this workspace, or None when there is none."""
    with connection.cursor(row_factory=dict_row) as cursor:
        return cursor.execute(
            "update job set state='running', claimed_by=%s, claimed_at=now(), "
            "attempts=attempts+1, claim_token=gen_random_uuid(), "
            "lease_expires_at=now()+make_interval(secs => %s) "
            "where job_id=(select job_id from job where workspace_id=%s and kind=%s "
            "and ((state='queued' and run_after<=now()) "
            "or (state='running' and lease_expires_at<now() and attempts<%s)) "
            "order by priority, job_id for update skip locked limit 1) "
            "returning job_id, payload, claim_token, attempts",
            (worker, LEASE_SECONDS, workspace_id, BAKE_JOB_KIND, MAXIMUM_CLAIMS),
        ).fetchone()


def abandon_stranded(
    connection: psycopg.Connection, workspace_id: uuid.UUID
) -> list[Mapping[str, Any]]:
    """End every bake of this workspace stranded :data:`MAXIMUM_CLAIMS` times, and return them.

    A bake is stranded when its lease expires with no worker saying anything, and
    :func:`claim_bake` passes over one that has used every claim it is allowed, so without this it
    would stay ``running`` and its tile would read as baking for ever. Failed, the tile reads as
    failed and the page says the world could not be drawn. ``failed`` rather than ``cancelled``,
    as the derivative queue's ``abandon`` says of its own jobs: the work did not happen and nobody
    withdrew it.
    """
    with connection.cursor(row_factory=dict_row) as cursor:
        return cursor.execute(
            "update job set state='failed', lease_expires_at=null, claim_token=null, "
            "completed_at=now(), failure_class='retry_exhausted_after_process_death', "
            "duration_ms=greatest(0, (extract(epoch from (now() - created_at)) * 1000)::bigint), "
            "last_error='claimed ' || attempts || ' times and stranded every time' "
            "where workspace_id=%s and kind=%s and state='running' and lease_expires_at<now() "
            "and attempts>=%s returning job_id, payload, last_error",
            (workspace_id, BAKE_JOB_KIND, MAXIMUM_CLAIMS),
        ).fetchall()


def _finish(
    connection: psycopg.Connection,
    job_id: uuid.UUID,
    claim_token: uuid.UUID,
    *,
    failed: str | None,
    failure_class: str = "bake_failed",
) -> None:
    connection.execute(
        "update job set state=%s, last_error=%s, failure_class=%s, completed_at=now(), "
        "duration_ms=greatest(0, (extract(epoch from (now() - created_at)) * 1000)::bigint), "
        "lease_expires_at=null, claim_token=null "
        "where job_id=%s and claim_token=%s and state='running'",
        (
            "failed" if failed else "done",
            failed,
            failure_class if failed else None,
            job_id,
            claim_token,
        ),
    )


def _requeue(
    connection: psycopg.Connection, job: Mapping[str, Any], *, delay_seconds: float, error: str
) -> bool:
    """Release a held claim back to the queue after a publish refused for the moment, as the
    derivative queue's ``retry`` does. The claim it used still counts toward
    :data:`MAXIMUM_CLAIMS`."""
    row = connection.execute(
        "update job set state='queued', run_after=now()+make_interval(secs => %s), "
        "last_error=%s, failure_class='publish_refused', claimed_by=null, "
        "lease_expires_at=null, claim_token=null "
        "where job_id=%s and claim_token=%s and state='running' returning job_id",
        (delay_seconds, error, job["job_id"], job["claim_token"]),
    ).fetchone()
    return row is not None


class GeneratedTileBaker:
    """Drains ``bake_generated_tile`` jobs for the workspaces it is given."""

    def __init__(
        self,
        *,
        session: Callable[[uuid.UUID], AbstractContextManager[psycopg.Connection]],
        publisher: Callable[[], AbstractContextManager[psycopg.Connection]],
        store: ContentAddressedStore,
        web_directory: Path,
        worker: str,
    ) -> None:
        self._session = session
        self._publisher = publisher
        self._store = store
        self._cli = web_directory / "packages" / "loom-tess" / "src" / "node" / "cli.ts"
        self._tsx = web_directory / "node_modules" / ".bin" / "tsx"
        self._web = web_directory
        self._worker = worker
        for required in (self._cli, self._tsx):
            if not required.exists():
                raise FileNotFoundError(f"the tessellator needs {required}; install web/ first")

    def drain(self, workspaces: Iterable[uuid.UUID]) -> list[BakeOutcome]:
        """End each workspace's stranded bakes, then bake every claimable job, one at a time, and
        say what happened to each."""
        outcomes = []
        for workspace_id in sorted(workspaces):
            with self._session(workspace_id) as connection:
                for row in abandon_stranded(connection, workspace_id):
                    payload = row["payload"]
                    outcomes.append(
                        BakeOutcome(
                            row["job_id"],
                            str(payload["world_id"]),
                            (int(payload["tile"][0]), int(payload["tile"][1])),
                            "failed",
                            str(row["last_error"]),
                        )
                    )
            while True:
                outcome = self.bake_one(workspace_id)
                if outcome is None:
                    break
                outcomes.append(outcome)
        return outcomes

    def bake_one(self, workspace_id: uuid.UUID) -> BakeOutcome | None:
        with self._session(workspace_id) as connection:
            job = claim_bake(connection, workspace_id, worker=self._worker)
            if job is None:
                return None
            payload = job["payload"]
            world_id = str(payload["world_id"])
            tile = (int(payload["tile"][0]), int(payload["tile"][1]))
            try:
                generated = town_records(
                    connection, workspace_id, world_id, uuid.UUID(payload["snapshot_id"])
                )
                if generated.receipt_sha256 != payload["receipt_sha256"]:
                    raise ValueError("the job names another receipt than the world's snapshot")
                composer = generated.receipt["composer"]
                module = composer_module(composer["key"], composer["version"])
                documents = module.tile_documents(generated.receipt, generated.records)
                document = next(d for d in documents if (d.tile.tile_x, d.tile.tile_y) == tile)
                key, answers = self._bake_and_publish(document, module, generated.receipt)
            except PublishRefused as exc:
                # Refused for the moment through every try: a reader held the asset read lock or
                # the connection dropped. Back to the queue while claims remain; a job that used
                # every claim this way is failed with that reason, as the derivative queue's is.
                detail = str(exc)[:2000]
                if int(job["attempts"]) < MAXIMUM_CLAIMS and _requeue(
                    connection,
                    job,
                    delay_seconds=REQUEUE_SECONDS * int(job["attempts"]),
                    error=detail,
                ):
                    return BakeOutcome(job["job_id"], world_id, tile, "requeued", detail)
                _finish(
                    connection,
                    job["job_id"],
                    job["claim_token"],
                    failed=detail,
                    failure_class="retry_exhausted",
                )
                return BakeOutcome(job["job_id"], world_id, tile, "failed", detail)
            except Exception as exc:  # the job records every failure with its reason
                detail = f"{type(exc).__name__}: {exc}"[:2000]
                _finish(connection, job["job_id"], job["claim_token"], failed=detail)
                return BakeOutcome(job["job_id"], world_id, tile, "failed", detail)
            if answers[-1] != "identical":
                detail = f"the second bake answered {answers[-1]}, not identical"
                _finish(connection, job["job_id"], job["claim_token"], failed=detail)
                return BakeOutcome(job["job_id"], world_id, tile, "failed", detail, key)
            _finish(connection, job["job_id"], job["claim_token"], failed=None)
            return BakeOutcome(job["job_id"], world_id, tile, "baked", " then ".join(answers), key)

    def _bake(self, document: Path, container: Path) -> dict[str, Any]:
        result = subprocess.run(
            [str(self._tsx), str(self._cli), "bake", str(document), str(container)],
            capture_output=True,
            text=True,
            cwd=self._web,
            env=child_environment(os.environ),
            timeout=BAKE_TIMEOUT_SECONDS,
            check=False,
        )
        if result.returncode != 0:
            message = (result.stderr or result.stdout).strip() or "no output"
            raise RuntimeError(f"the tessellator refused {document.name}: {message[:1000]}")
        statement: dict[str, Any] = json.loads(result.stdout.strip().splitlines()[-1])
        return statement

    def _publish(self, fields: Mapping[str, Any]) -> str:
        """Record one bake through the owner connection, tried again while the database refuses it
        for the moment. Each try opens a publisher of its own, so a refused try leaves nothing
        behind, and the write is one function call, so the next try is the same write; a publish
        refused through every wait of :data:`PUBLISH_RETRY_DELAYS` is :class:`PublishRefused`."""
        tried = 0
        while True:
            try:
                with self._publisher() as owner:
                    return BakedTileRepository(connection=owner, store=self._store).record(**fields)
            except TRANSIENT_PUBLISH_REFUSALS as exc:
                if tried == len(PUBLISH_RETRY_DELAYS):
                    raise PublishRefused(
                        f"the database refused the publish {tried + 1} times: "
                        f"{type(exc).__name__}: {exc}"
                    ) from exc
                _pause(PUBLISH_RETRY_DELAYS[tried] * (1.0 + random.random()))
                tried += 1

    def _bake_and_publish(
        self, document: Any, module: Any, receipt: Mapping[str, Any]
    ) -> tuple[uuid.UUID, list[str]]:
        spec = STAGES["baked_tile"]
        tile = document.tile
        key = baked_tile_id(spec, tile)
        data = module.tile_document_bytes(document)
        answers = []
        with tempfile.TemporaryDirectory() as work:
            document_path = Path(work) / f"tile-{tile.tile_x}-{tile.tile_y}.json"
            document_path.write_bytes(data)
            for bake in ("first", "second"):
                container_path = Path(work) / f"tile-{tile.tile_x}-{tile.tile_y}.{bake}.owd"
                statement = self._bake(document_path, container_path)
                container = container_path.read_bytes()
                if hashlib.sha256(container).hexdigest() != statement["container_sha256"]:
                    raise RuntimeError("the bake's statement and its bytes disagree")
                fields = {
                    "baked_tile_id": key,
                    "stage_version": spec.version,
                    "stage_params_sha256": spec.params_digest,
                    "tile": {
                        "tile_inputs_digest": tile_inputs_digest(tile),
                        **record_payload(tile)["fields"],
                    },
                    "document": data,
                    "container": container,
                    "render_batch_sha256": bytes.fromhex(
                        statement["triangle_digests"]["render_batch"]
                    ),
                    "nav_envelope_sha256": bytes.fromhex(
                        statement["triangle_digests"]["nav_envelope"]
                    ),
                    "receipt": {
                        "stage": spec.key,
                        "stage_version": spec.version,
                        "container": spec.params["container"],
                        "tessellator": spec.params["tessellator"],
                        "triangle_digest": spec.params["triangle_digest"],
                        "tile_document": spec.params["tile_document"],
                        "bake": statement,
                        # The recipe and specification the tile's world was generated from. The
                        # world itself is a workspace's, so this table, which holds nothing a
                        # workspace owns (migration 0072), does not name it; the workspace's own
                        # job and receipt do.
                        "generated_from": {
                            "recipe": receipt["recipe"],
                            "specification": receipt["specification"],
                        },
                    },
                }
                answers.append(self._publish(fields))
        return key, answers
