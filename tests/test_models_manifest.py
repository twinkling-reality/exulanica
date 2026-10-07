"""Manifest and preflight.

The load-bearing test in this file is ``test_no_model_id_is_inlined_in_product_code``. It is the
only mechanical enforcement of invariant 7, and it is written to fail on the change that would
break it rather than to restate that the manifest has entries.
"""

from __future__ import annotations

import ast
import json
from decimal import Decimal
from pathlib import Path

import pytest
from exulanica.models.errors import ManifestError, PreflightError, TransportError
from exulanica.models.manifest import MANIFEST_PATH, Role, parse_manifest
from exulanica.models.preflight import catalog_flavors, main, run_preflight
from exulanica.world.decision_roles import decision_roles

REPOSITORY = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPOSITORY / "exulanica" / "models"


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


def live_catalogs_for(manifest):
    """Synthetic catalogs, one per provider, in which every manifest identifier resolves and fits
    its role."""
    catalogs: dict[str, list] = {provider: [] for provider in manifest.providers}
    for model_id in sorted(manifest.referenced_model_ids()):
        spec = manifest.spec(model_id)
        catalogs[spec.provider].append(
            _catalog_entry(
                model_id,
                use_cases=spec.catalog_use_cases,
                price_in=spec.input_usd_per_mtok,
                price_out=spec.output_usd_per_mtok,
            )
        )
    return catalogs


def _without(catalogs, model_id):
    """The same catalogs with ``model_id`` withdrawn from whichever provider lists it."""
    return {
        provider: [e for e in entries if e["flavors"][0]["model_id"] != model_id]
        for provider, entries in catalogs.items()
    }


def _entry(catalogs, model_id):
    return next(
        entry
        for entries in catalogs.values()
        for entry in entries
        if entry["flavors"][0]["model_id"] == model_id
    )


# -- the manifest itself -------------------------------------------------------------------


def test_every_role_is_bound_or_chosen_and_never_both(manifest):
    """The manifest binds every role a call site names; a role a world chooses a model for is the
    decision role registry's, and never one of those."""
    assert set(manifest.roles) == set(Role)
    chosen = {role.key for role in decision_roles()}
    assert chosen and not chosen & {role.value for role in Role}


def test_prices_are_decimal_not_float(manifest):
    for spec in manifest.models.values():
        assert isinstance(spec.input_usd_per_mtok, Decimal)
        assert isinstance(spec.output_usd_per_mtok, Decimal)


#: The newest migration on disk when the scan was widened. Migrations up to it are applied, frozen
#: SQL and keep the identifiers they were written with (0001 names the embedding model); every
#: later migration is scanned like any other product file.
FROZEN_MIGRATIONS_THROUGH = 116


def product_files(repository: Path) -> list[Path]:
    """Every text file of product code: the package and the browser packages' sources, except
    the manifest itself and the migrations applied when the scan was widened."""
    package = repository / "exulanica"
    roots = [package, *sorted((repository / "web" / "packages").glob("*/src"))]
    frozen = {package / "models" / "models.manifest.json"}
    found = []
    for root in roots:
        for candidate in sorted(root.rglob("*")):
            if not candidate.is_file() or candidate in frozen or "__pycache__" in candidate.parts:
                continue
            if (
                candidate.parent == package / "migrations"
                and candidate.suffix == ".sql"
                and int(candidate.name[:4]) <= FROZEN_MIGRATIONS_THROUGH
            ):
                continue
            found.append(candidate)
    return found


def inlined_model_ids(files, model_ids) -> list[str]:
    """``file contains id`` for every identifier any of ``files`` spells, in any letter case.

    What it cannot see: an identifier split across string literals or built from parts, one in a
    file that is not UTF-8 text, and anything outside the package and the browser sources
    (scripts, tests and documents may name models; they are not product code).
    """
    offenders = []
    for candidate in files:
        try:
            text = candidate.read_text(encoding="utf-8").casefold()
        except UnicodeDecodeError:
            continue
        offenders.extend(
            f"{candidate} contains {model_id!r}"
            for model_id in model_ids
            if model_id.casefold() in text
        )
    return offenders


def test_no_model_id_is_inlined_in_product_code(manifest):
    """Invariant 7: identifiers live in the manifest JSON and nowhere else in product code.

    This fails the moment somebody pastes an identifier into a call site, a docstring, a default
    argument, a data file or the browser, which is the change that turns the next deprecation
    into a silent outage (a policy that names its model stops working when the manifest moves).
    """
    files = product_files(REPOSITORY)
    # The scan reaches both halves of the product, so an empty glob cannot pass it.
    assert REPOSITORY / "exulanica" / "ingest" / "place_proposal.py" in files
    assert any(f.suffix == ".ts" and "web" in f.parts for f in files)
    assert inlined_model_ids(files, manifest.model_ids) == [], (
        "model identifiers must appear only in models.manifest.json"
    )


def test_the_model_id_scan_finds_an_identifier_planted_in_product_code(manifest, tmp_path):
    """Positive control: the same scan over a copy of the layout with one identifier planted."""
    planted = tmp_path / "exulanica" / "ingest" / "place_proposal.py"
    planted.parent.mkdir(parents=True)
    model_id = sorted(manifest.model_ids)[0]
    planted.write_text(f'JUDGE = "{model_id.upper()}"\n', encoding="utf-8")
    browser = tmp_path / "web" / "packages" / "app" / "src" / "names.ts"
    browser.parent.mkdir(parents=True)
    browser.write_text(f"export const NAME = '{model_id}';\n", encoding="utf-8")
    migration = tmp_path / "exulanica" / "migrations" / "0001_spine.sql"
    migration.parent.mkdir(parents=True)
    migration.write_text(f"-- {model_id}\n", encoding="utf-8")
    later = migration.with_name(f"{FROZEN_MIGRATIONS_THROUGH + 1:04d}_a_later_change.sql")
    later.write_text(f"-- {model_id}\n", encoding="utf-8")
    offenders = inlined_model_ids(product_files(tmp_path), manifest.model_ids)
    assert sorted(offenders) == sorted(
        [
            f"{planted} contains {model_id!r}",
            f"{browser} contains {model_id!r}",
            f"{later} contains {model_id!r}",
        ]
    )


def credential_literals(source: str, variables) -> list[int]:
    """The lines of ``source`` holding a string constant that is a credential variable."""
    return sorted(
        node.lineno
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant) and node.value in variables
    )


def test_no_module_reads_a_credential_from_a_variable_it_spells(manifest):
    """Every caller takes a provider's credential variable from the manifest's ``api_key_env``
    (``Manifest.credential_variables``); a module that spells one reads a credential the
    manifest no longer names once the provider moves."""
    variables = {provider.api_key_env for provider in manifest.providers.values()}
    offenders = [
        f"{candidate}:{line}"
        for candidate in sorted((REPOSITORY / "exulanica").rglob("*.py"))
        for line in credential_literals(candidate.read_text(encoding="utf-8"), variables)
    ]
    assert offenders == []
    # Positive control: the same check finds the spelling this test exists to keep out.
    variable = sorted(variables)[0]
    assert credential_literals(f'KEY = "{variable}"\nprose = "needs {variable}"\n', variables) == [
        1
    ]


def test_embedding_role_declares_no_fallback(manifest):
    """The gap is real and the manifest must keep saying so rather than inventing a substitute."""
    assert manifest[Role.EMBEDDING].fallback is None
    assert manifest[Role.EMBEDDING].chain == (manifest[Role.EMBEDDING].primary,)


def test_reference_vision_declares_no_fallback(manifest):
    """The only other image model offered is conditional on its licence terms (L-2), so the role
    reads a person's picture with one model or not at all."""
    assert manifest[Role.REFERENCE_VISION].fallback is None
    assert manifest[Role.REFERENCE_VISION].chain == (manifest[Role.REFERENCE_VISION].primary,)


def test_every_other_role_has_a_distinct_fallback(manifest):
    for role, binding in manifest.roles.items():
        if role in (Role.EMBEDDING, Role.REFERENCE_VISION):
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
    report = run_preflight(manifest=manifest, catalogs=live_catalogs_for(manifest))
    assert report.ok, [str(i) for i in report.failures]
    assert len(report.checked) == len(manifest.referenced_model_ids())


def test_preflight_reads_each_model_from_its_own_providers_catalog(manifest):
    """Two providers may list one identifier: a model is held to its own provider's entry, and
    another provider listing it, even without the use cases it needs, changes nothing."""
    import copy

    document = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"), parse_float=Decimal)
    (first,) = list(document["providers"])[:1]
    second = copy.deepcopy(document["providers"][first])
    second["base_url"] = "https://second.example.com/v1"
    second["catalog_url"] = "https://second.example.com/models"
    second["api_key_env"] = "SECOND_PROVIDER_TEST_API_KEY"
    document["providers"]["zz_second_provider"] = second
    two = parse_manifest(document)
    catalogs = live_catalogs_for(two)
    listed = two[Role.REASONING_CHEAP].primary
    catalogs["zz_second_provider"] = [_catalog_entry(listed.model_id, use_cases=())]
    report = run_preflight(manifest=two, catalogs=catalogs)
    assert report.ok, [str(i) for i in report.failures]


def test_preflight_fails_when_an_id_is_withdrawn(manifest):
    """This is the December failure the whole mechanism exists to catch."""
    withdrawn = manifest[Role.REASONING_CHEAP].primary.model_id
    catalogs = _without(live_catalogs_for(manifest), withdrawn)

    report = run_preflight(manifest=manifest, catalogs=catalogs)
    assert not report.ok
    kinds = {i.kind for i in report.failures}
    assert kinds == {"absent_from_catalog"}
    assert any("reasoning_cheap" in i.roles for i in report.failures)
    with pytest.raises(PreflightError, match="absent_from_catalog"):
        report.raise_for_status()


def test_preflight_fails_when_a_fallback_is_withdrawn(manifest):
    """A failover that has itself been removed is worse than none: it fails only under load."""
    fallback = manifest[Role.VISION].fallback.model_id
    catalogs = _without(live_catalogs_for(manifest), fallback)
    report = run_preflight(manifest=manifest, catalogs=catalogs)
    assert not report.ok
    assert any(i.model_id == fallback for i in report.failures)


def test_preflight_asserts_on_use_cases_not_on_type(manifest):
    """The primary vision model is typed text2text and genuinely sees images.

    A preflight that trusted ``type`` would reject the model that was runtime-verified to work.
    """
    vision = manifest[Role.VISION].primary
    assert vision.catalog_type != "image2text"
    assert "image" in vision.catalog_use_cases

    catalogs = live_catalogs_for(manifest)
    # image capability removed
    _entry(catalogs, vision.model_id)["flavors"][0]["use_cases"] = ["text", "reasoning"]
    report = run_preflight(manifest=manifest, catalogs=catalogs)
    assert not report.ok
    assert {i.kind for i in report.failures} == {"use_case_lost"}


def test_price_drift_warns_but_does_not_fail(manifest):
    catalogs = live_catalogs_for(manifest)
    next(iter(catalogs.values()))[0]["flavors"][0]["input_price_per_million_tokens"] = 99.0
    report = run_preflight(manifest=manifest, catalogs=catalogs)
    assert report.ok
    assert any(i.kind == "price_drift" for i in report.warnings)


def test_preflight_does_not_touch_the_network_when_given_a_catalog(manifest, transport):
    run_preflight(manifest=manifest, catalogs=live_catalogs_for(manifest), transport=transport)
    assert transport.gets == []


def _catalog_files(tmp_path, catalogs, name):
    arguments = []
    for provider, entries in catalogs.items():
        path = tmp_path / f"{name}-{provider}.json"
        path.write_text(json.dumps(entries), encoding="utf-8")
        arguments += ["--catalog-file", f"{provider}={path}"]
    return arguments


def test_cli_exit_codes(manifest, tmp_path, capsys):
    assert main(_catalog_files(tmp_path, live_catalogs_for(manifest), "good")) == 0

    withdrawn = manifest[Role.VISION].primary.model_id
    bad = _without(live_catalogs_for(manifest), withdrawn)
    assert main(_catalog_files(tmp_path, bad, "bad")) == 1


def test_a_provider_whose_catalog_is_not_supplied_is_refused_by_name(manifest):
    """A checked model's provider with no catalog is a refusal, never a skipped provider."""
    catalogs = live_catalogs_for(manifest)
    missing = manifest[Role.VISION].provider
    del catalogs[missing]
    with pytest.raises(PreflightError, match=missing):
        run_preflight(manifest=manifest, catalogs=catalogs)


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
