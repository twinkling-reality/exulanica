"""Error types shared across the evidence spine and the content-addressed store.

Errors are separate classes rather than bare ValueError because several of them are
control-flow relevant: a worker treats TombstonedError as terminal, and the store treats
IntegrityError as a hard stop rather than a retry.
"""

from __future__ import annotations


class ExulanicaError(Exception):
    """Base class for every error raised by this package."""


class InvalidAddressError(ExulanicaError, ValueError):
    """An evidence address, or a component of one, is not well formed."""


class LossyAddressError(ExulanicaError):
    """Rendering this address to a URI would drop an input to its span digest.

    Raised rather than silently emitting a citation string that cannot be verified against
    the digest it claims to name. Pass allow_lossy=True to accept the loss explicitly.
    """


class CanonicalisationError(ExulanicaError, TypeError):
    """A value cannot be canonicalised deterministically, so it may not enter a digest."""


class IntegrityError(ExulanicaError):
    """Stored bytes do not hash to the key they are stored under."""


class BlobNotFoundError(ExulanicaError, KeyError):
    """No object exists in the store for this blob id."""


class ImmutableKeyError(ExulanicaError):
    """A write would change the content already stored at a content-addressed key.

    Under content addressing this can only mean a hash collision or a corrupted store, so it
    is never absorbed as an overwrite.
    """


class PurgeNotAuthorisedError(ExulanicaError):
    """A purge was attempted without a well formed authorisation."""


class ObjectStoreError(ExulanicaError):
    """An S3-compatible content store refused a request or could not be reached.

    ``code`` is a stable reason a caller or a readiness report can act on, for example
    ``object_store_unreachable`` or ``object_store_object_lock_enabled``. The message names the
    operation, the HTTP status, the store's own error code and the object key, and never a
    credential, a signature or a request header.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ObjectStoreUnavailable(ObjectStoreError, ConnectionError):
    """The endpoint could not be reached, or kept failing, within the retry bound.

    A ``ConnectionError``, so a caller that already treats a local ``OSError`` as a failed read
    or write treats this one the same way.
    """


class ObjectStoreRefused(ObjectStoreError):
    """The endpoint or the bucket refused, and retrying the same request will not change that."""


class ObjectStoreConfigurationError(ObjectStoreError, ValueError):
    """A store setting is missing or malformed. Raised at construction, so a process stops at
    startup with the setting's name rather than failing at its first read."""


class EpistemicViolation(ExulanicaError):
    """A write would file a claim under a provenance class its predicate does not allow.

    The database refuses the same write with an SQLSTATE and no explanation. This carries the
    explanation: which predicate, which kind, and which kinds it does allow.
    """


class TombstonedError(ExulanicaError):
    """A committed tombstone covers this address. Terminal, never retried.

    Control-flow relevant, and this is the one that costs something when it is wrong. A worker
    cancels on this and retries on anything else, so a tombstone refusal that arrives as some
    other error type becomes an unbounded retry loop against content the user deleted.
    """


class PrivacyAdmissionError(ExulanicaError):
    """No current eligible privacy receipt permits reconstruction of these bytes."""
