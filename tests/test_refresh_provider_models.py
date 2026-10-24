"""The operator's refresh of the provider models catalog, scripts/refresh_provider_models.py.

It writes the next catalog version from the provider's public catalog, its priced list of models
and each model's Hugging Face card, as metadata only, through a transport that reaches those three
origins and no other; the key goes to the provider's API alone and is never printed or written; a
version that exists is never rewritten, and a refused read writes nothing. Here every origin is
answered from memory by a stand-in transport, so nothing reaches a network.
"""

from __future__ import annotations

import json
import shutil
from datetime import date
from decimal import Decimal

import pytest
from exulanica.models import provider_catalog as catalog
from exulanica.models.egress import EgressRefused, declared_origin
from exulanica.models.manifest import load_manifest
from exulanica.models.transport import HttpResponse, HttpxTransport
from scripts import refresh_provider_models as refresh

from test_provider_catalog import NEW, PROVIDER, _complete_public

SERVED = load_manifest().providers[PROVIDER]
KEY = "the-operators-own-key"
CARD = {
    "id": NEW["model_id"],
    "sha": "0123456789abcdef0123456789abcdef01234567",
    "cardData": {"license": "apache-2.0", "language": ["en"]},
    "pipeline_tag": "text-generation",
    "safetensors": {"total": 9_000_000_000, "parameters": {"BF16": 9_000_000_000}},
    "createdAt": "2026-07-01T10:00:00.000Z",
}


def _rows() -> list[dict]:
    """The provider's priced list: every shipped model at the manifest's price, and the new one."""
    shipped = [
        (spec.model_id, spec.input_usd_per_mtok, spec.output_usd_per_mtok)
        for spec in load_manifest().models.values()
        if spec.provider == PROVIDER
    ]
    return [
        {
            "id": model_id,
            "context_length": 131072,
            "pricing": {"prompt": str(asked), "completion": str(answered)},
        }
        for model_id, asked, answered in [*shipped, (NEW["model_id"], "0.4", "1.2")]
    ]


class _Sources:
    """The three origins a refresh reads, answered from memory, with every ask recorded."""

    def __init__(
        self, *, public=None, prices_status: int = 200, cards=None, card_status: int = 404
    ) -> None:
        self.public = _complete_public(NEW) if public is None else public
        self.prices_status = prices_status
        self.cards = {NEW["model_id"]: CARD} if cards is None else cards
        self.card_status = card_status
        self.asked: list[tuple[str, dict]] = []

    def get_json(self, url, *, headers, timeout):
        self.asked.append((url, dict(headers)))
        if url == SERVED.catalog_url:
            return HttpResponse(status_code=200, text=json.dumps(self.public), headers={})
        if url == f"{SERVED.base_url.rstrip('/')}/models?verbose=true":
            body = {"object": "list", "data": _rows()}
            return HttpResponse(status_code=self.prices_status, text=json.dumps(body), headers={})
        if url.startswith(f"{refresh.HUGGING_FACE}/api/models/"):
            card = self.cards.get(url.removeprefix(f"{refresh.HUGGING_FACE}/api/models/"))
            if card is None:
                return HttpResponse(status_code=self.card_status, text="{}", headers={})
            return HttpResponse(status_code=200, text=json.dumps(card), headers={})
        raise AssertionError(f"a refresh asked {url}, which it never reads")

    def post_json(self, *arguments, **named):
        raise AssertionError("a refresh posts nothing and asks no model")


@pytest.fixture
def directory(tmp_path, monkeypatch):
    """A catalog directory holding the shipped version 1, with the operator's key set."""
    shutil.copy(catalog.CATALOG, tmp_path / "provider-models.v1.json")
    monkeypatch.setenv(SERVED.api_key_env, KEY)
    return tmp_path


def test_a_refresh_writes_the_next_version_with_each_model_s_price_and_card(directory, capsys):
    before = (directory / "provider-models.v1.json").read_bytes()
    sources = _Sources()
    assert refresh.main(["--directory", str(directory)], transport=sources) == 0
    assert (directory / "provider-models.v1.json").read_bytes() == before
    written = json.loads((directory / "provider-models.v2.json").read_text(encoding="utf-8"))
    assert (written["profile"], written["catalog_version"], written["read_on"]) == (
        catalog.PROFILE_WITH_FACTS,
        2,
        date.today().isoformat(),
    )
    assert written["licence_classes"] == json.loads(before)["licence_classes"]
    facts = catalog.read_facts(written)
    new = facts[f"{PROVIDER}|{NEW['model_id']}"]
    assert new.price == catalog.StatedPrice(Decimal("0.4"), Decimal("1.2"), 131072)
    assert new.card == catalog.CardFacts(
        repo=NEW["model_id"],
        revision=CARD["sha"],
        url=f"https://huggingface.co/{NEW['model_id']}",
        licence="apache-2.0",
        pipeline_tag="text-generation",
        parameters=9_000_000_000,
        created="2026-07-01",
    )
    shipped = [spec for spec in load_manifest().models.values() if spec.provider == PROVIDER]
    for spec in shipped:
        stated = facts[f"{PROVIDER}|{spec.model_id}"]
        assert stated.price is not None and stated.card is None
        assert stated.price.input_usd_per_mtok == spec.input_usd_per_mtok
    # The local model is no provider's to price or card here.
    assert all(
        (one.price, one.card) == (None, None)
        for key, one in facts.items()
        if not key.startswith(f"{PROVIDER}|")
    )
    printed = capsys.readouterr().out.splitlines()
    count = len(shipped) + 1
    assert printed[0] == (
        f"wrote provider-models.v2.json: {count} models stated, {count} priced, 1 with a card"
    )
    assert any(line.startswith("society_decision (needs text): ") for line in printed)
    # Nothing beyond metadata: the public catalog, one priced list, and one card read a model.
    assert [url for url, _ in sources.asked][:2] == [
        SERVED.catalog_url,
        f"{SERVED.base_url.rstrip('/')}/models?verbose=true",
    ]
    assert len(sources.asked) == 2 + count


def test_the_key_goes_only_to_the_provider_s_api_and_is_never_printed_or_written(directory, capsys):
    sources = _Sources()
    assert refresh.main(["--directory", str(directory)], transport=sources) == 0
    keyed = [url for url, headers in sources.asked if "Authorization" in headers]
    assert keyed == [f"{SERVED.base_url.rstrip('/')}/models?verbose=true"]
    assert all(KEY not in json.dumps(headers) for url, headers in sources.asked if url not in keyed)
    out, err = capsys.readouterr()
    assert KEY not in out and KEY not in err
    assert KEY not in (directory / "provider-models.v2.json").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("sources", "refused"),
    [
        (_Sources(prices_status=500), refresh.RefreshRefused),
        (_Sources(card_status=503), refresh.RefreshRefused),
        (_Sources(cards={NEW["model_id"]: {**CARD, "sha": "main"}}), refresh.RefreshRefused),
        (_Sources(public=[]), ValueError),
        (_Sources(public=_complete_public({**NEW, "model_id": "bad|identifier"})), ValueError),
    ],
)
def test_a_refused_read_writes_nothing(directory, sources, refused):
    before = sorted(path.name for path in directory.iterdir())
    with pytest.raises(refused):
        refresh.main(["--directory", str(directory)], transport=sources)
    assert sorted(path.name for path in directory.iterdir()) == before


def test_a_version_that_exists_is_never_rewritten(directory, monkeypatch):
    document = json.loads((directory / "provider-models.v1.json").read_text(encoding="utf-8"))
    taken = directory / "provider-models.v2.json"
    taken.write_text("a version written meanwhile\n")
    with pytest.raises(refresh.RefreshRefused, match="never rewritten"):
        refresh.write_new(taken, document)
    # Written between the look and the write, the version is still not replaced.
    monkeypatch.setattr(type(taken), "exists", lambda self: False)
    with pytest.raises(FileExistsError):
        refresh.write_new(taken, document)
    assert taken.read_text() == "a version written meanwhile\n"
    assert sorted(path.name for path in directory.iterdir()) == [
        "provider-models.v1.json",
        "provider-models.v2.json",
    ]


def test_without_the_key_nothing_is_asked(directory, monkeypatch, capsys):
    monkeypatch.delenv(SERVED.api_key_env)
    sources = _Sources()
    assert refresh.main(["--directory", str(directory)], transport=sources) == 2
    assert sources.asked == []
    assert capsys.readouterr().err.strip() == f"the provider's key is not in {SERVED.api_key_env}"
    assert not (directory / "provider-models.v2.json").exists()


def test_the_transport_it_builds_reaches_its_three_origins_and_no_other(directory, monkeypatch):
    built = []

    def recording(*, egress):
        built.append(egress)
        return _Sources()

    monkeypatch.setattr(refresh, "HttpxTransport", recording)
    assert refresh.main(["--directory", str(directory)]) == 0
    [egress] = built
    assert {str(origin) for origin in egress.origins} == {
        SERVED.catalog_origin,
        SERVED.origin,
        declared_origin("https://huggingface.co"),
    }
    # The real transport with that list refuses any other origin before a request is made.
    with pytest.raises(EgressRefused):
        HttpxTransport(egress=egress).get_json(
            "https://elsewhere.test/api/models", headers={}, timeout=1.0
        )
