"""Write the next version of the provider models catalog from where the models are: the provider's
own catalogs and each model's Hugging Face card, read as metadata only.

An operator runs it on their own machine, never the server, so the product's egress stays as it
is::

    uv run python scripts/refresh_provider_models.py [--provider nebius_token_factory]

with the provider's key in the variable the model manifest names for it (``api_key_env``,
``NEBIUS_API_KEY`` for Nebius Token Factory). It reads, through one transport whose egress
allowlist holds exactly three origins (the provider's public catalog's, the provider's API's and
Hugging Face's) and which follows no redirect:

1. the provider's public catalog (the manifest's ``catalog_url``), with no key: each model's type,
   use cases and licence as the provider words them
   (:func:`~exulanica.models.provider_catalog.refreshed`);
2. the provider's list of models with their prices, ``GET <base_url>/models?verbose=true``, with
   the operator's key in its Authorization header and nowhere else, read in the unit the
   manifest's own prices prove (:func:`~exulanica.models.provider_catalog.prices`); the key is
   never printed, written or sent to another origin;
3. for each model the provider serves, its card's metadata, ``GET
   https://huggingface.co/api/models/<id>``, with no key: the card's revision, licence, pipeline,
   parameters as its weights count them, and the day it was made. A model with no card there
   (or a gated or moved one) states none, and so does a model whose id is not a repository's own
   form (one optional organisation and one name, :data:`REPOSITORY`), for which nothing is read.

Nothing else is fetched: no weights, no README, and no model is asked anything. It writes
``provider-models.v<N+1>.json`` beside the newest version ``N``, profile
``exulanica.provider-models/v2``, with the day it was read and each entry's price and card (null
where none was read); every licence class stays as a person authored it, and a model new to the
provider arrives not classified. It never overwrites a version that exists, and writes nothing
when any read is refused. Then it prints, for each decision role, the models it can offer: chat
models with every use case the role requires whose licence is classed accepted.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any, Final
from urllib.parse import quote

from exulanica.models import provider_catalog
from exulanica.models.egress import declared_origin, parse_egress_allowlist
from exulanica.models.manifest import load_manifest
from exulanica.models.preflight import fetch_catalog
from exulanica.models.transport import HttpxTransport, Transport

#: Where each model's card is read, as metadata only.
HUGGING_FACE: Final = "https://huggingface.co"
#: A Hugging Face repository's own form, the only id a card is read for: an optional organisation
#: and one name, each starting and ending with a letter or digit and holding only letters, digits,
#: dots, hyphens and underscores, at most 96 characters, so no segment can leave the card's path.
_SEGMENT: Final = r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,94}[A-Za-z0-9])?"
REPOSITORY: Final = re.compile(rf"(?:{_SEGMENT}/)?{_SEGMENT}")
#: A card read waits no longer than a catalog read does.
TIMEOUT_SECONDS: Final = 30.0
#: The answers that mean the card is not served here to an anonymous read (absent, gated or
#: private, or moved): the model then states no card, and the run goes on.
NO_CARD: Final = frozenset({301, 302, 307, 308, 401, 403, 404})
#: What a version written here says of how it was made.
SOURCE_BUILD: Final = (
    "Derived: each entry is what a provider states of one model it serves (its type, its use "
    "cases and the words of its licence) from its public catalog, its price as the provider's API "
    "lists it, and what the model's Hugging Face card states as metadata, each read on the day "
    "the catalog names by scripts/refresh_provider_models.py; a price or a card that was "
    "not read is null. Authored: each licence class is this product's reading of that model's own "
    "row in docs/license-matrix.md, with the row's verdict word, and no script writes one."
)


class RefreshRefused(RuntimeError):
    """A read the refresh needs was refused, so no version is written."""


def _text(value: Any, maximum: int) -> str:
    """``value`` where it is plain text the catalog may hold, else empty."""
    return (
        value
        if isinstance(value, str)
        and len(value) <= maximum
        and not any(ord(char) < 32 or ord(char) == 127 or char in "<>" for char in value)
        else ""
    )


def card_path(model_id: str) -> str | None:
    """The path of ``model_id``'s card on Hugging Face's API, each segment quoted, or None where
    the id is not a repository's own form (:data:`REPOSITORY`, with no two dots or hyphens
    together), so that no card is read for it."""
    if REPOSITORY.fullmatch(model_id) is None or ".." in model_id or "--" in model_id:
        return None
    return "/api/models/" + "/".join(quote(segment, safe="") for segment in model_id.split("/"))


def card_facts(model_id: str, *, transport: Transport) -> dict[str, Any] | None:
    """What ``model_id``'s Hugging Face card states as metadata, as a catalog entry's ``card``, or
    None where no card is served to an anonymous read, or where the id is not a repository's own
    form, for which nothing is read. Refused by name on any other failure."""
    path = card_path(model_id)
    if path is None:
        return None
    response = transport.get_json(
        f"{HUGGING_FACE}{path}",
        headers={"Accept": "application/json"},
        timeout=TIMEOUT_SECONDS,
    )
    if response.status_code in NO_CARD:
        return None
    if not response.ok:
        raise RefreshRefused(f"the card of {model_id} answered {response.status_code}")
    body = response.json_body()
    repo = body.get("id") if isinstance(body, Mapping) else None
    revision = body.get("sha") if isinstance(body, Mapping) else None
    if (
        not isinstance(repo, str)
        or re.fullmatch(provider_catalog.MODEL_PATTERN, repo) is None
        or not isinstance(revision, str)
        or re.fullmatch(r"[0-9a-f]{40}", revision) is None
    ):
        raise RefreshRefused(f"the card of {model_id} names no repository and revision")
    stated = body.get("cardData")
    licence = stated.get("license") if isinstance(stated, Mapping) else None
    weights = body.get("safetensors")
    parameters = weights.get("total") if isinstance(weights, Mapping) else None
    created = body.get("createdAt")
    day = created[:10] if isinstance(created, str) else ""
    try:
        date.fromisoformat(day)
    except ValueError:
        day = ""
    return {
        "repo": repo,
        "revision": revision,
        "url": f"{HUGGING_FACE}/{repo}",
        "licence": _text(licence, 128),
        "pipeline_tag": _text(body.get("pipeline_tag"), 63),
        "parameters": parameters if type(parameters) is int and parameters > 0 else None,
        "created": day,
    }


def next_version(
    directory: Path,
    provider: str,
    *,
    key: str,
    read_on: str,
    transport: Transport,
) -> tuple[int, dict[str, Any]]:
    """The next catalog version's number and document: the newest version in ``directory``
    with ``provider``'s entries read again from its catalogs and each model's card."""
    manifest = load_manifest()
    served = manifest.providers[provider]
    versions = provider_catalog.catalog_versions(directory)
    newest = max(versions)
    public = fetch_catalog(served.catalog_url, transport=transport)
    document = provider_catalog.refreshed(
        json.loads(versions[newest].read_text(encoding="utf-8")),
        provider,
        public,
        source=served.catalog_url,
        read_on=read_on,
    )
    known = {
        spec.model_id: (spec.input_usd_per_mtok, spec.output_usd_per_mtok)
        for spec in manifest.models.values()
        if spec.provider == provider
    }
    try:
        listed = provider_catalog.prices(served.base_url, key, known, transport=transport)
    except provider_catalog.ProviderPricesUnreadable as exc:
        raise RefreshRefused(f"the provider's prices could not be read: {exc}") from exc
    entries = []
    for entry in document["entries"]:
        price, card = entry.get("price"), entry.get("card")
        if entry["provider"] == provider:
            found = listed.get(entry["model_id"])
            price = (
                None
                if found is None
                else {
                    "input_usd_per_mtok": str(found.input_usd_per_mtok),
                    "output_usd_per_mtok": str(found.output_usd_per_mtok),
                    "context_window_tokens": found.context_window_tokens,
                }
            )
            card = card_facts(entry["model_id"], transport=transport)
        entries.append({**entry, "price": price, "card": card})
    version = newest + 1
    written = {
        **document,
        "catalog_version": version,
        "profile": provider_catalog.PROFILE_WITH_FACTS,
        "read_on": read_on,
        "source_build": SOURCE_BUILD,
        "entries": entries,
    }
    provider_catalog.read(written)
    return version, written


def write_new(path: Path, document: Mapping[str, Any]) -> None:
    """Write ``document`` to ``path``, which must not exist: whole or not at all."""
    provider_catalog.read(document)
    if path.exists():
        raise RefreshRefused(f"{path.name} exists; a catalog version is never rewritten")
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as stream:
            temporary = stream.name
            stream.write(json.dumps(document, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        # A link fails where the name exists, so a version written meanwhile is never replaced.
        os.link(temporary, path)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)


def offers(document: Mapping[str, Any]) -> list[str]:
    """For each decision role, the models ``document`` lets it offer, as lines to print."""
    from exulanica.world.decision_roles import decision_roles

    models, classes = provider_catalog.read(document)
    lines = []
    for role in decision_roles():
        needed = role.chosen.required_use_cases
        capable = [
            key
            for key, model in sorted(models.items())
            if provider_catalog.decision_capable(model, needed)
        ]
        offered = [key for key in capable if classes.get(key) == provider_catalog.ACCEPTED]
        lines.append(
            f"{role.key} (needs {', '.join(needed)}): {len(offered)} of {len(capable)} capable "
            "models can be offered, the rest not classified or not accepted"
        )
        lines.extend(f"  {key.partition('|')[2]}" for key in offered)
    return lines


def main(argv: Sequence[str] | None = None, *, transport: Transport | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--provider", default="nebius_token_factory")
    parser.add_argument("--directory", type=Path, default=provider_catalog.CATALOG_DIRECTORY)
    arguments = parser.parse_args(argv)
    served = load_manifest().providers.get(arguments.provider)
    if served is None or served.api_key_env is None:
        parser.error("the manifest serves no provider by that name with a key to read its prices")
    key = os.environ.get(served.api_key_env, "")
    if not key:
        print(f"the provider's key is not in {served.api_key_env}", file=sys.stderr)
        return 2
    if transport is None:
        origins = {served.catalog_origin, served.origin, declared_origin(HUGGING_FACE)}
        transport = HttpxTransport(egress=parse_egress_allowlist(sorted(origins)))
    version, document = next_version(
        arguments.directory,
        arguments.provider,
        key=key,
        read_on=date.today().isoformat(),
        transport=transport,
    )
    path = arguments.directory / f"provider-models.v{version}.json"
    write_new(path, document)
    stated = [entry for entry in document["entries"] if entry["provider"] == arguments.provider]
    priced = sum(1 for entry in stated if entry["price"] is not None)
    carded = sum(1 for entry in stated if entry["card"] is not None)
    print(f"wrote {path.name}: {len(stated)} models stated, {priced} priced, {carded} with a card")
    for line in offers(document):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
