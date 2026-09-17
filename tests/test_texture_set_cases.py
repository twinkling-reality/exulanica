"""The shared texture set cases, run against the backend's readers.

``web/packages/loom-texture/test/texture-set-cases.json`` is one set of cases three readers run: the
baker's (``texture-set-cases.test.ts`` beside it), the browser's in ``atlas-core``, and the
backend's here. Each case is accepted by every reader, or refused by every reader for the same one
of five reasons: ``manifest``, ``byte-size``, ``digest``, ``container`` or ``header``. The fixtures
are small generated containers, not published sets, and each refused one has exactly one defect, so
the order a reader checks in cannot change the reason it gives. The package's test holds the
committed files to their generator byte for byte.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from exulanica.canonical import canonical_json
from exulanica.materials import MaterialObjectError
from exulanica.materials.manifest import MANIFEST_PROFILE_V2, read_texture_manifest
from exulanica.world.texture_assets import TextureSetRefused, read_texture_set

ROOT = Path(__file__).resolve().parents[1]
CASES_DIRECTORY = ROOT / "web" / "packages" / "loom-texture" / "test"
CASES = json.loads((CASES_DIRECTORY / "texture-set-cases.json").read_text(encoding="utf-8"))


def _apply(document: Any, changes: list[dict[str, Any]]) -> Any:
    changed = copy.deepcopy(document)
    for change in changes:
        parent = changed
        for step in change["path"][:-1]:
            parent = parent[step]
        last = change["path"][-1]
        if change.get("remove"):
            del parent[last]
        else:
            parent[last] = copy.deepcopy(change["value"])
    return changed


def _outcome(run: Callable[[], object]) -> str | None:
    """None when ``run`` accepts, or the shared reason it refused with."""
    try:
        run()
    except MaterialObjectError:
        return "manifest"
    except TextureSetRefused as refused:
        return refused.reason
    return None


@pytest.mark.parametrize("case", CASES["manifests"], ids=lambda case: case["name"])
def test_a_manifest_case(case):
    manifest = json.loads((CASES_DIRECTORY / CASES["manifest"]).read_text(encoding="utf-8"))
    raw = canonical_json(_apply(manifest, case["changes"]))
    assert _outcome(lambda: read_texture_manifest(raw)) == case["reason"]


@pytest.mark.parametrize("case", CASES["containers"], ids=lambda case: case["name"])
def test_a_container_case(case):
    (entry,) = read_texture_manifest(
        canonical_json({"profile": MANIFEST_PROFILE_V2, "sets": [case["entry"]]})
    ).values()
    payload = (CASES_DIRECTORY / case["container"]).read_bytes()
    assert _outcome(lambda: read_texture_set(payload, entry)) == case["reason"]


def test_the_cases_reach_every_reason_and_every_accepted_kind_of_container():
    assert {case["reason"] for case in CASES["containers"]} == {
        None,
        "byte-size",
        "digest",
        "container",
        "header",
    }
    assert {case["reason"] for case in CASES["manifests"]} == {None, "manifest"}
    accepted = {
        (case["entry"]["container_profile"], case["entry"]["material_class"])
        for case in CASES["containers"]
        if case["reason"] is None
    }
    assert accepted == {
        ("exulanica.texture-set/v1", "opaque"),
        ("exulanica.texture-set/v2", "opaque"),
        ("exulanica.texture-set/v2", "cutout"),
        ("exulanica.texture-set/v2", "decal"),
        ("exulanica.texture-set/v2", "glazing"),
    }
