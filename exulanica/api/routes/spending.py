"""What the caller's workspace may still spend on hosted models, from its own rows alone.

One read, of the workspace the caller's grant names: there is no identifier in the path, so there
is nothing another workspace's caller could probe. It states, for each provider the manifest
names, the workspace's grant and its state, what is committed and in flight, what may have been
billed with its outcome unknown, the provider-reported usage priced by the manifest, and what is
left; an authority by its state alone, never by what other workspaces committed. How this
instance spends (``durable`` or ``process``) is stated beside it, because under ``process`` no
durable authority admits this instance's calls and the grants below bind nothing here.
``docs/model-spending-contract.md`` is the contract.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from exulanica.api.dependencies import CurrentSession, ScopedConnection, get_services
from exulanica.spending.status import read_workspace_status

router = APIRouter(tags=["spending"])


@router.get(
    "/spending",
    summary="What this workspace may still spend on hosted models, by provider.",
)
def spending(
    request: Request, connection: ScopedConnection, session: CurrentSession
) -> dict[str, Any]:
    services = get_services(request)
    document = read_workspace_status(connection, session.workspace_id)
    return {**document, "mode": services.spending_mode}
