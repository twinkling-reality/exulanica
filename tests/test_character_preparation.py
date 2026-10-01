"""The parametric body preparer around a stand-in for Blender: limits, staleness and checking.

The real build needs the pinned Blender, MPFB 2 and the MakeHuman system assets and takes minutes;
it is measured separately and recorded in the C7 delivery report. Here a small executable plays
Blender's part, so everything this repository's preparer does around the build is exercised: the
identity check before and after, the watchdog, the failure classes, the independent measurement
and the integer receipt.
"""

import hashlib
import json
import stat
import sys
from pathlib import Path

import pytest
from exulanica.canonical import canonical_json
from exulanica.world.character_catalog_publication import catalog_documents
from exulanica.world.character_parametric import declared_family, parametric_recipe_families
from exulanica.world.character_preparation import (
    PREPARATION_RECEIPT_PROFILE,
    PreparationFailed,
    PreparerHost,
    PreparerLimits,
    PreparerUnavailable,
    prepare_body,
)

ROOT = Path(__file__).parents[1]
CHARACTERS = ROOT / "assets/characters"
FAMILY_ROOT = CHARACTERS / "makehuman-parametric-v1"
DEFAULT_BODY = FAMILY_ROOT / "human-default.glb"
SCALE = json.loads((FAMILY_ROOT / "default.look.json").read_text())["descriptor"]["unitScale"]

FAKE_INPUTS = """
import json
from pathlib import Path

HERE = Path(__file__).parent


def verify_inputs(source, blender, family_root):
    calls = HERE / "calls"
    count = int(calls.read_text()) if calls.exists() else 0
    calls.write_text(str(count + 1))
    drift = (HERE / "drift").exists() and count >= 1
    return {"tool": "stand-in", "generation": "changed" if drift else "pinned"}


def preparation_identity(inputs, family_root):
    return {"inputs": inputs, "family": "family-digest"}
"""

FAKE_BLENDER = """#!{python}
import json
import shutil
import sys
import time
from pathlib import Path

mode = (Path(__file__).parent / "mode").read_text().strip()
config = json.loads(Path(sys.argv[-1]).read_text())
if mode == "fail":
    print("the fit went wrong", file=sys.stderr)
    sys.exit(3)
if mode == "slow":
    time.sleep(30)
body = Path("{body}").read_bytes()
if mode == "renamed-joint":
    length = int.from_bytes(body[12:16], "little")
    document = json.loads(body[20 : 20 + length])
    document["nodes"][document["skins"][0]["joints"][3]]["name"] = "mixamorig:Tail"
    text = json.dumps(document, separators=(",", ":")).encode()
    text += b" " * (-len(text) % 4)
    rest = body[20 + length :]
    total = 12 + 8 + len(text) + len(rest)
    import struct
    header = struct.pack("<III", 0x46546C67, 2, total)
    body = header + struct.pack("<II", len(text), 0x4E4F534A) + text + rest
Path(config["output"]).write_bytes(body)
scale = {scale} * (1.05 if mode == "wrong-scale" else 1)
Path(config["metadata"]).write_text(json.dumps({{"scale": scale}}))
"""


@pytest.fixture(scope="module")
def family():
    _layered, parametric = catalog_documents(CHARACTERS)
    (recipe_family,) = parametric_recipe_families(parametric)
    declared = declared_family(parametric, recipe_family.family_id)
    (body,) = declared.representations
    return declared, recipe_family, body.values


@pytest.fixture
def stand_in(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "inputs.py").write_text(FAKE_INPUTS)
    (scripts / "blender_build.py").write_text("# the stand-in never runs this\n")
    blender = tmp_path / "blender"
    blender.write_text(
        FAKE_BLENDER.format(python=sys.executable, body=DEFAULT_BODY, scale=repr(SCALE))
    )
    blender.chmod(blender.stat().st_mode | stat.S_IXUSR)
    (tmp_path / "mode").write_text("ok")
    host = PreparerHost(
        blender=blender, source=tmp_path / "source", family_root=FAMILY_ROOT, scripts=scripts
    )

    def mode(value):
        (tmp_path / "mode").write_text(value)

    return host, mode, scripts


def test_a_body_is_built_measured_and_receipted_in_integers(stand_in, family):
    host, _mode, _ = stand_in
    declared, recipe_family, values = family
    prepared = prepare_body(host, declared, recipe_family.sha256, values)
    assert prepared.output_sha256 == hashlib.sha256(DEFAULT_BODY.read_bytes()).hexdigest()
    assert prepared.descriptor.unitScaleMillionths == 1130365
    assert prepared.descriptor.clips["walk"].speedMillimetresPerSecond == 1181
    receipt = json.loads(prepared.receipt)
    assert prepared.receipt == canonical_json(receipt)
    assert receipt["profile"] == PREPARATION_RECEIPT_PROFILE
    assert receipt["family"]["family_sha256"] == recipe_family.sha256
    assert receipt["output"] == {
        "sha256": prepared.output_sha256,
        "byte_size": len(DEFAULT_BODY.read_bytes()),
    }
    assert (
        receipt["identity_sha256"]
        == hashlib.sha256(canonical_json(receipt["identity"])).hexdigest()
    )
    assert receipt["measurements"]["joints"] == 64


@pytest.mark.parametrize(
    ("mode", "failure_class", "code"),
    [
        ("fail", "preparer_failed", "build_failed"),
        ("renamed-joint", "rig_incompatible", "joints_differ_from_family"),
        ("wrong-scale", "unverified_output", "scale_disagrees_with_measurement"),
    ],
)
def test_a_build_that_fails_or_does_not_check_out_gives_no_body(
    stand_in, family, mode, failure_class, code
):
    host, set_mode, _ = stand_in
    declared, recipe_family, values = family
    set_mode(mode)
    with pytest.raises(PreparationFailed) as failed:
        prepare_body(host, declared, recipe_family.sha256, values)
    assert (failed.value.failure_class, failed.value.code) == (failure_class, code)


def test_a_build_past_its_wall_clock_is_stopped(stand_in, family):
    host, set_mode, _ = stand_in
    declared, recipe_family, values = family
    set_mode("slow")
    limits = PreparerLimits(timeout_seconds=1.0, poll_seconds=0.05)
    with pytest.raises(PreparationFailed) as failed:
        prepare_body(host, declared, recipe_family.sha256, values, limits=limits)
    assert (failed.value.failure_class, failed.value.code) == ("timed_out", "build_timed_out")


def test_inputs_that_change_while_it_builds_make_the_preparation_stale(stand_in, family):
    host, _mode, scripts = stand_in
    declared, recipe_family, values = family
    (scripts / "drift").write_text("the second look sees other inputs")
    with pytest.raises(PreparationFailed) as failed:
        prepare_body(host, declared, recipe_family.sha256, values)
    assert (failed.value.failure_class, failed.value.code) == (
        "stale",
        "inputs_changed_during_build",
    )


def test_a_request_made_against_another_identity_is_stale_before_anything_runs(stand_in, family):
    host, set_mode, scripts = stand_in
    declared, recipe_family, values = family
    set_mode("fail")
    with pytest.raises(PreparationFailed) as failed:
        prepare_body(
            host, declared, recipe_family.sha256, values, expected_identity_sha256="0" * 64
        )
    assert (failed.value.failure_class, failed.value.code) == (
        "stale",
        "preparation_identity_changed",
    )
    # Refused before the build: the stand-in, set to fail, was never run.
    assert int((scripts / "calls").read_text()) == 1


def test_a_host_without_the_build_scripts_cannot_prepare(tmp_path):
    host = PreparerHost(
        blender=tmp_path / "blender",
        source=tmp_path,
        family_root=FAMILY_ROOT,
        scripts=tmp_path / "missing",
    )
    with pytest.raises(PreparerUnavailable, match="build scripts"):
        host.identity()
    assert PreparerHost.from_environment({}, FAMILY_ROOT) is None
