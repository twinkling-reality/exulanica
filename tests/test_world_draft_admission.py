"""World-operation price copies and native kind start-window sampling preserve authority."""

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from exulanica.api.kind_drafts import KindDraft, KindDrafts
from exulanica.models.errors import ProviderRefused
from exulanica.models.manifest import Role
from exulanica.models.provider_catalog import ProviderPrice


def test_kind_start_sample_counts_actor_across_workspaces_and_erased_timing_only_in_window():
    actor = uuid.uuid4()
    holder = KindDrafts(clock=lambda: 10000)
    for started, purpose, erased in (
        (9990, "kind", False),
        (9990, "kind", True),
        (6340, "kind", False),
        (9990, "world", False),
    ):
        draft = KindDraft(
            uuid.uuid4(),
            uuid.uuid4(),
            actor,
            "",
            dt.datetime.now(dt.UTC),
            started,
            state="ready",
            changed=6700,
            purpose=purpose,
            erased=erased,
        )
        holder._drafts[draft.draft_id] = draft
    other = KindDraft(
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
        "",
        dt.datetime.now(dt.UTC),
        9990,
        state="ready",
        changed=9990,
    )
    holder._drafts[other.draft_id] = other
    with holder.kind_start_count(actor) as count:
        assert count == 2
        assert not holder._lock.acquire(blocking=False)
    assert holder._lock.acquire(blocking=False)
    holder._lock.release()


def test_price_copy_cannot_widen_context_or_change_roles_and_wire_limit_refuses_before_transport(
    client,
    manifest,
    transport,
):
    role = Role.REASONING_CHEAP
    spec = manifest[role].primary
    clone = client.with_prices(
        {
            (spec.provider, spec.model_id): ProviderPrice(
                spec.model_id,
                Decimal("2.5"),
                Decimal("3"),
                spec.context_window_tokens * 2,
                "a" * 64,
            )
        },
        limits={role: (1, manifest[role].default_max_tokens)},
    )
    assert clone.manifest[role].primary.context_window_tokens == spec.context_window_tokens
    assert clone.manifest[role].primary.input_usd_per_mtok == Decimal("2.5")
    assert manifest[role].primary.input_usd_per_mtok != Decimal("2.5")
    assert clone.maximum_wire_attempts(role) == client.maximum_wire_attempts(role)
    assert [m.model_id for m in clone.manifest[role].chain] == [
        m.model_id for m in manifest[role].chain
    ]
    with pytest.raises(ProviderRefused) as failure:
        clone.chat(
            role,
            [{"role": "user", "content": "Too many bytes"}],
            prompt_version="private-price-check",
            use_cache=False,
        )
    assert failure.value.reason == "world_draft_request_limit_exceeded"
    assert transport.requests == []
