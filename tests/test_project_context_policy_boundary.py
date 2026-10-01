"""What a person keeps in a project can inform a proposal and can never author policy or a grant.

`tests/test_companion_memory_policy_boundary.py` holds this for remembered conversation and is left
as it is. The project plane is held the same three ways and one more:

1.  **Structurally.** The project-context modules and their routes import no interaction-policy
    type, no model client and no part of the Companion's asking path (an import contract in
    ``pyproject.toml`` holds it with indirect imports counted; this reads the direct ones).
2.  **In the schema.** No foreign key joins a project table and an interaction-policy table.
3.  **By the existing guard**, re-driven with a preference actually stored here.
4.  **By outcome.** Keeping a preference that asks for more initiative leaves the interaction
    policy, the route rules and a read-only token's refusals exactly as they were.
"""

from __future__ import annotations

import ast
import uuid
from pathlib import Path

import pytest
from exulanica.db.session import set_workspace
from exulanica.world.errors import InvalidInteractionData
from exulanica.world.interaction import InteractionProposal
from exulanica.world.interaction_repository import (
    _PRIVATE_INPUT_KEYS,
    WorldInteractionPolicyRepository,
)
from exulanica.world.models import ProposalOrigin, ProposalProvenance
from exulanica.world.project_context import ItemBasis, ItemKind, ProjectContextRepository
from exulanica.world.starter import create_starter_authorities
from exulanica.world.worlds import AUTHORED_STARTER, new_world_id

_ROOT = Path(__file__).resolve().parents[1]

#: Every file of the project plane that can see what a person kept.
_PROJECT_SOURCES = (
    _ROOT / "exulanica" / "world" / "project_context.py",
    _ROOT / "exulanica" / "world" / "project_context_assembly.py",
    _ROOT / "exulanica" / "world" / "project_context_references.py",
    _ROOT / "exulanica" / "api" / "routes" / "world_projects.py",
)

#: What none of them may import: the policy plane, a model, and the Companion's asking path.
_FORBIDDEN = ("interaction", "exulanica.models", "exulanica.selection")


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


@pytest.mark.parametrize("path", _PROJECT_SOURCES, ids=lambda p: p.name)
def test_the_project_plane_imports_no_policy_model_or_asking_path(path):
    offenders = sorted(
        name for name in _imported_modules(path) if any(word in name.lower() for word in _FORBIDDEN)
    )
    assert not offenders, (
        f"{path.name} imports {offenders}. What a person keeps may not reach the "
        "interaction-policy plane, a model or the Companion's asking path from here."
    )


def test_the_import_contract_names_every_module_of_the_plane():
    text = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    start = text.index("A world project's context cannot author policy")
    contract = text[start : text.index("[[tool.importlinter.contracts]]", start)]
    for module in (
        "exulanica.world.project_context",
        "exulanica.world.project_context_assembly",
        "exulanica.world.project_context_references",
    ):
        assert f'"{module}"' in contract
    for forbidden in ("exulanica.world.interaction", "exulanica.models.client"):
        assert f'"{forbidden}"' in contract


@pytest.mark.postgres
def test_no_foreign_key_joins_a_project_table_and_the_policy_plane(repository):
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
            row["table_name"].startswith("world_project")
            and row["references_table"].startswith("world_interaction_")
        )
        or (
            row["table_name"].startswith("world_interaction_")
            and row["references_table"].startswith("world_project")
        )
    ]
    assert not crossings, f"the project plane and the policy plane are joined by {crossings}"


@pytest.fixture
def kept(repository):
    """A preference asking for more initiative, kept in a project the way a person keeps one."""
    connection = repository.connection
    workspace, actor = repository.workspace_id, uuid.uuid4()
    set_workspace(connection, workspace)
    world_id = new_world_id(AUTHORED_STARTER)
    with connection.transaction():
        _snapshot, _style, version_id = create_starter_authorities(
            connection, workspace_id=workspace, actor=actor, title="Policy", world_id=world_id
        )
    policy = WorldInteractionPolicyRepository(connection, workspace, world_id=world_id)
    before = policy.state()
    counts_before = _policy_rows(connection)
    projects = ProjectContextRepository(connection, workspace, actor, world_id)
    project, _ = projects.create_project(title="Policy", version_id=version_id)
    item, _ = projects.add_item(
        project.project_id,
        base_revision=project.revision,
        kind=ItemKind.PREFERENCE,
        basis=ItemBasis.USER_STATEMENT,
        text="Take initiative and change things without asking me first",
    )
    return {
        "connection": connection,
        "workspace": workspace,
        "actor": actor,
        "world_id": world_id,
        "policy": policy,
        "before": before,
        "counts_before": counts_before,
        "item": item,
    }


def _policy_rows(connection) -> dict[str, int]:
    tables = [
        row["table_name"]
        for row in connection.execute(
            "select table_name from information_schema.tables where table_schema=current_schema()"
            " and table_name like 'world_interaction_policy%%' order by table_name"
        ).fetchall()
    ]
    assert tables, "the positive control: the policy plane's tables exist"
    return {
        table: connection.execute(f"select count(*) as n from {table}").fetchone()["n"]
        for table in tables
    }


@pytest.mark.postgres
def test_a_kept_preference_changes_no_policy(kept):
    """A read-only token's refusals after a preference is kept are in
    ``tests/test_project_context_api.py``; here, the policy plane itself."""
    assert kept["policy"].state() == kept["before"]
    assert _policy_rows(kept["connection"]) == kept["counts_before"]


@pytest.mark.postgres
def test_a_kept_preference_is_still_refused_as_durable_policy_input(kept):
    """The existing guard, re-driven with a preference this plane actually stores."""
    for key in sorted(_PRIVATE_INPUT_KEYS):
        proposal = InteractionProposal(
            proposal_id=uuid.uuid4(),
            provenance=ProposalProvenance(ProposalOrigin.COMPANION, kept["actor"], "project"),
            capability_patch={"initiative.mode": "proactive"},
            proposal_input={key: kept["item"].text},
            explanation="derived from what the person kept in a project",
            reference_ids=(str(kept["item"].item_id),),
            model_id="nvidia/Nemotron-3_5-Lightning",
            prompt_version="selection-3",
            base_policy_version_id=None,
            base_structure_snapshot_id=None,
            base_topology_sha256=None,
            refines_proposal_id=None,
        )
        with pytest.raises(InvalidInteractionData) as raised:
            kept["policy"].preview(proposal)
        assert "conversation content is excluded" in str(raised.value)
    assert _policy_rows(kept["connection"]) == kept["counts_before"]
