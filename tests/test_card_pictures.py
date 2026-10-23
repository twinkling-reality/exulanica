"""The record of the starter card pictures holds together and states what each card makes now.

The record (``web/packages/app/public/card-pictures/card-pictures.v1.json``) is written by
``scripts/capture_card_pictures.py`` when a release is built. These tests hold it: every entry well
formed, naming a card the server serves and a picture that exists at its digest as a 640 by 360
JPEG, no other file beside it, every held card with its reason, and every entry's reference the one
its card makes now (a recipe's land included). The page matches a recipe card by its values alone,
so a recipe whose catalog, specification or land changed with the same values would otherwise keep
an old picture: such an entry fails here until it is captured again or moved to ``held``, a data
edit, so the change never needs a browser to pass.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "capture_card_pictures.py"
spec = importlib.util.spec_from_file_location("capture_card_pictures", SCRIPT)
assert spec is not None and spec.loader is not None
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)

RECORD = json.loads(capture.CATALOG.read_text())
#: The page takes a picture only by a name like these (web/packages/app/src/ui/card-pictures.ts).
PICTURE_NAME = re.compile(r"^[a-z0-9_-]+\.jpg$")


def served_cards() -> set[str]:
    from exulanica.world.kinds.library import shipped_kinds, town_adapter
    from exulanica.world.world_recipes import world_recipes

    kinds = {kind.kind for kind in shipped_kinds() if kind.presets} | {town_adapter().kind}
    recipes = {f"recipe:{recipe.key}" for recipe in world_recipes()}
    return recipes | {f"kind:{kind}" for kind in kinds}


def test_the_record_states_its_profile_and_lists():
    assert RECORD["profile"] == capture.PROFILE
    assert isinstance(RECORD["entries"], list) and isinstance(RECORD["held"], list)


@pytest.mark.parametrize("entry", RECORD["entries"], ids=lambda entry: entry["card"])
def test_each_entry_names_a_served_card_and_its_picture_at_its_digest(entry):
    assert entry["card"] in served_cards()
    family, key = entry["card"].split(":", 1)
    reference = entry["reference"]
    if family == "recipe":
        assert reference["key"] == key and isinstance(reference["values"], dict)
    else:
        assert set(reference) == {"kind", "version", "sha256"} and reference["kind"] == key
    assert PICTURE_NAME.fullmatch(entry["picture"])
    data = (capture.CATALOG_DIR / entry["picture"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == entry["picture_sha256"]
    assert capture.jpeg_size(data) == capture.SIZE == (entry["width"], entry["height"])
    assert re.fullmatch(r"[0-9a-f]{40}", entry["commit"])
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", entry["captured_on"])
    assert entry["world_id"].startswith("world:generated:") and entry["entry_id"]


@pytest.mark.parametrize("entry", RECORD["entries"], ids=lambda entry: entry["card"])
def test_each_entry_states_the_reference_its_card_makes_now(entry):
    now = capture.current_reference(entry["card"], entry["reference"].get("values"))
    assert entry["reference"] == now, (
        f"{entry['card']}: the record states {json.dumps(entry['reference'], sort_keys=True)}, the "
        f"card now makes {json.dumps(now, sort_keys=True)}. Capture it again with "
        "scripts/capture_card_pictures.py, or move it to held in card-pictures.v1.json "
        "with its reason."
    )


def test_held_cards_say_why_and_have_no_picture():
    held = [item["card"] for item in RECORD["held"]]
    assert all(item["reason"].strip() for item in RECORD["held"])
    assert not set(held) & {entry["card"] for entry in RECORD["entries"]}
    assert len(held) == len(set(held))


def test_no_file_lies_beside_the_record_but_its_pictures():
    named = {entry["picture"] for entry in RECORD["entries"]} | {capture.CATALOG.name}
    assert {path.name for path in capture.CATALOG_DIR.iterdir()} == named


def test_the_capture_step_names_an_entry_whose_reference_no_longer_holds(
    tmp_path, monkeypatch, capsys
):
    current = capture.current_reference("recipe:small_town", None)
    held = {"card": "recipe:small_town", "reference": current, "picture": "recipe-small_town.jpg"}
    gone = {"kind": "town", "version": 0, "sha256": "0" * 64}
    stale = {**held, "card": "kind:town", "reference": gone}
    record = tmp_path / "card-pictures.v1.json"

    def write(*entries):
        record.write_text(json.dumps({"profile": capture.PROFILE, "entries": entries, "held": []}))

    write(held)
    monkeypatch.setattr(capture, "CATALOG", record)
    assert capture.check() == 0
    write(held, stale)
    assert capture.check() == 1
    out = capsys.readouterr().out
    assert "stale: kind:town" in out and "stale: recipe:small_town" not in out
