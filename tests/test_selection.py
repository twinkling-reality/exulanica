"""The Selection primitive: what may be asked, what is refused, and what comes back.

Everything here is deterministic. No model runs in any of these tests, and that is the point
being demonstrated rather than a convenience: a plan may have come from a language model, and
what happens to it afterwards is a fixed validator and a fixed compiler. The two model calls in
the path have their own file.

The set-algebra cases come from ``evaluation-methodology.md`` M6, which sets the bar at
"**Set exact-match rate**: returned photograph or region set equals the gold set. **Pass: 100%.**
This is set algebra over a known graph. Anything below 100% is a bug, not a model limitation."
Its trap (c) is called "the single highest-value trap in the suite, because it is where a filter
of this shape silently goes wrong", and it has a test below by that name.
"""

from __future__ import annotations

import copy
import datetime as dt
import uuid

import pytest
from exulanica.epistemics.assertions import AssertionWriter
from exulanica.identity import IdentityRepository, confirm_link, name_occurrence
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.selection import (
    CaptureWindow,
    EntityMode,
    EntitySelector,
    EpistemicScope,
    Intent,
    PlaceSelector,
    RejectionCode,
    SelectionPlan,
    SelectionRejected,
    Session,
    execute,
    parse,
    validate,
)
from exulanica.selection.plan import CaptureSelector, ProcessingState
from exulanica.store.local import LocalContentAddressedStore

from conftest import DEFAULT_PAYLOAD, CountingVisionModel, ingest_observed, write_photo

#: Boxes far enough apart that the 16x16 identity-key grid puts them in different cells, so two
#: people in one photograph are two occurrences rather than one.
_LEFT = {"x": 0.05, "y": 0.1, "w": 0.2, "h": 0.6}
_RIGHT = {"x": 0.70, "y": 0.1, "w": 0.2, "h": 0.6}


def _payload(*, people: int, place: str | None, caption: str) -> dict:
    """A vision payload with a controlled number of located people."""
    payload = copy.deepcopy(DEFAULT_PAYLOAD)
    payload["scene_description"] = caption
    payload["objects"] = [entry for entry in payload["objects"] if entry["label"] != "person"]
    for box in (_LEFT, _RIGHT)[:people]:
        payload["objects"].append(
            {
                "label": "person",
                "salience": "primary",
                "confidence": "high",
                "box": dict(box),
            }
        )
    if place is None:
        payload["proposed_place"] = None
    else:
        payload["proposed_place"]["label"] = place
    return payload


class Library:
    """Four photographs with a known, hand-checkable graph.

    ================  =======  ==========  =================================================
    photograph        people   place       purpose
    ================  =======  ==========  =================================================
    together.jpg      A and B  Gullfoss    the only capture where the two share a photograph
    alone_a.jpg       A        Gullfoss    A without B, same place
    alone_b.jpg       B        Lisbon   B without A, a different place and a later day
    empty.jpg         none     Lisbon   nobody, so ANY over {A, B} must exclude it
    ================  =======  ==========  =================================================

    That table is the gold set for every case below, and it is small enough to check by eye,
    which is the property M6 needs: "set algebra over a known graph".
    """

    def __init__(self, repository, identity, assertions, actor) -> None:
        self.repository = repository
        self.identity = identity
        self.assertions = assertions
        self.actor = actor
        self.captures: dict[str, uuid.UUID] = {}
        self.entities: dict[str, uuid.UUID] = {}

    @property
    def session(self) -> Session:
        return Session(workspace_id=self.repository.workspace_id, actor=self.actor)

    def run(self, plan: SelectionPlan):
        validated = validate(self.repository.connection, plan, self.session)
        return execute(self.repository.connection, validated)

    def matched(self, plan: SelectionPlan) -> set[str]:
        by_id = {capture_id: name for name, capture_id in self.captures.items()}
        return {by_id[capture.capture_id] for capture in self.run(plan).captures}


@pytest.fixture
def library(tmp_path, photo_dir, repository):
    store = LocalContentAddressedStore(tmp_path / "blobs")
    actor = uuid.uuid4()
    built = Library(
        repository,
        IdentityRepository(repository.connection, repository.workspace_id),
        AssertionWriter(repository.connection, repository.workspace_id),
        actor,
    )
    plates = [
        ("together", 2, "Gullfoss", "2026:03:04 10:00:00", "Two people beside a waterfall."),
        ("alone_a", 1, "Gullfoss", "2026:03:04 11:00:00", "One person beside a waterfall."),
        ("alone_b", 1, "Lisbon", "2026:05:20 09:00:00", "One person on a city street."),
        ("empty", 0, "Lisbon", "2026:05:20 09:30:00", "A harbour with boats and no people."),
    ]
    for name, people, place, when, caption in plates:
        vision = CountingVisionModel(payload=_payload(people=people, place=place, caption=caption))
        pipeline = PhotoIngestPipeline(repository, store, vision=vision)
        outcome = ingest_observed(
            pipeline, repository, write_photo(photo_dir, f"{name}.jpg", when=when)
        )
        assert outcome.error is None, outcome.error
        built.captures[name] = outcome.capture_id

    # Name the two people from the photograph where both appear, then confirm each of them in
    # the photograph where they are alone. Left is A, right is B, by the identity key's grid.
    people = repository.connection.execute(
        "select occurrence_id, capture_id, primary_span_id, s.region "
        "from occurrence o join evidence_span s on s.span_id = o.primary_span_id "
        "where o.class = 'person' order by s.region->'rect'->>'x'"
    ).fetchall()
    in_together = [row for row in people if row["capture_id"] == built.captures["together"]]
    assert len(in_together) == 2, in_together
    for label, row in zip(("A", "B"), in_together, strict=True):
        named = name_occurrence(
            built.identity,
            built.assertions,
            occurrence_id=row["occurrence_id"],
            display_name=label,
            actor=actor,
        )
        built.entities[label] = named.entity_id
    for label, capture in (("A", "alone_a"), ("B", "alone_b")):
        solo = next(
            row for row in people if row["capture_id"] == built.captures[capture]
        )
        confirm_link(
            built.identity,
            occurrence_id=solo["occurrence_id"],
            entity_id=built.entities[label],
            actor=actor,
        )

    # Places are entities too, and the same mechanism names them.
    places = repository.connection.execute(
        "select o.occurrence_id, o.capture_id from occurrence o where o.class = 'place' "
        "order by o.occurrence_id"
    ).fetchall()
    for row in places:
        label = "Gullfoss" if row["capture_id"] in {
            built.captures["together"],
            built.captures["alone_a"],
        } else "Lisbon"
        if label in built.entities:
            confirm_link(
                built.identity,
                occurrence_id=row["occurrence_id"],
                entity_id=built.entities[label],
                actor=actor,
            )
        else:
            named = name_occurrence(
                built.identity,
                built.assertions,
                occurrence_id=row["occurrence_id"],
                display_name=label,
                actor=actor,
            )
            built.entities[label] = named.entity_id
    return built


def _plan(**kwargs) -> SelectionPlan:
    kwargs.setdefault("intent", Intent.CAPTURES)
    return SelectionPlan(**kwargs)


# -- M6: ANY, ALL and TOGETHER -----------------------------------------------------------


def test_any_returns_every_capture_holding_at_least_one_of_them(library):
    plan = _plan(
        entities=EntitySelector(
            ids=[library.entities["A"], library.entities["B"]], mode=EntityMode.ANY
        )
    )
    assert library.matched(plan) == {"together", "alone_a", "alone_b"}


def test_all_returns_the_scope_even_where_they_never_share_a_photograph(library):
    """M6: "ALL means every named entity present within the scope, not necessarily in the same
    photograph."

    The scope here is the whole library, so ALL over a pair who both appear somewhere returns
    everything, including the photograph with nobody in it. That is the looser reading and it is
    the one M6 specifies.
    """
    plan = _plan(
        entities=EntitySelector(
            ids=[library.entities["A"], library.entities["B"]], mode=EntityMode.ALL
        )
    )
    assert library.matched(plan) == {"together", "alone_a", "alone_b", "empty"}


def test_together_over_a_pair_that_never_shares_a_photograph_returns_empty(library):
    """M6 trap (c), "the single highest-value trap in the suite".

    A and the place Lisbon are both present in the library and never in one photograph.
    TOGETHER must return empty while ALL over the same pair returns the region.
    """
    pair = [library.entities["A"], library.entities["Lisbon"]]
    together = _plan(entities=EntitySelector(ids=pair, mode=EntityMode.TOGETHER))
    every = _plan(entities=EntitySelector(ids=pair, mode=EntityMode.ALL))
    assert library.matched(together) == set()
    assert library.matched(every) != set()


def test_together_returns_only_the_capture_they_share(library):
    plan = _plan(
        entities=EntitySelector(
            ids=[library.entities["A"], library.entities["B"]], mode=EntityMode.TOGETHER
        )
    )
    assert library.matched(plan) == {"together"}


def test_all_over_entities_that_never_co_occur_in_the_scope_returns_empty(library):
    """M6 trap (a): it "must return empty rather than 'no results, here is something similar'".

    Scoped to the March day, B is absent, so ALL over the pair returns nothing at all rather
    than the captures A does appear in.
    """
    # A window holding only the photograph A is alone in. B is nowhere in this scope, so the
    # pair is not covered by it, and the whole scope drops rather than degrading to A's captures.
    without_b = CaptureWindow(
        start=dt.datetime(2026, 3, 4, 10, 30, tzinfo=dt.UTC),
        end=dt.datetime(2026, 3, 5, tzinfo=dt.UTC),
    )
    plan = _plan(
        entities=EntitySelector(
            ids=[library.entities["A"], library.entities["B"]], mode=EntityMode.ALL
        ),
        time=[without_b],
    )
    assert library.matched(plan) == set()
    # The scope itself is not empty, so the emptiness is the ALL predicate and not the window.
    assert library.matched(_plan(time=[without_b])) == {"alone_a"}
    # And widening the scope to a day that does hold both of them brings the whole scope back.
    march = CaptureWindow(
        start=dt.datetime(2026, 3, 4, tzinfo=dt.UTC), end=dt.datetime(2026, 3, 5, tzinfo=dt.UTC)
    )
    assert library.matched(
        _plan(
            entities=EntitySelector(
                ids=[library.entities["A"], library.entities["B"]], mode=EntityMode.ALL
            ),
            time=[march],
        )
    ) == {"together", "alone_a"}


def test_all_and_together_need_at_least_two_entities(library):
    for mode in (EntityMode.ALL, EntityMode.TOGETHER):
        with pytest.raises(SelectionRejected) as rejected:
            parse(
                {
                    "intent": "captures",
                    "entities": {"ids": [str(library.entities["A"])], "mode": str(mode)},
                }
            )
        assert rejected.value.code is RejectionCode.MALFORMED_PLAN


# -- time and place ----------------------------------------------------------------------


def test_a_time_window_is_half_open(library):
    """Two adjacent windows tile without either capture landing in both."""
    morning = CaptureWindow(
        start=dt.datetime(2026, 3, 4, 10, tzinfo=dt.UTC),
        end=dt.datetime(2026, 3, 4, 11, tzinfo=dt.UTC),
    )
    later = CaptureWindow(
        start=dt.datetime(2026, 3, 4, 11, tzinfo=dt.UTC),
        end=dt.datetime(2026, 3, 4, 12, tzinfo=dt.UTC),
    )
    assert library.matched(_plan(time=[morning])) == {"together"}
    assert library.matched(_plan(time=[later])) == {"alone_a"}
    assert library.matched(_plan(time=[morning, later])) == {"together", "alone_a"}


def test_place_narrows_to_the_captures_confirmed_at_it(library):
    plan = _plan(place=PlaceSelector(ids=[library.entities["Lisbon"]]))
    assert library.matched(plan) == {"alone_b", "empty"}


def test_dimensions_combine_with_and(library):
    """A at Gullfoss in March is one photograph, not the union of three filters."""
    plan = _plan(
        entities=EntitySelector(ids=[library.entities["A"]], mode=EntityMode.ANY),
        place=PlaceSelector(ids=[library.entities["Gullfoss"]]),
        time=[
            CaptureWindow(
                start=dt.datetime(2026, 3, 4, 10, 30, tzinfo=dt.UTC),
                end=dt.datetime(2026, 3, 5, tzinfo=dt.UTC),
            )
        ],
    )
    assert library.matched(plan) == {"alone_a"}


def test_the_free_text_field_matches_capture_derived_text(library):
    assert library.matched(_plan(semantic_query="waterfall")) == {"together", "alone_a"}
    assert library.matched(_plan(semantic_query="harbour boats")) == {"empty"}


def test_an_unconstrained_plan_returns_everything_and_says_how_much(library):
    result = library.run(_plan())
    assert len(result.captures) == 4
    assert result.total_matched == 4
    assert not result.truncated


def test_a_bounded_result_reports_that_it_was_bounded(library):
    """A truncated result that does not say so reads as "that is all there is"."""
    result = library.run(_plan(limit=2))
    assert len(result.captures) == 2
    assert result.total_matched == 4
    assert result.truncated


def test_processing_state_distinguishes_what_has_been_looked_at(library):
    complete = _plan(capture=CaptureSelector(processing_states=[ProcessingState.COMPLETE]))
    unseen = _plan(capture=CaptureSelector(processing_states=[ProcessingState.CAPTURE_ONLY]))
    assert library.matched(complete) == {"together", "alone_a", "alone_b", "empty"}
    assert library.matched(unseen) == set()


def test_a_capture_that_matched_always_carries_something_to_cite(library):
    """A match with no support is an answer that cannot be given about photographs that exist.

    `is_unconstrained` is false the moment any dimension is set, so this plan took neither the
    time branch nor any per-dimension one and every capture came back with `support=()`. The
    packet built from that is empty, and an empty packet abstains with "Nothing in your library
    matches" over four photographs that did.

    The dimension is asserted as well as the presence, because labelling this a time match would
    make the Selection say a time window put the photograph there when no window was asked for.
    """
    plan = _plan(capture=CaptureSelector(processing_states=[ProcessingState.COMPLETE]))
    result = library.run(plan)
    assert result.total_matched == 4
    assert result.captures
    for capture in result.captures:
        assert capture.support, f"{capture.capture_id} matched and has nothing to cite"
        assert {support.dimension for support in capture.support} == {"capture"}


def test_an_unconstrained_plan_does_not_claim_a_time_window_put_the_photograph_there(library):
    """The Atlas's opening view, and the third route into the capture dimension.

    An empty plan is legal, means "everything", and is what the interface shows before anybody
    has asked a question, so it is the most common Selection in the product. It carries no time
    window. Labelling its support a time match told every client, through SupportView, that a
    window it never sent had selected each photograph.
    """
    result = library.run(_plan())
    assert result.total_matched == 4
    for capture in result.captures:
        assert {support.dimension for support in capture.support} == {"capture"}

    # And a plan that DID ask about time still says so, or the fix would have cost the
    # distinction it exists to keep.
    windowed = library.run(
        _plan(
            time=[
                CaptureWindow(
                    start=dt.datetime(2026, 3, 4, tzinfo=dt.UTC),
                    end=dt.datetime(2026, 3, 5, tzinfo=dt.UTC),
                )
            ]
        )
    )
    assert windowed.captures
    for capture in windowed.captures:
        assert "time" in {support.dimension for support in capture.support}


def test_a_scope_member_holding_neither_entity_is_still_citable(library):
    """The second route into the same branch, pinned so it is deliberate rather than incidental.

    M6 makes ALL a question about the scope, and the scope is returned entire: the photograph
    with nobody in it is part of the correct answer to "photographs with both A and B" under
    that reading. It has no entity support and never will.

    Before it carried the whole-photograph span it was counted in `total_matched` and absent
    from the packet, which made `EvidencePacket.truncated` true and told the composer that more
    captures matched than were shown. Nothing had been truncated. A scope member that cannot be
    cited is a scope member the answer cannot mention, while still being counted in the total.
    """
    plan = _plan(
        entities=EntitySelector(
            ids=[library.entities["A"], library.entities["B"]], mode=EntityMode.ALL
        )
    )
    result = library.run(plan)
    assert library.matched(plan) == {"together", "alone_a", "alone_b", "empty"}
    empty = [c for c in result.captures if c.capture_id == library.captures["empty"]]
    assert len(empty) == 1
    assert {s.dimension for s in empty[0].support} == {"capture"}, (
        "the photograph with nobody in it is in the scope and has no entity support"
    )
    assert all(capture.support for capture in result.captures)


# -- the entities intent -----------------------------------------------------------------


def test_the_entities_intent_answers_who_is_here(library):
    result = library.run(
        SelectionPlan(
            intent=Intent.ENTITIES,
            place=PlaceSelector(ids=[library.entities["Gullfoss"]]),
        )
    )
    found = {entity.display_name: entity.capture_count for entity in result.entities}
    assert found["A"] == 2
    assert "B" in found and found["B"] == 1
    assert found["Gullfoss"] == 2


# -- validation --------------------------------------------------------------------------


def test_an_id_from_another_workspace_is_indistinguishable_from_one_that_does_not_exist(library):
    """5.2 stage 2: the same code for both, "so the surface is not an existence oracle"."""
    codes = set()
    for unknown in (uuid.uuid4(), uuid.uuid4()):
        with pytest.raises(SelectionRejected) as rejected:
            library.run(_plan(entities=EntitySelector(ids=[unknown], mode=EntityMode.ANY)))
        codes.add(rejected.value.code)
        assert str(unknown) not in rejected.value.detail, (
            "a rejection that echoed the id would let a caller binary-search the workspace"
        )
    assert codes == {RejectionCode.UNKNOWN_REFERENCE}


def test_a_plan_cannot_widen_what_the_session_may_see(library):
    """Stage 3: authority comes from the session and the plan may only narrow it."""
    restricted = Session(
        workspace_id=library.repository.workspace_id,
        actor=library.actor,
        may_include_proposals=False,
    )
    plan = _plan(epistemic=EpistemicScope.INCLUDE_PROPOSALS)
    with pytest.raises(SelectionRejected) as rejected:
        validate(library.repository.connection, plan, restricted)
    assert rejected.value.code is RejectionCode.NOT_AUTHORISED


@pytest.mark.parametrize(
    "payload",
    [
        {"intent": "captures", "table": "assertion"},
        {"intent": "drop_everything"},
        {"intent": "captures", "limit": 10_000},
        {"intent": "captures", "entities": {"ids": [], "mode": "any"}},
        {
            "intent": "captures",
            "time": [{"start": "2026-03-04T00:00:00Z", "end": "2026-03-03T00:00:00Z"}],
        },
        {
            "intent": "captures",
            "time": [{"start": "2026-03-04T00:00:00", "end": "2026-03-05T00:00:00"}],
        },
    ],
    ids=[
        "unknown-field",
        "unknown-intent",
        "over-limit",
        "empty-ids",
        "backwards-window",
        "naive-window",
    ],
)
def test_a_plan_that_is_not_a_plan_is_refused(payload):
    """Stage 1. Every one of these is a shape the form does not have."""
    with pytest.raises(SelectionRejected) as rejected:
        parse(payload)
    assert rejected.value.code is RejectionCode.MALFORMED_PLAN


def test_the_plan_has_no_field_that_could_name_a_table_or_a_workspace():
    """Structural, and the reason model-generated SQL was rejected as a design.

    "A fixed compiler turns the plan into parameterized SQL with zero string interpolation of
    model output." The claim rests on the form having no expressive surface, so the absence of
    these fields is checked rather than assumed.
    """
    schema = SelectionPlan.model_json_schema()

    def field_names(node: object) -> set[str]:
        found: set[str] = set()
        if isinstance(node, dict):
            found |= set(node.get("properties", {}))
            for key, value in node.items():
                if key != "description":
                    found |= field_names(value)
        elif isinstance(node, list):
            for value in node:
                found |= field_names(value)
        return found

    names = field_names(schema)
    assert names, "the schema has no fields at all, so this test would pass vacuously"
    forbidden_names = ("workspace", "table", "column", "sql", "order_by", "offset", "raw", "where")
    for forbidden in forbidden_names:
        assert not any(forbidden in name for name in names), (forbidden, sorted(names))
    # Every object in the plan refuses unknown fields, so there is nowhere to smuggle one.
    assert schema["additionalProperties"] is False
    for definition in schema.get("$defs", {}).values():
        if definition.get("type") == "object":
            assert definition["additionalProperties"] is False, definition.get("title")


@pytest.mark.parametrize(
    "attack",
    [
        "gullfoss'; drop table capture; --",
        "waterfall & secret | admin",
        "') or 1=1 --",
        "\\x00 waterfall",
    ],
)
def test_the_free_text_field_cannot_express_an_operator(library, attack):
    """The one free-text field, and why it goes to ``plainto_tsquery`` rather than to_tsquery.

    ``plainto_tsquery`` discards operator syntax and ANDs the remaining words, so an injected
    boolean is a set of literal terms that match nothing rather than a query the caller authored.
    Every one of these returns a result and none of them returns everything.
    """
    result = library.run(_plan(semantic_query=attack))
    assert result.total_matched < 4


def test_selecting_is_read_only(library):
    """Stage 6. The executor may not write, whatever a plan upstream of it wanted."""
    before = library.repository.rows_in_schema("capture")
    library.run(_plan())
    assert library.repository.rows_in_schema("capture") == before
    # And the transaction the executor opened has been closed, so the connection is usable.
    assert library.repository.rows_in_schema("assertion") > 0
