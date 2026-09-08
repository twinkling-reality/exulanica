"""Verify browser observations against the still-running generated scratch workspace."""

from __future__ import annotations

import hashlib
import json
import subprocess
import urllib.parse
import uuid
from fractions import Fraction
from pathlib import Path

from exulanica.db import Database

ROOT = Path.cwd()
DIRECTORY = Path(__file__).resolve().parent / "reload-fixed"


def read(name: str) -> dict:
    return json.loads((DIRECTORY / name).read_bytes())


fixture = read("browser-fixture.json")
drawn = read("browser-drawn.json")
loaded = read("browser-full-reloaded.json")
other = read("browser-other-capture.json")
negative = read("browser-negative-state.json")
left, top, right, bottom = drawn["coordinates"]
expected = [[left, top], [right, top], [right, bottom], [left, bottom]]
layout = {key: Fraction(value) for key, value in drawn["layout"].items()}
scale = min(layout["width"] / layout["naturalWidth"], layout["height"] / layout["naturalHeight"])
width, height = layout["naturalWidth"] * scale, layout["naturalHeight"] * scale
image_left = layout["left"] + (layout["width"] - width) / 2
image_top = layout["top"] + (layout["height"] - height) / 2
corners = []
for x, y in (drawn["gesture"]["from"], drawn["gesture"]["to"]):
    corners.extend(
        [round((x - image_left) * 1000000 / width), round((y - image_top) * 1000000 / height)]
    )
assert corners == drawn["coordinates"]
url = "postgresql://localhost:5433/exulanica_spine_test?options=" + urllib.parse.quote(
    "-csearch_path=" + fixture["schema"] + ",public -crole=exulanica_app", safe=""
)
with Database(url).session(uuid.UUID(fixture["workspace_id"])) as connection:
    rows = connection.execute(
        "select capture_id, region_key, source_sha256, silhouette, action, confirmed_by, "
        "subject_id, region_record, region_digest from person_region order by capture_id, sequence"
    ).fetchall()
    subjects = connection.execute("select count(*) as n from person_subject").fetchone()["n"]
    consents = connection.execute(
        "select count(*) as n from person_presentation_consent"
    ).fetchone()["n"]
assert len(rows) == 1 and subjects == consents == 0
row = rows[0]
assert str(row["capture_id"]) == drawn["captureId"] == loaded["captureId"]
assert row["silhouette"]["points"] == expected
assert loaded["points"] == " ".join(f"{x},{y}" for x, y in expected)
assert bytes(row["region_key"]).hex() == loaded["regionKey"]
assert str(row["confirmed_by"]) == fixture["actor"] and row["subject_id"] is None
assert loaded["state"] == "unknown" and loaded["editorImages"] == loaded["saveButtons"] == 0
assert "unavailable" in loaded["text"]
assert other["captureId"] != loaded["captureId"] and other["regionCount"] == 0
assert "Nobody has looked" in other["unscreened"]
assert negative["captureId"] == other["captureId"] and negative["editorCount"] == 0
assert "Save person region is missing" in (DIRECTORY / "browser-negative.log").read_text()
assert "PASS" in (DIRECTORY / "browser-restored-control.log").read_text()
for entry in fixture["captures"]:
    assert hashlib.sha256((DIRECTORY / entry["image"]).read_bytes()).hexdigest() == entry["sha256"]
encoded = [
    {
        key: value.hex()
        if isinstance(value, bytes)
        else str(value)
        if isinstance(value, uuid.UUID)
        else value
        for key, value in item.items()
    }
    for item in rows
]
(DIRECTORY / "verified-stored-rows.json").write_text(json.dumps(encoded, indent=2) + "\n")
head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
sources = {}
for path in (
    "web/packages/app/src/main.ts",
    "web/packages/app/src/ui/person-review.ts",
    "web/packages/app/src/ui/person-region-editor.ts",
    "exulanica/world/repository.py",
):
    sources[path] = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
assert not subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()
report = {
    "path": "mounted-empty-detector-person-authoring",
    "integrated_head": head,
    "integrated_sources": sources,
    "positive": True,
    "full_page_reload": True,
    "normalized_outline_matches_stored": True,
    "pending_mask_has_no_editable_image": True,
    "second_capture_unchanged": True,
    "presentation_consent_count": consents,
    "subject_count": subjects,
    "negative_failed": True,
    "negative_selector": "button with exact accessible name Save person region",
    "negative_reason": "Save person region is missing",
    "restored_control_passed": True,
    "integration_tree_clean": True,
    "capture_id": loaded["captureId"],
    "other_capture_id": other["captureId"],
    "region_key": loaded["regionKey"],
    "outline": expected,
}
(DIRECTORY / "browser-verified.json").write_text(json.dumps(report, indent=2) + "\n")
print(
    "PASS: real add, full reload, normalized outline, owner, no consent, unchanged second capture"
)
print("PASS: named browser negative failed and exact restoration passes")
