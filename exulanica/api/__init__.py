"""The HTTP surface. Routes validate and delegate; nothing here decides anything.

Four surfaces, and the shape of each says what it is for:

*   ``/healthz`` and ``/readyz`` are the only unauthenticated routes in the API. A liveness probe
    that needed a credential would go red the day the credential rotated.
*   ``/selection`` is the read path. One Selection primitive, four equal entry points, and the
    routes cannot tell which one produced the plan they were handed.
*   ``/identity`` is the whole mutation surface. No request model on it has a field for who
    decided, because that comes from the token.
*   ``/evidence`` is the product's promise as an HTTP response: given an address, the exact
    original media, with range support, and a 404 rather than a 403 for anything not yours.

The application is built by :func:`exulanica.api.app.create_app`, which takes its services rather
than reading globals, so a test builds an instance against a throwaway schema and a second
instance in one process is ordinary rather than surprising.

The names below are read from their modules on first use, so importing one module of this package
(a worker, the decision host, a command) does not load the web application and its services.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from exulanica.api.app import create_app
    from exulanica.api.authorisation import (
        API_TOKENS_ENV,
        TokenDirectory,
        TokenNotAccepted,
        load_token_directory,
    )
    from exulanica.api.services import Services, build_services

#: Each name this package offers, and the module it is read from.
_HOMES = {
    "API_TOKENS_ENV": "exulanica.api.authorisation",
    "Services": "exulanica.api.services",
    "TokenDirectory": "exulanica.api.authorisation",
    "TokenNotAccepted": "exulanica.api.authorisation",
    "build_services": "exulanica.api.services",
    "create_app": "exulanica.api.app",
    "load_token_directory": "exulanica.api.authorisation",
}

__all__ = [
    "API_TOKENS_ENV",
    "Services",
    "TokenDirectory",
    "TokenNotAccepted",
    "build_services",
    "create_app",
    "load_token_directory",
]


def __getattr__(name: str) -> Any:
    """An exported name, imported from its module on first use, or a module of this package."""
    module = _HOMES.get(name)
    if module is None:
        try:
            return importlib.import_module(f"{__name__}.{name}")
        except ModuleNotFoundError as missing:
            if missing.name != f"{__name__}.{name}":
                raise
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    value = getattr(importlib.import_module(module), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})
