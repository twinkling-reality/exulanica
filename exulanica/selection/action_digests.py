"""The digests a Companion plan names its documents by: a preview, a recorded document, the plan.

Every float is written as its shortest round-trip decimal, tagged, before the canonical JSON is
hashed (:mod:`exulanica.canonical` admits no float), so a style parameter enters a digest exactly.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from exulanica.canonical import canonical_json


def _digest_input(value: Any) -> Any:
    """``value`` with every float written as its shortest round-trip decimal, tagged.

    Floats never enter a digest input in this codebase (``exulanica.canonical``); a style
    parameter is one, so it enters as a tagged string that states it exactly.
    """
    if isinstance(value, float):
        return {"float": repr(value)}
    if isinstance(value, Mapping):
        return {str(key): _digest_input(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_digest_input(item) for item in value]
    return value


def _digest(document: Any) -> str:
    return hashlib.sha256(canonical_json(_digest_input(document))).hexdigest()


def document_sha256(document: Any) -> str:
    """The digest a plan gives a preview or recorded document, floats tagged as above."""
    return _digest(document)


def plan_document_sha256(document: Mapping[str, Any]) -> str:
    """The digest a plan names itself by: every member except the digest and the execution."""
    return _digest(
        {
            key: value
            for key, value in document.items()
            if key not in ("plan_sha256", "execution", "names")
        }
    )
