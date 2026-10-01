"""The capability descriptors the workspace asset reads carry, held to the routes and their rules.

Without a database: descriptors are built from plain records and described against the routing
application, so every mutating route under ``/workspace-assets`` must have one, and each state is
the one its write path decides. ``tests/test_workspace_assets_postgres.py`` reads them over HTTP.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from exulanica.api.capabilities import Surface, describe
from exulanica.api.permissions import ROUTE_RULES, Permission
from exulanica.api.routes.workspace_assets import admission_operation, asset_operations
from exulanica.api.surface import routing_only_application

ROUTES = Surface(routing_only_application())
EVERYTHING = frozenset(Permission)
ASSET = uuid.uuid4()


def _described(operations) -> dict[str, dict]:
    return {
        descriptor["operation"]: descriptor
        for descriptor in (describe(operation, ROUTES, EVERYTHING) for operation in operations)
    }


def _preparation(state: str, failure_class: str | None = None):
    return SimpleNamespace(state=state, failure_class=failure_class)


def test_every_mutating_workspace_asset_route_has_a_descriptor():
    mutating = {
        f"{method} {path}"
        for method, path in ROUTE_RULES
        if path.startswith("/workspace-assets") and method != "GET"
    }
    described = set(_described((admission_operation(None),))) | set(
        _described(asset_operations(ASSET, None, False, None))
    )
    assert mutating and described == mutating


def test_admission_is_available_until_a_count_bound_is_met():
    [open_] = _described((admission_operation(None),)).values()
    assert (open_["state"], open_["code"]) == ("available", None)
    assert open_["requires"] == ["admission.write"]
    assert open_["options"] == ["GET /workspace-assets"]
    assert open_["idempotency"] == "declaration"
    # Whether a preparation process runs here is a fact this server cannot read yet.
    assert open_["effects"] == [{"on": "preparation", "state": "unknown", "code": None}]
    for bound in ("assets", "requests_per_day", "pending_at_once"):
        [spent] = _described((admission_operation(bound),)).values()
        assert (spent["state"], spent["code"]) == (
            "unavailable",
            "workspace_asset_quota_exceeded",
        )
        assert spent["effects"] == []


@pytest.mark.parametrize(
    ("preparation", "present", "spent", "asking", "cancel"),
    [
        (None, False, None, None, "preparation_not_ready"),
        (None, False, "pending_at_once", "workspace_asset_quota_exceeded", "preparation_not_ready"),
        (_preparation("requested"), False, "pending_at_once", None, None),
        (_preparation("running"), False, None, None, None),
        (_preparation("prepared"), True, "requests_per_day", None, "preparation_finished"),
        (
            _preparation("prepared"),
            False,
            "requests_per_day",
            "workspace_asset_quota_exceeded",
            "preparation_finished",
        ),
        (_preparation("failed", "invalid_content"), False, "pending_at_once", None, None),
        (
            _preparation("failed", "timed_out"),
            False,
            "pending_at_once",
            "workspace_asset_quota_exceeded",
            None,
        ),
        (_preparation("cancelled", "cancelled"), False, None, None, None),
        (_preparation("cancelled", "withdrawn"), False, None, "withdrawn", None),
        (_preparation("cancelled", "deleted"), False, None, "withdrawn", None),
    ],
    ids=[
        "none",
        "none-spent",
        "waiting-spent",
        "running",
        "prepared-spent",
        "bytes-missing-spent",
        "content-failure-spent",
        "timeout-spent",
        "cancelled",
        "withdrawn",
        "deleted",
    ],
)
def test_each_assets_operations_say_what_their_write_paths_decide(
    preparation, present, spent, asking, cancel
):
    described = _described(asset_operations(ASSET, preparation, present, spent))
    asked = described["POST /workspace-assets/{asset_id}/preparation"]
    stopped = described["POST /workspace-assets/{asset_id}/preparation/cancel"]
    withdrawn = described["POST /workspace-assets/{asset_id}/withdraw"]
    assert asked["code"] == asking and stopped["code"] == cancel
    assert asked["state"] == ("available" if asking is None else "unavailable")
    assert stopped["state"] == ("available" if cancel is None else "unavailable")
    assert (withdrawn["state"], withdrawn["code"]) == ("available", None)
    for descriptor in (asked, stopped, withdrawn):
        assert descriptor["bind"] == {"asset_id": str(ASSET)}
        assert descriptor["subjects"] == {"read": "GET /workspace-assets", "field": "assets"}
        assert descriptor["requires"] == ["admission.write"]
