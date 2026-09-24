"""Every prompt the Companion sends is pinned to the version its output is recorded under.

Each prompt version is an input to the response cache key and is stored with what the prompt
produced: an answer's execution block names ``selection-8``, a world style proposal names
``proposal-2``, an environment proposal names ``environment-proposal-1``. A prompt edited without
its version moving would file new output under a prompt that no longer exists, and would serve a
cached answer composed under the old wording. So the bytes of every prompt text are hashed here,
per version: editing one fails this test until the version is bumped and its digest recorded.
"""

from __future__ import annotations

import hashlib

import pytest
from exulanica.canonical import canonical_json
from exulanica.selection import environment_proposal, prompts, proposal

#: version -> SHA-256 of the canonical JSON of that family's prompt texts, as ``_texts`` reads them.
PINNED = {
    "selection-8": "127e11c1d78fa9bed8f222ab06a087a6d8ee7388f5751f32949a1a41df83ea20",
    "proposal-2": "7c6b2cb2633943e0858cd7064e97bda1dcfa42cd9c520ed6c9f901f9b0d61665",
    # The same texts: `proposal-3` changed the draft schema's construction and no prompt.
    "proposal-3": "7c6b2cb2633943e0858cd7064e97bda1dcfa42cd9c520ed6c9f901f9b0d61665",
    "environment-proposal-1": "88314630219bea7f6571a54fff583920ac765581a25efa581e20f4b04e9e0a92",
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
    }


@pytest.mark.parametrize("family", sorted(_texts()))
def test_each_prompt_is_the_one_its_version_names(family):
    version, texts = _texts()[family]
    digest = hashlib.sha256(canonical_json(texts)).hexdigest()
    assert version in PINNED, f"{version} has no pinned digest; record {digest} for it"
    assert digest == PINNED[version], (
        f"the {family} prompts changed under {version}: bump the version and pin {digest}"
    )
