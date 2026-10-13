"""What a provider states of each model it serves, and how each model's licence is classed.

A person may add a model the provider serves to the models that can decide for a being. Before
anything is spent the server must know two things no price list answers: whether the model can
decide at all (a chat model with the use cases a decision role requires), and whether its licence
lets this product call it. Both are data every deployment ships
(``assets/catalogs/provider-models/provider-models.v<N>.json``):

*   ``entries``: for each model id its type, its use cases and its licence as the provider words
    it, with where that was read and on what day. An operator's command rewrites them from the
    provider's public catalog (``python -m exulanica.models.provider_catalog refresh``); the
    server never does.
*   ``licence_classes``: for each model id somebody has read the licence of, the class this
    product gives it, authored from that model's own row of ``docs/license-matrix.md`` with the
    row's verdict word. The refresh never writes one.

What this module holds by construction:

*   **A licence is never guessed.** A class is the matrix's verdict for that model id and nothing
    else. A model with no authored class is *not classified*, whatever label the provider gives
    its licence: the matrix calls that label derived and not authoritative.
*   **Refreshing cannot admit a model.** The refresh rewrites what the provider states. A model
    that is new to the provider arrives not classified, and stays so until a person reads its
    licence into the matrix and authors its class.
*   **Nothing here asks a model.** The provider's catalog is public and read with no key; a
    model's price is read from the provider's own API origin, the one every deployment already
    allows, by its route that lists models (:func:`prices`).
*   **A price is the provider's or it is not served.** The list route's prices are read in the
    unit the shipped models prove: the one unit under which the provider's figures for a model
    the manifest already holds are the manifest's own. Where no shipped model proves a unit, or
    two prove different ones, the prices are refused by name and no model is priced by a guess.
    A shipped model whose price has moved proves nothing and blocks nothing: its figure is then
    the provider's, as every other model's is.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import cache
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit

from exulanica.models.manifest import load_manifest
from exulanica.models.preflight import catalog_flavors, fetch_catalog
from exulanica.models.transport import Transport

__all__ = [
    "ACCEPTED",
    "CATALOG",
    "CHAT_TYPES",
    "CLASSES",
    "CONDITIONAL",
    "NOT_CLASSIFIED",
    "PROFILE",
    "REJECTED",
    "VERDICT_CLASSES",
    "ProviderModel",
    "ProviderPrice",
    "ProviderPricesUnreadable",
    "catalog_sha256",
    "decision_capable",
    "licence_class",
    "prices",
    "provider_model",
    "provider_models",
    "read",
    "refreshed",
]

_ROOT: Final = Path(__file__).resolve().parents[2]
CATALOG: Final = _ROOT / "assets/catalogs/provider-models/provider-models.v1.json"
PROFILE: Final = "exulanica.provider-models/v1"
#: The types of model that answer in words, so can be asked a choice.
CHAT_TYPES: Final = ("text2text", "image2text")
#: How a model's licence is classed for this product calling it.
ACCEPTED: Final = "accepted"
#: Usable only while conditions its row names are met: not accepted until a review says they are.
CONDITIONAL: Final = "conditional"
REJECTED: Final = "rejected"
NOT_CLASSIFIED: Final = "not_classified"
CLASSES: Final = (ACCEPTED, CONDITIONAL, REJECTED)
#: The class each verdict word of the licence matrix gives. A verdict not here (``UNVERIFIED``,
#: which the matrix calls an admission and not a verdict) authors no class.
VERDICT_CLASSES: Final[Mapping[str, str]] = {
    "SHIP": ACCEPTED,
    "SHIP if needed": ACCEPTED,
    "CONDITIONAL": CONDITIONAL,
    "AVOID": REJECTED,
    "BLOCKED": REJECTED,
    "DISPUTED": REJECTED,
}
_ENTRY: Final = frozenset(
    {"key", "provider", "model_id", "type", "use_cases", "licence_stated", "licence_url"}
    | {"source", "read_on", "reason"}
)
_CLASS: Final = frozenset({"provider", "model_id", "class", "verdict", "matrix", "row"})
PROVIDER_PATTERN: Final = r"[a-z][a-z0-9_]{0,62}"
MODEL_PATTERN: Final = r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}"


def _text(value: Any, maximum: int, *, empty: bool = False) -> bool:
    return (
        isinstance(value, str)
        and (empty or bool(value.strip()))
        and len(value) <= maximum
        and not any(ord(char) < 32 or ord(char) == 127 or char in "<>" for char in value)
    )


def _https(value: Any, *, empty: bool = False) -> bool:
    if value == "" and empty:
        return True
    if not _text(value, 2048):
        return False
    try:
        url = urlsplit(value)
        return bool(
            url.scheme == "https"
            and url.hostname
            and url.port in (None, 443)
            and not url.username
            and not url.password
            and not url.fragment
            and not any(char.isspace() for char in value)
        )
    except ValueError:
        return False


def _identifier(provider: Any, model_id: Any) -> bool:
    return (
        isinstance(provider, str)
        and re.fullmatch(PROVIDER_PATTERN, provider) is not None
        and isinstance(model_id, str)
        and re.fullmatch(MODEL_PATTERN, model_id) is not None
    )


@dataclass(frozen=True, slots=True)
class ProviderModel:
    """One model as its provider states it: its type, use cases and the words of its licence."""

    provider: str
    model_id: str
    type: str
    use_cases: tuple[str, ...]
    licence_stated: str
    #: Where the provider says the licence's text is; empty where it names no address.
    licence_url: str
    source: str
    read_on: str


def _key(provider: str, model_id: str) -> str:
    return f"{provider}|{model_id}"


def read(document: Any) -> tuple[dict[str, ProviderModel], dict[str, str]]:
    """The models ``document`` states and the licence class it authors for each, by
    ``provider|model_id``; refused by name where it is no such catalog."""
    if not isinstance(document, Mapping) or document.get("profile") != PROFILE:
        raise ValueError(f"not a catalog of profile {PROFILE}")
    models: dict[str, ProviderModel] = {}
    for raw in document.get("entries") or ():
        if not isinstance(raw, Mapping) or set(raw) != _ENTRY:
            raise ValueError(f"a provider model states exactly {sorted(_ENTRY)}")
        key = _key(str(raw["provider"]), str(raw["model_id"]))
        uses = raw["use_cases"]
        plain = (
            _identifier(raw["provider"], raw["model_id"])
            and raw["key"] == key
            and key not in models
            and _text(raw["type"], 63)
            and isinstance(uses, list)
            and len(uses) <= 32
            and all(_text(use, 63) for use in uses)
            and _text(raw["licence_stated"], 512, empty=True)
            and _https(raw["licence_url"], empty=True)
            and _https(raw["source"])
            and _text(raw["read_on"], 10)
            and _text(raw["reason"], 4096)
        )
        if not plain:
            raise ValueError(f"invalid provider model {raw.get('key')!r}")
        date.fromisoformat(raw["read_on"])
        models[key] = ProviderModel(
            provider=str(raw["provider"]),
            model_id=str(raw["model_id"]),
            type=raw["type"],
            use_cases=tuple(uses),
            licence_stated=raw["licence_stated"],
            licence_url=raw["licence_url"],
            source=raw["source"],
            read_on=raw["read_on"],
        )
    classes: dict[str, str] = {}
    for raw in document.get("licence_classes") or ():
        if not isinstance(raw, Mapping) or set(raw) != _CLASS:
            raise ValueError(f"a licence class states exactly {sorted(_CLASS)}")
        key = _key(str(raw["provider"]), str(raw["model_id"]))
        # A class is the matrix's verdict for the model: the two are stated together and agree.
        if (
            not _identifier(raw["provider"], raw["model_id"])
            or key in classes
            or VERDICT_CLASSES.get(str(raw["verdict"])) != raw["class"]
        ):
            raise ValueError(f"invalid licence class for {key}")
        if not str(raw["row"]).strip() or not str(raw["matrix"]).strip():
            raise ValueError(f"the licence class for {key} names no row of the matrix")
        classes[key] = str(raw["class"])
    return models, classes


@cache
def _shipped() -> tuple[dict[str, ProviderModel], dict[str, str], str]:
    raw = CATALOG.read_bytes()
    models, classes = read(json.loads(raw))
    return models, classes, hashlib.sha256(raw).hexdigest()


def catalog_sha256() -> str:
    """Digest of the same catalog bytes this process's model and licence readers loaded."""
    return _shipped()[2]


def provider_models() -> Mapping[str, ProviderModel]:
    """Every model the shipped catalog states, by ``provider|model_id``."""
    return _shipped()[0]


def provider_model(provider: str, model_id: str) -> ProviderModel | None:
    """What the provider states of one model, or None where the catalog does not hold it."""
    return _shipped()[0].get(_key(provider, model_id))


def licence_class(provider: str, model_id: str) -> str:
    """How this product classes the licence of one model: :data:`ACCEPTED`, :data:`CONDITIONAL`
    or :data:`REJECTED` where a person authored it from the matrix, else :data:`NOT_CLASSIFIED`,
    whatever the provider says of the licence and whether or not the catalog holds the model."""
    return _shipped()[1].get(_key(provider, model_id), NOT_CLASSIFIED)


def decision_capable(model: ProviderModel, required_use_cases: Sequence[str]) -> bool:
    """Whether ``model`` can be asked a choice for a role that requires ``required_use_cases``: a
    chat model, by the provider's own type, whose use cases hold every one required."""
    return model.type in CHAT_TYPES and set(required_use_cases) <= set(model.use_cases)


# -- prices, from the provider's own API origin ----------------------------------------------

#: The units a provider may state a price in: dollars a token, or dollars a million tokens.
_SCALES: Final = (Decimal(1_000_000), Decimal(1))
_TIMEOUT: Final = 30.0


class ProviderPricesUnreadable(ValueError):
    """The provider's list of models could not be read as prices, by the reason it names."""


@dataclass(frozen=True, slots=True)
class ProviderPrice:
    """What one model costs, as its provider's API states it, in dollars a million tokens."""

    model_id: str
    input_usd_per_mtok: Decimal
    output_usd_per_mtok: Decimal
    context_window_tokens: int
    #: The digest of the response the figures were read from.
    response_sha256: str


def _figure(value: Any) -> Decimal | None:
    try:
        figure = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return (
        figure
        if (
            figure.is_finite()
            and 0 <= figure <= Decimal(1_000_000)
            and (figure.is_zero() or figure.adjusted() >= -18)
        )
        else None
    )


def prices(
    base_url: str,
    api_key: str,
    known: Mapping[str, tuple[Decimal, Decimal]],
    *,
    transport: Transport,
) -> dict[str, ProviderPrice]:
    """Every model's price as the provider's API states it at ``base_url``, by model id.

    One read of the route that lists models with their details. ``known`` is what the shipped
    manifest states of its own models (input and output dollars a million tokens). The unit of
    the provider's figures is the one under which some shipped model in the list reads exactly as
    the manifest prices it. Refused, by name, where the route does not answer a list, where it
    holds no shipped model, where none of them reads as the manifest's price under either unit,
    and where two of them prove different units."""
    response = transport.get_json(
        f"{base_url.rstrip('/')}/models?verbose=true",
        headers={"Accept": "application/json", "Authorization": f"Bearer {api_key}"},
        timeout=_TIMEOUT,
    )
    if not response.ok:
        raise ProviderPricesUnreadable(f"the list of models answered {response.status_code}")
    digest = hashlib.sha256(response.text.encode("utf-8")).hexdigest()
    body = response.json_body()
    rows = body.get("data") if isinstance(body, Mapping) else None
    if not isinstance(rows, list):
        raise ProviderPricesUnreadable("the list of models is not a list")
    read_rows: dict[str, tuple[Decimal, Decimal, int]] = {}
    for row in rows:
        pricing = row.get("pricing") if isinstance(row, Mapping) else None
        if not isinstance(pricing, Mapping) or not isinstance(row.get("id"), str):
            continue
        asked, answered = _figure(pricing.get("prompt")), _figure(pricing.get("completion"))
        window = row.get("context_length")
        if (
            asked is None
            or answered is None
            or type(window) is not int
            or window <= 0
            or re.fullmatch(MODEL_PATTERN, row["id"]) is None
        ):
            continue
        read_rows[row["id"]] = (asked, answered, window)
    shipped = [model_id for model_id in known if model_id in read_rows]
    if not shipped:
        raise ProviderPricesUnreadable("the list holds no model the manifest prices")
    proven = [
        scale
        for scale in _SCALES
        if any(
            known[model_id] != (Decimal(0), Decimal(0))
            and (read_rows[model_id][0] * scale, read_rows[model_id][1] * scale) == known[model_id]
            for model_id in shipped
        )
    ]
    if len(proven) != 1:
        raise ProviderPricesUnreadable(
            "the shipped models' prices do not read as the manifest's under one unit"
        )
    [scale] = proven
    return {
        model_id: ProviderPrice(model_id, asked * scale, answered * scale, window, digest)
        for model_id, (asked, answered, window) in read_rows.items()
    }


# -- the operator's refresh ------------------------------------------------------------------


def refreshed(
    document: Mapping[str, Any],
    provider: str,
    catalog: Sequence[Mapping[str, Any]],
    *,
    source: str,
    read_on: str,
) -> dict[str, Any]:
    """``document`` with ``provider``'s entries rewritten from its public ``catalog`` as read
    from ``source`` on ``read_on``. Every other provider's entries and every licence class are as
    they were: a model new to the provider arrives with no class, and a model the provider no
    longer lists leaves the entries and keeps its class, which names a licence somebody read."""
    read(document)
    if not catalog:
        raise ValueError("the provider catalog is empty")
    # Refuse a partial/malformed answer before catalog_flavors can silently skip or overwrite it.
    ids: set[str] = set()
    for model in catalog:
        flavors = model.get("flavors") if isinstance(model, Mapping) else None
        if not isinstance(flavors, list) or not flavors:
            raise ValueError("the provider catalog holds no model flavors")
        for flavor in flavors:
            model_id = flavor.get("model_id") if isinstance(flavor, Mapping) else None
            if not _identifier(provider, model_id) or model_id in ids:
                raise ValueError("the provider catalog holds an invalid or duplicate model id")
            ids.add(model_id)
            uses = flavor.get("use_cases")
            if not isinstance(uses, list) or not all(isinstance(use, str) for use in uses):
                raise ValueError("the provider catalog holds invalid use cases")
            licence = flavor.get("license", model.get("license"))
            if licence is not None and not isinstance(licence, str | Mapping):
                raise ValueError("the provider catalog holds an invalid licence")
    required = {
        spec.model_id for spec in load_manifest().models.values() if spec.provider == provider
    }
    if not required <= ids:
        raise ValueError(
            "the provider catalog omits a manifest model; review withdrawal before refresh"
        )
    kept = [entry for entry in document["entries"] if entry["provider"] != provider]
    earlier = {
        entry["model_id"]: entry for entry in document["entries"] if entry["provider"] == provider
    }
    stated = []
    for model_id, flavor in sorted(catalog_flavors(catalog).items()):
        before = earlier.get(model_id)
        # The provider states a licence as a name with the address of its text, or as a name.
        licence = flavor.get("license")
        named = licence if isinstance(licence, Mapping) else {"name": licence}
        stated.append(
            {
                "key": _key(provider, model_id),
                "provider": provider,
                "model_id": model_id,
                "type": flavor.get("model_type"),
                "use_cases": flavor["use_cases"],
                "licence_stated": named.get("name") or "",
                "licence_url": named.get("url") or "",
                "source": source,
                "read_on": read_on,
                "reason": before["reason"]
                if before is not None
                else "Stated by the provider's public catalog on the day it was read; listed so "
                "that a person may ask for this model, which is not classified until its "
                "licence is read into the licence matrix.",
            }
        )
    result = {**document, "entries": [*kept, *stated]}
    read(result)
    return result


def main(argv: Sequence[str] | None = None, *, transport: Transport | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    refresh = commands.add_parser("refresh", help="rewrite the entries from the public catalog")
    refresh.add_argument("--provider", default="nebius_token_factory")
    refresh.add_argument("--out", type=Path, default=CATALOG)
    arguments = parser.parse_args(argv)
    provider = load_manifest().providers.get(arguments.provider)
    if provider is None:
        parser.error("provider is not served by this installation")
    catalog = fetch_catalog(provider.catalog_url, transport=transport)
    document = refreshed(
        json.loads(CATALOG.read_text(encoding="utf-8")),
        arguments.provider,
        catalog,
        source=provider.catalog_url,
        read_on=date.today().isoformat(),
    )
    _write_catalog(arguments.out, document)
    models, classes = read(document)
    stated = [model for model in models.values() if model.provider == arguments.provider]
    unclassed = sum(1 for model in stated if _key(model.provider, model.model_id) not in classes)
    print(f"{len(stated)} models stated; {unclassed} of them not classified")
    return 0


def _write_catalog(path: Path, document: Mapping[str, Any]) -> None:
    """Replace a validated catalog atomically; a refused write leaves its old bytes intact."""
    read(document)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as stream:
            temporary = stream.name
            stream.write(json.dumps(document, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, path.stat().st_mode & 0o777 if path.exists() else 0o644)
        os.replace(temporary, path)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)


if __name__ == "__main__":
    raise SystemExit(main())
