"""The door's pure parts, checked without a database: secrets, bridges, the cursor, mappings, the
words rule and what one process tells itself.

Each expected value comes from the rule as the contract states it (``docs/door-contract.md``), not
from the code under test: a code's alphabet and length from Crockford's base32 and the 80 bits the
contract asks for, a refusal from the field the setting must state, a deadline's bound from the
decision contract itself, a cursor from what a bridge is owed, a mapping's refusal from the
profile's own fields, a share of held polls from the stated ceilings.
"""

from __future__ import annotations

import base64
import json
import uuid

import pytest
from exulanica.door import channel as channel_module
from exulanica.door.bridges import (
    BridgeNotAccepted,
    BridgeSettingRefused,
    load_bridge_directory,
)
from exulanica.door.channel import ChannelRefused, carried_home, sendable
from exulanica.door.credentials import (
    CHANNEL_CREDENTIAL_FORM,
    credential_sha256,
    format_invite_code,
    new_channel_credential,
    new_invite_code,
    normalise_invite_code,
)
from exulanica.door.crossings import Visits
from exulanica.door.grants import Grant, GrantRefused, Scope
from exulanica.door.mapping import MappingRefused, check_mapping, check_reads
from exulanica.door.notices import ANSWERS_REMEMBERED, HeldPolls, Hellos, Notices
from exulanica.door.protocol import Cursor, InvalidCursor, declared_fault, words_fault
from exulanica.world.society_decision_contract import decision_contract

import door_support

CROCKFORD = set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")


# -- secrets ---------------------------------------------------------------------------------


def test_an_invite_code_carries_eighty_bits_in_four_groups_of_four():
    code = new_invite_code()
    assert len(code) == 16 and set(code) <= CROCKFORD  # 16 digits of 5 bits
    written = format_invite_code(code)
    assert written.count("-") == 3 and [len(group) for group in written.split("-")] == [4] * 4
    assert normalise_invite_code(written) == code


def test_typing_an_invite_forgives_what_crockford_forgives_and_nothing_else():
    assert normalise_invite_code("abcd-efgh-jkmn-pqrs") == "ABCDEFGHJKMNPQRS"
    assert normalise_invite_code("0OIL 1111 2222 3333") == "0011111122223333"
    for typed in (
        "ABCD-EFGH-JKMN-PQR",
        "ABCD-EFGH-JKMN-PQRSU",
        "ABCD-EFGH-JKMN-PQR!",
        "",
        "U" * 16,
    ):
        assert normalise_invite_code(typed) is None, typed
    assert normalise_invite_code("A" * 41) is None


def test_a_channel_credential_is_two_hundred_fifty_six_bits_and_stored_by_its_digest():
    credential = new_channel_credential()
    padded = credential + "=" * (-len(credential) % 4)
    assert len(base64.urlsafe_b64decode(padded)) == 32
    assert credential_sha256(credential) != credential and len(credential_sha256(credential)) == 64
    assert new_channel_credential() != credential
    # 32 bytes are 43 characters of URL-safe base64 without padding, and nothing else is looked up.
    assert len(credential) == 43 and CHANNEL_CREDENTIAL_FORM.fullmatch(credential)
    for other in (credential[:-1], credential + "A", credential[:-1] + "=", "x" * 43 + " "):
        assert CHANNEL_CREDENTIAL_FORM.fullmatch(other) is None


# -- bridges ---------------------------------------------------------------------------------


def test_no_setting_admits_no_bridge_and_a_declared_one_is_matched_by_its_own_credential():
    assert len(load_bridge_directory({})) == 0
    directory = door_support.bridges()
    assert directory.for_credential(door_support.BRIDGE_CREDENTIAL).key == "test-bridge"
    assert directory.for_credential(door_support.OTHER_CREDENTIAL).key == "other-bridge"
    for presented in (None, "", "not-a-declared-bridge-credential-at-all", "x" * 300):
        with pytest.raises(BridgeNotAccepted):
            directory.for_credential(presented)


def test_an_unlisted_bridge_is_offered_only_to_the_workspaces_it_names():
    named = uuid.uuid4()
    directory = door_support.bridges(listed=False, workspaces=[str(named)])
    assert [b.key for b in directory.offered_to(named)] == ["other-bridge", "test-bridge"]
    assert [b.key for b in directory.offered_to(uuid.uuid4())] == ["other-bridge"]


_CEILING = decision_contract().value("decision_deadline_ms")


@pytest.mark.parametrize(
    ("change", "says"),
    [
        (lambda entry: entry.pop("credential_sha256"), "SHA-256"),
        (lambda entry: entry.update(credential_sha256="a-plain-credential"), "SHA-256"),
        (lambda entry: entry.pop("run_by"), "exactly the bridge fields"),
        (lambda entry: entry.update(run_by="anyone"), "run_by server or owner"),
        (lambda entry: entry.update(run_by="owner"), "has no bridge credential"),
        (lambda entry: entry.pop("ai"), "exactly the bridge fields"),
        (lambda entry: entry.update(ai="yes"), "ai true or false"),
        (lambda entry: entry.update(hold_seconds=0), "holds a poll 1 to 25"),
        (lambda entry: entry.update(hold_seconds=26), "holds a poll 1 to 25"),
        (lambda entry: entry.update(hold_seconds=15.0), "holds a poll 1 to 25"),
        (lambda entry: entry.update(deadline_ms=0), f"1 to {_CEILING} ms"),
        (lambda entry: entry.update(deadline_ms=_CEILING + 1), f"1 to {_CEILING} ms"),
        (lambda entry: entry.update(bridge="Upper"), "bridge key"),
        (lambda entry: entry.update(mapping_sha256=[]), "mapping_sha256"),
        (lambda entry: entry.update(adapter_versions=["has space"]), "adapter_versions"),
        (lambda entry: entry.update(adapter_versions=["0.1.0-beta"]), "adapter_versions"),
        (lambda entry: entry.update(adapter_versions=["alex.smith"]), "adapter_versions"),
        (lambda entry: entry.update(listed="yes"), "listed"),
        (lambda entry: entry.update(listed=False), "names no workspace"),
        (lambda entry: entry.update(label=""), "label"),
        (lambda entry: entry.update(surprise=True), "exactly the bridge fields"),
    ],
)
def test_a_malformed_bridge_setting_is_refused_by_name(change, says):
    entries = json.loads(door_support.bridges_setting())
    change(entries[0])
    with pytest.raises(BridgeSettingRefused, match=says):
        load_bridge_directory({"EXULANICA_DOOR_BRIDGES": json.dumps(entries)})


def test_a_bridge_states_its_own_hold_and_deadline_within_the_decision_contract():
    assert door_support.bridges().get("test-bridge").hold_seconds == 15
    assert door_support.bridges().get("test-bridge").deadline_ms == 3000
    declared = door_support.bridges(hold_seconds=25, deadline_ms=_CEILING).get("test-bridge")
    assert (declared.hold_seconds, declared.deadline_ms) == (25, _CEILING)


def test_who_runs_a_bridge_decides_how_its_grants_open():
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    directory = door_support.bridges(owner_workspaces=[str(mine)])
    listed_server = directory.get("other-bridge")
    owned = directory.get("owned-bridge")
    # A program its owner runs: no bridge credential, no invites, a credential for its own owner.
    assert owned.credential_sha256 is None and not owned.takes_invites()
    assert owned.direct_credentials_for(mine) and not owned.direct_credentials_for(theirs)
    # A listed server serves strangers: its grants open by invites only.
    assert listed_server.takes_invites() and not listed_server.direct_credentials_for(mine)
    # A server declared for one workspace alone may also be given its credential directly.
    unlisted = door_support.bridges(listed=False, workspaces=[str(mine)]).get("test-bridge")
    assert unlisted.direct_credentials_for(mine) and not unlisted.direct_credentials_for(theirs)
    assert (owned.ai, listed_server.ai) == (True, False)


def test_two_bridges_may_not_share_a_key_or_a_credential():
    entries = json.loads(door_support.bridges_setting())
    with pytest.raises(BridgeSettingRefused, match="declared twice"):
        load_bridge_directory(
            {"EXULANICA_DOOR_BRIDGES": json.dumps([entries[0], dict(entries[0])])}
        )
    entries[1]["credential_sha256"] = entries[0]["credential_sha256"]
    with pytest.raises(BridgeSettingRefused, match="shares a credential"):
        load_bridge_directory({"EXULANICA_DOOR_BRIDGES": json.dumps(entries)})


# -- the cursor ------------------------------------------------------------------------------


def test_a_cursor_round_trips_and_a_first_poll_starts_from_nothing():
    assert Cursor.decode(None) == Cursor() == Cursor.decode("")
    cursor = Cursor(ask=12, outcome=9, grant=2, ended=True)
    assert Cursor.decode(cursor.encode()) == cursor


@pytest.mark.parametrize(
    ("written", "read"),
    [
        # Cursors as a door without crossings wrote them (the first version), held by a bridge
        # across the upgrade: {"ask":7,"ended":false,"grant":2,"outcome":6,"v":1} and its end.
        (
            "eyJhc2siOjcsImVuZGVkIjpmYWxzZSwiZ3JhbnQiOjIsIm91dGNvbWUiOjYsInYiOjF9",
            Cursor(ask=7, outcome=6, grant=2, crossed=0, departed=0, ended=False),
        ),
        (
            "eyJhc2siOjcsImVuZGVkIjp0cnVlLCJncmFudCI6Mywib3V0Y29tZSI6NywidiI6MX0",
            Cursor(ask=7, outcome=7, grant=3, crossed=0, departed=0, ended=True),
        ),
    ],
)
def test_a_cursor_written_before_crossings_reads_on_as_told_no_crossing(written, read):
    assert Cursor.decode(written) == read
    # What the door writes next is its newest cursor, which reads back as itself.
    assert read.encode() != written
    assert Cursor.decode(read.encode()) == read


@pytest.mark.parametrize(
    ("written", "read"),
    [
        # Cursors as the door wrote them before lines were sent (package 2's second version), held
        # by a bridge across the upgrade:
        # {"ask":7,"crossed":3,"departed":1,"ended":false,"grant":2,"outcome":6,"v":2} and an end.
        (
            "eyJhc2siOjcsImNyb3NzZWQiOjMsImRlcGFydGVkIjoxLCJlbmRlZCI6ZmFsc2UsImdyYW50IjoyLCJvdXRj"
            "b21lIjo2LCJ2IjoyfQ",
            Cursor(ask=7, outcome=6, grant=2, crossed=3, departed=1, said=0, ended=False),
        ),
        (
            "eyJhc2siOjksImNyb3NzZWQiOjQsImRlcGFydGVkIjo0LCJlbmRlZCI6dHJ1ZSwiZ3JhbnQiOjMsIm91dGNv"
            "bWUiOjksInYiOjJ9",
            Cursor(ask=9, outcome=9, grant=3, crossed=4, departed=4, said=0, ended=True),
        ),
    ],
)
def test_a_cursor_written_before_lines_reads_on_as_told_nothing_said(written, read):
    assert Cursor.decode(written) == read
    assert read.encode() != written
    assert Cursor.decode(read.encode()) == read
    # The newest cursor counts the lines told too.
    told = Cursor(ask=1, outcome=1, said=5)
    assert Cursor.decode(told.encode()).said == 5


@pytest.mark.parametrize(
    "text",
    [
        "not base64 at all!",
        base64.urlsafe_b64encode(b'{"v":1}').decode().rstrip("="),
        base64.urlsafe_b64encode(b'{"ask":1,"ended":false,"grant":0,"outcome":2,"v":1}')
        .decode()
        .rstrip("="),  # an outcome of an ask it has not seen
        base64.urlsafe_b64encode(b'{"ask":1.0,"ended":false,"grant":0,"outcome":0,"v":1}')
        .decode()
        .rstrip("="),
        base64.urlsafe_b64encode(b'{"ask": 1, "ended": false, "grant": 0, "outcome": 0, "v": 1}')
        .decode()
        .rstrip("="),  # not this door's own writing of it
        base64.urlsafe_b64encode(b'{"ask":1,"ended":false,"grant":0,"outcome":0,"v":true}')
        .decode()
        .rstrip("="),  # a first cursor's version written as a truth value
        base64.urlsafe_b64encode(
            b'{"ask":1,"crossed":0,"departed":0,"ended":false,"grant":0,"outcome":0,"v":1}'
        )
        .decode()
        .rstrip("="),  # the second cursor's fields under the first's version
        base64.urlsafe_b64encode(b'{"ask":1,"ended":false,"grant":0,"outcome":0,"v":2}')
        .decode()
        .rstrip("="),  # the first cursor's fields under the second's version
        base64.urlsafe_b64encode(
            b'{"ask":1,"crossed":0,"departed":0,"ended":false,"grant":0,"outcome":0,"said":0,"v":2}'
        )
        .decode()
        .rstrip("="),  # the third cursor's fields under the second's version
        base64.urlsafe_b64encode(
            b'{"ask":1,"crossed":0,"departed":0,"ended":false,"grant":0,"outcome":0,"v":3}'
        )
        .decode()
        .rstrip("="),  # the second cursor's fields under the third's version
        base64.urlsafe_b64encode(
            b'{"ask":1,"crossed":0,"departed":0,"ended":false,"grant":0,"outcome":0,"said":0,"v":4}'
        )
        .decode()
        .rstrip("="),  # a version this door never wrote
        "A" * 201,
    ],
)
def test_a_cursor_this_door_did_not_write_is_refused(text):
    with pytest.raises(InvalidCursor):
        Cursor.decode(text)


# -- mappings --------------------------------------------------------------------------------


def test_the_test_mapping_is_complete_for_what_its_adapter_reads():
    checked = check_mapping(door_support.mapping())
    assert check_reads(checked, door_support.READS) == frozenset(door_support.READS)


def test_an_adapter_that_reads_a_field_its_mapping_leaves_out_is_refused_by_name():
    with pytest.raises(MappingRefused, match="does not account for: hunger"):
        check_reads(check_mapping(door_support.mapping()), [*door_support.READS, "hunger"])


def _without_name(document):
    document["never_crosses"] = [
        entry for entry in document["never_crosses"] if entry["field"] != "player name"
    ]


def _approximate_silently(document):
    del document["items"][1]["reason_words"]


def _exact_with_a_reason(document):
    document["items"][0]["reason_words"] = "it is the same thing"


def _a_second_sword_travelling_out(document):
    document["items"].append({**document["items"][0], "game_item": "test:old_sword"})


def _more_kinds_travelling_out_than_an_arrival_names(document):
    document["items"] += [
        {
            **document["items"][0],
            "game_item": f"test:thing_{n}",
            "kind": {"key": f"kind_{n}", "version": 1},
        }
        for n in range(63)
    ]


def _nested(depth):
    value: object = "bottom"
    for _ in range(depth):
        value = {"down": value}
    return value


@pytest.mark.parametrize(
    ("change", "says"),
    [
        (_without_name, "player name"),
        (_approximate_silently, "reason_words exactly when it is approximated"),
        (_exact_with_a_reason, "reason_words exactly when it is approximated"),
        (_a_second_sword_travelling_out, "travelling out, by kind"),
        (_more_kinds_travelling_out_than_an_arrival_names, "at most 64 items travelling out"),
        (lambda document: document.update(profile="other/v1"), "profile"),
        (lambda document: document.update(extra=1), "states exactly"),
        (lambda document: document["visitors"][0]["looks"][0].update(look="a.png"), "sha256"),
        (
            lambda document: document["visitors"][0]["looks"][0].update(
                look={"look": "blocky-traveller", "version": 1, "sha256": "0" * 64}
            ),
            "sha256:<digest>",
        ),
        (lambda document: document["items"].append(dict(document["items"][0])), "once"),
        (lambda document: document["items"][0].update(ways="sideways"), "in, out or both"),
        (lambda document: document["visitors"][0]["kind"].update(version=0), "kind"),
        (lambda document: document["visitors"][0].pop("outcome"), "states exactly"),
        (lambda document: document["actions"][0].pop("words"), "states exactly"),
        (lambda document: document["never_crosses"][1].pop("reason_words"), "states exactly"),
        (lambda document: document.update(version=1.0), "fractional"),
        (lambda document: document["items"][0]["kind"].update(version=1.5), "fractional"),
        (lambda document: document["game"].update(content=None), "fractional number or null"),
        (lambda document: document["game"].update(content=_nested(9)), "nests at most 8"),
        (lambda document: document["items"][0].update(words="a\u200bsword"), "separator"),
        (lambda document: document["items"][0].update(words=" a sword"), "no white space"),
        (lambda document: document["items"][0].update(words="x" * 201), "1 to 200 code points"),
        (lambda document: document["actions"][0].update(ability="Say Loud"), "ability"),
    ],
)
def test_a_mapping_that_breaks_its_profile_is_refused_by_name(change, says):
    document = door_support.mapping()
    change(document)
    with pytest.raises(MappingRefused, match=says):
        check_mapping(document)


def test_the_second_mapping_profile_names_a_look_by_the_library_s_reference():
    document = door_support.mapping_v2()
    assert check_mapping(document) is document
    # Each profile names a look its own way, and only its own way.
    document["visitors"][0]["looks"][0]["look"] = "sha256:" + "0" * 64
    with pytest.raises(MappingRefused, match="shipped look by its key"):
        check_mapping(document)
    later = door_support.mapping_v2()
    later["visitors"][0]["looks"][0]["look"]["version"] = 0
    with pytest.raises(MappingRefused, match="shipped look by its key"):
        check_mapping(later)
    other = door_support.mapping()
    other["profile"] = "exulanica.bridge-mapping/v3"
    with pytest.raises(MappingRefused, match="profile is one of"):
        check_mapping(other)


def test_a_program_that_brings_no_visitor_needs_none_in_its_mapping():
    document = door_support.mapping()
    document["visitors"] = []
    # Nor a player's name to leave behind: it brings nobody with one.
    document["never_crosses"] = [
        entry for entry in document["never_crosses"] if entry["field"] != "player name"
    ]
    reads = [field for field in door_support.READS if field not in ("player", "player name")]
    assert check_reads(check_mapping(document), reads) == frozenset(reads)


def test_a_game_names_its_actions_with_its_own_identifiers_and_items_travel_in_alone():
    document = door_support.mapping()
    # A namespaced action id, as games write them, is one grammar for every game.
    document["actions"][0]["game_action"] = "Default:Chat"
    # Two game items may become one kind on the way in; only one of that kind travels out.
    document["items"].append({**document["items"][0], "game_item": "test:old_sword", "ways": "in"})
    assert check_mapping(document) is document


# -- the words rule --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "fault"),
    [
        ("A torch, which arrives as a lantern", None),
        ("Скаут говорит", None),
        ("", "1 to 40 code points"),
        ("x" * 41, "1 to 40 code points"),
        (" padded", "no white space at either end"),
        ("e\u0301", "normal form C"),
        ("a\nb", "no control, format or separator"),
        ("a\u200eb", "no control, format or separator"),
        ("a\ue000b", "no control, format or separator"),
        ("a\u2028b", "no control, format or separator"),
        (12, "a line is text"),
    ],
)
def test_text_a_person_reads_meets_the_line_rule(text, fault):
    found = words_fault(text, maximum=40)
    assert (found is None) if fault is None else (fault in found), found


@pytest.mark.parametrize(
    ("text", "slash", "allowed"),
    [
        ("Scout", False, True),
        ("Acme & Sons (Ltd.)", False, True),
        ("हिन्दी", False, True),
        ("Qwen/Qwen3-235B-A22B-Instruct-2507", True, True),
        ("Qwen/Qwen3", False, False),
        ("see acme.ai", False, False),
        ("see \uff45\uff58\uff41\uff4d\uff50\uff4c\uff45.\uff43\uff4f\uff4d", False, False),
        ("\u043f\u0440\u0438\u043c\u0435\u0440.\u0440\u0444", False, False),
        ("at 10.0.0.1", False, False),
        ("meta-llama/Llama-3.1-8B", True, True),
        ("Mr. Smith", False, True),
        ("see x\u0301.com", False, False),
        ("mail me@there", False, False),
        ("https x", False, True),
        ("https://x", False, False),
        ("a;b", False, False),
    ],
)
def test_a_program_declares_itself_in_allowed_words_only(text, slash, allowed):
    assert (declared_fault(text, maximum=60, slash=slash) is None) is allowed


# -- what one process tells itself -----------------------------------------------------------


def test_held_polls_are_shared_by_workspace_and_by_bridge():
    polls = HeldPolls(maximum=8, per_workspace=2)
    one, two = uuid.uuid4(), uuid.uuid4()
    assert polls.per_bridge == 4
    oldest = uuid.uuid4()
    first = polls.hold(oldest, one, "a")
    assert first is not None and polls.hold(uuid.uuid4(), one, "a") is not None
    # A third poll of the same workspace waits for one of its own to end, whatever the bridge.
    assert polls.hold(uuid.uuid4(), one, "b") is None
    assert polls.hold(uuid.uuid4(), two, "a") is not None
    assert polls.hold(uuid.uuid4(), uuid.uuid4(), "a") is not None
    # Four polls of bridge "a" are half the ceiling. A fifth, from a workspace holding none there,
    # takes the place of the oldest poll of the workspace holding two; then every workspace there
    # holds one, and a sixth waits. Another bridge does not.
    assert polls.hold(uuid.uuid4(), uuid.uuid4(), "a") is not None
    assert not polls.holds(oldest, first)
    assert polls.hold(uuid.uuid4(), uuid.uuid4(), "a") is None
    assert polls.hold(uuid.uuid4(), uuid.uuid4(), "b") is not None


def test_a_full_process_gives_a_workspace_holding_fewer_the_place_of_one_holding_the_most():
    polls = HeldPolls(maximum=4, per_workspace=4)
    many, few = uuid.uuid4(), uuid.uuid4()
    held = [
        (grant, polls.hold(grant, many, bridge))
        for grant, bridge in (
            (uuid.uuid4(), "a"),
            (uuid.uuid4(), "a"),
            (uuid.uuid4(), "b"),
            (uuid.uuid4(), "b"),
        )
    ]
    assert all(token is not None for _grant, token in held)
    # The process is full. A workspace holding none takes the oldest place of the one holding four,
    # and then another, while that one still holds two more than it would.
    assert polls.hold(uuid.uuid4(), few, "c") is not None
    assert [polls.holds(grant, token) for grant, token in held] == [False, True, True, True]
    assert polls.hold(uuid.uuid4(), few, "c") is not None
    assert [polls.holds(grant, token) for grant, token in held] == [False, False, True, True]
    # Two and two: neither takes a place from the other, and the poll that lost its place waits.
    assert polls.hold(uuid.uuid4(), few, "d") is None
    assert polls.hold(held[0][0], many, "a") is None


def test_a_grant_polling_again_ends_its_last_poll_without_needing_room():
    polls = HeldPolls(maximum=1, per_workspace=1)
    grant, workspace = uuid.uuid4(), uuid.uuid4()
    old = polls.hold(grant, workspace, "a")
    new = polls.hold(grant, workspace, "a")
    assert old is not None and new is not None and old != new
    assert not polls.holds(grant, old) and polls.holds(grant, new)
    polls.release(grant, old)  # the ended poll's release leaves the new one held
    assert polls.holds(grant, new)


def test_six_hellos_a_minute_then_none_until_the_minute_has_passed():
    clock = [1000.0]
    hellos = Hellos(monotonic=lambda: clock[0])
    grant = uuid.uuid4()
    assert all(hellos.admit(grant) for _ in range(6))
    assert not hellos.admit(grant) and hellos.admit(uuid.uuid4())
    clock[0] += 60.0
    assert hellos.admit(grant)


def test_a_process_remembers_a_bounded_number_of_answers():
    notices = Notices()
    first = uuid.uuid4()
    notices.answered(first)
    assert notices.wait_for_answer(first, 0)
    for _ in range(ANSWERS_REMEMBERED):
        notices.answered(uuid.uuid4())
    assert not notices.wait_for_answer(first, 0)


def test_a_grant_s_visitors_are_decided_by_their_program_unless_it_says_the_world():
    version = str(uuid.uuid4())
    program = Scope(visitors_maximum=1, kinds=("player",), version_id=version)
    world = Scope(
        visitors_maximum=1, kinds=("player",), version_id=version, visitors_decided_by="world"
    )
    # A program grant's revision keeps the bytes it had before the field existed; a world grant
    # states it; a revision stating nothing reads as its program's.
    assert "visitors_decided_by" not in program.document()
    assert world.document()["visitors_decided_by"] == "world"
    assert Scope.from_document(program.document()) == program
    assert Scope.from_document(world.document()) == world
    with pytest.raises(GrantRefused, match="invalid_scope"):
        Scope(visitors_maximum=1, kinds=("player",), version_id=version, visitors_decided_by="x")
    things = Scope(things=(str(uuid.uuid4()),), version_id=version, visitors_decided_by="world")
    with pytest.raises(GrantRefused, match="only for visitors a grant lets in"):
        things.check_issue()


def test_an_arrival_is_named_by_a_random_id_whoever_calls_the_door():
    """The route takes only a version 4 arrival id; the crossings refuse any other by name for any
    other caller, before anything is read or written (no connection is opened here)."""
    grant_id = uuid.uuid4()
    grant = Grant(
        grant_id=grant_id,
        world_id="world",
        bridge="test-bridge",
        grant_seq=1,
        state="active",
        scope=Scope(visitors_maximum=1, kinds=("player",), version_id=str(uuid.uuid4())),
        mapping_sha256=(),
        expires_at=None,  # type: ignore[arg-type]
        issued_at=None,  # type: ignore[arg-type]
    )
    visits = Visits(None, uuid.uuid4(), grant, uuid.uuid4())  # type: ignore[arg-type]
    departure = uuid.uuid5(uuid.UUID("8f1d6a52-3c47-5e09-b4a8-1e7c2d90f6b3"), f"{grant_id}:x")
    with pytest.raises(ChannelRefused) as refused:
        visits.arrive(
            arrival_id=departure,
            game_type="player",
            look_key="otherwise",
            carried=[],
            presence=None,
            mapping={},
            reads=[],
        )
    assert (refused.value.code, refused.value.status) == ("arrival_id_not_random", 422)


def test_a_thing_carried_home_leaves_as_its_own_item_and_a_world_thing_only_when_allowed():
    sword = {"id": "s", "kind": {"kind": "sword", "version": 1, "sha256": "0" * 64}}
    lantern = {"id": "l", "kind": {"kind": "lantern", "version": 1, "sha256": "1" * 64}}
    came_as = {"s": "test:sword"}
    outbound = {"sword": "test:sword", "lantern": "test:torch"}
    allowed = carried_home([sword, lantern], came_as, outbound, may_carry_out=True)
    held_back = carried_home([sword, lantern], came_as, outbound, may_carry_out=False)
    assert [(each["thing_id"], each["game_item"]) for each in allowed] == [
        ("s", "test:sword"),
        ("l", "test:torch"),
    ]
    # Its own sword goes home whatever the grant says; the world's lantern becomes nothing.
    assert [(each["thing_id"], each["game_item"]) for each in held_back] == [
        ("s", "test:sword"),
        ("l", None),
    ]


# -- what an asked frame sends, as it is sent ---------------------------------------------------


def _context(heard: list[tuple[str, str, int]], said: list[tuple[str, str | None, int]]) -> dict:
    """A society of things' context with lines heard ``(from, line, tick)`` and said ``(to, line,
    minutes_ago)``, as the decision contract writes them."""
    return {
        "engine": "exulanica-society/v7",
        "options": [{"label": "wait here a minute"}],
        "heard": [
            {"from": who, "to_you": True, "line": line, "tick": tick, "minutes_ago": 30 - tick}
            for who, line, tick in heard
        ],
        "said": [{"to": to, "line": line, "minutes_ago": ago} for to, line, ago in said],
    }


def test_lines_from_before_a_grant_s_first_ask_are_not_sent():
    context = _context(
        [
            ("the knight (person 2)", "Before.", 9),
            ("the knight (person 2)", "That minute.", 12),
            ("the knight (person 2)", "After.", 13),
        ],
        [(None, "Long ago.", 25), (None, "That minute.", 18), (None, "Lately.", 3)],
    )
    # Asked at minute 30, the grant's first ask made in minute 12: lines heard at 9 and 12, and
    # lines said 25 and 18 minutes before (minutes 5 and 12), are not sent, since a line of the
    # first ask's minute may come from before the grant; a line heard at 13 and one said at 27 are.
    kept = channel_module._lines_since(context, 12, 30)
    assert [line["line"] for line in kept["heard"]] == ["After."]
    assert [line["line"] for line in kept["said"]] == ["Lately."]
    assert channel_module._lines_since(context, None, 30) is context


def _host_screen(names, context):
    """The decision host's own rule for an outside request, at reservation."""
    from exulanica.api.decision_host import outside_context_sendable, without_named_lines

    withheld = without_named_lines(names)(dict(context))
    return withheld if outside_context_sendable(names, withheld) else None


@pytest.mark.parametrize(
    "context",
    [
        _context([("the knight (person 2)", "Good day.", 3)], [(None, "Hello.", 1)]),
        _context([("the knight (person 2)", "Is Marisol here?", 3)], [(None, "Hello.", 1)]),
        _context([("Marisol", "Good day.", 3)], []),
        _context([], [("Marisol", "Hello.", 1), (None, "Fine.", 2)]),
        {**_context([], []), "options": [{"label": "say something to Marisol"}]},
    ],
    ids=["clean", "heard-line", "heard-from", "said-to", "option"],
)
def test_the_door_screens_an_asked_context_as_the_host_screened_it(context):
    from exulanica.epistemics.saved_names import SavedName, recogniser

    names = (SavedName(uuid.UUID(int=7), "person", "Marisol Vega"),)
    spans = recogniser(names)

    def carries(texts: list[str]) -> bool:
        return any(spans(text) for text in texts)

    assert sendable(context, carries) == _host_screen(names, context)


def test_a_saved_name_written_as_a_placeholder_is_still_screened():
    from exulanica.epistemics.saved_names import SavedName, recogniser

    spans = recogniser((SavedName(uuid.UUID(int=7), "person", "Maria Vega"),))
    # The product's own recogniser leaves a placeholder's words alone; the door opens them first.
    assert spans("Ask [person MARIA] about it.") == []
    assert spans(channel_module._bare("Ask [person MARIA] about it."))


def test_a_held_poll_keeps_holding_when_nothing_or_only_its_line_place_moved():
    from exulanica.api.routes.door import _moved_past_lines

    before = Cursor(ask=3, outcome=3, said=5)
    assert not _moved_past_lines(before, Cursor(ask=3, outcome=3, said=9))
    assert not _moved_past_lines(before, before)
    assert _moved_past_lines(before, Cursor(ask=4, outcome=3, said=9))
    assert _moved_past_lines(before, Cursor(ask=3, outcome=3, said=5, ended=True))
