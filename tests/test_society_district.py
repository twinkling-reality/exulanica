"""Exact byte/frame response and scoped failure behavior for the society district read."""

from __future__ import annotations

import hashlib
import uuid
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from exulanica.api.society_district import society_district_view
from exulanica.selection.validation import Session
from exulanica.world.errors import UnknownWorldResource
from exulanica.world.society import UnavailableSocietyInput


@pytest.fixture
def stub():
    session = Session(workspace_id=uuid.uuid4(), actor=uuid.uuid4())
    version = uuid.uuid4()
    base = b'{ "base": true }\r\n'
    interpreted = b'{\n  "interpretation": true\n}\n'
    registration = dict(
        world_id="world",
        version_id=str(version),
        source_snapshot_id=str(uuid.uuid4()),
        region_id="registered-second-region",
        district_id="district",
        frame_name="district-frame",
        translation_mm=[1200, 300, -4567],
        yaw_microradians=0,
        scale_milli=1000,
    )
    binding = SimpleNamespace(
        registration=lambda: registration,
        place_id=uuid.uuid4(),
        base_artifact_sha256=hashlib.sha256(base).hexdigest(),
        interpretation_artifact_sha256=hashlib.sha256(interpreted).hexdigest(),
        interpretation_document_sha256="c" * 64,
        sources=[SimpleNamespace(source_sha256="a" * 64), SimpleNamespace(source_sha256="b" * 64)],
    )
    calls = []

    class Connection:
        @contextmanager
        def transaction(self):
            calls.append("transaction")
            yield
            calls.append("commit")

        def execute(self, sql):
            calls.append(sql)

    runtime = SimpleNamespace(
        _binding=lambda s, v: binding,
        _lock=lambda c, s: calls.append("lock"),
        _version=lambda c, s, b: SimpleNamespace(source_invalidated=False),
        _district=lambda c, s, b: ({}, base, None),
        _blob=lambda sha: interpreted,
    )
    return runtime, Connection(), session, version, base, interpreted, calls, binding


def test_exact_utf8_strings_and_registered_transform_survive_response(stub):
    runtime, c, s, v, base, interpreted, calls, binding = stub
    result = society_district_view(runtime, c, s, v).model_dump(mode="json")
    assert result["base_json"].encode() == base
    assert result["interpretation_json"].encode() == interpreted
    assert result["registration"] == binding.registration()
    assert result["current_dependencies"] == {"a" * 64: "available", "b" * 64: "available"}
    assert "base_document" not in result and "interpretation_document" not in result
    assert calls == ["transaction", "set transaction read only", "lock", "commit"]


@pytest.mark.parametrize("failure", ["binding", "version", "invalidated", "district", "utf8"])
def test_boundary_distinguishes_missing_scope_from_unavailable_source(stub, failure):
    runtime, c, s, v, *_ = stub

    def missing_binding(*args):
        raise UnavailableSocietyInput("not configured")

    def missing_version(*args):
        try:
            raise UnknownWorldResource("absent")
        except UnknownWorldResource as exc:
            raise UnavailableSocietyInput("version unavailable") from exc

    def unavailable(*args):
        raise UnavailableSocietyInput("source denied")

    if failure == "binding":
        runtime._binding = missing_binding
    elif failure == "version":
        runtime._version = missing_version
    elif failure == "invalidated":
        runtime._version = lambda *args: SimpleNamespace(source_invalidated=True)
    elif failure == "district":
        runtime._district = unavailable
    else:
        runtime._blob = lambda *args: b"\xff"
    with pytest.raises(
        UnknownWorldResource if failure in ("binding", "version") else UnavailableSocietyInput
    ):
        society_district_view(runtime, c, s, v)
