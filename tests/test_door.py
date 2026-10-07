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
from exulanica.door.bridges import (
    BridgeNotAccepted,
    BridgeSettingRefused,
    load_bridge_directory,
)
from exulanica.door.credentials import (
    CHANNEL_CREDENTIAL_FORM,
    credential_sha256,
    format_invite_code,
    new_channel_credential,
    new_invite_code,
    normalise_invite_code,
)
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
        (lambda document: document.update(profile="other/v1"), "profile"),
        (lambda document: document.update(extra=1), "states exactly"),
        (lambda document: document["visitors"][0]["looks"][0].update(look="a.png"), "sha256"),
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
