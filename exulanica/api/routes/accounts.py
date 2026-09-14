"""Public Google redirect endpoints and authenticated cookie session/logout endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, RedirectResponse, Response

from exulanica.api.account_repository import AccountRejected, AccountUnavailable
from exulanica.api.account_runtime import LOGIN_COOKIE, SESSION_COOKIE, AccountRuntime, origin
from exulanica.api.authorisation import TokenNotAccepted

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
    if actual_origin != origin(runtime.config.callback_uri):
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
        response = RedirectResponse(target, status_code=303, headers=_HEADERS)
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=runtime.config.session_seconds,
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


@router.get("/session")
def account_session(request: Request) -> Response:
    try:
        account = _runtime(request).browser_session(request)
        return JSONResponse(
            content=jsonable_encoder(
                {
                    "user_id": account.user_id,
                    "actor": account.session.actor,
                    "workspace_id": account.session.workspace_id,
                    "expires_at": account.expires_at,
                    "csrf_token": account.csrf_token,
                }
            ),
            headers=_HEADERS,
        )
    except (AccountRejected, AccountUnavailable, TokenNotAccepted) as exc:
        return _failure(exc)


@router.post("/logout")
def logout(request: Request) -> Response:
    try:
        _runtime(request).logout(request)
        response = JSONResponse(content={"logged_out": True}, headers=_HEADERS)
        response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
        return response
    except (AccountRejected, AccountUnavailable, TokenNotAccepted) as exc:
        return _failure(exc)
