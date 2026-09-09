"""Conversation text is stored, and it never becomes an interaction-policy input.

``exulanica/world/interaction_repository.py`` already refuses a proposal whose input carries
``conversation``, ``messages``, ``raw_utterance``, ``transcript`` or ``prompt_text``, and 0021
says the same in its own header. Storing conversation durably for the first time is exactly the
change that makes that refusal easy to erode: there is now a table full of the very text the
policy plane will not accept, one import away.

So the boundary is held three ways here, and only one of them is the existing refusal.

1.  **Structurally.** Neither the repository nor the route imports an interaction type, so a call
    site that wanted to launder a question into a capability decision has to add the import first,
    in a diff a reviewer can see. This is the check that would fail on the first line of such a
    change rather than after somebody wired it up.
2.  **In the schema.** No foreign key joins the two planes in either direction.
3.  **By the existing guard**, re-driven with real stored text rather than a synthetic payload, so
    the thing being refused is the thing this branch now keeps.

The word "policy" means two different things across these files and the collision is why this
file spells the distinction out. 4.4's "policy over the entity graph snapshot plus the
conversation transcript" is the turn generator: per session, in the browser, choosing the next
question. The plane guarded here is the durable capability policy: what the system is PERMITTED
to do. A question somebody typed is evidence about them; a capability is a rule. The first may
inform the next question and may never author the second.
"""

from __future__ import annotations

import ast
import uuid
from pathlib import Path

import pytest
from exulanica.db.session import set_workspace
from exulanica.world.companion_memory import CompanionMemoryRepository, RecordedAnswer
from exulanica.world.errors import InvalidInteractionData
from exulanica.world.interaction import InteractionProposal
from exulanica.world.interaction_repository import (
    _PRIVATE_INPUT_KEYS,
    WorldInteractionPolicyRepository,
)
from exulanica.world.models import ProposalOrigin, ProposalProvenance

_ROOT = Path(__file__).resolve().parents[1]

#: The two files this branch adds that can see stored conversation text.
_COMPANION_SOURCES = (
    _ROOT / "exulanica" / "world" / "companion_memory.py",
    _ROOT / "exulanica" / "api" / "routes" / "companion.py",
)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


@pytest.mark.parametrize("path", _COMPANION_SOURCES, ids=lambda p: p.name)
def test_the_companion_memory_plane_imports_no_interaction_policy_type(path):
    """The structural half, and the reason it is a test rather than a comment.

    A comment saying "do not pass this to the policy plane" is advice. An import list that names
    no policy type is a fact, and this is what keeps it one.
    """
    offenders = sorted(
        name
        for name in _imported_modules(path)
        if "interaction" in name.lower() and "interaction-model" not in name
    )
    assert not offenders, (
        f"{path.name} imports {offenders}. Durable conversation text may not reach the "
        "interaction-policy plane, and an import is the first step of it doing so."
    )


def test_the_two_planes_are_joined_by_no_foreign_key(repository):
    """Neither direction. A key either way would be a path a query could travel."""
    set_workspace(repository.connection, repository.workspace_id)
    rows = repository.connection.execute(
        """
        select tc.table_name, ccu.table_name as references_table
          from information_schema.table_constraints tc
          join information_schema.constraint_column_usage ccu
            on ccu.constraint_name = tc.constraint_name
           and ccu.table_schema = tc.table_schema
         where tc.constraint_type = 'FOREIGN KEY'
           and tc.table_schema = current_schema()
        """
    ).fetchall()
    crossings = [
        (row["table_name"], row["references_table"])
        for row in rows
        if (
            row["table_name"].startswith("companion_")
            and row["references_table"].startswith("world_interaction_")
        )
        or (
            row["table_name"].startswith("world_interaction_")
            and row["references_table"].startswith("companion_")
        )
    ]
    assert not crossings, f"the conversation plane and the policy plane are joined by {crossings}"


def test_a_stored_question_is_still_refused_as_durable_policy_input(repository):
    """The existing guard, re-driven with text that is now actually stored somewhere.

    Every key in ``_PRIVATE_INPUT_KEYS`` is tried, because the guard is a set membership test and
    a set that lost a member would fail silently: the proposal would be accepted and the sentence
    somebody typed would become an input to what this system is permitted to do.
    """
    set_workspace(repository.connection, repository.workspace_id)
    actor = uuid.uuid4()
    memory = CompanionMemoryRepository(repository.connection, repository.workspace_id, actor)
    stored = memory.record_answer(
        RecordedAnswer(
            question="Who is in these photographs?",
            answer_text="Your photographs contain no describable information about people.",
            abstained=None,
            deterministic=False,
            repaired=False,
            served_model="nvidia/Nemotron-3_5-Lightning",
            planned_by="Qwen/Qwen3-235B-A22B-Instruct-2507",
            prompt_version="selection-3",
            latency_ms=10094,
            citations=(),
        )
    )

    policy = WorldInteractionPolicyRepository(repository.connection, repository.workspace_id)
    for key in sorted(_PRIVATE_INPUT_KEYS):
        proposal = InteractionProposal(
            proposal_id=uuid.uuid4(),
            provenance=ProposalProvenance(ProposalOrigin.COMPANION, actor, "companion-memory"),
            capability_patch={"companion.initiative": "minimal"},
            # The real stored sentence, under the real refused key. A synthetic string would
            # test the guard; this tests the guard against what this branch actually keeps.
            proposal_input={key: stored.question},
            explanation="derived from what the person asked",
            reference_ids=(str(stored.answer_id),),
            model_id="nvidia/Nemotron-3_5-Lightning",
            prompt_version="selection-3",
            base_policy_version_id=None,
            base_structure_snapshot_id=None,
            base_topology_sha256=None,
            refines_proposal_id=None,
        )
        with pytest.raises(InvalidInteractionData) as raised:
            policy.preview(proposal)
        assert "conversation content is excluded" in str(raised.value)
        assert key in str(raised.value)


def test_the_refused_key_set_still_names_every_word_this_plane_stores_under():
    """A ratchet on the set itself.

    The guard is a membership test over five names, and ``_private_keys`` looks at keys and never
    at values, so a transcript filed under an unlisted key is not caught. That limit is the
    interaction plane's and is not this branch's to change; what this branch can do is fail loudly
    if one of the five ever disappears, because the set shrinking is indistinguishable from the
    guard working right up until somebody uses the removed name.
    """
    assert frozenset(
        {"conversation", "messages", "raw_utterance", "transcript", "prompt_text"}
    ) == _PRIVATE_INPUT_KEYS
