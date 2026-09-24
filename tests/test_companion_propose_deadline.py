"""The page waits for a proposal at least as long as the server may take to draw one.

``appearance_bound_seconds`` in ``exulanica/selection/proposal.py`` is the server's bound on one
appearance request's model calls: each call site, as ``APPEARANCE_PATH_CALLS`` states it, times
what the client says one call to its role can take at worst. The page's deadline,
``PROPOSE_TIMEOUT_MS`` in ``web/packages/app/src/companion-ask-api.ts``, must be at least that
bound plus the page's allowance for an ordinary read, ``PACKET_TIMEOUT_MS``, as ``ASK_TIMEOUT_MS``
is held to the answer's bound. Measured by reading, before this existed: the page gave up at 90 s
on a path whose classifier and two drafts may take 150 s.

The other half is that ``APPEARANCE_PATH_CALLS`` is true: each call site is driven to its worst
case here, through the real functions over a scripted transport.
"""

from __future__ import annotations

import uuid

import pytest
from exulanica.models.errors import StructuredOutputError
from exulanica.models.manifest import Role
from exulanica.selection.proposal import (
    APPEARANCE_PATH_CALLS,
    SourceChoice,
    _proposable_profiles,
    appearance_bound_seconds,
    classify_request,
    draft_appearance,
)
from exulanica.world import STYLE_REGISTRY, StyleReference

from model_fakes import chat_body
from test_companion_ask_deadline import _api_client, _milliseconds, _reply, _roles_sent


def test_the_page_waits_at_least_the_appearance_bound_and_its_read_allowance():
    client, _ = _api_client()
    bound_ms = appearance_bound_seconds(client) * 1000
    assert bound_ms > 0
    assert _milliseconds("PROPOSE_TIMEOUT_MS") >= bound_ms + _milliseconds("PACKET_TIMEOUT_MS")


def test_the_classifier_and_the_drafter_send_their_role_as_many_times_as_stated():
    unreadable = _reply(chat_body("this is not a form"))
    client, transport = _api_client([unreadable] * 5)
    classify_request(client, "make it warmer")
    profile = _proposable_profiles(STYLE_REGISTRY)[0]
    current = STYLE_REGISTRY.validate_reference(
        StyleReference(profile.profile_id, profile.profile_version, {})
    )
    catalogue = (SourceChoice(uuid.uuid4(), uuid.uuid4(), None, "reference:x"),)
    with pytest.raises(StructuredOutputError):  # refused after its repair
        draft_appearance(client, "make it warmer", current, catalogue)
    assert _roles_sent(transport) == [
        role for role, count in APPEARANCE_PATH_CALLS for _ in range(count)
    ]


def test_every_role_the_appearance_path_sends_is_counted_once():
    roles = [role for role, _ in APPEARANCE_PATH_CALLS]
    assert len(roles) == len(set(roles))
    assert set(roles) == {Role.STRUCTURED_EXTRACTION}
