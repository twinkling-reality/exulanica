"""The one place the World Read API asks whether a photograph may be shown.

This module used to be a constants module that stood in for a layer being built elsewhere. That
layer has merged, and the shape of the answer changed with it: a single sentence about a whole
photograph became a list of people, each with three separate decisions and a withdrawal that
reaches forward. What follows is the policy that reads those facts, and the reasoning is here
rather than at the call site because there is exactly one call site and there must stay one.

**What is now known, and it is more than before.** ``exulanica.graph.person_regions`` resolves,
per photograph, the live person regions and the state each of them is in, and
``review_states_for_captures`` says whether anybody has looked at that photograph for people at
all. Those are different facts and the second is the one default deny turns on: a photograph with
no person-region row is ``unscreened``, which means nobody looked, not that nobody is there.

**What is still not known, and it is why the release state did not move.** The World Read bundle
carries no per-person fact. A recipient holding the bundle can see how many photographs were
screened and how many people are recorded in them; they cannot see any individual person's state,
so they cannot check a claim that every pictured person consented. A release state more permissive
than ``internal_only`` would be a claim its own recipient could not verify from the bytes they
hold, which is the failure this bundle exists to prevent. ``internal_only`` is therefore still the
answer, but it is now computed from the scene rather than asserted, and it says which of the three
consents is unestablished and why.

**Why none of this reads the clock.** ``person_consent_is_granted`` in migration 0037 filters on
``clock_timestamp()`` against ``effective_at`` and ``valid_until``, so a person's resolved state
can change between two reads with no write in between. ``release`` is inside ``recorded_keys`` and
therefore inside both digests. A digest that moved because a consent expired would be a digest
nobody could quote, so nothing here reads a resolved person state. The two facts it does read,
whether a photograph has been screened and how many live regions it carries, are existence
queries with no time predicate. The rule is short enough to state: **the recorded digest may not
depend on the clock**, and keeping the resolved states out of the bundle is how that is kept.

**Why the policy version is the one part of the database's own predicate that may be reported.**
``privacy_screening_allows_capture`` in migration 0037 is a conjunction, and its terms do not all
behave the same way under the rule above. ``s.policy_version = current_privacy_policy()`` compares
against a function declared ``immutable`` that returns a literal, verified in the migration text
and live (``pg_proc.provolatile = 'i'``), so it can only change when a migration writes a new
version. Its neighbours ``s.valid_until > clock_timestamp()`` and ``a.valid_until >
clock_timestamp()`` are exactly the shape the rule forbids. So ``screening`` reports whether the
receipt was written under the policy in force and does not claim the database accepts it, because
half of that predicate cannot be put inside a digest. One consequence is worth stating rather than
discovering: a migration that bumps ``current_privacy_policy()`` moves the recorded digest of
every bundle. That is a write and not a tick, so the rule holds, but it is a new way for the
digest to move.

**The basis is per photograph, not a module constant.** ``CONSENT_BASIS``'s first version carried
a comment demanding that a later basis be a new value rather than a silent change of meaning under
the same name. It is now two values, and which one applies depends on whether that photograph has
person regions at all. A capture nobody screened rests on the screening receipt alone, exactly as
before, and saying otherwise would be the same overstatement in a new place.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any, Final, Literal

import psycopg

from exulanica.graph.person_regions import review_states_for_captures

__all__ = [
    "PERSON_RECEIPT_BASIS",
    "SCREENING_BASIS",
    "consent_for_captures",
    "person_consent_state",
    "release_state",
    "scene_consent_basis",
]

#: What a photograph with no located people rests on: one named human's statement about the whole
#: frame. Unchanged in meaning and in spelling, so a record written before the person layer landed
#: still says what it said.
SCREENING_BASIS: Final = "human-screening-receipt"

#: What a photograph with located people rests on: that same statement AND the per-person receipts.
#: A new value rather than a redefinition of the one above, which is what the original comment on
#: the single constant asked for. It is deliberately additive: the screening receipt does not stop
#: being the gate when regions appear, it stops being the whole of it.
PERSON_RECEIPT_BASIS: Final = "human-screening-receipt+person-presentation-receipts"

#: What a photograph's per-person record can say, and none of these is a consent. ``unscreened``
#: means nobody has looked for people in it. ``recorded`` means people are located and each has
#: decisions on file, whose resolved states are evaluated at read time and are deliberately not
#: carried here; see the module docstring on the clock.
PersonConsentState = Literal["unscreened", "recorded"]

_SCREENINGS: Final = """
select distinct on (s.capture_id)
       s.capture_id,
       s.screening_method,
       s.eligibility_state,
       s.human_review_required,
       s.reviewed_by is not null as reviewed_by_a_named_actor,
       jsonb_array_length(s.sensitive_regions) as sensitive_region_count,
       s.policy_version,
       encode(s.receipt_digest, 'hex') as receipt_digest
  from reconstruction_privacy_screening s
 where s.workspace_id = %s
   and s.capture_id = any(%s)
 order by s.capture_id, s.screened_at desc, s.screening_id desc
"""

#: The policy a receipt has to have been written under to still count, asked of the database rather
#: than imported from :data:`exulanica.ingest.privacy.PRIVACY_POLICY_VERSION`. The question this
#: record answers is what the DATABASE demands of a receipt, and if the Python constant ever drifts
#: from the SQL function, a bundle that read the constant would report the drift as agreement.
#: Migration 0037 made this a function rather than a literal inside the resolver for exactly that
#: reason: one place to move it, one place to compare against.
_POLICY_IN_FORCE: Final = "select current_privacy_policy() as policy"


def consent_for_captures(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    capture_ids: list[uuid.UUID],
) -> dict[str, dict[str, Any]]:
    """Report, per capture, what is actually known about showing it.

    Returns a mapping from capture id string to a canonical-JSON-safe record. Every requested
    capture appears in the result, because a caller that had to distinguish "absent from the
    mapping" from "screened and eligible" would eventually get it wrong in the permissive
    direction.

    The person half is an existence query, not a resolution: it says whether anybody has looked at
    this photograph for people, and how many live regions that looking left. It deliberately does
    not say what any of them agreed to. Two reasons, and both are load bearing. The resolved state
    is clock-dependent and this record is inside a digest (see the module docstring). And a state
    per person belongs beside that person's outline, which is the graph payload's job and not this
    one; duplicating it here would be the second implementation of the presentation rule that
    ``person_regions`` warns against, and the direction two implementations drift is a person shown
    who should not have been.

    The screening half reports two facts that used to be one. ``eligibility`` is what the receipt
    says, unchanged and never rewritten here. ``under_current_policy`` is whether that receipt was
    written under the policy the database now demands, which is a term of
    ``privacy_screening_allows_capture`` and, before this, the one the bundle silently assumed.
    MEASURED 2026-09-07 against the retained ``public`` schema, by the query in the test named
    for this: of the 283 captures whose newest receipt is retained, 281 say ``eligible`` while the
    database refuses geometry for them on the policy version alone, and NONE is both eligible and
    current. Every one of those 281 was published here as screened and eligible, which is a bundle
    contradicting its own database.
    """
    rows: dict[uuid.UUID, dict[str, Any]] = {}
    policy_in_force: str | None = None
    if capture_ids:
        for row in connection.execute(_SCREENINGS, (workspace, capture_ids)).fetchall():
            rows[row["capture_id"]] = row
        # No try/except and no default. If `current_privacy_policy()` is missing this must raise,
        # because every fallback available here is the permissive one: a bundle that guessed the
        # policy would report a superseded receipt as current on the strength of the guess.
        in_force = connection.execute(_POLICY_IN_FORCE).fetchone()
        assert in_force is not None
        policy_in_force = in_force["policy"]

    # One query for the whole member set, matching the shape of the screening query above rather
    # than asking once per capture.
    reviewed = review_states_for_captures(connection, workspace, capture_ids)
    people = _live_region_counts(connection, workspace, capture_ids)

    result: dict[str, dict[str, Any]] = {}
    for capture_id in capture_ids:
        row = rows.get(capture_id)
        if row is None:
            screening: dict[str, Any] = {
                "state": "unscreened",
                "method": None,
                "eligibility": None,
                "named_human_reviewer": False,
                "sensitive_region_count": None,
                "policy_version": None,
                "receipt_digest": None,
                "policy_in_force": policy_in_force,
                # No receipt is not a current receipt. The restrictive value is the default here
                # for the same reason every requested capture appears in this mapping at all.
                "under_current_policy": False,
                "policy_reason": (
                    "no screening receipt exists for this photograph, so there is nothing for "
                    "the policy in force to accept"
                ),
            }
        else:
            current = row["policy_version"] == policy_in_force
            screening = {
                "state": "screened",
                "method": row["screening_method"],
                # Never rewritten from the policy check beside it. What the receipt says and
                # whether the receipt is still accepted are two facts, and a reader that collapsed
                # them would be making the same coarse statement this layer exists to retire.
                "eligibility": row["eligibility_state"],
                "named_human_reviewer": bool(row["reviewed_by_a_named_actor"]),
                "sensitive_region_count": int(row["sensitive_region_count"]),
                "policy_version": row["policy_version"],
                "receipt_digest": row["receipt_digest"],
                "policy_in_force": policy_in_force,
                "under_current_policy": current,
                "policy_reason": _policy_reason(row["policy_version"], policy_in_force, current),
            }
        key = str(capture_id)
        person_state: PersonConsentState = (
            "recorded" if reviewed.get(key) == "screened" else "unscreened"
        )
        result[key] = {
            "basis": PERSON_RECEIPT_BASIS if person_state == "recorded" else SCREENING_BASIS,
            "screening": screening,
            # Still never an empty list of people, and now for a sharper reason than before: the
            # two answers are "nobody has looked" and "people are located", and neither of them is
            # "there is nobody here". A count of zero under `recorded` means every proposed region
            # was reviewed away as a false positive, which is a reviewed statement; absence of a
            # row is not.
            "person_consent": person_state,
            "recorded_person_count": people.get(key, 0),
            "person_consent_reason": (
                "People are located in this photograph and each carries presentation receipts. "
                "Their resolved states are evaluated at read time and are not carried here, "
                "because this record is inside the bundle digest and a resolved state expires "
                "with the clock."
                if person_state == "recorded"
                else "Nobody has screened this photograph for people. That is not a statement "
                "that there is nobody in it."
            ),
        }
    return result


#: Said in both branches of :func:`_policy_reason`, because a reader who saw it only on the
#: superseded branch would read ``under_current_policy: true`` as "the database allows this", which
#: is the permissive misreading. The three terms named here are real terms of
#: ``privacy_screening_allows_capture`` and none of them is reported.
_NOT_THE_WHOLE_PREDICATE: Final = (
    "Being current under the policy is necessary and not sufficient: the receipt's validity "
    "window, its authorization's window and any tombstone are also terms of "
    "privacy_screening_allows_capture, and they are deliberately not reported here because they "
    "move with the clock and this record is inside the bundle digest."
)


def _policy_reason(written_under: str, in_force: str | None, current: bool) -> str:
    """Whether the policy in force still accepts a receipt written under ``written_under``.

    Named for the half of the database's predicate it actually checks. The other half is stated as
    absent rather than left out, because a field called something like ``allowed`` would be read as
    the whole predicate and would be wrong for any receipt whose authorization had expired.
    """
    if current:
        return (
            f"this receipt was written under {written_under}, which is the policy in force. "
            f"{_NOT_THE_WHOLE_PREDICATE}"
        )
    return (
        f"this receipt says what it said and nothing here rewrites it, but it was written under "
        f"{written_under} while the policy in force is {in_force}, so "
        f"privacy_screening_allows_capture refuses geometry on it until this photograph is "
        f"screened again. {_NOT_THE_WHOLE_PREDICATE}"
    )


def _live_region_counts(
    connection: psycopg.Connection, workspace: uuid.UUID, capture_ids: list[uuid.UUID]
) -> dict[str, int]:
    """How many live person regions each photograph carries.

    A count rather than the regions themselves, and no consent predicate anywhere in it, so the
    answer is a function of the rows alone and not of the moment it was asked.
    """
    if not capture_ids:
        return {}
    rows = connection.execute(
        "select capture_id, count(*) as live from person_region_current "
        "where workspace_id = %s and capture_id = any(%s) and action <> 'deleted' "
        "group by capture_id",
        (workspace, list(capture_ids)),
    ).fetchall()
    return {str(row["capture_id"]): int(row["live"]) for row in rows}


#: The per-capture records this module produced, keyed by capture id string. Every scene-level
#: answer below is a fold over exactly these, and that is a deliberate constraint rather than a
#: convenience: it is the same mapping the bundle publishes under ``consent.per_capture``, so a
#: recipient can recompute every count in the release block from the bytes they were handed. An
#: answer derived from anything the bundle does not carry would be one they had to take on trust.
#:
#: It also removes a contradiction that a scene-row-derived answer would have created. On the four
#: paths where ``reconstruction_scenes._fallback`` is reached, a member's ``person_review_state`` is
#: hard-set to ``unscreened`` whatever the database says, so folding over the members would let a
#: bundle report no people while its own per-capture records reported some.
CaptureConsent = Mapping[str, dict[str, Any]]


def person_consent_state(consent: CaptureConsent) -> PersonConsentState:
    """The one symbol a caller should branch on, for a whole scene.

    It used to answer a different question under this name: whether the build contained a person
    layer at all. That question stopped being interesting the day the layer merged, and leaving it
    would have been worse than uninteresting, because the value it returned was drawn from a
    different vocabulary than the per-capture records beside it. A bundle whose scene-level field
    said ``available`` while every capture in it said ``unavailable`` contradicted itself under one
    word. Both now describe photographs, and the scene is the weakest of its members: one
    photograph nobody screened is enough to make the scene unscreened.
    """
    if not consent:
        return "unscreened"
    if all(record["person_consent"] == "recorded" for record in consent.values()):
        return "recorded"
    return "unscreened"


def scene_consent_basis(consent: CaptureConsent) -> str:
    """What the scene's consent answer rests on, which is the weakest of its members' bases."""
    return PERSON_RECEIPT_BASIS if person_consent_state(consent) == "recorded" else SCREENING_BASIS


#: The release ladder, least to most revealed. Only the first is reachable today and the block on
#: each of the others is stated in the bundle rather than left in a design note, because a
#: vocabulary whose unreachable half is undocumented gets reinvented by the next caller who needs
#: it. ``undecidable`` is deliberately NOT in this list: a scene nobody screened permits exactly
#: what ``internal_only`` permits, and a state that changes no permission is vocabulary a consumer
#: has to learn for nothing. What varies per scene is the reason, and the reason has its own keys.
ReleaseState = Literal["internal_only", "releasable_masked", "releasable"]


def release_state(consent: CaptureConsent) -> dict[str, Any]:
    """What the consent basis permits for this scene, stated rather than left to the reader.

    Computed from the members rather than returned as a constant, and computed from the ones
    already in the caller's hand rather than from a second read. That matters beyond cost: the
    scene row's person fields and this answer must come from the same read of the same rows, or a
    bundle could report people its own release state had not counted.

    ``internal_only`` is still the answer for every scene, and the reason it is not a placeholder
    is that it is now derived from two facts that vary. What changed is that the bundle says which
    of the three consents is unestablished and why, so the next person to look can tell a scene
    nobody has screened from a scene fully screened whose people this bundle cannot describe.
    Those are different distances from a release and the old constant collapsed them.

    **Why not a per-scene gradient yet.** ``releasable_masked`` would have to prove that the
    geometry *this bundle offers* descends from the masked derivatives. Nothing in the bundle
    records which source derivative a point map or a SOG was built from; the geometry entries carry
    the digest of the artifact produced, not of the bytes read to produce it. Until they do, a
    scene could satisfy every consent and the claim would still be uncheckable by its recipient.
    That is recorded in ``not_yet_earnable`` rather than in a comment, because it is the recipient
    who needs to know it.
    """
    total = len(consent)
    screened = sum(1 for record in consent.values() if record["person_consent"] == "recorded")
    recorded_people = sum(int(record["recorded_person_count"]) for record in consent.values())
    unscreened = total - screened

    if unscreened:
        # Default deny, and it reaches the whole scene rather than the photograph it came from: a
        # release is a statement about the material handed over, and one unexamined photograph in
        # it is enough to make that statement unsupported.
        why = (
            f"{unscreened} of {total} photographs in this scene have not been screened for "
            "people, so no decision about anybody in them exists to report"
        )
    else:
        why = (
            f"all {total} photographs have been screened and {recorded_people} people are "
            "recorded, but this bundle carries no per-person state, so a recipient holding it "
            "cannot check that any of them agreed"
        )

    return {
        "state": "internal_only",
        "basis": scene_consent_basis(consent),
        # The three consents from `exulanica.consent.states`, kept apart here for the same reason
        # they are kept apart there: granting one grants nothing else, and a single boolean over
        # all three is the yes-or-no gate this layer exists to replace.
        "scopes": {
            "presence": {"established": False, "reason": why},
            "naming": {"established": False, "reason": why},
            "likeness": {"established": False, "reason": why},
        },
        # Not a fourth consent, and it is here so a recipient cannot read the three above as the
        # whole of the rule. A withdrawal reaches forward and no later receipt undoes it.
        "withdrawal": {
            "honoured": True,
            "meaning": (
                "a withdrawn person is masked and their derived artifacts are purged through the "
                "existing withdrawal path; a consent recorded afterwards does not restore them"
            ),
        },
        # Counted, so the two sentences above are checkable against the bundle rather than taken
        # on trust. Every one of these is an existence count with no time predicate behind it.
        "people": {
            "photographs": total,
            "screened_for_people": screened,
            "recorded_people": recorded_people,
        },
        "permits": [
            "reading inside the owning workspace by an authenticated session",
        ],
        "does_not_establish": [
            "that any pictured person consented to their likeness being shown",
            "that any pictured person consented to being named",
            "that this material may be released to a third party",
            "that this material may be used to train a model",
        ],
        "not_yet_earnable": {
            "releasable_masked": (
                "the geometry entries record the digest of the artifact produced, not of the "
                "source derivative read to produce it, so a recipient cannot check that what "
                "they were handed descends from the masked images"
            ),
            "releasable": (
                "no per-person state is carried in this bundle. Adding it means putting a "
                "clock-dependent value inside recorded_keys, because a presentation consent "
                "expires against clock_timestamp(), and the recorded digest may not depend on "
                "the clock"
            ),
        },
        "blocked_until": (
            "the bundle carries a state per person that a recipient can check, and the geometry "
            "entries name the source derivative they were built from "
            "(docs/person-presentation-consent.md, docs/phase-10-tickets.md P10-5)"
        ),
    }
