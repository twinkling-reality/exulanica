"""AWS Signature Version 4, for the S3 requests the object store sends.

An S3-compatible endpoint authenticates a request by recomputing an HMAC over a canonical form of
it: the method, the path, the sorted query, the lower-cased and trimmed headers the request names
as signed, and the SHA-256 of the payload. A signature therefore binds the exact bytes of the body
as well as the key they are written under, so an endpoint that accepts a signed PUT has checked
that it received what was signed.

The functions here are pure. They take strings that are already in their wire form where the
protocol says so (the canonical URI is the encoded path) and raw strings where it encodes them
itself (query names and values). ``tests/test_store_sigv4.py`` holds this module to the cases of
AWS's published Signature Version 4 test suite that apply to S3, and to the S3 rules the suite's
generic cases do not cover: a path is encoded once and never normalised.

The secret access key never leaves :class:`RequestSigner`: it is not in the repr, and the derived
day key it caches is not either. Nothing here logs.
"""

from __future__ import annotations

import hashlib
import hmac
import threading
import urllib.parse
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

__all__ = [
    "ALGORITHM",
    "EMPTY_PAYLOAD_SHA256",
    "RequestSigner",
    "SignedRequest",
    "canonical_headers",
    "canonical_query",
    "canonical_request",
    "s3_canonical_uri",
    "signing_key",
    "string_to_sign",
    "uri_encode",
]

ALGORITHM: Final = "AWS4-HMAC-SHA256"
#: The hex SHA-256 of zero bytes, which a request without a body signs as its payload.
EMPTY_PAYLOAD_SHA256: Final = hashlib.sha256(b"").hexdigest()
_UNRESERVED: Final = "-_.~"


def uri_encode(value: str, *, keep_slash: bool = False) -> str:
    """Percent-encode as Signature Version 4 defines it.

    Letters, digits and ``-_.~`` stay as they are; every other byte of the UTF-8 form becomes
    ``%XY`` with upper-case hex. ``/`` stays only inside a path.
    """
    return urllib.parse.quote(value, safe=_UNRESERVED + ("/" if keep_slash else ""))


def s3_canonical_uri(path: str) -> str:
    """The canonical URI of an S3 request: the path encoded once, never normalised.

    Other services double-encode and resolve ``.`` and ``..`` segments; S3 does neither, because
    ``a/./b`` and ``a/b`` are different object keys.
    """
    if not path.startswith("/"):
        raise ValueError(f"a request path starts with '/', got {path!r}")
    return uri_encode(path, keep_slash=True)


def canonical_query(parameters: Iterable[tuple[str, str]]) -> str:
    """Encoded names and values, sorted by name and then by value, joined with ``&``."""
    encoded = sorted((uri_encode(name), uri_encode(value)) for name, value in parameters)
    return "&".join(f"{name}={value}" for name, value in encoded)


def canonical_headers(headers: Iterable[tuple[str, str]]) -> tuple[str, str]:
    """The canonical header block and the signed-header list, in that order.

    Names are lower-cased; each value is trimmed and its runs of whitespace collapse to one
    space; a name that repeats keeps every value, comma-separated in the order sent.
    """
    grouped: dict[str, list[str]] = {}
    for name, value in headers:
        grouped.setdefault(name.strip().lower(), []).append(" ".join(value.split()))
    names = sorted(grouped)
    block = "".join(f"{name}:{','.join(grouped[name])}\n" for name in names)
    return block, ";".join(names)


def canonical_request(
    method: str,
    canonical_uri: str,
    query: Iterable[tuple[str, str]],
    headers: Iterable[tuple[str, str]],
    payload_sha256: str,
) -> tuple[str, str]:
    """The canonical request and its signed-header list."""
    block, signed = canonical_headers(headers)
    text = "\n".join(
        (method.upper(), canonical_uri, canonical_query(query), block, signed, payload_sha256)
    )
    return text, signed


def string_to_sign(amz_date: str, scope: str, canonical: str) -> str:
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return "\n".join((ALGORITHM, amz_date, scope, digest))


def _hmac(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def signing_key(secret_access_key: str, date: str, region: str, service: str) -> bytes:
    """The day key: an HMAC chain from the secret through the date, region and service."""
    key = _hmac(f"AWS4{secret_access_key}".encode(), date)
    for part in (region, service, "aws4_request"):
        key = _hmac(key, part)
    return key


@dataclass(frozen=True, slots=True)
class SignedRequest:
    """What signing produced: the headers to send, and the intermediate forms a test compares."""

    authorization: str
    amz_date: str
    canonical_request: str
    string_to_sign: str
    signed_headers: str


class RequestSigner:
    """Signs requests with one access key for one region and service.

    ``access_key_id`` travels in every Authorization header, which is the only place it goes.
    Neither it nor the secret access key is printed: ``repr`` names the region and service.
    """

    __slots__ = ("_cache", "_lock", "_secret", "access_key_id", "region", "service")

    def __init__(
        self, access_key_id: str, secret_access_key: str, *, region: str, service: str = "s3"
    ) -> None:
        for name, value in (
            ("access key id", access_key_id),
            ("secret access key", secret_access_key),
            ("region", region),
            ("service", service),
        ):
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f"a request signer needs a non-empty {name} without spaces")
        self.access_key_id = access_key_id
        self.region = region
        self.service = service
        self._secret = secret_access_key
        self._cache: tuple[str, bytes] | None = None
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return f"RequestSigner(region={self.region!r}, service={self.service!r})"

    def reset_after_fork(self) -> None:
        """A forked child gets a fresh lock: the parent's may have been held by another thread."""
        self._lock = threading.Lock()

    def _day_key(self, date: str) -> bytes:
        with self._lock:
            if self._cache is None or self._cache[0] != date:
                self._cache = (date, signing_key(self._secret, date, self.region, self.service))
            return self._cache[1]

    def sign(
        self,
        method: str,
        canonical_uri: str,
        query: Sequence[tuple[str, str]],
        headers: Sequence[tuple[str, str]],
        payload_sha256: str,
        when: datetime,
    ) -> SignedRequest:
        """Sign a request whose headers already include ``host`` and ``x-amz-date``.

        ``when`` must be the instant ``x-amz-date`` states; passing it separately rather than
        reading it back out of the headers keeps a caller from signing one time and sending
        another.
        """
        if when.tzinfo is None:
            raise ValueError("a signing time must be timezone-aware")
        moment = when.astimezone(UTC)
        amz_date = moment.strftime("%Y%m%dT%H%M%SZ")
        date = amz_date[:8]
        stated = [value.strip() for name, value in headers if name.lower() == "x-amz-date"]
        if stated != [amz_date]:
            raise ValueError("the x-amz-date header must state the signing time exactly once")
        canonical, signed = canonical_request(method, canonical_uri, query, headers, payload_sha256)
        scope = f"{date}/{self.region}/{self.service}/aws4_request"
        to_sign = string_to_sign(amz_date, scope, canonical)
        signature = hmac.new(
            self._day_key(date), to_sign.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        return SignedRequest(
            authorization=(
                f"{ALGORITHM} Credential={self.access_key_id}/{scope}, "
                f"SignedHeaders={signed}, Signature={signature}"
            ),
            amz_date=amz_date,
            canonical_request=canonical,
            string_to_sign=to_sign,
            signed_headers=signed,
        )
