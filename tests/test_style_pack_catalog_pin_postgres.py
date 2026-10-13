"""Actual upload admission keeps catalog inheritance within authorized workspace boundaries."""

import pytest
from exulanica.world.style_packs import load_context

from style_pack_upload_support import upload
from test_workspace_style_packs_api_postgres import ROOT, PacksApi
from test_workspace_style_packs_api_postgres import api as api

pytestmark = pytest.mark.postgres


def test_pinned_base_and_child_are_checked_and_mixed_or_foreign_base_is_refused(api: PacksApi):
    pin = {"version": 2, "sha256": load_context(ROOT).family_catalogs[2].sha256}
    base = upload("maker.pinned-base")
    base.manifest["look_family_catalog"] = pin
    created = api.send(base)
    assert created.status_code == 201, created.text
    digest = created.json()["manifest_sha256"]
    outcome = api.check()
    assert (outcome.ready, outcome.errors) == (1, []), outcome
    child = upload("maker.pinned-child")
    child.manifest["base"] = {
        "pack_id": base.manifest["pack_id"],
        "version": 1,
        "manifest_sha256": digest,
    }
    refused = api.send(child)
    assert (refused.status_code, refused.json()["code"], refused.json()["path"]) == (
        422,
        "invalid_style_data",
        "base",
    ), refused.text
    # The stranger gets the same authorized-base refusal before seeing any catalog difference.
    foreign = api.send(child, who="stranger")
    assert (foreign.status_code, foreign.json()["code"]) == (422, "style_pack_base_unavailable")
    child.manifest["look_family_catalog"] = pin
    admitted = api.send(child)
    assert admitted.status_code == 201, admitted.text
    outcome = api.check()
    assert (outcome.ready, outcome.errors) == (1, []), outcome
    served = api.get(f"/workspace-style-packs/{admitted.json()['manifest_sha256']}")
    assert served.status_code == 200
    assert served.json()["manifest"] == child.manifest
