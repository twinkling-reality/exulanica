"""A start that nothing on the installation would play is refused, as its capability read says.

Where the API leaves its comparisons to a process of its own (``EXULANICA_COMPARISON_WORKER`` is
``process``) and the installation's profile declares that process, the ``comparison`` component,
not installed or unavailable, a start would wait for a host the installation does not run. So the
start, its plan and the version's capability read refuse it as ``comparisons_not_played``, read
from the installation's facts as a capability read reads them
(``Services.comparison_process_absent``). Where the API plays its comparisons itself the profile
changes nothing, and so does a process with no profile, which cannot see the component, or a
profile that installs it. Shown for comparisons of a world's people and of a town's signals, on
private PostgreSQL as the runtime role.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest
from exulanica.api.installation import (
    ComponentSpec,
    Installation,
    InstallationProfile,
    load_profile,
)

import test_signal_comparison_postgres as signals
import test_society_comparison_start_postgres as people
import test_society_stay_requests_api as stays
from test_comparison_plan_allowance_postgres import _plan_people
from test_comparison_start_allowance_postgres import (
    _operation,
    _people_capabilities,
    _signal_capabilities,
)
from test_signal_comparison_postgres import _presets_try_every_candidate, town
from test_society_comparison_start_postgres import saved_world, started

__all__ = ["_presets_try_every_candidate", "saved_world", "started", "town"]

pytestmark = pytest.mark.postgres

PROFILES = Path(__file__).resolve().parent.parent / "deploy" / "profiles"
START_PEOPLE = "POST /world/versions/{version_id}/society/comparisons"
START_SIGNALS = "POST /world/versions/{version_id}/traffic/comparisons"
NOT_PLAYED = "comparisons_not_played"
_EMPTY = {"society_comparison": 0, "society_comparison_run": 0, "society_comparison_start": 0}


def _profile(name: str) -> InstallationProfile:
    return load_profile(PROFILES / f"{name}.json")


def _installed(app: Any, profile: InstallationProfile | None, **changes: Any) -> None:
    """The application's services composed with an installation of ``profile`` (None for a process
    with no profile), as ``build_services`` composes every process."""
    installation = Installation(
        profile=profile, code_revision="a" * 40, images={}, maintenance_status_path=None
    )
    app.state.services = dataclasses.replace(
        app.state.services, installation=installation, **changes
    )


def _unavailable_here(profile: InstallationProfile) -> InstallationProfile:
    """``profile`` with its comparison process installed but declared unavailable here."""
    components = {
        **profile.components,
        "comparison": ComponentSpec(installed=True, unavailable_reason="comparison_host_absent"),
    }
    return dataclasses.replace(profile, components=components)


def _refused_alike(start: Any, plan: dict[str, Any], capability: dict[str, Any]) -> None:
    assert start.status_code == 409, start.text
    assert start.json()["code"] == NOT_PLAYED
    assert plan["refusal"]["code"] == NOT_PLAYED
    assert plan["plan"] is None and plan["plan_refusal"]["code"] == NOT_PLAYED
    assert (capability["state"], capability["code"]) == ("unavailable", NOT_PLAYED)


# -- the process that plays them is declared absent ----------------------------------------------


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_start_left_to_a_process_the_profile_does_not_install_is_refused(started):
    world = started["world"]
    stays._inhabited(world, started["client"])
    # The fixture leaves comparisons to a process of its own; the reviewer profile installs none.
    assert started["client"].app.state.services.comparisons_played_elsewhere
    _installed(started["client"].app, _profile("reviewer"))
    _refused_alike(
        people._start(started, people._body()),
        _plan_people(started).json(),
        _operation(_people_capabilities(started), START_PEOPLE),
    )
    assert people._counts(world) == _EMPTY


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_start_left_to_a_process_declared_unavailable_here_is_refused(started):
    world = started["world"]
    stays._inhabited(world, started["client"])
    _installed(started["client"].app, _unavailable_here(_profile("single-host")))
    _refused_alike(
        people._start(started, people._body()),
        _plan_people(started).json(),
        _operation(_people_capabilities(started), START_PEOPLE),
    )
    assert people._counts(world) == _EMPTY


def test_a_signal_start_left_to_a_process_the_profile_does_not_install_is_refused(town):
    _installed(town["api"].client.app, _profile("reviewer"))
    named = f"&model={signals.MODEL.provider}/{signals.MODEL.model_id}&seeds=2"
    plan = town["api"].get(signals._path(town, "/plan") + named)
    assert plan.status_code == 200, plan.text
    _refused_alike(
        signals._start(town, signals._body()),
        plan.json(),
        _operation(_signal_capabilities(town), START_SIGNALS),
    )
    assert signals._count(town, "signal_comparison") == 0


# -- what the profile does not change ------------------------------------------------------------


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_process_that_plays_its_own_comparisons_starts_whatever_its_profile_declares(started):
    """The default path: the API plays its comparisons in a thread of its own, so the reviewer
    profile's comparison process is not one it needs."""
    world = started["world"]
    stays._inhabited(world, started["client"])
    _installed(
        started["client"].app,
        _profile("reviewer"),
        runs_comparison_worker=True,
        comparisons_played_elsewhere=False,
    )
    capability = _operation(_people_capabilities(started), START_PEOPLE)
    assert (capability["state"], capability["code"]) == ("available", None)
    assert _plan_people(started).json()["refusal"] is None
    assert people._start(started, people._body()).status_code == 201


@pytest.mark.parametrize("saved_world", [2], indirect=True)
@pytest.mark.parametrize("profile", [None, "single-host"])
def test_no_profile_or_one_that_installs_the_process_refuses_nothing(started, profile):
    """A process with no profile cannot see the component (``undeclared_installation``), and a
    profile that installs it declares a process that plays the starts."""
    world = started["world"]
    stays._inhabited(world, started["client"])
    _installed(started["client"].app, None if profile is None else _profile(profile))
    assert _plan_people(started).json()["refusal"] is None
    assert people._start(started, people._body()).status_code == 201
