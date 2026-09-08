"""Evidence resolution: the endpoint the product's promise reduces to.

Every historical factual claim resolves to the exact original source moment. This is where that
stops being a design and becomes an HTTP response, so three properties matter more here than
anywhere else in the API.

**It serves the original bytes, never a derivative.** ``resolve_original_bytes`` goes to the
content-addressed store, which re-hashes what it read before returning it, so a citation cannot
resolve to a rendition, a thumbnail, or content that has been altered since it was cited. The
region endpoint is a separate path and says so in its name: it crops the original in display
space, applying the same orientation transform ingest applied, and it is a convenience for the
interface rather than what a citation resolves to.

**A span from another workspace is a 404, not a 403.** ``evaluation-methodology.md`` M10 is
explicit: "404, never 403, so the surface is not an existence oracle. Nonexistent and foreign IDs
return the identical code." That is not achieved by a check in this module; it is achieved by the
query being scoped to the caller's workspace under row-level security, so a foreign span is
simply not there. The two cases share a code because they share a code path.

**Withdrawal is checked before bytes are read.** A committed capture, interval or workspace
withdrawal returns 410 even while purge is pending. The canonical address predicate preserves
ordinary deliberate reimport and workspace isolation; shared stored bytes do not override it.

**Range requests are supported**, because the original of a photograph is a few megabytes and a
citation deep link should not have to transfer all of it to show the top of it. The
implementation is deliberately the boring one: a single byte range, a 206 with ``Content-Range``,
and a 416 with the unsatisfied-range header when the request is out of bounds.

**The response carries the citation's wall clock and the uncertainty of it**, in headers, because
a client showing "this was taken at 10:00" needs to know how well that is known. The domain model
is specific: wall-clock queries are "translated through the anchor table and the uncertainty of
that translation is carried into the answer rather than rounded away". An EXIF timestamp with no
zone is a real and common state, and it is knowable to within hours rather than seconds. Headers
rather than a second metadata endpoint, because the client needs them at the moment it renders
the bytes and a second round trip to learn them would be a second thing to get out of step.
"""

from __future__ import annotations

import datetime as dt
import io
import re
import uuid
from collections.abc import Mapping
from typing import Annotated, Any, Final

import psycopg
from fastapi import APIRouter, Header, HTTPException, Path, Request, Response

from exulanica.api.dependencies import CurrentSession, ReadOnlyConnection, get_services
from exulanica.evidence import EvidenceAddress, parse_uri
from exulanica.evidence.blob import BlobId
from exulanica.graph.asset_read_policy import evaluation_time, final_check, image_source
from exulanica.ingest.resolve import resolve_region_image
from exulanica.selection.validation import Session
from exulanica.store.resolve import address_from_span_row, resolve_original_bytes

router = APIRouter(prefix="/evidence", tags=["evidence"])

#: One range, ``bytes=start-end``, either bound optional. A multipart response to a multi-range
#: request is a real thing and nothing here needs it, so it is refused rather than half done.
_RANGE: Final = re.compile(r"^bytes=(\d*)-(\d*)$")

_MEDIA_TYPE_FALLBACK: Final = "application/octet-stream"


@router.get("/{span_id}", summary="The original media a citation resolves to.")
def original(
    span_id: Annotated[uuid.UUID, Path()],
    request: Request,
    connection: ReadOnlyConnection,
    session: CurrentSession,
    range_header: Annotated[str | None, Header(alias="range")] = None,
) -> Response:
    address, media_type, clock = _address(connection, session, span_id)
    data = resolve_original_bytes(address, get_services(request).store)
    _authorize_original(connection, session, address, media_type)
    return _ranged(data, media_type, range_header, clock)


@router.get(
    "/{span_id}/masked",
    summary="The photograph with every unconsented person filled neutral.",
)
def masked(
    span_id: Annotated[uuid.UUID, Path()],
    request: Request,
    connection: ReadOnlyConnection,
    session: CurrentSession,
    range_header: Annotated[str | None, Header(alias="range")] = None,
) -> Response:
    """The derivative a viewer may see, never the original bytes behind it.

    A sibling of the route above rather than a change to it, and the distinction is not cosmetic.
    ``GET /evidence/{span_id}`` resolves the exact bytes a citation names, and those bytes are
    inside the span digest: serving something else there would break every archived citation that
    verifies against it. So the original endpoint keeps its meaning and this one exists for the
    world, which shows photographs to people rather than resolving citations.

    **Refuses rather than falling back.** When the photograph contains somebody who has not
    consented and no masked derivative exists, this returns 409 and no bytes. Serving the original
    would show exactly the person the derivative exists to hide, on the one path a viewer actually
    looks at, and it would do it precisely when something upstream had already gone wrong.
    """
    address, media_type, clock = _address(connection, session, span_id)
    store = get_services(request).store
    if address.track_key != "img" and not media_type.startswith("image/"):
        data = resolve_original_bytes(address, store)
        _authorize_original(connection, session, address, media_type)
        return _ranged(data, media_type, range_header, clock)
    selected = image_source(
        connection, session.workspace_id, address.blob_id.digest, evaluation_time(connection)
    )
    if selected is None:
        raise HTTPException(409, "current viewer image is unavailable")
    data = store.get(BlobId(selected))
    with final_check(connection) as at:
        _check_span(connection, session, address, at)
        if image_source(connection, session.workspace_id, address.blob_id.digest, at) != selected:
            raise HTTPException(409, "viewer image permission changed")
    return _ranged(
        data,
        media_type if selected == address.blob_id.digest else "image/jpeg",
        range_header,
        clock,
    )


@router.get("/{span_id}/region", summary="The region of the original this span names, as PNG.")
def region(
    span_id: Annotated[uuid.UUID, Path()],
    request: Request,
    connection: ReadOnlyConnection,
    session: CurrentSession,
) -> Response:
    """A crop, for showing what a citation points at inside a photograph.

    Not what the citation resolves to. The address names the original bytes and a region within
    them; this renders that region so an interface can draw it, and a caller wanting the
    evidence itself asks for the endpoint above.
    """
    address, _media_type, clock = _address(connection, session, span_id)
    image = resolve_region_image(address, get_services(request).store)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    _authorize_original(connection, session, address, _media_type)
    return Response(
        content=buffer.getvalue(),
        media_type="image/png",
        headers={"Cache-Control": "private, no-store", **clock},
    )


@router.get("", summary="The same, addressed by permalink rather than by row id.")
def by_uri(
    uri: str,
    request: Request,
    connection: ReadOnlyConnection,
    session: CurrentSession,
    range_header: Annotated[str | None, Header(alias="range")] = None,
) -> Response:
    """Resolve an ``exulanica://`` permalink.

    The permalink is designed to stay valid forever and to parse back to an address with the
    same digest, which is what lets an archived answer's citation still open. It names a blob
    directly, so the workspace check cannot come from the row id and has to be made explicitly:
    a span with this digest must exist in the caller's workspace. Without that, a permalink
    would be a way to read any blob in the database by naming its hash.
    """
    try:
        address = parse_uri(uri)
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"not a valid evidence permalink: {exc}"
        ) from exc

    row = connection.execute(
        "select b.media_type, "
        "tombstone_blocks_span(s.workspace_id, s.blob_sha256, s.track_key, "
        "s.t_start_ns, s.t_end_ns) as withdrawn "
        "from evidence_span s join blob b on b.blob_sha256 = s.blob_sha256 "
        "where s.workspace_id = %s and s.span_digest = %s",
        (session.workspace_id, address.span_digest),
    ).fetchone()
    if row is None:
        # The same 404 a nonexistent span gets. A permalink for a span in another workspace and
        # a permalink for a span that never existed are indistinguishable from out here.
        raise HTTPException(status_code=404, detail="no such evidence")
    if row["withdrawn"]:
        raise HTTPException(
            status_code=410,
            detail="evidence was withdrawn",
            headers={"Cache-Control": "private, no-store"},
        )
    data = resolve_original_bytes(address, get_services(request).store)
    _authorize_original(connection, session, address, row["media_type"])
    return _ranged(data, row["media_type"], range_header, _evidence_headers(str(address.modality)))


def _address(
    connection: psycopg.Connection, session: Session, span_id: uuid.UUID
) -> tuple[EvidenceAddress, str, dict[str, str]]:
    """Rebuild the address from the stored span, and refuse if the digest no longer matches.

    ``address_from_span_row`` raises when the rebuilt digest differs from the stored one. That
    is not a defensive nicety: the token in an archived answer was verified against the stored
    digest, so a mismatch means every citation naming this span has silently stopped verifying,
    and serving the bytes anyway would hide it.
    """
    row = connection.execute(
        "select s.*, b.media_type, a.utc_instant, a.uncertainty_ms, a.source, "
        "tombstone_blocks_span(s.workspace_id, s.blob_sha256, s.track_key, "
        "s.t_start_ns, s.t_end_ns) as withdrawn "
        "from evidence_span s "
        "join blob b on b.blob_sha256 = s.blob_sha256 "
        "left join media_track t on t.blob_sha256 = s.blob_sha256 and t.track_key = s.track_key "
        "left join clock_anchor a on a.track_id = t.track_id "
        "where s.workspace_id = %s and s.span_id = %s",
        (session.workspace_id, span_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="no such evidence")
    if row["withdrawn"]:
        raise HTTPException(
            status_code=410,
            detail="evidence was withdrawn",
            headers={"Cache-Control": "private, no-store"},
        )
    # No `except` here, and the absence is the point. `address_from_span_row` raises
    # IntegrityError when the row no longer hashes to its stored digest, and InvalidAddressError
    # when the row is not a well formed address at all. Both are integrity failures about every
    # citation naming this span, and app.py answers IntegrityError with a loud 500 rather than a
    # 404. This used to catch BlobNotFoundError, which that function cannot raise: the clause
    # was inert, and had it ever fired it would have turned the mismatch this docstring says
    # must not be hidden into "no such evidence".
    address = address_from_span_row(row)
    return address, row["media_type"] or _MEDIA_TYPE_FALLBACK, _clock_headers(row)


def _evidence_headers(modality: str) -> dict[str, str]:
    return {"X-Exulanica-Modality": modality}


def _clock_headers(row: Mapping[str, Any]) -> dict[str, str]:
    """The wall clock this evidence carries, with how well it is known.

    Three headers or none. A timestamp without its uncertainty invites an interface to render a
    minute that is only known to the hour, and the clock source is what explains why: an EXIF
    time with no offset is a different kind of fact from one with a GPS fix behind it.
    """
    headers = _evidence_headers(row["modality"])
    if row["utc_instant"] is None:
        return headers
    headers["X-Exulanica-Captured-At"] = row["utc_instant"].isoformat()
    headers["X-Exulanica-Captured-At-Uncertainty-Ms"] = str(row["uncertainty_ms"])
    headers["X-Exulanica-Clock-Source"] = row["source"]
    return headers


def _ranged(
    data: bytes, media_type: str, range_header: str | None, extra: dict[str, str] | None = None
) -> Response:
    """A whole response, or one byte range of it. Never a multipart one."""
    total = len(data)
    common = {
        "Accept-Ranges": "bytes",
        # Every new request must observe current withdrawal state; neither shared caches nor
        # a one-hour private freshness window may bypass the evidence boundary.
        "Cache-Control": "private, no-store",
        **(extra or {}),
    }
    if not range_header:
        return Response(content=data, media_type=media_type, headers=common)

    match = _RANGE.match(range_header.strip())
    if match is None:
        raise HTTPException(
            status_code=416,
            detail="only a single 'bytes=start-end' range is supported",
            headers={"Content-Range": f"bytes */{total}"},
        )
    raw_start, raw_end = match.groups()
    if raw_start == "" and raw_end == "":
        raise HTTPException(
            status_code=416,
            detail="a range needs a bound",
            headers={"Content-Range": f"bytes */{total}"},
        )
    if raw_start == "":
        # A suffix range: the last N bytes.
        length = min(int(raw_end), total)
        start, end = total - length, total - 1
    else:
        start = int(raw_start)
        end = min(int(raw_end), total - 1) if raw_end else total - 1
    if start > end or start >= total:
        raise HTTPException(
            status_code=416,
            detail="range not satisfiable",
            headers={"Content-Range": f"bytes */{total}"},
        )
    return Response(
        status_code=206,
        content=data[start : end + 1],
        media_type=media_type,
        headers={**common, "Content-Range": f"bytes {start}-{end}/{total}"},
    )


def _check_span(
    connection: psycopg.Connection, session: Session, address: EvidenceAddress, at: dt.datetime
) -> None:
    blocked = connection.execute(
        "select asset_tombstone_span(%s,%s,%s,%s,%s,%s) as blocked",
        (
            session.workspace_id,
            address.blob_id.digest,
            address.track_key,
            address.interval.start_ns,
            address.interval.end_ns,
            at,
        ),
    ).fetchone()["blocked"]
    if blocked:
        raise HTTPException(410, "evidence was withdrawn")


def _authorize_original(
    connection: psycopg.Connection,
    session: Session,
    address: EvidenceAddress,
    media_type: str | None,
) -> None:
    with final_check(connection) as at:
        _check_span(connection, session, address, at)
        if (
            address.track_key == "img" or (media_type and media_type.startswith("image/"))
        ) and image_source(
            connection, session.workspace_id, address.blob_id.digest, at, original=True
        ) != address.blob_id.digest:
            raise HTTPException(409, "current permission does not allow original image delivery")
