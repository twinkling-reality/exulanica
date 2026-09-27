"""Which reviewed interaction capabilities the settings page offers is data the registry states.

Each capability in ``exulanica/world/interaction-policy-registry.v1.json`` says whether the settings
page offers a control for it and, when it does not, why; ``GET /world/interactions/catalog`` serves
both, and the page draws exactly the offered ones
(web/packages/app/test/interaction-settings.test.ts).
"""

from __future__ import annotations

import copy
import json
from importlib.resources import files

import pytest
from exulanica.world.interaction import INTERACTION_POLICY_REGISTRY, InteractionPolicyRegistry

DOCUMENT = json.loads(
    files("exulanica.world").joinpath("interaction-policy-registry.v1.json").read_text("utf-8")
)


def test_the_catalog_serves_each_capability_s_visibility_as_the_registry_states_it():
    served = {c["key"]: c for c in INTERACTION_POLICY_REGISTRY.catalog()["capabilities"]}
    for stated in DOCUMENT["capabilities"]:
        assert served[stated["key"]]["shown_in_settings"] is stated["shown_in_settings"]
        assert served[stated["key"]]["settings_note"] == stated.get("settings_note")
    shown = sorted(key for key, capability in served.items() if capability["shown_in_settings"])
    assert shown == [
        "comfort.field-of-view-degrees",
        "comfort.look-sensitivity-milli",
        "comfort.vignette",
    ]


@pytest.mark.parametrize(
    "edit",
    [
        lambda capability: capability.pop("shown_in_settings"),
        lambda capability: capability.update(shown_in_settings="yes"),
        lambda capability: capability.update(shown_in_settings=False),
        lambda capability: capability.update(settings_note="a reason for a shown control"),
    ],
    ids=["missing", "not-a-boolean", "hidden-without-a-reason", "shown-with-a-reason"],
)
def test_a_capability_states_its_visibility_and_why_only_when_hidden(edit):
    document = copy.deepcopy(DOCUMENT)
    shown = next(c for c in document["capabilities"] if c["shown_in_settings"])
    edit(shown)
    with pytest.raises(RuntimeError, match="invalid interaction policy capability"):
        InteractionPolicyRegistry(document)
