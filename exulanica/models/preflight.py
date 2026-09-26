"""Check every manifest identifier against the live catalog, and fail loudly if one is gone.

This is the mechanism that stops a vendor deprecation from silently breaking a running deployment.
Two rounds of removals landed in roughly ten weeks before this was written, ten and eleven models
each, and the next round lands on the vendor's schedule rather than on ours. A user could otherwise
hit a hard 404-class failure with nobody watching.

Three checks, and each one catches a different real failure:

1.  **Presence.** Every identifier a role can reach, primary and fallback alike, appears in
    ``flavors[].model_id``. A fallback that has itself been withdrawn is a failover that fails,
    which is worse than no failover because it is only discovered under load.
2.  **Capability.** The identifier still declares the ``use_cases`` its role needs. Asserted on
    ``use_cases`` and never on ``type``: a model typed ``text2text`` was runtime-verified to
    accept and correctly describe an image, so ``use_cases`` is authoritative and ``type`` is
    not.
3.  **Price drift.** The catalog price differs from the manifest price. A warning rather than a
    failure, because a price change breaks the cost report rather than the service, but silent
    price drift is how a cost report becomes fiction.

Each model is checked against the catalog of the provider serving it, read by that provider's
declared ``catalog_format``. Every model a role reaches is checked, and so is every model offered
to a role a world chooses, because a world may have chosen it.

Run it as ``exulanica-preflight``, the console script, or as
``python -m exulanica.models.preflight``. Exit status 0 clean, 1 on any failure, so CI and the
weekly uptime check on a running deployment can both call it without parsing output.
Pass ``--catalog-file PROVIDER=PATH`` to check a provider against a saved snapshot, which is how
the offline test runs.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

from exulanica.models.errors import PreflightError, TransportError
from exulanica.models.manifest import (
    CatalogFormat,
    Manifest,
    Provider,
    load_manifest,
    load_manifest_from,
)
from exulanica.models.transport import HttpxTransport, Transport

__all__ = [
    "PreflightIssue",
    "PreflightReport",
    "catalog_entries",
    "catalog_flavors",
    "fetch_catalog",
    "main",
    "run_preflight",
]

_TIMEOUT: Final = 60.0


@dataclass(frozen=True, slots=True)
class PreflightIssue:
    """One problem. ``fatal`` decides the exit status."""

    kind: str
    model_id: str
    roles: tuple[str, ...]
    detail: str
    fatal: bool = True

    def __str__(self) -> str:
        where = ", ".join(self.roles) or "unreferenced"
        mark = "FAIL" if self.fatal else "WARN"
        return f"[{mark}] {self.kind}: {self.model_id} ({where}) - {self.detail}"


@dataclass(frozen=True, slots=True)
class PreflightReport:
    checked: tuple[str, ...]
    catalog_size: int
    issues: tuple[PreflightIssue, ...]

    @property
    def failures(self) -> tuple[PreflightIssue, ...]:
        return tuple(i for i in self.issues if i.fatal)

    @property
    def warnings(self) -> tuple[PreflightIssue, ...]:
        return tuple(i for i in self.issues if not i.fatal)

    @property
    def ok(self) -> bool:
        return not self.failures

    def raise_for_status(self) -> None:
        if self.ok:
            return
        raise PreflightError(
            "model manifest does not match the live catalog:\n"
            + "\n".join(str(i) for i in self.failures)
        )

    def as_json(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checked": list(self.checked),
            "catalog_size": self.catalog_size,
            "issues": [
                {
                    "kind": i.kind,
                    "model_id": i.model_id,
                    "roles": list(i.roles),
                    "detail": i.detail,
                    "fatal": i.fatal,
                }
                for i in self.issues
            ],
        }


def catalog_flavors(catalog: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Map callable identifier to its flavor entry.

    Reads ``flavors[].model_id`` and never the human-readable ``name``. The two differ, and
    inconsistently: one identifier doubles its vendor prefix, another is entirely lowercase, a
    third swaps a dot for an underscore. Reading ``name`` produces a typo that 404s at runtime.
    """
    found: dict[str, dict[str, Any]] = {}
    for model in catalog:
        for flavor in model.get("flavors") or ():
            model_id = flavor.get("model_id")
            if isinstance(model_id, str) and model_id:
                merged = dict(flavor)
                merged.setdefault("license", model.get("license"))
                found[model_id] = merged
    return found


def fetch_catalog(url: str, *, transport: Transport | None = None) -> list[dict[str, Any]]:
    """Fetch the authoritative machine-readable catalog. No credential needed; it is public."""
    transport = transport or HttpxTransport()
    response = transport.get_json(url, headers={"Accept": "application/json"}, timeout=_TIMEOUT)
    if not response.ok:
        raise TransportError(f"catalog fetch returned HTTP {response.status_code} from {url}")
    body = response.json_body()
    if not isinstance(body, list):
        raise TransportError(f"catalog at {url} is not a JSON array")
    return body


def catalog_entries(
    provider: Provider, catalog: Sequence[Mapping[str, Any]]
) -> dict[str, dict[str, Any]]:
    """A provider's catalog as callable identifier to entry, read by its declared format."""
    if provider.catalog_format is CatalogFormat.MODEL_FLAVORS:
        return catalog_flavors(catalog)
    raise PreflightError(
        f"provider {provider.provider_id} declares catalog format {provider.catalog_format!r}, "
        "which the preflight has no reader for"
    )


def _roles_using(manifest: Manifest, model_id: str) -> tuple[str, ...]:
    bound = (
        str(binding.role)
        for binding in manifest.roles.values()
        if any(spec.model_id == model_id for spec in binding.chain)
    )
    chosen = (
        str(role)
        for role in manifest.chosen_roles
        if any(spec.model_id == model_id for spec in manifest.offered_models(role))
    )
    return tuple(sorted((*bound, *chosen)))


def _required_use_cases(manifest: Manifest, model_id: str) -> list[tuple[str, tuple[str, ...]]]:
    """Each role reaching ``model_id``, bound or chosen, with the use cases it needs."""
    needs = [
        (str(binding.role), binding.required_use_cases)
        for binding in manifest.roles.values()
        if any(spec.model_id == model_id for spec in binding.chain)
    ]
    needs.extend(
        (str(role), manifest.chosen(role).required_use_cases)
        for role in manifest.chosen_roles
        if any(spec.model_id == model_id for spec in manifest.offered_models(role))
    )
    return needs


def run_preflight(
    *,
    manifest: Manifest | None = None,
    catalogs: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    transport: Transport | None = None,
) -> PreflightReport:
    """Run all three checks. Fetches each provider's catalog unless ``catalogs`` supplies them.

    ``catalogs`` maps a provider key to that provider's catalog document. When it is given, it
    must hold every provider a checked model is served by: a provider it leaves out is refused by
    name rather than skipped.
    """
    manifest = manifest or load_manifest()
    referenced = sorted(manifest.referenced_model_ids())
    # By provider and identifier: two providers may list one identifier, and a model is checked
    # against its own provider's entry only.
    live: dict[tuple[str, str], dict[str, Any]] = {}
    size = 0
    for provider_id in sorted({manifest.spec(model_id).provider for model_id in referenced}):
        provider = manifest.provider(provider_id)
        if catalogs is None:
            catalog = fetch_catalog(provider.catalog_url, transport=transport)
        elif provider_id in catalogs:
            catalog = catalogs[provider_id]
        else:
            raise PreflightError(
                f"no catalog was supplied for provider {provider_id}, which serves a checked model"
            )
        entries = catalog_entries(provider, catalog)
        size += len(entries)
        live.update({(provider_id, model_id): entry for model_id, entry in entries.items()})

    issues: list[PreflightIssue] = []

    for model_id in referenced:
        roles = _roles_using(manifest, model_id)
        spec = manifest.spec(model_id)
        flavor = live.get((spec.provider, model_id))
        if flavor is None:
            issues.append(
                PreflightIssue(
                    kind="absent_from_catalog",
                    model_id=model_id,
                    roles=roles,
                    detail=(
                        f"not present in {spec.provider}'s flavors[].model_id. It has been "
                        "withdrawn, or the identifier is misspelled. Check casing before assuming "
                        "a deprecation."
                    ),
                )
            )
            continue

        declared = {str(u) for u in (flavor.get("use_cases") or ())}
        for role, required in _required_use_cases(manifest, model_id):
            missing = [u for u in required if u not in declared]
            if missing:
                issues.append(
                    PreflightIssue(
                        kind="use_case_lost",
                        model_id=model_id,
                        roles=(role,),
                        detail=(
                            f"role needs use_cases {sorted(required)}, catalog "
                            f"now declares {sorted(declared)}; missing {missing}"
                        ),
                    )
                )

        for field_name, attr in (
            ("input_price_per_million_tokens", "input_usd_per_mtok"),
            ("output_price_per_million_tokens", "output_usd_per_mtok"),
        ):
            live_price = flavor.get(field_name)
            if live_price is None:
                continue
            if Decimal(str(live_price)) != getattr(spec, attr):
                issues.append(
                    PreflightIssue(
                        kind="price_drift",
                        model_id=model_id,
                        roles=roles,
                        detail=(
                            f"{field_name}: catalog {live_price}, manifest {getattr(spec, attr)}. "
                            "The cost report is now wrong; update the manifest."
                        ),
                        fatal=False,
                    )
                )

    return PreflightReport(checked=tuple(referenced), catalog_size=size, issues=tuple(issues))


def _catalog_file(value: str) -> tuple[str, Path]:
    provider, separator, path = value.partition("=")
    if not separator or not provider or not path:
        raise argparse.ArgumentTypeError(f"{value!r} is not PROVIDER=PATH")
    return provider, Path(path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="exulanica-preflight",
        description="Check every model identifier in the manifest against its provider's catalog.",
    )
    parser.add_argument("--manifest", type=Path, default=None, help="alternate manifest JSON")
    parser.add_argument(
        "--catalog-file",
        type=_catalog_file,
        action="append",
        default=None,
        metavar="PROVIDER=PATH",
        help="check PROVIDER against a saved catalog snapshot instead of the network; repeat it "
        "for each provider a checked model is served by",
    )
    parser.add_argument("--json", action="store_true", help="emit the report as JSON")
    args = parser.parse_args(argv)

    manifest = load_manifest_from(args.manifest) if args.manifest else load_manifest()
    catalogs = None
    if args.catalog_file is not None:
        catalogs = {
            provider: json.loads(path.read_text(encoding="utf-8"))
            for provider, path in args.catalog_file
        }

    try:
        report = run_preflight(manifest=manifest, catalogs=catalogs)
    except TransportError as exc:
        # A catalog that cannot be reached is not a passing preflight. Saying so is the whole
        # point: the check exists to be believed when it is green.
        print(f"[FAIL] catalog unreachable: {exc}", file=sys.stderr)
        return 1
    except PreflightError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report.as_json(), indent=2))
    else:
        print(
            f"manifest {manifest.manifest_version}, pipeline version "
            f"{manifest.pipeline_version}: checked {len(report.checked)} identifiers against "
            f"{report.catalog_size} live catalog entries"
        )
        for issue in report.issues:
            print(str(issue), file=sys.stderr if issue.fatal else sys.stdout)
        if report.ok:
            print("[PASS] every referenced identifier resolves and still fits its role")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
