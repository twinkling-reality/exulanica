"""The reference client in ``bridges/door_client`` speaks the door's channel as the contract states.

The client is outside the product and is loaded here by its path, never imported by the product.
A fake opener stands in for the network, so each assertion is about the request the client makes:
its method, path, body and credential, and how it keeps the cursor the door returns.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[1] / "bridges" / "door_client" / "door_client.py"


def _client_module():
    name = "door_reference_client"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered before it runs: its dataclass looks its own module up while being defined.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class _Answer(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def _recording(answers):
    sent = []

    def opener(request, timeout):
        sent.append(
            {
                "method": request.get_method(),
                "url": request.full_url,
                "body": None if request.data is None else json.loads(request.data),
                "authorization": request.get_header("Authorization"),
                "timeout": timeout,
            }
        )
        status, body = answers.pop(0)
        if status >= 400:
            raise urllib.error.HTTPError(
                request.full_url, status, "refused", {}, io.BytesIO(json.dumps(body).encode())
            )
        return _Answer(json.dumps(body).encode())

    return sent, opener


def test_the_client_keeps_the_cursor_and_answers_an_offered_label():
    module = _client_module()
    sent, opener = _recording(
        [
            (200, {"cursor": "c1", "grant": {}, "hold_seconds": 15}),
            (
                200,
                {
                    "cursor": "c2",
                    "frames": [
                        {
                            "kind": "asked",
                            "request_id": "r",
                            "request_sha256": "h",
                            "context": {"options": [{"label": "wait"}]},
                        }
                    ],
                },
            ),
            (202, {"received": True}),
        ]
    )
    client = module.DoorClient("https://door.example/", "secret", opener=opener)
    client.hello("0.1.0", {"profile": "exulanica.bridge-mapping/v1"}, ["player"])
    frames = client.frames()
    assert client.cursor == "c2" and module.DoorClient.offered(frames[0]) == ["wait"]
    client.answer(frames[0], "wait")
    assert [(s["method"], s["url"]) for s in sent] == [
        ("POST", "https://door.example/door/channel/hello"),
        ("GET", "https://door.example/door/channel/frames?after=c1"),
        ("POST", "https://door.example/door/channel/answers"),
    ]
    assert sent[2]["body"] == {"request_id": "r", "request_sha256": "h", "label": "wait"}
    assert {s["authorization"] for s in sent} == {"Bearer secret"}
    # A poll waits longer than the hold the door's hello said, and the credential is never shown.
    assert sent[1]["timeout"] > 15 and "secret" not in repr(client)


def test_the_client_sends_visitors_calls_them_home_and_reports_what_came_back():
    module = _client_module()
    sent, opener = _recording(
        [
            (201, {"arrival_id": "a1", "thing_id": "t1"}),
            (202, {"departure_id": "d1", "recorded": True}),
            (202, {"recorded": True}),
        ]
    )
    client = module.DoorClient("https://door.example", "secret", opener=opener)
    assert client.arrive("a1", "player", "cc0-traveller")["thing_id"] == "t1"
    client.home("t1")
    client.delivered("d1", [{"thing_id": "s1", "game_item": "test:sword"}])
    assert [(s["method"], s["url"]) for s in sent] == [
        ("POST", "https://door.example/door/channel/arrivals"),
        ("POST", "https://door.example/door/channel/home"),
        ("POST", "https://door.example/door/channel/departures/d1/delivered"),
    ]
    assert [s["body"] for s in sent] == [
        {"arrival_id": "a1", "game_type": "player", "look_key": "cc0-traveller", "carried": []},
        {"thing_id": "t1"},
        {"delivered": [{"thing_id": "s1", "game_item": "test:sword"}], "not_delivered": []},
    ]


def test_a_refusal_reaches_the_adapter_as_its_status_and_code():
    module = _client_module()
    _sent, opener = _recording([(404, {"code": "invite_not_redeemable", "detail": "no"})])
    with pytest.raises(module.DoorRefused) as refused:
        module.redeem("https://door.example", "bridge-secret", "ABCD", "a" * 64, opener=opener)
    assert (refused.value.status, refused.value.code) == (404, "invite_not_redeemable")


def test_the_client_sends_a_credential_only_over_https_or_to_this_machine():
    module = _client_module()
    _sent, opener = _recording([(200, {"cursor": "c", "grant": {}, "hold_seconds": 1})] * 3)
    for base in ("https://door.example", "http://127.0.0.1:19500", "http://localhost:19500"):
        module.DoorClient(base, "secret", opener=opener).hello("0.1.0", {}, ["player"])
    for base in ("http://door.example", "ftp://door.example", "door.example"):
        with pytest.raises(ValueError, match="HTTPS"):
            module.DoorClient(base, "secret", opener=opener).hello("0.1.0", {}, ["player"])


def test_the_client_follows_no_redirect():
    module = _client_module()
    handler = module._NoRedirect()
    request = urllib.request.Request("https://door.example/door/channel/hello")
    request.add_header("Authorization", "Bearer secret")
    moved = handler.redirect_request(request, None, 307, "moved", {}, "https://elsewhere.example/")
    assert moved is None
