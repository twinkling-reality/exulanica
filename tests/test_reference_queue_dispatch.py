"""A rented worker cannot spend a newly queued pass on an older job's final attempt."""

import json
import os
import subprocess
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from exulanica.ingest import scene_worker, scene_worker_command
from exulanica.ingest.spine.reconstruction_jobs import MAX_SCENE_CLAIMS
from scripts import queue_reference_reconstruction as queue

from test_reconstruction_scene_jobs import _captures, _enqueue

ROOT = Path(__file__).resolve().parents[1]


def test_unscoped_gpu_pass_is_refused_before_docker(tmp_path):
    docker = tmp_path / "docker"
    marker = tmp_path / "called"
    docker.write_text(f'#!/bin/sh\ntouch "{marker}"\necho image@sha256:abc\n')
    docker.chmod(0o755)
    env = {key: value for key, value in os.environ.items() if not key.startswith("EXULANICA_")}
    env.update(
        PATH=f"{tmp_path}:/usr/bin:/bin",
        CODE_REVISION="a" * 40,
        EXULANICA_WORKSPACE_IDS=str(uuid.uuid4()),
        EXULANICA_DATABASE_URL="unused",
    )
    result = subprocess.run(
        [
            "bash",
            str(ROOT / "deploy/gsplat/run-scene-worker.sh"),
            "exulanica-scene-worker",
            "--once",
        ],
        env=env,
        capture_output=True,
    )
    assert result.returncode != 0
    assert not marker.exists(), "unscoped launch reached Docker before refusing the drain"


def test_queue_dispatch_preserves_an_older_jobs_final_attempt(ingest_spine, monkeypatch, tmp_path):
    repository, reopen = ingest_spine
    older, _ = _enqueue(repository, _captures(repository))
    repository.connection.execute(
        "update reconstruction_scene_job set attempts=%s where job_id=%s",
        (MAX_SCENE_CLAIMS - 1, older),
    )
    captures = _captures(repository, start=3)
    files = [{"sha256": f"{i:064x}"} for i in range(3)]
    manifest = {"record_sha256": "a" * 64, "record": {"files": files}}
    (tmp_path / "intake.json").write_text(
        json.dumps(
            {
                "source_manifest_sha256": manifest["record_sha256"],
                "refused": [],
                "accepted": [
                    {"blob_sha256": row["sha256"], "capture_id": str(capture)}
                    for row, capture in zip(files, captures, strict=True)
                ],
            }
        )
    )
    monkeypatch.setattr(queue, "read_manifest", lambda path: manifest)
    session_active = False

    class TestDatabase:
        @contextmanager
        def session(self, workspace):
            nonlocal session_active
            session_active = True
            try:
                connection = reopen().connection
                with connection.transaction():
                    yield connection
            finally:
                session_active = False

    monkeypatch.setattr(queue.Database, "from_env", lambda: TestDatabase())
    selected = []

    def enqueue(repo, members, **kwargs):
        job, inserted = _enqueue(repo, members)
        selected.append(job)
        return SimpleNamespace(job_id=job, inserted=inserted, member_count=len(members))

    monkeypatch.setattr(queue, "enqueue_exact_scene_reconstruction", enqueue)
    processed = []

    class Processor:
        def __init__(self, *args, **kwargs):
            pass

        def process(self, claimed):
            processed.append(claimed.job_id)
            return SimpleNamespace(status="failed")

    monkeypatch.setattr(scene_worker, "SceneReconstructionProcessor", Processor)
    monkeypatch.setenv("EXULANICA_SCENE_JOB_IDS", str(older))

    def launch(command, *, env):
        assert not session_active, "dispatch must follow the queue session"
        assert command[0] == "scripted-worker"
        index = command.index("--job")
        assert command[index + 1] == str(selected[0])
        worker = scene_worker.SceneReconstructionWorker(
            TestDatabase(),
            object(),
            tmp_path / "scratch",
            frozenset({repository.workspace_id}),
            name="scripted",
            code_revision="a" * 40,
            execution_image="image@sha256:" + "b" * 64,
            job_ids=scene_worker_command.parse_job_ids([command[index + 1]], env),
        )
        outcomes = worker.drain_observed()
        assert len(outcomes) == 1
        return 7

    monkeypatch.setattr(subprocess, "call", launch)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "queue",
            "--workspace",
            str(repository.workspace_id),
            "--actor",
            str(uuid.uuid4()),
            "--directory",
            str(tmp_path),
            "--worker-command",
            "scripted-worker",
        ],
    )
    assert queue.main() == 7
    assert processed == selected
    row = (
        reopen()
        .connection.execute(
            "select attempts,status from reconstruction_scene_job where job_id=%s", (older,)
        )
        .fetchone()
    )
    assert row == {"attempts": MAX_SCENE_CLAIMS - 1, "status": "queued"}


@pytest.mark.parametrize(
    "argument", ["--job", "--job=bad", "--workspace", "--workspace=bad", "--j=bad", "--w", "--"]
)
def test_dispatch_rejects_scope_overrides_before_queueing(monkeypatch, tmp_path, argument):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "queue",
            "--workspace",
            str(uuid.uuid4()),
            "--actor",
            str(uuid.uuid4()),
            "--directory",
            str(tmp_path),
            "--worker-command",
            "worker",
            argument,
        ],
    )
    with pytest.raises(SystemExit):
        queue.main()


@pytest.mark.parametrize("job_arguments", [["--job"], ["--job="]])
def test_gpu_cli_scope_replaces_stale_host_scope(tmp_path, job_arguments):
    selected, stale = str(uuid.uuid4()), str(uuid.uuid4())
    docker = tmp_path / "docker"
    marker = tmp_path / "arguments.json"
    docker.write_text(
        f"#!{sys.executable}\nimport json,sys\n"
        'if sys.argv[1] == "inspect":\n    print("image@sha256:abc")\n'
        f'else:\n    open({str(marker)!r}, "w").write(json.dumps(sys.argv[1:]))\n'
    )
    docker.chmod(0o755)
    stat = tmp_path / "stat"
    stat.write_text("#!/bin/sh\necho 0\n")
    stat.chmod(0o755)
    env = {key: value for key, value in os.environ.items() if not key.startswith("EXULANICA_")}
    env.update(
        PATH=f"{tmp_path}:/usr/bin:/bin",
        HOME=str(tmp_path),
        CODE_REVISION="a" * 40,
        EXULANICA_WORKSPACE_IDS=str(uuid.uuid4()),
        EXULANICA_DATABASE_URL="unused",
        EXULANICA_SCENE_JOB_IDS=stale,
    )
    scope = ["--job", selected] if job_arguments == ["--job"] else [f"--job={selected}"]
    result = subprocess.run(
        [
            "bash",
            str(ROOT / "deploy/gsplat/run-scene-worker.sh"),
            "exulanica-scene-worker",
            "--once",
            *scope,
        ],
        env=env,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    args = json.loads(marker.read_text())
    assert f"EXULANICA_SCENE_JOB_IDS={selected}" in args
    assert not any(stale in argument for argument in args)
