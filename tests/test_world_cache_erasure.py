"""Erasure cannot be undone by a town record computation finishing after cache eviction."""

from types import SimpleNamespace

from exulanica.world import generated_worlds as generated


def test_late_record_generation_does_not_retain_erased_content(monkeypatch):
    private, other = "a" * 64, "b" * 64
    monkeypatch.setattr(generated, "_records_kept", generated.OrderedDict({other: ("other",)}))
    receipt = {"composer": {"key": "test-composer", "version": 1}}
    monkeypatch.setattr(generated, "generation_receipt", lambda *args: (private, receipt))
    calls = []

    def records(document):
        calls.append(document)
        generated.forget_generated_records(frozenset({private}))
        return ("private derived words",)

    monkeypatch.setattr(
        generated, "composer_module", lambda *args: SimpleNamespace(records=records)
    )
    generated.town_records(None, None, "world", None)
    assert private not in generated._records_kept
    assert generated._records_kept[other] == ("other",)
    generated.town_records(None, None, "world", None)
    assert len(calls) == 2
