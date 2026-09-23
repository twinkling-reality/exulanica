"""The visual gate recorder writes and removes only inside the document root it is pointed at.

``scripts/record_visual_gate_evidence.py`` writes digest-bound records under ``docs/evaluation/``,
and its baseline and corridor verbs remove an artifacts directory before rewriting it under
``--replace``. Its paths were once bound to the root at import, so a caller that pointed ``ROOT``
at a scratch copy still wrote, and would have removed, through the retained paths. These tests
point the recorder at a scratch root and nothing else, and every path they check lives in
``tmp_path``: none of them touches the retained tree, even to prove it is safe.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "record_visual_gate_evidence.py"


@pytest.fixture
def recorder(tmp_path, monkeypatch):
    """The recorder loaded fresh, with only ROOT pointed at a scratch document root."""
    spec = importlib.util.spec_from_file_location("record_visual_gate_evidence_root", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = (tmp_path / "root").resolve()
    monkeypatch.setattr(module, "ROOT", root)
    _scratch(module, module.REMOVABLE_UNDER).mkdir(parents=True)
    return module


def _scratch(recorder, relative) -> Path:
    """``relative`` under the scratch root, proven to be there before a test creates anything.

    A regression that bound a path to the real root again would otherwise steer the test's own
    setup into the retained tree.
    """
    joined = recorder.ROOT / relative
    assert recorder.ROOT in joined.parents, f"{relative} does not lead into the scratch root"
    return joined


def _outside(tmp_path: Path) -> Path:
    """A directory beside the root holding a file that must survive every refusal."""
    outside = tmp_path / "outside" / "docs" / "evaluation" / "artifacts" / "retained"
    outside.mkdir(parents=True)
    (outside / "sentinel.png").write_bytes(b"retained bytes")
    return outside


def test_the_baseline_artifacts_follow_the_root_the_recorder_is_pointed_at(recorder):
    """Only ROOT is redirected here, which is the redirect that once missed the artifacts."""
    root = recorder.ROOT
    assert recorder._under_root(recorder.ARTIFACTS) == root / recorder.ARTIFACTS
    assert recorder._under_root(recorder.BASELINE) == root / recorder.BASELINE
    assert recorder._under_root(recorder.RECONCILIATION) == root / recorder.RECONCILIATION
    assert recorder._under_root(recorder.RUBRIC_COPY) == root / recorder.RUBRIC_COPY


def test_replacing_the_baseline_artifacts_removes_the_scratch_copy_and_nothing_else(
    recorder, tmp_path
):
    outside = _outside(tmp_path)
    scratch = _scratch(recorder, recorder.ARTIFACTS)
    scratch.mkdir()
    (scratch / "capture-01-route-start.png").write_bytes(b"scratch bytes")
    recorder._remove_directory(recorder.ARTIFACTS)
    assert not scratch.exists()
    assert (outside / "sentinel.png").read_bytes() == b"retained bytes"


def test_a_directory_outside_the_root_is_refused_by_name_and_kept(recorder, tmp_path):
    outside = _outside(tmp_path)
    with pytest.raises(SystemExit, match="outside the document root") as refusal:
        recorder._remove_directory(outside)
    assert str(outside) in str(refusal.value)
    assert (outside / "sentinel.png").read_bytes() == b"retained bytes"


@pytest.mark.parametrize(
    "target",
    [".", "docs", "docs/evaluation", "docs/evaluation/artifacts", "docs/evaluation/artifacts/a/b"],
)
def test_nothing_but_one_artifacts_directory_is_ever_removed(recorder, target):
    kept = _scratch(recorder, "docs/evaluation/artifacts/a/b")
    kept.mkdir(parents=True)
    (kept / "record.json").write_text("{}")
    with pytest.raises(SystemExit, match="removes only a directory directly under"):
        recorder._remove_directory(target)
    assert (kept / "record.json").read_text() == "{}"


def test_a_link_out_of_the_tree_is_followed_to_where_it_leads_and_refused(recorder, tmp_path):
    outside = _outside(tmp_path)
    link = _scratch(recorder, recorder.REMOVABLE_UNDER / "linked")
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(SystemExit, match="outside the document root"):
        recorder._remove_directory(link.relative_to(recorder.ROOT))
    assert (outside / "sentinel.png").read_bytes() == b"retained bytes"


def test_a_record_or_a_copy_aimed_outside_the_root_is_refused_before_it_is_written(
    recorder, tmp_path
):
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(SystemExit, match="outside the document root"):
        recorder._write(outside / "record.json", {"record": {}}, replace=False)
    source = tmp_path / "capture.png"
    source.write_bytes(b"capture")
    with pytest.raises(SystemExit, match="outside the document root"):
        recorder._copy(source, recorder.ROOT / ".." / "outside" / "capture.png")
    assert list(outside.iterdir()) == []


def test_the_recorder_removes_files_in_one_place_only():
    """Every removal the script makes goes through the guard, so a new verb cannot bypass it."""
    removals = {"rmtree", "rmdir", "unlink", "removedirs"}
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    owners = []
    for function in ast.walk(tree):
        if not isinstance(function, ast.FunctionDef):
            continue
        for node in ast.walk(function):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            receiver = node.func.value
            # os.remove removes a file; list.remove does not, so only the module's is counted.
            by_os = isinstance(receiver, ast.Name) and receiver.id == "os"
            if node.func.attr in removals or (node.func.attr == "remove" and by_os):
                owners.append((function.name, node.func.attr))
    assert owners == [("_remove_directory", "rmtree")], owners
