"""How large a decision's request may be, stated as data: the input half of what an ask holds.

A decision is asked of the model a world chose for its role, at most its contract's
``answer_attempts_maximum`` times (:func:`exulanica.api.decision_admission.ask_bound_usd`). Each
request's answer is bounded by the model's answer bound. Its input is bounded here: for a role and
the terms it asks under, named by the terms' prompt version, ``request_bytes_at_most``
(``assets/catalogs/request-envelopes/decision-request-envelopes.v<N>.json``), the most bytes the
request's JSON may hold with every character outside ASCII escaped, every message, the function or
schema with every option and a retry's note included, measured the way the model chain measures a
request before sending it. A tokenizer that works on bytes, or falls back to them, makes no token of
less than one byte, so these bytes bound the request's input tokens, as they do for the roles a
draft asks (:mod:`exulanica.models.request_envelopes`).

A request is bounded by what its context may carry: the contract's options, lines and characters,
the bytes its noticed and remembered blocks may hold, and the context's own bytes. The figures rest
on a guard: ``tests/test_decision_request_envelopes.py`` builds each terms' largest request, every
part it renders at its own most, through the host's one ask path for each answering mechanism, and
holds it under its terms' envelope, so a prompt, catalog or bound that grows past it fails there
first. Nothing refuses a request at send by these figures. A terms the catalog does not name is
priced as before, by its prompt's characters.

Pure: no connection, no model asked.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from functools import cache
from pathlib import Path
from typing import Any, Final

from exulanica.world.decision_roles import RoleRefused, RoleRegistry, decision_roles

__all__ = [
    "CATALOG",
    "PROFILE",
    "catalog_sha256",
    "read",
    "request_bytes_at_most",
]

_ROOT: Final = Path(__file__).resolve().parents[2]
CATALOG: Final = _ROOT / "assets/catalogs/request-envelopes/decision-request-envelopes.v1.json"
PROFILE: Final = "exulanica.decision-request-envelopes/v1"
_ENTRY: Final = frozenset({"role", "prompt_version", "request_bytes_at_most", "reason"})
#: The largest envelope an entry may state: far above any request, far below any context's bytes.
_MOST_BYTES: Final = 1 << 22


def read(document: Any, roles: RoleRegistry | None = None) -> dict[tuple[str, str], int]:
    """Each envelope ``document`` states, in bytes, by role key and prompt version; refused by name
    where it is no such catalog, names a terms twice, a role ``roles`` does not register or a prompt
    version that role's terms never stated, or states no whole positive figure."""
    if not isinstance(document, Mapping) or document.get("profile") != PROFILE:
        raise ValueError(f"not a catalog of profile {PROFILE}")
    registry = decision_roles() if roles is None else roles
    envelopes: dict[tuple[str, str], int] = {}
    for raw in document.get("entries") or ():
        if not isinstance(raw, Mapping) or set(raw) != _ENTRY:
            raise ValueError(f"a decision request envelope states exactly {sorted(_ENTRY)}")
        try:
            role = registry.role(raw["role"])
        except RoleRefused:
            raise ValueError(f"{raw['role']!r} is no registered decision role") from None
        prompt = raw["prompt_version"]
        stated = {terms.prompt_version for terms in role.every_terms()} | set(role.historical_terms)
        if prompt not in stated:
            raise ValueError(f"{prompt!r} is no prompt version of {role.key}")
        figure = raw["request_bytes_at_most"]
        key = (role.key, prompt)
        if (
            key in envelopes
            or type(figure) is not int
            or not 0 < figure <= _MOST_BYTES
            or not isinstance(raw["reason"], str)
            or not raw["reason"].strip()
        ):
            raise ValueError(f"invalid decision request envelope for {role.key} {prompt}")
        envelopes[key] = figure
    return envelopes


@cache
def _shipped() -> tuple[dict[tuple[str, str], int], str]:
    raw = CATALOG.read_bytes()
    return read(json.loads(raw)), hashlib.sha256(raw).hexdigest()


def catalog_sha256() -> str:
    """Digest of the same catalog bytes this process's envelopes were read from."""
    return _shipped()[1]


def request_bytes_at_most(role_key: str, prompt_version: str) -> int | None:
    """The most bytes a request of ``role_key`` asked under ``prompt_version`` may send, or None
    where the catalog names none."""
    return _shipped()[0].get((role_key, prompt_version))
