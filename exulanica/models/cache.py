"""The response cache. Invariant 6: idempotency keyed by content hash and pipeline version.

This is a cost control before it is a correctness one. A full corpus pass costs about $0.41 and
ten development iterations over the same photographs cost ten times that for identical answers.
Re-running ingest must not re-bill.

**The key is ``(provider, model, input content hash, pipeline version, role, prompt version)``.**
Each of the six is load bearing:

*   *provider* and *model*, so an answer is only ever served for the model that gave it. A call
    looks up the model it addresses (a role's primary, or the model a world chose), and an entry
    is stored under the model that served it, so a fallback's answer never answers for the
    primary and one model's answer never answers for another. The cost of the rule is stated
    rather than hidden: while a primary is withdrawn, an identical request asks the fallback
    again, because an answer from another model is another answer.
*   *input content hash* over the canonical request, so identical work hits.
*   *pipeline version* from the manifest, so the stored work of a replaced configuration is not
    served under a new one.
*   *role*, so vision answers and reasoning answers cannot collide.
*   *prompt version*, so editing a prompt invalidates the answers it produced. Editing a prompt
    and silently getting the old prompt's answers is the failure that wastes an afternoon.

The identifier that served each entry is recorded *in* the entry too, and a lookup refuses an
entry whose recorded model is not the one it addressed.

Digest input goes through ``exulanica.canonical``, the same canonical JSON the evidence spine uses.
That module refuses floats outright, which is right for a citation digest and inconvenient here
because ``temperature`` is a float, so floats are converted to a tagged repr string first. The
tagged form is injective, so no payload can forge a tag and be served another payload's stored
response, but it is stable only within a process family and would not be sound for anything
that has to be reproduced by another implementation.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Protocol

from exulanica.canonical import sha256_of_canonical
from exulanica.models.manifest import Role

__all__ = [
    "CacheKey",
    "FileResponseCache",
    "InMemoryResponseCache",
    "NullResponseCache",
    "ResponseCache",
    "cache_key",
    "request_digest",
]

#: Keys excluded from the digest. ``model`` is written by the chain for the model each attempt
#: reaches and is named in the key itself; ``stream`` and ``user`` do not change the answer.
_NON_SEMANTIC: Final = frozenset({"model", "stream", "stream_options", "user"})


def _digest_safe(value: Any) -> Any:
    """Encode a request payload injectively, in a form ``exulanica.canonical`` accepts.

    Floats become a tagged string rather than being rejected. ``exulanica.canonical`` bans floats
    because a citation digest must serialise identically in every language forever; a cache key
    has no such obligation, and the tag keeps ``0.0`` from colliding with the string ``"0.0"``.

    A payload mapping is tagged for the same reason, and it is the half that was missing. While
    a mapping passed through unwrapped, the float ``0.0`` and the mapping ``{"__float__":
    "0.0"}`` both encoded to ``{"__float__": "0.0"}`` and shared one cache entry, so one request
    could be answered with another request's response. Tagged, the three dict-valued encodings
    are disjoint single-key namespaces and a payload mapping can only ever reach ``__map__``.
    A payload that spells the tag itself lands one wrapper deeper, always, so there is no depth
    at which it catches up.

    Injective over what a request payload can be on the wire, which is what this digest covers.
    Two mapping keys differing only in type still collapse, because ``str`` is applied to both
    and JSON has one kind of object name; a payload that reached the endpoint could not have
    told them apart either.
    """
    if isinstance(value, bool) or value is None or isinstance(value, (int, str)):
        return value
    if isinstance(value, float):
        return {"__float__": repr(value)}
    if isinstance(value, Mapping):
        return {"__map__": {str(k): _digest_safe(v) for k, v in value.items()}}
    if isinstance(value, (list, tuple)):
        return [_digest_safe(v) for v in value]
    return {"__repr__": repr(value)}


def request_digest(payload: Mapping[str, Any]) -> str:
    """SHA-256 hex over the semantic content of a request payload."""
    semantic = {k: v for k, v in payload.items() if k not in _NON_SEMANTIC}
    return sha256_of_canonical(_digest_safe(semantic)).hex()


@dataclass(frozen=True, slots=True)
class CacheKey:
    """The six-part key, and its flat string form."""

    provider: str
    model_id: str
    input_digest: str
    pipeline_version: int
    role: Role
    prompt_version: str

    def __str__(self) -> str:
        return (
            f"{self.provider}/{self.model_id}/{self.role}/{self.pipeline_version}/"
            f"{self.prompt_version}/{self.input_digest}"
        )

    @property
    def digest(self) -> str:
        """A hash of the whole key. Used as a filename, so no key component can escape a path."""
        return sha256_of_canonical(
            {
                "provider": self.provider,
                "model_id": self.model_id,
                "input_digest": self.input_digest,
                "pipeline_version": self.pipeline_version,
                "role": str(self.role),
                "prompt_version": self.prompt_version,
            }
        ).hex()


def cache_key(
    payload: Mapping[str, Any],
    *,
    provider: str,
    model_id: str,
    pipeline_version: int,
    role: Role,
    prompt_version: str,
) -> CacheKey:
    return CacheKey(
        provider=provider,
        model_id=model_id,
        input_digest=request_digest(payload),
        pipeline_version=pipeline_version,
        role=role,
        prompt_version=prompt_version,
    )


class ResponseCache(Protocol):
    """Read-through cache over provider responses."""

    def get(self, key: CacheKey) -> dict[str, Any] | None: ...

    def put(self, key: CacheKey, entry: Mapping[str, Any]) -> None: ...


class NullResponseCache:
    """Caches nothing. The default, so caching is something a caller opts into knowingly."""

    def get(self, key: CacheKey) -> dict[str, Any] | None:
        return None

    def put(self, key: CacheKey, entry: Mapping[str, Any]) -> None:
        return None


@dataclass
class InMemoryResponseCache:
    """Process-lifetime cache. Right for one script run and for tests."""

    entries: dict[str, dict[str, Any]] = field(default_factory=dict)

    def get(self, key: CacheKey) -> dict[str, Any] | None:
        return self.entries.get(key.digest)

    def put(self, key: CacheKey, entry: Mapping[str, Any]) -> None:
        self.entries[key.digest] = dict(entry)

    def __len__(self) -> int:
        return len(self.entries)


class FileResponseCache:
    """Cache on disk, so the saving survives between development runs.

    One JSON file per entry under two levels of hex fanout, matching the layout the content
    store already uses. Writes go to a temporary file and are moved into place, so a crash never
    leaves a half-written entry that later parses as a truncated answer.

    **Cached bodies are model output over the user's photographs, which is personal data.** The
    root belongs somewhere the deletion cascade can reach, and it is not a place to put anything
    that is not already derived from the corpus. No credential is ever written here: the entry
    holds the response, never the request headers.
    """

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def _path_for(self, key: CacheKey) -> Path:
        digest = key.digest
        return self._root / digest[:2] / digest[2:4] / f"{digest}.json"

    def get(self, key: CacheKey) -> dict[str, Any] | None:
        path = self._path_for(key)
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            # A corrupt entry is a miss, never an error. The worst case is one re-billed call.
            return None
        return entry if isinstance(entry, dict) else None

    def put(self, key: CacheKey, entry: Mapping[str, Any]) -> None:
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(entry)
        payload.setdefault("cached_at", time.time())
        payload.setdefault("cache_key", str(key))
        handle, temp_name = tempfile.mkstemp(dir=path.parent, prefix="entry-", suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, sort_keys=True)
            os.replace(temp_name, path)
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise
