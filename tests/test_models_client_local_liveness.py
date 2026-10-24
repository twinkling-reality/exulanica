"""A model on this computer is offered only while its server answers (A2).

The decision client reads each admitted server's catalog at most every
:data:`~exulanica.models.client.LOCAL_LIVENESS_EVERY` seconds, within a short timeout, through its
own egress-checked transport, and refuses that provider as ``provider_not_running`` while the last
read failed. A test double that carries no allowlist reaches no network and answers for itself.
"""

from __future__ import annotations

import json

from exulanica.models.client import (
    LOCAL_LIVENESS_EVERY,
    PROVIDER_NOT_RUNNING,
    LocalLiveness,
    ModelClient,
)
from exulanica.models.egress import parse_egress_allowlist
from exulanica.models.errors import TransportError
from exulanica.models.manifest import load_manifest
from exulanica.models.transport import HttpResponse

from model_fakes import FakeTransport

TAGS = {"models": [{"name": "a-model:latest", "digest": "abc", "capabilities": ["completion"]}]}


def _local():
    """The manifest's provider on this computer (the positive control: there is one)."""
    local = [p for p in load_manifest().providers.values() if p.on_this_computer]
    assert local, "the manifest names a provider on this computer"
    return local[0]


class Server(FakeTransport):
    """A server on this computer that answers its catalog while ``up``, else refuses at once."""

    egress = parse_egress_allowlist(["http://localhost:11434"])

    def __init__(self) -> None:
        super().__init__()
        self.up = True

    def get_json(self, url, *, headers, timeout):
        self.gets.append(url)
        if not self.up:
            raise TransportError("connection refused", reached_provider=False)
        return HttpResponse(status_code=200, text=json.dumps(TAGS))


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_a_server_is_read_at_most_once_a_period_and_counts_as_stopped_while_it_does_not_answer():
    local, server, clock = _local(), Server(), Clock()
    liveness = LocalLiveness([local], server, clock=clock)
    assert liveness.stopped() == frozenset()
    assert server.gets == [local.catalog_url]
    # Within the period the last read answers; nothing is read again.
    server.up = False
    clock.now += LOCAL_LIVENESS_EVERY - 1
    assert liveness.stopped() == frozenset()
    assert len(server.gets) == 1
    # A period later it is read again, and a server that does not answer is stopped.
    clock.now += 1
    assert liveness.stopped() == {local.provider_id}
    assert len(server.gets) == 2
    # It answers again: offered again a period later.
    server.up = True
    clock.now += LOCAL_LIVENESS_EVERY
    assert liveness.stopped() == frozenset()


def test_any_failure_to_read_counts_as_stopped():
    local = _local()

    class Broken(Server):
        def get_json(self, url, *, headers, timeout):
            raise RuntimeError("anything at all")

    class NotItsCatalog(Server):
        def get_json(self, url, *, headers, timeout):
            return HttpResponse(status_code=200, text=json.dumps({"something": "else"}))

    for transport in (Broken(), NotItsCatalog()):
        assert LocalLiveness([local], transport).stopped() == {local.provider_id}


def test_a_read_under_way_never_makes_another_caller_wait_or_read_again():
    local, server = _local(), Server()
    started: list = []
    liveness = LocalLiveness([local], server, start=started.append)
    # The read is started and not finished: every caller is answered by the last read (none yet).
    assert liveness.stopped() == frozenset()
    assert liveness.stopped() == frozenset()
    assert len(started) == 1 and server.gets == []
    server.up = False
    started[0]()
    assert liveness.stopped() == {local.provider_id}


def test_the_client_refuses_a_stopped_server_s_provider_and_only_reads_where_its_list_admits_it():
    local = _local()
    assert local.provider_id not in ModelClient(transport=Server(), local_only=True).refusals
    down = Server()
    down.up = False
    stopped = ModelClient(transport=down, local_only=True)
    assert stopped.refusals[local.provider_id] == PROVIDER_NOT_RUNNING
    # A copy shares what was read of the server.
    assert stopped.with_attempts(lambda usage: None).refusals[local.provider_id] == (
        PROVIDER_NOT_RUNNING
    )
    # A test double carrying no allowlist reaches no network: nothing is read, nothing refused.
    double = FakeTransport()
    assert local.provider_id not in ModelClient(transport=double, local_only=True).refusals
    assert double.gets == []


def test_a_server_the_list_does_not_admit_is_refused_as_not_admitted_and_never_read():
    local = _local()

    class Elsewhere(Server):
        egress = parse_egress_allowlist(["https://elsewhere.example"])

    transport = Elsewhere()
    client = ModelClient(transport=transport, local_only=True)
    assert client.refusals[local.provider_id] == "provider_not_admitted"
    assert transport.gets == []
