"""The host's decision phase with more than one role hosted by one engine, as the database takes it.

Two roles decide for a purposeful society's people here, each a registry entry and a copy of the
person's adapter under its own key (``tests/decision_role_support.py``), each with its own chosen
people. What is shown:

*   a race on the second role's reservation asks that role again alone, so the first role's
    requests, already committed, are still asked in their minute and none is left without a
    receipt;
*   a role whose models are slow does not starve the role after it: every role's asks run at once,
    each to its own deadline.
"""

from __future__ import annotations

import json
import time
import uuid
from decimal import Decimal
from typing import Any

import pytest
from exulanica.api.decision_host import DecisionHost
from exulanica.models.manifest import MANIFEST_PATH, parse_manifest
from exulanica.world.decision_roles import DecisionRole
from exulanica.world.society import SocietyBytesNotRead
from exulanica.world.society_controls import LEASE_SECONDS
from exulanica.world.society_decision_repository import SocietyDecisionRepository
from exulanica.world.society_model_choice_repository import SocietyModelChoiceRepository

import test_society_person_decisions_postgres as person_decisions
import test_society_stay_requests_api as stays
from decision_role_support import person_entry, person_like, registry_in_use, write_registry

saved_world = stays.saved_world
app = stays.app
pytestmark = pytest.mark.postgres
PROBE_RECORD = person_decisions.PROBE_RECORD
#: How long a slow model takes to answer, and the deadline each role's asks are given here in
#: place of the contract's twenty seconds, so the test measures in seconds.
SLOW_SECONDS = 2.0
DEADLINE_SECONDS = 1.5


def _offered_two():
    """The manifest with two declared chat models verified to answer by a forced function."""
    document = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"), parse_float=Decimal)
    chosen = [
        model_id
        for model_id, raw in sorted(document["models"].items())
        if raw["min_max_tokens"] is not None and "text" in raw["catalog_use_cases"]
    ][:2]
    for model_id in chosen:
        document["models"][model_id]["answering"] = {"tool_call": PROBE_RECORD}
    return parse_manifest(document), chosen


def _choose(services, world, role: DecisionRole, people, model, *, manifest) -> None:
    with services.database.session(world["workspace"]) as connection:
        SocietyModelChoiceRepository(
            connection, world["workspace"], world_id=world["binding"].world_id
        ).record_choice(
            world["binding"].version_id,
            role,
            request_id=uuid.uuid4(),
            subjects=people,
            model=model,
            chosen_by=world["session"].actor,
            manifest=manifest,
            contract=role.contract(),
        )


def _receipts(services, world, snapshot) -> list[dict[str, Any]]:
    return person_decisions._decisions(services, world, snapshot)


def _unanswered(services, world, snapshot) -> int:
    """How many of the society's requests no receipt answers."""
    with services.database.session(world["workspace"]) as connection:
        return connection.execute(
            "select count(*) as n from world_society_decision_request r "
            "left join world_society_decision d using(workspace_id,society_id,request_id) "
            "where r.workspace_id=%s and r.society_id=%s and d.request_id is null",
            (world["workspace"], snapshot["society_id"]),
        ).fetchone()["n"]


class _Slowly(person_decisions._Chooser):
    """The scripted chooser, taking ``SLOW_SECONDS`` to answer whenever ``slow`` is asked."""

    def __init__(self, slow: str) -> None:
        super().__init__()
        self.slow = slow

    def post_json(self, url, *, headers, payload, timeout):
        if payload["model"] == self.slow:
            time.sleep(SLOW_SECONDS)
        return super().post_json(url, headers=headers, payload=payload, timeout=timeout)


def _minute(host, world, snapshot, services) -> list[dict[str, Any]]:
    """One host minute, and the receipts it recorded."""
    before = len(_receipts(services, world, snapshot))
    assert host.before_minute(
        person_decisions._claim(world, snapshot), time.monotonic() + LEASE_SECONDS
    )
    return _receipts(services, world, snapshot)[before:]


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_race_on_the_second_role_s_reservation_asks_it_again_and_the_first_is_still_asked(
    app, tmp_path, monkeypatch
):
    world, client = app
    services = client.app.state.services
    # Hosted in key order: the person's requests are reserved and committed before the tenant's.
    directory, package = write_registry(
        tmp_path, [person_entry(), person_like("tenant_decision", "tenant")]
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    manifest, (model_id, _other) = _offered_two()
    model = {"provider": manifest.spec(model_id).provider, "model_id": model_id}
    raced: list[str] = []
    #: This minute's reservations so far: each role's key, and whether it reserved a request.
    minute: list[tuple[str, bool]] = []
    prepare = SocietyDecisionRepository.prepare_role

    def racing(self, role, *args, **kwargs):
        # The tenant's first reservation in a minute the person has already reserved in meets the
        # race between reading an input's bytes and the asset read lock, once.
        if role.key == "tenant_decision" and not raced and ("society_decision", True) in minute:
            raced.append(role.key)
            raise SocietyBytesNotRead("a reviewed asset changed between the read and the lock")
        reserved, fresh = prepare(self, role, *args, **kwargs)
        minute.append((role.key, fresh and reserved["request"] is not None))
        return reserved, fresh

    with registry_in_use(directory, package) as registry:
        person, tenant = registry.role("society_decision"), registry.role("tenant_decision")
        assert [role.key for role in registry.hosted_by("exulanica-society/v2")] == [
            "society_decision",
            "tenant_decision",
        ]
        snapshot = stays._inhabited(world, client)
        people = sorted(person["id"] for person in snapshot["state"]["inhabitants"])
        half = len(people) // 2
        _choose(services, world, person, people[:half], model, manifest=manifest)
        _choose(services, world, tenant, people[half:], model, manifest=manifest)
        monkeypatch.setattr(SocietyDecisionRepository, "prepare_role", racing)
        transport = person_decisions._Chooser()
        host = person_decisions._host(
            world, person_decisions._client(manifest, transport), services, manifest
        )
        for _ in range(30):
            minute.clear()
            recorded = _minute(host, world, snapshot, services)
            if raced:
                break
            snapshot = stays._step(world, client, snapshot)
        else:
            raise AssertionError("the tenant never reserved after the person in one minute")
        receipts = _receipts(services, world, snapshot)
    # The positive control: the race was met in a minute both roles reserved in.
    assert raced == ["tenant_decision"]
    assert {receipt["profile"] for receipt in recorded} == {
        person.receipt_profile,
        tenant.receipt_profile,
    }
    assert _unanswered(services, world, snapshot) == 0, "a request was left without its receipt"
    assert {(r["status"], r["reason"]) for r in receipts} == {("accepted", "validated_choice")}
    assert transport.call_count == len(receipts)


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_role_with_slow_models_does_not_starve_the_role_after_it(app, tmp_path, monkeypatch):
    world, client = app
    services = client.app.state.services
    # Hosted in key order: the slow role is asked first, the quick one after it.
    directory, package = write_registry(
        tmp_path,
        [
            person_like("dawdler_decision", "dawdler"),
            person_entry(),
            person_like("sprinter_decision", "sprinter"),
        ],
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    manifest, (slow, quick) = _offered_two()
    monkeypatch.setattr(
        DecisionHost,
        "_ends_at",
        staticmethod(lambda _contract, _lease_ends: time.monotonic() + DEADLINE_SECONDS),
    )
    with registry_in_use(directory, package) as registry:
        dawdler, sprinter = registry.role("dawdler_decision"), registry.role("sprinter_decision")
        snapshot = stays._inhabited(world, client)
        people = sorted(person["id"] for person in snapshot["state"]["inhabitants"])
        half = len(people) // 2
        _choose(
            services,
            world,
            dawdler,
            people[:half],
            {"provider": manifest.spec(slow).provider, "model_id": slow},
            manifest=manifest,
        )
        _choose(
            services,
            world,
            sprinter,
            people[half:],
            {"provider": manifest.spec(quick).provider, "model_id": quick},
            manifest=manifest,
        )
        transport = _Slowly(slow)
        host = person_decisions._host(
            world, person_decisions._client(manifest, transport), services, manifest
        )
        for _ in range(30):
            began = time.monotonic()
            recorded = _minute(host, world, snapshot, services)
            took = time.monotonic() - began
            if {r["profile"] for r in recorded} == {
                dawdler.receipt_profile,
                sprinter.receipt_profile,
            }:
                break
            snapshot = stays._step(world, client, snapshot)
        else:
            raise AssertionError("both roles were never asked in one minute")
    quick_receipts = [r for r in recorded if r["profile"] == sprinter.receipt_profile]
    # The positive control: the slow role's models took their time, past its deadline.
    assert took >= SLOW_SECONDS
    assert quick_receipts
    assert {(r["status"], r["reason"]) for r in quick_receipts} == {
        ("accepted", "validated_choice")
    }
