"""The gate a guest meets says how long this host keeps what is made on it, before they come in.

A signed-out browser's session answer (``GET /auth/session``) states the day the host keeps what
is made on it until, where the host states one (``EXULANICA_HOST_KEEPS_UNTIL``), as the Create offer
does; where it states none, the answer leaves it out, so the gate says nothing.
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from exulanica.api.routes import accounts
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _session(kept: dt.date | None) -> dict[str, object]:
    """The signed-out answer of a server with no browser accounts and the host's day ``kept``."""
    app = FastAPI()
    app.state.services = SimpleNamespace(accounts=None, host_keeps_until=kept)
    app.include_router(accounts.router)
    with TestClient(app) as client:
        answer = client.get("/auth/session")
    assert answer.status_code == 503
    return answer.json()


def test_a_signed_out_answer_states_the_day_the_host_keeps_what_is_made_until() -> None:
    answer = _session(dt.date(2026, 12, 15))
    assert answer["host_keeps_until"] == "2026-12-15"
    # Beside how a browser may come in, as before.
    assert answer["sign_in"] == {"google": False, "guest": "off"}


def test_a_host_that_states_no_day_is_answered_without_one() -> None:
    answer = _session(None)
    assert "host_keeps_until" not in answer
    assert answer["sign_in"] == {"google": False, "guest": "off"}
