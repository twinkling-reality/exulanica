"""``POST /intake``: upload photographs, and watch them arrive.

**The queue between this route and the worker holds capture ids and never bytes.** That is the
one decision this file exists to keep, and :mod:`exulanica.ingest.derivative_queue` carries the
argument for it: an evidence address is a content hash of the original bytes, and the deletion
cascade reaches the rows under the tombstone guards and the objects in the content-addressed
store, and nothing else. Bytes staged anywhere in between are outside both, a tombstone written
while they sit there cascades to neither, and every test of the cascade still passes because
they look at the database and at the store.

So the staging window collapses to one request. The **intake stage runs here, synchronously**:
a hash, an EXIF read, an orientation transform and a handful of rows, tens of milliseconds on an
ordinary photograph. What is expensive is the vision stage, which is a model call, and it runs
in the worker from a capture id. The pipeline this route builds has **no vision model and no
depth model**, which is not a configuration choice: it is what makes "no model call happens in a
request thread" structural rather than a thing to be careful about.

**The store write still lands after the transaction that ran the tombstone guard commits.** The
obvious way to put uploaded bytes somewhere guarded is to write them to the store on arrival,
and that regresses the fix for defect 4 exactly: the rows of a refused import roll back and the
purged bytes stay on disk. Nothing here writes to the store; ``committed_writes`` does, after.

**202 and not 201.** The photographs are in the library when this returns and the rest of their
processing is not. ``batch_id`` is what the formation stream is addressed by, so the client that
caused the work is the client that watches it.

The eight checks, in the order a part meets them:

1.  the bearer token names a workspace, or the request never reaches this function;
2.  the request carries at most :data:`MAX_PARTS` parts;
3.  the part's name ends in a suffix this pipeline reads;
4.  the part is at most :data:`MAX_PART_BYTES`;
5.  the part is not empty;
6.  the bytes are an image of a format Pillow identifies, from the header alone;
7.  the frame is inside the pixel budget, from the same header, so a decompression bomb is
    refused for the price of parsing a header and the refusal states the pixel count;
8.  the content hash is not under a tombstone, which the pipeline asks before it writes anything
    anywhere, and which the database asks again inside the writing transaction.

**What is bounded here and what is not.** Checks 3 to 5 bound what reaches the store and the
database, which is what they are for. They do not bound the temporary file a multipart parser
has already written by the time this function runs: the body is received and parsed before any
route sees it. :mod:`exulanica.api.body_limit` refuses an over-large declared body ahead of that,
and a request that declares no length at all is a reverse proxy's to bound.
"""

from __future__ import annotations

import uuid
from pathlib import PurePosixPath
from typing import Annotated, Final, Literal

from fastapi import APIRouter, Depends, File, UploadFile
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict

from exulanica.api.dependencies import CurrentSession, ScopedConnection, get_services
from exulanica.api.services import Services
from exulanica.ingest import derivative_queue
from exulanica.ingest.batch import IntakeBatch
from exulanica.ingest.decode import probe
from exulanica.ingest.pipeline import SUPPORTED_SUFFIXES, PhotoIngestPipeline
from exulanica.ingest.report import IngestOutcome
from exulanica.ingest.repository import IngestRepository

router = APIRouter(prefix="/intake", tags=["intake"])

#: The most parts one upload may carry. A phone's selection, not a library import; a library
#: import is `exulanica-ingest` over a directory, which is a different thing with a different
#: failure mode.
MAX_PARTS: Final = 200

#: The most bytes one part may carry. Comfortably past any consumer camera's JPEG and past a
#: 16-bit TIFF of the same frame.
MAX_PART_BYTES: Final = 64 * 1024 * 1024

#: The refusal codes, and what each one means. A client can act on the code; the detail beside
#: it says which instance of it this was. Collapsing these into one "bad file" would be the
#: failure this project has a rule about: a zero must say which zero it is.
REFUSALS: Final[dict[str, str]] = {
    "too_many_parts": "the request carried more parts than one upload may",
    "unsupported_type": "the file name does not end in a suffix this pipeline reads",
    "too_large": "the part is larger than one photograph may be",
    "empty": "the part carried no bytes",
    "not_an_image": "the bytes are not an image of a format this pipeline identifies",
    "too_many_pixels": "the frame is larger than this pipeline will decode",
    "tombstoned": "the user has deleted these bytes and they may not be re-admitted",
    "failed": "the intake stage did not complete, and the reason is beside this",
}


class AcceptedPart(BaseModel):
    """One photograph that is in the library now, with the rest of its stages queued."""

    model_config = ConfigDict(extra="forbid")

    filename: str
    capture_id: uuid.UUID
    #: The content hash, hex. The first half of an evidence address, and the only identifier
    #: here that means anything after this response: a filename is what a client called a file.
    blob_sha256: str
    #: ``unchanged`` when these exact bytes were already in the library. Under content
    #: addressing that is the normal deduplication case and not an error: the capture is real,
    #: the derivatives already exist, and nothing was recomputed.
    status: Literal["ingested", "unchanged"]


class RefusedPart(BaseModel):
    """One part that did not become a photograph, and which of the checks stopped it."""

    model_config = ConfigDict(extra="forbid")

    filename: str
    reason: str
    detail: str


class IntakeAccepted(BaseModel):
    """What a 202 says: what is in, what is not, and what is still coming."""

    model_config = ConfigDict(extra="forbid")

    #: The watched intake. ``GET /formation/{batch_id}`` streams its progress.
    batch_id: uuid.UUID
    accepted: list[AcceptedPart]
    refused: list[RefusedPart]
    #: The queued derivative run, or null when nothing was accepted and so nothing was queued.
    #: Null here and an empty ``accepted`` are the same fact said twice, on purpose: a client
    #: polling a job id must be able to tell "there is no job" from "the job is not done".
    queued_job_id: uuid.UUID | None


@router.post(
    "",
    status_code=202,
    summary="Upload photographs. Intake runs now; the model stages are queued.",
)
def intake(
    connection: ScopedConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
    files: Annotated[list[UploadFile], File(description="The photographs to ingest.")],
) -> IntakeAccepted:
    """Admit what can be admitted, refuse the rest by name, and queue what remains.

    The batch is opened before anything is read so a client that subscribes immediately finds
    something to subscribe to, and its declared size is written once, from what was accepted,
    rather than accumulated. A denominator that grows is one that moves under a fraction
    somebody is already reading.

    **The batch is closed here only when there is nothing to queue.** Otherwise the worker
    closes it, because a batch's terminal event tells a client to stop listening and it has to
    come after all of the work. A request that closed the batch it opened would emit "finished"
    before the vision stage had started.
    """
    repository = IngestRepository(connection, session.workspace_id)
    # No vision model and no depth model. Structural, not configuration: this pipeline cannot
    # make a model call, so no amount of later editing puts one in a request thread.
    pipeline = PhotoIngestPipeline(repository, services.store)
    batch = IntakeBatch.open(repository, label="upload")

    accepted: list[AcceptedPart] = []
    refused: list[RefusedPart] = []
    capture_ids: list[uuid.UUID] = []

    for index, upload in enumerate(files):
        name = _safe_name(upload.filename, index)
        try:
            if index >= MAX_PARTS:
                refused.append(_refusal(name, "too_many_parts", f"at most {MAX_PARTS} per upload"))
                continue
            checked = _read_and_check(upload, name)
            if isinstance(checked, RefusedPart):
                refused.append(checked)
                continue
            outcome = pipeline.ingest_intake(checked, filename=name, batch_id=batch.batch_id)
            _record(outcome, name, accepted, refused, capture_ids)
        except Exception as exc:
            # **One part may never abandon the others.** By the time a later part raises, the
            # earlier ones have committed: their captures exist, their intake artifacts exist,
            # and their bytes are in the store. An exception escaping this loop would skip
            # `declare_size` and `enqueue` below, leaving those photographs with no derivative
            # job, a batch stuck open, and a 500 carrying no batch id for the client to watch or
            # retry against. Nothing reconciles that, so the loop refuses the part instead.
            #
            # Broad on purpose. `_read_and_check` already names every refusal it can recognise;
            # what reaches here is by definition a shape nobody anticipated, and the response to
            # an unanticipated shape must not be to lose the work that already succeeded.
            refused.append(_refusal(name, "failed", f"{type(exc).__name__}: {exc}"))
        finally:
            # The parser spooled this part before this function was entered, so closing here
            # does not bound the peak: it releases each part's temporary space as soon as the
            # part has been read, rather than holding all of it until the response is sent.
            upload.file.close()

    batch.declare_size(len(accepted))
    job_id: uuid.UUID | None = None
    if capture_ids:
        job_id = derivative_queue.enqueue(
            connection, session.workspace_id, batch_id=batch.batch_id, capture_ids=capture_ids
        )
    else:
        # Nothing was queued, so nothing will ever close this batch, and a stream that never
        # ends is a client reconnecting forever to be told nothing. The refusals are already in
        # this response, synchronously, to the person who can act on them.
        batch.close(IntakeBatch.outcome_for(succeeded=0, failed=0))

    return IntakeAccepted(
        batch_id=batch.batch_id, accepted=accepted, refused=refused, queued_job_id=job_id
    )


def _read_and_check(upload: UploadFile, name: str) -> bytes | RefusedPart:
    """Checks 3 to 7, in order, returning either the bytes or the check that stopped them."""
    if PurePosixPath(name).suffix.lower() not in SUPPORTED_SUFFIXES:
        return _refusal(name, "unsupported_type", f"one of {', '.join(sorted(SUPPORTED_SUFFIXES))}")
    # One byte past the bound, and no more. This is the check rather than a comparison against
    # the size the parser reports, deliberately: the reported size is the parser's own
    # bookkeeping, this bound is what keeps an over-large part out of memory and out of the
    # store, and a check that holds only while a library keeps its accounting is not the check.
    # The extra byte is what separates "exactly the limit" from "over it" without reading the
    # rest of a part that is already refused.
    data = upload.file.read(MAX_PART_BYTES + 1)
    if len(data) > MAX_PART_BYTES:
        return _refusal(name, "too_large", f"more than {MAX_PART_BYTES} bytes")
    if not data:
        return _refusal(name, "empty", "0 bytes")
    try:
        width, height = probe(data)
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        return _refusal(name, "too_many_pixels", str(exc))
    except UnidentifiedImageError:
        # Not ``str(exc)``. Pillow's message for this one is "cannot identify image file
        # <_io.BytesIO object at 0x...>", which puts a repr and a heap address of ours into a
        # response somebody else reads, and says nothing they could act on either.
        return _refusal(
            name, "not_an_image", "no image format this pipeline reads was found in these bytes"
        )
    except (OSError, ValueError) as exc:
        # These do say something useful and carry no repr: a truncated file, a broken data
        # stream, a decoder that ran out of input.
        #
        # ``ValueError`` because **Pillow dispatches on magic bytes and not on the file name**.
        # A thirty-byte part named ``a.jpg`` beginning ``P6\n999...`` reaches ``PpmImagePlugin``
        # and raises ``ValueError: Token too long in file header``, which is neither
        # ``UnidentifiedImageError`` nor ``OSError``. Measured, and before this it was a 500 that
        # abandoned every part already ingested in the same request.
        return _refusal(name, "not_an_image", str(exc))
    if width <= 0 or height <= 0:
        return _refusal(name, "not_an_image", f"the header declares a {width}x{height} frame")
    return data


def _record(
    outcome: IngestOutcome,
    name: str,
    accepted: list[AcceptedPart],
    refused: list[RefusedPart],
    capture_ids: list[uuid.UUID],
) -> None:
    """Check 8's answer, and everything after it, as three distinct outcomes.

    ``tombstoned`` is not ``failed``. The user deleted these bytes and the system declined to
    re-admit them, which is the deletion path working; reporting it as a failure would put a
    fault in front of somebody who got exactly what they asked for.
    """
    if outcome.tombstoned:
        refused.append(_refusal(name, "tombstoned", outcome.error or "tombstoned"))
        return
    if outcome.error is not None or outcome.capture_id is None or outcome.blob_id is None:
        refused.append(_refusal(name, "failed", outcome.error or "the intake stage wrote nothing"))
        return
    accepted.append(
        AcceptedPart(
            filename=name,
            capture_id=outcome.capture_id,
            blob_sha256=outcome.blob_id.hex,
            status="unchanged" if outcome.unchanged else "ingested",
        )
    )
    # Once per capture, however many parts named it. Two parts carrying identical bytes are one
    # photograph under content addressing and the response says so twice, honestly, because two
    # files were uploaded; the queue must not say so twice, because that is the same derivative
    # work queued twice and the model calls behind it are what a duplicate costs.
    if outcome.capture_id not in capture_ids:
        capture_ids.append(outcome.capture_id)


def _refusal(name: str, reason: str, detail: str) -> RefusedPart:
    assert reason in REFUSALS, reason
    return RefusedPart(filename=name, reason=reason, detail=detail)


def _safe_name(filename: str | None, index: int) -> str:
    """What the client called this part, reduced to something safe to echo and to log.

    The name is never a path here and never reaches the filesystem: an evidence address is a
    content hash, a track key and a time interval, and a name a client chose is none of those.
    It is still stripped to a basename and capped, because a value that is echoed back to a
    browser and written into a report should not carry directory separators or arbitrary length.
    """
    raw = (filename or "").strip()
    base = PurePosixPath(raw.replace("\\", "/")).name if raw else ""
    cleaned = "".join(c for c in base if c.isprintable() and c not in '"\\')[:200]
    return cleaned or f"part-{index}"
