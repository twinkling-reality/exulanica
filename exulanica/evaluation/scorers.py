"""The corpus and authorization scorers; declared-plan answers use question_scorers.py.

Each one returns a ``Count`` with every case named, because section 3.1 rule 4 asks for failures
by name with their evidence rather than for an aggregate. A component that cannot run is not
here: it is a row in ``metrics.py`` carrying the sentence that says what is missing, because
"blocked" and "scored zero" are different facts and a harness that reported them alike would be
the same defect this project keeps finding elsewhere.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from collections.abc import Callable
from typing import Final

import psycopg

from exulanica.evaluation.counts import Count, NamedCase
from exulanica.evaluation.ground_truth import Frame, GroundTruth
from exulanica.selection import (
    CaptureWindow,
    EpistemicScope,
    Intent,
    Session,
    execute,
    parse,
    validate,
)

__all__ = [
    "score_authorisation",
    "score_capture_time_windows",
    "score_citation_identity",
    "score_provenance_completeness",
]


def score_citation_identity(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    truth: GroundTruth,
    read_blob: Callable[[bytes], bytes | None],
) -> Count:
    """M1 CIT-ID. Every span resolves to the exact original bytes the manifest names.

    The join is by content address, never by filename, which is the reason the manifest is keyed
    that way. What is being measured is that a citation opens the exact original, so the check
    reads the bytes back out of the store and hashes them: a row that merely points at a hash
    would be checking the database against itself.

    A span whose bytes are NOT in the manifest is not scored and is not a failure. It is a
    capture this corpus has no ground truth for, which happens whenever a workspace holds more
    than one corpus, and counting it as a failed citation would report the harness's own blind
    spot as the product's defect. The count of unscoreable spans is returned as a passing case so
    the number appears in the report rather than being silently dropped: a reader has to be able
    to see that 80 of 327 spans were in scope.
    """
    rows = connection.execute(
        "select distinct blob_sha256 from evidence_span where workspace_id = %s",
        (workspace,),
    ).fetchall()
    by_hash = truth.by_hash
    cases: list[NamedCase] = []
    outside = 0
    for row in rows:
        digest = bytes(row["blob_sha256"]).hex()
        frame = by_hash.get(digest)
        if frame is None:
            outside += 1
            continue
        payload = read_blob(bytes(row["blob_sha256"]))
        if payload is None:
            cases.append(NamedCase(frame.filename, False, "the cited bytes are not in the store"))
            continue
        recomputed = hashlib.sha256(payload).hexdigest()
        cases.append(
            NamedCase(
                frame.filename,
                recomputed == frame.sha256,
                "" if recomputed == frame.sha256 else f"store holds {recomputed[:12]}",
            )
        )
    scored = Count(sum(case.passed for case in cases), len(cases), tuple(cases))
    if outside:
        # Reported, not dropped. "80 of 80 in scope, 247 spans outside this corpus" and
        # "80 of 327" are different facts and only the first one is true.
        scored = Count(
            scored.k,
            scored.n,
            (
                NamedCase(
                    f"{outside} spans in this workspace are outside the corpus and were not "
                    "scored, because there is no ground truth for them",
                    True,
                ),
                *scored.cases,
            ),
        )
    return scored


def score_provenance_completeness(
    connection: psycopg.Connection, workspace: uuid.UUID
) -> Count:
    """M5. Every edge in the confirmed graph carries at least one evidence pointer.

    It licenses nothing about whether the edges are CORRECT. That is a learned number and it is
    not this one, and section 6.1 says so in the row this scorer implements.
    """
    rows = connection.execute(
        "select l.link_id, o.span_ids from entity_link l "
        "join occurrence o on o.occurrence_id = l.occurrence_id "
        "where l.workspace_id = %s and l.state = 'confirmed'",
        (workspace,),
    ).fetchall()
    cases = [
        NamedCase(
            str(row["link_id"])[:8],
            bool(row["span_ids"]),
            "" if row["span_ids"] else "a confirmed edge with no evidence pointer",
        )
        for row in rows
    ]
    return Count(sum(case.passed for case in cases), len(cases), tuple(cases))


#: What turns a closed range of instants into a half-open window. A trip's frames run from its
#: first instant to its last INCLUSIVE, and every window in this system excludes its end, so a
#: window meant to hold the whole trip has to end after the last frame rather than on it. One
#: second is enough because the corpus records instants to the second, and using it rather than
#: the smallest representable step keeps the boundary readable in a failure message.
_A_SECOND: Final = dt.timedelta(seconds=1)


def _placeable(truth: GroundTruth, ingested: set[str]) -> list[tuple[Frame, dt.datetime]]:
    """The frames whose instant the manifest can adjudicate, and which are actually here.

    Three conditions and each one drops a frame for a different reason.

    *   **Ingested.** A frame the workspace does not hold cannot be returned by anything, and a
        gold set over frames that were never ingested scores every window as failing for a
        reason that is the harness's own.
    *   **Recoverable from the file.** One device in this corpus writes ``OffsetTimeOriginal``
        and one does not. A frame from the second carries a wall-clock reading and no way to
        place it on a timeline, so the manifest cannot say which window it belongs in, and a
        gold set that included it would be scoring the pipeline's guess at an offset under a
        name that says filters.
    *   **Carries an instant.** Belt and braces against a manifest that says recoverable and
        records nothing; :func:`exulanica.evaluation.ground_truth.instant_is_correct` treats that
        combination as a failure and this must not silently read it as a window boundary.
    """
    return sorted(
        (
            (frame, dt.datetime.fromisoformat(frame.utc_instant))
            for frame in truth.frames
            if frame.sha256 in ingested
            and frame.instant_is_recoverable_from_the_file
            and frame.utc_instant
        ),
        key=lambda pair: (pair[1], pair[0].sha256),
    )


def _window_cases(
    placeable: list[tuple[Frame, dt.datetime]], trips: tuple[str, ...]
) -> list[tuple[str, list[CaptureWindow]]]:
    """The windows to ask for, derived from the manifest and from nothing else.

    Fixed by this rule rather than chosen per corpus, because a harness that picked its own
    boundaries after seeing the data could pick the ones that pass. Per trip holding a placeable
    frame: the whole trip, its opening half and its closing half, so the two halves must tile the
    whole exactly. Then three cases about the shape of the interval rather than about a trip:

    *   **The half-open end.** A window ending exactly on a frame's instant must exclude that
        frame. This is the boundary every interval in this system is half-open at, and it is
        where an off-by-one in a filter of this shape hides.
    *   **A gap holding nothing.** It must come back empty rather than with the nearest thing,
        which is the same demand M6's trap (a) makes of the entity dimension.
    *   **Two windows.** They are ORed with each other, so the answer is the union and not the
        intersection, and a compiler that ANDed them would return nothing at all.
    """
    cases: list[tuple[str, list[CaptureWindow]]] = []
    for trip in trips:
        instants = [instant for frame, instant in placeable if frame.trip == trip]
        if not instants:
            continue
        low, high, middle = instants[0], instants[-1] + _A_SECOND, instants[len(instants) // 2]
        cases.append((f"{trip}, the whole trip", [CaptureWindow(start=low, end=high)]))
        if middle > low:
            cases.append((f"{trip}, its opening half", [CaptureWindow(start=low, end=middle)]))
        if high > middle:
            cases.append((f"{trip}, its closing half", [CaptureWindow(start=middle, end=high)]))

    every = [instant for _frame, instant in placeable]
    first, last = every[0], every[-1]
    opening = CaptureWindow(start=first, end=every[1])
    cases.append(("a half-open end excludes the frame sitting on it", [opening]))
    cases.append(
        (
            "a window holding no frame comes back empty",
            [CaptureWindow(start=last + _A_SECOND, end=last + dt.timedelta(days=1))],
        )
    )
    cases.append(
        (
            "two windows are ORed with each other",
            [opening, CaptureWindow(start=last, end=last + _A_SECOND)],
        )
    )
    return cases


def score_capture_time_windows(
    connection: psycopg.Connection, workspace: uuid.UUID, truth: GroundTruth
) -> tuple[Count | None, str]:
    """M15. A capture-time window returns the frames the corpus placed inside it.

    **The whole path runs.** Each case builds a plan payload, hands it to
    :func:`exulanica.selection.validation.parse`, then to
    :func:`exulanica.selection.validation.validate`, then to
    :func:`exulanica.selection.executor.execute`. That ordering is not a style choice: ``execute``
    accepts only a ``ValidatedPlan`` and ``validate`` is the only thing that constructs one, so
    there is no way to reach the executor that skips a stage. A defect anywhere in parse,
    validation, compilation or the SQL makes a case here fail.

    **Why this dimension and no other.** Capture time is the one dimension of a Selection whose
    gold set is ground truth rather than the system's own output. The corpus generator WROTE the
    instants into the files and recorded them in ``MANIFEST.json``; every other dimension is
    either an entity, which exists only where a person confirmed one, or a property the pipeline
    derived, and a gold set derived from the system's output measures nothing.

    **What a failure here does not distinguish, and the report says so.** Two things can make a
    frame miss its window: the filter, or the instant the pipeline stored for it. The evidence on
    each failing case prints both the manifest's instant and the stored one, so a reader can tell
    which of the two they are looking at without rerunning anything.

    **Three ways a case is not scored, and none of them is a zero.**

    *   The page came back bounded, so the result is a page and not a set.
    *   The result holds a corpus frame the manifest cannot place on a timeline, so the manifest
        cannot adjudicate whether it belonged in the window.
    *   The result holds captures outside this corpus, which is not a failure and not scoreable
        either: the manifest has no ground truth for them.

    The first two make a case unscoreable and are counted into a named case of their own. The
    third is counted and reported and does not stop a case scoring, because a capture the
    manifest never described cannot be evidence for or against a claim about the manifest. It is
    counted once per capture rather than once per window it appeared in: the windows overlap, so
    the two numbers differ and only the first is the one the sentence claims.
    """
    rows = connection.execute(
        "select blob_sha256, started_at from capture "
        "where workspace_id = %s and deleted_at is null",
        (workspace,),
    ).fetchall()
    stored = {bytes(row["blob_sha256"]).hex(): row["started_at"] for row in rows}
    in_corpus = {frame.sha256 for frame in truth.frames}
    placeable = _placeable(truth, set(stored))
    if len(placeable) < 2:
        return None, (
            f"{len(placeable)} of this corpus's {len(truth.frames)} frames are both ingested in "
            "this workspace and carry an instant the manifest can place on a timeline, and two "
            "are needed before a window has a boundary to be half-open at"
        )

    by_instant = {frame.sha256: instant for frame, instant in placeable}
    unplaceable = in_corpus - set(by_instant)
    cases: list[NamedCase] = []
    unscoreable: list[str] = []
    outside: set[str] = set()
    for name, windows in _window_cases(placeable, truth.trips):
        plan = parse(
            {
                "intent": str(Intent.CAPTURES),
                "epistemic": str(EpistemicScope.CONFIRMED),
                "time": [
                    {"start": window.start.isoformat(), "end": window.end.isoformat()}
                    for window in windows
                ],
            }
        )
        # `may_include_proposals` is False because this plan does not ask for proposals and a
        # session that could not grant them proves it did not lean on them. The actor is required
        # by `Session` and is read by nothing on this path: `orimera.selection` never touches it,
        # and this harness performs no write for it to be the author of.
        validated = validate(
            connection,
            plan,
            Session(workspace_id=workspace, actor=uuid.UUID(int=0), may_include_proposals=False),
        )
        result = execute(connection, validated)
        got = {capture.blob_id.hex for capture in result.captures}
        # A SET, because the windows overlap by construction: a trip's two halves tile its whole,
        # so a capture outside the corpus is returned by three of them. Summing the per-window
        # counts would report (window, capture) pairs under a sentence that says captures.
        outside |= got - in_corpus
        got_here = got & in_corpus
        if result.truncated:
            unscoreable.append(
                f"{name}: {result.total_matched} captures match and a page holds "
                f"{plan.limit}, so the result is a page and not a set"
            )
            continue
        if got_here & unplaceable:
            unscoreable.append(
                f"{name}: the window caught {len(got_here & unplaceable)} corpus frame(s) whose "
                "instant the manifest cannot place, so it cannot adjudicate them"
            )
            continue
        gold = {
            digest
            for digest, instant in by_instant.items()
            if any(window.start <= instant < window.end for window in windows)
        }
        cases.append(
            NamedCase(
                f"{name} ({len(gold)} frames)",
                got_here == gold,
                "" if got_here == gold else _why(gold, got_here, by_instant, stored, truth),
            )
        )

    if not cases:
        return None, (
            "no window could be compared as a set: " + "; ".join(unscoreable)
        )
    scored = Count(sum(case.passed for case in cases), len(cases), tuple(cases))
    notes = []
    if unscoreable:
        notes.append(
            NamedCase(
                f"{len(unscoreable)} window(s) were not scored, and why: "
                + "; ".join(unscoreable),
                True,
            )
        )
    if outside:
        # Reported, not dropped, for the same reason M1 reports its out-of-scope spans: a reader
        # has to be able to see that the workspace holds captures this corpus says nothing about.
        notes.append(
            NamedCase(
                f"{len(outside)} distinct capture(s) returned across these windows are outside "
                "this corpus and were neither required nor forbidden, because there is no "
                "ground truth for them",
                True,
            )
        )
    return Count(scored.k, scored.n, (*notes, *scored.cases)), ""


def _why(
    gold: set[str],
    got: set[str],
    by_instant: dict[str, dt.datetime],
    stored: dict[str, dt.datetime | None],
    truth: GroundTruth,
) -> str:
    """Name the frames that made a window wrong, and print both instants for each.

    Rule 4 wants the case that produced a failure. For this metric that is not just the filename:
    the reader needs to know whether the frame missed because the filter did not return it or
    because the pipeline stored a different instant for it than the generator wrote, and those
    two are told apart by putting the manifest's instant next to the stored one.
    """
    names = {frame.sha256: frame.filename for frame in truth.frames}

    def described(digests: set[str]) -> str:
        return ", ".join(
            f"{names.get(digest, digest[:12])} "
            f"(manifest {by_instant[digest].isoformat()}, stored "
            f"{stored[digest].isoformat() if stored.get(digest) else 'nothing'})"
            for digest in sorted(digests, key=lambda d: names.get(d, d))
        )

    parts = []
    if gold - got:
        parts.append(f"{len(gold - got)} not returned: {described(gold - got)}")
    if got - gold:
        parts.append(f"{len(got - gold)} returned and out of window: {described(got - gold)}")
    return "; ".join(parts)


def score_authorisation(
    probe: Callable[[str, str], tuple[int, object]],
    routes: list[tuple[str, str]],
    public: set[str],
) -> Count:
    """M10. No cross-tenant read succeeded on any route generated from the router.

    ``routes`` comes from ``exulanica.api.routes.routable_paths`` rather than from a list here,
    which is what M10's own specification requires and what stopped this sweep going blind once
    already.

    TWO KINDS OF ROUTE AND TWO PASS CONDITIONS, because one rule gets the second kind wrong.

    *   A route addressed by an id is a resource. A stranger must receive 404 and never 403, so
        the surface is not an existence oracle: a foreign id and an invented one have to be
        indistinguishable from outside.
    *   A route with no id in it is a collection scoped to the caller's own workspace. A stranger
        asking for their own graph gets their own graph, which is empty, and 200 is the correct
        answer. Requiring 404 there would be requiring the API to pretend the caller does not
        exist. What must be true is that the body carries none of the owner's records, so that is
        what is checked.

    The first version of this scorer applied the resource rule to everything and reported
    ``GET /graph`` and ``GET /formation`` as cross-tenant reads. They were not: they were empty.
    """
    cases: list[NamedCase] = []
    for method, path in routes:
        if path in public:
            continue
        status, body = probe(method, path)
        if "{" in path:
            allowed = status in (404, 422)
            evidence = "" if allowed else f"a stranger received {status} for a foreign id"
        else:
            allowed = status in (404, 422) or _is_empty_of_records(body)
            evidence = (
                "" if allowed else f"a stranger received {status} carrying records: {body!r:.120}"
            )
        cases.append(NamedCase(f"{method} {path}", allowed, evidence))
    return Count(sum(case.passed for case in cases), len(cases), tuple(cases))


def _is_empty_of_records(body: object) -> bool:
    """Does this response carry nothing belonging to anybody?

    A collection route answers a stranger with the stranger's own scope, and the stranger owns
    nothing, so every list in the body must be empty. Scalars are ignored: a state version or a
    count is not somebody's record.
    """
    if isinstance(body, list):
        return not body
    if isinstance(body, dict):
        return all(_is_empty_of_records(value) for value in body.values())
    return True
