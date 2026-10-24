"""What the provider states of each model, and how each model's licence is classed.

The shipped catalog (``assets/catalogs/provider-models``) is held here to the two documents it is
made from, each read by itself and never through the catalog's reader: the shipped manifest, for
what it already states of its own models, and ``docs/license-matrix.md``, read as text, for the
verdict word in each classified model's own row. Then the rules: a licence is never guessed, and a
refresh rewrites what the provider states and never a class.
"""

from __future__ import annotations

import copy
import json
import re
from decimal import Decimal
from pathlib import Path

import pytest
from exulanica.models import provider_catalog as catalog
from exulanica.models.manifest import load_manifest
from exulanica.models.transport import HttpResponse

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "docs/license-matrix.md"
PROVIDER = "nebius_token_factory"


def _document() -> dict:
    return json.loads(catalog.CATALOG.read_text(encoding="utf-8"))


def _verdict_rows() -> list[tuple[list[str], str]]:
    """Every row of the licence matrix's verdict tables (a table whose last heading is Verdict):
    the names its first cell holds in backticks, and its verdict cell with its emphasis marks
    taken off. A table that only compares (its last heading is another) gives no verdict."""
    lines = MATRIX.read_text(encoding="utf-8").splitlines()
    rows, verdicts = [], False
    for at, line in enumerate(lines):
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        ruled = at + 1 < len(lines) and set(lines[at + 1]) <= set("|-: ") and "-" in lines[at + 1]
        if line.startswith("|") and ruled:
            verdicts = cells[-1] == "Verdict"
        elif line.startswith("| `") and verdicts:
            rows.append((re.findall(r"`([^`]+)`", cells[0]), cells[-1].replace("*", "").strip()))
    return rows


def _names(model_id: str) -> set[str]:
    """What a matrix row may call a model: its identifier or its short name, each also as the
    family the matrix writes with a trailing ``-*``."""
    short = model_id.partition("/")[2]
    return {model_id, short, f"{model_id}-*", f"{short}-*"}


# -- the classes against the licence matrix ------------------------------------------------------


def test_every_licence_class_is_the_verdict_word_of_that_model_s_own_row_in_the_matrix():
    classes = _document()["licence_classes"]
    rows = _verdict_rows()
    assert len(classes) == 26 and len(rows) > 60
    for entry in classes:
        model_id, cited, verdict = entry["model_id"], entry["row"], entry["verdict"]
        assert entry["matrix"] == "docs/license-matrix.md"
        # The row a class cites is a name of its own model, as the matrix writes it in backticks.
        assert cited.startswith("`") and cited.endswith("`"), (model_id, cited)
        assert cited.strip("`") in _names(model_id), (model_id, cited)
        # Exactly one verdict row names the model, by any of its names, and it is the one cited.
        naming = [(names, cell) for names, cell in rows if _names(model_id) & set(names)]
        assert len(naming) == 1, (model_id, naming)
        [(names, cell)] = naming
        assert cited.strip("`") in names, (model_id, cited, names)
        # The verdict cell is the word, then its end, a full stop or a comma: "SHIP" is not read
        # out of "SHIP if needed", "SHIP-ATTRIB" or "SHIP by license, but removed".
        assert re.match(re.escape(verdict) + r"(?=$|[.,])", cell), (model_id, verdict, cell)
        assert entry["class"] == catalog.VERDICT_CLASSES[verdict]


@pytest.mark.parametrize(
    ("cell", "verdict", "reads"),
    [
        ("SHIP", "SHIP", True),
        ("SHIP. The vision role's fallback", "SHIP", True),
        ("SHIP, trust HF (section 5).", "SHIP", True),
        ("SHIP if needed", "SHIP", False),
        ("SHIP-ATTRIB", "SHIP", False),
        ("SHIP by license, but removed", "SHIP", False),
        ("SHIP if needed. A licence of its own", "SHIP if needed", True),
        ("SHIP if needed and more", "SHIP if needed", False),
        ("CONDITIONAL. Offered to nobody", "CONDITIONAL", True),
        ("CONDITIONALLY", "CONDITIONAL", False),
    ],
)
def test_a_verdict_word_is_read_only_whole(cell, verdict, reads):
    assert bool(re.match(re.escape(verdict) + r"(?=$|[.,])", cell)) is reads


def test_the_matrix_s_tables_that_give_no_verdict_name_models_and_are_not_read():
    """The matrix names some of these models again in a table that compares two sources; its
    last heading is not Verdict, so no class can rest on a row of it."""
    text = MATRIX.read_text(encoding="utf-8")
    assert text.count("| `nvidia/nemotron-3-super-120b-a12b`") == 2
    rows = [
        names for names, _cell in _verdict_rows() if "nvidia/nemotron-3-super-120b-a12b" in names
    ]
    assert len(rows) == 1


def test_the_classes_are_the_ones_the_matrix_gives_today():
    by_class: dict[str, set[str]] = {}
    for entry in _document()["licence_classes"]:
        by_class.setdefault(entry["class"], set()).add(entry["model_id"])
    assert by_class[catalog.CONDITIONAL] == {
        "MiniMaxAI/MiniMax-M3",
        "google/gemma-3-27b-it",
        "NousResearch/Hermes-4-405B",
    }
    assert by_class[catalog.REJECTED] == {"moonshotai/Kimi-K3"}
    assert len(by_class[catalog.ACCEPTED]) == 22
    # Two models of one publisher under two licences are two rows, each with its own verdict.
    named = [names for names, _cell in _verdict_rows()]
    assert named.count(["zai-org/GLM-5.3"]) == 1 and named.count(["zai-org/GLM-5.3-Flash"]) == 1
    # Every row written from a licence read on a stated day says how strong the reading is.
    matrix = MATRIX.read_text(encoding="utf-8")
    assert matrix.count("on 2026-10-10, read through a text fetch; no file hashed") == 17
    # Every model a provider states today has a class under that provider; a model the matrix
    # does not name has none, whatever its licence is called, and neither has the same id under
    # another provider.
    stated = {(model.provider, model.model_id) for model in catalog.provider_models().values()}
    assert len(stated) == 26
    assert all(
        catalog.licence_class(provider, model_id) != catalog.NOT_CLASSIFIED
        for provider, model_id in stated
    )
    assert not any(_names("someone/New-Model-9B") & set(names) for names in named)
    assert catalog.licence_class(PROVIDER, "someone/New-Model-9B") == catalog.NOT_CLASSIFIED
    assert catalog.licence_class("another_provider", "Qwen/Qwen3.5-397B-A17B") == (
        catalog.NOT_CLASSIFIED
    )
    assert catalog.licence_class(PROVIDER, "moonshotai/Kimi-K3") == catalog.REJECTED
    assert catalog.licence_class(PROVIDER, "google/gemma-3-27b-it") == catalog.CONDITIONAL
    assert catalog.licence_class(PROVIDER, "openai/gpt-oss-120b") == catalog.ACCEPTED


def test_unverified_authors_no_class():
    # The matrix: "The license was not read. Not a verdict, an admission".
    assert "UNVERIFIED" not in catalog.VERDICT_CLASSES
    assert set(catalog.VERDICT_CLASSES.values()) == set(catalog.CLASSES)


# -- the entries against the manifest ------------------------------------------------------------


def test_every_model_of_the_shipped_manifest_is_stated_as_the_manifest_states_it():
    manifest = load_manifest()
    for spec in manifest.models.values():
        stated = catalog.provider_model(spec.provider, spec.model_id)
        assert stated is not None, spec.model_id
        assert stated.type == spec.catalog_type
        # The provider's use cases for it hold every one the manifest relies on.
        assert set(spec.catalog_use_cases) <= set(stated.use_cases), spec.model_id
        # Every model the manifest offers for a decision is one this product may call.
        if spec.answering:
            assert catalog.licence_class(spec.provider, spec.model_id) == catalog.ACCEPTED


def test_a_model_can_decide_only_as_a_chat_model_with_the_use_cases_the_role_requires():
    chat = catalog.ProviderModel(
        PROVIDER, "a/chat", "text2text", ("text", "code"), "x", "", "s", "d"
    )
    sees = catalog.ProviderModel(
        PROVIDER, "a/sees", "image2text", ("text", "image"), "x", "", "s", "d"
    )
    embeds = catalog.ProviderModel(
        PROVIDER, "an/embedder", "embedding", ("text",), "x", "", "s", "d"
    )
    assert catalog.decision_capable(chat, ("text",))
    assert catalog.decision_capable(sees, ("text",))
    assert not catalog.decision_capable(embeds, ("text",))
    assert not catalog.decision_capable(chat, ("text", "function_calling"))


# -- the reader's rules --------------------------------------------------------------------------


def _with_class(**members) -> dict:
    document = copy.deepcopy(_document())
    document["licence_classes"][0].update(members)
    return document


@pytest.mark.parametrize(
    "document",
    [
        # A class that is not its verdict's.
        _with_class(**{"class": "rejected"}),
        # A verdict word the matrix does not use, or the admission that is no verdict.
        _with_class(verdict="FINE"),
        _with_class(verdict="UNVERIFIED", **{"class": "accepted"}),
        # A class that cites no row.
        _with_class(row=" "),
    ],
)
def test_a_class_that_is_not_the_matrix_s_verdict_is_refused(document):
    with pytest.raises(ValueError, match="licence class"):
        catalog.read(document)


def test_a_model_stated_twice_or_with_a_member_missing_is_refused():
    twice = copy.deepcopy(_document())
    twice["entries"].append(copy.deepcopy(twice["entries"][0]))
    with pytest.raises(ValueError, match="invalid provider model"):
        catalog.read(twice)
    missing = copy.deepcopy(_document())
    del missing["entries"][0]["read_on"]
    with pytest.raises(ValueError, match="states exactly"):
        catalog.read(missing)


# -- the operator's refresh ----------------------------------------------------------------------


def _public(*flavors: dict) -> list[dict]:
    """A public catalog in the provider's own shape: one model a flavor."""
    return [
        {"name": flavor["model_id"], "license": flavor.pop("license"), "flavors": [flavor]}
        for flavor in (dict(one) for one in flavors)
    ]


NEW = {
    "model_id": "someone/New-Model-9B",
    "model_type": "text2text",
    "use_cases": ["text", "code"],
    # As the provider states one: a name and the address of its text.
    "license": {
        "url": "https://licences.test/apache-2.0",
        "name": "Apache 2.0 License",
        "type": "",
    },
}
KEPT = {
    "model_id": "openai/gpt-oss-120b",
    "model_type": "text2text",
    "use_cases": ["text", "reasoning"],
    "license": "A licence the provider now words another way",
}


def _complete_public(*flavors: dict) -> list[dict]:
    extra = {flavor["model_id"] for flavor in flavors}
    return _public(
        *flavors,
        *[
            {
                "model_id": spec.model_id,
                "model_type": spec.catalog_type,
                "use_cases": list(spec.catalog_use_cases),
                "license": spec.catalog_license,
            }
            for spec in load_manifest().models.values()
            if spec.model_id not in extra and spec.provider == PROVIDER
        ],
    )


def test_a_refresh_rewrites_what_the_provider_states_and_never_a_class():
    before = _document()
    after = catalog.refreshed(
        before,
        PROVIDER,
        _complete_public(NEW, KEPT),
        source="https://provider.test/models",
        read_on="2026-10-10",
    )
    models, classes = catalog.read(after)
    # The classes are byte for byte the ones a person authored.
    assert after["licence_classes"] == before["licence_classes"]
    # A model new to the provider is stated, and is not classified, whatever its licence's words.
    new = models[f"{PROVIDER}|someone/New-Model-9B"]
    assert (new.type, new.use_cases, new.licence_stated, new.licence_url) == (
        "text2text",
        ("text", "code"),
        "Apache 2.0 License",
        "https://licences.test/apache-2.0",
    )
    assert (new.source, new.read_on) == ("https://provider.test/models", "2026-10-10")
    assert f"{PROVIDER}|someone/New-Model-9B" not in classes
    # A model already classified keeps its class when the provider rewords its licence.
    kept = models[f"{PROVIDER}|openai/gpt-oss-120b"]
    assert (kept.licence_stated, kept.licence_url) == (
        "A licence the provider now words another way",
        "",
    )
    assert classes[f"{PROVIDER}|openai/gpt-oss-120b"] == catalog.ACCEPTED
    # A model the provider no longer lists leaves the entries; its class stays, since it names
    # a licence somebody read.
    assert f"{PROVIDER}|moonshotai/Kimi-K3" not in models
    assert classes[f"{PROVIDER}|moonshotai/Kimi-K3"] == catalog.REJECTED
    # Another provider's entries are not touched.
    other = copy.deepcopy(before)
    other["entries"].append(
        {
            **other["entries"][0],
            "key": "another|a/model",
            "provider": "another",
            "model_id": "a/model",
        }
    )
    again = catalog.refreshed(
        other,
        PROVIDER,
        _complete_public(NEW),
        source="https://provider.test/models",
        read_on="2026-10-10",
    )
    assert [entry for entry in again["entries"] if entry["provider"] == "another"] == [
        other["entries"][-1]
    ]


# -- versions, and the facts a version 2 catalog states -------------------------------------------

PRICE = {
    "input_usd_per_mtok": "0.06",
    "output_usd_per_mtok": "0.24",
    "context_window_tokens": 131072,
}
CARD = {
    "repo": "someone/New-Model-9B",
    "revision": "0123456789abcdef0123456789abcdef01234567",
    "url": "https://huggingface.co/someone/New-Model-9B",
    "licence": "apache-2.0",
    "pipeline_tag": "text-generation",
    "parameters": 9_000_000_000,
    "created": "2026-07-01",
}


def _with_facts(price: dict | None = PRICE, card: dict | None = CARD) -> dict:
    """The shipped catalog as a version 2: the first entry priced and carded, the rest neither."""
    document = copy.deepcopy(_document())
    document.update(profile=catalog.PROFILE_WITH_FACTS, catalog_version=2, read_on="2026-10-24")
    for at, entry in enumerate(document["entries"]):
        entry.update(price=price if at == 0 else None, card=card if at == 0 else None)
    return document


def test_the_server_reads_the_newest_version_and_every_older_one_stays_readable(tmp_path):
    """The catalog the server reads is the newest version beside it; a version 1 states no facts."""
    assert catalog.catalog_versions()[max(catalog.catalog_versions())] == catalog.CATALOG
    (tmp_path / "provider-models.v1.json").write_text(json.dumps(_document()))
    (tmp_path / "provider-models.v2.json").write_text(json.dumps(_with_facts()))
    (tmp_path / "provider-models.v2.json.tmp").write_text("{}")
    assert sorted(catalog.catalog_versions(tmp_path)) == [1, 2]
    assert catalog.read_facts(_document()) == {}
    assert catalog.read(_with_facts())[0] == catalog.read(_document())[0]


def test_a_version_2_entry_states_its_price_and_card_or_none():
    first = _document()["entries"][0]
    facts = catalog.read_facts(_with_facts())
    stated = facts[first["key"]]
    assert stated.price == catalog.StatedPrice(Decimal("0.06"), Decimal("0.24"), 131072)
    assert stated.card is not None and stated.card.parameters == 9_000_000_000
    assert (stated.card.licence, stated.card.created) == ("apache-2.0", "2026-07-01")
    assert all(
        (one.price, one.card) == (None, None) for key, one in facts.items() if key != first["key"]
    )


@pytest.mark.parametrize(
    ("price", "card"),
    [
        ({**PRICE, "input_usd_per_mtok": 0.06}, CARD),
        ({**PRICE, "context_window_tokens": 0}, CARD),
        ({**PRICE, "currency": "usd"}, CARD),
        (PRICE, {**CARD, "revision": "main"}),
        (PRICE, {**CARD, "url": "https://elsewhere.test/someone/New-Model-9B"}),
        (PRICE, {**CARD, "parameters": 0}),
        (PRICE, {**CARD, "licence": "<b>apache</b>"}),
        (PRICE, {**CARD, "created": "July 2026"}),
    ],
)
def test_a_price_or_card_that_is_not_plain_data_is_refused(price, card):
    with pytest.raises(ValueError):
        catalog.read(_with_facts(price, card))
    missing = _with_facts()
    del missing["read_on"]
    with pytest.raises(ValueError, match="the day it was read"):
        catalog.read(missing)
    unpriced = _with_facts()
    del unpriced["entries"][0]["price"]
    with pytest.raises(ValueError, match="states exactly"):
        catalog.read(unpriced)


def test_a_refresh_of_a_version_2_leaves_its_provider_s_facts_to_be_read_again():
    """Each rewritten entry states no price and no card, which the operator's script then reads;
    another provider's entries keep theirs."""
    before = _with_facts()
    other = {**before["entries"][0], "key": "another|a/model", "provider": "another"}
    before["entries"].append({**other, "model_id": "a/model"})
    after = catalog.refreshed(
        before,
        PROVIDER,
        _complete_public(NEW),
        source="https://provider.test/models",
        read_on="2026-10-24",
    )
    facts = catalog.read_facts(after)
    assert facts["another|a/model"].price is not None
    assert all(
        (one.price, one.card) == (None, None)
        for key, one in facts.items()
        if key.startswith(f"{PROVIDER}|")
    )


# -- prices, from the provider's own API origin --------------------------------------------------

KNOWN = {
    "maker/Shipped-One": (Decimal("0.06"), Decimal("0.24")),
    "maker/Shipped-Two": (Decimal("2.5"), Decimal("10")),
}


class _Listing:
    """A transport that answers the route listing models, and records what it was asked."""

    def __init__(self, rows: list[dict] | None, status: int = 200) -> None:
        self.body = {"object": "list", "data": rows} if rows is not None else {"object": "list"}
        self.status = status
        self.asked: list[tuple[str, dict]] = []

    def get_json(self, url, *, headers, timeout):
        self.asked.append((url, dict(headers)))
        return HttpResponse(status_code=self.status, text=json.dumps(self.body), headers={})

    def post_json(self, *arguments, **named):
        raise AssertionError("reading prices posts nothing and asks no model")


def _row(model_id: str, prompt, completion, window: int = 131072) -> dict:
    return {
        "id": model_id,
        "context_length": window,
        "pricing": {"prompt": prompt, "completion": completion, "request": "0"},
    }


def _prices(rows, status: int = 200):
    transport = _Listing(rows, status)
    found = catalog.prices("https://api.provider.test/v1/", "a-key", KNOWN, transport=transport)
    return found, transport


@pytest.mark.parametrize(
    ("one", "two", "new"),
    [
        # Dollars a token, as text.
        (("0.00000006", "0.00000024"), ("0.0000025", "0.00001"), ("0.0000004", "0.0000012")),
        # Dollars a million tokens, as numbers.
        ((0.06, 0.24), (2.5, 10), (0.4, 1.2)),
    ],
)
def test_prices_are_read_in_the_unit_the_shipped_models_prove(one, two, new):
    found, transport = _prices(
        [
            _row("maker/Shipped-One", *one),
            _row("maker/Shipped-Two", *two, window=1048576),
            _row("someone/New-Model-9B", *new, window=32768),
        ]
    )
    # One read, of the list route with its details, with the key in its header and nowhere else.
    [(url, headers)] = transport.asked
    assert url == "https://api.provider.test/v1/models?verbose=true"
    assert headers["Authorization"] == "Bearer a-key" and "a-key" not in url
    # The shipped models read as the manifest prices them, and the new one in the same unit.
    assert (
        found["maker/Shipped-One"].input_usd_per_mtok,
        found["maker/Shipped-One"].output_usd_per_mtok,
    ) == KNOWN["maker/Shipped-One"]
    new_price = found["someone/New-Model-9B"]
    assert (new_price.input_usd_per_mtok, new_price.output_usd_per_mtok) == (
        Decimal("0.4"),
        Decimal("1.2"),
    )
    assert new_price.context_window_tokens == 32768
    assert len(new_price.response_sha256) == 64


@pytest.mark.parametrize(
    ("rows", "status", "said"),
    [
        (None, 200, "is not a list"),
        ([], 503, "answered 503"),
        # No shipped model in the list: nothing proves the unit.
        (
            [_row("someone/New-Model-9B", "0.0000004", "0.0000012")],
            200,
            "holds no model the manifest",
        ),
        # No shipped model reads as the manifest prices it, under either unit.
        (
            [
                _row("maker/Shipped-One", "0.00000007", "0.00000024"),
                _row("maker/Shipped-Two", "0.0000026", "0.00001"),
            ],
            200,
            "under one unit",
        ),
        # The two shipped models read in two different units.
        (
            [
                _row("maker/Shipped-One", "0.00000006", "0.00000024"),
                _row("maker/Shipped-Two", 2.5, 10),
            ],
            200,
            "under one unit",
        ),
    ],
)
def test_prices_nothing_proves_are_refused_and_no_model_is_priced_by_a_guess(rows, status, said):
    with pytest.raises(catalog.ProviderPricesUnreadable, match=said):
        _prices(rows, status)


def test_a_row_that_states_no_price_or_no_window_is_left_out_and_never_priced_at_nothing():
    found, _transport = _prices(
        [
            _row("maker/Shipped-One", "0.00000006", "0.00000024"),
            {"id": "someone/No-Price", "context_length": 4096},
            {
                "id": "someone/No-Window",
                "pricing": {"prompt": "0.0000001", "completion": "0.0000001"},
            },
            _row("someone/Not-A-Number", "free", "0.0000001"),
            _row("someone/Negative", "-0.0000001", "0.0000001"),
        ]
    )
    assert set(found) == {"maker/Shipped-One"}


def test_a_shipped_model_whose_price_moved_proves_nothing_and_blocks_nothing():
    found, _transport = _prices(
        [
            _row("maker/Shipped-One", "0.00000007", "0.00000024"),
            _row("maker/Shipped-Two", "0.0000025", "0.00001"),
            _row("someone/New-Model-9B", "0.0000004", "0.0000012"),
        ]
    )
    # The unit is the one the other shipped model proves; the moved price is the provider's own.
    assert found["maker/Shipped-One"].input_usd_per_mtok == Decimal("0.07")
    assert found["someone/New-Model-9B"].output_usd_per_mtok == Decimal("1.2")


def test_zero_prices_cannot_prove_a_unit_and_boolean_context_is_not_a_window():
    known = {**KNOWN, "maker/Free": (Decimal(0), Decimal(0))}
    transport = _Listing(
        [
            _row("maker/Free", 0, 0),
            _row("maker/Shipped-One", "0.00000006", "0.00000024"),
            _row("someone/Boolean", "0.0000001", "0.0000002", window=True),
            _row("someone/Overflow", "1e999999999", "1e999999999"),
        ]
    )
    found = catalog.prices("https://api.provider.test/v1", "a-key", known, transport=transport)
    assert set(found) == {"maker/Free", "maker/Shipped-One"}
