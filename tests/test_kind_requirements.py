"""Declared semantics and shapes use deterministic checks; replies here are authored fixtures."""

from __future__ import annotations

import copy
import hashlib
import json

import pytest
from exulanica.models.schema import response_format_for
from exulanica.selection.kind_brief import brief_form, compile_brief
from exulanica.selection.kind_drafting import DRAFT_ATTEMPTS, draft_kind, kind_drafting_prompt
from exulanica.world.composers import site_plan
from exulanica.world.kinds import thing_leaves
from exulanica.world.kinds.catalogs import load_kind_catalogs
from exulanica.world.kinds.document import KindRefused, read_kind
from exulanica.world.kinds.samples import check_samples
from exulanica.world.kinds.shape_classes import load_shape_classes

from form_shapes import properties_after_an_array
from kind_briefs import PROVENANCE, brief_of, fixture_kind
from test_kind_drafting import ROLE, _checked, _client, _reply

DESCRIPTION = "A farm with a farmhouse, four beds, a duck pond and a flying boat."


def claim(words="farmhouse", labels=("farmhouse",), **constraints):
    return {
        "words": words,
        "status": "fulfilled",
        "omission": "",
        "form": "structure",
        "roles": [],
        "look": "",
        "shape_class": "",
        "roof_form": "",
        "minimum_count": 1,
        "part_labels": list(labels),
        **constraints,
    }


def farm(*requirements):
    brief = brief_of(fixture_kind("farm"))
    brief["requirements"] = list(requirements) or [claim()]
    return brief_form(requirement_contract=True).model_validate(brief).model_dump(mode="json")


def compile_(brief, description=DESCRIPTION, *, size=False):
    return compile_brief(
        brief,
        description=description,
        provenance={**PROVENANCE, "words_sha256": hashlib.sha256(description.encode()).hexdigest()},
        size=size,
    )


def part(document, label):
    return next(p for p in document["parts"] if p["label"] == label)


def structure(brief):
    return brief["zones"][0]["structures"][0]


def test_v7_schema_is_bounded_and_arrays_last():
    schema = response_format_for(brief_form(requirement_contract=True), arrays_last=True)[
        "json_schema"
    ]["schema"]
    assert properties_after_an_array(schema) == []
    assert "anyOf" not in json.dumps(schema)
    assert schema["properties"]["requirements"]["maxItems"] == 48
    assert '"part_labels"' in json.dumps(schema) and '"source_span"' not in json.dumps(schema)


def test_v7_drafter_binds_source_and_returns_omissions_without_retaining_words():
    omitted = claim("a flying boat", (), status="omitted", omission="unsupported_behavior", form="")
    brief = farm(claim(), omitted)
    invalid = copy.deepcopy(brief)
    invalid["requirements"][1]["words"] = "secret invented phrase"
    client, transport = _client(_reply(invalid), _reply(brief))
    outcome = draft_kind(client, DESCRIPTION, role=ROLE, check=_checked)
    assert outcome.attempts == ("check:kind_document_invalid", "passed")
    assert outcome.document["profile"] == "exulanica.world-kind/v2"
    assert outcome.document["provenance"]["prompt_version"] == "kind-drafting-7"
    assert [DESCRIPTION[a:b] for a, b in outcome.not_supported_at] == ["a flying boat"]
    assert (
        "secret invented phrase" not in transport.requests[1]["payload"]["messages"][-1]["content"]
    )
    reqs = outcome.document["requirements"]
    assert "words" not in json.dumps(reqs) and "part_labels" not in json.dumps(reqs)
    assert "a flying boat" not in json.dumps(outcome.document)
    assert (
        outcome.document["requirement_source"]["sha256"]
        == outcome.document["provenance"]["words_sha256"]
    )
    assert reqs[0]["parts"] == [part(outcome.document, "farmhouse")["key"]]


def test_partial_placeholder_and_missing_or_ambiguous_target_are_named_refusals():
    cases = [
        (farm(claim("person A")), "A farm for [person A]", "kind_document_invalid"),
        (farm(claim(labels=("missing",))), DESCRIPTION, "kind_requirement_unmet"),
    ]
    ambiguous = farm()
    structure(ambiguous)["rooms"][0]["label"] = "farmhouse"
    cases.append((ambiguous, DESCRIPTION, "kind_requirement_unmet"))
    for brief, words, code in cases:
        with pytest.raises(KindRefused) as error:
            compile_(brief, words)
        assert error.value.code == code


def test_a_target_label_matches_whatever_its_case_and_a_refusal_names_the_label_and_its_fault():
    """A real fishing village (26 October) was refused three times at requirements[0].part_labels
    by one sentence for two faults, so no repair could say what to change."""
    loose = farm(claim(labels=("  FarmHouse ",)))
    assert compile_(loose, DESCRIPTION).document["requirements"][0]["parts"]
    with pytest.raises(KindRefused) as error:
        compile_(farm(claim(labels=("lighthouse",))), DESCRIPTION)
    assert '"lighthouse" names no part' in error.value.detail
    assert '"farmhouse"' in error.value.detail
    ambiguous = farm()
    structure(ambiguous)["rooms"][0]["label"] = "farmhouse"
    with pytest.raises(KindRefused) as error:
        compile_(ambiguous, DESCRIPTION)
    assert '"farmhouse" names 2 parts' in error.value.detail


@pytest.mark.parametrize(
    "constraint",
    [
        {"form": "fixture"},
        {"roles": ["water"]},
        {"look": "structure.keep"},
        {"roof_form": "flat"},
        {"shape_class": "fortified_residence"},
        {"minimum_count": 2},
    ],
)
def test_labels_cannot_fulfill_wrong_form_roles_look_roof_shape_or_quantity(constraint):
    compiled = compile_(farm(claim(**constraint)))
    with pytest.raises(KindRefused) as error:
        read_kind(compiled.document)
    assert error.value.code == "kind_requirement_unmet"


def test_unplaced_water_cannot_fulfill_a_water_requirement():
    compiled = compile_(farm(claim("duck pond", ("duck pond",), form="area", roles=["water"])))
    document = compiled.document
    water = part(document, "duck pond")
    for zone in document["zones"]:
        zone["holds"] = [held for held in zone["holds"] if held["part"] != water["key"]]
    with pytest.raises(KindRefused) as error:
        read_kind(document)
    assert error.value.code == "kind_requirement_unmet" and "not placed" in error.value.detail


def test_quantities_include_nested_holding_minima_and_not_a_favorable_seed():
    brief = farm(claim("four beds", ("bed",), form="fixture", roles=["bed"], minimum_count=4))
    bedroom_brief = next(r for r in structure(brief)["rooms"] if r["label"] == "bedroom")
    bed = bedroom_brief["fixtures"][0]
    assert bed["label"] == "bed"
    bed["count"] = {"from": 2, "to": 3}
    compiled = compile_(brief)
    read_kind(compiled.document)
    bedroom = part(compiled.document, "bedroom")
    bedroom["holds"][0]["count"] = {"from": 1, "to": 3}
    with pytest.raises(KindRefused, match="kind_requirement_unmet"):
        read_kind(compiled.document)
    # A parameter's minimum, rather than the current preset, governs the claim too.
    document = compile_(brief).document
    document["parameters"] = [
        {
            "key": "beds",
            "label": "beds",
            "minimum": 1,
            "maximum": 3,
            "step": 1,
            "reason": "Test quantity range",
        }
    ]
    document["presets"][0]["values"] = {"beds": 2}
    part(document, bedroom["label"])["holds"][0]["count"] = {"parameter": "beds"}
    with pytest.raises(KindRefused, match="kind_requirement_unmet"):
        read_kind(document)


def test_omission_is_exclusive_and_an_unconstrained_claim_is_refused():
    for change in (
        {"status": "omitted", "omission": "unsupported_geometry"},
        {"omission": "unavailable_asset"},
        {"form": ""},
    ):
        compiled = compile_(farm(claim(**change)))
        with pytest.raises(KindRefused, match="kind_document_invalid"):
            read_kind(compiled.document)


def fortified(roof="catalog"):
    brief = farm(
        claim(
            "farmhouse",
            shape_class="fortified_residence",
            roof_form="flat" if roof == "catalog" else roof,
        )
    )
    structure(brief).update(
        shape_class="fortified_residence", shape_source="catalog", roof_form=roof
    )
    return brief


@pytest.mark.parametrize("roof", ["catalog", "gable"])
def test_fortified_dimensions_resolve_then_compose_and_replay_with_pinned_catalog(
    roof, monkeypatch
):
    compiled = compile_(fortified(roof), size=True)
    kind = read_kind(compiled.document)
    keep = part(compiled.document, "farmhouse")
    assert (keep["width_mm"], keep["depth_mm"], keep["storeys"], keep["storey_height_mm"]) == (
        20000,
        20000,
        5,
        3000,
    )
    assert keep["roof_form"] == ("flat" if roof == "catalog" else roof)
    assert keep["shape_class"] == load_shape_classes().reference("fortified_residence")
    report = check_samples(kind)
    assert report["verdict"] == "passed"
    made = site_plan.compose_kind(
        kind, kind.values(kind.presets[0][0]), "world:generated:fortified"
    )
    structures = [
        r for r in made.records if r.RECORD_KIND == "site.structure" and r.part_key == keep["key"]
    ]
    assert structures and all(r.storeys * r.storey_height_mm == 15000 for r in structures)
    assert made.receipt["catalogs"] == dict(load_kind_catalogs(bounds_version=2).sha256)

    def unavailable(*_args, **_kwargs):
        raise AssertionError("receipt reread drafting defaults")

    monkeypatch.setattr(thing_leaves, "load_thing_leaves", unavailable)
    assert site_plan.records(json.loads(json.dumps(made.receipt))) == made.records
    assert kind.reference()["profile"] == "exulanica.world-kind/v2"


def test_low_keep_and_range_endpoint_cannot_hide_behind_default_or_preset():
    document = compile_(fortified()).document
    keep = part(document, "farmhouse")
    keep["storeys"] = 2
    with pytest.raises(KindRefused, match="kind_shape_unmet"):
        read_kind(document)
    keep["storeys"] = {"from": 3, "to": 5}
    with pytest.raises(KindRefused, match="kind_shape_unmet"):
        read_kind(document)
    keep["storeys"] = 5
    keep["width_mm"] = keep["depth_mm"] = {"from": 20000, "to": 40000}
    with pytest.raises(KindRefused, match="kind_shape_unmet"):
        read_kind(document)


@pytest.mark.parametrize(
    "changed",
    [
        {"version": []},
        {"version": True},
        {"version": 2},
        {"sha256": "0" * 64},
        {"key": "defensive_wall"},
    ],
)
def test_invalid_shape_binding_is_a_named_refusal(changed):
    document = compile_(fortified()).document
    part(document, "farmhouse")["shape_class"].update(changed)
    with pytest.raises(KindRefused, match="kind_shape_unmet"):
        read_kind(document)


def test_defensive_wall_and_thin_mat_need_v2_but_do_not_change_v1():
    brief = farm(claim("farm", ("fence",), form="boundary", shape_class="defensive_wall"))
    brief["boundary"].update(shape_class="defensive_wall", shape_source="catalog")
    brief["site_fenced"] = True
    compiled = compile_(brief, size=True)
    boundary = part(compiled.document, "fence")
    assert (boundary["height_mm"], boundary["thickness_mm"]) == (5000, 1500)
    kind = read_kind(compiled.document)
    made = site_plan.compose_kind(kind, kind.values(kind.presets[0][0]), "world:generated:wall")
    assert any(r.RECORD_KIND == "site.wall" and r.thickness_mm == 1500 for r in made.records)
    assert site_plan.records(json.loads(json.dumps(made.receipt))) == made.records
    boundary["thickness_mm"] = 100
    with pytest.raises(KindRefused, match="kind_shape_unmet"):
        read_kind(compiled.document)

    brief = farm(claim("four beds", ("mat",), form="fixture", look="fixture.sleeping_mat"))
    mat = structure(brief)["rooms"][0]["fixtures"][0]
    mat.update(label="mat", look="fixture.sleeping_mat", size_source="catalog")
    document = compile_(brief).document
    assert part(document, "mat")["height_mm"] == 50
    read_kind(document)
    document["profile"] = "exulanica.world-kind/v1"
    del document["requirements"], document["requirement_source"]
    with pytest.raises(KindRefused, match="kind_out_of_bounds"):
        read_kind(document)


def test_prompt_refusals_cover_new_declared_invariants():
    prompt = kind_drafting_prompt()
    cases = {rule.case: rule.code for rule in prompt.rules}
    assert cases["false_requirement"] == "kind_requirement_unmet"
    assert cases["false_shape"] == "kind_shape_unmet"
    brief = fortified()
    structure(brief).update(
        shape_source="stated",
        storeys={"from": 2, "to": 2},
        width_mm={"from": 20000, "to": 20000},
        depth_mm={"from": 20000, "to": 20000},
    )
    client, _transport = _client(*[_reply(brief)] * DRAFT_ATTEMPTS)
    outcome = draft_kind(client, DESCRIPTION, role=ROLE, check=_checked)
    assert outcome.refusal.check[0] == cases["false_shape"]
    client, _transport = _client(*[_reply(farm(claim(form="fixture")))] * DRAFT_ATTEMPTS)
    outcome = draft_kind(client, DESCRIPTION, role=ROLE, check=_checked)
    assert outcome.refusal.check[0] == cases["false_requirement"]


def test_water_and_static_boat_claims_compose_as_distinct_content():
    words = "A harbour with water and two fishing boats"
    brief = farm(
        claim("water", ("duck pond",), form="area", roles=["water"]),
        claim(
            "two fishing boats",
            ("fishing boat",),
            form="fixture",
            look="vehicle.fishing_boat",
            minimum_count=2,
        ),
    )
    boat = copy.deepcopy(brief["zones"][0]["fixtures"][0])
    boat.update(
        label="fishing boat",
        description="a static fishing boat",
        look="vehicle.fishing_boat",
        size_source="catalog",
        count={"from": 2, "to": 3},
        roles=["decoration"],
        use_role="",
        work=[],
        visit=[],
        seats=0,
        stands=0,
        sleepers=0,
        blocks=True,
    )
    brief["zones"][0]["fixtures"].append(boat)
    compiled = compile_(brief, words, size=True)
    kind = read_kind(compiled.document)
    made = site_plan.compose_kind(
        kind, kind.values(kind.presets[0][0]), "world:generated:water-boat"
    )
    assert any(r.RECORD_KIND == "site.area" and "water" in r.roles for r in made.records)
    boats = [
        r for r in made.records if r.RECORD_KIND == "site.fixture" and r.look_family == "vehicle"
    ]
    assert len(boats) >= 2 and all(r.height_mm == 2000 for r in boats)
    assert site_plan.records(json.loads(json.dumps(made.receipt))) == made.records
    # Ordinary ground in place of the declared water cannot pass the same claim.
    part(compiled.document, "duck pond")["roles"] = ["ground"]
    with pytest.raises(KindRefused, match="kind_requirement_unmet"):
        read_kind(compiled.document)


def test_campfire_claim_refuses_a_building_and_resolves_a_fixture():
    words = "A campfire at a farmhouse"
    brief = farm(claim("campfire", ("farmhouse",), form="fixture", look="fixture.campfire"))
    with pytest.raises(KindRefused, match="kind_requirement_unmet"):
        read_kind(compile_(brief, words).document)
    fire = copy.deepcopy(brief["zones"][0]["fixtures"][0])
    fire.update(
        label="campfire",
        description="a campfire",
        look="fixture.campfire",
        size_source="catalog",
        count={"from": 1, "to": 1},
        roles=["decoration"],
        use_role="",
        work=[],
        visit=[],
        seats=0,
        stands=0,
        sleepers=0,
    )
    brief["zones"][0]["fixtures"].append(fire)
    brief["requirements"][0]["part_labels"] = ["campfire"]
    compiled = compile_(brief, words, size=True)
    assert part(compiled.document, "campfire")["height_mm"] == 600
    read_kind(compiled.document)


def test_thin_mat_replays_with_its_actual_height_after_samples():
    words = "A farmhouse with sleeping mats"
    brief = farm(claim("sleeping mats", ("mat",), form="fixture", look="fixture.sleeping_mat"))
    mat = next(r for r in structure(brief)["rooms"] if r["label"] == "bedroom")["fixtures"][0]
    mat.update(label="mat", look="fixture.sleeping_mat", size_source="catalog")
    kind = read_kind(compile_(brief, words, size=True).document)
    assert check_samples(kind)["verdict"] == "passed"
    made = site_plan.compose_kind(kind, kind.values(kind.presets[0][0]), "world:generated:mat")
    mats = [
        r for r in made.records if r.RECORD_KIND == "site.fixture" and r.look_leaf == "sleeping_mat"
    ]
    assert mats and all(r.height_mm == 50 for r in mats)
    assert site_plan.records(json.loads(json.dumps(made.receipt))) == made.records


def test_admission_instruction_budget_selects_the_published_prompt_bounds(monkeypatch):
    from exulanica.api import kind_drafts
    from exulanica.selection.kind_drafting import PROMPT_PATH, render_instructions
    from exulanica.world.society_living import town_routine

    try:
        for version in (5, 6, 7):
            prompt = kind_drafting_prompt(PROMPT_PATH.with_name(f"kind-drafting.v{version}.json"))
            monkeypatch.setattr(kind_drafts, "kind_drafting_prompt", lambda prompt=prompt: prompt)
            kind_drafts._instructions_characters.cache_clear()
            catalogs = load_kind_catalogs(bounds_version=2 if version == 7 else 1)
            assert kind_drafts._instructions_characters() == len(
                render_instructions(prompt, catalogs, town_routine())
            )
    finally:
        kind_drafts._instructions_characters.cache_clear()


@pytest.mark.parametrize(
    "change",
    [
        {"source_span": [True, 5]},
        {"source_span": [0, 1001]},
        {"roles": [[]]},
        {"parts": [None]},
        {"look": []},
        {"shape_class": {}},
        {"shape_class": "unknown_class"},
    ],
)
def test_malformed_requirement_values_are_named_refusals(change):
    document = compile_(farm()).document
    document["requirements"][0].update(change)
    with pytest.raises(KindRefused) as refused:
        read_kind(document)
    assert refused.value.code in ("kind_document_invalid", "kind_out_of_bounds")


def test_drafted_requirement_source_is_bound_to_provenance_and_cannot_extend_its_spans():
    document = compile_(farm()).document
    document["requirement_source"]["sha256"] = "0" * 64
    with pytest.raises(KindRefused, match="kind_document_invalid"):
        read_kind(document)
    document = compile_(farm()).document
    document["requirement_source"]["characters"] = 1
    with pytest.raises(KindRefused, match="kind_out_of_bounds"):
        read_kind(document)


def test_shape_constraint_covers_parameter_range_even_when_preset_fits():
    document = compile_(fortified()).document
    document["parameters"] = [
        {
            "key": "keep_width",
            "label": "Keep width",
            "minimum": 20000,
            "maximum": 40000,
            "step": 500,
            "reason": "Test range",
        }
    ]
    document["presets"][0]["values"] = {"keep_width": 20000}
    keep = part(document, "farmhouse")
    keep["width_mm"] = keep["depth_mm"] = {"parameter": "keep_width"}
    with pytest.raises(KindRefused, match="kind_shape_unmet"):
        read_kind(document)
