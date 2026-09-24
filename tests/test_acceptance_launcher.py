"""The acceptance launcher in ``scripts/acceptance/launch.py``, without a browser or a server.

These cover what can be decided before anything starts: how its arguments parse, which ports a
slot owns, every refusal it reaches before starting a process, the command lines and environments
it builds for the development server, the production build and its preview, and what it passes to
the API with and without a model. Starting real services is exercised by running it
(``docs/demo-integrity.md`` section 5).

A launcher that ran on one machine only would stop a clone from running the rehearsal, so one test
reads its source for anything that belongs to a machine: a home or install path, a port outside
the slot table.
"""

from __future__ import annotations

import ast
import importlib.util
import io
import json
import re
import subprocess
import tempfile
from contextlib import redirect_stderr
from pathlib import Path
from types import ModuleType

import pytest
from exulanica.api.permissions import ACCOUNT_OWNER_PERMISSIONS

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts" / "acceptance" / "launch.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("exulanica_acceptance_launch", LAUNCHER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LAUNCH = _load()


@pytest.fixture
def temporary(tmp_path, monkeypatch) -> Path:
    """This test's own system temporary directory, where the launcher keeps run state."""
    directory = tmp_path / "system-temporary"
    directory.mkdir()
    monkeypatch.setenv("TMPDIR", str(directory))
    monkeypatch.setattr(tempfile, "tempdir", None)
    return directory


def _refusal(call, *arguments, **keywords) -> str:
    with pytest.raises(LAUNCH.Refused) as refused:
        call(*arguments, **keywords)
    return refused.value.name


def _checkout(at: Path) -> Path:
    """A git checkout holding the files the launcher checks for, and nothing that runs."""
    for relative in (
        ".venv/bin/python",
        "web/packages/app/node_modules/.bin/vite",
        "scripts/test_postgres.py",
    ):
        (at / relative).parent.mkdir(parents=True, exist_ok=True)
        (at / relative).write_text("")
    subprocess.run(["git", "init", "-q", str(at)], check=True)
    return at.resolve()


# -- arguments ------------------------------------------------------------------------------------


def test_up_parses_every_flag_and_defaults_to_slot_zero_without_them():
    parser = LAUNCH.build_parser()
    plain = parser.parse_args(["up", "--worktree", "w"])
    full = parser.parse_args(
        [
            "up",
            "--worktree",
            "w",
            "--slot",
            "3",
            "--reuse-database",
            "--model",
            "--no-derivative-worker",
            "--production",
        ]
    )

    assert (plain.slot, plain.reuse_database, plain.model, plain.production) == (
        0,
        False,
        False,
        False,
    )
    assert plain.no_derivative_worker is False
    assert (full.slot, full.reuse_database, full.model, full.production) == (3, True, True, True)
    assert full.no_derivative_worker is True


def test_every_command_needs_a_worktree_and_status_and_down_take_no_run_flags():
    parser = LAUNCH.build_parser()
    for command in ("up", "status", "down"):
        with pytest.raises(SystemExit), redirect_stderr(io.StringIO()):
            parser.parse_args([command])
    for command in ("status", "down"):
        with pytest.raises(SystemExit), redirect_stderr(io.StringIO()):
            parser.parse_args([command, "--worktree", "w", "--production"])


# -- slots ----------------------------------------------------------------------------------------


def test_each_slot_owns_five_consecutive_ports_inside_the_table():
    seen: set[int] = set()
    for slot in range(LAUNCH.SLOT_COUNT):
        owned = LAUNCH.ports(slot)
        assert list(owned) == list(LAUNCH.PORT_ROLES)
        values = list(owned.values())
        assert values == list(range(values[0], values[0] + LAUNCH.SLOT_WIDTH))
        assert values[0] == LAUNCH.PORT_BASE + LAUNCH.SLOT_WIDTH * slot
        assert not seen & set(values)
        seen |= set(values)
    assert max(seen) == LAUNCH.PORT_LIMIT
    assert min(seen) == LAUNCH.PORT_BASE


def test_the_rehearsal_finds_its_preview_port_where_it_looks_for_it():
    """``rehearse.py`` serves its build on ``browser + 1`` and refuses one past ``PORT_LIMIT``."""
    for slot in range(LAUNCH.SLOT_COUNT):
        owned = LAUNCH.ports(slot)
        assert owned["spare"] == owned["browser"] + 1 <= LAUNCH.PORT_LIMIT


def test_a_slot_outside_the_table_is_refused_by_name():
    assert _refusal(LAUNCH.ports, LAUNCH.SLOT_COUNT) == "slot-out-of-range"
    assert _refusal(LAUNCH.ports, -1) == "slot-out-of-range"


# -- refusals before anything starts ---------------------------------------------------------------


def test_a_directory_that_is_not_a_checkout_is_refused(tmp_path):
    assert _refusal(LAUNCH.checkout, str(tmp_path)) == "not-a-checkout"


def test_a_checkout_without_its_own_toolchain_is_refused_naming_what_is_missing(tmp_path):
    with pytest.raises(LAUNCH.Refused) as refused:
        LAUNCH.check_toolchain(tmp_path)

    assert refused.value.name == "toolchain-missing"
    assert ".venv/bin/python" in refused.value.detail


def test_a_model_run_is_refused_until_it_has_a_key_an_allowlist_and_a_bound():
    key = "sk-not-a-real-key-" + "x" * 24
    steps = [
        ({}, "model-key-missing"),
        ({"NEBIUS_API_KEY": key}, "model-allowlist-missing"),
        (
            {"NEBIUS_API_KEY": key, "EXULANICA_EGRESS_ALLOWLIST": '["https://model.example"]'},
            "budget-missing",
        ),
    ]
    for environ, expected in steps:
        with pytest.raises(LAUNCH.Refused) as refused:
            LAUNCH.model_environment(environ)
        assert refused.value.name == expected
        assert key not in str(refused.value)

    complete = {
        "NEBIUS_API_KEY": key,
        "EXULANICA_EGRESS_ALLOWLIST": '["https://model.example"]',
        "EXULANICA_BUDGET_USD": "1.00",
        "EXULANICA_DATA_DIR": "/elsewhere",
    }
    assert LAUNCH.model_environment(complete) == {
        name: complete[name] for name in LAUNCH.MODEL_VARIABLES
    }


def test_up_refuses_a_model_run_without_a_bound_before_it_starts_anything(
    tmp_path, temporary, monkeypatch
):
    worktree = _checkout(tmp_path / "clone")
    monkeypatch.setenv("NEBIUS_API_KEY", "sk-not-a-real-key")
    monkeypatch.setenv("EXULANICA_EGRESS_ALLOWLIST", '["https://model.example"]')
    monkeypatch.delenv("EXULANICA_BUDGET_USD", raising=False)
    started: list[list[str]] = []
    monkeypatch.setattr(LAUNCH, "spawn", lambda command, *rest: started.append(command))
    arguments = LAUNCH.build_parser().parse_args(["up", "--worktree", str(worktree), "--model"])

    assert _refusal(LAUNCH.up, arguments) == "budget-missing"
    assert started == []
    assert not LAUNCH.runtime_root().exists()


def test_up_refuses_a_second_run_of_one_checkout_and_a_slot_whose_ports_are_held(
    tmp_path, temporary, monkeypatch
):
    worktree = _checkout(tmp_path / "clone")
    arguments = LAUNCH.build_parser().parse_args(["up", "--worktree", str(worktree), "--slot", "2"])
    held = LAUNCH.ports(2)["api"]
    monkeypatch.setattr(LAUNCH, "listening", lambda port: port == held)

    assert _refusal(LAUNCH.up, arguments) == "port-in-use"

    state = LAUNCH.state_dir(worktree) / "state.json"
    state.parent.mkdir(parents=True)
    state.write_text("{}")
    assert _refusal(LAUNCH.up, arguments) == "state-exists"


def test_down_with_nothing_recorded_is_refused(tmp_path, temporary):
    worktree = _checkout(tmp_path / "clone")
    arguments = LAUNCH.build_parser().parse_args(["down", "--worktree", str(worktree)])

    assert _refusal(LAUNCH.down, arguments) == "no-state"


def test_the_command_line_prints_a_refusal_by_name_and_exits_2(tmp_path, temporary, monkeypatch):
    monkeypatch.setattr(LAUNCH.shutil, "which", lambda name: None)
    error = io.StringIO()
    with redirect_stderr(error):
        status = LAUNCH.main(["status", "--worktree", str(tmp_path)])

    assert status == 2
    assert error.getvalue().startswith("refused (lsof-missing): ")


def test_run_state_lives_in_the_system_temporary_directory_one_directory_per_checkout(
    tmp_path, temporary
):
    first = LAUNCH.state_dir(tmp_path / "a" / "clone")
    second = LAUNCH.state_dir(tmp_path / "b" / "clone")

    assert first.parent == second.parent == temporary / LAUNCH.RUNTIME_DIRECTORY_NAME
    assert first != second
    assert first.name.startswith("clone-")


# -- what each process is given --------------------------------------------------------------------


def test_the_production_build_command_writes_into_the_run_directory(tmp_path):
    vite = tmp_path / "vite"
    run_dir = tmp_path / "run"

    assert LAUNCH.production_build_command(vite, run_dir) == [
        str(vite),
        "build",
        "--outDir",
        str(run_dir / "app-build"),
        "--emptyOutDir",
    ]


def test_the_production_build_gets_no_token_and_nothing_that_redirects_it():
    environ = {
        "PATH": "/bin",
        "VITE_EXULANICA_TOKEN": "a-development-token",
        "EXULANICA_API_URL": "http://elsewhere",
        "NEBIUS_API_KEY": "sk-not-a-real-key",
        "PGPORT": "5433",
    }

    built = LAUNCH.production_build_environment(environ)

    assert built == {"PATH": "/bin"}


def test_the_build_token_guard_refuses_a_vite_variable_that_escaped_the_scrub(monkeypatch):
    """The positive control: with the scrub list missing VITE_, the guard is what refuses."""
    monkeypatch.setattr(LAUNCH, "SCRUBBED_PREFIXES", ("EXULANICA_",))

    name = _refusal(LAUNCH.production_build_environment, {"VITE_EXULANICA_TOKEN": "t"})

    assert name == "build-token"


def test_the_preview_serves_that_build_on_the_slot_port_and_proxies_to_the_slot_api(tmp_path):
    vite = tmp_path / "vite"
    run_dir = tmp_path / "run"
    owned = LAUNCH.ports(1)

    command = LAUNCH.preview_command(vite, run_dir, owned["vite"])
    environment = LAUNCH.preview_environment(owned, {"VITE_EXULANICA_TOKEN": "t", "HOME": "/h"})

    assert command == [
        str(vite),
        "preview",
        "--outDir",
        str(run_dir / "app-build"),
        "--port",
        str(owned["vite"]),
        "--strictPort",
    ]
    assert environment["EXULANICA_API_URL"] == f"http://127.0.0.1:{owned['api']}"
    assert not any(name.startswith("VITE_") for name in environment)


def test_the_development_server_alone_carries_the_synthetic_token(tmp_path):
    owned = LAUNCH.ports(0)

    environment = LAUNCH.development_environment(owned, "synthetic", {"VITE_OTHER": "x"})

    assert environment["VITE_EXULANICA_TOKEN"] == "synthetic"
    assert "VITE_OTHER" not in environment
    assert environment["EXULANICA_API_URL"] == f"http://127.0.0.1:{owned['api']}"
    assert LAUNCH.development_command(tmp_path / "vite", owned["vite"])[1:] == [
        "--port",
        str(owned["vite"]),
        "--strictPort",
    ]


def _api_environment(model: bool, environ: dict[str, str]) -> dict[str, str]:
    exports = {
        "EXULANICA_DATABASE_URL": "postgresql://exulanica_app@localhost:19200/exulanica",
        "EXULANICA_READONLY_DATABASE_URL": "postgresql://exulanica_ro@localhost:19200/exulanica",
        "EXULANICA_PURGE_DATABASE_URL": "postgresql://exulanica_purge@localhost:19200/exulanica",
    }
    return LAUNCH.api_environment(
        exports=exports,
        grant={"token": {"permissions": []}},
        data_dir=Path("run/data"),
        model=model,
        derivative_worker=False,
        environ=environ,
    )


def test_the_api_gets_the_model_and_its_bound_only_with_model():
    environ = {
        "NEBIUS_API_KEY": "sk-not-a-real-key",
        "EXULANICA_EGRESS_ALLOWLIST": '["https://model.example"]',
        "EXULANICA_BUDGET_USD": "1.00",
        "EXULANICA_DATA_DIR": "/somebody/else",
    }

    without = _api_environment(False, environ)
    with_model = _api_environment(True, environ)

    assert not set(LAUNCH.MODEL_VARIABLES) & set(without)
    assert {name: with_model[name] for name in LAUNCH.MODEL_VARIABLES} == {
        name: environ[name] for name in LAUNCH.MODEL_VARIABLES
    }
    for environment in (without, with_model):
        assert environment["EXULANICA_DATA_DIR"] == "run/data"
        assert environment["EXULANICA_DERIVATIVE_WORKER"] == "off"
        assert json.loads(environment["EXULANICA_API_TOKENS"]) == {"token": {"permissions": []}}


# -- what the launcher states --------------------------------------------------------------------


def test_the_synthetic_grant_is_the_account_owners():
    assert set(LAUNCH.PERMISSIONS) == {permission.value for permission in ACCOUNT_OWNER_PERMISSIONS}
    assert len(LAUNCH.PERMISSIONS) == len(set(LAUNCH.PERMISSIONS))


def test_every_refusal_it_raises_is_registered_and_every_registered_one_is_raised():
    tree = ast.parse(LAUNCHER.read_text(encoding="utf-8"))
    raised = {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "refuse"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    }
    raised |= set(LAUNCH.MODEL_VARIABLES.values())

    assert raised == set(LAUNCH.REFUSALS)


def test_the_launcher_states_nothing_that_belongs_to_one_machine():
    """No home, install or temporary path, no host with a fixed port, and no port but the table's.

    Every number the size of a port is a named module constant, and the one of those that is a
    port is the slot table's base.
    """
    tree = ast.parse(LAUNCHER.read_text(encoding="utf-8"))
    strings = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    machine_paths = ("/Users/", "/home/", "/opt/", "/usr/local/", "/private/", "/tmp", "/var/")
    fixed_hosts = re.compile(r"(localhost|127\.0\.0\.1|\[::1\]|0\.0\.0\.0):\d")
    named = {
        node.targets[0].id: node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Constant)
    }
    port_sized = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and type(node.value) is int
        and 1024 <= node.value <= 65535
    ]
    unnamed = [node.value for node in port_sized if all(node is not v for v in named.values())]
    named_port_sized = {name for name, value in named.items() if value in port_sized}

    assert [text for text in strings if any(marker in text for marker in machine_paths)] == []
    assert [text for text in strings if fixed_hosts.search(text)] == []
    assert unnamed == []
    assert named_port_sized == {"PORT_BASE", "RECORD_EXCERPT_CHARACTERS", "LOG_TAIL_CHARACTERS"}
