"""The generated asset job: tree checks, the shared runner, the stand-ins and the Nebius commands.

Expected values come from git itself (tree ids), from hand-built pictures and from fake aws and
nebius executables that record what they were asked, never from the code under test.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
from pathlib import Path

import numpy as np
import pytest
from conftest import REPOSITORY
from exulanica_pieces.budgets import read_budgets
from exulanica_pieces.canonical import Refused, sha256_hex
from exulanica_pieces.records import build_job, build_request, read_receipt

from exulanica_appearance.assets import nebius, remote
from exulanica_appearance.assets.backends.step1x import project_colours
from exulanica_appearance.assets.dryrun import STUB_PACK, StubBackend, dry_run
from exulanica_appearance.assets.gittree import tree_id
from exulanica_appearance.assets.job import run_job

BUDGETS = read_budgets(REPOSITORY)

STANDINS = Path(__file__).resolve().parents[1] / "container" / "assets" / "standins"
GIT = shutil.which("git")


def _git(cwd: Path, *arguments: str) -> str:
    environment = dict(
        os.environ,
        GIT_AUTHOR_NAME="t",
        GIT_AUTHOR_EMAIL="t@t",
        GIT_COMMITTER_NAME="t",
        GIT_COMMITTER_EMAIL="t@t",
    )
    environment.pop("GIT_INDEX_FILE", None)
    environment.pop("GIT_DIR", None)
    return subprocess.run(
        ["git", *arguments], cwd=cwd, check=True, capture_output=True, text=True, env=environment
    ).stdout.strip()


@pytest.fixture
def upstream_repository(tmp_path: Path) -> tuple[Path, str, str]:
    """A small repository with an executable, a symlink, git's tree-name ordering case and a gitlink."""
    root = tmp_path / "upstream"
    (root / "a").mkdir(parents=True)
    (root / "a" / "inner.py").write_text("x = 1\n")
    (root / "a.b").write_text("sorted before a/ by git's rule\n")
    (root / "run.sh").write_text("#!/bin/sh\necho hi\n")
    (root / "run.sh").chmod(0o755)
    (root / "link").symlink_to("a/inner.py")
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_text("from . import data, models, systems\n")
    _git(root, "init", "-q")
    _git(root, "add", ".")
    sub = "1" * 40
    _git(root, "update-index", "--add", "--cacheinfo", f"160000,{sub},sub")
    _git(root, "commit", "-q", "-m", "c")
    return root, _git(root, "rev-parse", "HEAD^{tree}"), sub


@pytest.mark.skipif(GIT is None, reason="git is not on PATH")
def test_the_tree_id_is_git_s_own(
    upstream_repository: tuple[Path, str, str], tmp_path: Path
) -> None:
    root, expected, sub = upstream_repository
    archive = tmp_path / "archive.tar"
    _git(root, "archive", "--format=tar", "--prefix=top/", "-o", str(archive), "HEAD")
    with tarfile.open(archive) as tar:
        tar.extractall(tmp_path / "x", filter="data")
    (tmp_path / "x" / "top" / "sub").mkdir(exist_ok=True)
    assert tree_id(tmp_path / "x" / "top", {"sub": sub}) == expected
    (tmp_path / "x" / "top" / "a" / "inner.py").write_text("x = 2\n")
    assert tree_id(tmp_path / "x" / "top", {"sub": sub}) != expected
    (tmp_path / "x" / "top" / "a" / "inner.py").write_text("x = 1\n")
    (tmp_path / "x" / "top" / "run.sh").chmod(0o644)
    assert tree_id(tmp_path / "x" / "top", {"sub": sub}) != expected


@pytest.mark.skipif(GIT is None, reason="git is not on PATH")
def test_fetched_upstream_is_held_to_its_tree_and_patched_once(
    upstream_repository: tuple[Path, str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, expected, sub = upstream_repository
    archive = tmp_path / "archive.tar"
    _git(root, "archive", "--format=tar", "--prefix=top/", "-o", str(archive), "HEAD")

    def fake_archive(repository: str, commit: str, into: Path) -> Path:
        with tarfile.open(archive) as tar:
            tar.extractall(into, filter="data")
        return into / "top"

    monkeypatch.setattr(remote, "_archive", fake_archive)
    source = {
        "name": "up",
        "repository": "o/r",
        "commit": "2" * 40,
        "tree": expected,
        "routes": ["A"],
        "gitlinks": {"sub": sub},
        "patch": {
            "file": "pkg/__init__.py",
            "replace": "from . import data, models, systems",
            "with": "from . import models",
        },
    }
    held = remote.fetch_upstream([source], "A", tmp_path / "out")
    assert held == {"up": expected}
    assert (tmp_path / "out" / "up" / "pkg" / "__init__.py").read_text() == "from . import models\n"
    assert remote.fetch_upstream([source], "B", tmp_path / "other") == {}
    with pytest.raises(Refused, match="has tree"):
        remote.fetch_upstream([dict(source, tree="3" * 40)], "A", tmp_path / "out2")
    with pytest.raises(Refused, match="exactly once"):
        remote.fetch_upstream(
            [dict(source, patch=dict(source["patch"], replace="absent line"))],
            "A",
            tmp_path / "out3",
        )


def test_route_b_starts_from_route_a_s_cut_outs(repository: Path, tmp_path: Path) -> None:
    first = dry_run(repository, tmp_path / "a")
    bench = next(item for item in first["pieces"] if item["look_role"] == "prop.bench")
    receipts = [json.loads(p.read_bytes()) for p in (tmp_path / "a" / "receipts").glob("*.json")]
    receipt = next(r for r in receipts if r["output"]["sha256"] == bench["piece"])
    cutout_sha256 = receipt["inputs"]["cutout"]
    cutout = (tmp_path / "a" / "inputs" / f"{cutout_sha256}.png").read_bytes()
    request = build_request(
        budgets=BUDGETS,
        pack=STUB_PACK,
        variants=1,
        route="S",
        look_role="prop.bench",
        slot_mm={"width": 1800, "height": 900, "depth": 700},
    )
    job = build_job(
        budgets=BUDGETS,
        route="S",
        components_sha256="1" * 64,
        requests=[request],
        code_sha256="2" * 64,
        container="stub",
        estimate_seconds=1,
        cutouts={(sha256_hex(request), 0): cutout_sha256},
    )
    results = run_job(
        job_raw=job,
        requests=[request],
        backend=StubBackend(),
        repository=repository,
        out=tmp_path / "b",
        cutouts={cutout_sha256: cutout},
    )
    [item] = results["items"]
    second = json.loads((tmp_path / "b" / "receipts" / f"{item['receipt']}.json").read_bytes())
    assert second["inputs"]["cutout"] == cutout_sha256
    assert "concept_picture" not in second["inputs"]
    read_receipt(
        json.dumps(second, sort_keys=True, separators=(",", ":")).encode(), json.loads(request)
    )
    missing = run_job(
        job_raw=job,
        requests=[request],
        backend=StubBackend(),
        repository=repository,
        out=tmp_path / "c",
        cutouts={},
    )
    assert "not given" in missing["items"][0]["refused"]


def test_one_item_s_failure_is_recorded_and_the_run_goes_on(
    repository: Path, tmp_path: Path
) -> None:
    class Flaky(StubBackend):
        def mesh(self, cutout, seed, request):  # type: ignore[no-untyped-def]
            if request["look_role"] == "plant.tree":
                raise RuntimeError("CUDA out of memory (simulated)")
            return super().mesh(cutout, seed, request)

    requests = [
        build_request(
            budgets=BUDGETS,
            pack=STUB_PACK,
            variants=1,
            route="S",
            look_role=role,
            slot_mm={"width": 1800, "height": 2000, "depth": 900},
        )
        for role in ("plant.tree", "prop.bench")
    ]
    job = build_job(
        budgets=BUDGETS,
        route="S",
        components_sha256="1" * 64,
        requests=requests,
        code_sha256="2" * 64,
        container="stub",
        estimate_seconds=1,
    )
    results = run_job(
        job_raw=job, requests=requests, backend=Flaky(), repository=repository, out=tmp_path
    )
    outcomes = {item.get("look_role", "?"): item for item in results["items"]}
    assert results["items"][0]["failed"] == "RuntimeError: CUDA out of memory (simulated)"
    assert outcomes["prop.bench"]["within"] is True


def test_colour_projection_takes_the_cut_out_s_colour_seen_from_the_front() -> None:
    picture = np.zeros((10, 20, 4), dtype=np.uint8)
    picture[2:8, 2:10] = (200, 30, 30, 255)
    picture[2:8, 10:18] = (30, 30, 200, 255)
    vertices = np.array([[-1.0, 0.5, 0.0], [1.0, 0.5, 0.3], [-1.0, -1.0, -0.4], [1.0, 1.0, 0.0]])
    colours = project_colours(vertices, picture)
    assert colours[0].tolist() == [200, 30, 30]
    assert colours[1].tolist() == [30, 30, 200]


def test_the_stand_ins_do_their_one_thing_and_refuse_the_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(STANDINS))
    for name in ("easydict", "plyfile", "rembg", "kaolin.utils.testing"):
        sys.modules.pop(name, None)
    from easydict import EasyDict
    from kaolin.utils.testing import check_tensor
    from plyfile import PlyData

    settings = EasyDict({"a": {"b": 1}, "c": [{"d": 2}]})
    assert settings.a.b == 1 and settings.c[0].d == 2
    settings.e = 3
    assert settings["e"] == 3
    assert check_tensor(np.zeros((2, 3)), shape=(None, 3))
    with pytest.raises(ValueError, match="shape"):
        check_tensor(np.zeros((2, 4)), shape=(None, 3))
    with pytest.raises(RuntimeError, match="PLY"):
        PlyData()
    for name in ("easydict", "plyfile", "kaolin.utils.testing", "kaolin.utils", "kaolin"):
        sys.modules.pop(name, None)


def test_the_code_archive_is_the_same_bytes_twice_and_holds_no_compiled_files(
    repository: Path,
) -> None:
    first = nebius.code_archive(repository)
    assert first == nebius.code_archive(repository)
    with tarfile.open(fileobj=io.BytesIO(first)) as tar:
        names = tar.getnames()
    assert "assets/colour/srgb8-linear16.v1.json" in names
    assert "ml/appearance/container/assets/job.sh" in names
    assert not any("__pycache__" in name or name.endswith(".pyc") for name in names)
    assert not any(name.startswith("ml/appearance/tests") for name in names)


def _arguments(**changes: object) -> list[str]:
    values: dict[str, object] = {
        "route": "A",
        "job_sha256": "a" * 64,
        "code_sha256": "b" * 64,
        "bucket_id": "bucket-1",
        "subnet_id": "subnet-1",
        "platform": "gpu-rtx6000-a",
        "preset": "1gpu",
        "timeout_seconds": 5400,
        "rate_cents_per_hour": 180,
        "bound_cents": 500,
        "preemptible": False,
        "profile": "exulanica-gen",
    }
    values.update(changes)
    return nebius.submit_arguments(**values)  # type: ignore[arg-type]


def test_submit_refuses_a_worst_case_over_the_bound() -> None:
    # 5400 s at 180 cents an hour is 270 cents.
    assert nebius.worst_case_cents(5400, 180) == 270
    command = _arguments()
    assert command[command.index("--timeout") + 1] == "5400s"
    assert "STOP_SECONDS=5400" in command
    with pytest.raises(Refused, match="over the allocated 269"):
        _arguments(bound_cents=269)
    # A stop shorter than the service's one-hour floor still risks an hour: 180 cents.
    short = _arguments(timeout_seconds=900, bound_cents=180)
    assert short[short.index("--timeout") + 1] == "3600s" and "STOP_SECONDS=900" in short
    with pytest.raises(Refused):
        _arguments(timeout_seconds=900, bound_cents=179)
    with pytest.raises(Refused, match="route A or B"):
        _arguments(route="S")


def _fake(bin_directory: Path, name: str, log: Path, reply: str) -> None:
    script = bin_directory / name
    script.write_text(
        "#!/bin/sh\n"
        f'printf "%s|" "{name}" "$@" >> "{log}"\n'
        f'printf "AWS_SHARED_CREDENTIALS_FILE=%s KEY=%s\\n" "${{AWS_SHARED_CREDENTIALS_FILE:-}}" "${{AWS_ACCESS_KEY_ID:-}}" >> "{log}"\n'
        f"printf '%s' '{reply}'\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)


def test_stage_and_submit_call_the_clis_with_no_key_in_the_environment(
    repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_directory = tmp_path / "bin"
    bin_directory.mkdir()
    log = tmp_path / "calls.log"
    _fake(bin_directory, "aws", log, "")
    _fake(bin_directory, "nebius", log, '{"metadata": {"id": "aijob-1"}}')
    monkeypatch.setenv("PATH", f"{bin_directory}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "must-not-reach-aws")
    monkeypatch.delenv("EXULANICA_GEN_S3_CREDENTIALS", raising=False)
    requests = tmp_path / "requests"
    requests.mkdir()
    request = build_request(
        budgets=BUDGETS,
        pack=STUB_PACK,
        variants=1,
        route="A",
        look_role="prop.bench",
        slot_mm={"width": 1800, "height": 900, "depth": 700},
    )
    (requests / f"{sha256_hex(request)}.json").write_bytes(request)
    job = tmp_path / "job.json"
    job.write_bytes(
        build_job(
            budgets=BUDGETS,
            route="A",
            components_sha256="1" * 64,
            requests=[request],
            code_sha256="2" * 64,
            container="sha256:" + "3" * 64,
            estimate_seconds=600,
        )
    )
    with pytest.raises(Refused, match="EXULANICA_GEN_S3_CREDENTIALS"):
        nebius.stage(
            repository=repository, job=job, requests=requests, bucket="gen", region="us-central1"
        )
    monkeypatch.setenv("EXULANICA_GEN_S3_CREDENTIALS", "/elsewhere/credentials")
    staged = nebius.stage(
        repository=repository, job=job, requests=requests, bucket="gen", region="us-central1"
    )
    assert staged["job_sha256"] == sha256_hex(job.read_bytes())
    calls = log.read_text()
    assert "--endpoint-url|https://storage.us-central1.nebius.cloud|" in calls
    assert f"s3://gen/runs/{staged['job_sha256']}/|" in calls
    assert "AWS_SHARED_CREDENTIALS_FILE=/elsewhere/credentials KEY=\n" in calls
    created = nebius.submit(
        route="A", job_sha256=staged["job_sha256"], code_sha256=staged["code_sha256"], bucket_id="b", subnet_id="s",
        platform="gpu-rtx6000-a", preset="1gpu", timeout_seconds=900, rate_cents_per_hour=180, bound_cents=500,
        preemptible=False, profile="p",
    )  # fmt: skip
    assert created == {"metadata": {"id": "aijob-1"}}
    assert f"--args|/mnt/data/runs/{staged['job_sha256']}/job.sh|" in log.read_text()


def test_the_job_entry_script_parses() -> None:
    script = Path(__file__).resolve().parents[1] / "container" / "assets" / "job.sh"
    subprocess.run(["sh", "-n", str(script)], check=True)
