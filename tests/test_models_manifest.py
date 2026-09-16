"""Manifest and preflight.

The load-bearing test in this file is ``test_no_model_id_is_inlined_in_python_source``. It is the
only mechanical enforcement of invariant 7, and it is written to fail on the change that would
break it rather than to restate that the manifest has entries.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from exulanica.models.errors import ManifestError, PreflightError, TransportError
from exulanica.models.manifest import MANIFEST_PATH, Role, parse_manifest
from exulanica.models.preflight import catalog_flavors, main, run_preflight

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "exulanica" / "models"


def _catalog_entry(model_id: str, *, use_cases, price_in="0.06", price_out="0.24"):
    return {
        "name": "Display Name Which Code Must Never Read",
        "flavors": [
            {
                "model_id": model_id,
                "use_cases": list(use_cases),
                "input_price_per_million_tokens": float(price_in),
                "output_price_per_million_tokens": float(price_out),
            }
        ],
    }


def live_catalog_for(manifest):
    """A synthetic catalog in which every manifest identifier resolves and fits its role."""
    entries = []
    for model_id in sorted(manifest.referenced_model_ids()):
        spec = manifest.spec(model_id)
        entries.append(
            _catalog_entry(
                model_id,
                use_cases=spec.catalog_use_cases,
                price_in=spec.input_usd_per_mtok,
                price_out=spec.output_usd_per_mtok,
            )
        )
    return entries


# -- the manifest itself -------------------------------------------------------------------


def test_every_role_is_bound(manifest):
    assert set(manifest.roles) == set(Role)


def test_prices_are_decimal_not_float(manifest):
    for spec in manifest.models.values():
        assert isinstance(spec.input_usd_per_mtok, Decimal)
        assert isinstance(spec.output_usd_per_mtok, Decimal)


def test_no_model_id_is_inlined_in_python_source(manifest):
    """Invariant 7: identifiers live in the manifest JSON and nowhere else.

    This fails the moment somebody pastes an identifier into a call site, a docstring or a
    default argument, which is the change that turns the next deprecation into a silent outage.
    """
    offenders: list[str] = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for model_id in manifest.model_ids:
            if model_id in text:
                offenders.append(f"{path.name} contains {model_id!r}")
    assert offenders == [], (
        "model identifiers must appear only in models.manifest.json:\n" + "\n".join(offenders)
    )


def test_embedding_role_declares_no_fallback(manifest):
    """The gap is real and the manifest must keep saying so rather than inventing a substitute."""
    assert manifest[Role.EMBEDDING].fallback is None
    assert manifest[Role.EMBEDDING].chain == (manifest[Role.EMBEDDING].primary,)


def test_every_other_role_has_a_distinct_fallback(manifest):
    for role, binding in manifest.roles.items():
        if role is Role.EMBEDDING:
            continue
        assert binding.fallback is not None, f"{role} has no fallback"
        assert binding.fallback.model_id != binding.primary.model_id


def test_chain_floor_is_the_strictest_in_the_chain(manifest):
    """A fallback with a bigger reasoning overhead must not be allowed to truncate silently."""
    for role, binding in manifest.roles.items():
        if role is Role.EMBEDDING:
            continue
        for spec in binding.chain:
            assert binding.min_max_tokens >= (spec.min_max_tokens or 0)


def test_reasoning_floor_clears_the_measured_overhead(manifest):
    """Measured overhead was 149 to 214 tokens. The floor has to clear it with room to answer."""
    assert manifest[Role.REASONING_CHEAP].min_max_tokens >= 640


def test_fallback_equal_to_primary_is_rejected():
    document = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"), parse_float=Decimal)
    primary = document["roles"]["reasoning_cheap"]["primary"]
    document["roles"]["reasoning_cheap"]["fallback"] = primary
    with pytest.raises(ManifestError, match="fallback"):
        parse_manifest(document)


def test_unknown_role_is_rejected():
    document = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"), parse_float=Decimal)
    document["roles"]["telepathy"] = {"primary": document["roles"]["vision"]["primary"]}
    with pytest.raises(ManifestError, match="telepathy"):
        parse_manifest(document)


def test_missing_role_is_rejected():
    document = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"), parse_float=Decimal)
    del document["roles"]["vision"]
    with pytest.raises(ManifestError, match="vision"):
        parse_manifest(document)


def test_unknown_role_lookup_names_the_known_roles(manifest):
    with pytest.raises(ManifestError, match="reasoning_cheap"):
        manifest["telepathy"]


def test_cost_is_exact_decimal(manifest):
    spec = manifest[Role.REASONING_CHEAP].primary
    # 8000 in at 0.06/M plus 800 out at 0.24/M, the shape the routing analysis uses.
    cost = spec.cost_usd(prompt_tokens=8000, completion_tokens=800)
    assert cost == Decimal("0.000672")


# -- preflight -----------------------------------------------------------------------------


def test_catalog_flavors_reads_model_id_never_name():
    catalog = [
        {
            "name": "Nemotron 3.5 Lightning",
            "flavors": [{"model_id": "vendor/Real-Callable-Id", "use_cases": ["text"]}],
        }
    ]
    assert set(catalog_flavors(catalog)) == {"vendor/Real-Callable-Id"}


def test_preflight_passes_when_every_id_resolves(manifest):
    report = run_preflight(manifest=manifest, catalog=live_catalog_for(manifest))
    assert report.ok, [str(i) for i in report.failures]
    assert len(report.checked) == len(manifest.referenced_model_ids())


def test_preflight_fails_when_an_id_is_withdrawn(manifest):
    """This is the December failure the whole mechanism exists to catch."""
    catalog = live_catalog_for(manifest)
    withdrawn = manifest[Role.REASONING_CHEAP].primary.model_id
    catalog = [e for e in catalog if e["flavors"][0]["model_id"] != withdrawn]

    report = run_preflight(manifest=manifest, catalog=catalog)
    assert not report.ok
    kinds = {i.kind for i in report.failures}
    assert kinds == {"absent_from_catalog"}
    assert any("reasoning_cheap" in i.roles for i in report.failures)
    with pytest.raises(PreflightError, match="absent_from_catalog"):
        report.raise_for_status()


def test_preflight_fails_when_a_fallback_is_withdrawn(manifest):
    """A failover that has itself been removed is worse than none: it fails only under load."""
    catalog = live_catalog_for(manifest)
    fallback = manifest[Role.VISION].fallback.model_id
    catalog = [e for e in catalog if e["flavors"][0]["model_id"] != fallback]
    report = run_preflight(manifest=manifest, catalog=catalog)
    assert not report.ok
    assert any(i.model_id == fallback for i in report.failures)


def test_preflight_asserts_on_use_cases_not_on_type(manifest):
    """The primary vision model is typed text2text and genuinely sees images.

    A preflight that trusted ``type`` would reject the model that was runtime-verified to work.
    """
    vision = manifest[Role.VISION].primary
    assert vision.catalog_type != "image2text"
    assert "image" in vision.catalog_use_cases

    catalog = live_catalog_for(manifest)
    for entry in catalog:
        if entry["flavors"][0]["model_id"] == vision.model_id:
            entry["flavors"][0]["use_cases"] = ["text", "reasoning"]  # image capability removed
    report = run_preflight(manifest=manifest, catalog=catalog)
    assert not report.ok
    assert {i.kind for i in report.failures} == {"use_case_lost"}


def test_price_drift_warns_but_does_not_fail(manifest):
    catalog = live_catalog_for(manifest)
    catalog[0]["flavors"][0]["input_price_per_million_tokens"] = 99.0
    report = run_preflight(manifest=manifest, catalog=catalog)
    assert report.ok
    assert any(i.kind == "price_drift" for i in report.warnings)


def test_preflight_does_not_touch_the_network_when_given_a_catalog(manifest, transport):
    run_preflight(manifest=manifest, catalog=live_catalog_for(manifest), transport=transport)
    assert transport.gets == []


def test_cli_exit_codes(manifest, tmp_path, capsys):
    good = tmp_path / "catalog.json"
    good.write_text(json.dumps(live_catalog_for(manifest)), encoding="utf-8")
    assert main(["--catalog-file", str(good)]) == 0

    withdrawn = manifest[Role.VISION].primary.model_id
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps(
            [e for e in live_catalog_for(manifest) if e["flavors"][0]["model_id"] != withdrawn]
        ),
        encoding="utf-8",
    )
    assert main(["--catalog-file", str(bad)]) == 1


def test_cli_reports_an_unreachable_catalog_as_failure(monkeypatch):
    def boom(url, **kwargs):
        raise TransportError("DNS is having a day")

    monkeypatch.setattr("exulanica.models.preflight.fetch_catalog", boom)
    assert main([]) == 1


def test_the_manifest_data_file_sits_beside_the_module():
    """``load_manifest`` resolves it relative to the module, so it must ship with the package."""
    assert MANIFEST_PATH.name == "models.manifest.json"
    assert MANIFEST_PATH.parent == PACKAGE_ROOT
    assert MANIFEST_PATH.is_file()


def test_the_model_package_is_not_excluded_from_version_control():
    """A `models/` ignore rule meant for weight caches silently swallowed this whole package.

    The consequence was not a lint warning: hatchling honours these rules, so `exulanica/models`
    and the manifest JSON beside it were absent from the built wheel, and an installed copy
    raised ImportError. This asserts the negation that fixes it is still there.
    """
    import subprocess

    repo = PACKAGE_ROOT.parents[1]
    if not (repo / ".git").exists():
        pytest.skip("not a git checkout")
    tracked = [str(MANIFEST_PATH), str(PACKAGE_ROOT / "client.py")]
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", *tracked],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, (
        "these files are git-ignored and will not be packaged:\n" + result.stdout
    )
