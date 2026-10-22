"""A served starter: a shipped kind whose worlds start on a setting, a named landscape in the
settings catalog. The catalog reads and holds each landscape as every landscape is held; only the
shipped document itself starts there, never a workspace's kind of the same key; a world of it made
with no land, landscape or support of its own is composed on its setting's island, arriving with
something in view, and drawn in the setting parts its setting names over the host's look."""

from __future__ import annotations

import copy
import json
import re
from typing import Any

import pytest
from exulanica.grammar import landscape as landscapes
from exulanica.grammar.errors import CatalogError
from exulanica.grammar.landscape import landscape_settings, read_settings, starting_setting
from exulanica.grammar.landscape.settings import SETTINGS_DIRECTORY, SETTINGS_VERSION
from exulanica.world.composers import site_plan
from exulanica.world.kinds import worker
from exulanica.world.kinds.document import read_kind
from exulanica.world.kinds.library import (
    shipped_kinds,
    starter_landscape,
    starter_look,
    starter_setting_parts,
)
from exulanica.world.kinds.samples import SiteRefused, check_samples
from exulanica.world.style_pack_library import style_pack_library

WORLD = "world:generated:starter"
SHIPPED = json.loads(
    (SETTINGS_DIRECTORY / f"landscape-setting.v{SETTINGS_VERSION}.json").read_text(encoding="utf-8")
)


def island_hamlet() -> Any:
    return next(kind for kind in shipped_kinds() if kind.kind == "island_hamlet")


def test_the_shipped_setting_stands_the_island_hamlet_on_a_sky_island_over_the_bay():
    (setting,) = landscape_settings()
    assert (setting.key, setting.label) == ("island_over_the_bay", "Sky island over the bay")
    assert setting.starters == (("island_hamlet", 1),)
    assert setting.setting_parts == (("sky", "clear_noon"),)
    assert starting_setting("island_hamlet", 1) is setting
    assert starting_setting("island_hamlet", 2) is None and starting_setting("town", 1) is None
    landscape = setting.landscape()
    assert landscape["site"]["on"] == "isle"
    # A copy each time: what one caller changes, the next never sees.
    landscape["site"]["on"] = "elsewhere"
    assert setting.landscape()["site"]["on"] == "isle"


@pytest.mark.parametrize("kind", shipped_kinds(), ids=lambda kind: kind.kind)
def test_every_shipped_kind_passes_both_stages_of_the_checks(kind):
    # Stage A is reading it (the library reads every file); stage B is its sample worlds.
    assert check_samples(kind)["verdict"] == "passed"


def test_only_the_shipped_document_itself_starts_on_its_setting():
    kind = island_hamlet()
    assert kind.label == "Hamlet on a sky island" and kind.origin == "authored"
    assert starter_landscape(kind) == landscape_settings()[0].landscape()
    # A workspace's kind of the same key and version, its words changed, is its own kind.
    own = copy.deepcopy(dict(kind.document))
    own["summary"] = "Our own hamlet, on open ground."
    assert starter_landscape(read_kind(own)) is None


def test_a_starter_is_made_on_its_island_arriving_with_something_in_view():
    kind = island_hamlet()
    values = kind.values(kind.presets[0][0])
    made = site_plan.compose_kind(
        kind, values, WORLD, place_id="place:isle", landscape=starter_landscape(kind)
    )
    assert made.receipt["composer"] == {"key": "site-plan", "version": 7}
    assert made.receipt["landscape"]["site"]["on"] == "isle"
    fx, fy = made.receipt["arrival"]["facing_mm"]
    assert 990 <= abs(complex(fx, fy)) <= 1001


def test_the_worker_composes_a_starter_on_its_setting_unless_its_making_names_its_own(
    monkeypatch: pytest.MonkeyPatch,
):
    asked: list[tuple[Any, ...]] = []

    class Outcome:
        status = "done"
        reason = None

        def __init__(self) -> None:
            self.value = {"status": "refused", "code": "site_refused", "refusals": []}

    class Worker:
        epoch = 0

        def run(self, key: str, seconds: float, job: Any, *args: Any, **kwargs: Any) -> Outcome:
            asked.append((key, *args))
            return Outcome()

    monkeypatch.setattr(worker, "kind_worker", Worker)
    kind = island_hamlet()
    values = kind.values(kind.presets[0][0])
    for composer in (
        worker.WorkerComposer("ws"),
        worker.WorkerComposer("ws", land={"profile": "x"}),
    ):
        with pytest.raises(SiteRefused):
            composer(kind, values, WORLD)
    started, named = asked
    # Made from its card: on the setting's landscape, kept apart from any other making by it.
    assert started[-2:] == (None, landscape_settings()[0].landscape())
    assert ":landscape:" in started[0]
    # Made with land of its own: that land, and no setting.
    assert named[-2:] == ({"profile": "x"}, None)
    assert ":landscape:" not in named[0]


def _catalog(change: Any) -> dict[str, Any]:
    raw = copy.deepcopy(SHIPPED)
    change(raw)
    return raw


@pytest.mark.parametrize(
    ("change", "where"),
    [
        (lambda raw: raw.update(catalog_version=1), "catalog_version"),
        (lambda raw: raw["entries"].append(copy.deepcopy(raw["entries"][0])), "entries"),
        (lambda raw: raw["entries"][0]["landscape"]["site"].update(on="nowhere"), "landscape"),
        (lambda raw: raw["entries"][0].update(starters=[]), "starters"),
        (lambda raw: raw["entries"][0]["starters"][0].update(version=0), "version"),
        (lambda raw: raw["entries"][0].update(reason="Too short."), "reason"),
        (lambda raw: raw["entries"][0]["licence"].update(spdx="GPL-3.0"), "licence"),
        (lambda raw: raw["entries"][0].pop("label"), "entries[0]"),
        (lambda raw: raw["entries"][0].update(look="exulanica.cozy-town"), "entries[0]"),
        (lambda raw: raw["entries"][0].update(setting_parts=["clear_noon"]), "setting_parts"),
        (lambda raw: raw["entries"][0]["setting_parts"].update(Sky="dusk"), "setting_parts.Sky"),
        (lambda raw: raw["entries"][0]["setting_parts"].update(sky=3), "setting_parts.sky"),
    ],
)
def test_a_settings_catalog_that_breaks_a_rule_is_refused_where_it_broke(change, where):
    assert read_settings(_catalog(lambda raw: None))
    with pytest.raises(CatalogError, match=re.escape(where)):
        read_settings(_catalog(change))


def test_a_kind_starts_on_one_setting_at_most():
    def twice(raw: dict[str, Any]) -> None:
        other = copy.deepcopy(raw["entries"][0])
        other["key"] = "another_island"
        raw["entries"].append(other)

    with pytest.raises(CatalogError, match="one setting at most"):
        read_settings(_catalog(twice))


def test_a_starter_is_drawn_in_its_settings_parts_over_the_hosts_look():
    kind = island_hamlet()
    assert starter_setting_parts(kind) == {"sky": "clear_noon"}
    look = starter_look(kind)
    assert look is not None
    # The host's look, as every served starter wears it, with the clear noon composed for it.
    assert look.pack_id == style_pack_library().default_pack.pack_id
    setting = json.loads(look.setting or "{}")
    assert setting["parts"] == [{"axis": "sky", "key": "clear_noon"}]
    assert setting["light"]["changes"]["sun.elevation_mdeg"] > 60_000
    # A workspace's kind of the same key starts on no setting and is drawn as the host draws it.
    own = copy.deepcopy(dict(kind.document))
    own["summary"] = "Our own hamlet, on open ground."
    assert starter_setting_parts(read_kind(own)) is None and starter_look(read_kind(own)) is None


def test_a_setting_naming_a_part_the_parts_catalog_does_not_hold_is_refused(monkeypatch):
    def unheld(raw: dict[str, Any]) -> None:
        raw["entries"][0]["setting_parts"] = {"sky": "purple_rain"}

    (setting,) = read_settings(_catalog(unheld))
    monkeypatch.setattr(landscapes, "starting_setting", lambda kind, version: setting)
    with pytest.raises(CatalogError, match="purple_rain"):
        starter_setting_parts(island_hamlet())
