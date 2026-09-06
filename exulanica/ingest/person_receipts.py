"""The immutable records behind a person region, a consent transition and a masked derivative.

Every function here returns a plain dictionary of integers, strings, booleans and nulls, so
``canonical_json`` accepts it and its digest is the same on every machine and in every language
that later reads an Exulanica package. That is not decoration: a consent receipt whose digest
depended on the reader is a receipt nobody can verify offline, and the design note requires a
verifier that enforces the current state without this database.

**The two digests that make a consent change a new build.** ``region_set_digest`` covers the
confirmed regions on one photograph and ``consent_state_digest`` covers the states in force over
them. Both enter the ``masked_source`` stage's input digest, which enters the depth stage's, which
enters the scene build inputs. So revoking a consent moves a chain of keys and produces a new
build, and no existing artifact is ever mutated to match a decision made after it. That property
is inherited from the existing key rules rather than added by a new mechanism.

**Sorted by region key, everywhere.** A worker resolving regions in a different order must reach
the same digest, so every list here is ordered by the region key rather than by whatever the
database returned.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping, Sequence
from typing import Any, Final

from exulanica.canonical import canonical_json, sha256_of_canonical
from exulanica.consent.regions import DetectedPerson, Silhouette
from exulanica.consent.states import CONSENT_SCOPES, ResolvedPresentation

__all__ = [
    "CONSENT_NAMESPACE",
    "MASKED_SOURCE_NAMESPACE",
    "REGION_EDIT_NAMESPACE",
    "SUBJECT_NAMESPACE",
    "consent_receipt",
    "consent_state_digest",
    "masked_source_manifest",
    "person_region_list",
    "region_edit_receipt",
    "region_set_digest",
]

#: Frozen once, as ``uuid5(NAMESPACE_URL, "https://exulanica.local/ns/<name>")``. Changing one
#: orphans every row already minted under it, exactly as the artifact namespace does.
SUBJECT_NAMESPACE: Final = uuid.UUID("5c3d0225-6115-5872-b2fd-b3c99d2c3920")
REGION_EDIT_NAMESPACE: Final = uuid.UUID("56e16ea0-98f0-5e61-8807-4e9a5ced571c")
CONSENT_NAMESPACE: Final = uuid.UUID("b0b08e61-d306-55c1-b024-de2c89ebc350")
MASKED_SOURCE_NAMESPACE: Final = uuid.UUID("e9c9657e-eb24-54ac-b946-1d4c4e86773e")

_REGION_EDIT_ACTIONS: Final = frozenset({"detected", "confirmed", "added", "deleted"})
_ACTOR_ROLES: Final = frozenset({"owner", "subject", "operator"})
_DECISIONS: Final = frozenset({"granted", "revoked", "withdrawn"})


def _iso(value: dt.datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("a person receipt time must include a UTC offset")
    return value.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")


def person_region_list(
    *,
    source_sha256: str,
    detector_id: str,
    stage_version: int,
    detections: Sequence[tuple[bytes, DetectedPerson]],
    unlocated_people: int,
) -> dict[str, Any]:
    """What one detector proposed for one photograph, before any human looked at it.

    ``confirmed_by`` is null on every entry and stays null until a person edits it. That is the
    default-deny shape of the artifact itself: nothing a detector produced is a decision.
    """
    return {
        "profile": "exulanica.person-region-list/v1",
        "source_sha256": source_sha256,
        "detector_id": detector_id,
        "stage_version": stage_version,
        "unlocated_people": unlocated_people,
        "regions": [
            {
                "region_key": key.hex(),
                "shape": found.shape,
                "confidence": found.confidence,
                "silhouette": found.silhouette.as_digest_input(),
                "confirmed_by": None,
            }
            for key, found in sorted(detections, key=lambda pair: pair[0])
        ],
    }


def region_edit_receipt(
    *,
    workspace_id: uuid.UUID,
    capture_id: uuid.UUID,
    source_sha256: str,
    region_key: bytes,
    sequence: int,
    action: str,
    shape: str,
    silhouette: Silhouette,
    subject_id: uuid.UUID | None,
    actor: uuid.UUID | None,
    detector_id: str | None,
    confidence: str | None,
    recorded_at: dt.datetime,
) -> tuple[uuid.UUID, dict[str, Any], bytes, bytes]:
    """One edit to one region: what changed, who changed it, and when.

    A reviewer confirming, adding or deleting a region produces one of these, so the review screen
    that replaces the old free-text statement leaves a trail rather than a checkbox.
    """
    if action not in _REGION_EDIT_ACTIONS:
        raise ValueError(f"{action!r} is not one of {sorted(_REGION_EDIT_ACTIONS)}")
    if action == "detected" and actor is not None:
        raise ValueError("a detection is not somebody's decision and may not name an actor")
    if action != "detected" and actor is None:
        raise ValueError("a region edit is a human decision and must name the human who made it")
    record = {
        "profile": "exulanica.person-region-edit/v1",
        "capture_id": str(capture_id),
        "source_sha256": source_sha256,
        "region_key": region_key.hex(),
        "sequence": sequence,
        "action": action,
        "shape": shape,
        "silhouette": silhouette.as_digest_input(),
        "subject_id": str(subject_id) if subject_id else None,
        "detector_id": detector_id,
        "confidence": confidence,
        "confirmed_by": str(actor) if actor else None,
        "recorded_at": _iso(recorded_at),
    }
    digest = sha256_of_canonical(record)
    edit_id = uuid.uuid5(
        REGION_EDIT_NAMESPACE, f"{workspace_id}:{capture_id}:{region_key.hex()}:{digest.hex()}"
    )
    return edit_id, record, canonical_json(record), digest


def consent_receipt(
    *,
    workspace_id: uuid.UUID,
    subject_id: uuid.UUID,
    region_key: bytes | None,
    consent_scope: str,
    decision: str,
    sequence: int,
    actor: uuid.UUID,
    actor_role: str,
    effective_at: dt.datetime,
    valid_until: dt.datetime | None = None,
) -> tuple[uuid.UUID, dict[str, Any], bytes, bytes]:
    """One consent transition, with the actor, the time and the scope the design note requires.

    ``actor_role`` distinguishes a decision the account holder made from one the person in the
    photograph made about themselves. No route writes ``'subject'`` yet; the field exists so that
    adding the subject-facing link later is a route rather than a schema change, and so that a
    receipt written today does not silently claim to be the subject's own decision.
    """
    if consent_scope not in CONSENT_SCOPES:
        raise ValueError(f"{consent_scope!r} is not one of {sorted(CONSENT_SCOPES)}")
    if decision not in _DECISIONS:
        raise ValueError(f"{decision!r} is not one of {sorted(_DECISIONS)}")
    if actor_role not in _ACTOR_ROLES:
        raise ValueError(f"{actor_role!r} is not one of {sorted(_ACTOR_ROLES)}")
    if decision == "withdrawn" and consent_scope != "likeness":
        raise ValueError("withdrawal is recorded against likeness, the consent that reaches pixels")
    record = {
        "profile": "exulanica.person-presentation-consent/v1",
        "subject_id": str(subject_id),
        "region_key": region_key.hex() if region_key else None,
        "consent_scope": consent_scope,
        "decision": decision,
        "sequence": sequence,
        "actor_id": str(actor),
        "actor_role": actor_role,
        "effective_at": _iso(effective_at),
        "valid_until": _iso(valid_until) if valid_until else None,
    }
    digest = sha256_of_canonical(record)
    consent_id = uuid.uuid5(CONSENT_NAMESPACE, f"{workspace_id}:{subject_id}:{digest.hex()}")
    return consent_id, record, canonical_json(record), digest


def region_set_digest(
    *, capture_id: uuid.UUID, source_sha256: str, regions: Mapping[bytes, Silhouette]
) -> bytes:
    """The confirmed regions on one photograph, as a digest the mask can be keyed on."""
    return sha256_of_canonical(
        {
            "profile": "exulanica.person-region-set/v1",
            "capture_id": str(capture_id),
            "source_sha256": source_sha256,
            "regions": [
                {"region_key": key.hex(), "silhouette": regions[key].as_digest_input()}
                for key in sorted(regions)
            ],
        }
    )


def consent_state_digest(
    *,
    capture_id: uuid.UUID,
    source_sha256: str,
    resolved: Mapping[bytes, ResolvedPresentation],
) -> bytes:
    """The states in force over one photograph's regions, as a digest.

    Separate from :func:`region_set_digest` because the two change for different reasons: a
    reviewer corrects an outline, a person changes their mind. Both must move the masked
    derivative's key, and keeping them apart says which one did.
    """
    return sha256_of_canonical(
        {
            "profile": "exulanica.person-consent-state/v1",
            "capture_id": str(capture_id),
            "source_sha256": source_sha256,
            "states": [
                {
                    "region_key": key.hex(),
                    "state": resolved[key].state,
                    "masked": resolved[key].masked,
                    "name_permitted": resolved[key].name_permitted,
                }
                for key in sorted(resolved)
            ],
        }
    )


def masked_source_manifest(
    *,
    workspace_id: uuid.UUID,
    capture_id: uuid.UUID,
    source_sha256: str,
    masked_sha256: str,
    stage_version: int,
    dilation_millionths: int,
    masks: Sequence[tuple[bytes, uuid.UUID | None, str]],
) -> tuple[uuid.UUID, dict[str, Any], bytes, bytes]:
    """Which person each mask belongs to, bound to the exact derivative bytes.

    The design note asks for the manifest by name, and this is why it is not optional: without it
    a masked photograph is a picture with grey shapes on it and nothing records whose they were,
    so a later withdrawal could not find the derivative it needs to purge.
    """
    record = {
        "profile": "exulanica.masked-source-manifest/v1",
        "capture_id": str(capture_id),
        "source_sha256": source_sha256,
        "masked_sha256": masked_sha256,
        "stage_version": stage_version,
        "dilation_millionths": dilation_millionths,
        "fill": "neutral-flat",
        "generative_fill": False,
        "masks": [
            {
                "region_key": key.hex(),
                "subject_id": str(subject) if subject else None,
                "state": state,
            }
            for key, subject, state in sorted(masks, key=lambda item: item[0])
        ],
    }
    digest = sha256_of_canonical(record)
    manifest_id = uuid.uuid5(MASKED_SOURCE_NAMESPACE, f"{workspace_id}:{capture_id}:{digest.hex()}")
    return manifest_id, record, canonical_json(record), digest
