"""The contract this lane consumes is held to the tree it describes.

``exulanica/grammar/grammars/city/generation/contract.py`` is what this lane and others read to
know what they can rely on: the tessellator's container and stage, the rules a record can be
waiting on, the texture sets and the runtime. Nothing tested it, and on 2026-09-18 it still said
"what draws on main: terrain only" while the tessellator drew facades, massing, object parts, lot
and block ground, kerbs, footways and junction fills. Three lanes were reading it.

A document that asserts facts about the repository and is checked by nobody goes stale silently and
is believed anyway. These are the facts in it that a machine can check: the stage's own numbers,
and the closed set of rules a tessellator entry may name. The prose around them still needs a
person, but a reader who finds those numbers right is entitled to more trust in the rest.
"""

from __future__ import annotations

import re
from pathlib import Path

from exulanica.grammar.grammars.city.generation import contract
from exulanica.ingest.stages import STAGES

ROOT = Path(__file__).resolve().parents[1]
NEEDS_SOURCE = ROOT / "web" / "packages" / "loom-tess" / "src" / "core" / "expand.ts"
TEXT = contract.__doc__ or ""


def test_the_contract_names_the_stage_this_tree_states():
    """EVERY tessellator number in the document is this tree's, not merely one of them.

    Written as a set rather than a substring because the first version of this test asked whether
    the right number appeared anywhere, and a document that says 13 in one paragraph and 11 in
    another satisfies that while being wrong where it counts. Proved by changing the heading alone:
    the substring test passed.
    """
    spec = STAGES["baked_tile"]
    assert f"stage ``baked_tile`` version {spec.version}" in TEXT
    assert f"``{spec.params['container']}``" in TEXT
    assert f"``{spec.params['triangle_digest']}``" in TEXT
    stated = set(re.findall(r"tessellator (\d+)", TEXT))
    assert stated == {str(spec.params["tessellator"])}, (
        f"the contract names tessellator(s) {sorted(stated)} and this tree states "
        f"{spec.params['tessellator']}"
    )


def test_every_rule_a_record_may_wait_on_is_in_the_contract_and_nothing_else_is():
    """The closed set of `NEEDS` the tessellator states, against the set the contract names.

    Both directions matter. A need in the tessellator and not here means a lane can be told its
    records are waiting on a rule this document has never heard of. A need here and not in the
    tessellator means the document is describing a rule that no longer exists, which is how the
    section this test was written for went wrong.
    """
    declared = set(re.findall(r"^  (\w+): '\1',$", NEEDS_SOURCE.read_text(encoding="utf-8"), re.M))
    assert declared, "the tessellator's NEEDS table could not be read; its shape has moved"
    named = {need for need in declared if f"``{need}``" in TEXT}
    assert named == declared, (
        "the consumed contract and the tessellator disagree about what a record can wait on: "
        f"only in the tessellator {sorted(declared - named)}, "
        f"only in the contract {sorted(named - declared)}"
    )
