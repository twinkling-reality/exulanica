"""The database latency proxy in ``scripts/acceptance/latency_proxy.py``, without PostgreSQL.

It forwards every byte unchanged in both directions, holds each chunk for the delay its file names
(read again while it runs, bounded, and no delay when the file is absent or unreadable), and
listens and connects on the loopback address alone.
"""

from __future__ import annotations

import asyncio
import importlib.util
import socket
import sys
import time
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "acceptance" / "latency_proxy.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("exulanica_acceptance_latency_proxy", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


PROXY = _load()


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_a_delay_is_whole_milliseconds_bounded_and_none_when_unreadable(tmp_path):
    path = tmp_path / "delay"
    assert PROXY.parse_delay(path) == 0
    for text, expected in (
        ("", 0),
        ("50", 50),
        (" 7\n", 7),
        ("-3", 0),
        ("x", 0),
        ("999999", 10_000),
    ):
        path.write_text(text)
        assert PROXY.parse_delay(path) == expected, text


def test_bytes_pass_unchanged_both_ways_and_each_chunk_waits_for_the_delay(tmp_path):
    delay_file = tmp_path / "delay"
    delay_file.write_text("0")
    upstream_port, listen_port = _free_port(), _free_port()

    async def run() -> tuple[bytes, float, bytes, float]:
        async def echo(reader, writer):
            while data := await reader.read(65536):
                writer.write(data[::-1])
                await writer.drain()
            writer.close()

        upstream = await asyncio.start_server(echo, "127.0.0.1", upstream_port)
        delay = PROXY.Delay(delay_file)
        proxy = asyncio.create_task(PROXY.serve(listen_port, upstream_port, delay))
        await asyncio.sleep(0.2)

        async def round_trip(payload: bytes) -> tuple[bytes, float]:
            reader, writer = await asyncio.open_connection("127.0.0.1", listen_port)
            started = time.monotonic()
            writer.write(payload)
            await writer.drain()
            answer = await reader.readexactly(len(payload))
            elapsed = time.monotonic() - started
            writer.close()
            return answer, elapsed

        fast, fast_seconds = await round_trip(b"select 1;" * 100)
        delay_file.write_text("150")
        await asyncio.sleep(PROXY.RELOAD_SECONDS * 2)
        slow, slow_seconds = await round_trip(b"select 2;" * 100)
        proxy.cancel()
        upstream.close()
        return fast, fast_seconds, slow, slow_seconds

    fast, fast_seconds, slow, slow_seconds = asyncio.run(run())
    assert fast == (b"select 1;" * 100)[::-1]
    assert slow == (b"select 2;" * 100)[::-1]
    # Each direction holds its chunk 150 ms, so a round trip takes at least 300 ms.
    assert slow_seconds >= 0.3 > fast_seconds


def test_it_listens_and_forwards_on_the_loopback_address_alone():
    source = SCRIPT.read_text()
    assert PROXY.LOOPBACK == "127.0.0.1"
    assert "0.0.0.0" not in source
    assert "import exulanica" not in source and "from exulanica" not in source
