"""Pure checks for an invitation's public words and absolute expiration.

Expiration is compared to an explicit server instant, supplied by the transaction that issues
or opens the grant. No client clock or simulation tick participates in access decisions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from exulanica.canonical import sha256_of_canonical
from exulanica.things.lines import check_line

WORLD_WORDS_MAXIMUM = 80
PROFILE = "exulanica.world-grant/v1"
ROLE = {
    "profile": "exulanica.participation-role/v1",
    "key": "observer",
    "permissions": ["world.enter"],
    "actions": ["world.observe", "world.leave"],
    "may_speak": False,
    "may_act": False,
}
NOTICE = {
    "profile": "exulanica.participation-notice/v1",
    "key": "observe-a-world",
    "words": (
        "This invitation lets you observe one world. Some beings may be run by AI models. "
        "You cannot control beings, speak, edit the world or spend its owner's model budget. "
        "You may leave permanently at any time. The owner may end this invitation."
    ),
}


def role_reference() -> dict:
    return {"key": ROLE["key"], "version": 1, "sha256": sha256_of_canonical(ROLE).hex()}


def notice_reference() -> dict:
    return {"key": NOTICE["key"], "version": 1, "sha256": sha256_of_canonical(NOTICE).hex()}


def public_world_words(value: object) -> str:
    """An invitation's plain public line; saved-name screening is the issuing boundary's."""
    return check_line(value, maximum=WORLD_WORDS_MAXIMUM)


def utc_instant(value: datetime) -> datetime:
    """An unambiguous instant, refusing naive wall-clock values."""
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("an invitation's time includes its UTC offset")
    return value.astimezone(UTC)


def not_expired(expires_at: datetime, *, now: datetime) -> bool:
    """Expiration is exclusive: authority ends at the stated instant itself."""
    return utc_instant(now) < utc_instant(expires_at)


def issue_expiry(expires_at: datetime, *, now: datetime) -> datetime:
    """A future expiry normalized to UTC, or a refusal before an invitation is issued."""
    expiry = utc_instant(expires_at)
    if not not_expired(expiry, now=now):
        raise ValueError("an invitation expires after the issuing instant")
    return expiry


def revision_document(grant: UUID, version: UUID, expires_at: datetime, world_words: str) -> dict:
    """The immutable observer grant. No free-form permission or speech input is accepted."""
    return {
        "profile": PROFILE,
        "grant_id": str(grant),
        "grant_seq": 1,
        "principal_kind": "person",
        "version_id": str(version),
        "expires_at": utc_instant(expires_at).isoformat(timespec="microseconds"),
        "world_words": public_world_words(world_words),
        "role": role_reference(),
        "notice": notice_reference(),
    }


def validate_revision(document: object) -> dict:
    """Stored authority is read against its exact supported role and notice, never defaults."""
    if not isinstance(document, dict):
        raise ValueError("an invitation revision is a document")
    try:
        expected = revision_document(
            UUID(document["grant_id"]),
            UUID(document["version_id"]),
            datetime.fromisoformat(document["expires_at"]),
            document["world_words"],
        )
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("an invitation revision is incomplete") from exc
    if document != expected:
        raise ValueError("an invitation revision names unsupported authority")
    return expected
