"""Offline-only safety boundaries for private pilot harness tests."""

import pytest


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    import socket

    import exulanica.api.services as services
    import psycopg

    def denied(*args, **kwargs):
        raise AssertionError(
            "offline guard tests prohibit network, database and service construction"
        )

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(psycopg, "connect", denied)
    monkeypatch.setattr(psycopg.Connection, "connect", denied)
    monkeypatch.setattr(services, "build_services", denied)
