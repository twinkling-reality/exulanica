"""The bucket check a process runs before its first request, every few minutes and before every
purge.

It refuses a bucket anyone can list, a bucket with object lock (locked versions cannot be erased), a
replication configuration (a replica is a copy no purge sees) and a lifecycle rule that expires or
moves current objects under the prefix. :class:`BucketGuard` holds the latest verdict for the
store in :mod:`exulanica.store.object`.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from exulanica.errors import ObjectStoreRefused, ObjectStoreUnavailable
from exulanica.store.object_requests import (
    _FORK_SENSITIVE,
    ObjectRequests,
    _child,
    _children,
    _document,
    _text,
)


@dataclass(frozen=True, slots=True)
class _Finding:
    """One reason the bucket cannot be trusted, and whether it also stops erasure."""

    code: str
    message: str
    blocks_erasure: bool


@dataclass(frozen=True, slots=True)
class BucketCheck:
    """What the bucket check found, as codes a readiness report can carry."""

    versioning: str
    object_lock: str
    replication: str
    lifecycle: str
    anonymous_listing: str
    anonymous_read: str
    findings: tuple[_Finding, ...] = ()

    def document(self) -> dict[str, Any]:
        return {
            "versioning": self.versioning,
            "object_lock": self.object_lock,
            "replication": self.replication,
            "lifecycle": self.lifecycle,
            "anonymous_listing": self.anonymous_listing,
            "anonymous_read": self.anonymous_read,
            "codes": [finding.code for finding in self.findings],
        }


def _moving_rules(document: bytes, prefix: str) -> list[str]:
    """Enabled lifecycle rules that expire or transition current objects this store may hold."""
    root = _document(document, "LifecycleConfiguration", "GET_BUCKET_LIFECYCLE")
    ours = f"{prefix}/" if prefix else ""
    moving = []
    for rule in _children(root, "Rule"):
        if _text(rule, "Status") != "Enabled":
            continue
        expiration = _child(rule, "Expiration")
        expires = expiration is not None and (
            _child(expiration, "Days") is not None or _child(expiration, "Date") is not None
        )
        if not expires and _child(rule, "Transition") is None:
            continue
        scope = _child(rule, "Filter")
        if scope is not None and (conjunction := _child(scope, "And")) is not None:
            scope = conjunction
        if scope is not None and _child(scope, "Tag") is not None:
            continue  # no object this store writes carries a tag
        rule_prefix = (_text(scope, "Prefix") if scope is not None else _text(rule, "Prefix")) or ""
        if ours.startswith(rule_prefix) or rule_prefix.startswith(ours):
            moving.append(_text(rule, "ID") or "(unnamed)")
    return moving


class BucketGuard:
    """Runs the bucket check before a process's first request, again every few minutes, and
    before every purge.

    Every finding is collected rather than the first one raised, so readiness shows the whole
    picture. A request refuses on any finding. A purge refuses only on a finding that makes
    erasure incomplete or impossible (an enabled object lock, a replication configuration, one
    that cannot be read), because deleting from a bucket that is wrongly public, or that a
    lifecycle rule expires, still removes the bytes. An unreachable endpoint is remembered for a
    few seconds, so callers waiting behind one check do not each wait out their own.
    """

    VERIFIED_SECONDS: Final = 300.0
    REFUSED_SECONDS: Final = 30.0
    UNAVAILABLE_SECONDS: Final = 5.0

    def __init__(
        self,
        requests: ObjectRequests,
        prefix: str,
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._requests = requests
        self._prefix = prefix
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._result: BucketCheck | None = None
        self._unavailable: str | None = None
        self._until = 0.0
        _FORK_SENSITIVE.add(self)

    def _reset_after_fork(self) -> None:
        self._lock = threading.Lock()

    def require(self, *, fresh: bool = False, erasing: bool = False) -> BucketCheck:
        with self._lock:
            now = self._monotonic()
            if fresh or now >= self._until:
                try:
                    checked = self._check()
                except ObjectStoreUnavailable as unavailable:
                    self._result, self._unavailable = None, str(unavailable)
                    self._until = now + self.UNAVAILABLE_SECONDS
                    raise
                self._result, self._unavailable = checked, None
                self._until = now + (
                    self.REFUSED_SECONDS if checked.findings else self.VERIFIED_SECONDS
                )
            elif self._unavailable is not None:
                raise ObjectStoreUnavailable("object_store_unreachable", self._unavailable)
            result = self._result
            assert result is not None
        blocking = [f for f in result.findings if f.blocks_erasure or not erasing]
        if blocking:
            raise ObjectStoreRefused(blocking[0].code, blocking[0].message)
        return result

    def describe(self) -> dict[str, Any]:
        with self._lock:
            if self._unavailable is not None:
                return {"state": "unreachable", "code": "object_store_unreachable"}
            if self._result is None:
                return {"state": "unchecked", "code": None}
            findings = self._result.findings
            return {
                "state": "refused" if findings else "verified",
                "code": findings[0].code if findings else None,
                **self._result.document(),
            }

    def _check(self) -> BucketCheck:
        requests = self._requests
        findings: list[_Finding] = []

        def unreadable(what: str, *, blocks_erasure: bool) -> None:
            findings.append(
                _Finding(
                    "object_store_bucket_unverified",
                    f"the bucket's {what} could not be read; the store's identity must be allowed "
                    "to read it",
                    blocks_erasure,
                )
            )

        state, body = requests.bucket_document("object-lock")
        # An identity may be refused this one read (some endpoints reserve it for an
        # administrator) without anything being unsafe: a lock shows up anyway, as a purge that
        # fails because a version remains, never as a purge reported complete. So an unreadable
        # lock is recorded, not refused.
        if state == "present":
            root = _document(body, "ObjectLockConfiguration", "GET_BUCKET_OBJECT_LOCK")
            if _text(root, "ObjectLockEnabled") == "Enabled":
                findings.append(
                    _Finding(
                        "object_store_object_lock_enabled",
                        "the bucket has object lock, so a locked version could not be erased",
                        True,
                    )
                )
        object_lock = {"not_exposed": "not_exposed", "denied": "unverified"}.get(state, "off")
        if object_lock == "off" and findings:
            object_lock = "enabled"

        state, body = requests.bucket_document("versioning")
        versioning = {"not_exposed": "not_exposed", "denied": "unverified"}.get(state, "off")
        if state == "denied":
            unreadable("versioning configuration", blocks_erasure=False)
        if state == "present":
            status = _text(
                _document(body, "VersioningConfiguration", "GET_BUCKET_VERSIONING"), "Status"
            )
            versioning = {"": "off", "Enabled": "enabled", "Suspended": "suspended"}.get(
                status or "", "unknown"
            )

        state, _ = requests.bucket_document("replication")
        replication = {"not_exposed": "not_exposed", "denied": "unverified"}.get(state, "off")
        if state == "denied":
            unreadable("replication configuration", blocks_erasure=True)
        if state == "present":
            replication = "configured"
            findings.append(
                _Finding(
                    "object_store_replication_configured",
                    "the bucket replicates objects, and a replica is a copy no purge here reaches",
                    True,
                )
            )

        state, body = requests.bucket_document("lifecycle")
        lifecycle = {"absent": "off", "not_exposed": "not_exposed", "denied": "unverified"}.get(
            state, "no_matching_rule"
        )
        if state == "denied":
            unreadable("lifecycle configuration", blocks_erasure=False)
        if state == "present" and (rules := _moving_rules(body, self._prefix)):
            lifecycle = "moves_content"
            findings.append(
                _Finding(
                    "object_store_lifecycle_moves_content",
                    f"lifecycle rule(s) {', '.join(rules)} expire or move current objects under "
                    "the store's prefix",
                    False,
                )
            )

        listing_prefix = f"{self._prefix}/" if self._prefix else ""
        anonymous_listing = "refused"
        if not requests.anonymous_listing_refused(listing_prefix):
            anonymous_listing = "allowed"
            findings.append(
                _Finding(
                    "object_store_publicly_listable",
                    "anyone can list the bucket, so the digests citations carry would open its "
                    "bytes",
                    False,
                )
            )
        # One stored object, read without credentials, must be refused too: a bucket policy can
        # open reads without opening listings.
        anonymous_read = "unchecked"
        sample = requests.list_page(listing_prefix, limit=1).keys
        if sample:
            anonymous_read = "refused"
            if not requests.anonymous_read_refused(sample[0][0]):
                anonymous_read = "allowed"
                findings.append(
                    _Finding(
                        "object_store_publicly_readable",
                        "anyone can read the bucket's objects, so a digest would open its bytes "
                        "without the application's checks",
                        False,
                    )
                )
        return BucketCheck(
            versioning,
            object_lock,
            replication,
            lifecycle,
            anonymous_listing,
            anonymous_read,
            tuple(findings),
        )
