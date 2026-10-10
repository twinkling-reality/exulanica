"""Every prompt the Companion sends is pinned to the version its output is recorded under.

Each prompt version is an input to the response cache key and is stored with what the prompt
produced: an answer's execution block names ``selection-9``, a world style proposal names
``proposal-2``, an environment proposal names ``environment-proposal-1``. A prompt edited without
its version moving would file new output under a prompt that no longer exists, and would serve a
cached answer composed under the old wording. So the bytes of every prompt text are hashed here,
per version: editing one fails this test until the version is bumped and its digest recorded.
"""

from __future__ import annotations

import hashlib

import pytest
from exulanica.canonical import canonical_json
from exulanica.selection import action_plan, environment_proposal, prompts, proposal

#: version -> SHA-256 of the canonical JSON of that family's prompt texts, as ``_texts`` reads them.
PINNED = {
    "selection-8": "127e11c1d78fa9bed8f222ab06a087a6d8ee7388f5751f32949a1a41df83ea20",
    # `selection-9` adds the society composer's prompt to the family's texts.
    "selection-9": "9200a1322581ab6df098c87531dae7505640b0ca19a8747cb66e90d0d4f6fb55",
    # The same texts: `selection-10` sends the planner's form with its lists last.
    "selection-10": "9200a1322581ab6df098c87531dae7505640b0ca19a8747cb66e90d0d4f6fb55",
    "proposal-2": "7c6b2cb2633943e0858cd7064e97bda1dcfa42cd9c520ed6c9f901f9b0d61665",
    # The same texts: `proposal-3` changed the draft schema's construction and no prompt.
    "proposal-3": "7c6b2cb2633943e0858cd7064e97bda1dcfa42cd9c520ed6c9f901f9b0d61665",
    "proposal-4": "c5d95ac33e52e9a22fe41d4056788b18a05588260506499ac91a2792b4e005ae",
    # The same texts: `proposal-5` sends the draft with its references list last.
    "proposal-5": "c5d95ac33e52e9a22fe41d4056788b18a05588260506499ac91a2792b4e005ae",
    "environment-proposal-1": "88314630219bea7f6571a54fff583920ac765581a25efa581e20f4b04e9e0a92",
    # The Companion's world actions: its five-way classifier and the world-edit drafter.
    "action-plan-1": "a9c3708ef441cbeeae00b2972628d89de75dc787aebf0a37f0cf658b8273da88",
    # `action-plan-2` adds the simulation drafter's prompt; the other two texts are unchanged.
    "action-plan-2": "f6d753b9d112b6b61f29c787fcea5beb65807248f19c66aee7d7a6eb63d4e6c9",
    # `action-plan-3`: the world-edit drafter's step is an operation then one options list, named
    # once each, written on one line; the classifier and simulation texts are unchanged.
    "action-plan-3": "aa66c6c57167604ee4824c79c7222bf65f3dd8828ba2732c0839db7aa61cd00e",
    # `action-plan-5`: the world-edit drafter is no longer asked to write the form on one line.
    "action-plan-5": "ea26b399ae2499732432cd0f279aec2ae30dc0e39dc32d39c801c6fd4b14d9d0",
    # `action-plan-6`: things added by their kind and beings asked to go to or use a place; the
    # classifier counts asking a being as a world edit; up to eight steps of four options each.
    "action-plan-6": "332b30f3cad261a8376b043c0589f33c3c155a5a98f485e4195202db454417c6",
    # `action-plan-7`: a being asked to pick a thing up, put it down, give it or take it; the
    # classifier counts those as world edits too.
    "action-plan-7": "3af61e470e542d4984c38a2b03ce48bd505a0c2ed4152a0215e01d0a628cc849",
    # `action-plan-8`: a step's options name what it goes beside or where it goes as well as what
    # it adds or asks; a walk or a use names the place; describing words are no step of their own.
    "action-plan-8": "d68afb2a32f23689d55f39037076128559150a7b2ac07da58259363ae1d83bbd",
    # `action-plan-9`: what stands in the world is named by its listed label, not its kind; a visit
    # to a place, or doing what else it is for, is a use, and a walk only walks there.
    "action-plan-9": "0c6c4c32250b7f4bc214e347777ae8b481d2795dbab897e243702e9942319ed4",
    # `action-plan-10`: the world-edit drafter may ask for new pieces of how kinds of thing look
    # (`request_pieces`), and the classifier counts that as a world edit.
    "action-plan-10": "54f46a55581c758b1f8f76878d845a275b2f36dae751de645ec791a5f5bbcf3c",
    # `action-plan-11`: the world-edit drafter may say who decides for a being or a group of them
    # (`choose_mind`: a listed model or their own routine), and the classifier counts that as a
    # world edit.
    "action-plan-11": "0e116a6d36677840f24714416717933f54ec14d1113a3b6a7a78f4c6534c941b",
    # `action-plan-12`: a move or a removal may name a placed thing; the person may start to play
    # a listed being or give it back (`play_being`, `give_back`); the simulation drafter may send
    # everyone away or bring them back; the classifier counts playing a being as a world edit.
    "action-plan-12": "0d41046441d43eb2ef3e290e68a5298a9484ae605fecd348930cd892ef0fd64d",
    # The appearance drafter for a design choice drawn from no evidence; its own family, so the
    # evidence drafter's texts and `proposal-4` are untouched.
    "proposal-authored-1": "7b840134c24bc8152ab423f0665362b1d37bdd3cfb9b96cf208cfc6a46308d9a",
}


def _texts() -> dict[str, tuple[str, dict[str, str]]]:
    """Each family's version and its prompt texts, read from the modules that hold them."""
    return {
        "selection": (
            prompts.PROMPT_VERSION,
            {
                "planner_system": prompts._PLANNER_SYSTEM,
                "composer_system": prompts._COMPOSER_SYSTEM,
                "empty_catalogue": prompts._EMPTY_CATALOGUE,
                "society_composer_system": prompts._SOCIETY_COMPOSER_SYSTEM,
            },
        ),
        "proposal": (
            proposal.PROMPT_VERSION,
            {
                "classifier_system": proposal._CLASSIFIER_SYSTEM,
                "drafter_system": proposal._DRAFTER_SYSTEM,
            },
        ),
        "environment-proposal": (
            environment_proposal.ENVIRONMENT_PROMPT_VERSION,
            {"system": environment_proposal._SYSTEM},
        ),
        "action-plan": (
            action_plan.ACTION_PROMPT_VERSION,
            {
                "classifier_system": action_plan._CLASSIFIER_SYSTEM,
                "world_edit_system": action_plan._WORLD_EDIT_SYSTEM,
                "simulation_system": action_plan._SIMULATION_SYSTEM,
            },
        ),
        "proposal-authored": (
            proposal.AUTHORED_PROMPT_VERSION,
            {"drafter_system": proposal._AUTHORED_DRAFTER_SYSTEM},
        ),
    }


@pytest.mark.parametrize("family", sorted(_texts()))
def test_each_prompt_is_the_one_its_version_names(family):
    version, texts = _texts()[family]
    digest = hashlib.sha256(canonical_json(texts)).hexdigest()
    assert version in PINNED, f"{version} has no pinned digest; record {digest} for it"
    assert digest == PINNED[version], (
        f"the {family} prompts changed under {version}: bump the version and pin {digest}"
    )
