"""A place's saved name leaves only where its namer allowed it, in the requests that honour it.

The owner's rules: a person's name never goes to a hosted model, with or without a right, and a
confirmed place's name goes only under a right its namer grants for that place and that model,
asked for each place. The default is no, and a stop takes effect on the next request. The right is
stored and resolved by :mod:`exulanica.consent.place_name_rights`; every hosted request passes the
workspace policy of :mod:`exulanica.epistemics.hosted_requests`, which releases a place's name only
where the resolver it was built with does. What is held here is the wiring between the two,
through the constructions the product runs:

*   ``build_services`` gives the right's resolver to every route's client, to the society
    runtime's policy and to the API's derivative worker;
*   the standalone worker command gives it to its caption pass;
*   the vision stage keeps the resolver that releases nothing, because no vision use is offered.

Every run records what the transport was handed and which registered hosted path sent it: the
paths are ``HOSTED_CALL_PATHS`` in ``tests/test_hosted_boundary.py``, held there to the code. A
person and a place are saved through ``name_occurrence`` and both are written on each photograph's
sign, as ``tests/test_companion_saved_names.py`` draws them, and each decision is recorded through
the product's own grant and withdrawal.
"""

from __future__ import annotations

import dataclasses
import json
import sys
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import psycopg
import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import API_TOKENS_ENV
from exulanica.api.services import (
    DATA_DIR_ENV,
    DERIVATIVE_WORKER_ENV,
    READONLY_DATABASE_URL_ENV,
    Services,
    build_services,
)
from exulanica.consent import place_name_rights
from exulanica.consent.place_name_rights import grant_place_name, withdraw_place_name
from exulanica.consent.place_names import load_place_name_uses
from exulanica.db.migrate import provision_workspace
from exulanica.db.roles import EXECUTOR_ROLE, provision_runtime_role
from exulanica.db.session import DATABASE_URL_ENV
from exulanica.env import env_name
from exulanica.epistemics.hosted_requests import borrowing, no_place_released
from exulanica.epistemics.saved_names import Redacted
from exulanica.ingest import worker_command
from exulanica.ingest.hosted_policy import photograph_policy
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.worker import DerivativeWorker
from exulanica.models.client import ModelClient
from exulanica.models.handoff import ModelHandoff
from exulanica.models.manifest import Manifest, Role, load_manifest
from exulanica.models.policy import HostedRequest
from exulanica.models.transport import HttpResponse
from exulanica.selection.answer import Answer, AnswerClause, ClauseType
from exulanica.selection.environment_proposal import (
    EnvironmentOperation,
    propose_environment_operation,
)
from exulanica.selection.plan import Intent, SelectionPlan
from exulanica.selection.proposal import propose_appearance
from fastapi.testclient import TestClient

from conftest import (
    DEFAULT_PAYLOAD,
    CountingVisionModel,
    ingest_observed,
    scratch_role_database,
    write_photo,
)
from model_fakes import FakeTransport, chat_body
from test_companion_saved_names import PERSON, PLACE, TEXT, _vector_reply, named
from test_hosted_boundary import HOSTED_CALL_PATHS
from test_selection_proposal import WORLD, _seed_world, current_reference, draft
from tests_support_api import EVERY_PERMISSION, scratch_database
from world_support import registered_world

pytestmark = pytest.mark.postgres

__all__ = ["named"]

USES = load_place_name_uses()
MANIFEST = load_manifest()
EMBEDDING = Role.EMBEDDING.value

OWNER = "place-release-owner-token-that-is-long-enough-to-be-accepted"
AUTH = {"Authorization": f"Bearer {OWNER}"}

#: Each registered hosted path by the function whose frame sends it, so a request says who sent it.
_SITES: Mapping[tuple[str, str], str] = {site: path for path, site in HOSTED_CALL_PATHS.items()}

#: The placeholder the boundary gives the fixture's one saved place, lower-cased as bodies are read.
_PLACE_HELD = "[place a]"


# -- what a request carried ------------------------------------------------------------------------


def _read(body: str) -> tuple[bool, list[str]]:
    """Whether a body holds the place's saved name, and each part of the person's that it holds."""
    lowered = " ".join(body.lower().split())
    return PLACE.lower() in lowered, [part for part in PERSON.lower().split() if part in lowered]


def _carries_the_place(body: str) -> bool:
    """The place went by name, and not one part of the person's name went with it."""
    place, person = _read(body)
    assert not person, f"a person's name reached a hosted model: {person} in {body}"
    return place


def _withholds_the_place(body: str) -> bool:
    """The place was in the text and went as its placeholder: withheld, not merely absent."""
    place, person = _read(body)
    assert not person, f"a person's name reached a hosted model: {person} in {body}"
    return not place and _PLACE_HELD in body.lower()


def _sending_path() -> str | None:
    frame = sys._getframe(1)
    while frame is not None:
        site = (frame.f_globals.get("__name__"), frame.f_code.co_qualname)
        if site in _SITES:
            return _SITES[site]
        frame = frame.f_back
    return None


# -- the transport ---------------------------------------------------------------------------------


def _chat(value: str) -> HttpResponse:
    return HttpResponse(status_code=200, text=json.dumps(chat_body(value)))


def _answer(*clauses: AnswerClause) -> HttpResponse:
    return _chat(Answer(clauses=list(clauses)).model_dump_json())


#: A composed answer the validator accepts: it claims nothing about the photographs.
_ANSWERED = _answer(AnswerClause(text="I have no evidence for that.", type=ClauseType.META))
#: One the validator refuses, a historical claim citing nothing, so the composer is asked again.
_REFUSED = _answer(AnswerClause(text="You were there.", type=ClauseType.HISTORICAL))


class Recorder(FakeTransport):
    """Every request as the transport was handed it, and the registered path that sent it.

    It answers each role's primary model with a reply that role's caller accepts, so any number of
    requests can be sent through one instance, and the paths that share the extraction role each
    with a reply of their own form. ``composer`` replies, when given, are handed out in order
    instead, which is how a refused answer and its repair are scripted. ``during`` is called with
    the sending path while each request is in flight.
    """

    def __init__(
        self,
        manifest: Manifest,
        *,
        composer: list[HttpResponse] | None = None,
        during: Callable[[str | None], None] | None = None,
    ) -> None:
        super().__init__(list(composer or ()))
        self.paths: list[str | None] = []
        self.during = during
        self.by_model = {
            manifest[Role.EMBEDDING].primary.model_id: _vector_reply(),
            manifest[Role.STRUCTURED_EXTRACTION].primary.model_id: _chat(
                SelectionPlan(
                    intent=Intent.CAPTURES, semantic_query="running club"
                ).model_dump_json()
            ),
        }
        if composer is None:
            self.by_model[manifest[Role.REASONING_CHEAP].primary.model_id] = _ANSWERED
        #: The extraction role's paths other than the planner, each answered in its own form.
        self.by_path = {
            "request classifier": _chat(json.dumps({"kind": "appearance"})),
            "appearance drafter": _chat(json.dumps(draft())),
            "environment drafter": _chat(json.dumps({"operation": "place_selected_feature"})),
        }

    def post_json(self, url, *, headers, payload, timeout):
        path = _sending_path()
        self.paths.append(path)
        if self.during is not None:
            self.during(path)
        if path in self.by_path:
            self.requests.append({"url": url, "headers": dict(headers), "payload": dict(payload)})
            return self.by_path[path]
        return super().post_json(url, headers=headers, payload=payload, timeout=timeout)

    def sent_by(self, path: str) -> list[str]:
        """The body of every request ``path`` sent, in order."""
        return [
            json.dumps(request["payload"], ensure_ascii=False)
            for request, sender in zip(self.requests, self.paths, strict=True)
            if sender == path
        ]

    def urls_of(self, path: str) -> list[str]:
        return [
            request["url"]
            for request, sender in zip(self.requests, self.paths, strict=True)
            if sender == path
        ]


# -- the instance ----------------------------------------------------------------------------------


class _Unopened:
    """The worker command's database, which these runs never open: the pass is handed its own."""

    url = "postgresql://never-opened.invalid/exulanica"

    @classmethod
    def from_env(cls, environ):
        return cls()

    @contextmanager
    def unscoped(self):
        yield None


@dataclass
class Instance:
    """One workspace, with a person and a place saved, and the product built over it."""

    repository: Any
    store: Any
    session: Any
    entities: Mapping[str, uuid.UUID]
    scratch: str
    tmp_path: Path
    photo_dir: Path
    open_another: Callable[[], Any]
    photographs: list[uuid.UUID] = dataclasses.field(default_factory=list)

    @property
    def workspace_id(self) -> uuid.UUID:
        return self.repository.workspace_id

    @property
    def place(self) -> uuid.UUID:
        return self.entities["place"]

    @property
    def asking(self) -> str:
        """``POST /selection/ask`` in this workspace's world, registered the first time asked."""
        world = registered_world(self.repository.connection, self.workspace_id)
        return f"/selection/ask?world_id={world}"

    def client(
        self, manifest: Manifest = MANIFEST, **recorder: Any
    ) -> tuple[ModelClient, Recorder]:
        """The process's client, with no policy, as ``build_services`` receives one."""
        transport = Recorder(manifest, **recorder)
        client = ModelClient(api_key="test-key-not-real", manifest=manifest, transport=transport)
        return client, transport

    def services(self, client: ModelClient | None, *, worker: bool = False) -> Services:
        """What an instance builds from its environment, over this schema, with ``client``.

        The executor connects as the read-only role, as a deployment's does. The catalogs are left
        out, because nothing here reads them.
        """
        environ = {
            DATABASE_URL_ENV: scratch_database(self.scratch).url,
            READONLY_DATABASE_URL_ENV: scratch_role_database(self.scratch, EXECUTOR_ROLE).url,
            DATA_DIR_ENV: str(self.tmp_path / "instance"),
            DERIVATIVE_WORKER_ENV: "1" if worker else "0",
            env_name("TEXTURE_DIRECTORY"): str(self.tmp_path / "no-texture-catalog"),
            env_name("CHARACTER_DIRECTORY"): str(self.tmp_path / "no-character-catalog"),
            API_TOKENS_ENV: json.dumps(
                {
                    OWNER: {
                        "workspace_id": str(self.workspace_id),
                        "actor": str(self.session.actor),
                        "permissions": EVERY_PERMISSION,
                    }
                }
            ),
        }
        return build_services(environ, model_client=client)

    @contextmanager
    def http(self, services: Services) -> Iterator[TestClient]:
        with TestClient(create_app(services, verify=False)) as client:
            yield client

    def api_worker(self, client: ModelClient) -> DerivativeWorker:
        worker = self.services(client, worker=True).build_derivative_worker()
        assert worker is not None
        return worker

    def standalone_worker(self, client: ModelClient, monkeypatch) -> DerivativeWorker:
        """The worker ``exulanica-derivative-worker`` builds, around ``client``."""
        monkeypatch.setattr(worker_command, "Database", _Unopened)
        monkeypatch.setattr(worker_command, "verify_schema", lambda database: None)
        monkeypatch.setattr(worker_command, "assert_runtime_role", lambda connection: None)
        monkeypatch.setattr(worker_command, "ModelClient", lambda **_: client)
        args = SimpleNamespace(workspace=[str(self.workspace_id)], name="wiring", poll_seconds=2.0)
        environ = {
            worker_command.DATA_DIR_ENV: str(self.tmp_path / "worker"),
            worker_command.MODEL_KEY_ENV: "test-key-not-real",
        }
        return worker_command._build_worker(args, environ)

    def photograph(self) -> uuid.UUID:
        """Another photograph whose sign carries both saved names, so its caption request does."""
        payload = json.loads(json.dumps(DEFAULT_PAYLOAD))
        payload["legible_text"] = [
            {"text": text, "is_signage": True, "confidence": "high", "box": None} for text in TEXT
        ]
        pipeline = PhotoIngestPipeline(
            self.repository, self.store, vision=CountingVisionModel(payload=payload)
        )
        taken = f"2026:08:28 {10 + len(self.photographs):02d}:00:00"
        outcome = ingest_observed(
            pipeline,
            self.repository,
            write_photo(self.photo_dir, f"sign-{len(self.photographs)}.jpg", when=taken),
        )
        assert outcome.error is None, outcome.error
        self.photographs.append(outcome.capture_id)
        return outcome.capture_id

    def caption(self, worker: DerivativeWorker, capture: uuid.UUID) -> None:
        """The worker's caption pass for one capture, under the capture's own screening."""
        screening = self.repository.latest_privacy_screening(capture)
        assert screening is not None, "the fixture photograph has no screening to send under"
        embedded, withheld = worker._embed_captions(
            self.repository, capture, screening.screening_id
        )
        assert withheld is None, withheld
        assert embedded is not None, "the caption pass sent nothing, so it shows nothing"

    def ask(self, http: TestClient, query: str) -> dict:
        """``POST /selection/ask`` with a plan the caller supplies, its query as given."""
        plan = SelectionPlan(intent=Intent.CAPTURES, semantic_query=query)
        response = http.post(
            self.asking,
            headers=AUTH,
            json={
                "question": "Where does the running club meet?",
                "plan": plan.model_dump(mode="json"),
            },
        )
        assert response.status_code == 200, response.text
        return response.json()

    def notice(self, role: str = EMBEDDING) -> str:
        use = USES.use(role)
        assert use is not None, f"the {role} use is not offered"
        return USES.notice(use, USES.handoff(use, MANIFEST))

    def grant(self, role: str = EMBEDDING) -> None:
        grant_place_name(
            self.repository.connection,
            self.workspace_id,
            entity_id=self.place,
            role=role,
            notice=self.notice(role),
            actor=self.session.actor,
        )

    def withdraw(self, role: str = EMBEDDING) -> None:
        withdraw_place_name(
            self.repository.connection,
            self.workspace_id,
            entity_id=self.place,
            role=role,
            actor=self.session.actor,
        )


@pytest.fixture
def instance(named, spine_schema, ingest_spine, tmp_path, photo_dir) -> Instance:
    repository, store, session, entities = named
    provision_workspace(repository.connection, repository.workspace_id)
    provision_runtime_role(repository.connection, role=EXECUTOR_ROLE, read_only=True)
    (first,) = repository.connection.execute(
        "select capture_id from capture where workspace_id=%s", (repository.workspace_id,)
    ).fetchall()
    return Instance(
        repository,
        store,
        session,
        entities,
        spine_schema[1],
        tmp_path,
        photo_dir,
        ingest_spine[1],
        [first["capture_id"]],
    )


@pytest.fixture
def resolutions(monkeypatch) -> list[tuple[str, frozenset[str]]]:
    """Each time the place-name right was read: the role of the connection, and the roles asked."""
    seen: list[tuple[str, frozenset[str]]] = []
    original = place_name_rights._released

    def read(connection, workspace_id, handoff, entity_ids, uses, manifest):
        row = connection.execute("select current_user as who").fetchone()
        seen.append(
            (
                row["who"] if isinstance(row, Mapping) else row[0],
                frozenset(identity.role for identity in handoff.identities),
            )
        )
        return original(connection, workspace_id, handoff, entity_ids, uses, manifest)

    monkeypatch.setattr(place_name_rights, "_released", read)
    return seen


def _unreplaced(text, names, placeholders=None, **_kwargs):
    """A call site that replaces nothing, so what leaves is the boundary's decision alone."""
    return Redacted(text=text, placeholders=dict(placeholders or {}))


# -- the caption pass, as either worker builds it --------------------------------------------------

WORKERS: Mapping[str, Callable[[Instance, ModelClient, Any], DerivativeWorker]] = {
    "the API's worker": lambda instance, client, _: instance.api_worker(client),
    "the standalone worker": lambda instance, client, monkeypatch: instance.standalone_worker(
        client, monkeypatch
    ),
}


@pytest.mark.parametrize("built_by", sorted(WORKERS))
def test_a_caption_request_carries_a_place_only_while_its_namer_allows_the_embedding_use(
    instance, monkeypatch, built_by
):
    """Default no; allowed, the name goes; stopped, the next photograph's request holds it back."""
    client, transport = instance.client()
    worker = WORKERS[built_by](instance, client, monkeypatch)

    instance.caption(worker, instance.photographs[0])
    instance.grant()
    instance.caption(worker, instance.photograph())
    instance.withdraw()
    instance.caption(worker, instance.photograph())

    assert transport.paths == ["caption embedding"] * 3
    before, allowed, after = transport.sent_by("caption embedding")
    assert _withholds_the_place(before)
    assert _carries_the_place(allowed)
    assert _withholds_the_place(after)
    # Positive control: every request carried the photograph's text, the person as a placeholder.
    for body in (before, allowed, after):
        assert "RUNNING CLUB" in body and "[person A]" in body


def _vectors(instance: Instance) -> int:
    return instance.repository.connection.execute(
        "select count(*) as vectors from embedding where workspace_id=%s", (instance.workspace_id,)
    ).fetchone()["vectors"]


def test_a_decision_changes_the_requests_sent_after_it_and_no_vector_already_stored(instance):
    """The caption index is keyed by the text as stored, not by what a decision let leave."""
    client, transport = instance.client()
    worker = instance.api_worker(client)
    first = instance.photographs[0]
    instance.caption(worker, first)
    assert _vectors(instance) == 1
    instance.grant()

    screening = instance.repository.latest_privacy_screening(first)
    again = worker._embed_captions(instance.repository, first, screening.screening_id)

    assert again == (None, None), "a caption embedded before the grant was sent again"
    second = instance.photograph()
    instance.caption(worker, second)
    instance.withdraw()
    assert _vectors(instance) == 2, "a stop removed or remade a vector"
    before, allowed = transport.sent_by("caption embedding")
    assert _withholds_the_place(before) and _carries_the_place(allowed)
    assert transport.paths == ["caption embedding"] * 2


# -- the query embedding, through the route, and nothing else the question sends -------------------


def test_a_query_request_carries_a_place_only_while_allowed_and_no_other_request_does(instance):
    """The whole round trip a person makes: ask, allow in the Library, ask, stop, ask again."""
    client, transport = instance.client()
    services = instance.services(client)
    # A stored caption vector, so a question's query is embedded at all.
    instance.caption(instance.api_worker(client), instance.photographs[0])
    query = f"{PERSON} running club at {PLACE}"
    rights = f"/place-name-rights/{instance.place}"

    with instance.http(services) as http:
        instance.ask(http, query)
        read = http.get(rights, headers=AUTH)
        assert read.status_code == 200, read.text
        (use,) = [each for each in read.json()["uses"] if each["use"] == EMBEDDING]
        allowed = http.post(
            f"{rights}/grants", headers=AUTH, json={"use": EMBEDDING, "notice": use["notice"]}
        )
        assert allowed.status_code == 201, allowed.text
        instance.ask(http, query)
        stopped = http.post(f"{rights}/withdrawals", headers=AUTH, json={"use": EMBEDDING})
        assert stopped.status_code == 201, stopped.text
        instance.ask(http, query)

    before, granted, after = transport.sent_by("query embedding")
    assert _withholds_the_place(before)
    assert _carries_the_place(granted)
    assert _withholds_the_place(after)
    assert "running club" in granted and "[person A]" in granted
    # The composer is sent the same photograph, its sign naming the place, and never the name.
    composed = transport.sent_by("composer")
    assert len(composed) == 3, "the composer was not reached, so its absence shows nothing"
    assert all(_withholds_the_place(body) for body in composed)
    assert set(transport.paths) == {"caption embedding", "query embedding", "composer"}


def test_a_place_allowed_for_the_embedding_use_reaches_no_other_roles_request(
    instance, monkeypatch
):
    """With the Companion's call sites replacing nothing, the boundary alone keeps it from them.

    The question is asked in words, so the planner, the query embedding and the composer are each
    sent the place's name by their call sites. The embedding role's request carries it; the
    planner's and the composer's hand-overs were never allowed, so theirs hold it back.
    """
    monkeypatch.setattr(
        sys.modules["exulanica.selection.request_names"], "redact_names", _unreplaced
    )
    client, transport = instance.client()
    transport.by_model[MANIFEST[Role.STRUCTURED_EXTRACTION].primary.model_id] = _chat(
        SelectionPlan(
            intent=Intent.CAPTURES, semantic_query=f"running club at {PLACE}"
        ).model_dump_json()
    )
    services = instance.services(client)
    instance.caption(instance.api_worker(client), instance.photographs[0])
    instance.grant()

    with instance.http(services) as http:
        response = http.post(
            instance.asking,
            headers=AUTH,
            json={"question": f"Is {PERSON} wearing the running club shirt outside {PLACE}?"},
        )
        assert response.status_code == 200, response.text

    (planned,) = transport.sent_by("planner")
    (searched,) = transport.sent_by("query embedding")
    (composed,) = transport.sent_by("composer")
    assert _withholds_the_place(planned)
    assert _carries_the_place(searched)
    assert _withholds_the_place(composed)


def test_a_question_asked_in_words_searches_without_the_name_even_while_it_is_allowed(instance):
    """The planner is sent the question with the place replaced, so its query cannot name it.

    The live planner copies a placeholder into its query; the question path removes it, because a
    placeholder is never a search term. So the words that reach the embedding role are the rest of
    the query, and the name the account holder allowed reaches it only in a query that names it.
    """
    client, transport = instance.client()
    transport.by_model[MANIFEST[Role.STRUCTURED_EXTRACTION].primary.model_id] = _chat(
        SelectionPlan(
            intent=Intent.CAPTURES, semantic_query="[place A] running club"
        ).model_dump_json()
    )
    services = instance.services(client)
    instance.caption(instance.api_worker(client), instance.photographs[0])
    instance.grant()

    with instance.http(services) as http:
        response = http.post(
            instance.asking,
            headers=AUTH,
            json={"question": f"Photographs of the running club at {PLACE}"},
        )
        assert response.status_code == 200, response.text

    (planned,) = transport.sent_by("planner")
    (searched,) = transport.sent_by("query embedding")
    assert _withholds_the_place(planned)
    assert json.loads(searched)["input"] == ["running club"]


def test_a_society_decision_carries_no_place_allowed_for_the_embedding_use(instance):
    """The society runtime's policy releases no place's name, whatever its namer allowed."""
    from exulanica.world.society_decisions import SocietyDecisionProvider

    client, transport = instance.client()
    transport.by_model[MANIFEST[Role.REASONING_CHEAP].primary.model_id] = _chat(
        json.dumps({"kind": "wait", "target_id": None})
    )
    services = instance.services(client)
    instance.grant()
    provider = SocietyDecisionProvider(client, Role.REASONING_CHEAP, "a" * 64)
    # Bound as exulanica.api.society_decision_runtime binds it: the workspace's policy, releasing
    # no place's name, on a fresh read-only session for each judgement.
    bound = dataclasses.replace(
        provider,
        client=provider.client.with_policy(
            services.request_policy(
                instance.workspace_id,
                lambda: services.readonly_database.session(instance.workspace_id),
                released_places=no_place_released,
            )
        ),
    )

    result = bound.propose(
        {"own_beliefs": [{"origin": "communication", "text": f"{PERSON} waits at {PLACE}"}]}
    )

    assert result["status"] == "accepted", result
    (decided,) = transport.sent_by("society decision")
    assert _withholds_the_place(decided)


# -- a grant is for one hand-over ------------------------------------------------------------------


def _elsewhere(manifest: Manifest) -> Manifest:
    """The same models, reached at an origin the grant does not name."""
    return dataclasses.replace(
        manifest,
        providers={
            key: dataclasses.replace(provider, base_url="https://elsewhere.example/v1")
            for key, provider in manifest.providers.items()
        },
    )


def _unallowed(manifest: Manifest) -> Any:
    return dataclasses.replace(
        manifest[Role.EMBEDDING].primary, model_id="unallowed/embedding-model"
    )


def _beside(manifest: Manifest) -> Manifest:
    """The allowed model, with a fallback the grant does not name that can receive the request."""
    binding = dataclasses.replace(manifest[Role.EMBEDDING], fallback=_unallowed(manifest))
    return dataclasses.replace(manifest, roles={**manifest.roles, Role.EMBEDDING: binding})


def _instead(manifest: Manifest) -> Manifest:
    """A model the grant does not name, in place of the allowed one."""
    binding = dataclasses.replace(manifest[Role.EMBEDDING], primary=_unallowed(manifest))
    return dataclasses.replace(manifest, roles={**manifest.roles, Role.EMBEDDING: binding})


HANDOVERS: Mapping[str, tuple[Callable[[Manifest], Manifest], bool]] = {
    "the granted chain at its destination": (lambda manifest: manifest, True),
    "another destination": (_elsewhere, False),
    "a model beside the granted one": (_beside, False),
    "a model instead of the granted one": (_instead, False),
}


@pytest.mark.parametrize("handover", sorted(HANDOVERS))
def test_a_grant_reaches_only_the_models_and_destination_it_names(instance, handover):
    vary, released = HANDOVERS[handover]
    manifest = vary(MANIFEST)
    client, transport = instance.client(manifest)
    services = instance.services(client)
    instance.grant()

    instance.caption(instance.api_worker(client), instance.photographs[0])
    with instance.http(services) as http:
        instance.ask(http, f"running club at {PLACE}")

    (captioned,) = transport.sent_by("caption embedding")
    (searched,) = transport.sent_by("query embedding")
    for body in (captioned, searched):
        assert (_carries_the_place if released else _withholds_the_place)(body), handover
    # Positive controls: the requests went where the varied manifest sends them, and its
    # hand-over differs from the granted one exactly where the name was held back.
    endpoint = f"{manifest.provider(manifest[Role.EMBEDDING].provider).base_url}/embeddings"
    assert transport.urls_of("caption embedding") == [endpoint]
    assert transport.urls_of("query embedding") == [endpoint]
    granted = ModelHandoff.hosted(MANIFEST, Role.EMBEDDING)
    assert (ModelHandoff.hosted(manifest, Role.EMBEDDING) == granted) is released


# -- how the resolver runs -------------------------------------------------------------------------


def test_the_resolver_runs_on_the_routes_read_only_connection_once_per_hand_over(
    instance, resolutions
):
    """Only for a request carrying a saved place, once per hand-over in one request, never early.

    The first question's query names no place, so its vector request reads nothing, and the sign
    in its packet names the place, so the composer's hand-over is read once. The second question's
    composer is refused once and asked again: two requests to one hand-over, and one read.
    """
    client, transport = instance.client(composer=[_ANSWERED, _REFUSED, _ANSWERED])
    services = instance.services(client)
    instance.caption(instance.api_worker(client), instance.photographs[0])
    resolutions.clear()
    composer = (EXECUTOR_ROLE, frozenset({Role.REASONING_CHEAP.value}))

    with instance.http(services) as http:
        instance.ask(http, "running club")
        assert resolutions == [composer], "a request carrying no saved place's name read the right"
        instance.ask(http, f"running club at {PLACE}")

    assert resolutions == [composer, (EXECUTOR_ROLE, frozenset({EMBEDDING})), composer]
    assert transport.paths[-4:] == ["composer", "query embedding", "composer", "composer"]


def test_a_stop_commits_while_a_request_is_in_flight_and_holds_the_next_one_back(instance):
    """The right's read lock is released before the request leaves, so nothing waits on a model."""
    stops: list[str] = []

    def stop_while_sending(path: str | None) -> None:
        if path != "query embedding" or stops:
            return
        other = instance.open_another()
        try:
            withdraw_place_name(
                other.connection,
                instance.workspace_id,
                entity_id=instance.place,
                role=EMBEDDING,
                actor=instance.session.actor,
            )
            stops.append("recorded")
        except psycopg.errors.SerializationFailure as refused:
            stops.append(f"refused: {refused}")

    client, transport = instance.client(during=stop_while_sending)
    services = instance.services(client)
    instance.caption(instance.api_worker(client), instance.photographs[0])
    instance.grant()

    with instance.http(services) as http:
        instance.ask(http, f"running club at {PLACE}")
        instance.ask(http, f"running club at {PLACE}")

    assert stops == ["recorded"]
    in_flight, after = transport.sent_by("query embedding")
    assert _carries_the_place(in_flight), "the request admitted before the stop was sent as it was"
    assert _withholds_the_place(after)
    events = instance.repository.connection.execute(
        "select event from place_name_right_event order by sequence"
    ).fetchall()
    assert [event["event"] for event in events] == ["granted", "withdrawn"]


# -- the vision stage ------------------------------------------------------------------------------


def test_the_vision_stage_releases_no_place_because_no_vision_use_is_offered(instance):
    """No vision use is offered, so the vision stage's policy asks no right and releases nothing.

    Its policy is held against the instance's on the one hand-over the right does release, the
    embedding role's: the instance's policy lets the name go, the vision stage's does not, and
    for its own role's hand-over the vision stage's policy holds it back too.
    """
    assert USES.use(Role.VISION.value) is None
    instance.grant()
    capture = instance.photographs[0]
    screening = instance.repository.latest_privacy_screening(capture)
    assert screening is not None
    text = f"Is this {PLACE}?"

    def admitted(policy, role: Role, *, images: int) -> str:
        (sent,) = policy.admit(
            HostedRequest(
                role=role,
                handoff=ModelHandoff.hosted(MANIFEST, role),
                texts=(text,),
                instructions=(),
                photographs=frozenset(),
                images=images,
            )
        )
        return sent

    services = instance.services(None)
    instance_policy = services.request_policy(
        instance.workspace_id,
        borrowing(instance.repository.connection),
        released_places=services.released_place_names,
    )
    vision_policy = photograph_policy(instance.repository, capture, screening.screening_id)
    assert admitted(instance_policy, Role.EMBEDDING, images=0) == text, "the positive control"
    assert admitted(vision_policy, Role.EMBEDDING, images=0) == "Is this [place A]?"
    assert admitted(vision_policy, Role.VISION, images=1) == "Is this [place A]?"


# -- every offered use is honoured where the registry says -----------------------------------------


def _send_a_caption(instance: Instance, client: ModelClient, _http: TestClient) -> None:
    instance.caption(instance.api_worker(client), instance.photograph())


def _send_a_query(instance: Instance, _client: ModelClient, http: TestClient) -> None:
    instance.ask(http, f"running club at {PLACE}")


def _ask_in_words(instance: Instance, _client: ModelClient, http: TestClient) -> None:
    """``POST /selection/ask`` with a question in words naming the place: planner and composer."""
    response = http.post(
        instance.asking,
        headers=AUTH,
        json={"question": f"Which photographs show the running club at {PLACE}?"},
    )
    assert response.status_code == 200, response.text


def _hosted(instance: Instance, client: ModelClient) -> ModelClient:
    """The client a route sends through, with the instance's policy attached."""
    hosted = instance.services(client).hosted_model(
        instance.repository.connection, instance.workspace_id
    )
    assert hosted is not None
    return hosted


def _classify(instance: Instance, client: ModelClient, _http: TestClient) -> None:
    """The appearance path in a world that holds no evidence: classified, refused before a draft."""
    propose_appearance(
        instance.repository.connection,
        _hosted(instance, client),
        f"make the light warmer outside {PLACE}",
        instance.session,
        current=None,
        world_id=WORLD,
        store=None,
    )


def _draft_appearance(instance: Instance, client: ModelClient, _http: TestClient) -> None:
    """The appearance path on a world with bound evidence: classified, then drafted."""
    if not instance.repository.connection.execute(
        "select 1 from world_topology_source where workspace_id=%s limit 1",
        (instance.workspace_id,),
    ).fetchone():
        _seed_world(instance.repository, instance.tmp_path, instance.photo_dir)
    outcome = propose_appearance(
        instance.repository.connection,
        _hosted(instance, client),
        f"make the light warmer outside {PLACE}",
        instance.session,
        current=current_reference(),
        world_id=WORLD,
        store=None,
    )
    assert outcome.proposal is not None, outcome.refusal


def _draft_environment(instance: Instance, client: ModelClient, _http: TestClient) -> None:
    """The environment panel's proposal, as its route hands the drafter an utterance."""
    decision = propose_environment_operation(
        instance.repository.connection,
        _hosted(instance, client),
        f"put the selected building outside {PLACE}",
        instance.session,
        [EnvironmentOperation.PLACE_SELECTED_FEATURE],
    )
    assert decision.operation is EnvironmentOperation.PLACE_SELECTED_FEATURE, decision.refusal


#: How to send a request down each request path the uses registry may name in ``honoured_by``, as
#: the product builds that path, with a saved place in its text. A path the registry names and this
#: does not fails below, so a use cannot be offered until a run shows its paths honouring it.
HONOURING_RUNS: Mapping[str, Callable[[Instance, ModelClient, TestClient], None]] = {
    "exulanica.epistemics.caption_embeddings:embed_capture": _send_a_caption,
    "exulanica.selection.embeddings:embed_query": _send_a_query,
    "exulanica.selection.environment_proposal:draft_environment_operation": _draft_environment,
    "exulanica.selection.proposal:classify_request": _classify,
    "exulanica.selection.proposal:draft_appearance": _draft_appearance,
    "exulanica.selection.question:compose_answer": _send_a_query,
    "exulanica.selection.planner:propose_plan": _ask_in_words,
}

OFFERED = sorted((use.role.value, path) for use in USES.uses for path in use.honoured_by)


def test_the_registry_offers_something_to_honour():
    # Positive control for the parametrisation below: an empty registry would test nothing.
    assert OFFERED, "the uses registry offers no use"


@pytest.mark.parametrize(("role", "path"), OFFERED)
def test_every_offered_use_is_honoured_by_each_path_it_names(instance, role, path):
    """Behaviour, not a name: the path's own request carries the place exactly while allowed."""
    run = HONOURING_RUNS.get(path)
    assert run is not None, (
        f"the {role} use names {path} and nothing here sends a request down it; add a run that "
        "shows a granted place reaching that path's request before offering it"
    )
    module, function = path.split(":")
    sent_by = _SITES.get((module, function))
    assert sent_by is not None, f"{path} is no hosted call path tests/test_hosted_boundary.py knows"
    client, transport = instance.client()
    # A question's query is embedded only once a caption vector exists; the pass is the product's.
    instance.caption(instance.api_worker(client), instance.photographs[0])

    with instance.http(instance.services(client)) as http:
        run(instance, client, http)
        instance.grant(role)
        run(instance, client, http)

    sent = transport.sent_by(sent_by)[-2:]
    assert len(sent) == 2, f"{path} sent {len(sent)} request(s), so it shows nothing"
    before, allowed = sent
    assert _withholds_the_place(before)
    assert _carries_the_place(allowed)
