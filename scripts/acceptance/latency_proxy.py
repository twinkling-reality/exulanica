#!/usr/bin/env python3
"""A TCP proxy that adds a stated delay to every chunk it forwards: added database latency.

    python3 scripts/acceptance/latency_proxy.py --listen PORT --upstream PORT --delay-file FILE

It listens on 127.0.0.1:``--listen`` and forwards each connection to 127.0.0.1:``--upstream``,
holding every chunk it reads, in either direction, for the delay ``--delay-file`` names in whole
milliseconds before it writes it on. Order within a direction is kept, so a round trip costs about
twice the delay. The file is read again at most every ``RELOAD_SECONDS``, so a run changes the
delay without restarting the proxy or the connections through it; a missing or unreadable file
means no delay. It stands between the acceptance API and its PostgreSQL server
(``launch.py up --database-latency``), so J2 can exercise added connection latency.

Standard library only; it imports nothing from the product and changes no byte it forwards. Each
event is one JSON line on standard output: ``startup``, ``delay`` when the delay it applies
changes, and ``stopped``. It never forwards to any host but 127.0.0.1.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import signal
import sys
import time
from collections.abc import Sequence
from pathlib import Path

LOOPBACK = "127.0.0.1"
#: How often the delay file is read again.
RELOAD_SECONDS = 0.2
#: The most one chunk is held, so a mistyped file cannot hold a connection open for hours.
DELAY_MAXIMUM_MS = 10_000
CHUNK_BYTES = 64 * 1024


def emit(event: str, **fields: object) -> None:
    print(json.dumps({"component": "latency-proxy", "event": event, **fields}), flush=True)


class Delay:
    """The delay the file states, read again at most every ``RELOAD_SECONDS``."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.read_at = 0.0
        self.milliseconds = 0

    def current(self) -> int:
        now = time.monotonic()
        if now - self.read_at >= RELOAD_SECONDS:
            self.read_at = now
            value = parse_delay(self.path)
            if value != self.milliseconds:
                self.milliseconds = value
                emit("delay", milliseconds=value)
        return self.milliseconds


def parse_delay(path: Path) -> int:
    """Whole milliseconds from the file, bounded; anything else is no delay."""
    try:
        value = int(path.read_text().strip() or "0")
    except (OSError, ValueError):
        return 0
    return max(0, min(DELAY_MAXIMUM_MS, value))


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, delay: Delay) -> None:
    """Forward one direction in order, each chunk held for the delay as it stands when read."""
    queue: asyncio.Queue[tuple[float, bytes]] = asyncio.Queue()

    async def send() -> None:
        while True:
            due, chunk = await queue.get()
            wait = due - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()

    sender = asyncio.create_task(send())
    try:
        while True:
            chunk = await reader.read(CHUNK_BYTES)
            await queue.put((time.monotonic() + delay.current() / 1000, chunk))
            if not chunk:
                break
        await sender
    except (ConnectionError, asyncio.IncompleteReadError):
        sender.cancel()
    finally:
        if not writer.is_closing():
            writer.close()


async def serve(listen: int, upstream: int, delay: Delay) -> None:
    connections = 0

    async def connect(client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter):
        nonlocal connections
        connections += 1
        try:
            server_reader, server_writer = await asyncio.open_connection(LOOPBACK, upstream)
        except OSError:
            client_writer.close()
            return
        await asyncio.gather(
            pipe(client_reader, server_writer, delay),
            pipe(server_reader, client_writer, delay),
            return_exceptions=True,
        )

    server = await asyncio.start_server(connect, LOOPBACK, listen)
    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stopping.set)
    emit("startup", listen=listen, upstream=upstream, delay_file=str(delay.path))
    async with server:
        await stopping.wait()
    emit("stopped", connections=connections)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--listen", type=int, required=True)
    parser.add_argument("--upstream", type=int, required=True)
    parser.add_argument("--delay-file", type=Path, required=True)
    arguments = parser.parse_args(argv)
    asyncio.run(serve(arguments.listen, arguments.upstream, Delay(arguments.delay_file)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
