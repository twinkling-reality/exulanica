"""What a person's worlds can connect to, over HTTP: the integrations catalog beside the manifest.

Read-only and the same for every workspace: ``GET /integrations`` answers the catalog the server
ships (``exulanica.integrations/v1``, :mod:`exulanica.models.integrations`) as it was loaded and
checked, each entry's key, kind, name, line, mark and guide. It states no entry's state: each
kind's own read answers whether it is on.

It needs a session (``world.read``), a guest's included, as the models read does.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from exulanica.api.dependencies import CurrentSession
from exulanica.models.integrations import integrations

router = APIRouter(prefix="/integrations", tags=["integrations"])

_PRIVATE = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}


@router.get(
    "",
    summary="What a person's worlds can connect to: each one's words, mark and guide, by kind.",
)
def integrations_catalog(_session: CurrentSession) -> Any:
    return JSONResponse(content=integrations(), headers=_PRIVATE)
