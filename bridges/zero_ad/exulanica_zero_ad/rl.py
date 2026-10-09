"""0 A.D.'s reinforcement-learning interface, as the game serves it on this machine.

The game, started as ``pyrogenesis --rl-interface=127.0.0.1:<port>``, serves four routes, each a
POST (read in the engine's ``source/rlinterface/RLInterface.cpp``):

``/reset``
    Starts a match from its settings (the body: a match's JSON settings; ``playerID`` and
    ``saveReplay`` in the query) and answers the game's state once it has started.
``/step``
    Applies the commands in the body, one ``player;json-command`` line each (none to just advance),
    advances the game (one turn when it has a window) and answers the game's state.
``/evaluate``
    Runs the JavaScript in the body in the simulation and answers its result as JSON.
``/templates``
    Answers the named templates, one per line.

The state is the game's AI interface representation as JSON: its ``entities``, by id, each with
its ``template``, ``owner`` and ``position``. This client is our own, standard library only; it
speaks only to a loopback address, and follows no redirect.
"""

from __future__ import annotations

import ipaddress
import json
import urllib.parse
import urllib.request
from collections.abc import Iterable, Sequence
from typing import Any

__all__ = ["GameRefused", "RLInterface", "command_lines"]

#: How long the game may take to answer: a match's start loads its map.
TIMEOUT_SECONDS = 120.0


class GameRefused(Exception):
    """The game answered a route with an error, or with something that is not its state."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def _loopback(base_url: str) -> str:
    """``base_url`` without its trailing slash, if it is plain HTTP to this machine."""
    parts = urllib.parse.urlsplit(base_url)
    host = parts.hostname or ""
    try:
        loopback = host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False
    if parts.scheme != "http" or not loopback:
        raise ValueError("the game's interface is reached over plain HTTP to this machine only")
    return base_url.rstrip("/")


def command_lines(commands: Iterable[tuple[int, dict[str, Any]]]) -> str:
    """The body of a step: one ``player;json-command`` line for each command."""
    return "\n".join(
        f"{player};{json.dumps(command, separators=(',', ':'))}" for player, command in commands
    )


class RLInterface:
    """One running game's interface."""

    def __init__(self, base_url: str, *, opener: Any = None) -> None:
        self.base_url = _loopback(base_url)
        self._open = opener or urllib.request.build_opener(_NoRedirect).open

    def _post(self, route: str, body: str, query: dict[str, str] | None = None) -> bytes:
        url = f"{self.base_url}/{route}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        request = urllib.request.Request(url, data=body.encode("utf-8"), method="POST")
        try:
            with self._open(request, timeout=TIMEOUT_SECONDS) as response:
                return response.read()
        except OSError as error:
            raise GameRefused(f"the game's {route} did not answer: {error}") from error

    def _state(self, raw: bytes) -> dict[str, Any]:
        try:
            state = json.loads(raw)
        except ValueError as error:
            raise GameRefused("the game answered something that is not its state") from error
        if not isinstance(state, dict):
            raise GameRefused("the game answered something that is not its state")
        return state

    def reset(self, settings: dict[str, Any], *, player_id: int = 1) -> dict[str, Any]:
        """Start a match from ``settings``, playing as ``player_id``; its first state."""
        raw = self._post("reset", json.dumps(settings), {"playerID": str(player_id)})
        return self._state(raw)

    def step(self, commands: Sequence[tuple[int, dict[str, Any]]] = ()) -> dict[str, Any]:
        """Apply ``commands``, each ``(player, command)``, advance the game; its new state."""
        return self._state(self._post("step", command_lines(commands)))

    def evaluate(self, code: str) -> Any:
        """Run ``code`` in the game's simulation; its result."""
        raw = self._post("evaluate", code)
        try:
            return json.loads(raw) if raw.strip() else None
        except ValueError as error:
            raise GameRefused("the game's evaluation answered no JSON") from error

    def templates(self, names: Sequence[str]) -> dict[str, str]:
        """The named templates, by name."""
        raw = self._post("templates", "\n".join(names)).decode("utf-8")
        return dict(zip(names, raw.split("\n"), strict=False))
