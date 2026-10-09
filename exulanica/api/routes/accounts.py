"""Public Google redirect endpoints, the guest entry, and cookie session/logout endpoints."""

from __future__ import annotations

import datetime as dt
import logging
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Body, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from exulanica.api.account_repository import (
    AccountRejected,
    AccountSession,
    AccountUnavailable,
    GuestEntriesExhausted,
)
from exulanica.api.account_runtime import (
    LOGIN_COOKIE,
    SESSION_COOKIE,
    AccountRuntime,
    GuestCodeRefused,
    GuestEntryOff,
    origin,
)
from exulanica.api.authorisation import TokenNotAccepted
from exulanica.models.spending import SpendingRefused

_LOG = logging.getLogger(__name__)

#: How often a guest's session read may ask again for an allowance it does not hold, per workspace:
#: each ask takes the authority's witness and state locks, which every admission takes too.
GRANT_RETRY_SECONDS = 60.0
#: How many workspaces' last asks are remembered; the oldest is forgotten past it.
GRANT_RETRY_REMEMBERED = 10_000


class _GrantRetries:
    """When each workspace last asked again for its allowance, in this process."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._asked: OrderedDict[uuid.UUID, float] = OrderedDict()

    def may_ask(self, workspace_id: uuid.UUID) -> bool:
        """True, and remembered, when the workspace has not asked within GRANT_RETRY_SECONDS."""
        with self._lock:
            now = self._clock()
            last = self._asked.get(workspace_id)
            if last is not None and now - last < GRANT_RETRY_SECONDS:
                return False
            self._asked[workspace_id] = now
            self._asked.move_to_end(workspace_id)
            while len(self._asked) > GRANT_RETRY_REMEMBERED:
                self._asked.popitem(last=False)
            return True


_GRANT_RETRIES = _GrantRetries()

router = APIRouter(prefix="/auth", tags=["accounts"])
_HEADERS = {
    "Cache-Control": "private, no-store",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
}


def _runtime(request: Request) -> AccountRuntime:
    runtime = getattr(request.app.state.services, "accounts", None)
    if runtime is None:
        raise AccountUnavailable("Google sign-in is not configured")
    # Never derive callback/cookie authority from an untrusted Host or forwarded header.
    try:
        actual_origin = origin(str(request.url))
    except ValueError as exc:
        raise AccountRejected("invalid account request origin") from exc
    expected = (
        {origin(runtime.config.callback_uri)}
        if runtime.config is not None
        else set(runtime.browser_origins)
    )
    if actual_origin not in expected:
        raise AccountRejected("request origin does not match configured account endpoint")
    return runtime


def _failure(exc: Exception) -> JSONResponse:
    unavailable = isinstance(exc, AccountUnavailable)
    return JSONResponse(
        status_code=503 if unavailable else 401,
        content={
            "code": "account_unavailable" if unavailable else "authentication_failed",
            "detail": "Google sign-in is not configured or unavailable"
            if unavailable
            else "Sign-in or session was not accepted",
        },
        headers=_HEADERS,
    )


@router.get("/google/start")
def google_start(
    request: Request, return_uri: Annotated[str | None, Query(max_length=2048)] = None
) -> Response:
    try:
        runtime = _runtime(request)
        url, browser = runtime.start(return_uri)
        response = RedirectResponse(url, status_code=303, headers=_HEADERS)
        response.set_cookie(
            LOGIN_COOKIE, browser, max_age=600, path="/", secure=True, httponly=True, samesite="lax"
        )
        return response
    except (AccountRejected, AccountUnavailable) as exc:
        return _failure(exc)


@router.get("/google/callback")
def google_callback(request: Request) -> Response:
    try:
        runtime = _runtime(request)
        # Reject parameter pollution rather than letting a framework choose one repeated value.
        if (
            len(request.query_params.getlist("state")) != 1
            or any(len(request.query_params.getlist(key)) > 1 for key in ("code", "iss", "error"))
            or (("code" in request.query_params) == ("error" in request.query_params))
        ):
            raise AccountRejected("invalid callback parameters")
        target, token, session = runtime.callback(
            state=request.query_params["state"],
            code=request.query_params.get("code", ""),
            browser=request.cookies.get(LOGIN_COOKIE, ""),
            response_issuer=request.query_params.get("iss"),
            previous_token=request.cookies.get(SESSION_COOKIE),
        )
        # A completed callback is Google's: runtime.callback refuses first without its config.
        config = runtime.config
        assert config is not None
        response = RedirectResponse(target, status_code=303, headers=_HEADERS)
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=config.session_seconds,
            expires=session.expires_at,
            path="/",
            secure=True,
            httponly=True,
            samesite="lax",
        )
    except (AccountRejected, AccountUnavailable) as exc:
        response = _failure(exc)
    response.delete_cookie(LOGIN_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
    return response


def _allowance(request: Request, workspace_id: uuid.UUID) -> list[dict[str, Any]]:
    """What a guest may still spend on each provider: the grant's state and what is left of it,
    from the workspace's own spending (never an authority's figure)."""
    from exulanica.spending.status import workspace_status

    services = request.app.state.services
    entries = workspace_status(services.database, workspace_id)["providers"]
    return [
        {
            "provider": entry["provider"],
            "state": (entry.get("grant") or {}).get("state", "none"),
            "available_usd": entry.get("available_usd"),
            "available_calls": entry.get("available_calls"),
        }
        for entry in entries
    ]


def _session_view(
    request: Request, account: AccountSession, *, grant_missing: bool = False
) -> dict[str, Any]:
    """The session as the browser reads it. For a guest, the allowance; with ``grant_missing``, a
    guest who holds no allowance on a provider is granted it first, on those providers alone and at
    most once a minute per workspace (an entry whose grant failed, the authority suspended or the
    database slow, is granted on a later read). An allowance that
    cannot be read is null, and the session is still answered."""
    view: dict[str, Any] = {
        "user_id": account.user_id,
        "actor": account.session.actor,
        "workspace_id": account.session.workspace_id,
        "expires_at": account.expires_at,
        "csrf_token": account.csrf_token,
        "role": account.role,
        # Whether a style pack or workspace asset upload from this session is let through: the
        # operator's creator grant (exulanica-creator-grant).
        "creator": account.creator,
    }
    if account.role == "guest":
        workspace = account.session.workspace_id
        try:
            allowance = _allowance(request, workspace)
            missing = [entry["provider"] for entry in allowance if entry["state"] == "none"]
            if grant_missing and missing and _GRANT_RETRIES.may_ask(workspace):
                _grant_guest(request, workspace, providers=missing)
                allowance = _allowance(request, workspace)
        except Exception as exc:  # the session stands; the allowance is unread, not invented
            _LOG.warning("a guest's allowance could not be read: %s", type(exc).__qualname__)
            allowance = None
        view["allowance"] = allowance
    return view


@router.get("/session")
def account_session(request: Request) -> Response:
    try:
        account = _runtime(request).browser_session(request)
        return JSONResponse(
            content=jsonable_encoder(_session_view(request, account, grant_missing=True)),
            headers=_HEADERS,
        )
    except (AccountRejected, AccountUnavailable, TokenNotAccepted) as exc:
        return _failure(exc)


class GuestEntryBody(BaseModel):
    """What a visitor sends to enter: nothing, or the code the server asks for."""

    model_config = ConfigDict(extra="forbid")

    code: Annotated[str | None, Field(min_length=1, max_length=256)] = None


def _guest_refusal(
    status: int, code: str, detail: str, *, retry_after: int | None = None
) -> JSONResponse:
    headers = dict(_HEADERS)
    content: dict[str, Any] = {"code": code, "detail": detail}
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
        content["retry_after_seconds"] = retry_after
    return JSONResponse(status_code=status, content=content, headers=headers)


def _seconds_to_the_next_utc_day(now: dt.datetime | None = None) -> int:
    """How long until the day's guest count starts again: the next 00:00 UTC, at least a second."""
    instant = now or dt.datetime.now(dt.UTC)
    tomorrow = (instant + dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((tomorrow - instant).total_seconds()))


@router.post("/guest", status_code=201)
def guest_entry(
    request: Request, body: Annotated[GuestEntryBody | None, Body()] = None
) -> Response:
    """Enter as a guest: an account with no identity, a workspace of its own and a session.

    After the account's transaction commits, the workspace is given its allowance by the spending
    authority's guest policy and its first world from the installation's arrival list. Either can
    fail without undoing the entry, so once the account exists the answer is always 201 with the
    session cookie, and ``incomplete`` names each step that failed (``allowance`` with the
    refusal's code, or ``arrival``). A visitor whose allowance is missing is granted it on their
    next session read (``GET /auth/session``).
    """
    try:
        runtime = _runtime(request)
    except (AccountRejected, AccountUnavailable) as exc:
        # No accounts at all, or a request to another origin: as every account route answers.
        return _failure(exc)
    try:
        entry = runtime.enter_guest(request, body.code if body is not None else None)
    except GuestEntriesExhausted:
        return _guest_refusal(
            429,
            "guest_entries_exhausted",
            "this server has admitted all its guests for today",
            retry_after=_seconds_to_the_next_utc_day(),
        )
    except GuestCodeRefused:
        return _guest_refusal(403, "guest_entry_code_wrong", "that code does not open this server")
    except GuestEntryOff:
        return _guest_refusal(503, "guest_entry_off", "this server does not admit guests")
    except AccountUnavailable:
        # The entry is configured and its database did not answer: nothing was made.
        return _guest_refusal(
            503,
            "guest_entry_unavailable",
            "this server could not admit a guest just now; try again shortly",
            retry_after=30,
        )
    except AccountRejected:
        return _guest_refusal(
            403, "origin_not_permitted", "this request's origin is not this server"
        )
    workspace = entry.account.session.workspace_id
    incomplete = [{"step": "allowance", **problem} for problem in _grant_guest(request, workspace)]
    arrival = _arrival(request, workspace, entry.account.session.actor)
    if arrival is None:
        incomplete.append({"step": "arrival", "code": "arrival_not_made"})
    view = _session_view(request, entry.account)
    if view.get("allowance") is None:
        incomplete.append({"step": "allowance", "code": "allowance_unread"})
    view["arrival"] = arrival
    view["incomplete"] = incomplete
    response = JSONResponse(status_code=201, content=jsonable_encoder(view), headers=_HEADERS)
    assert runtime.guest is not None
    response.set_cookie(
        SESSION_COOKIE,
        entry.token,
        max_age=runtime.guest.session_seconds,
        expires=entry.account.expires_at,
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )
    return response


def _grant_guest(
    request: Request, workspace_id: uuid.UUID, *, providers: list[str] | None = None
) -> list[dict[str, str]]:
    """The workspace's allowance from every provider with a guest policy. A refusal, or a failure
    of any kind, leaves the workspace without one on that provider and is answered by provider and
    code (a failure by its class alone, never its text); the entry stands."""
    from exulanica.models.manifest import load_manifest

    spending = getattr(request.app.state.services, "spending", None)
    if spending is None:
        return []
    problems: list[dict[str, str]] = []
    if providers is None:
        try:
            providers = list(load_manifest().providers)
        except Exception as exc:
            _LOG.warning("the model manifest could not be read: %s", type(exc).__qualname__)
            return [{"provider": "*", "code": "allowance_failed"}]
    for provider in providers:
        try:
            spending.grant_guest(workspace_id, provider=provider)
        except SpendingRefused as refused:
            _LOG.warning("a guest's allowance was not granted: %s", refused.reason)
            problems.append(
                {"provider": str(provider), "code": str(refused.detail or refused.reason)}
            )
        except Exception as exc:
            _LOG.warning("a guest's allowance failed: %s", type(exc).__qualname__)
            problems.append({"provider": str(provider), "code": "allowance_failed"})
    return problems


def _arrival(request: Request, workspace_id: uuid.UUID, actor: uuid.UUID) -> dict[str, Any] | None:
    """The workspace's first world, from the installation's arrival list, or None when it could
    not be made; the visitor can still make one."""
    from exulanica.world.arrival_worlds import load_arrival_worlds, make_arrival_world
    from exulanica.world.saved_entries import SavedWorldEntryRepository

    services = request.app.state.services
    try:
        world, *_ = load_arrival_worlds()
        with services.database.session(workspace_id) as connection:
            entry = make_arrival_world(
                SavedWorldEntryRepository(connection, workspace_id, services.store),
                world,
                created_by=actor,
            )
        return {"entry_id": entry.entry_id, "world_id": entry.world_id}
    except Exception as exc:  # the entry stands without its arrival world; say why in the log
        _LOG.warning("a guest's arrival world was not made: %s: %s", type(exc).__name__, exc)
        return None


@router.post("/logout")
def logout(request: Request) -> Response:
    try:
        _runtime(request).logout(request)
        response = JSONResponse(content={"logged_out": True}, headers=_HEADERS)
        response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
        return response
    except (AccountRejected, AccountUnavailable, TokenNotAccepted) as exc:
        return _failure(exc)
