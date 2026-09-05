"""Exercise actual launcher signals with an explicit local Docker-protocol stand-in.

These tests verify process/control behavior; they do not claim a real Docker daemon or CUDA run.
The stand-in's daemon state survives CLI exit, reproducing the failure mode being guarded.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from exulanica.reconstruction.gsplat_container import (
    ContainerCleanupUncertain,
    reconcile_container_cleanup,
)


def _docker(tmp_path: Path, **settings):
    fake = tmp_path / "docker-stand-in"
    config = tmp_path / "config.json"
    config.write_text(json.dumps(settings))
    fake.write_text(
        "#!"
        + sys.executable
        + "\n"
        + r"""
import json,os,signal,sys,time
from pathlib import Path
root=Path(__file__).parent
config=json.loads((root/"config.json").read_text())
state_path=root/"daemon.json"
operation=sys.argv[1]
with (root/"calls.jsonl").open("a") as stream:
    stream.write(json.dumps(sys.argv[1:])+"\n")
def state():
    return json.loads(state_path.read_text()) if state_path.exists() else None
def save(value):
    state_path.write_text(json.dumps(value))
if operation=="run":
    cidfile,owner=sys.argv[2:]
    guard=json.loads((Path(cidfile).parent.parent/"container-cleanup-required.json").read_text())
    assert guard["owner_label"]==owner
    save({"id":"c"*64,"owner":owner,"running":True,"cli_pid":os.getpid()})
    if not config.get("omit_cidfile"):
        Path(cidfile).write_text("c"*64)
    if config.get("disconnected_cli"):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM,signal.SIG_IGN)
    signal.signal(signal.SIGUSR1,lambda *args: sys.exit(75))
    signal.signal(signal.SIGUSR2,lambda *args: sys.exit(137))
    time.sleep(.1)
    os.kill(os.getppid(),signal.SIGTERM)
    if config.get("exit_after_signal"):
        raise SystemExit(0)
    while True:
        time.sleep(.05)
elif operation=="ps":
    value=state()
    if value is not None:
        print(value["id"])
elif operation=="inspect":
    if config.get("inspection_unavailable"):
        print("Docker daemon unavailable",file=sys.stderr)
        raise SystemExit(1)
    value=state()
    if value is None:
        print("No such container",file=sys.stderr)
        raise SystemExit(1)
    owner="another-owner" if config.get("foreign_owner") else value["owner"]
    print(owner+"|"+str(value["running"]).lower())
elif operation in {"stop","kill"}:
    value=state()
    if operation=="stop" and config.get("ignore_stop"):
        raise SystemExit(0)
    value["running"]=False
    save(value)
    try:
        os.kill(value["cli_pid"],signal.SIGUSR1 if operation=="stop" else signal.SIGUSR2)
    except ProcessLookupError:
        pass
"""
    )
    fake.chmod(0o700)
    return fake


def _run(tmp_path: Path, **settings):
    fake = _docker(tmp_path, **settings)
    output = tmp_path / "output"
    output.mkdir()
    (output / ".containers").mkdir()
    (output / "checkpoint.pt").write_bytes(b"private-checkpoint-test-only")
    owner = "a" * 32
    cidfile = output / ".containers" / f"{owner}.cid"
    program = r"""
from pathlib import Path
import json,sys
from exulanica.reconstruction import gsplat_container
fake,output,cidfile,owner=sys.argv[1:]
# Force the race into the interval between polls: the CLI sends its signal and exits while
# the actual launcher is sleeping, so the next poll observes an already-exited CLI.
if json.loads((Path(fake).parent/"config.json").read_text()).get("exit_after_signal"):
    original_sleep=gsplat_container.time.sleep
    gsplat_container.time.sleep=lambda delay: original_sleep(max(delay,.3))
result=gsplat_container.run_managed_container((fake,"run",cidfile,owner), output=Path(output),
    cidfile=Path(cidfile),owner=owner,docker=fake,grace_seconds=0,startup_wait_seconds=.05)
print(result)
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(fake), str(output), str(cidfile), owner],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return int(result.stdout.strip()), fake, output


def test_stop_signal_uses_daemon_stop_and_confirms_exit_before_returning(tmp_path):
    result, _, output = _run(tmp_path)
    calls = [json.loads(row) for row in (tmp_path / "calls.jsonl").read_text().splitlines()]
    assert result == 75
    assert any(call[0] == "stop" and call[-1] == "c" * 64 for call in calls)
    assert json.loads((tmp_path / "daemon.json").read_text())["running"] is False
    assert not (output / "container-cleanup-required.json").exists()


def test_ignored_stop_requires_confirmed_daemon_kill_and_never_claims_checkpoint(tmp_path):
    result, _, output = _run(tmp_path, ignore_stop=True)
    calls = [json.loads(row) for row in (tmp_path / "calls.jsonl").read_text().splitlines()]
    assert result == 137
    assert any(call[0] == "kill" for call in calls)
    assert json.loads((tmp_path / "daemon.json").read_text())["running"] is False
    assert not (output / "container-cleanup-required.json").exists()


def test_uncertain_daemon_retains_marker_and_only_reconciles_after_confirmation(tmp_path):
    result, fake, output = _run(tmp_path, inspection_unavailable=True)
    marker = output / "container-cleanup-required.json"
    assert result == 76 and marker.exists()
    assert (output / "checkpoint.pt").read_bytes() == b"private-checkpoint-test-only"
    try:
        reconcile_container_cleanup(output, docker=str(fake))
    except ContainerCleanupUncertain:
        pass
    else:
        raise AssertionError("unconfirmed daemon state cleared cleanup guard")
    assert marker.exists()
    (tmp_path / "config.json").write_text("{}")
    reconcile_container_cleanup(output, docker=str(fake))
    assert not marker.exists()
    assert json.loads((tmp_path / "daemon.json").read_text())["running"] is False


def test_foreign_container_id_is_never_stopped(tmp_path):
    result, _, output = _run(tmp_path, foreign_owner=True)
    calls = [json.loads(row) for row in (tmp_path / "calls.jsonl").read_text().splitlines()]
    assert result == 76 and (output / "container-cleanup-required.json").exists()
    assert not any(call[0] in {"stop", "kill"} for call in calls)


def test_exited_cli_cannot_leave_its_daemon_container_running(tmp_path):
    result, _, output = _run(tmp_path, disconnected_cli=True)
    assert result == 0
    assert json.loads((tmp_path / "daemon.json").read_text())["running"] is False
    assert not (output / "container-cleanup-required.json").exists()


def test_cli_exiting_after_stop_request_still_requires_daemon_confirmation(tmp_path):
    result, _, output = _run(tmp_path, exit_after_signal=True)
    assert result == 0
    assert json.loads((tmp_path / "daemon.json").read_text())["running"] is False
    assert not (output / "container-cleanup-required.json").exists()


def test_interrupted_creation_without_cidfile_keeps_guard_until_label_reconciliation(tmp_path):
    result, fake, output = _run(tmp_path, omit_cidfile=True)
    assert result == 76
    assert (output / "container-cleanup-required.json").exists()
    (tmp_path / "config.json").write_text("{}")
    reconcile_container_cleanup(output, docker=str(fake))
    assert not (output / "container-cleanup-required.json").exists()
    assert json.loads((tmp_path / "daemon.json").read_text())["running"] is False
