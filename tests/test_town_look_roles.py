"""The look role each texture set a town is drawn with takes, held to the catalogs it comes from.

``assets/style-packs/town-look-roles.v1.json`` is what the browser reads to dress a town's surfaces
from a style pack. Its rule is stated in the file: the family of the first grammar surface role the
material catalog lists for the set's material, then the material's key as the leaf. These tests
derive every entry again from the material catalog and the world kinds' look-family catalog, so a
material added to the catalog, or a family dropped from the kinds' catalog, fails here rather than
leaving a set the page cannot dress.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> Any:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_every_material_set_takes_its_first_roles_family_and_its_own_key() -> None:
    roles = _read("assets/style-packs/town-look-roles.v1.json")
    family_of = roles["families_of_roles"]
    expected = {}
    for entry in _read("assets/catalogs/material.v5.json")["entries"]:
        family = family_of[entry["surfaces"][0]]
        expected[entry["texture_set_id"]] = f"{family}.{entry['key']}"
    assert roles["sets"] == expected


def test_every_surface_role_a_material_names_has_a_family() -> None:
    roles = _read("assets/style-packs/town-look-roles.v1.json")["families_of_roles"]
    named = {
        role
        for entry in _read("assets/catalogs/material.v5.json")["entries"]
        for role in entry["surfaces"]
    }
    assert named <= set(roles)


def test_every_family_the_table_uses_is_a_look_family_of_the_kinds_catalog() -> None:
    roles = _read("assets/style-packs/town-look-roles.v1.json")
    families = {
        entry["key"]
        for entry in _read("assets/catalogs/world-kinds/look-family.v1.json")["entries"]
    }
    used = set(roles["families_of_roles"].values()) | {
        role.split(".")[0] for role in roles["sets"].values()
    }
    assert used <= families
