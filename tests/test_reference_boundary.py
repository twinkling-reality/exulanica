"""Nothing withheld leaves in a reference query: every outgoing request is recorded and scanned.

The policy here is the product's own ``WorkspaceRequestPolicy``. Only its read of the workspace's
saved names is replaced by a fixed list, so this runs without a database; the redaction, the
place-name rule and the photograph rule are the code that runs. A person's saved name, a saved
place with no right, the account's own name and email, first-person words and a vision note are
planted, and each must be absent from every recorded request body. Each guard is then broken in
turn and the scan must catch the leak, so the scan is shown able to fail.
"""

from __future__ import annotations

import ast
import contextlib
import json
import re
import uuid
from pathlib import Path

import pytest
from exulanica.epistemics import hosted_requests
from exulanica.epistemics.hosted_requests import WorkspaceRequestPolicy, no_place_released
from exulanica.epistemics.saved_names import SavedName
from exulanica.errors import PrivacyAdmissionError
from exulanica.models.transport import HttpResponse
from exulanica.references import boundary
from exulanica.references.adapters.tavily import TavilySearch
from exulanica.references.boundary import (
    QueryRefused,
    SearchSubject,
    admit_query,
    source_handoff,
)
from exulanica.references.catalogs import load_reference_catalogs

from model_fakes import FakeTransport, RecordingPolicy

WORKSPACE = uuid.UUID("5d0c6f3e-6d0e-4f0a-9a43-6f1d2c0e7b11")
PERSON = SavedName(
    uuid.UUID("0b1f3c52-2c55-4a50-8e0a-2f6f1d9c4e01"), "person", "Marguerite Okonkwo"
)
PLACE = SavedName(uuid.UUID("0b1f3c52-2c55-4a50-8e0a-2f6f1d9c4e02"), "place", "Fernhollow Cottage")
ACCOUNT = ("Rosalind Teague", "rteague@example.test")
VISION_NOTE = "a cracked green door beside a rusted bicycle"

#: Every planted string, and the subject that tries to carry it out.
ATTEMPTS = {
    "a saved person's name": ("harbour houses Marguerite Okonkwo painted", "Okonkwo"),
    "a saved place's name": ("cottages like Fernhollow Cottage", "Fernhollow"),
    "the account's own name": ("Teague family farmhouse style", "Teague"),
    "the account's email": ("rteague@example.test farm", "rteague"),
    "a first-person subject": ("my grandmother's kitchen dresser", "grandmother"),
    "a link": ("houses from www.example.test gallery", "example.test"),
    "a phone number": ("bakery 0207 946 0018 shopfront", "946"),
    "a credential word": ("password protected gate lodge", "password"),
}
SAFE = ("whitewashed island houses", "stone quays with fishing boats")


@pytest.fixture
def policy(monkeypatch) -> WorkspaceRequestPolicy:
    monkeypatch.setattr(
        hosted_requests, "saved_names", lambda connection, workspace: (PERSON, PLACE)
    )

    def no_photograph(connection, workspace, photographs, handoff):
        raise PrivacyAdmissionError("no model right names a search source")

    return WorkspaceRequestPolicy(
        WORKSPACE,
        connection=lambda: contextlib.nullcontext(object()),
        photograph_right=no_photograph,
        released_places=no_place_released,
    )


def _answer() -> HttpResponse:
    return HttpResponse(
        200,
        json.dumps(
            {"results": [{"content": "White cube houses."}], "images": [], "usage": {"credits": 1}}
        ),
    )


def _run(policy, subjects) -> tuple[FakeTransport, dict[str, int]]:
    """Each subject through the boundary and, if admitted, the adapter; refusals by code."""
    source = load_reference_catalogs().sources["tavily_search"]
    transport = FakeTransport([_answer() for _ in subjects])
    adapter = TavilySearch(source, transport=transport, credential="tvly-test")
    refused: dict[str, int] = {}
    for text in subjects:
        try:
            query = admit_query(
                SearchSubject(text, "buildings"),
                source=source,
                policy=policy,
                withheld_words=ACCOUNT,
            )
        except QueryRefused as refusal:
            refused[refusal.code] = refused.get(refusal.code, 0) + 1
            continue
        adapter.search(query)
    return transport, refused


def _sent(transport: FakeTransport) -> str:
    return json.dumps([request["payload"] for request in transport.requests]).lower()


def test_safe_subjects_leave_unchanged(policy) -> None:
    transport, refused = _run(policy, SAFE)
    assert refused == {}
    assert [request["payload"]["query"] for request in transport.requests] == list(SAFE)


@pytest.mark.parametrize("case", sorted(ATTEMPTS))
def test_nothing_withheld_reaches_any_outgoing_request(policy, case: str) -> None:
    subject, planted = ATTEMPTS[case]
    transport, refused = _run(policy, (subject, *SAFE))
    assert sum(refused.values()) == 1
    assert len(transport.requests) == len(SAFE)
    assert planted.lower() not in _sent(transport)


def test_the_refusals_name_why_and_never_quote(policy) -> None:
    source = load_reference_catalogs().sources["tavily_search"]
    expected = {
        "a saved person's name": "names_withheld",
        "a saved place's name": "names_withheld",
        "the account's own name": "withheld_word",
        "the account's email": "link_or_contact",
        "a first-person subject": "screened_word",
        "a link": "link_or_contact",
        "a phone number": "long_number",
        "a credential word": "screened_word",
    }
    for case, (subject, planted) in ATTEMPTS.items():
        with pytest.raises(QueryRefused) as refusal:
            admit_query(
                SearchSubject(subject, "buildings"),
                source=source,
                policy=policy,
                withheld_words=ACCOUNT,
            )
        assert refusal.value.code == expected[case], case
        assert planted.lower() not in str(refusal.value).lower()


def test_a_vision_note_cannot_be_a_subject_because_the_policy_refuses_any_photograph(
    policy,
) -> None:
    # A caller that tried to send picture-derived text would have to declare its photograph, and
    # no right names a search source; the request is refused before any query exists.
    source = load_reference_catalogs().sources["tavily_search"]
    request = hosted_requests.HostedRequest(
        role=boundary.SEARCH_ROLE,
        handoff=source_handoff(source),
        texts=(VISION_NOTE,),
        instructions=(),
        photographs=frozenset({uuid.uuid4()}),
        images=0,
    )
    with pytest.raises(PrivacyAdmissionError):
        policy.admit(request)


# --- Each guard broken in turn: the scan must then see the leak. ---


def test_without_the_request_policy_a_saved_name_would_leave(policy) -> None:
    transport, _ = _run(RecordingPolicy(), (ATTEMPTS["a saved person's name"][0],))
    assert "okonkwo" in _sent(transport)


def test_without_the_screen_the_account_email_would_leave(policy, monkeypatch) -> None:
    monkeypatch.setattr(boundary, "screen_text", lambda text, **kwargs: None)
    transport, _ = _run(policy, (ATTEMPTS["the account's email"][0],))
    assert "rteague" in _sent(transport)


def test_a_subject_the_policy_rewrites_is_refused_not_sent_rewritten() -> None:
    class Redacting:
        def admit(self, request):
            return tuple(text.replace("Fernhollow Cottage", "[place A]") for text in request.texts)

    with pytest.raises(QueryRefused) as refusal:
        admit_query(
            SearchSubject("cottages like Fernhollow Cottage", "buildings"),
            source=load_reference_catalogs().sources["tavily_search"],
            policy=Redacting(),
        )
    assert refusal.value.code == "names_withheld"


def test_without_the_placeholder_rule_a_placeholder_would_leave(monkeypatch) -> None:
    subject = ("cottages like [place A]",)
    transport, refused = _run(RecordingPolicy(), subject)
    assert refused == {"names_withheld": 1} and transport.requests == []
    monkeypatch.setattr(boundary, "PLACEHOLDER", re.compile(r"(?!x)x"))
    transport, _ = _run(RecordingPolicy(), subject)
    assert "[place a]" in _sent(transport)


# --- The source scan: one way out. ---

PACKAGE = Path(__file__).resolve().parents[1] / "exulanica"


def _calls(name: str) -> list[tuple[str, str]]:
    """Every call to ``name`` (as a function or a method) in the package, by module and function."""
    found: list[tuple[str, str]] = []
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for function in ast.walk(tree):
            if not isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for node in ast.walk(function):
                if isinstance(node, ast.Call):
                    callee = node.func
                    called = (
                        callee.attr
                        if isinstance(callee, ast.Attribute)
                        else getattr(callee, "id", None)
                    )
                    if called == name:
                        module = ".".join(path.relative_to(PACKAGE.parent).with_suffix("").parts)
                        found.append((module, function.name))
    return found


def test_only_the_boundary_builds_an_admitted_query() -> None:
    assert set(_calls("AdmittedQuery")) == {("exulanica.references.boundary", "admit_query")}


def test_a_reference_source_is_sent_to_only_from_an_adapter_search() -> None:
    reference_posts = {
        call for call in _calls("post_json") if call[0].startswith("exulanica.references")
    }
    assert reference_posts == {("exulanica.references.adapters.tavily", "search")}
