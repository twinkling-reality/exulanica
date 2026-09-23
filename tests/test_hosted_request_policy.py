"""The boundary's mechanism: the client's admission point, and the workspace's policy.

``tests/test_hosted_boundary.py`` shows that no saved name leaves on any path the product has.
This file holds the parts that make that true to their contracts: a client with no policy sends
nothing and says why, policies only accumulate, what is cached is what left, a system message is
sent as written, a place right releases a place's name to exactly the hand-over it names, and a
photograph goes only as a declared photograph under its right.
"""

from __future__ import annotations

import json
import uuid

import pytest
from exulanica.epistemics.hosted_requests import (
    WorkspaceRequestPolicy,
    borrowing,
    no_place_released,
)
from exulanica.epistemics.saved_names import SavedName, redact_names
from exulanica.errors import PrivacyAdmissionError
from exulanica.models.cache import InMemoryResponseCache
from exulanica.models.client import ModelClient
from exulanica.models.errors import ModelError
from exulanica.models.handoff import ModelHandoff
from exulanica.models.manifest import Role, load_manifest
from exulanica.models.messages import image_part
from exulanica.models.policy import (
    BenchmarkInputs,
    HostedRequest,
    HostedRequestRefused,
    NoHostedRequestPolicy,
)
from exulanica.models.transport import HttpResponse
from pydantic import BaseModel

from model_fakes import FakeTransport, RecordingPolicy, chat_body
from test_companion_saved_names import PERSON, _leaks, named
from test_companion_saved_names import PLACE as PLACE_NAME

__all__ = ["named"]

SYSTEM = "You read one sentence and answer with one word."


class _Word(BaseModel):
    word: str


def _client(*, policy=None, cache=None, responses=()) -> tuple[ModelClient, FakeTransport]:
    transport = FakeTransport(list(responses))
    transport.default = HttpResponse(status_code=200, text=json.dumps(chat_body('{"word": "x"}')))
    return (
        ModelClient(
            api_key="test-key-not-real",
            transport=transport,
            cache=cache,
            policy=policy,
        ),
        transport,
    )


def _messages(text: str) -> list[dict]:
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}]


def _vector() -> HttpResponse:
    return HttpResponse(
        status_code=200,
        text=json.dumps({"data": [{"embedding": [1.0] + [0.0] * 4095}], "usage": {}}),
    )


class _Replacing:
    """A policy that replaces one word, and keeps what it was shown."""

    def __init__(self, word: str, by: str) -> None:
        self.word, self.by = word, by
        self.seen: list[HostedRequest] = []

    def admit(self, request: HostedRequest) -> tuple[str, ...]:
        self.seen.append(request)
        return tuple(text.replace(self.word, self.by) for text in request.texts)


# -- the client ------------------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["chat", "structured", "vision", "embed"])
def test_a_client_with_no_policy_sends_nothing_and_says_why(method):
    client, transport = _client()
    calls = {
        "chat": lambda: client.chat(Role.STRUCTURED_EXTRACTION, _messages("x"), prompt_version="v"),
        "structured": lambda: client.structured(
            Role.STRUCTURED_EXTRACTION, _messages("x"), _Word, prompt_version="v"
        ),
        "vision": lambda: client.vision([b"\x89PNG"], "describe", prompt_version="v"),
        "embed": lambda: client.embed(["x"]),
    }
    with pytest.raises(NoHostedRequestPolicy, match="no hosted-request policy"):
        calls[method]()
    assert transport.requests == []


def test_a_missing_policy_is_not_a_model_failure_a_caller_could_quietly_absorb():
    assert not issubclass(NoHostedRequestPolicy, ModelError)


def test_policies_only_accumulate_and_each_sees_what_the_one_before_left():
    first = _Replacing("Maria", "[person A]")
    second = RecordingPolicy()
    base, transport = _client(policy=first)
    bound = base.with_policy(second)

    bound.chat(Role.STRUCTURED_EXTRACTION, _messages("Where is Maria?"), prompt_version="v")

    assert second.requests[0].texts == ("Where is [person A]?",)
    assert transport.requests[-1]["payload"]["messages"][1]["content"] == "Where is [person A]?"
    # The client it was attached to is unchanged: it still sends under the first policy alone.
    base.chat(Role.STRUCTURED_EXTRACTION, _messages("Maria again"), prompt_version="v")
    assert len(second.requests) == 1 and len(first.seen) == 2


def test_what_is_cached_is_what_left():
    """The cache key is computed after the policies, so it never holds a caller's own text."""
    policy = _Replacing("Maria", "[person A]")
    client, transport = _client(policy=policy, cache=InMemoryResponseCache())
    client.chat(Role.STRUCTURED_EXTRACTION, _messages("Where is Maria?"), prompt_version="v")
    hit = client.chat(
        Role.STRUCTURED_EXTRACTION, _messages("Where is [person A]?"), prompt_version="v"
    )
    assert hit.cache_hit and transport.call_count == 1


def test_the_callers_messages_are_not_rewritten():
    """A caller repairs by appending to the list it sent, so that list keeps what it wrote."""
    client, transport = _client(policy=_Replacing("Maria", "[person A]"))
    messages = _messages("Where is Maria?")
    client.chat(Role.STRUCTURED_EXTRACTION, messages, prompt_version="v")
    assert messages[1]["content"] == "Where is Maria?"
    assert transport.requests[0]["payload"]["messages"][1]["content"] == "Where is [person A]?"


def test_a_system_message_is_shown_to_the_policy_and_sent_as_written():
    policy = _Replacing("one", "[person A]")
    client, transport = _client(policy=policy)
    client.chat(Role.STRUCTURED_EXTRACTION, _messages("one more"), prompt_version="v")
    (request,) = policy.seen
    assert request.instructions == (SYSTEM,) and request.texts == ("one more",)
    sent = transport.requests[0]["payload"]["messages"]
    assert sent[0]["content"] == SYSTEM and sent[1]["content"] == "[person A] more"


def test_a_policy_that_loses_a_text_sends_nothing():
    class Dropping:
        def admit(self, request):
            return ()

    client, transport = _client(policy=Dropping())
    with pytest.raises(HostedRequestRefused, match="0 texts for a request carrying 1"):
        client.chat(Role.STRUCTURED_EXTRACTION, _messages("x"), prompt_version="v")
    assert transport.requests == []


def test_a_part_that_is_neither_text_nor_an_image_is_refused():
    client, transport = _client(policy=RecordingPolicy())
    messages = [{"role": "user", "content": [{"type": "input_audio", "input_audio": {}}]}]
    with pytest.raises(HostedRequestRefused, match="neither text nor an image"):
        client.chat(Role.STRUCTURED_EXTRACTION, messages, prompt_version="v")
    assert transport.requests == []


def test_text_outside_messages_and_inputs_is_refused():
    """A caller's extra parameter is not shown to a policy, so it may carry numbers, not text."""
    client, transport = _client(policy=RecordingPolicy())
    with pytest.raises(HostedRequestRefused, match="'stop' carries text"):
        client.chat(
            Role.STRUCTURED_EXTRACTION,
            _messages("x"),
            prompt_version="v",
            extra={"stop": ["Maria"]},
        )
    assert transport.requests == []
    named_message = [{"role": "user", "name": "Maria", "content": "x"}]
    with pytest.raises(HostedRequestRefused, match="'name' carries text"):
        client.chat(Role.STRUCTURED_EXTRACTION, named_message, prompt_version="v")
    assert transport.requests == []
    client.chat(Role.STRUCTURED_EXTRACTION, _messages("x"), prompt_version="v", extra={"seed": 7})
    assert transport.requests[0]["payload"]["seed"] == 7


def test_a_request_declares_its_photographs_by_capture_id():
    client, _ = _client(policy=RecordingPolicy())
    with pytest.raises(TypeError, match="capture id"):
        client.embed(["x"], photographs=["not-an-id"])


def test_benchmark_inputs_sends_text_as_written_and_no_photograph_or_image():
    client, transport = _client(
        policy=BenchmarkInputs("invented catalogue questions"), responses=[_vector()]
    )
    client.embed(["Maria at the harbour"])
    assert transport.requests[0]["payload"]["input"] == ["Maria at the harbour"]
    with pytest.raises(HostedRequestRefused, match="no photograph and no image"):
        client.embed(["x"], photographs=[uuid.uuid4()])
    with pytest.raises(HostedRequestRefused, match="no photograph and no image"):
        client.vision([b"\x89PNG"], "describe", prompt_version="v")
    assert len(transport.requests) == 1
    with pytest.raises(ValueError, match="which inputs"):
        BenchmarkInputs(" ")


# -- the workspace's policy ------------------------------------------------------------------------


def _policy(repository, *, released=no_place_released, right=None, photographs=()):
    def allowed(connection, workspace_id, captures, handoff):
        return None

    return WorkspaceRequestPolicy(
        repository.workspace_id,
        connection=borrowing(repository.connection),
        photograph_right=right or allowed,
        released_places=released,
        photographs=photographs,
    )


def test_a_released_place_name_goes_to_exactly_the_hand_over_it_names(named):
    repository, _, _, entities = named
    manifest = load_manifest()
    embedding = ModelHandoff.hosted(manifest, Role.EMBEDDING)
    asked: list[ModelHandoff] = []

    def released(connection, workspace_id, handoff):
        asked.append(handoff)
        return frozenset({entities["place"]}) if handoff == embedding else frozenset()

    client, transport = _client(
        policy=_policy(repository, released=released), responses=[_vector(), _vector()]
    )
    text = f"{PERSON} runs past {PLACE_NAME}"
    client.embed([text])
    client.embed([text])
    client.chat(Role.STRUCTURED_EXTRACTION, _messages(text), prompt_version="v")
    client.chat(Role.STRUCTURED_EXTRACTION, _messages("nothing named here"), prompt_version="v")

    embedded, again, drafted, unnamed = transport.requests
    assert embedded["payload"]["input"] == [f"[person A] runs past {PLACE_NAME}"]
    assert again["payload"]["input"] == embedded["payload"]["input"]
    assert drafted["payload"]["messages"][1]["content"] == "[person A] runs past [place A]"
    assert not _leaks(json.dumps(drafted["payload"]))
    # Asked once for each hand-over, and not at all for a request that carries no place's name.
    extraction = ModelHandoff.hosted(manifest, Role.STRUCTURED_EXTRACTION)
    assert asked == [embedding, extraction]
    assert unnamed["payload"]["messages"][1]["content"] == "nothing named here"


def test_a_person_is_never_released_even_by_a_resolver_that_names_them(named):
    repository, _, _, entities = named

    def everyone(connection, workspace_id, handoff):
        return frozenset(entities.values())

    client, transport = _client(
        policy=_policy(repository, released=everyone), responses=[_vector()]
    )
    client.embed([f"{PERSON} runs past {PLACE_NAME}"])
    # The place the resolver released went as written, which shows the resolver was applied.
    assert transport.requests[0]["payload"]["input"] == [f"[person A] runs past {PLACE_NAME}"]


def test_a_photograph_goes_only_under_its_right_and_an_image_only_as_a_photograph(named):
    repository, _, _, _ = named
    capture = uuid.uuid4()

    def refuse(connection, workspace_id, captures, handoff):
        assert captures == {capture}
        raise PrivacyAdmissionError("no personal model right names this model")

    client, transport = _client(policy=_policy(repository, right=refuse), responses=[_vector()])
    with pytest.raises(HostedRequestRefused, match="no personal model right"):
        client.embed(["a caption"], photographs=[capture])
    with pytest.raises(HostedRequestRefused, match="names no photograph"):
        client.chat(
            Role.VISION,
            [{"role": "user", "content": [image_part(b"\x89PNG")]}],
            prompt_version="v",
        )
    assert transport.requests == []
    # Positive control: the same client sends a request that carries no photograph.
    client.embed(["a sentence somebody typed"])
    assert len(transport.requests) == 1


def test_a_policy_scoped_to_a_photograph_treats_every_request_as_carrying_it(named):
    repository, _, _, _ = named
    capture = uuid.uuid4()
    checked: list[frozenset[uuid.UUID]] = []

    def right(connection, workspace_id, captures, handoff):
        checked.append(captures)

    client, transport = _client(policy=_policy(repository, right=right, photographs=[capture]))
    client.chat(
        Role.VISION,
        [{"role": "user", "content": [image_part(b"\x89PNG"), {"type": "text", "text": "go"}]}],
        prompt_version="v",
    )
    assert checked == [frozenset({capture})] and len(transport.requests) == 1


def test_a_label_the_request_already_carries_is_never_handed_to_another_entity(named):
    """A call site labelled somebody; the boundary replaces a name it left without reusing it."""
    repository, _, _, _ = named
    client, transport = _client(policy=_policy(repository))
    messages = [
        {"role": "user", "content": "Is [person A] the runner?"},
        {"role": "user", "content": f"The sign says {PERSON}."},
    ]
    client.chat(Role.STRUCTURED_EXTRACTION, messages, prompt_version="v")
    first, second = transport.requests[0]["payload"]["messages"]
    assert first["content"] == "Is [person A] the runner?"
    assert second["content"] == "The sign says [person B]."


def test_a_label_an_instruction_uses_is_never_handed_to_an_entity(named):
    """A prompt that shows the placeholder form by example keeps its example unambiguous."""
    repository, _, _, _ = named
    client, transport = _client(policy=_policy(repository))
    messages = [
        {"role": "system", "content": "Refer to people by their placeholder, as in [person A]."},
        {"role": "user", "content": f"Where did {PERSON} run?"},
    ]
    client.chat(Role.STRUCTURED_EXTRACTION, messages, prompt_version="v")
    sent = transport.requests[0]["payload"]["messages"]
    assert sent[1]["content"] == "Where did [person B] run?"


def test_a_saved_name_is_recognised_inside_a_json_document():
    """A request can carry a JSON document as text, where a quotation mark is written escaped."""
    door = SavedName(uuid.uuid4(), "place", 'The "Blue" Door')
    document = json.dumps({"note": 'meet at The "Blue" Door'}, ensure_ascii=False)
    redacted = redact_names(document, [door])
    assert "Blue" not in redacted.text
    assert json.loads(redacted.text) == {"note": "meet at [place A]"}
