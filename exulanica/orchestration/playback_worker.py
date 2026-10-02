"""Play the societies this host plays, and seal their coupled traffic, in a process of its own.

    exulanica-playback-worker

The playback the API's lifespan otherwise runs in its own threads: the society playback worker
(:mod:`exulanica.api.society_control_worker`), whose rounds claim, lease and advance each playing
society and ask the models a society's owner chose before a minute, and the traffic signal
controller's loop (:mod:`exulanica.api.traffic_signal_controller`), which seals coupled traffic
behind each society and prepares the signal choices of legacy worlds. It plays the workspaces
``EXULANICA_SOCIETY_CONTROL_WORKSPACES`` lists and, with ``EXULANICA_SOCIETY_CONTROL_WORKER``, every
active account-owned workspace, at ``EXULANICA_SOCIETY_TICK_INTERVAL_MS``, until it is interrupted
or terminated; a round it is running then finishes or rolls back.

Run it beside an API started with ``EXULANICA_PLAYBACK_WORKER=process`` and the same settings: that
API then serves the playback controls without playing, so no round and no traffic minute runs on
its interpreter. Claims and leases decide which host advances a society, so a second playback
process, or an API that plays as well, never advances one twice. While it runs it holds a shared
session advisory lock keyed by its playback configuration (``PlaybackHostLock``); an API with the
same configuration reads it to say whether its worlds advance on their own. Like the API, it
refuses to start against a schema it does not recognise, as a role that is not the runtime role,
or on a restored database whose withdrawals are not replayed. Each event is one line of JSON on
standard output.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
from collections.abc import Mapping, Sequence
from typing import Any

from exulanica.api.services import build_services
from exulanica.api.society_control_worker import PlaybackHostLock
from exulanica.api.traffic_signal_controller import TrafficSignalController
from exulanica.db.migrate import verify_schema
from exulanica.db.roles import assert_runtime_role
from exulanica.deletion.restore import verify_restore

__all__ = ["main"]


def _emit(stream: Any, event: str, **fields: Any) -> None:
    print(
        json.dumps({"component": "playback-worker", "event": event, **fields}, sort_keys=True),
        file=stream,
        flush=True,
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    stream: Any = None,
) -> int:
    del argv
    output = stream or sys.stdout
    environment = os.environ if environ is None else environ
    try:
        services = build_services(environment, spending_label="playback-worker")
        if services.playback_player == "none":
            raise ValueError("EXULANICA_PLAYBACK_WORKER is off: this environment plays no society")
        verify_schema(services.database)
        with services.database.unscoped() as connection:
            assert_runtime_role(connection)
        verify_restore(services.database, services.restore_state_path)
        worker = services.build_society_control_worker()
        if worker is None:
            raise ValueError(
                "this environment plays no society: it configures no society runtime, lists no "
                "workspace in EXULANICA_SOCIETY_CONTROL_WORKSPACES and leaves "
                "EXULANICA_SOCIETY_CONTROL_WORKER off"
            )
    except Exception as exc:
        _emit(output, "startup_failed", failure_class=type(exc).__name__, message=str(exc))
        return 1

    configuration = services.playback_configuration_sha256()
    held = PlaybackHostLock(services.database, configuration)
    try:
        held.__enter__()
    except Exception as exc:
        _emit(output, "startup_failed", failure_class=type(exc).__name__, message=str(exc))
        return 1
    traffic = TrafficSignalController(
        services.database,
        services.model_client,
        services.society_control_workspaces,
        services.person_decision_policy,
    )
    stop = threading.Event()

    def request_shutdown(signum: int, _frame: Any) -> None:
        _emit(output, "shutdown_requested", signal=signal.Signals(signum).name)
        stop.set()

    previous = {
        signum: signal.signal(signum, request_shutdown)
        for signum in (signal.SIGTERM, signal.SIGINT)
    }
    playback = threading.Thread(target=worker.run, args=(stop,), name="society-playback")
    try:
        _emit(
            output,
            "startup",
            listed_workspaces=len(services.society_control_workspaces),
            account_discovery=services.runs_society_control_worker,
            base_tick_interval_ms=services.society_base_tick_interval_ms,
            configuration_sha256=configuration,
        )
        traffic.start()
        playback.start()
        while not stop.wait(0.5):
            if not playback.is_alive():
                _emit(output, "worker_stopped_unexpectedly")
                return 1
    finally:
        stop.set()
        if playback.is_alive():
            playback.join()
        traffic.close()
        held.__exit__(None, None, None)
        for signum, handler in previous.items():
            signal.signal(signum, handler)
    _emit(output, "stopped", **worker.health)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
