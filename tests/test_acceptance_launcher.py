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
import hashlib
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
from exulanica.api.permissions import ACCOUNT_OWNER_PERMISSIONS, Permission

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
            "--society-playback",
            "--society-tick-interval-ms",
            "8000",
        ]
    )

    assert (plain.slot, plain.reuse_database, plain.model, plain.production) == (
        0,
        False,
        False,
        False,
    )
    assert plain.no_derivative_worker is False
    assert (plain.society_playback, plain.society_tick_interval_ms) == (False, None)
    assert (full.society_playback, full.society_tick_interval_ms) == (True, 8000)
    assert (full.slot, full.reuse_database, full.model, full.production) == (3, True, True, True)
    assert full.no_derivative_worker is True


def test_every_command_needs_a_worktree_and_status_and_down_take_no_run_flags():
    parser = LAUNCH.build_parser()
    for command in ("up", "status", "down", "restart-api"):
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


def test_a_slot_outside_the_table_is_refused_by_name():
    assert _refusal(LAUNCH.ports, LAUNCH.SLOT_COUNT) == "slot-out-of-range"
    assert _refusal(LAUNCH.ports, -1) == "slot-out-of-range"


def test_the_multi_client_options_are_off_by_default_so_a_plain_run_is_unchanged():
    plain = LAUNCH.build_parser().parse_args(["up", "--worktree", "w"])

    assert (plain.port_base, plain.workspaces, plain.read_only_token) == (None, 1, False)
    for slot in range(LAUNCH.SLOT_COUNT):
        assert LAUNCH.ports(slot, None) == LAUNCH.ports(slot)
    assert LAUNCH.token_file_name(1) == "token"


def test_a_moved_table_starts_at_the_port_base_and_keeps_five_ports_a_slot():
    parser = LAUNCH.build_parser()
    moved = parser.parse_args(["up", "--worktree", "w", "--port-base", "19430", "--slot", "1"])

    assert moved.port_base == 19430
    assert list(LAUNCH.ports(0, 19430).values()) == list(range(19430, 19435))
    assert list(LAUNCH.ports(1, 19430).values()) == list(range(19435, 19440))
    assert list(LAUNCH.ports(1, 19430)) == list(LAUNCH.PORT_ROLES)


def test_a_port_base_that_puts_a_port_outside_the_unprivileged_range_is_refused():
    assert _refusal(LAUNCH.ports, 0, LAUNCH.PORT_MINIMUM - 1) == "port-base-out-of-range"
    assert _refusal(LAUNCH.ports, 0, LAUNCH.PORT_MAXIMUM - 3) == "port-base-out-of-range"
    assert _refusal(LAUNCH.ports, LAUNCH.SLOT_COUNT, 19430) == "slot-out-of-range"
    assert LAUNCH.ports(0, LAUNCH.PORT_MAXIMUM - 4)["spare"] == LAUNCH.PORT_MAXIMUM


def test_workspaces_are_counted_from_one_to_the_maximum_and_each_later_one_has_its_own_file():
    assert LAUNCH.workspace_count(1) == 1
    assert LAUNCH.workspace_count(LAUNCH.WORKSPACES_MAXIMUM) == LAUNCH.WORKSPACES_MAXIMUM
    assert _refusal(LAUNCH.workspace_count, 0) == "workspaces-out-of-range"
    assert _refusal(LAUNCH.workspace_count, LAUNCH.WORKSPACES_MAXIMUM + 1) == (
        "workspaces-out-of-range"
    )
    names = [LAUNCH.token_file_name(index) for index in range(1, LAUNCH.WORKSPACES_MAXIMUM + 1)]
    assert names[:2] == ["token", "token-2"]
    assert len(set(names)) == len(names)
    assert "token-read" not in names


def test_the_read_only_token_grants_world_read_alone():
    parser = LAUNCH.build_parser()
    assert parser.parse_args(["up", "--worktree", "w", "--read-only-token"]).read_only_token
    assert (Permission.WORLD_READ.value,) == LAUNCH.READ_ONLY_PERMISSIONS
    assert set(LAUNCH.READ_ONLY_PERMISSIONS) < set(LAUNCH.PERMISSIONS)


def test_up_refuses_a_workspace_count_out_of_range_before_it_starts_anything(tmp_path, temporary):
    worktree = _checkout(tmp_path / "checkout")
    arguments = LAUNCH.build_parser().parse_args(
        ["up", "--worktree", str(worktree), "--workspaces", "0"]
    )

    assert _refusal(LAUNCH.up, arguments) == "workspaces-out-of-range"
    assert not LAUNCH.state_dir(worktree).exists()


def _recorded_run(run_dir: Path, *, others: int = 0, read_only: bool = False) -> dict:
    """A run's state as ``up`` records it, with its token files written."""
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "token").write_text("primary-token")
    state: dict = {
        "workspace_id": "w1",
        "actor": "a1",
        "permissions": list(LAUNCH.PERMISSIONS),
    }
    if others:
        state["other_workspaces"] = []
        for index in range(2, others + 2):
            name = LAUNCH.token_file_name(index)
            (run_dir / name).write_text(f"token-of-{index}")
            state["other_workspaces"].append(
                {
                    "workspace_id": f"w{index}",
                    "actor": f"a{index}",
                    "token_file": str(run_dir / name),
                }
            )
    if read_only:
        (run_dir / "token-read").write_text("read-token")
        state["read_only_token"] = {
            "token_file": str(run_dir / "token-read"),
            "workspace_id": "w1",
            "actor": "r1",
            "permissions": list(LAUNCH.READ_ONLY_PERMISSIONS),
        }
    return state


def test_restart_rebuilds_every_grant_the_run_started_with_by_token_file(tmp_path):
    state = _recorded_run(tmp_path / "run", others=1, read_only=True)

    grants = LAUNCH.recorded_grants(state, tmp_path / "run")

    assert sorted(grants) == ["token", "token-2", "token-read"]
    assert grants["token"] == {
        "workspace_id": "w1",
        "actor": "a1",
        "permissions": list(LAUNCH.PERMISSIONS),
    }
    assert grants["token-2"]["workspace_id"] == "w2"
    assert grants["token-read"]["permissions"] == list(LAUNCH.READ_ONLY_PERMISSIONS)


def test_the_peer_token_is_a_second_actor_in_the_first_workspace_and_survives_restart(tmp_path):
    state = _recorded_run(tmp_path / "run")
    (tmp_path / "run" / LAUNCH.PEER_TOKEN_NAME).write_text("peer-token")
    state["peer_token"] = {
        "token_file": str(tmp_path / "run" / LAUNCH.PEER_TOKEN_NAME),
        "workspace_id": "w1",
        "actor": "p1",
        "permissions": list(LAUNCH.PERMISSIONS),
    }

    grants = LAUNCH.recorded_grants(state, tmp_path / "run")

    assert grants[LAUNCH.PEER_TOKEN_NAME]["workspace_id"] == grants["token"]["workspace_id"]
    assert grants[LAUNCH.PEER_TOKEN_NAME]["actor"] != grants["token"]["actor"]
    assert grants[LAUNCH.PEER_TOKEN_NAME]["permissions"] == grants["token"]["permissions"]


def test_the_peer_token_and_second_api_are_off_by_default_and_parse_when_asked():
    parser = LAUNCH.build_parser()
    plain = parser.parse_args(["up", "--worktree", "w"])
    asked = parser.parse_args(["up", "--worktree", "w", "--peer-token", "--second-api"])

    assert (plain.peer_token, plain.second_api) == (False, False)
    assert (asked.peer_token, asked.second_api) == (True, True)
    assert parser.parse_args(["restart-api", "--worktree", "w"]).api == "primary"
    assert parser.parse_args(["restart-api", "--worktree", "w", "--api", "second"]).api == "second"
    with pytest.raises(SystemExit), redirect_stderr(io.StringIO()):
        parser.parse_args(["restart-api", "--worktree", "w", "--api", "third"])


def test_restarting_a_second_api_the_run_never_started_is_refused(tmp_path, temporary):
    worktree = _checkout(tmp_path / "checkout")
    state_file = LAUNCH.state_dir(worktree) / "state.json"
    state_file.parent.mkdir(parents=True)
    run_dir = tmp_path / "run"
    state = _recorded_run(run_dir)
    run_dir.joinpath("logs").mkdir()
    state.update({"run_dir": str(run_dir), "pids": {"api": 1}, "data_dir": str(run_dir)})
    state_file.write_text(json.dumps(state))
    arguments = LAUNCH.build_parser().parse_args(
        ["restart-api", "--worktree", str(worktree), "--api", "second"]
    )

    assert _refusal(LAUNCH.restart_api, arguments) == "no-second-api"


def test_a_plain_run_restarts_with_its_one_grant(tmp_path):
    grants = LAUNCH.recorded_grants(_recorded_run(tmp_path / "run"), tmp_path / "run")
    assert list(grants) == ["token"]


def test_a_recorded_token_file_that_is_gone_is_refused_rather_than_dropped(tmp_path):
    state = _recorded_run(tmp_path / "run", others=1)
    (tmp_path / "run" / "token-2").unlink()

    assert _refusal(LAUNCH.recorded_grants, state, tmp_path / "run") == "token-file-unknown"


def test_restart_api_takes_a_revoked_token_file_and_no_run_flags():
    parser = LAUNCH.build_parser()
    plain = parser.parse_args(["restart-api", "--worktree", "w"])
    revoking = parser.parse_args(["restart-api", "--worktree", "w", "--revoke", "token-2"])

    assert (plain.revoke, revoking.revoke) == (None, "token-2")
    with pytest.raises(SystemExit), redirect_stderr(io.StringIO()):
        parser.parse_args(["restart-api", "--worktree", "w", "--production"])
    with pytest.raises(SystemExit), redirect_stderr(io.StringIO()):
        parser.parse_args(["up", "--worktree", "w", "--revoke", "token-2"])


def test_restart_api_with_nothing_recorded_is_refused(tmp_path, temporary):
    worktree = _checkout(tmp_path / "checkout")
    arguments = LAUNCH.build_parser().parse_args(["restart-api", "--worktree", str(worktree)])

    assert _refusal(LAUNCH.restart_api, arguments) == "no-state"


def test_the_api_command_is_unchanged_without_a_plan_and_scripted_with_one(tmp_path):
    python, worktree = tmp_path / "python", tmp_path / "tree"
    plain = LAUNCH.api_command(python, worktree, 19431, None)
    scripted = LAUNCH.api_command(python, worktree, 19431, tmp_path / "plan.json")

    assert plain == [str(python), "-c", LAUNCH.API_WRAPPER, str(worktree), "19431"]
    assert scripted[:2] == [str(python), "-c"]
    assert scripted[2] == LAUNCH.SCRIPTED_API_WRAPPER
    assert scripted[3:] == [str(worktree), "19431", str(tmp_path / "plan.json")]
    # ``down`` and ``restart-api`` stop an API by this marker in its command line.
    assert LAUNCH.API_MARKER in LAUNCH.SCRIPTED_API_WRAPPER


def test_a_scripted_run_is_refused_with_a_model_or_without_its_plan(tmp_path, temporary):
    worktree = _checkout(tmp_path / "checkout")
    plan = tmp_path / "plan.json"
    plan.write_text("{}")
    parser = LAUNCH.build_parser()

    both = parser.parse_args(
        ["up", "--worktree", str(worktree), "--model", "--scripted-model", str(plan)]
    )
    missing = parser.parse_args(
        ["up", "--worktree", str(worktree), "--scripted-model", str(tmp_path / "absent.json")]
    )

    assert _refusal(LAUNCH.up, both) == "scripted-with-model"
    assert _refusal(LAUNCH.up, missing) == "scripted-plan-missing"
    assert parser.parse_args(["up", "--worktree", "w"]).scripted_model is None
    assert not LAUNCH.state_dir(worktree).exists()


def test_a_scripted_run_always_states_its_spending_authority(tmp_path):
    process = LAUNCH.scripted_environment(tmp_path, tmp_path / "logs", "process")
    durable = LAUNCH.scripted_environment(tmp_path, tmp_path / "logs", "durable")
    parser = LAUNCH.build_parser()

    assert process["EXULANICA_SPENDING"] == "process"
    assert "EXULANICA_SPENDING_WITNESS_DIR" not in process
    assert durable["EXULANICA_SPENDING"] == "durable"
    assert durable["EXULANICA_SPENDING_WITNESS_DIR"] == str(tmp_path / "spending-witness")
    assert parser.parse_args(["up", "--worktree", "w"]).spending == "process"
    with pytest.raises(SystemExit), redirect_stderr(io.StringIO()):
        parser.parse_args(["up", "--worktree", "w", "--spending", "free"])


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
        (
            {
                "NEBIUS_API_KEY": key,
                "EXULANICA_EGRESS_ALLOWLIST": '["https://model.example"]',
                "EXULANICA_BUDGET_USD": "1.00",
            },
            "call-ceiling-missing",
        ),
        (
            {
                "NEBIUS_API_KEY": key,
                "EXULANICA_EGRESS_ALLOWLIST": '["https://model.example"]',
                "EXULANICA_BUDGET_USD": "1.00",
                "EXULANICA_BUDGET_MAX_CALLS": "7000",
            },
            "spending-mode-missing",
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
        "EXULANICA_BUDGET_MAX_CALLS": "7000",
        "EXULANICA_SPENDING": "process",
        "EXULANICA_DATA_DIR": "/elsewhere",
    }
    assert LAUNCH.model_environment(complete) == {
        name: complete[name] for name in LAUNCH.MODEL_VARIABLES
    }


def test_a_durable_model_run_spends_with_the_runs_own_witness(tmp_path):
    durable = {"EXULANICA_SPENDING": "durable"}

    assert LAUNCH.model_witness_environment(durable, tmp_path) == {
        "EXULANICA_SPENDING_WITNESS_DIR": str(tmp_path / LAUNCH.SPENDING_WITNESS_NAME)
    }
    assert LAUNCH.model_witness_environment({"EXULANICA_SPENDING": "process"}, tmp_path) == {}
    assert LAUNCH.model_witness_environment({}, tmp_path) == {}


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


def _api_environment(
    model: bool, environ: dict[str, str], society_playback: dict[str, str] | None = None
) -> dict[str, str]:
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
        society_playback=society_playback or {},
        environ=environ,
    )


def test_the_api_gets_the_model_and_its_bound_only_with_model():
    environ = {
        "NEBIUS_API_KEY": "sk-not-a-real-key",
        "EXULANICA_EGRESS_ALLOWLIST": '["https://model.example"]',
        "EXULANICA_BUDGET_USD": "1.00",
        "EXULANICA_BUDGET_MAX_CALLS": "7000",
        "EXULANICA_SPENDING": "process",
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


_SOCIETY_VARIABLES = ("EXULANICA_SOCIETY_CONTROL_WORKSPACES", "EXULANICA_SOCIETY_TICK_INTERVAL_MS")


def test_society_playback_is_off_unless_asked_and_then_plays_the_runs_workspace_alone():
    # Settings in the caller's shell never reach the API: only the flag turns playback on.
    shell = {
        "EXULANICA_SOCIETY_CONTROL_WORKSPACES": '["00000000-0000-0000-0000-000000000001"]',
        "EXULANICA_SOCIETY_TICK_INTERVAL_MS": "4000",
        "EXULANICA_SOCIETY_CONTROL_WORKER": "on",
    }
    off = _api_environment(False, shell, LAUNCH.society_playback_environment(None, None))
    assert not [name for name in off if name.startswith("EXULANICA_SOCIETY_")]

    workspace = "11111111-2222-3333-4444-555555555555"
    listed = LAUNCH.society_playback_environment(workspace, None)
    at_default = _api_environment(False, shell, listed)
    assert json.loads(at_default["EXULANICA_SOCIETY_CONTROL_WORKSPACES"]) == [workspace]
    assert "EXULANICA_SOCIETY_TICK_INTERVAL_MS" not in at_default
    assert "EXULANICA_SOCIETY_CONTROL_WORKER" not in at_default

    stated = _api_environment(False, {}, LAUNCH.society_playback_environment(workspace, 8000))
    assert {name: stated[name] for name in _SOCIETY_VARIABLES} == {
        "EXULANICA_SOCIETY_CONTROL_WORKSPACES": json.dumps([workspace]),
        "EXULANICA_SOCIETY_TICK_INTERVAL_MS": "8000",
    }


def test_an_interval_without_playback_is_refused_before_anything_starts(tmp_path, temporary):
    assert (
        _refusal(LAUNCH.society_playback_environment, None, 8000)
        == "society-interval-without-playback"
    )
    worktree = _checkout(tmp_path / "checkout")
    arguments = LAUNCH.build_parser().parse_args(
        ["up", "--worktree", str(worktree), "--society-tick-interval-ms", "8000"]
    )
    assert _refusal(LAUNCH.up, arguments) == "society-interval-without-playback"
    assert not list(temporary.iterdir())


def _readyz(**check) -> bytes:
    return json.dumps({"ok": True, "checks": {"society_playback": check}}).encode()


def test_a_playback_run_needs_readiness_to_report_its_one_workspace_played():
    played = {
        "ok": True,
        "configured": True,
        "running": True,
        "base_tick_interval_ms": 8000,
        "listed_workspaces": 1,
        "account_discovery": False,
    }
    assert LAUNCH.society_playback_readiness(_readyz(**played)) == played
    for wrong in (
        {**played, "running": False},
        {**played, "listed_workspaces": 0},
        {**played, "listed_workspaces": 2},
        {**played, "account_discovery": True},
        {"ok": True, "configured": False, "running": False},
    ):
        assert (
            _refusal(LAUNCH.society_playback_readiness, _readyz(**wrong))
            == "society-playback-not-running"
        )
    assert (
        _refusal(LAUNCH.society_playback_readiness, b"not json") == "society-playback-not-running"
    )
    assert (
        _refusal(LAUNCH.society_playback_readiness, b'{"checks": {}}')
        == "society-playback-not-running"
    )


# -- what the launcher states --------------------------------------------------------------------


def test_the_synthetic_grant_is_the_account_owners():
    assert set(LAUNCH.PERMISSIONS) == {permission.value for permission in ACCOUNT_OWNER_PERMISSIONS}
    assert len(LAUNCH.PERMISSIONS) == len(set(LAUNCH.PERMISSIONS))


def test_tiles_add_the_tile_permission_to_the_synthetic_grant_only_when_asked():
    parser = LAUNCH.build_parser()
    assert parser.parse_args(["up", "--worktree", "w"]).tiles is False
    assert parser.parse_args(["up", "--worktree", "w", "--tiles"]).tiles is True
    assert Permission.TILES_MATERIALISE.value == LAUNCH.TILES_PERMISSION
    assert LAUNCH.TILES_PERMISSION not in LAUNCH.PERMISSIONS
    assert LAUNCH.synthetic_permissions(False) == list(LAUNCH.PERMISSIONS)
    assert LAUNCH.synthetic_permissions(True) == [*LAUNCH.PERMISSIONS, LAUNCH.TILES_PERMISSION]


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
    assert named_port_sized == {
        "PORT_BASE",
        "PORT_MINIMUM",
        "PORT_MAXIMUM",
        "RECORD_EXCERPT_CHARACTERS",
        "LOG_TAIL_CHARACTERS",
    }


def test_a_run_publishes_the_character_catalogs_before_its_api_starts(tmp_path):
    """People are drawn only from published catalogs, so a run publishes as a deployment must:
    the owner connection, the run's own data directory, nothing inherited, before the API."""
    import inspect

    launch = _load()
    assert launch.publication_command(Path("/w/.venv/bin/python")) == [
        "/w/.venv/bin/python",
        "-m",
        "exulanica.world.character_catalog_publication",
        "publish",
        "--apply",
    ]
    owner = "postgresql://owner@127.0.0.1:1/exulanica"
    environment = launch.publication_environment(
        owner,
        tmp_path / "data",
        {"PATH": "/usr/bin", "EXULANICA_STORE_KIND": "object", "EXULANICA_DATABASE_URL": "x"},
    )
    assert environment["EXULANICA_DATABASE_URL"] == owner
    assert environment["EXULANICA_DATA_DIR"] == str(tmp_path / "data")
    assert "EXULANICA_STORE_KIND" not in environment
    assert environment["PATH"] == "/usr/bin"
    source = inspect.getsource(launch.up)
    assert source.index("publication_command(") < source.index("api_command(")


def test_a_depth_worker_replaces_the_apis_worker_and_is_refused_beside_it(tmp_path, temporary):
    worktree = _checkout(tmp_path / "checkout")
    arguments = LAUNCH.build_parser().parse_args(
        ["up", "--worktree", str(worktree), "--depth-worker"]
    )
    assert _refusal(LAUNCH.up, arguments) == "depth-worker-shape"
    assert not list(temporary.iterdir())


def test_the_depth_checkpoint_is_the_pinned_revision_in_the_local_cache_or_refused(tmp_path):
    manifest = json.loads((ROOT / "exulanica" / "models" / "models.manifest.json").read_text())
    revision = manifest["local_models"][LAUNCH.DEPTH_MODEL]["revision"]
    cache = tmp_path / "hf"
    environ = {"HF_HOME": str(cache)}
    assert _refusal(LAUNCH.depth_checkpoint, ROOT, environ) == "depth-checkpoint-missing"

    snapshot = cache / "hub" / "models--Ruicheng--moge-2-vitl" / "snapshots"
    (snapshot / "an-older-revision").mkdir(parents=True)
    (snapshot / "an-older-revision" / LAUNCH.DEPTH_CHECKPOINT).write_bytes(b"old")
    assert _refusal(LAUNCH.depth_checkpoint, ROOT, environ) == "depth-checkpoint-missing"

    (snapshot / revision).mkdir()
    (snapshot / revision / LAUNCH.DEPTH_CHECKPOINT).write_bytes(b"pinned weights")
    found = LAUNCH.depth_checkpoint(ROOT, environ)
    assert found["revision"] == revision
    assert found["bytes"] == str(len(b"pinned weights"))
    assert found["sha256"] == hashlib.sha256(b"pinned weights").hexdigest()


def test_database_latency_takes_the_spare_port_and_is_refused_beside_a_second_api(
    tmp_path, temporary
):
    worktree = _checkout(tmp_path / "checkout")
    arguments = LAUNCH.build_parser().parse_args(
        ["up", "--worktree", str(worktree), "--database-latency", "--second-api"]
    )
    assert _refusal(LAUNCH.up, arguments) == "database-latency-shape"
    assert not list(temporary.iterdir())


def test_the_api_alone_connects_through_the_proxy():
    exports = {
        "EXULANICA_DATABASE_URL": "postgresql://exulanica_app:p@127.0.0.1:19430/exulanica",
        "EXULANICA_READONLY_DATABASE_URL": "postgresql://exulanica_read:p@127.0.0.1:19430/exulanica",
        "EXULANICA_PURGE_DATABASE_URL": "postgresql://exulanica_purge:p@127.0.0.1:19430/exulanica",
        "OWNER_URL": "postgresql://owner@127.0.0.1:19430/exulanica",
    }
    proxied = LAUNCH.through_proxy(exports, 19434)

    assert proxied["EXULANICA_DATABASE_URL"].endswith("@127.0.0.1:19434/exulanica")
    assert proxied["EXULANICA_READONLY_DATABASE_URL"].endswith("@127.0.0.1:19434/exulanica")
    assert proxied["EXULANICA_PURGE_DATABASE_URL"] == exports["EXULANICA_PURGE_DATABASE_URL"]
    assert proxied["OWNER_URL"] == exports["OWNER_URL"]


def test_door_bridges_fill_the_run_s_synthetic_workspaces_and_reach_the_api_alone(tmp_path):
    declared = [
        {"bridge": "a", "listed": False, "workspaces": "synthetic"},
        {"bridge": "b", "listed": True},
        {"bridge": "c", "listed": False, "workspaces": ["11111111-1111-1111-1111-111111111111"]},
    ]
    path = tmp_path / "bridges.json"
    path.write_text(json.dumps(declared))
    setting = LAUNCH.door_bridges_setting(path, ["w1", "w2"])
    assert json.loads(setting) == [
        {"bridge": "a", "listed": False, "workspaces": ["w1", "w2"]},
        declared[1],
        declared[2],
    ]
    environment = LAUNCH.api_environment(
        exports={
            "EXULANICA_DATABASE_URL": "u",
            "EXULANICA_READONLY_DATABASE_URL": "r",
            "EXULANICA_PURGE_DATABASE_URL": "p",
        },
        grant={},
        data_dir=tmp_path,
        model=False,
        derivative_worker=True,
        society_playback={},
        door_bridges=setting,
        environ={"EXULANICA_DOOR_BRIDGES": "[]", "HOME": "/home/someone"},
    )
    assert environment["EXULANICA_DOOR_BRIDGES"] == setting
    plain = LAUNCH.build_parser().parse_args(["up", "--worktree", "w"])
    assert plain.door_bridges is None


@pytest.mark.parametrize("written", ["{}", "[1]", "not json"])
def test_a_door_bridges_file_that_is_not_an_array_of_objects_is_refused(tmp_path, written):
    path = tmp_path / "bridges.json"
    path.write_text(written)
    assert _refusal(LAUNCH.door_bridges_setting, path, []) == "door-bridges-file"
