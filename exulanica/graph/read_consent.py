"""The one place the World Read API asks whether a photograph may be shown.

This module exists to be replaced. The person-region and presentation-consent layer
(``docs/person-presentation-consent.md``) is being built on its own branch; when it merges, the
body of :func:`consent_for_captures` delegates to it and nothing else in the read path changes.
Isolating that single call is the whole point: a read API that has to be retrofitted with a consent
check is a read API that shipped without one.

What can honestly be said today is narrow. The only durable per-photograph privacy fact in this
tree is the screening receipt from migration 0029: a named human, or a synthetic exemption, stating
that a capture carries no visible people or sensitive regions, with an eligibility verdict and a
policy digest. That is a real receipt and this module reports it. It is also, as
``docs/person-presentation-consent.md`` records, too coarse to be a consent state: the reviewer of
the retained bowl collection stated no visible people, and the frames contain the arms, hands and
clothing of diners at the edges. One statement about a whole photograph cannot carry three separate
decisions about each person in it.

So the answer this module gives has two parts that must not be collapsed into one. ``screening``
is what the receipt says. ``person_consent`` is ``"unavailable"``, meaning no per-person decision
exists to report, which is a different fact from "there is nobody here". Reporting an empty list of
people would be exactly the confusion that made the 2026-09-05 screening statement too coarse, and
a consumer that read absence as permission would be reading a fact the system never established.

Default deny follows from that: while ``person_consent`` is ``"unavailable"``, no bundle built on
this module may be released to a third party, and :func:`release_state` says so rather than leaving
the caller to infer it.
"""

from __future__ import annotations

import uuid
from typing import Any, Final, Literal

import psycopg

__all__ = [
    "CONSENT_BASIS",
    "PERSON_CONSENT_AVAILABLE",
    "consent_for_captures",
    "release_state",
]

#: What the current answer rests on. A string rather than a boolean so a later basis, such as the
#: per-person receipts, is a new value rather than a silent change of meaning under the same name.
CONSENT_BASIS: Final = "human-screening-receipt"


def _person_consent_layer_is_present() -> bool:
    """Whether the per-person presentation-consent layer exists in this tree.

    **Detected, not declared, and the first version's hand-set ``False`` was an inert tripwire.**
    That constant lived only on this branch, so the branch actually building the consent layer had
    no reason to touch it: the layer could merge in full and this module would go on reporting that
    it was absent, and the test pinning the value would go on passing. A tripwire nobody has to
    disarm is not a tripwire.

    Importing the module is the detection because ``exulanica.graph.person_regions`` is that
    layer's own read seam. Its arrival is the event this needs to notice, and it cannot arrive
    without arriving here.
    """
    try:
        import exulanica.graph.person_regions  # noqa: F401
    except ImportError:
        return False
    return True


#: Whether a per-person consent layer is present, resolved once at import.
PERSON_CONSENT_AVAILABLE: Final = _person_consent_layer_is_present()

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
    """
    rows: dict[uuid.UUID, dict[str, Any]] = {}
    if capture_ids:
        for row in connection.execute(_SCREENINGS, (workspace, capture_ids)).fetchall():
            rows[row["capture_id"]] = row

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
            }
        else:
            screening = {
                "state": "screened",
                "method": row["screening_method"],
                "eligibility": row["eligibility_state"],
                "named_human_reviewer": bool(row["reviewed_by_a_named_actor"]),
                "sensitive_region_count": int(row["sensitive_region_count"]),
                "policy_version": row["policy_version"],
                "receipt_digest": row["receipt_digest"],
            }
        result[str(capture_id)] = {
            "basis": CONSENT_BASIS,
            "screening": screening,
            # Deliberately not an empty list. No per-person decision exists to report, and an
            # empty list of people would read as "nobody is in this photograph".
            "person_consent": "unavailable",
            "person_consent_reason": (
                "No per-person presentation consent layer is present in this build. A screening "
                "receipt states that a whole photograph was reviewed; it does not record a "
                "decision about any individual person in it."
            ),
        }
    return result


def release_state() -> dict[str, Any]:
    """What the consent basis permits, stated rather than left to the reader.

    ``internal_only`` is not a placeholder for a value that will be filled in later by the same
    code. It is the correct answer while no per-person consent exists, and Phase 10 capability 5
    states the rule it enforces: no third party sees an export before that layer lands.
    """
    if PERSON_CONSENT_AVAILABLE:  # pragma: no cover - flipped by the person-consent branch
        raise NotImplementedError(
            "the per-person consent layer is present; release_state must be decided from the "
            "per-person receipts rather than from the screening receipt alone"
        )
    return {
        "state": "internal_only",
        "basis": CONSENT_BASIS,
        "permits": [
            "reading inside the owning workspace by an authenticated session",
        ],
        "does_not_establish": [
            "that any pictured person consented to their likeness being shown",
            "that any pictured person consented to being named",
            "that this material may be released to a third party",
            "that this material may be used to train a model",
        ],
        "blocked_until": (
            "the person-region and presentation-consent layer records a state per person "
            "(docs/person-presentation-consent.md)"
        ),
    }


def person_consent_state() -> Literal["unavailable", "available"]:
    """The one symbol a caller should branch on, so the branch appears in exactly one place."""
    return "available" if PERSON_CONSENT_AVAILABLE else "unavailable"
