"""Training permission is an exact-term decision, independent of presentation consent."""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass
from typing import Any

from exulanica.canonical import canonical_json


def _time(value: dt.datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("training consent times must carry a UTC offset")
    return value.astimezone(dt.UTC).isoformat()


@dataclass(frozen=True, slots=True)
class TrainingTerms:
    package_id: str
    licensee: str
    model_classes: tuple[str, ...]
    valid_from: dt.datetime
    valid_until: dt.datetime
    terms_sha256: str

    def __post_init__(self) -> None:
        if not self.package_id.strip() or not self.licensee.strip():
            raise ValueError("training terms require a package and licensee")
        if not self.model_classes or any(not item.strip() for item in self.model_classes):
            raise ValueError("training terms require model classes")
        if tuple(sorted(set(self.model_classes))) != self.model_classes:
            raise ValueError("model classes must be sorted and unique")
        _time(self.valid_from)
        _time(self.valid_until)
        if self.valid_until <= self.valid_from:
            raise ValueError("training term must end after it starts")
        if len(self.terms_sha256) != 64 or any(
            c not in "0123456789abcdef" for c in self.terms_sha256
        ):
            raise ValueError("terms_sha256 must be a lowercase SHA-256 digest")

    def as_dict(self) -> dict[str, Any]:
        return {
            "package_id": self.package_id,
            "licensee": self.licensee,
            "model_classes": list(self.model_classes),
            "valid_from": _time(self.valid_from),
            "valid_until": _time(self.valid_until),
            "terms_sha256": self.terms_sha256,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> TrainingTerms:
        if not isinstance(value, dict):
            raise ValueError("training record must be an object")
        if set(value) != {
            "package_id",
            "licensee",
            "model_classes",
            "valid_from",
            "valid_until",
            "terms_sha256",
        }:
            raise ValueError("unexpected training terms fields")
        if (
            any(
                not isinstance(value[k], str)
                for k in ("package_id", "licensee", "valid_from", "valid_until", "terms_sha256")
            )
            or not isinstance(value["model_classes"], list)
            or any(not isinstance(x, str) for x in value["model_classes"])
        ):
            raise ValueError("invalid training terms field types")
        return cls(
            value["package_id"],
            value["licensee"],
            tuple(value["model_classes"]),
            dt.datetime.fromisoformat(value["valid_from"]),
            dt.datetime.fromisoformat(value["valid_until"]),
            value["terms_sha256"],
        )

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_json(self.as_dict())).hexdigest()


@dataclass(frozen=True, slots=True)
class TrainingReceipt:
    subject_id: str
    terms: TrainingTerms
    decision: str
    actor: str
    sequence: int
    decided_at: dt.datetime

    def __post_init__(self) -> None:
        if not self.subject_id.strip() or not self.actor.strip():
            raise ValueError("training receipt requires a subject and actor")
        if self.decision not in {"granted", "revoked", "withdrawn"}:
            raise ValueError("invalid training decision")
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValueError("training receipt sequence must be a nonnegative integer")
        _time(self.decided_at)

    def as_dict(self) -> dict[str, Any]:
        return {
            "subject_id": self.subject_id,
            "terms": self.terms.as_dict(),
            "decision": self.decision,
            "actor": self.actor,
            "sequence": self.sequence,
            "decided_at": _time(self.decided_at),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> TrainingReceipt:
        if not isinstance(value, dict):
            raise ValueError("training record must be an object")
        if set(value) != {"subject_id", "terms", "decision", "actor", "sequence", "decided_at"}:
            raise ValueError("unexpected training receipt fields")
        if (
            any(
                not isinstance(value[k], str)
                for k in ("subject_id", "decision", "actor", "decided_at")
            )
            or type(value["sequence"]) is not int
        ):
            raise ValueError("invalid training receipt field types")
        return cls(
            value["subject_id"],
            TrainingTerms.from_dict(value["terms"]),
            value["decision"],
            value["actor"],
            value["sequence"],
            dt.datetime.fromisoformat(value["decided_at"]),
        )

    @property
    def canonical(self) -> bytes:
        return canonical_json(self.as_dict())

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.canonical).hexdigest()


def training_is_granted(
    receipts: tuple[TrainingReceipt, ...],
    *,
    subject_id: str,
    terms: TrainingTerms,
    at: dt.datetime,
    withdrawn: bool = False,
) -> bool:
    """Withdrawal dominates the relationship; grants require exact, currently valid terms."""
    _time(at)
    if withdrawn or not terms.valid_from <= at < terms.valid_until:
        return False
    relevant = [
        r
        for r in receipts
        if r.subject_id == subject_id
        and r.terms.package_id == terms.package_id
        and r.terms.licensee == terms.licensee
        and r.decided_at <= at
    ]
    if any(r.decision == "withdrawn" for r in relevant):
        return False
    exact = [r for r in relevant if r.terms.digest == terms.digest]
    if not exact:
        return False
    # Reject ambiguous chains rather than allowing digest order to invent consent.
    if len({r.sequence for r in relevant}) != len(relevant):
        raise ValueError("training receipt chain has duplicate sequence numbers")
    return max(exact, key=lambda r: r.sequence).decision == "granted"
