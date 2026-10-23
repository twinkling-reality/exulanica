"""How large a request each role may send, stated as data: the input half of an honest hold.

Work that holds money before it starts (a world from a sentence, a creature from words) holds the
worst case of the calls it will make. Each call's worst case is its input and its answer at the
model's prices. The answer is bounded by the request's own answer limit (the manifest's
``max_tokens`` for the role). The input is bounded here: each role's ``request_bytes_at_most``
(``assets/catalogs/request-envelopes/request-envelopes.v<N>.json``), the most bytes the request's
JSON may hold with every character outside ASCII escaped, its answer's schema and every repair
included, measured the way the model chain measures a request before sending it
(:meth:`exulanica.models.chain.ModelChain` refuses one larger than the bound its work was priced
at, so nothing sent passes it).

A tokenizer that works on bytes, or falls back to them, makes no token of less than one byte, and
the request's JSON keys and quotes outnumber the few tokens a chat template adds to each message,
so a request's escaped bytes bound its input tokens. Priced at that bound, a hold is a worst case
the work can reach rather than a model's whole context window, which no request of these roles
comes near. A role the catalog does not name is priced at its model's whole context window, as
before. ``tests/test_request_envelopes.py`` measures every stage's largest request again and holds
it under its role's envelope, so a prompt or catalog that grows past it fails there first.

Pure: no connection, no model asked.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from functools import cache
from pathlib import Path
from typing import Any, Final

from exulanica.models.manifest import Role

__all__ = [
    "CATALOG",
    "PROFILE",
    "catalog_sha256",
    "read",
    "request_bytes_at_most",
]

_ROOT: Final = Path(__file__).resolve().parents[2]
CATALOG: Final = _ROOT / "assets/catalogs/request-envelopes/request-envelopes.v1.json"
PROFILE: Final = "exulanica.request-envelopes/v1"
_ENTRY: Final = frozenset({"role", "request_bytes_at_most", "reason"})
#: The largest envelope a role may state: far above any request, far below any context's bytes.
_MOST_BYTES: Final = 1 << 22


def read(document: Any) -> dict[Role, int]:
    """Each role's request envelope ``document`` states, in bytes; refused by name where it is no
    such catalog, names a role twice or one the manifest does not know, or states no whole
    positive figure."""
    if not isinstance(document, Mapping) or document.get("profile") != PROFILE:
        raise ValueError(f"not a catalog of profile {PROFILE}")
    envelopes: dict[Role, int] = {}
    for raw in document.get("entries") or ():
        if not isinstance(raw, Mapping) or set(raw) != _ENTRY:
            raise ValueError(f"a request envelope states exactly {sorted(_ENTRY)}")
        try:
            role = Role(raw["role"])
        except ValueError:
            raise ValueError(f"{raw['role']!r} is no role of the model manifest") from None
        figure = raw["request_bytes_at_most"]
        if (
            role in envelopes
            or type(figure) is not int
            or not 0 < figure <= _MOST_BYTES
            or not isinstance(raw["reason"], str)
            or not raw["reason"].strip()
        ):
            raise ValueError(f"invalid request envelope for {role}")
        envelopes[role] = figure
    return envelopes


@cache
def _shipped() -> tuple[dict[Role, int], str]:
    raw = CATALOG.read_bytes()
    return read(json.loads(raw)), hashlib.sha256(raw).hexdigest()


def catalog_sha256() -> str:
    """Digest of the same catalog bytes this process's envelopes were read from."""
    return _shipped()[1]


def request_bytes_at_most(role: Role | str) -> int | None:
    """The most bytes a request of ``role`` may send, or None where the catalog names none."""
    return _shipped()[0].get(Role(role))
