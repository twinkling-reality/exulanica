"""The process-wide bound on photographs decoded at once (``exulanica.corpus.decode.decoding``).

Held: a decode over the limit waits for a turn and proceeds when one is given back; one that waits
out :data:`~exulanica.corpus.decode.DECODE_WAIT_SECONDS` is refused with ``DecodeBusy``, which
nothing reads as an unreadable photograph; and a thread already holding a turn is never made to wait
on itself.
"""

from __future__ import annotations

import threading
import time

import pytest
from exulanica.corpus import decode
from exulanica.corpus.decode import UNREADABLE, DecodeBusy, decode_counts, decoding, open_sensor
from exulanica.ingest.decode import open_upright

from conftest import photo_bytes


@pytest.fixture
def one_turn(monkeypatch):
    """The process allowed one decode at a time and a short wait, restored afterwards."""
    before = decode_counts()["limit"]
    decode.configure_decode_concurrency(1)
    monkeypatch.setattr(decode._BOUND, "_wait_seconds", 0.3)
    yield
    decode.configure_decode_concurrency(before)


def _hold_turn(release: threading.Event, holding: threading.Event) -> None:
    with decoding():
        holding.set()
        release.wait(5)


def test_a_decode_that_waits_out_its_turn_is_refused_and_not_read_as_a_bad_photograph(one_turn):
    release, holding = threading.Event(), threading.Event()
    holder = threading.Thread(target=_hold_turn, args=(release, holding))
    holder.start()
    try:
        assert holding.wait(5)
        refused_before = decode_counts()["refused"]
        started = time.monotonic()
        with pytest.raises(DecodeBusy):
            open_sensor(photo_bytes())
        assert time.monotonic() - started >= 0.3
        assert decode_counts()["refused"] == refused_before + 1
        assert not issubclass(DecodeBusy, UNREADABLE)
    finally:
        release.set()
        holder.join(5)


def test_a_waiting_decode_proceeds_when_a_turn_is_given_back(one_turn, monkeypatch):
    monkeypatch.setattr(decode._BOUND, "_wait_seconds", 5.0)
    release, holding = threading.Event(), threading.Event()
    holder = threading.Thread(target=_hold_turn, args=(release, holding))
    holder.start()
    assert holding.wait(5)
    waited_before = decode_counts()["waited"]
    threading.Timer(0.2, release.set).start()
    with open_sensor(photo_bytes()) as image:
        assert image.size == (160, 100)
    holder.join(5)
    counts = decode_counts()
    assert counts["waited"] == waited_before + 1
    assert counts["in_use"] == 0


def test_a_thread_holding_a_turn_decodes_without_waiting_on_itself(one_turn):
    with decoding():
        upright, _facts = open_upright(photo_bytes())
        with decoding(), open_sensor(photo_bytes()) as again:
            assert again.size == upright.size
    assert decode_counts()["in_use"] == 0


def test_the_limit_is_a_whole_number_of_at_least_one():
    for limit in (0, -1, 1.5):
        with pytest.raises(ValueError, match="at least 1"):
            decode.configure_decode_concurrency(limit)  # type: ignore[arg-type]
