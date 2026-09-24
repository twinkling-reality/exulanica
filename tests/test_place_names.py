"""The rule for a place's saved name, with no database: what is offered, what is said, what counts.

:mod:`exulanica.consent.place_names` states the rule once. These tests hold it to every case a
stored decision can be in, fold every combination of a two-model chain, refuse every malformed
registry, and pin the modules that name each offered role to the registry's own list, so a new
caller of a role is read against the purpose a person agreed to before a grant can cover it.
"""

from __future__ import annotations

import copy
import datetime as dt
import importlib
import itertools
import json
import re
from pathlib import Path

import pytest
from exulanica.consent.place_names import (
    LastDecision,
    load_place_name_uses,
    model_state,
    parse_place_name_uses,
    read_use,
)
from exulanica.models.handoff import ModelHandoff, ModelIdentity
from exulanica.models.manifest import Role, load_manifest

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "exulanica/consent/place-name-uses.v1.json"
RAW = json.loads(REGISTRY.read_text(encoding="utf-8"))
USES = load_place_name_uses()
MANIFEST = load_manifest()
AT = dt.datetime(2026, 9, 23, 12, 0, tzinfo=dt.UTC)
#: An offered use whose role has a fallback. The rule is the same for every role; this is how a
#: two-model chain is held to it.
PLANNER_USE = USES.use("structured_extraction")
PLANNER = USES.handoff(PLANNER_USE, MANIFEST)
NOTICE = USES.notice(PLANNER_USE, PLANNER)
#: For each offered role, a module known to name it, so the scan below cannot pass empty.
NAMED_BY = {
    "embedding": "exulanica/selection/embeddings.py",
    "reasoning_cheap": "exulanica/selection/question.py",
    "structured_extraction": "exulanica/selection/proposal.py",
}


def _decision(identity: ModelIdentity, state: str, *, handoff: ModelHandoff = PLANNER):
    """A last decision that reads ``state`` at ``AT`` against ``NOTICE``, or None for never."""
    if state == "not_allowed":
        return None
    if state == "withdrawn":
        return LastDecision(
            identity=identity,
            destination=handoff.destination,
            event="withdrawn",
            decided_at=AT - dt.timedelta(hours=1),
            valid_until=None,
            notice=None,
            naming_holds=False,
        )
    return LastDecision(
        identity=identity,
        destination=handoff.destination,
        event="granted",
        decided_at=AT - dt.timedelta(days=1),
        valid_until=AT - dt.timedelta(seconds=1) if state == "ended" else AT + USES.term,
        notice="other words" if state == "notice_changed" else NOTICE,
        naming_holds=state != "name_changed",
    )


MODEL_STATES = ("allowed", "not_allowed", "withdrawn", "ended", "name_changed", "notice_changed")


# -- the registry ----------------------------------------------------------------------------------


def test_the_shipped_registry_offers_each_role_whose_requests_honour_a_release():
    """Every request of these roles leaves a place's name to the boundary; no other role's does.

    The Companion's call sites replace only the names no right can release. The vision stage's
    policy releases no place's name and a society decision's releases none, so neither is offered.
    """
    assert [use.role for use in USES.uses] == [
        Role.EMBEDDING,
        Role.REASONING_CHEAP,
        Role.STRUCTURED_EXTRACTION,
    ]
    for role in ("vision", "depth", "reasoning_mid"):
        assert USES.use(role) is None
    assert USES.term == dt.timedelta(days=90)


def test_every_offered_use_names_a_request_path_that_honours_a_release():
    """A use is never offered while inert: it names each path that sends a released name.

    Each path must resolve to a function in a module that names the role. What each path does with
    a released name is held where the redaction boundary is wired, by a request recorded per path.
    """
    for use in USES.uses:
        assert use.honoured_by, f"{use.role.value} is offered and names no path that honours it"
        for path in use.honoured_by:
            module_name, function_name = path.split(":")
            function = getattr(importlib.import_module(module_name), function_name, None)
            assert callable(function), f"{path} names no function"
            assert module_name.replace(".", "/") + ".py" in use.used_by, (
                f"{path} is not in a module that names the {use.role.value} role"
            )


def test_the_term_is_the_default_consent_principle_p3_states():
    """The term is stated once as data; rule P3 is the policy it implements, so the two agree."""
    doc = (ROOT / "docs/privacy-consent-threat-model.md").read_text(encoding="utf-8")
    (rule,) = [line for line in doc.splitlines() if line.startswith("| P3 |")]
    (stated,) = re.findall(r"default (\d+) days", rule)
    assert int(stated) == USES.term_days
    assert str(USES.term_days) not in USES.term_basis, "the number is stated once, as term_days"


def test_each_offered_role_lists_exactly_the_modules_that_name_it():
    """A new caller of an offered role fails here until its purpose sentence has been read again.

    The scan is of the ``exulanica`` package for ``Role.<MEMBER>``. ``exulanica/models/`` is left
    out: the manifest defines the roles and the client carries every request, and neither uses a
    role for a purpose of its own. A role named only as a string is not seen, which is why the
    positive control below requires the scan to find, for each role, a module known to name it.
    """
    found: dict[str, set[str]] = {use.role.value: set() for use in USES.uses}
    for path in sorted((ROOT / "exulanica").rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        if relative.startswith("exulanica/models/"):
            continue
        text = path.read_text(encoding="utf-8")
        for use in USES.uses:
            if re.search(rf"\bRole\.{use.role.name}\b", text):
                found[use.role.value].add(relative)
    assert set(found) == set(NAMED_BY), "the known namers and the offered roles differ"
    for role, module in NAMED_BY.items():
        assert module in found[role], f"the scan did not find {module} naming {role}"
    for use in USES.uses:
        assert sorted(found[use.role.value]) == list(use.used_by), (
            f"the modules naming {use.role.value} changed; read its purpose sentence "
            f"({use.purpose!r}) against them before changing used_by in {REGISTRY.name}"
        )


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda raw: raw.update(extra=1), "only the keys"),
        (lambda raw: raw.update(profile="exulanica.place-name-uses/v2"), "declares"),
        (lambda raw: raw.update(notice=raw["notice"].replace("{host}", "{origin}")), "fills"),
        (lambda raw: raw.update(notice=raw["notice"] + " "), "trimmed"),
        (lambda raw: raw.update(term_days=0), "positive number of days"),
        (lambda raw: raw.update(term_days=True), "positive number of days"),
        (lambda raw: raw.update(fallback_joiner="\n"), "printable"),
        (lambda raw: raw.update(uses=[]), "at least one use"),
        (lambda raw: raw["uses"].append(dict(raw["uses"][0])), "at most once"),
        (lambda raw: raw["uses"][0].update(purpose="two\nlines"), "control character"),
        (lambda raw: raw["uses"][0].update(used_by=raw["uses"][0]["used_by"][::-1]), "sorted"),
        (lambda raw: raw["uses"][0].update(note="x"), "exactly the keys"),
        (lambda raw: raw["uses"][0].update(honoured_by=[]), "at least one request path"),
        (lambda raw: raw["uses"][0].update(honoured_by=["embed_query"]), "module:function"),
        (
            lambda raw: raw["uses"][0].update(honoured_by=raw["uses"][0]["honoured_by"][::-1]),
            "sorted",
        ),
    ],
)
def test_a_malformed_registry_is_refused_whole(mutate, message):
    raw = copy.deepcopy(RAW)
    mutate(raw)
    with pytest.raises(ValueError, match=message):
        parse_place_name_uses(raw)


def test_a_role_the_manifest_does_not_state_is_refused():
    raw = copy.deepcopy(RAW)
    raw["uses"][0]["role"] = "depth"
    with pytest.raises(ValueError, match="depth"):
        parse_place_name_uses(raw)


# -- the notice ------------------------------------------------------------------------------------


def test_the_notice_names_every_model_and_the_host_and_no_place():
    for use in USES.uses:
        handoff = USES.handoff(use, MANIFEST)
        text = USES.notice(use, handoff)
        for identity in handoff.identities:
            assert identity.model_id in text
        assert "api.tokenfactory.nebius.com" in text
        assert use.purpose in text and "90 days" in text
        assert "{" not in text
    assert len(PLANNER.identities) == 2 and USES.fallback_joiner in NOTICE


def test_a_notice_is_written_only_for_a_hosted_hand_over_of_its_own_role():
    embedding = USES.use("embedding")
    with pytest.raises(ValueError, match="does not belong"):
        USES.notice(embedding, PLANNER)
    local = ModelHandoff.local(ModelIdentity.local("embedding", "local/model", "a" * 40))
    with pytest.raises(ValueError, match="hosted"):
        USES.notice(embedding, local)


def test_a_notice_longer_than_the_database_stores_is_refused():
    raw = copy.deepcopy(RAW)
    raw["uses"][0]["purpose"] = "read " * 500 + "it"
    uses = parse_place_name_uses(raw)
    with pytest.raises(ValueError, match="at most 2000"):
        uses.notice(uses.uses[0], uses.handoff(uses.uses[0], MANIFEST))


# -- one model's last decision ---------------------------------------------------------------------


@pytest.mark.parametrize("state", MODEL_STATES)
def test_each_last_decision_reads_as_what_it_is(state):
    identity = PLANNER.identities[0]
    assert model_state(_decision(identity, state), notice=NOTICE, at=AT) == state


def test_a_grant_ends_at_its_term_not_after():
    identity = PLANNER.identities[0]
    grant = _decision(identity, "allowed")
    just_before = grant.valid_until - dt.timedelta(microseconds=1)
    assert model_state(grant, notice=NOTICE, at=just_before) == "allowed"
    assert model_state(grant, notice=NOTICE, at=grant.valid_until) == "ended"


def test_a_decision_is_well_formed_or_refused():
    identity = PLANNER.identities[0]
    with pytest.raises(ValueError, match="notice and its term"):
        LastDecision(identity, PLANNER.destination, "granted", AT, None, NOTICE, True)
    with pytest.raises(ValueError, match="notice and its term"):
        LastDecision(identity, PLANNER.destination, "withdrawn", AT, AT, None, False)
    with pytest.raises(ValueError, match="rests on no naming"):
        LastDecision(identity, PLANNER.destination, "withdrawn", AT, None, None, True)
    with pytest.raises(ValueError, match="UTC offset"):
        LastDecision(
            identity, PLANNER.destination, "withdrawn", AT.replace(tzinfo=None), None, None, False
        )
    with pytest.raises(ValueError, match="UTC offset"):
        model_state(None, notice=NOTICE, at=AT.replace(tzinfo=None))


# -- a role's whole chain --------------------------------------------------------------------------


@pytest.mark.parametrize("states", list(itertools.product(MODEL_STATES, repeat=2)))
def test_a_chain_is_allowed_only_when_every_model_is(states):
    decisions = {
        (identity, PLANNER.destination): decision
        for identity, state in zip(PLANNER.identities, states, strict=True)
        if (decision := _decision(identity, state)) is not None
    }
    reading = read_use(PLANNER_USE, PLANNER, notice=NOTICE, decisions=decisions, at=AT)
    assert reading.allowed == (states == ("allowed", "allowed"))
    assert tuple(state for _, state in reading.models) == states
    if reading.allowed:
        assert reading.since is not None and reading.until == AT + USES.term
    else:
        assert reading.since is None and reading.until is None
        assert reading.state != "allowed"
    if set(states) == {"allowed", "not_allowed"}:
        assert reading.state == "models_changed"
    elif len(set(states)) == 1:
        assert reading.state == states[0]


def test_a_decision_for_another_model_or_destination_is_not_counted():
    primary, fallback = PLANNER.identities
    decisions = {
        (primary, PLANNER.destination): _decision(primary, "allowed"),
        (fallback, "https://elsewhere.example"): _decision(fallback, "allowed"),
    }
    reading = read_use(PLANNER_USE, PLANNER, notice=NOTICE, decisions=decisions, at=AT)
    assert reading.state == "models_changed" and not reading.allowed
    assert reading.changed_at == AT - dt.timedelta(days=1)


def test_a_chain_never_decided_reads_as_never_decided():
    reading = read_use(PLANNER_USE, PLANNER, notice=NOTICE, decisions={}, at=AT)
    assert reading.state == "not_allowed" and reading.changed_at is None
