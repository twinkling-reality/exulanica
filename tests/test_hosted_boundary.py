"""Every hosted request the product sends passes one boundary, and no saved name crosses it.

:data:`HOSTED_CALL_PATHS` names every function in the product package that sends a request to a
hosted model. It is held to the code in both directions: the package's syntax trees are walked
for calls to the client's sending methods (themselves read from the client's own source), and a
call site the table does not name fails, as does an entry that no longer sends anything. A new
path is therefore registered or failing, never silently absent, and every registered path has a
scripted run here or the suite fails.

Each run goes through the code the product runs, over a workspace where a person and a place are
saved through ``name_occurrence`` and both are written on a photograph's sign. The client is the
process's client with no policy, and the product attaches the workspace's: the API through
``Services.hosted_model``, the caption pass for its capture, the vision stage for its photograph,
the society runtime for its decision. A witness transport records every request and the
registered call site whose frame sent it, and the workspace policy's admissions are recorded
beside it. Three things are asserted of every run:

1. No saved name, and no part of a person's saved name, is in any request body, its system
   messages included.
2. Every request the transport saw was admitted by the workspace's policy, text for text.
3. The run reached the call site it is registered for. A run that reached nothing would assert
   nothing about it.

The paths whose call site replaces saved names itself run a second time with that replacement
disabled, so what they show is the boundary alone: a call site that replaces nothing is covered.
"""

from __future__ import annotations

import ast
import dataclasses
import json
import sys
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from exulanica.api.authorisation import TokenDirectory
from exulanica.api.composer_rights import composer_rights_check
from exulanica.api.routes.selection import society_answer_model
from exulanica.api.services import Services
from exulanica.db.migrate import provision_workspace
from exulanica.db.session import Database
from exulanica.epistemics.caption_embeddings import CaptionEmbeddingPass
from exulanica.epistemics.hosted_requests import WorkspaceRequestPolicy, no_place_released
from exulanica.epistemics.saved_names import Redacted, saved_names
from exulanica.errors import PrivacyAdmissionError
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.vision import NebiusVisionModel
from exulanica.models.client import ModelClient
from exulanica.models.manifest import Role, load_manifest
from exulanica.models.policy import HostedRequestRefused, request_parts
from exulanica.models.transport import HttpResponse
from exulanica.selection.answer import Answer, AnswerClause, ClauseType
from exulanica.selection.calls import CallLog
from exulanica.selection.environment_proposal import (
    EnvironmentOperation,
    propose_environment_operation,
)
from exulanica.selection.plan import (
    Intent,
    SelectionPlan,
    SocietyAspect,
    SocietyScope,
    SocietySelector,
)
from exulanica.selection.proposal import propose_appearance
from exulanica.selection.question import answer_question
from exulanica.selection.society_question import answer_about_society, build_scene
from exulanica.world.society_decisions import SocietyDecisionProvider

from conftest import ingest_observed, write_photo
from model_fakes import FakeTransport, chat_body
from test_companion_saved_names import (
    PERSON,
    PLACE,
    _allow,
    _bare,
    _leaks,
    _photograph,
    _reply,
    _vector_reply,
    named,
)
from test_selection_proposal import WORLD, _seed_world, current_reference, draft
from test_society_question import EVENTS, SNAPSHOT, TARGETS
from test_vision_contract import VALID as OBSERVATION

pytestmark = pytest.mark.postgres

__all__ = ["named"]

_PACKAGE = Path(__file__).resolve().parent.parent / "exulanica"
_CLIENT = _PACKAGE / "models" / "client.py"

#: Every function in the product package that sends a request to a hosted model, by module and
#: qualified name. Written from the code, and held to it by
#: ``test_every_hosted_call_in_the_product_is_a_registered_path``.
HOSTED_CALL_PATHS: Mapping[str, tuple[str, str]] = {
    "planner": ("exulanica.selection.planner", "propose_plan"),
    "composer": ("exulanica.selection.question", "compose_answer"),
    "society composer": ("exulanica.selection.society_question", "compose_society_answer"),
    "request classifier": ("exulanica.selection.proposal", "classify_request"),
    "appearance drafter": ("exulanica.selection.proposal", "draft_appearance"),
    "environment drafter": (
        "exulanica.selection.environment_proposal",
        "draft_environment_operation",
    ),
    "query embedding": ("exulanica.selection.embeddings", "embed_query"),
    "caption embedding": ("exulanica.epistemics.caption_embeddings", "embed_capture"),
    "vision": ("exulanica.ingest.vision", "NebiusVisionModel.observe"),
    "society decision": (
        "exulanica.world.society_decisions",
        "SocietyDecisionProvider.propose",
    ),
}

_PATH_AT = {site: path for path, site in HOSTED_CALL_PATHS.items()}


# -- the registry is the code's own list ---------------------------------------------------------


def _sending_methods() -> frozenset[str]:
    """The client's public methods that send, read from its source rather than typed here.

    A method sends when it calls ``self._admit``, the one point every request passes, or calls a
    method that sends.
    """
    tree = ast.parse(_CLIENT.read_text(encoding="utf-8"))
    (client,) = [
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ModelClient"
    ]
    calls: dict[str, set[str]] = {}
    for method in client.body:
        if isinstance(method, ast.FunctionDef):
            calls[method.name] = {
                node.func.attr
                for node in ast.walk(method)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "self"
            }
    sending = {name for name, called in calls.items() if "_admit" in called}
    while True:
        more = {name for name, called in calls.items() if called & sending} - sending
        if not more:
            break
        sending |= more
    return frozenset(name for name in sending if not name.startswith("_"))


class _Sends(ast.NodeVisitor):
    """Collects the qualified name of every function in one module that calls a sending method."""

    def __init__(self, module: str, sending: frozenset[str]) -> None:
        self.module = module
        self.sending = sending
        self.scope: list[str] = []
        self.found: set[tuple[str, str]] = set()

    def _enter(self, node: ast.AST, name: str) -> None:
        self.scope.append(name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._enter(node, node.name)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._enter(node, node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._enter(node, node.name)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute) and node.func.attr in self.sending:
            self.found.add((self.module, ".".join(self.scope)))
        self.generic_visit(node)


def _call_sites() -> set[tuple[str, str]]:
    """Every (module, qualified function) outside the model package that calls a sending method."""
    sending = _sending_methods()
    found: set[tuple[str, str]] = set()
    for path in sorted(_PACKAGE.rglob("*.py")):
        relative = path.relative_to(_PACKAGE.parent)
        if relative.parts[1] == "models":
            continue
        visitor = _Sends(".".join(relative.with_suffix("").parts), sending)
        visitor.visit(ast.parse(path.read_text(encoding="utf-8")))
        found |= visitor.found
    return found


def test_the_client_sends_through_exactly_the_methods_the_boundary_names():
    # Positive control for the reading: the four methods a caller sends with.
    assert _sending_methods() == {"chat", "structured", "vision", "embed"}


def test_every_hosted_call_in_the_product_is_a_registered_path():
    found = _call_sites()
    # Positive control: the walk found call sites at all, so an empty difference means something.
    assert len(found) >= len(HOSTED_CALL_PATHS) - 1, f"the walk found only {sorted(found)}"
    registered = set(HOSTED_CALL_PATHS.values())
    assert not found - registered, f"hosted calls no path names: {sorted(found - registered)}"
    assert not registered - found, f"paths that send nothing: {sorted(registered - found)}"


def test_benchmark_inputs_is_never_attached_by_the_product():
    """The one policy that replaces nothing is for inputs with no account holder data in them."""
    named_here = [
        f"{path.relative_to(_PACKAGE.parent)}:{node.lineno}"
        for path in sorted(_PACKAGE.rglob("*.py"))
        if path != _PACKAGE / "models" / "policy.py"
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if (isinstance(node, ast.Name) and node.id == "BenchmarkInputs")
        or (isinstance(node, ast.Attribute) and node.attr == "BenchmarkInputs")
        or (isinstance(node, ast.alias) and node.name == "BenchmarkInputs")
    ]
    assert not named_here, f"the product names BenchmarkInputs: {named_here}"


# -- the witness ---------------------------------------------------------------------------------


class Witness(FakeTransport):
    """Every request, and the registered path whose call site sent it (None for none)."""

    def __init__(self, responses: list[HttpResponse]) -> None:
        super().__init__(responses)
        self.paths: list[str | None] = []

    def post_json(self, url, *, headers, payload, timeout):
        self.paths.append(_sending_path())
        return super().post_json(url, headers=headers, payload=payload, timeout=timeout)


def _sending_path() -> str | None:
    frame = sys._getframe(1)
    while frame is not None:
        site = (frame.f_globals.get("__name__"), frame.f_code.co_qualname)
        if site in _PATH_AT:
            return _PATH_AT[site]
        frame = frame.f_back
    return None


def _body(payload: Mapping[str, Any]) -> str:
    """The request as text, with image bytes left out: they are pixels, not text to search."""

    def strip(node: Any) -> Any:
        if isinstance(node, Mapping):
            if node.get("type") == "image_url":
                return {"type": "image_url"}
            return {key: strip(value) for key, value in node.items()}
        if isinstance(node, list):
            return [strip(item) for item in node]
        return node

    return json.dumps(strip(payload), ensure_ascii=False)


@pytest.fixture
def admissions(monkeypatch) -> list[tuple[str, ...]]:
    """What the workspace policy returned for each request it admitted, in order."""
    seen: list[tuple[str, ...]] = []
    original = WorkspaceRequestPolicy.admit

    def admit(self, request):
        admitted = original(self, request)
        seen.append(tuple(admitted))
        return admitted

    monkeypatch.setattr(WorkspaceRequestPolicy, "admit", admit)
    return seen


@dataclass
class World:
    repository: Any
    store: Any
    session: Any
    entities: Mapping[str, uuid.UUID]
    capture: uuid.UUID
    tmp_path: Path
    photo_dir: Path
    services: Services

    @property
    def connection(self):
        return self.repository.connection

    def hosted(self, responses: list[HttpResponse]) -> tuple[ModelClient, Witness]:
        """The client a route sends through, built by ``Services.hosted_model``."""
        transport = Witness(responses)
        services = dataclasses.replace(self.services, model_client=_process_client(transport))
        client = services.hosted_model(self.connection, self.repository.workspace_id)
        assert client is not None
        return client, transport

    def embed_caption(self) -> None:
        """Store the photograph's caption vector, so a question's query is embedded as well."""
        client, _ = _bare([_vector_reply()])
        embedded = CaptionEmbeddingPass(client)(
            self.connection, self.repository.workspace_id, self.capture, before_send=_allow
        )
        assert embedded is not None, "no caption vector exists, so no query would be embedded"


def _process_client(transport: FakeTransport) -> ModelClient:
    """The process's client: no policy, as ``build_services`` builds it."""
    return ModelClient(api_key="test-key-not-real", transport=transport)


@pytest.fixture
def world(named, tmp_path, photo_dir) -> World:
    repository, store, session, entities = named
    provision_workspace(repository.connection, repository.workspace_id)
    services = Services(
        database=Database(url="postgresql://never-opened.invalid/exulanica"),
        readonly_database=Database(url="postgresql://never-opened.invalid/exulanica"),
        store=store,
        tokens=TokenDirectory(sessions={}),
        executor_shares_the_write_role=False,
        model_client=None,
    )
    return World(
        repository, store, session, entities, _photograph(repository), tmp_path, photo_dir, services
    )


# -- one scripted run per path --------------------------------------------------------------------


def _answer_reply() -> HttpResponse:
    answer = Answer(
        clauses=[AnswerClause(text="I have no evidence for that.", type=ClauseType.META)]
    )
    return _reply(answer.model_dump_json())


def _json_reply(value: Any, role: Role) -> HttpResponse:
    model = load_manifest()[role].primary.model_id
    return HttpResponse(status_code=200, text=json.dumps(chat_body(json.dumps(value), model=model)))


def run_ask(world: World) -> Witness:
    """``POST /selection/ask`` with a question naming both: planner, query embedding, composer."""
    world.embed_caption()
    plan = SelectionPlan(intent=Intent.CAPTURES, semantic_query="running club")
    client, transport = world.hosted(
        [_reply(plan.model_dump_json()), _vector_reply(), _answer_reply()]
    )
    answer_question(
        world.connection,
        client,
        f"Is {PERSON} wearing the running club shirt outside {PLACE}?",
        world.session,
        world_id=None,
        store=world.store,
        before_compose=composer_rights_check(world.connection, world.repository.workspace_id),
    )
    return transport


def run_supplied_plan(world: World) -> Witness:
    """``POST /selection/ask`` with a plan the caller supplies, its query naming both."""
    world.embed_caption()
    plan = SelectionPlan(intent=Intent.CAPTURES, semantic_query=f"{PERSON} running club {PLACE}")
    client, transport = world.hosted([_vector_reply(), _answer_reply()])
    answer_question(
        world.connection,
        client,
        "Where does the running club meet?",
        world.session,
        world_id=None,
        plan=plan,
        store=world.store,
        before_compose=composer_rights_check(world.connection, world.repository.workspace_id),
    )
    return transport


def run_society_question(world: World, *, client_for=None) -> Witness:
    """What happened among a world's people, asked in a question naming both saved names, through
    the client the route builds for it (``society_answer_model``), or ``client_for``'s."""
    saved = saved_names(world.connection, world.repository.workspace_id)
    transport = Witness([_answer_reply()])
    services = dataclasses.replace(world.services, model_client=_process_client(transport))
    client = (client_for or society_answer_model)(
        services, world.connection, world.repository.workspace_id
    )
    assert client is not None
    scene = build_scene(
        SNAPSHOT,
        targets=TARGETS,
        events=EVENTS,
        selected=None,
        question=f"What happened while {PERSON} waited outside {PLACE}?",
        saved=saved,
    )
    answer_about_society(
        scene,
        SocietySelector(scope=SocietyScope.WORLD, aspect=SocietyAspect.RECENT),
        client=client,
        saved=saved,
        log=CallLog(),
        max_tokens=4096,
        attempts=1,
    )
    return transport


def run_appearance(world: World) -> Witness:
    """``POST /selection/appearance`` with an utterance naming both: classifier, then drafter."""
    _seed_world(world.repository, world.tmp_path, world.photo_dir)
    client, transport = world.hosted(
        [
            _json_reply({"kind": "appearance"}, Role.STRUCTURED_EXTRACTION),
            _json_reply(draft(), Role.STRUCTURED_EXTRACTION),
        ]
    )
    propose_appearance(
        world.connection,
        client,
        f"make the horizon softer where {PERSON} stands outside {PLACE}",
        world.session,
        current=current_reference(),
        world_id=WORLD,
        store=None,
    )
    return transport


def run_environment(world: World) -> Witness:
    """The environment drafter, handed the utterance as the environment panel's route hands it."""
    client, transport = world.hosted(
        [_json_reply({"operation": "place_selected_feature"}, Role.STRUCTURED_EXTRACTION)]
    )
    propose_environment_operation(
        world.connection,
        client,
        f"put the selected tree where {PERSON} waits outside {PLACE}",
        world.session,
        [EnvironmentOperation.PLACE_SELECTED_FEATURE],
    )
    return transport


def run_caption(world: World) -> Witness:
    """The derivative worker's caption pass over the process's client."""
    transport = Witness([_vector_reply()])
    embedded = CaptionEmbeddingPass(_process_client(transport))(
        world.connection, world.repository.workspace_id, world.capture, before_send=_allow
    )
    assert embedded is not None
    return transport


def run_vision(world: World) -> Witness:
    """A photograph through the ingest pipeline with the hosted vision model."""
    transport = Witness([_json_reply(OBSERVATION, Role.VISION)])
    pipeline = PhotoIngestPipeline(
        world.repository,
        world.store,
        vision=NebiusVisionModel(_process_client(transport)),
    )
    photograph = write_photo(world.photo_dir, "vision.jpg", when="2026:08:28 01:00:00")
    outcome = ingest_observed(pipeline, world.repository, photograph)
    assert outcome.error is None, outcome.error
    assert "vision" in outcome.stages_run
    return transport


def run_society(world: World) -> Witness:
    """A society decision, bound as the society runtime binds it, over a context naming both."""
    transport = Witness([_json_reply({"kind": "wait", "target_id": None}, Role.REASONING_CHEAP)])
    provider = SocietyDecisionProvider(_process_client(transport), Role.REASONING_CHEAP, "a" * 64)
    bound = dataclasses.replace(
        provider,
        client=provider.client.with_policy(
            world.services.request_policy(
                world.repository.workspace_id,
                lambda: _lent(world.connection),
                released_places=no_place_released,
            )
        ),
    )
    result = bound.propose(
        {"own_beliefs": [{"origin": "communication", "text": f"{PERSON} waits at {PLACE}"}]}
    )
    assert result["status"] == "accepted", result
    return transport


class _lent:
    """The test's connection, lent for one judgement the way a session would be opened."""

    def __init__(self, connection) -> None:
        self._connection = connection

    def __enter__(self):
        return self._connection

    def __exit__(self, *exc) -> None:
        return None


#: The run that exercises each path, and what that run must still carry besides names.
SCENARIOS: Mapping[str, tuple[Callable[[World], Witness], str]] = {
    "planner": (run_ask, "running club shirt"),
    "composer": (run_ask, "RUNNING CLUB"),
    "society composer": (run_society_question, "Simulated minute"),
    "query embedding": (run_supplied_plan, "running club"),
    "request classifier": (run_appearance, "make the horizon softer"),
    "appearance drafter": (run_appearance, "THE REVIEWED CATALOGUE"),
    "environment drafter": (run_environment, "put the selected tree"),
    "caption embedding": (run_caption, "RUNNING CLUB"),
    "vision": (run_vision, "Describe this photograph"),
    "society decision": (run_society, "waits at"),
}

#: The paths whose call site replaces saved names itself, and the modules it replaces them with.
CALL_SITE_REPLACES: Mapping[str, tuple[str, ...]] = {
    "planner": ("exulanica.selection.request_names",),
    "composer": ("exulanica.selection.request_names",),
    "request classifier": ("exulanica.selection.request_names",),
    "appearance drafter": ("exulanica.selection.request_names",),
    "environment drafter": ("exulanica.selection.request_names",),
}


def test_every_registered_path_has_a_scripted_run():
    assert set(SCENARIOS) == set(HOSTED_CALL_PATHS)
    assert set(CALL_SITE_REPLACES) <= set(HOSTED_CALL_PATHS)


def _holds(path: str, transport: Witness, admissions: list[tuple[str, ...]]) -> None:
    _, carried = SCENARIOS[path]
    assert transport.requests, f"the {path} run sent nothing, so it shows nothing"
    assert path in transport.paths, f"the {path} run never reached {HOSTED_CALL_PATHS[path]}"
    assert None not in transport.paths, "a request came from a call site no path names"
    bodies = [_body(request["payload"]) for request in transport.requests]
    for body in bodies:
        assert not _leaks(body), f"{path}: sent to a hosted model: {_leaks(body)}"
    # Positive control: the path's own request carried what it exists to carry.
    own = [body for body, sent_by in zip(bodies, transport.paths, strict=True) if sent_by == path]
    assert any(carried in body for body in own), f"{path}: nothing it carries reached it"
    sent = [request_parts(request["payload"])[0] for request in transport.requests]
    assert sent == admissions, "a request left that the workspace policy did not admit as sent"


@pytest.mark.parametrize("path", sorted(HOSTED_CALL_PATHS))
def test_no_saved_name_leaves_on_any_hosted_path(world, admissions, path):
    run, _ = SCENARIOS[path]
    transport = run(world)
    _holds(path, transport, admissions[-len(transport.requests) :])


def _unreplaced(text, names, placeholders=None, **_kwargs):
    """A call site that replaces nothing."""
    return Redacted(text=text, placeholders=dict(placeholders or {}))


@pytest.mark.parametrize("path", sorted(CALL_SITE_REPLACES))
def test_the_boundary_alone_holds_where_a_call_site_replaces_nothing(
    world, admissions, monkeypatch, path
):
    for module in CALL_SITE_REPLACES[path]:
        monkeypatch.setattr(sys.modules[module], "redact_names", _unreplaced)
    run, _ = SCENARIOS[path]
    transport = run(world)
    _holds(path, transport, admissions[-len(transport.requests) :])


# -- the right check at the boundary, reached past the call site's own ---------------------------


def test_the_composer_is_refused_at_the_boundary_when_the_call_sites_check_is_missing(
    world, monkeypatch
):
    """A packet's photographs are checked as the request leaves, not only where it is built."""
    import exulanica.api.services as services_module

    def refuse(connection, workspace_id, captures, handoff):
        raise PrivacyAdmissionError("no personal model right names this model")

    monkeypatch.setattr(services_module, "photograph_text_right", refuse)
    world.embed_caption()
    plan = SelectionPlan(intent=Intent.CAPTURES, semantic_query="running club")
    client, transport = world.hosted([_vector_reply(), _answer_reply()])
    with pytest.raises(HostedRequestRefused, match="no personal model right"):
        answer_question(
            world.connection,
            client,
            "What does the sign say?",
            world.session,
            world_id=None,
            plan=plan,
            store=world.store,
            before_compose=lambda captures, handoff: None,
        )
    assert "composer" not in transport.paths
    # Positive control: the query embedding, which carries no photograph, did leave.
    assert transport.paths == ["query embedding"]


def test_the_vision_request_is_refused_at_the_boundary_when_the_stages_check_is_missing(
    world, monkeypatch
):
    """The photograph's right is asked again as its bytes leave, not only by the stage."""
    import exulanica.ingest.hosted_policy as hosted_policy
    import exulanica.ingest.stages.vision as vision_stage

    def refuse(*args, **kwargs):
        raise PrivacyAdmissionError("no personal model right names this model")

    monkeypatch.setattr(vision_stage, "require_model_right", lambda *args, **kwargs: None)
    monkeypatch.setattr(hosted_policy, "require_model_right", refuse)
    transport = Witness([_json_reply(OBSERVATION, Role.VISION)])
    pipeline = PhotoIngestPipeline(
        world.repository, world.store, vision=NebiusVisionModel(_process_client(transport))
    )
    photograph = write_photo(world.photo_dir, "refused.jpg", when="2026:08:28 02:00:00")
    outcome = ingest_observed(pipeline, world.repository, photograph)
    assert transport.requests == []
    assert outcome.error is not None and "no personal model right" in outcome.error
