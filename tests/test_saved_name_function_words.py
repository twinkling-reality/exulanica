"""A closed-class word a saved name writes as no name is not a name by itself, in either layer.

A part of a person's or a voice's saved name is recognised alone, because people are called by one
of their names, except a word in ``name-part-function-words.v1.json`` (``FUNCTION_WORDS`` in
``exulanica/epistemics/saved_names.py``) that the saved name writes in lowercase while it
capitalises another part: the "the" of "Joe the Plumber". The saved name's own writing decides, so
"Nguyen The Anh" keeps "The" and a saved name written all in lowercase keeps every part. The rule
lives in the one matcher both layers use, the Companion's call sites (``RequestNames``) and the
boundary every hosted request passes (``WorkspaceRequestPolicy``), so each is driven here over a
workspace that holds the names.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from exulanica.epistemics.assertions import AssertionWriter
from exulanica.epistemics.saved_names import FUNCTION_WORDS, SavedName, redact_names
from exulanica.identity import IdentityRepository, rename_entity
from exulanica.models.manifest import Role
from exulanica.selection.request_names import RequestNames

from test_companion_saved_names import named
from test_hosted_request_policy import _client, _messages, _policy

__all__ = ["named"]

CATALOG = json.loads(
    (
        Path(__file__).resolve().parents[1]
        / "exulanica/epistemics/name-part-function-words.v1.json"
    ).read_text(encoding="utf-8")
)

#: Given names and surnames from many naming cultures, as they are written in Latin letters, among
#: them every one the catalog once held. None may be in the catalog, so none is ever skipped.
NAME_PARTS = {
    "English given names": (
        "Will",
        "May",
        "Bill",
        "Rose",
        "Hope",
        "Grace",
        "Art",
        "Joy",
        "Faith",
        "Mark",
        "June",
        "Ray",
        "Glen",
        "Dawn",
        "Summer",
        "Autumn",
        "Hunter",
        "Page",
        "Sonny",
        "Rich",
        "Chase",
    ),
    "English surnames": (
        "With",
        "Few",
        "Under",
        "Every",
        "From",
        "Over",
        "Much",
        "Such",
        "Both",
        "Some",
        "Below",
        "Down",
        "More",
        "Most",
        "Near",
        "Young",
        "Little",
        "Long",
        "Short",
        "Case",
        "Before",
    ),
    "Malay and Indonesian": ("Nor", "Nur", "Siti", "Aisyah", "Ahmad", "Binti", "Bin", "Wati"),
    "Arabic": ("Nor", "Abdul", "Al", "Bin", "Ibn", "Abu", "Umm", "Noor", "Nour"),
    "Burmese": ("Than", "Thet", "Thein", "Aung", "Kyaw", "Myint", "Soe", "Win", "Zaw", "Hla"),
    "Finnish": ("Into", "Onni", "Toivo", "Aino", "Usko", "Tapio", "Lahja"),
    "Vietnamese without diacritics": ("The", "Thi", "Van", "Anh", "Minh", "Nguyen", "Tran"),
    "Dutch and German particles": ("Van", "Von", "Der", "Den", "Ter", "Zu", "Vom", "Zum"),
    "Spanish and Portuguese": ("Del", "Dos", "Das", "Santos", "Paz", "Luz", "Cruz", "Sol"),
    "Italian and French": ("Della", "Delle", "Degli", "Del", "Des", "Lou", "Luce"),
    "Scandinavian": ("Per", "Till", "Tor", "Bo", "Ole", "Ask", "Siv"),
    "Chinese pinyin": ("Yan", "Wen", "Yet", "Hui", "Xin", "Bao", "Ren", "Yu", "Ai"),
    "Korean": ("Min", "Jin", "Sun", "Hye", "Eun", "Ho"),
    "Japanese": ("Aoi", "Ren", "Sora", "Yuki", "Hana"),
    "Hindi and Tamil": ("Anand", "Asha", "Arun", "Amal", "Veda", "Uma"),
    "Yoruba and Igbo": ("Ade", "Ayo", "Ola", "Chi", "Obi", "Ife"),
    "Swahili": ("Amani", "Baraka", "Imani", "Neema", "Upendo"),
    "Turkish": ("Ay", "Deniz", "Can", "Ece", "Nur", "Umut"),
    "Thai": ("Som", "Chai", "Nok", "Dao"),
    "Hebrew": ("Ben", "Bat", "Or", "Tal", "Adi"),
}

#: The society decision labels' words (``assets/catalogs/society/society-decision-action.v2.json``).
LABELS = ("sit, 12 m away", "talk with person 2, 8 m away")


def _saved(*names: str) -> list[SavedName]:
    return [SavedName(uuid.UUID(int=n + 1), "person", name) for n, name in enumerate(names)]


def test_the_catalog_holds_closed_class_words_each_with_its_class_and_why():
    words = [entry["word"] for entry in CATALOG["words"]]
    assert len(words) == len(set(words)) and set(words) == FUNCTION_WORDS
    for entry in CATALOG["words"]:
        assert entry["class"] in {"article", "determiner", "preposition", "conjunction"}, entry
        assert entry["reason"].strip(), entry
    assert {"the", "away", "and"} <= FUNCTION_WORDS
    # Words the first version held that are somebody's name, which a person may be called by.
    assert FUNCTION_WORDS.isdisjoint({"with", "from", "nor", "than", "into", "both", "few"})


#: The one catalog word that is also a name part: "the", Vietnamese "Thế" written without its
#: diacritic. It is skipped only where a saved name writes it in lowercase beside a capitalised
#: part, which a Vietnamese name does not (the "capitalised-The" case below).
DECLARED_EXCEPTIONS = {"the"}


@pytest.mark.parametrize("culture", sorted(NAME_PARTS))
def test_no_word_in_the_catalog_is_a_name_part_in_any_culture_here(culture):
    parts = {part.casefold() for part in NAME_PARTS[culture]}
    assert FUNCTION_WORDS & parts <= DECLARED_EXCEPTIONS, sorted(FUNCTION_WORDS & parts)


def test_the_declared_exception_says_why_in_the_catalog():
    (the,) = [entry for entry in CATALOG["words"] if entry["word"] in DECLARED_EXCEPTIONS]
    assert "Vietnamese" in the["reason"] and "Vietnamese" in CATALOG["note"]


#: A saved name, a text, and the text as it leaves.
WRITINGS = {
    "lowercase-the": (
        "Joe the Plumber",
        "Did Joe fix the sink? The plumber came, and Joe the Plumber left.",
        "Did [person A] fix the sink? The [person A] came, and [person A] left.",
    ),
    # Capitalised, "The" is a name part (a Vietnamese one written without its diacritic).
    "capitalised-The": (
        "Nguyen The Anh",
        "Is The Anh with the dog?",
        "Is [person A] [person A] with [person A] dog?",
    ),
    "Nor": (
        "Nor Aisyah Ahmad",
        "Nor Aisyah came, nor did anyone.",
        "[person A] [person A] came, [person A] did anyone.",
    ),
    "With": ("Tom With", "talk with person 2", "talk [person A] person 2"),
    # Written all in lowercase, the name says nothing about which part is no name: every part is.
    "all-lowercase": (
        "joe the plumber",
        "Did joe fix the sink?",
        "Did [person A] fix [person A] sink?",
    ),
}


@pytest.mark.parametrize("case", sorted(WRITINGS))
def test_only_a_lowercase_function_word_beside_a_capitalised_part_is_no_name(case):
    saved, text, sent = WRITINGS[case]
    assert redact_names(text, _saved(saved)).text == sent


def test_a_name_that_is_also_a_word_is_still_recognised_standing_alone():
    names = _saved("Will Smith", "May")
    redacted = redact_names("Will was there in May, and so was Smith.", names).text
    assert redacted == "[person A] was there in [person B], and so was [person A]."


#: Per workspace: the names saved, a request, what must leave unchanged in it, what must not
#: leave at all, and which decision labels leave as written.
WORKSPACES = {
    "written-as-no-name": (
        ("Joe the Plumber", "Will Smith", "Rita away"),
        "Was Joe with the plumber, and will Will come away?",
        (" the ", " with ", " away"),
        ("Joe", "plumber", "Will come"),
        LABELS,
    ),
    "written-as-names": (
        ("Nguyen The Anh", "Nor Aisyah Ahmad", "Tom With"),
        "Did The Anh and Nor Aisyah talk with Tom?",
        (" and ",),
        ("The", "Anh", "Nor", "Aisyah", " with ", "Tom"),
        ("sit, 12 m away",),
    ),
    "all-lowercase": (
        ("joe the plumber",),
        "Did joe fix the sink?",
        (),
        ("joe", " the "),
        LABELS,
    ),
}


@pytest.fixture(params=sorted(WORKSPACES))
def saved_in_workspace(request, named):
    """The fixture workspace with the case's people saved through the product's naming path."""
    repository, _, session, _ = named
    identity = IdentityRepository(repository.connection, repository.workspace_id)
    assertions = AssertionWriter(repository.connection, repository.workspace_id)
    names, *expected = WORKSPACES[request.param]
    for name in names:
        rename_entity(
            identity,
            assertions,
            entity_id=identity.entities.create(entity_class="person"),
            display_name=name,
            actor=session.actor,
        )
    return repository, expected


@pytest.mark.postgres
def test_the_call_sites_follow_the_saved_names_writing(saved_in_workspace):
    repository, (text, kept, withheld, labels) = saved_in_workspace
    names = RequestNames.read(repository.connection, repository.workspace_id)
    sent = names.sendable(text)
    assert all(word in sent for word in kept), sent
    assert not any(word in sent for word in withheld), sent
    assert [label for label in LABELS if names.sendable(label) == label] == list(labels)


@pytest.mark.postgres
def test_the_boundary_follows_the_saved_names_writing(saved_in_workspace):
    repository, (text, kept, withheld, labels) = saved_in_workspace
    client, transport = _client(policy=_policy(repository))
    client.chat(Role.STRUCTURED_EXTRACTION, _messages(text), prompt_version="v")
    sent = transport.requests[0]["payload"]["messages"][1]["content"]
    assert all(word in sent for word in kept), sent
    assert not any(word in sent for word in withheld), sent
    left_as_written = []
    for label in LABELS:
        client.chat(Role.STRUCTURED_EXTRACTION, _messages(label), prompt_version="v")
        if transport.requests[-1]["payload"]["messages"][1]["content"] == label:
            left_as_written.append(label)
    assert left_as_written == list(labels)
