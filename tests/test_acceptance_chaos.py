"""The J2 acceptance driver, ``scripts/acceptance/chaos.py``, without a stack.

The driver reads the formation stream line by line, so it can leave it at any moment, and it
counts and locks tables by name through the evidence connection. These hold that its reader tells
event ids, phases and the ``retry:`` hint apart as the route sends them, and that every table it
names is one the migrations create, so a renamed table fails here rather than as a hung lock.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "scripts" / "acceptance" / "chaos.py"
MIGRATIONS = ROOT / "exulanica" / "migrations"

#: A stream as the formation route writes one: a comment heartbeat, events, then a retry hint.
BODY = (
    ": heartbeat\n\n"
    'id: received\ndata: {"eventId": "received", "phase": "received"}\n\n'
    'id: 0190\ndata: {"eventId": "0190", "phase": "media_extraction"}\n\n'
    "retry: 5000\n\n"
)


class _Formation(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self.wfile.write(BODY.encode())

    def log_message(self, *arguments: object) -> None:
        pass


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("exulanica_acceptance_chaos", DRIVER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_reader_tells_events_and_the_retry_hint_apart(tmp_path):
    driver = _load()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Formation)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        api = driver.Api.__new__(driver.Api)
        api.port, api.token = server.server_address[1], "not-a-credential"
        stream = driver.Stream(api, "batch").read(10)
    finally:
        server.shutdown()
    assert stream.status == 200
    assert stream.ids == ["received", "0190"]
    assert stream.phases == ["received", "media_extraction"]
    assert stream.retry and stream.ended and stream.terminal is None


def test_every_table_the_driver_names_is_created_by_a_migration():
    driver = _load()
    created = {
        name
        for path in MIGRATIONS.glob("*.sql")
        for name in re.findall(r"create table (?:if not exists )?([a-z_]+)", path.read_text())
    }
    source = DRIVER.read_text()
    named = {driver.LEDGER, *re.findall(r"from ([a-z_]+)", driver.OUTPUTS)}
    named |= set(re.findall(r'"select count\(\*\) from ([a-z_]+)"', source))
    assert named <= created, named - created
