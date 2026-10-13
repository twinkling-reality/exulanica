"""New recording boundaries reject provider prose without changing historical records."""

import dataclasses
import json
from datetime import UTC

import pytest
from exulanica.api.kind_drafts import KindDraft
from exulanica.api.world_draft_worker import snapshot
from exulanica.models.errors import ModelError
from exulanica.models.identity import reported_model_identity
from exulanica.models.manifest import load_manifest
from exulanica.models.transport import HttpResponse
from exulanica.selection.calls import admitted_model_call, noted_calls
from exulanica.world.role_decisions import replay_minutes, validate_role_receipt

import test_creature_drafting as creature
import test_kind_drafting as kind
import test_society_model_follow as follow
import test_world_drafting as world
from model_fakes import chat_body

ECHO = "PRIVATE_WORDS_SENTINEL a creature with six legs and a striped tail"


def reply(form, reported):
    body = chat_body(json.dumps(form))
    if reported is None:
        body.pop("model", None)
    else:
        body["model"] = reported
    return HttpResponse(200, json.dumps(body))


@pytest.mark.parametrize("reported", [None, "", ECHO, {"echo": ECHO}, False])
@pytest.mark.parametrize("workflow", ["creature", "kind"])
def test_immutable_provenance_refuses_before_assembly_with_one_accounted_call(
    reported, workflow, monkeypatch
):
    if workflow == "creature":
        client, transport = creature._client(
            reply(creature.form_of("horse", label="hill beast"), reported)
        )
        monkeypatch.setattr(
            "exulanica.selection.creature_drafting.assemble_creature",
            lambda *a, **k: pytest.fail("assembled with unavailable model"),
        )

        def run():
            return creature.draft_creature(client, ECHO, role=creature.ROLE)
    else:
        client, transport = kind._client(reply(kind._farm(), reported))

        def run():
            return kind.draft_kind(
                client,
                ECHO,
                role=kind.ROLE,
                check=lambda *a, **k: pytest.fail("checked immutable kind with unavailable model"),
            )

    with pytest.raises(ModelError) as caught:
        run()
    records = noted_calls(caught.value)
    assert records is not None and len(records.calls) == 1
    assert transport.call_count == 1
    call = records.calls[0]
    assert call.served_model is None
    assert call.served_model_unavailable == (
        "response_names_no_model" if reported in (None, "") else "reported_model_not_admitted"
    )
    assert (
        call.attempts == 1 and call.prompt_tokens is not None and call.completion_tokens is not None
    )
    assert ECHO not in str(caught.value) and ECHO not in json.dumps(
        dataclasses.asdict(call), default=str
    )


@pytest.mark.parametrize("reported", [None, ECHO, {"echo": ECHO}])
def test_bounded_world_specification_keeps_answer_with_unavailable_identity(reported):
    client, transport, _ = world._client(
        reply(world._form(preset="market_town", storey_band_high=5, fit="all"), reported)
    )
    outcome = world.draft_world_specification(client, ECHO, world.VIEW)
    assert outcome.draft is not None and outcome.refusal is None and outcome.model_id is None
    assert transport.call_count == 1 and outcome.calls[0].served_model is None
    assert outcome.calls[0].served_model_unavailable is not None
    assert ECHO not in json.dumps([dataclasses.asdict(c) for c in outcome.calls], default=str)


def test_identity_is_provider_scoped_and_preserves_explicit_dynamic_selection():
    manifest = load_manifest()
    spec = manifest[creature.ROLE].primary
    foreign = dataclasses.replace(spec, model_id="verified/other", provider="another-provider")
    extended = dataclasses.replace(manifest, models={**manifest.models, foreign.model_id: foreign})
    assert (
        reported_model_identity(spec.model_id, provider=spec.provider, manifest=manifest).model_id
        == spec.model_id
    )
    assert (
        reported_model_identity(
            foreign.model_id, provider=spec.provider, manifest=extended
        ).model_id
        is None
    )
    dynamic = dataclasses.replace(spec, model_id="verified/dynamic")
    assert (
        reported_model_identity(
            dynamic.model_id, provider=spec.provider, manifest=manifest
        ).model_id
        is None
    )
    assert (
        reported_model_identity(
            dynamic.model_id, provider=spec.provider, manifest=manifest, admitted_specs=(dynamic,)
        ).model_id
        == dynamic.model_id
    )


def test_decision_echo_is_withheld_and_cold_replay_uses_the_recorded_receipts(monkeypatch):
    original = follow.PursuitTransport

    class EchoTransport(original):
        def post_json(self, *a, **k):
            response = super().post_json(*a, **k)
            body = json.loads(response.text)
            body["model"] = ECHO
            return HttpResponse(response.status_code, json.dumps(body), response.headers)

    monkeypatch.setattr(follow, "PursuitTransport", EchoTransport)
    _, _, _, role, _, transport, played, play = follow.run_scenario()
    for request, receipt in zip(played.requests, played.receipts, strict=True):
        validate_role_receipt(role, receipt, request)
        if receipt["provider"]:
            assert receipt["provider"]["served_model_id"] is None
            assert all(
                c["served_model"] is None
                and c["served_model_unavailable"] == "reported_model_not_admitted"
                for c in receipt["provider"]["calls"]
            )
            assert ECHO not in json.dumps(receipt)
    assert any(r["status"] == "accepted" for r in played.receipts)
    count = transport.call_count
    # Existing independent replay helper is used by the ordinary model-follow fixture itself.
    replayed = replay_minutes(
        list(zip(played.requests, played.receipts, strict=True)),
        minute_digests=played.minute_digests,
        play=play,
    )
    assert (
        replayed.states == played.states
        and replayed.events == played.events
        and transport.call_count == count
    )


def test_worker_snapshot_and_native_fence_keep_accounting_without_echo():
    import uuid
    from datetime import datetime

    from exulanica.api.kind_draft_worker import safe_calls

    client, _, _ = world._client(
        reply(world._form(preset="market_town", storey_band_high=5, fit="all"), ECHO)
    )
    outcome = world.draft_world_specification(client, ECHO, world.VIEW)
    safe = outcome.calls[0]
    unsafe = dataclasses.replace(safe, served_model=ECHO, served_model_unavailable=None)
    cleaned = admitted_model_call(unsafe, client.manifest)
    assert cleaned == safe
    draft = KindDraft(
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
        "",
        datetime.now(UTC),
        0,
        state="ready",
        calls=(unsafe,),
        model_id=ECHO,
    )
    recorded = snapshot(draft, manifest=client.manifest)
    assert recorded["model_id"] is None
    assert recorded["calls"] == safe_calls((unsafe,), client)
    assert ECHO not in json.dumps(recorded, default=str)
    # Sanitizing a new snapshot must not mutate a historical/input record.
    assert draft.calls[0].served_model == ECHO and draft.model_id == ECHO
