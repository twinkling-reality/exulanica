"""Preparation in an installation: which preparers its profile installs, and who honours that.

A profile may declare its ``preparation`` component's preparers one by one
(``components.preparation.preparers``). Three readers take the same declaration:

*   **the facts** report each preparer's state, and judge the queue by the installed ones only,
    because a request for a preparer the installation does not run waits by design;
*   **the capability projection** decides an effect that names a preparer by that preparer's state;
*   **the worker** (``exulanica-asset-preparation``) runs the installed preparers and nothing else,
    and refuses to start, by name, when one it is told to run cannot run.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
from exulanica.api import capabilities
from exulanica.api.capabilities import Effect, unknown
from exulanica.api.installation import (
    MAINTENANCE_STATUS_PROFILE,
    Installation,
    InstallationRefused,
    installation_facts,
    load_profile,
)
from exulanica.orchestration.installation.preparation import (
    PreparerDeclarationRefused,
    declared_preparers,
)
from exulanica.world import character_parametric, static_glb
from exulanica.world.asset_preparation import PREPARERS

from test_installation_facts import _services
from test_purge import purged as purged

PROFILES = Path(__file__).resolve().parents[1] / "deploy" / "profiles"
STATIC = f"{static_glb.PREPARER_ID}@{static_glb.PREPARER_VERSION}"
BODY = f"{character_parametric.PREPARER_ID}@{character_parametric.PREPARER_VERSION}"


def _profile(tmp_path, change=None, name="single-host"):
    document = json.loads((PROFILES / f"{name}.json").read_text())
    if change is not None:
        change(document)
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(document))
    return path


def _preparers(document):
    return document["components"]["preparation"]["preparers"]


# -- the profile ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(lambda d: d["components"]["api"].__setitem__("preparers", {}), id="other"),
        pytest.param(
            lambda d: d["components"]["preparation"].__setitem__("installed", False),
            id="component-not-installed",
        ),
        pytest.param(
            lambda d: _preparers(d).__setitem__("static-glb", {"installed": True}), id="pin"
        ),
        pytest.param(lambda d: _preparers(d)[STATIC].__setitem__("installed", False), id="none"),
        pytest.param(
            lambda d: _preparers(d)[BODY].__setitem__("reason", "No Blender"), id="reason"
        ),
        pytest.param(lambda d: _preparers(d)[BODY].__setitem__("installed", "no"), id="bool"),
        pytest.param(lambda d: _preparers(d)[BODY].__setitem__("why", "x"), id="key"),
        pytest.param(
            lambda d: d["components"]["preparation"].__setitem__("preparers", {}), id="empty"
        ),
    ],
)
def test_a_preparer_declaration_stated_inexactly_is_refused(tmp_path, change):
    with pytest.raises(InstallationRefused) as refused:
        load_profile(_profile(tmp_path, change))
    assert refused.value.code == "profile_invalid"


def test_the_shipped_installation_profiles_declare_every_registered_preparer():
    registered = {f"{key[0]}@{key[1]}" for key in PREPARERS}
    for name in ("single-host", "single-host-server-only", "shared-store"):
        preparers = load_profile(PROFILES / f"{name}.json").components["preparation"].preparers
        assert preparers is not None and set(preparers) == registered
        assert preparers[STATIC].installed and not preparers[BODY].installed
        assert preparers[BODY].reason == "preparer_tool_absent"


# -- the worker -----------------------------------------------------------------------------------


def _environment(tmp_path, change=None, name="single-host"):
    return {"EXULANICA_INSTALLATION_PROFILE": str(_profile(tmp_path, change, name))}


def test_the_worker_runs_the_installed_preparers_and_nothing_else(tmp_path):
    chosen = declared_preparers(_environment(tmp_path))
    assert [f"{key[0]}@{key[1]}" for key in chosen] == [STATIC]
    # No profile, or a profile that names no preparer: every registered one the host can run.
    assert declared_preparers({}) is PREPARERS
    unnamed = declared_preparers(
        _environment(tmp_path, lambda d: d["components"]["preparation"].pop("preparers"))
    )
    assert unnamed is PREPARERS


@pytest.mark.parametrize(
    ("change", "name", "code"),
    [
        (None, "reviewer", "preparation_not_installed"),
        (
            lambda d: _preparers(d).__setitem__(
                "exulanica.unknown-preparer@1", {"installed": True}
            ),
            "single-host",
            "declared_preparer_unknown",
        ),
        (
            lambda d: _preparers(d)[STATIC].__setitem__("reason", "disk_full"),
            "single-host",
            "declared_preparer_unavailable",
        ),
    ],
)
def test_the_worker_refuses_a_declaration_it_cannot_honour(tmp_path, change, name, code):
    with pytest.raises(PreparerDeclarationRefused) as refused:
        declared_preparers(_environment(tmp_path, change, name))
    assert refused.value.code == code


def test_the_worker_refuses_to_start_when_an_installed_preparer_cannot_run_here(
    tmp_path, monkeypatch
):
    body = PREPARERS[(character_parametric.PREPARER_ID, character_parametric.PREPARER_VERSION)]
    monkeypatch.setattr(type(body), "available", lambda self: False)
    environment = _environment(
        tmp_path, lambda d: _preparers(d).__setitem__(BODY, {"installed": True})
    )
    with pytest.raises(PreparerDeclarationRefused) as refused:
        declared_preparers(environment)
    assert refused.value.code == "declared_preparer_unavailable"


# -- the capability projection --------------------------------------------------------------------


def test_an_effect_naming_a_preparer_takes_that_preparers_state():
    components = {
        "preparation": {
            "component": "preparation",
            "state": "configured",
            "preparers": [
                {"preparer": BODY, "state": "not_installed", "reason": "preparer_tool_absent"},
                {"preparer": STATIC, "state": "configured"},
            ],
        }
    }
    body = capabilities._effect(
        Effect("preparation", unknown(), component="preparation", preparer=BODY), components
    )
    static = capabilities._effect(
        Effect("preparation", unknown(), component="preparation", preparer=STATIC), components
    )
    assert (body.availability.state, body.availability.code) == (
        "unavailable",
        "preparer_tool_absent",
    )
    assert static.availability.state == "available"
    with pytest.raises(ValueError):
        Effect("playback", unknown(), component="simulation", preparer=STATIC)


# -- the facts ------------------------------------------------------------------------------------


def _status(path, preparers):
    path.write_text(
        json.dumps(
            {
                "profile": MAINTENANCE_STATUS_PROFILE,
                "written_at": dt.datetime.now(dt.UTC).isoformat(),
                "queues": {
                    "preparation": {
                        "oldest_queued_seconds": max(preparers.values(), default=0),
                        "preparers": preparers,
                    }
                },
                "failures": [],
                "withdrawal_export": {
                    "covered_through": dt.datetime.now(dt.UTC).isoformat(),
                    "lag_seconds": 1,
                },
                "last_verified_backup_at": "2026-09-30T00:00:00+00:00",
            }
        )
    )


def test_facts_report_each_preparer_and_judge_the_queue_by_the_installed_ones(purged, tmp_path):
    status = tmp_path / "maintenance.json"
    installation = Installation(
        profile=load_profile(PROFILES / "single-host.json"),
        code_revision=None,
        images={},
        maintenance_status_path=status,
    )

    def preparation():
        facts = installation_facts(_services(purged, installation))
        return next(entry for entry in facts["components"] if entry["component"] == "preparation")

    # A body request waiting an hour is not late: the installation does not run that preparer.
    _status(status, {BODY: 3600, STATIC: 10})
    entry = preparation()
    assert entry["state"] == "configured"
    assert entry["preparers"] == [
        {"preparer": BODY, "state": "not_installed", "reason": "preparer_tool_absent"},
        {"preparer": STATIC, "state": "configured"},
    ]
    installation._cache.clear()
    # A static request past the bound is.
    _status(status, {BODY: 3600, STATIC: 901})
    entry = preparation()
    assert (entry["state"], entry["reason"]) == ("degraded", "queue_progress_exceeds_bound")
    assert entry["preparers"][1] == {
        "preparer": STATIC,
        "state": "degraded",
        "reason": "queue_progress_exceeds_bound",
    }
