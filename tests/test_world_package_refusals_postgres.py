"""Every refusal the projector can end in, its exact message, and a projection that reaches it.

``REFUSALS`` is the table: one row per message the projection modules raise, keyed by the
message with each interpolated value written ``{}``. Each row names how a real projection reaches
it, and its test asserts the whole message, that nothing was published and that nothing was
receipted. ``test_the_table_names_every_refusal_the_projection_modules_raise`` reads the modules'
syntax trees, so a refusal added without a row, or a row whose refusal is gone, fails here.

Two refusals a projection reaches are raised by the package rules every writer shares
(``exulanica/world_package/package.py``): a prohibited field and a non-finite number in an
evaluation report the caller supplies. They are in ``SHARED_RULE_REFUSALS``, outside the syntax
check, because that module's other refusals are the verifier's. The verifier refusals are tabled
in ``test_world_package_extension.py`` and ``test_world_package_environment.py``.
"""

from __future__ import annotations

import ast
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from exulanica.world.authored_delta import DELTA_SECTIONS, DeltaSection
from exulanica.world.edit_kinds import EDIT_KINDS, EditSubject
from exulanica.world_package import (
    authored,
    environments,
    export_partition,
    extension_projection,
    projector,
)
from exulanica.world_package.extension_formats import AUTHORED_WORLD_1_0, AUTHORED_WORLD_1_1
from exulanica.world_package.package import PackageError
from exulanica.world_package.projector import project_world_package

from test_world_environment_composition_postgres import _add, _composed_over
from test_world_package_extension_postgres import _one_version_one_object
from test_world_package_withdrawal_postgres import WITHDRAWN
from test_world_package_withdrawal_postgres import people as imported_people  # noqa: F401
from world_structure_fixtures import structural_candidate
from world_support import registered_world

pytestmark = pytest.mark.postgres

ROOT = Path(__file__).resolve().parents[1]
#: The modules a projection runs. A refusal raised in one of them is a projection refusal.
PROJECTION_MODULES = tuple(
    ROOT / "exulanica" / "world_package" / name
    for name in ("projector.py", "extension_projection.py", "export_partition.py")
)


@dataclass(frozen=True)
class Refusal:
    """How a projection reaches one refusal, and the exact message it must end in."""

    reach: Callable[..., dict]
    #: The whole message, or None when it names a value only the reach knows (a path, an id).
    message: str | None = None


def _project(repository, output: Path, **overrides):
    """A projection of the world a reach wrote into, or of a registered world when it wrote none.

    A reach that writes no world still names a registered one, so it ends in its own refusal
    rather than in the one for a world this workspace does not hold.
    """
    arguments = {
        "workspace_id": repository.workspace_id,
        "actor": uuid.uuid4(),
        "output": output,
        "private_key": Ed25519PrivateKey.generate(),
    }
    arguments.update(overrides)
    if "world_id" not in arguments:
        arguments["world_id"] = registered_world(repository.connection, repository.workspace_id)
    return project_world_package(repository.connection, **arguments)


# -- the reaches ---------------------------------------------------------------------------------


def _unknown_extension(repository, tmp_path, **_):
    return {
        "extensions": ["authored-world-9.9"],
        "expected": "unknown package extension: ['authored-world-9.9']",
    }


def _two_versions_of_one_extension(repository, tmp_path, **_):
    return {"extensions": [AUTHORED_WORLD_1_1.key, AUTHORED_WORLD_1_0.key]}


def _busy_connection(repository, tmp_path, **_):
    # The harness connection autocommits, so a statement alone leaves it idle; an open
    # transaction block is what a caller that forgot to commit hands the projector.
    repository.connection.execute("begin")
    repository.connection.execute("select 1")
    assert repository.connection.info.transaction_status.name == "INTRANS"
    return {}


def _existing_output(repository, tmp_path, **_):
    output = tmp_path / "already.wmp"
    output.mkdir()
    return {"output": output, "expected": f"output already exists: {output}", "published": True}


def _bad_parent_root(repository, tmp_path, **_):
    return {"parent_merkle_root_sha256": "A" * 64}


def _a_world_another_workspace_holds(repository, tmp_path, **_):
    elsewhere = registered_world(repository.connection, uuid.uuid4(), "world:personal:elsewhere")
    return {
        "world_id": elsewhere,
        "expected": "'world:personal:elsewhere' is not a world this workspace holds",
    }


def _environment_under_authored_alone(repository, tmp_path, **_):
    composed = _composed_over(repository, tmp_path, structural_candidate())
    _add(composed, composed.placement("environment:plaza"))
    return {"extensions": [authored.EXTENSION_KEY], "world_id": composed.worlds.world_id}


def _a_section_with_no_table(repository, tmp_path, monkeypatch, **_):
    unread = DeltaSection("vapour_instances", EditSubject.OBJECT, dict, str, 4)
    monkeypatch.setattr(extension_projection, "DELTA_SECTIONS", (*DELTA_SECTIONS, unread))
    return {"extensions": [authored.EXTENSION_KEY]}


def _a_kind_the_registry_forgot(repository, tmp_path, monkeypatch, **_):
    objects, _snapshot, _version = _one_version_one_object(repository, tmp_path)
    forgetful = tuple(kind for kind in EDIT_KINDS if kind.name != "move_object")
    monkeypatch.setattr(export_partition, "EDIT_KINDS", forgetful)
    return {"extensions": [authored.EXTENSION_KEY], "world_id": objects.world_id}


def _withdrawn_entity_not_withheld(repository, tmp_path, monkeypatch, people, **_):
    _, _, _, withdraw = people
    withdraw()
    monkeypatch.setattr(projector, "_withheld", lambda field, withheld: {})
    return {}


def _withdrawn_naming_not_withheld(repository, tmp_path, monkeypatch, people, **_):
    _, _, _, withdraw = people
    withdraw()
    monkeypatch.setattr(projector, "_names_withdrawn", lambda row, withdrawn: False)
    return {}


def _withdrawn_name_in_another_field(repository, tmp_path, monkeypatch, people, **_):
    _, _, _, withdraw = people
    withdraw()
    original = projector._crate_files

    def leaking(components):
        components = dict(components)
        graph = dict(components["memory/graph.json"])
        graph["labels"] = [WITHDRAWN.upper()]
        components["memory/graph.json"] = graph
        return original(components)

    monkeypatch.setattr(projector, "_crate_files", leaking)
    return {
        "expected": (
            "memory/graph.json/labels/0: a withdrawn person's saved name would be signed into "
            "the package"
        )
    }


def _pointer_elsewhere(name: str):
    def reach(repository, tmp_path, monkeypatch, **_):
        original = projector._current_pointers

        def pointing_nowhere(cursor, world_id):
            pointers = original(cursor, world_id)
            pointers[name] = uuid.uuid4()
            return pointers

        monkeypatch.setattr(projector, "_current_pointers", pointing_nowhere)
        return {}

    return reach


def _report_is_a_directory(repository, tmp_path, **_):
    report = tmp_path / "report-directory"
    report.mkdir()
    return {
        "evaluation_reports": [report],
        "expected": f"evaluation report is not a regular file: {report}",
    }


def _report_is_not_json(repository, tmp_path, **_):
    report = tmp_path / "report.json"
    report.write_bytes(b"{not json")
    return {
        "evaluation_reports": [report],
        "expected": f"evaluation report is not UTF-8 JSON: {report}",
    }


def _stale_state_token(repository, tmp_path, **_):
    objects, _snapshot, version = _one_version_one_object(repository, tmp_path)
    repository.connection.execute(
        "update world_alternate_version set state_sha256=%s where version_id=%s",
        ("0" * 64, version.version_id),
    )
    repository.connection.commit()
    return {"extensions": [authored.EXTENSION_KEY], "world_id": objects.world_id}


def _stale_environment_state_token(repository, tmp_path, **_):
    composed = _composed_over(repository, tmp_path, structural_candidate())
    version = _add(composed, composed.placement("environment:plaza"))
    repository.connection.execute(
        "update world_alternate_version set state_sha256=%s where version_id=%s",
        ("0" * 64, version.version_id),
    )
    repository.connection.commit()
    return {
        "extensions": [environments.EXTENSION_KEY],
        "store": composed.store,
        "world_id": composed.worlds.world_id,
    }


REFUSALS: dict[str, Refusal] = {
    "unknown package extension: {}": Refusal(_unknown_extension),
    "request one version of each extension, not {} and {}": Refusal(
        _two_versions_of_one_extension,
        "request one version of each extension, not authored-world-1.0 and authored-world-1.1",
    ),
    "package projection requires an idle connection": Refusal(
        _busy_connection, "package projection requires an idle connection"
    ),
    "output already exists: {}": Refusal(_existing_output),
    "parent Merkle root must be a lowercase SHA-256 digest": Refusal(
        _bad_parent_root, "parent Merkle root must be a lowercase SHA-256 digest"
    ),
    "{} is not a world this workspace holds": Refusal(_a_world_another_workspace_holds),
    "{} cannot export versions whose state includes environment instances or environment "
    "edits; request {} rather than omit them or emit schema version 2 under the {} extension "
    "name": Refusal(
        _environment_under_authored_alone,
        "authored-world-1.0 cannot export versions whose state includes environment instances or "
        "environment edits; request environment-instances-1.0 rather than omit them or emit "
        "schema version 2 under the 1.0 extension name",
    ),
    "the delta section {} has no table this projector reads, so no version can be judged for "
    "export": Refusal(
        _a_section_with_no_table,
        "the delta section 'vapour_instances' has no table this projector reads, so no version "
        "can be judged for export",
    ),
    "the edit kind {} is not registered, so no extension can say whether it admits it": Refusal(
        _a_kind_the_registry_forgot,
        "the edit kind 'move_object' is not registered, so no extension can say whether it admits "
        "it",
    ),
    "memory/graph.json: entity {} withdrew and does not withhold its name": Refusal(
        _withdrawn_entity_not_withheld
    ),
    "memory/graph.json: naming assertion {} names a person who withdrew and does not withhold "
    "its value": Refusal(_withdrawn_naming_not_withheld),
    "{}: a withdrawn person's saved name would be signed into the package": Refusal(
        _withdrawn_name_in_another_field
    ),
    "current structure pointer does not resolve inside the snapshot": Refusal(
        _pointer_elsewhere("structure_snapshot_id"),
        "current structure pointer does not resolve inside the snapshot",
    ),
    "current style pointer does not resolve inside the snapshot": Refusal(
        _pointer_elsewhere("style_version_id"),
        "current style pointer does not resolve inside the snapshot",
    ),
    "current interaction pointer does not resolve inside the snapshot": Refusal(
        _pointer_elsewhere("interaction_policy_version_id"),
        "current interaction pointer does not resolve inside the snapshot",
    ),
    "evaluation report is not a regular file: {}": Refusal(_report_is_a_directory),
    "evaluation report is not UTF-8 JSON: {}": Refusal(_report_is_not_json),
    "an alternate version's stored state token does not describe its delta inside the export "
    "snapshot": Refusal(
        _stale_state_token,
        "an alternate version's stored state token does not describe its delta inside the "
        "export snapshot",
    ),
    "an alternate version's stored state token does not describe its environment-inclusive "
    "delta inside the export snapshot": Refusal(
        _stale_environment_state_token,
        "an alternate version's stored state token does not describe its environment-inclusive "
        "delta inside the export snapshot",
    ),
}


def _report_with_a_prohibited_field(repository, tmp_path, **_):
    report = tmp_path / "report.json"
    report.write_text('{"password": "hunter2"}', encoding="utf-8")
    return {"evaluation_reports": [report]}


def _report_with_a_non_finite_number(repository, tmp_path, **_):
    report = tmp_path / "report.json"
    report.write_text('{"score": NaN}', encoding="utf-8")
    return {"evaluation_reports": [report]}


SHARED_RULE_REFUSALS: dict[str, Refusal] = {
    "evaluation/input-0.json/password: prohibited field": Refusal(
        _report_with_a_prohibited_field, "evaluation/input-0.json/password: prohibited field"
    ),
    "non-finite floating-point data cannot enter a WMP": Refusal(
        _report_with_a_non_finite_number, "non-finite floating-point data cannot enter a WMP"
    ),
}


def _template(node: ast.expr) -> str:
    """A raised message with every interpolated value written ``{}``."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            part.value if isinstance(part, ast.Constant) else "{}" for part in node.values
        )
    raise AssertionError(f"a refusal message must be a literal or an f-string: {ast.dump(node)}")


def raised_templates(paths=PROJECTION_MODULES) -> dict[str, str]:
    """Every ``raise PackageError(...)`` message in the projection modules, with where it is."""
    found: dict[str, str] = {}
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Raise)
                and isinstance(node.exc, ast.Call)
                and isinstance(node.exc.func, ast.Name)
                and node.exc.func.id == "PackageError"
            ):
                found[_template(node.exc.args[0])] = f"{path.name}:{node.lineno}"
    return found


def test_the_table_names_every_refusal_the_projection_modules_raise():
    raised = raised_templates()
    assert set(raised) - set(REFUSALS) == set(), "a refusal has no row in REFUSALS"
    assert set(REFUSALS) - set(raised) == set(), "a row in REFUSALS names no refusal left"


def test_the_template_reader_sees_a_planted_refusal(tmp_path):
    """The positive control: the reader finds a literal and an f-string refusal it is given."""
    planted = tmp_path / "planted.py"
    planted.write_text(
        "def f(x):\n    raise PackageError('a planted refusal')\n\n"
        "def g(x):\n    raise PackageError(f'planted {x} value')\n",
        encoding="utf-8",
    )
    assert set(raised_templates((planted,))) == {"a planted refusal", "planted {} value"}


@pytest.fixture(name="people")
def _people_alias(request):
    return request.getfixturevalue("imported_people")


@pytest.mark.parametrize("template", sorted(REFUSALS) + sorted(SHARED_RULE_REFUSALS))
def test_each_refusal_is_reached_by_a_projection_and_says_exactly_why(
    template, repository, tmp_path, monkeypatch, request
):
    refusal = {**REFUSALS, **SHARED_RULE_REFUSALS}[template]
    uses_people = "people" in refusal.reach.__code__.co_varnames
    reached = refusal.reach(
        repository,
        tmp_path,
        monkeypatch=monkeypatch,
        people=request.getfixturevalue("people") if uses_people else None,
    )
    expected = reached.pop("expected", refusal.message)
    existed = reached.pop("published", False)
    output = reached.get("output", tmp_path / "refused.wmp")
    reached.setdefault("output", output)
    with pytest.raises(PackageError) as refused:
        _project(repository, **reached)
    message = str(refused.value)
    pattern = "".join(
        ".+" if part == "{}" else re.escape(part) for part in re.split(r"(\{\})", template)
    )
    assert re.fullmatch(pattern, message), (template, message)
    if expected is not None:
        assert message == expected
    if repository.connection.info.transaction_status.name != "IDLE":
        repository.connection.rollback()
    assert output.exists() is existed, "a refused package was published"
    receipts = repository.connection.execute(
        "select count(*) as n from world_package_export where workspace_id=%s",
        (repository.workspace_id,),
    ).fetchone()["n"]
    assert receipts == 0, "a refused package was receipted"
