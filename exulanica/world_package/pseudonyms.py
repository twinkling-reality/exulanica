"""The one rule a package uses to name a database row without revealing its identifier.

``urn:exulanica:wmp:<kind>:<sha256>`` where the digest is SHA-256 of ``"<kind>:<id>"``. A holder of
the identifier can match it; the package alone does not reveal it. The 1.0 components and every
extension use this rule, so a reference made in one resolves in another.

Pure: imports nothing that opens a database.
"""

from __future__ import annotations

import hashlib
from typing import Any

__all__ = ["optional_urn", "urn"]


def urn(kind: str, value: Any) -> str:
    digest = hashlib.sha256(f"{kind}:{value}".encode()).hexdigest()
    return f"urn:exulanica:wmp:{kind}:{digest}"


def optional_urn(kind: str, value: Any) -> str | None:
    return None if value is None else urn(kind, value)
