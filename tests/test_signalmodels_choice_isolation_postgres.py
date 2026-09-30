"""One subject cannot be selected for two hosted decision roles at once."""

from __future__ import annotations

import uuid

import pytest
from exulanica.world.society_model_choice_repository import (
    ModelChoiceRefused,
    SocietyModelChoiceRepository,
)

import test_decision_host_roles_postgres as roles
import test_society_stay_requests_api as stays
from decision_role_support import person_entry, person_like, registry_in_use, write_registry

app = stays.app
saved_world = stays.saved_world
pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_subject_chosen_under_one_role_cannot_be_chosen_under_another(
    app, tmp_path, monkeypatch
):
    world, client = app
    services = client.app.state.services
    directory, package = write_registry(
        tmp_path, [person_entry(), person_like("tenant_decision", "tenant")]
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    manifest, (model_id, _other) = roles._offered_two()
    model = {"provider": manifest.spec(model_id).provider, "model_id": model_id}
    with registry_in_use(directory, package) as registry:
        person = registry.role("society_decision")
        tenant = registry.role("tenant_decision")
        snapshot = stays._inhabited(world, client)
        subject = snapshot["state"]["inhabitants"][0]["id"]
        roles._choose(services, world, person, [subject], model, manifest=manifest)
        with services.database.session(world["workspace"]) as connection:
            repository = SocietyModelChoiceRepository(
                connection, world["workspace"], world_id=world["binding"].world_id
            )
            with pytest.raises(ModelChoiceRefused) as refused:
                repository.record_choice(
                    world["binding"].version_id,
                    tenant,
                    request_id=uuid.uuid4(),
                    subjects=[subject],
                    model=model,
                    chosen_by=world["session"].actor,
                    manifest=manifest,
                    contract=tenant.contract(),
                )
            assert refused.value.code == "subject_chosen_under_another_role"
            assert (
                repository.current(world["binding"].version_id, person)[subject]["model"] == model
            )
            assert subject not in repository.current(world["binding"].version_id, tenant)


def _two_chosen_roles(app, tmp_path, monkeypatch):
    world, client = app
    services = client.app.state.services
    directory, package = write_registry(
        tmp_path, [person_entry(), person_like("tenant_decision", "tenant")]
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    manifest, (model_id, _other) = roles._offered_two()
    model = {"provider": manifest.spec(model_id).provider, "model_id": model_id}
    return world, client, services, directory, package, manifest, model


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_failed_second_role_reservation_does_not_drop_the_first_roles_answer(
    app, tmp_path, monkeypatch
):
    from exulanica.api.decision_host import DecisionHost

    world, client, services, directory, package, manifest, model = _two_chosen_roles(
        app, tmp_path, monkeypatch
    )
    original = DecisionHost._reserved
    first_tick = None
    failed = []

    def one_role_fails(self, connection, claim, decisions, row, role, *args):
        nonlocal first_tick
        if role.key == "tenant_decision" and first_tick == row["current_tick"] and not failed:
            failed.append(row["current_tick"])
            raise RuntimeError("the second role cannot reserve")
        result = original(self, connection, claim, decisions, row, role, *args)
        if role.key == "society_decision" and result[0]:
            first_tick = row["current_tick"]
        return result

    with registry_in_use(directory, package) as registry:
        person, tenant = registry.role("society_decision"), registry.role("tenant_decision")
        snapshot = stays._inhabited(world, client)
        people = sorted(p["id"] for p in snapshot["state"]["inhabitants"])
        half = len(people) // 2
        roles._choose(services, world, person, people[:half], model, manifest=manifest)
        roles._choose(services, world, tenant, people[half:], model, manifest=manifest)
        monkeypatch.setattr(DecisionHost, "_reserved", one_role_fails)
        transport = roles.person_decisions._Chooser()
        host = roles.person_decisions._host(
            world, roles.person_decisions._client(manifest, transport), services, manifest
        )
        for _ in range(30):
            recorded = roles._minute(host, world, snapshot, services)
            if failed:
                break
            snapshot = stays._step(world, client, snapshot)
        else:
            raise AssertionError("both roles were never due in one minute")
    assert failed
    assert any(receipt["profile"] == person.receipt_profile for receipt in recorded)
    assert all(receipt["profile"] != tenant.receipt_profile for receipt in recorded)


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_failed_first_role_recording_does_not_drop_the_second_roles_paid_answer(
    app, tmp_path, monkeypatch
):
    from exulanica.api.decision_host import DecisionHost
    from exulanica.world.society_decision_repository import SocietyDecisionRepository

    world, client, services, directory, package, manifest, model = _two_chosen_roles(
        app, tmp_path, monkeypatch
    )
    original_reserve = DecisionHost._reserved
    original_finish = SocietyDecisionRepository.finish
    reserved: dict[str, str] = {}
    failed = []

    def collect(self, connection, claim, decisions, row, role, *args):
        asks, refused = original_reserve(self, connection, claim, decisions, row, role, *args)
        if asks:
            reserved[role.key] = asks[0].request["request_id"]
        return asks, refused

    def fail_first(self, version_id, request_id, result, *, last_try):
        if (
            not failed
            and "tenant_decision" in reserved
            and str(request_id) == reserved.get("society_decision")
        ):
            failed.append(str(request_id))
            raise RuntimeError("the first role cannot record")
        return original_finish(self, version_id, request_id, result, last_try=last_try)

    with registry_in_use(directory, package) as registry:
        person, tenant = registry.role("society_decision"), registry.role("tenant_decision")
        snapshot = stays._inhabited(world, client)
        people = sorted(p["id"] for p in snapshot["state"]["inhabitants"])
        half = len(people) // 2
        roles._choose(services, world, person, people[:half], model, manifest=manifest)
        roles._choose(services, world, tenant, people[half:], model, manifest=manifest)
        monkeypatch.setattr(DecisionHost, "_reserved", collect)
        monkeypatch.setattr(SocietyDecisionRepository, "finish", fail_first)
        transport = roles.person_decisions._Chooser()
        host = roles.person_decisions._host(
            world, roles.person_decisions._client(manifest, transport), services, manifest
        )
        for _ in range(30):
            reserved.clear()
            recorded = roles._minute(host, world, snapshot, services)
            if failed:
                break
            snapshot = stays._step(world, client, snapshot)
        else:
            raise AssertionError("both roles were never due in one minute")
    assert failed
    assert any(receipt["profile"] == tenant.receipt_profile for receipt in recorded)
    assert transport.call_count >= 2, "both roles' asks reached the model before recording"
