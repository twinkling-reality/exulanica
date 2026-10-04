"""Installation profiles are exact, and installation facts say what each component can do now.

The facts are read by the capability projection on every request, so they are held here to the
properties that projection relies on: the frozen component names and states, stable reason codes,
a bounded cache, no secret and no workspace content, and a serving gate that follows a restore.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from dataclasses import replace
from pathlib import Path

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.installation import (
    COMPONENTS,
    FACTS_CACHE_SECONDS,
    FACTS_PROFILE,
    MAINTENANCE_STATUS_PROFILE,
    STATES,
    Installation,
    InstallationRefused,
    installation_facts,
    load_installation,
    load_profile,
    paid_admission,
)
from exulanica.api.services import Services
from exulanica.deletion.restore import checkpoint, prepare_restore
from exulanica.store.configured import local_content_stores
from fastapi.testclient import TestClient

from test_purge import purged as purged
from tests_support_api import EVERY_PERMISSION

PROFILES = Path(__file__).resolve().parents[1] / "deploy" / "profiles"


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


_TOKEN = "installation-test-token-" + uuid.uuid4().hex


def _services(purged, installation=None, **changes):
    token = _TOKEN
    services = Services(
        database=purged.database(),
        readonly_database=purged.database(),
        store=purged.store,
        tokens=load_token_directory(
            {
                "EXULANICA_API_TOKENS": json.dumps(
                    {
                        token: {
                            "workspace_id": str(purged.workspace_id),
                            "actor": str(uuid.uuid4()),
                            "permissions": EVERY_PERMISSION,
                        }
                    }
                )
            }
        ),
        executor_shares_the_write_role=True,
        model_client=None,
        installation=installation,
    )
    return replace(services, **changes)


def _installation(profile="single-host", status=None, clock=None):
    return Installation(
        profile=load_profile(PROFILES / f"{profile}.json"),
        code_revision="a" * 40,
        images={"backend": "sha256:" + "b" * 64},
        maintenance_status_path=status,
        clock=clock or _Clock(),
    )


def _by_name(facts):
    return {entry["component"]: entry for entry in facts["components"]}


def _write_status(path, *, written_at=None, queues=None, failures=()):
    path.write_text(
        json.dumps(
            {
                "profile": MAINTENANCE_STATUS_PROFILE,
                "written_at": (written_at or dt.datetime.now(dt.UTC)).isoformat(),
                "queues": queues or {},
                "failures": list(failures),
                "withdrawal_export": {
                    "covered_through": dt.datetime.now(dt.UTC).isoformat(),
                    "lag_seconds": 12,
                },
                "last_verified_backup_at": "2026-09-30T00:00:00+00:00",
            }
        )
    )


def test_every_shipped_profile_declares_exactly_the_frozen_components():
    shipped = sorted(PROFILES.glob("*.json"))
    assert {path.stem for path in shipped} == {
        "public",
        "reviewer",
        "shared-store",
        "single-host",
        "single-host-server-only",
    }
    for path in shipped:
        profile = load_profile(path)
        assert tuple(profile.components) == COMPONENTS
        assert profile.id == path.stem
    assert load_profile(PROFILES / "shared-store.json").store_kind == "object"
    assert not load_profile(PROFILES / "reviewer.json").components["maintenance"].installed
    # The public server is the server-only installation with the tile worker, and nothing else.
    public = load_profile(PROFILES / "public.json")
    server_only = load_profile(PROFILES / "single-host-server-only.json")
    assert public.components["generated_tiles"].installed
    assert {
        name: spec for name, spec in public.components.items() if name != "generated_tiles"
    } == {name: spec for name, spec in server_only.components.items() if name != "generated_tiles"}
    assert public.recovery == server_only.recovery


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (lambda d: d["components"].pop("comparison"), "profile_invalid"),
        (lambda d: d["components"].__setitem__("weather", {"installed": True}), "profile_invalid"),
        (lambda d: d.__setitem__("secret", "x"), "profile_invalid"),
        (lambda d: d["recovery"].__setitem__("max_export_lag_seconds", 1), "profile_invalid"),
        (lambda d: d["recovery"].__setitem__("backup_interval_seconds", 0), "profile_invalid"),
        (
            lambda d: d["components"]["pose_scene"].__setitem__("unavailable_reason", "No GPU!"),
            "profile_invalid",
        ),
        (
            lambda d: d["components"]["api"].__setitem__("queue_bound_seconds", 5),
            "profile_invalid",
        ),
        (lambda d: d["components"]["api"].__setitem__("installed", False), "profile_invalid"),
        (
            lambda d: d["settings_owners"]["R1"].append("EXULANICA_SPENDING"),
            "profile_invalid",
        ),
        (lambda d: d["settings_owners"].__setitem__("someone", []), "profile_invalid"),
    ],
)
def test_a_profile_that_states_anything_inexactly_is_refused(tmp_path, change, code):
    document = json.loads((PROFILES / "single-host.json").read_text())
    change(document)
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(document))
    with pytest.raises(InstallationRefused) as refused:
        load_profile(path)
    assert refused.value.code == code


def test_startup_refuses_an_unreadable_profile_or_an_unpinned_identity(tmp_path):
    with pytest.raises(InstallationRefused, match="profile_unreadable"):
        load_installation({"EXULANICA_INSTALLATION_PROFILE": str(tmp_path / "missing.json")})
    with pytest.raises(InstallationRefused, match="identity_invalid"):
        load_installation({"EXULANICA_IMAGE_BACKEND": "exulanica:latest"})
    with pytest.raises(InstallationRefused, match="identity_invalid"):
        load_installation({"EXULANICA_CODE_REVISION": "main"})
    assert load_installation({}).profile is None


def test_facts_use_frozen_names_and_states_and_carry_no_secret(purged, tmp_path, monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", "a-secret-that-must-not-leave")
    facts = installation_facts(_services(purged, _installation()))
    assert facts["profile"] == FACTS_PROFILE
    assert [entry["component"] for entry in facts["components"]] == list(COMPONENTS)
    assert {entry["state"] for entry in facts["components"]} <= set(STATES)
    assert "a-secret-that-must-not-leave" not in json.dumps(facts)
    assert str(purged.workspace_id) not in json.dumps(facts)
    assert facts["identity"]["code_revision"] == "a" * 40
    components = _by_name(facts)
    assert components["database"]["state"] == "ready"
    # Installed, with no maintenance status yet to observe its queue; each preparer as declared.
    assert components["preparation"] == {
        "component": "preparation",
        "state": "degraded",
        "reason": "queue_progress_unobserved",
        "preparers": [
            {
                "preparer": "exulanica.makehuman-parametric-preparer@1",
                "state": "not_installed",
                "reason": "preparer_tool_absent",
            },
            {
                "preparer": "exulanica.static-glb-preparer@1",
                "state": "degraded",
                "reason": "queue_progress_unobserved",
            },
        ],
    }
    assert {one["state"] for one in components["preparation"]["preparers"]} <= set(STATES)


def test_the_schema_is_ready_only_when_applied_equals_expected(purged, monkeypatch):
    from exulanica.migrations import migrations

    expected = [migration.version for migration in migrations()]
    # A schema that records no applied version is a mismatch. Set here rather than assumed of the
    # shared test schema, whose versions another test's fixture may have recorded.
    monkeypatch.setattr("exulanica.db.migrate.applied_migrations", lambda _c: [])
    facts = installation_facts(_services(purged, _installation()))
    assert _by_name(facts)["schema"] == {
        "component": "schema",
        "state": "unavailable",
        "reason": "schema_mismatch",
        "observed": {"expected": expected[-1], "applied": None},
    }
    monkeypatch.setattr("exulanica.db.migrate.applied_migrations", lambda _c: list(expected))
    facts = installation_facts(_services(purged, _installation()))
    assert _by_name(facts)["schema"] == {"component": "schema", "state": "ready"}
    assert facts["identity"]["schema"] == {"expected": expected[-1], "applied": expected[-1]}


def test_no_model_mode_still_serves_and_says_what_it_cannot_do(purged):
    facts = installation_facts(_services(purged, _installation()))
    assert facts["models"] == {
        "mode": "no_model",
        "paid_admission": {"state": "blocked", "reason": "provider_credential_absent"},
    }
    components = _by_name(facts)
    assert components["ingestion"]["reason"] == "provider_credential_absent"
    assert components["ingestion"]["state"] == "degraded"
    assert components["comparison"]["state"] == "unavailable"
    assert facts["serving"] == {"state": "open"}


def test_a_server_only_image_reports_its_workers_unavailable_not_absent(purged):
    components = _by_name(
        installation_facts(_services(purged, _installation("single-host-server-only")))
    )
    for name in ("derivatives", "pose_scene"):
        assert components[name]["state"] == "unavailable"
        assert components[name]["reason"] == "image_built_without_extra"


def test_queue_progress_comes_from_a_fresh_maintenance_status_only(purged, tmp_path):
    status = tmp_path / "maintenance-status.json"
    missing = _by_name(installation_facts(_services(purged, _installation(status=status))))
    assert missing["maintenance"]["reason"] == "maintenance_status_missing"
    assert missing["derivatives"]["reason"] == "queue_progress_unobserved"

    _write_status(status, queues={"derivatives": {"oldest_queued_seconds": 901}})
    facts = installation_facts(_services(purged, _installation(status=status)))
    components = _by_name(facts)
    assert components["maintenance"]["state"] == "ready"
    assert components["derivatives"] == {
        "component": "derivatives",
        "state": "degraded",
        "reason": "queue_progress_exceeds_bound",
        "observed": {"oldest_queued_seconds": 901, "bound_seconds": 900},
    }
    assert facts["recovery"]["withdrawal_authority"]["lag_seconds"] == 12

    stale = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=601)
    _write_status(status, written_at=stale, queues={"derivatives": {"oldest_queued_seconds": 1}})
    components = _by_name(installation_facts(_services(purged, _installation(status=status))))
    assert components["maintenance"]["state"] == "degraded"
    assert components["derivatives"]["reason"] == "queue_progress_unobserved"


def test_observations_are_cached_for_the_stated_bound_only(purged, tmp_path):
    clock = _Clock()
    status = tmp_path / "maintenance-status.json"
    installation = _installation(status=status, clock=clock)
    services = _services(purged, installation)
    first = installation_facts(services)
    _write_status(status)
    clock.now += FACTS_CACHE_SECONDS - 0.5
    assert installation_facts(services)["observed_at"] == first["observed_at"]
    clock.now += 1
    later = installation_facts(services)
    assert later["observed_at"] != first["observed_at"]
    assert _by_name(later)["maintenance"]["state"] == "ready"


def test_a_pending_restore_refuses_serving_within_the_bound(purged, tmp_path):
    clock = _Clock()
    services = _services(purged, _installation(clock=clock))
    assert installation_facts(services)["serving"] == {"state": "open"}
    # Sealing the source for a planned restore closes writes within the cache bound.
    source = tmp_path / "custody" / "checkpoint.json"
    checkpoint(purged.database(), source)
    clock.now += FACTS_CACHE_SECONDS
    facts = installation_facts(services)
    assert facts["serving"] == {"state": "refused", "reason": "restore_pending"}
    assert facts["recovery"]["restore_state"] == "sealed"
    # A configured marker still pending refuses too, as startup does.
    marker = tmp_path / "control" / "restore.json"
    prepare_restore(source, marker)
    pending = installation_facts(_services(purged, _installation(), restore_state_path=marker))
    assert pending["serving"] == {"state": "refused", "reason": "restore_pending"}


def test_an_undeclared_process_says_only_what_it_can_see(purged):
    facts = installation_facts(_services(purged))
    assert facts["installation"] is None
    components = _by_name(facts)
    assert components["client"] == {
        "component": "client",
        "state": "not_installed",
        "reason": "undeclared_installation",
    }
    assert components["maintenance"]["reason"] == "undeclared_installation"


def test_public_readiness_carries_no_identity_or_recovery_fields(purged, tmp_path):
    status = tmp_path / "maintenance-status.json"
    _write_status(status)
    services = _services(purged, _installation(status=status))
    # The full document holds every field the public summary must not.
    full = json.dumps(installation_facts(services))
    for private in ("a" * 40, "b" * 64, "configuration_sha256", "covered_through", "observed_at"):
        assert private in full, private
    app = create_app(services, verify=False)
    with TestClient(app) as client:
        body = client.get("/readyz").json()
    summary = body["installation"]
    assert set(summary) == {"installation", "serving", "components"}
    assert summary["installation"] == {"id": "single-host", "version": 1}
    assert [entry["component"] for entry in summary["components"]] == list(COMPONENTS)
    assert all(set(entry) <= {"component", "state", "reason"} for entry in summary["components"])
    text = json.dumps(summary)
    for private in ("a" * 40, "b" * 64, "configuration_sha256", "covered_through", "observed_at"):
        assert private not in text


def test_an_authorised_operator_reads_the_whole_document(purged):
    services = _services(purged, _installation())
    app = create_app(services, verify=False)
    with TestClient(app) as client:
        assert client.get("/operations/installation").status_code == 401
        body = client.get(
            "/operations/installation", headers={"Authorization": f"Bearer {_TOKEN}"}
        ).json()
    assert body["profile"] == FACTS_PROFILE
    assert body["identity"]["code_revision"] == "a" * 40
    assert body["identity"]["images"] == {"backend": "sha256:" + "b" * 64}


def test_paid_admission_says_how_spending_is_bounded_and_why_it_is_blocked():
    def authority(state, **more):
        return {"authority_id": "a", "provider": "p", "state": state, **more}

    def admission(mode, found):
        return paid_admission(no_model=False, spending_mode=mode, authorities=found)

    assert admission("process", None) == {
        "state": "open",
        "spending": "process",
        "restore_protection": "none",
    }
    assert admission("durable", [authority("active")])["state"] == "open"
    # A restored database is behind its witness: the allowance is not handed back.
    suspended = admission(
        "durable",
        [authority("suspended", suspension="ledger_behind_witness"), authority("revoked")],
    )
    assert (suspended["state"], suspended["reason"], suspended["suspensions"]) == (
        "blocked",
        "spending_suspended",
        ["ledger_behind_witness"],
    )
    assert admission("durable", [])["reason"] == "no_active_authority"
    assert admission("durable", [{"state": "unreadable"}])["state"] == "unknown"


def test_a_durable_process_reports_its_authorities_without_amounts(purged, monkeypatch):
    found = [
        {
            "authority_id": str(uuid.uuid4()),
            "provider": "nebius",
            "state": "suspended",
            "restore_protection": "witnessed",
            "epoch": 2,
            "suspension": "witness_behind",
        }
    ]
    monkeypatch.setattr("exulanica.spending.status.authority_states", lambda _database: found)
    services = _services(purged, _installation(), model_client=object(), spending_mode="durable")
    admission = installation_facts(services)["models"]["paid_admission"]
    assert admission["reason"] == "spending_suspended" and admission["authorities"] == found


def test_the_store_the_process_built_must_be_the_profiles(purged, tmp_path):
    profile = PROFILES / "shared-store.json"
    with pytest.raises(InstallationRefused, match="store_kind_conflict"):
        load_installation({"EXULANICA_INSTALLATION_PROFILE": str(profile)})
    with pytest.raises(InstallationRefused, match="store_kind_conflict"):
        load_installation(
            {
                "EXULANICA_INSTALLATION_PROFILE": str(PROFILES / "single-host.json"),
                "EXULANICA_STORE_KIND": "object",
            }
        )
    stores = local_content_stores(purged.store.root.parent)
    facts = installation_facts(_services(purged, _installation(), content_stores=stores))
    assert facts["store"]["configured_kind"] == "local" and facts["store"]["matches_profile"]
    assert facts["store"]["description"]["location_sha256"] == stores.location_sha256
    assert str(purged.store.root.parent) not in json.dumps(facts)


def test_a_process_that_cannot_write_its_witness_is_refused_alone():
    witnessed = {"authority_id": "a", "provider": "p", "state": "active"}
    witnessed["restore_protection"] = "witnessed"
    unwitnessed = {**witnessed, "authority_id": "b", "restore_protection": "none"}

    def admission(found, process_witness):
        return paid_admission(
            no_model=False,
            spending_mode="durable",
            authorities=found,
            process_witness=process_witness,
        )

    assert admission([witnessed], "marked")["state"] == "open"
    for state, code in (
        ("unmarked", "witness_directory_mismatch"),
        ("not_configured", "witness_not_configured"),
        ("unreadable", "witness_unreadable"),
    ):
        refused = admission([witnessed], state)
        assert (refused["state"], refused["process_refusal"]) == ("blocked", code)
        # The authority is not suspended: nothing is listed as a suspension.
        assert "suspensions" not in refused and refused["process_witness"] == state
    # An unwitnessed authority does not need this process's witness.
    assert admission([witnessed, unwitnessed], "unmarked")["state"] == "open"


def test_facts_read_this_processs_witness_directory_marker(purged, tmp_path, monkeypatch):
    from types import SimpleNamespace

    from exulanica.spending.witness import FileSpendingWitness

    found = [
        {
            "authority_id": str(uuid.uuid4()),
            "provider": "nebius",
            "state": "active",
            "restore_protection": "witnessed",
            "epoch": 1,
        }
    ]
    monkeypatch.setattr("exulanica.spending.status.authority_states", lambda _database: found)
    witness = FileSpendingWitness(tmp_path / "witness")
    spending = SimpleNamespace(witness=witness)
    services = _services(
        purged, _installation(), model_client=object(), spending_mode="durable", spending=spending
    )
    admission = installation_facts(services)["models"]["paid_admission"]
    assert admission["process_refusal"] == "witness_directory_mismatch"
    witness.ensure_directory_id()
    services = _services(
        purged, _installation(), model_client=object(), spending_mode="durable", spending=spending
    )
    assert installation_facts(services)["models"]["paid_admission"]["state"] == "open"
