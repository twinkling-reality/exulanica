"""A world's capability read states the installation it runs on, read once per request.

Where a process was composed with an installation, each capability read reads the installation's
facts (:func:`exulanica.api.installation.installation_facts`) once and projects them: an operation
that needs a component the installation declares not installed is unavailable by it, a component a
process without an installation profile cannot see is listed and decides nothing, and an
installation that refuses to serve while a restore is incomplete closes every write. A process
composed with no installation reads no facts. Shown on comparisons of a world's people and of a
town's signals, which need the installation's comparison component.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest
from exulanica.api import capabilities as capabilities_module
from exulanica.api.installation import Installation, installation_facts, load_profile
from fastapi import FastAPI

import personal_world_support as personal
import test_society_comparison_start_postgres as people
import test_society_stay_requests_api as stays
from test_signal_comparison_postgres import _presets_try_every_candidate, town
from test_society_comparison_start_postgres import saved_world, started

__all__ = ["_presets_try_every_candidate", "saved_world", "started", "town"]

PROFILES = Path(__file__).resolve().parents[1] / "deploy" / "profiles"
START_PEOPLE = "POST /world/versions/{version_id}/society/comparisons"
CANCEL_PEOPLE = "POST /world/versions/{version_id}/society/comparisons/{comparison_id}/cancel"
START_SIGNALS = "POST /world/versions/{version_id}/traffic/comparisons"
TRAFFIC = "GET /world/versions/{version_id}/traffic"


def _installed(app: FastAPI, profile: str | None, **changes: Any) -> None:
    """The application's services composed with an installation: a profile of deploy/profiles,
    or None for a process with no profile."""
    installation = Installation(
        profile=None if profile is None else load_profile(PROFILES / f"{profile}.json"),
        code_revision="a" * 40,
        images={},
        maintenance_status_path=None,
    )
    app.state.services = dataclasses.replace(
        app.state.services, installation=installation, **changes
    )


def _reads(monkeypatch) -> list[int]:
    """One entry for every installation facts read a capability read makes from now on."""
    read = capabilities_module.installation_facts
    seen: list[int] = []

    def counted(services, **kwargs):
        seen.append(1)
        return read(services, **kwargs)

    monkeypatch.setattr(capabilities_module, "installation_facts", counted)
    return seen


def _operation(document: dict[str, Any], operation: str) -> dict[str, Any]:
    (found,) = [row for row in document["operations"] if row["operation"] == operation]
    return found


def _people(held: dict[str, Any], suffix: str = "/capabilities") -> dict[str, Any]:
    world = held["world"]
    read = held["client"].get(
        f"/world/versions/{world['binding'].version_id}{suffix}",
        headers=people.OWNER,
        params=people._scope(world),
    )
    assert read.status_code == 200, read.text
    return read.json()


def _signals(held: dict[str, Any]) -> dict[str, Any]:
    entry = held["entry"]
    read = held["api"].get(
        f"/world/versions/{entry['authored_version_id']}/capabilities?world_id={entry['world_id']}",
        token=personal.OWNER_TOKEN,
    )
    assert read.status_code == 200, read.text
    return read.json()


@pytest.mark.postgres
@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_composed_installation_is_read_once_per_request_and_none_without_one(
    started, monkeypatch
):
    stays._inhabited(started["world"], started["client"])
    reads = _reads(monkeypatch)
    plain = _people(started)
    assert reads == [], "a process composed with no installation reads no facts"
    assert _operation(plain, START_PEOPLE)["dependencies"] == []

    _installed(started["client"].app, "single-host")
    for suffix in ("/capabilities", "/models"):
        before = len(reads)
        _people(started, suffix)
        assert len(reads) - before == 1, suffix
    before = len(reads)
    creation = started["client"].get("/worlds/capabilities", headers=people.OWNER)
    assert creation.status_code == 200, creation.text
    assert len(reads) - before == 1


@pytest.mark.postgres
@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_declared_component_refuses_and_an_undeclared_one_only_says_so(started):
    stays._inhabited(started["world"], started["client"])
    app = started["client"].app
    # Before any installation the start is available here: the fixture plays comparisons elsewhere.
    assert _operation(_people(started), START_PEOPLE)["state"] == "available"

    _installed(app, "reviewer")
    (comparison,) = [
        entry
        for entry in installation_facts(app.state.services)["components"]
        if entry["component"] == "comparison"
    ]
    assert comparison["state"] == "not_installed" and "reason" not in comparison
    declared = _operation(_people(started), START_PEOPLE)
    # The start's own refusal comes first; only where it allows the start does the component's
    # state refuse it, by its code where the installation gives no reason.
    own = app.state.services.comparison_refusal(started["world"]["workspace"])
    assert (declared["state"], declared["code"]) == (
        "unavailable",
        own or "comparison_not_installed",
    )
    assert declared["dependencies"] == [
        {"component": "comparison", "state": "not_installed", "code": None}
    ]

    _installed(app, None)
    undeclared = _operation(_people(started), START_PEOPLE)
    assert (undeclared["state"], undeclared["code"]) == ("available", None)
    assert undeclared["dependencies"] == [
        {"component": "comparison", "state": "not_installed", "code": "undeclared_installation"}
    ]


@pytest.mark.postgres
@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_an_installation_that_refuses_to_serve_closes_every_write(started, tmp_path):
    stays._inhabited(started["world"], started["client"])
    app = started["client"].app
    marker = tmp_path / "restore.json"
    marker.write_text(json.dumps({"profile": "exulanica.restore-state/v1", "state": "pending"}))
    _installed(app, "single-host", restore_state_path=marker)
    serving = installation_facts(app.state.services)["serving"]
    assert serving["state"] == "refused", serving
    document = _people(started)
    writes = [row for row in document["operations"] if row["writes"]]
    assert writes and {(row["state"], row["code"]) for row in writes} == {
        ("unavailable", serving["reason"])
    }
    assert _operation(document, CANCEL_PEOPLE)["code"] == serving["reason"]
    assert _operation(document, TRAFFIC)["code"] != serving["reason"]


@pytest.mark.postgres
def test_a_start_of_signals_needs_the_comparison_component(town):
    app = town["api"].client.app
    _installed(app, "reviewer")
    start = _operation(_signals(town), START_SIGNALS)
    assert start["dependencies"] == [
        {"component": "comparison", "state": "not_installed", "code": None}
    ]
    own = app.state.services.signal_comparison_refusal(town["repository"].workspace_id)
    assert (start["state"], start["code"]) == ("unavailable", own or "comparison_not_installed")


@pytest.mark.postgres
@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_town_is_not_offered_where_nothing_bakes_its_tiles(started):
    """A generated world is drawn only from tiles a bake worker makes, so an installation that
    runs none lists its creation unavailable, by the component; an undeclared process decides
    nothing, and the starter, which bakes nothing, is untouched."""
    app = started["client"].app
    # A store to serve tiles from, so the component's state is the profile's declaration; a
    # process with no tile store reports it unavailable (tile_store_absent), which refuses too.
    tiles = app.state.services.store

    def creation():
        read = started["client"].get("/worlds/capabilities", headers=people.OWNER)
        assert read.status_code == 200, read.text
        return {row["kind"]: row["create"] for row in read.json()["kinds"]}

    _installed(app, None, tiles=tiles)
    undeclared = creation()["generated"]
    assert undeclared["code"] != "generated_tiles_not_installed"
    assert undeclared["dependencies"] == [
        {
            "component": "generated_tiles",
            "state": "not_installed",
            "code": "undeclared_installation",
        }
    ]
    for profile in ("single-host", "reviewer"):
        _installed(app, profile, tiles=tiles)
        kinds = creation()
        generated = kinds["generated"]
        if generated["code"] != "world_limit_reached":
            assert (generated["state"], generated["code"]) == (
                "unavailable",
                "generated_tiles_not_installed",
            ), profile
        assert generated["dependencies"] == [
            {"component": "generated_tiles", "state": "not_installed", "code": None}
        ]
        assert (
            "dependencies" not in kinds["authored-starter"]
            or not kinds["authored-starter"]["dependencies"]
        )
