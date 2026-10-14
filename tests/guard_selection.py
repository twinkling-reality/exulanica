"""The guards: checks over the whole source tree, the whole route table or the whole schema.

A change anywhere can break one of these, so no choice of tests by the files a change touches
includes them, and a run of the whole tree without a database skips the ones keyed on routes and
tables. ``pytest --guards`` runs exactly the tests listed here; the ``postgres`` marker that
collection already applies splits them into the ones that need no database
(``pytest --guards -m "not postgres"``) and the ones that need a private server
(``EXULANICA_TEST_POSTGRES=private pytest --guards``). docs/development-setup.md says when to run
each.

An entry is a test file, every test in it a guard, or ``file::function`` for one test function of
a file whose other tests are not guards. A test that reads the whole tree, iterates every route or
inspects every table belongs here, with one line on what it holds.
"""

from __future__ import annotations

from typing import Final

GUARDS: Final[dict[str, str]] = {
    "test_acceptance_scripted_model.py": (
        "no wheel or image can carry the scripted model; reads every Dockerfile"
    ),
    "test_agent_outside_product.py": (
        "outside agents stay outside the product: one door, no agent-specific core"
    ),
    "test_api.py::test_a_stranger_never_gets_a_403": (
        "every probed route answers a stranger 404, never 403"
    ),
    "test_api.py::test_every_authenticated_route_refuses_a_bad_token": (
        "every probed route refuses a bad token"
    ),
    "test_api.py::test_every_authenticated_route_refuses_an_anonymous_caller": (
        "every probed route refuses an anonymous caller"
    ),
    "test_api_surface_snapshot.py": "the routes and schema equal the committed snapshots",
    "test_backup_role.py": (
        "the backup role reads every row after the whole migration chain and writes nothing"
    ),
    "test_base_images_pinned.py": (
        "every image a build starts from or a composition runs names a digest"
    ),
    "test_capability_descriptors.py": (
        "a capability descriptor states nothing its route, permission or schema does not"
    ),
    "test_catalog_provenance.py": "every discovered catalog says where its content came from",
    "test_ci_workflow.py": (
        "what continuous integration runs, held to the sources it is derived from"
    ),
    "test_companion_acceptance.py": (
        "the frozen input evidence stays local only; reads the tracked files"
    ),
    "test_companion_action_policy_boundary.py": (
        "the Companion's world actions never grant a capability or reach the policy plane"
    ),
    "test_companion_memory_policy_boundary.py": (
        "conversation text never becomes an interaction-policy input"
    ),
    "test_comparison_reading_bound.py": (
        "the people a comparison runs are derived from the protocol's replay line"
    ),
    "test_consent_wording_is_one_text.py": (
        "the sentences a person reads come from the server that checks them"
    ),
    "test_db_migrate.py": "the whole migration chain applies to a real server",
    "test_decision_roles.py": (
        "a part of a world that changes is run by a chosen model through one path"
    ),
    "test_deployment.py": "the deployment files, checked as text",
    "test_documentation_links.py": (
        "every documentation path the repository names is in the repository"
    ),
    "test_documentation_structure.py": (
        "the maintained documentation has one home and resolvable section links"
    ),
    "test_door_names_no_game.py": (
        "no game's name in product source, and nothing of bridges/ imported"
    ),
    "test_door_tables_withheld_from_read_only.py": (
        "the door's global tables are withheld from the read-only role"
    ),
    "test_edit_kinds.py": (
        "every edit the product appends names a registered kind; scans exulanica/"
    ),
    "test_egress_allowlist.py": "every network module is held to the egress allowlist",
    "test_existence_oracle.py": (
        "a stranger cannot tell a foreign id from an invented one, on every id route"
    ),
    "test_final_read_check.py": "the final read check is stated once and reached from there",
    "test_flight_page_words.py": "the page has words for every flight code the server can send",
    "test_grammar_layering.py": "generated content cannot name a citation",
    "test_hosted_boundary.py": (
        "every hosted request passes one boundary, and no saved name crosses it"
    ),
    "test_image_ships_import_reads.py": (
        "every file the package reads at import is in each image that installs it"
    ),
    "test_ingest_preconditions.py": (
        "nothing in the ingest package writes an embedding; scans the package"
    ),
    "test_inhabitant_words.py": "a simulated person in words: one data file, two readers",
    "test_lettering_boundary.py": (
        "the lettering tool stays outside the product, in both directions"
    ),
    "test_migration.py": "checks over the migration files themselves",
    "test_models_manifest.py": (
        "no module reads a credential from a variable it spells; scans exulanica/"
    ),
    "test_movement_layering.py": "the movement modules cannot reach what they must not",
    "test_no_creature_code.py": "no code is written for a particular creature",
    "test_optional_stacks.py": "a test that needs an optional stack says which one",
    "test_orimera_rename_guard.py": "the old name appears only on a reviewed allowlist",
    "test_pieces_boundary.py": (
        "the piece formats belong to no side and need no numpy where the product reads them"
    ),
    "test_place_names.py": (
        "each offered place role lists exactly the modules that name it; scans exulanica/"
    ),
    "test_project_context_policy_boundary.py": (
        "what a project keeps can inform a proposal and never author policy or a grant"
    ),
    "test_public_deployment.py": "the public server's composition, edge and operator script",
    "test_reconstruction_is_not_evidence.py": "reconstruction is never evidence",
    "test_reference_boundary.py": "nothing withheld leaves in a reference query",
    "test_registry_tables.py": (
        "the registry tables are named once and every place that acts on them sees all"
    ),
    "test_restore_replay_withdrawal_catalog.py": (
        "the withdrawal catalog a restore carries matches the schema"
    ),
    "test_route_permissions.py": (
        "every mounted route is declared, and a missing grant is refused on the wire"
    ),
    "test_route_probes.py": "the authorisation sweep covers exactly the declared surface",
    "test_route_rule_layout.py": "the layout of ROUTE_RULES",
    "test_row_level_security.py": "workspace isolation, exercised as a role that cannot bypass it",
    "test_runtime_update_grants.py": (
        "every relation the runtime role may update is named, with its reason"
    ),
    "test_saved_name_function_words.py": (
        "a closed-class word is not a saved name by itself, in either layer"
    ),
    "test_segmentation_stage.py": (
        "no local checkpoint identifier is inlined in Python source; scans exulanica/"
    ),
    "test_society_action_refusals.py": (
        "the names a directed or presence request is refused by are stated once"
    ),
    "test_society_engine_capabilities.py": (
        "a module asks the engine table what an engine can do, never its name"
    ),
    "test_society_engine_table.py": "the engine table is the one statement of which engines exist",
    "test_society_erasure_postgres.py": "a world's society is erased whole, as the runtime role",
    "test_spending_privileges.py": "who may read and write the spending tables",
    "test_tests_read_the_clock_when_they_run.py": (
        "a test reads the clock when it runs, never at import"
    ),
    "test_thing_store_words.py": (
        "a container a creature's look is drawn from holds no word a person wrote"
    ),
    "test_third_party_notices.py": "the shipped-data section of THIRD_PARTY_NOTICES.md is current",
    "test_traffic_layering.py": "the traffic layer cannot reach what it must not",
    "test_training_boundary.py": "the training code in ml/ stays outside the product",
    "test_workspace_lock.py": "the workspace lock seed is stated once",
    "test_world_erasure_postgres.py": (
        "a world's rows are erased whole, and a workspace's erasure erases every world"
    ),
    "test_world_identity_inventory.py": "every statement over a world table names its world",
    "test_world_inventory_postgres.py": "the world overview's reads and locks, as the runtime role",
    "test_world_specification_served_snapshot.py": (
        "the page and the server read one committed specification"
    ),
}


def guard_files() -> frozenset[str]:
    """The test files that hold at least one guard."""
    return frozenset(entry.partition("::")[0] for entry in GUARDS)


def is_guard(file_name: str, function_name: str) -> bool:
    """Whether the test function ``function_name`` of the test file ``file_name`` is a guard."""
    return file_name in GUARDS or f"{file_name}::{function_name}" in GUARDS
