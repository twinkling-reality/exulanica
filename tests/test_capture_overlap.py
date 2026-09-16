"""The capture overlap verdict, on constructed graphs and on the real photographs on disk.

Two halves. The pure half builds measurements by hand and holds the decision rules, the closed
instruction vocabulary, the unavailable reasons and the canonical record. The real half measures
the retained Montserrat volcanic sample (Mike R. James and Stuart Robson, CC0) and the held-out
chili salmon bowl (Charin Rungchaowarat, CC0) through the ``.exulanica`` symlink, and pins what
``docs/capture-overlap-and-recovery-state.md`` reports: the four measured rows with their
margins, the monotonicity sweep with its known flip-backs, the held-out failure, the cost of the
210-photograph verdict, and determinism across processes. No photograph is copied into the
repository; the real half skips when they are absent.

A passing test over a constructed graph verifies a rule, not the verdict. The verdict is verified
by the real half, and the document says which of its results are failures.
"""

from __future__ import annotations

import dataclasses
import glob
import hashlib
import io
import json
import math
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest
from exulanica.canonical import canonical_json
from exulanica.capture import (
    Photograph,
    assess_capture_set,
    instruction,
    measure_overlap,
    outcome_from_pose_receipt,
    verdict_for_measurement,
)
from exulanica.capture.instructions import INSTRUCTION_KEYS
from exulanica.capture.overlap import (
    DescriptorParameters,
    OverlapMeasurement,
    PhotographFeatures,
    overlap_graph,
)
from exulanica.capture.recovery import member_digest
from exulanica.capture.verdict import POLICY_V1, decide
from exulanica.errors import CanonicalisationError
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/capture-overlap"
VOLCANIC = ROOT / ".exulanica/reference-baseline/inputs/volcanic-sample/photographs"
BOWL = ROOT / ".exulanica/reference-baseline/inputs/chili-salmon-bowl/images"
RETAINED_STORE = ROOT / ".exulanica/reference-baseline/runtime/blobs"
SCRATCH_STORE = Path(
    "/Users/glendonchin/dev/Technology/exulanica-scratch/capture-size/segments-view-data/blobs"
)
CAMERAS = json.loads((FIXTURES / "volcanic-cameras.json").read_text())["photographs"]
NAMES = [camera["name"] for camera in CAMERAS]
RUNS = {
    run["label"]: run for run in json.loads((FIXTURES / "measured-runs.json").read_text())["runs"]
}
FORBIDDEN_PREFIXES = (
    "torch",
    "numpy",
    "cv2",
    "pycolmap",
    "psycopg",
    "exulanica.db",
    "exulanica.store",
    "exulanica.evidence",
    "exulanica.reconstruction",
    "exulanica.ingest",
    "exulanica.graph",
)


def _forward(index: int) -> list[float]:
    return [value / 1_000_000 for value in CAMERAS[index]["forward_e6"]]


def _angle(first: int, second: int) -> float:
    a, b = _forward(first), _forward(second)
    dot = sum(p * q for p, q in zip(a, b, strict=True))
    dot /= math.sqrt(sum(p * p for p in a) * sum(q * q for q in b))
    return math.degrees(math.acos(max(-1.0, min(1.0, dot))))


def _jpeg(size=(400, 300), seed: int = 0, orientation: int | None = None) -> bytes:
    """A textured JPEG made here, so the pure tests need nothing on disk."""
    image = Image.new("L", size)
    digest = hashlib.sha256(f"texture/{seed}".encode()).digest()
    image.putdata(
        [
            digest[(x * 7 + y * 13) % 32] ^ ((x // 9) * (y // 7)) & 255
            for y in range(size[1])
            for x in range(size[0])
        ]
    )
    buffer = io.BytesIO()
    if orientation is None:
        image.save(buffer, format="JPEG")
    else:
        exif = Image.Exif()
        exif[0x0112] = orientation
        image.save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


def _features(ref: str, measured: bool = True) -> PhotographFeatures:
    if not measured:
        return PhotographFeatures(ref, None, "unavailable", "undecodable", 0, 0, ())
    return PhotographFeatures(ref, "0" * 64, "measured", None, 256, 192, ((10, 10, 1),))


def _constructed(
    scores: dict[tuple[int, int], int], count: int, unmeasured=()
) -> OverlapMeasurement:
    """A measurement with chosen pair scores, over ``count`` photographs named p00, p01, ..."""
    photographs = tuple(_features(f"p{i:02d}", i not in unmeasured) for i in range(count))
    nodes = tuple(i for i in range(count) if i not in unmeasured)
    pair_scores = tuple(
        scores.get((nodes[a], nodes[b]), 0)
        for a in range(len(nodes))
        for b in range(a + 1, len(nodes))
    )
    return OverlapMeasurement(DescriptorParameters(), photographs, nodes, pair_scores)


def _chain(count: int, links: list[int]) -> dict[tuple[int, int], int]:
    return {(i, i + 1): 20 for i in links if i + 1 < count}


AUTHORISED = dataclasses.replace(
    POLICY_V1, version="exulanica.capture-overlap-policy/test-authorised", refusal_authorised=True
)

# ---------------------------------------------------------------------------------------------
# The pure half.
# ---------------------------------------------------------------------------------------------


def test_the_package_imports_nothing_it_must_not_in_a_fresh_process(tmp_path):
    """Checked over sys.modules after a real verdict, in a process that imported nothing else."""
    for index in range(3):
        (tmp_path / f"photo{index}.jpg").write_bytes(_jpeg(seed=index))
    code = """import sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from exulanica.capture import Photograph, assess_capture_set
folder = Path(sys.argv[2])
verdict = assess_capture_set(
    [Photograph.from_path(path.name, path) for path in sorted(folder.glob("*.jpg"))]
)
print(verdict.sha256().hex())
forbidden = tuple(sys.argv[3].split(","))
loaded = sorted(name for name in sys.modules if name.split(".")[0] in forbidden
                or any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden))
print("LOADED", ",".join(loaded))
"""
    env = {key: value for key, value in os.environ.items() if not key.startswith("EXULANICA_")}
    result = subprocess.run(
        [sys.executable, "-I", "-c", code, str(ROOT), str(tmp_path), ",".join(FORBIDDEN_PREFIXES)],
        env=env,
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[-1] == "LOADED "


def test_a_verdict_is_a_prediction_and_only_an_authorised_refusal_is_a_state():
    scatter = _constructed({}, 6)
    verdict = verdict_for_measurement(scatter, POLICY_V1)
    assert not hasattr(verdict, "recovery_state")
    assert verdict.predicted_ceiling == "insufficient_overlap"
    assert verdict.worth_attempting is False
    assert verdict.refusal() is None, "policy v1 failed its held-out check and may not refuse"
    assert verdict_for_measurement(scatter, AUTHORISED).refusal() == "insufficient_overlap"
    chained = verdict_for_measurement(_constructed(_chain(6, list(range(5))), 6), AUTHORISED)
    assert chained.predicted_ceiling == "registered_scene"
    assert chained.refusal() is None


@pytest.mark.parametrize(
    ("scores", "count", "unmeasured", "ceiling", "fault", "advisories"),
    [
        ({}, 1, (), "insufficient_overlap", "too_few_photographs", ()),
        ({}, 0, (), "insufficient_overlap", "too_few_photographs", ()),
        ({}, 6, (), "insufficient_overlap", "no_overlapping_neighbours", ()),
        # Two islands of three, nothing between them.
        ({(0, 1): 9, (1, 2): 9, (3, 4): 9, (4, 5): 9}, 6, (), "registered_partial",
         "separate_groups", ()),
        # One pair and four photographs that overlap nothing.
        ({(0, 1): 30}, 6, (), "registered_partial", "mostly_unconnected", ()),
        # Nine of ten chained, which reaches the pose gate's floor, and one left out.
        (_chain(10, list(range(8))), 10, (), "registered_scene", None, ("some_unconnected",)),
        # Exactly at the floor: eight of ten.
        (_chain(10, list(range(7))), 10, (), "registered_scene", None, ("some_unconnected",)),
        # One short of it.
        (_chain(10, list(range(6))), 10, (), "registered_partial", "mostly_unconnected", ()),
        # Unmeasured photographs are credited to the largest group, never counted against it.
        (_chain(10, list(range(5))), 10, (8, 9), "registered_scene", None,
         ("some_unconnected", "unreadable_photographs")),
        ({}, 3, (0, 1), "registered_scene", None, ("unreadable_photographs",)),
        ({}, 5, (4,), "registered_partial", "no_overlapping_neighbours",
         ("unreadable_photographs",)),
    ],
)  # fmt: skip
def test_the_decision_rules(scores, count, unmeasured, ceiling, fault, advisories):
    verdict = verdict_for_measurement(_constructed(scores, count, unmeasured), AUTHORISED)
    assert verdict.predicted_ceiling == ceiling
    assert verdict.fault == fault
    assert verdict.advisories == advisories
    assert verdict.worth_attempting == (ceiling == "registered_scene")
    keys = [key for key, _ in verdict.instruction_counts]
    assert keys == ([fault] if fault else []) + list(advisories)
    assert "one_side_uncovered" not in keys
    for said in verdict.instructions():
        assert said.headline and said.detail


def test_a_graph_thresholded_under_another_policy_is_refused():
    graph = overlap_graph(_constructed({}, 3), 9)
    with pytest.raises(ValueError, match="different policy"):
        decide(graph, POLICY_V1)
    with pytest.raises(ValueError, match="different descriptor"):
        verdict_for_measurement(
            dataclasses.replace(_constructed({}, 3), parameters=DescriptorParameters(keypoints=8)),
            POLICY_V1,
        )


def test_instructions_are_closed_and_carry_only_the_numbers_they_were_given():
    samples = {
        "too_few_photographs": {"photographs": 1},
        "no_overlapping_neighbours": {"photographs": 6},
        "separate_groups": {"groups": 3},
        "mostly_unconnected": {"largest": 2, "photographs": 6, "others": 4},
        "some_unconnected": {"others": 1},
        "one_side_uncovered": {},
        "unreadable_photographs": {"unreadable": 2},
        "run_placed_none": {"photographs": 6},
        "run_placed_some": {"registered": 7, "photographs": 12},
    }
    assert set(samples) == set(INSTRUCTION_KEYS)
    for key, counts in samples.items():
        said = instruction(key, counts)
        text = " ".join(filter(None, (said.headline, said.detail, said.action)))
        digits = {
            token for token in text.replace(",", " ").replace(".", " ").split() if token.isdigit()
        }
        assert digits <= {str(value) for value in counts.values()}, (key, text)
        assert chr(0x2014) not in text, "no em dash in anything a person reads"
        lowered = text.lower()
        assert "take " not in lowered or not any(
            lowered.split("take ", 1)[1].startswith(str(n)) for n in range(10)
        ), "the advice is never a number of photographs"
    with pytest.raises(KeyError):
        instruction("take_more_photographs", {})  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="takes exactly"):
        instruction("separate_groups", {})
    with pytest.raises(ValueError, match="non-negative int"):
        instruction("separate_groups", {"groups": 2.0})  # type: ignore[dict-item]
    with pytest.raises(ValueError, match="non-negative int"):
        instruction("separate_groups", {"groups": True})
    assert instruction("some_unconnected", {"others": 1}).detail.startswith("One of them doesn't")


def test_a_photograph_that_cannot_be_measured_is_named_and_never_defaulted(tmp_path):
    good = _jpeg(seed=1)
    sixteen = io.BytesIO()
    Image.new("I;16", (400, 300)).save(sixteen, format="PNG")

    def unreadable() -> bytes:
        raise OSError("the store is unreachable")

    photographs = [
        Photograph.from_bytes("a-good", good),
        Photograph.from_bytes("b-garbage", b"not an image at all"),
        Photograph.from_bytes("c-mirrored", _jpeg(seed=2, orientation=2)),
        Photograph.from_bytes("d-tiny", _jpeg(size=(120, 90), seed=3)),
        Photograph.from_bytes("e-sixteen", sixteen.getvalue()),
        Photograph("f-unreadable", unreadable),
        Photograph.from_bytes("g-rotated", _jpeg(seed=4, orientation=6)),
    ]
    verdict = assess_capture_set(photographs)
    states = {item.ref: (item.state, item.reason) for item in verdict.graph.measurement.photographs}
    assert states == {
        "a-good": ("measured", None),
        "b-garbage": ("unavailable", "undecodable"),
        "c-mirrored": ("unavailable", "mirrored_orientation"),
        "d-tiny": ("unavailable", "too_small"),
        "e-sixteen": ("unavailable", "unsupported_pixel_format"),
        "f-unreadable": ("unavailable", "unreadable"),
        "g-rotated": ("measured", None),
    }
    by_ref = {item.ref: item for item in verdict.graph.measurement.photographs}
    assert by_ref["f-unreadable"].sha256 is None
    assert by_ref["b-garbage"].sha256 == hashlib.sha256(b"not an image at all").hexdigest()
    assert by_ref["b-garbage"].keypoints == ()
    assert (by_ref["g-rotated"].width, by_ref["g-rotated"].height) == (192, 256)
    assert verdict.graph.measurement.nodes == (0, 6)
    assert "unreadable_photographs" in verdict.advisories
    assert verdict.unmeasured == 5


def test_the_record_is_canonical_and_a_float_anywhere_in_it_is_refused():
    verdict = verdict_for_measurement(_constructed({(0, 1): 12}, 3), POLICY_V1)
    record = verdict.record()
    assert canonical_json(record) == verdict.canonical_bytes()
    assert verdict.sha256() == hashlib.sha256(verdict.canonical_bytes()).digest()
    poisoned = json.loads(verdict.canonical_bytes())
    poisoned["graph"]["pair_scores"][0] = 12.0
    with pytest.raises(CanonicalisationError, match="float"):
        canonical_json(poisoned)
    poisoned = json.loads(verdict.canonical_bytes())
    poisoned["policy"]["registration_floor"]["numerator"] = 0.8
    with pytest.raises(CanonicalisationError, match="float"):
        canonical_json(poisoned)


def test_the_member_digest_names_a_set():
    ids = [uuid.uuid4() for _ in range(4)]
    assert member_digest(ids) == member_digest(reversed(ids))
    assert member_digest(ids) != member_digest(ids[:3])
    with pytest.raises(ValueError):
        member_digest([])
    with pytest.raises(ValueError):
        member_digest([ids[0], ids[0]])


def test_the_order_photographs_are_given_in_does_not_change_the_verdict():
    photographs = [Photograph.from_bytes(f"shot-{i}", _jpeg(seed=i)) for i in range(4)]
    forward = assess_capture_set(photographs)
    backward = assess_capture_set(list(reversed(photographs)))
    assert forward.canonical_bytes() == backward.canonical_bytes()
    with pytest.raises(ValueError, match="share a ref"):
        assess_capture_set(photographs + photographs[:1])


# ---------------------------------------------------------------------------------------------
# The real half.
# ---------------------------------------------------------------------------------------------


class _NoProcesses:
    """Refuse every way this process could start another, for the duration of a measurement."""

    targets = (
        (subprocess, "Popen"),
        (os, "system"),
        (os, "fork"),
        (os, "posix_spawn"),
        (os, "posix_spawnp"),
        (os, "execv"),
    )

    def __enter__(self):
        self.saved = [(module, name, getattr(module, name)) for module, name in self.targets]

        def refuse(*args, **kwargs):
            raise AssertionError("the overlap verdict tried to start a process")

        for module, name, _ in self.saved:
            setattr(module, name, refuse)
        return self

    def __exit__(self, *exc):
        for module, name, original in self.saved:
            setattr(module, name, original)
        return False


@pytest.fixture(scope="module")
def volcanic():
    """All 210 photographs measured once, timed, with process creation refused throughout."""
    if not VOLCANIC.is_dir():
        pytest.skip("the retained volcanic photographs are not reachable through .exulanica")
    photographs = [Photograph.from_path(name, VOLCANIC / name) for name in NAMES]
    before = set(sys.modules)
    with _NoProcesses():
        started, started_cpu = time.perf_counter(), time.process_time()
        verdict = assess_capture_set(photographs)
        wall, cpu = time.perf_counter() - started, time.process_time() - started_cpu
    newly = sorted(
        name for name in set(sys.modules) - before
        if any(name == p or name.startswith(p + ".") for p in FORBIDDEN_PREFIXES)
    )  # fmt: skip
    return verdict, wall, cpu, newly


def _outcome(run) -> str:
    if run["registered_count"] == 0:
        return "insufficient_overlap"
    return "registered_scene" if run["accepted"] else "registered_partial"


def test_the_210_photograph_verdict_costs_seconds_and_starts_nothing(volcanic):
    verdict, wall, cpu, newly = volcanic
    print(f"210-photograph verdict: wall {wall:.2f} s, cpu {cpu:.2f} s")
    assert newly == []
    assert wall < 120, f"{wall:.1f} s is not a cheap verdict"
    assert verdict.graph.photograph_count == verdict.graph.measured_count == 210
    assert len(verdict.graph.measurement.pair_scores) == 21945
    assert verdict.predicted_ceiling == "registered_scene"
    assert (verdict.graph.largest_component, verdict.graph.groups) == (210, 1)


@pytest.mark.parametrize(
    ("label", "ceiling", "fault", "decided_right", "transitions"),
    [
        # ``transitions`` is the verdict as the edge threshold rises from 1 to 40, written as the
        # thresholds where it changes: the margin the document reports, pinned exactly.
        ("six", "registered_partial", "mostly_unconnected", True,
         [(1, "registered_scene"), (5, "registered_partial"), (9, "insufficient_overlap")]),
        ("twelve_wide", "registered_partial", "separate_groups", True,
         [(1, "registered_scene"), (6, "registered_partial"), (26, "insufficient_overlap")]),
        # THE KNOWN FAILURE. This set registered twelve of twelve, and at the policy threshold the
        # verdict refuses it. It is right only up to 7, and the declared rule chose 8.
        ("twelve_close", "registered_partial", "separate_groups", False,
         [(1, "registered_scene"), (8, "registered_partial"), (29, "insufficient_overlap")]),
        ("all_210", "registered_scene", None, True,
         [(1, "registered_scene"), (15, "registered_partial")]),
    ],
)  # fmt: skip
def test_the_four_measured_rows_and_their_margins(
    volcanic, label, ceiling, fault, decided_right, transitions
):
    measurement = volcanic[0].graph.measurement
    run = RUNS[label]
    subset = (
        measurement if label == "all_210" else measurement.subset(NAMES[i] for i in run["indices"])
    )

    def at(threshold=None):
        policy = POLICY_V1
        if threshold is not None:
            policy = dataclasses.replace(POLICY_V1, edge_min_score=threshold)
        return verdict_for_measurement(subset, policy)

    verdict = at()
    assert verdict.predicted_ceiling == ceiling
    assert verdict.fault == fault
    # Right means: the set is recommended for a run exactly when the run registered it.
    assert (verdict.worth_attempting == (_outcome(run) == "registered_scene")) is decided_right
    seen, previous = [], None
    for threshold in range(1, 41):
        current = at(threshold).predicted_ceiling
        if current != previous:
            seen.append((threshold, current))
            previous = current
    assert seen == transitions


def test_the_measured_index_lists_come_from_the_receipts_not_from_arithmetic():
    """Fact 4's reconstruction stepped through all 210; the receipts say the first 113."""
    assert RUNS["six"]["indices"] == [0, 22, 45, 67, 90, 112]
    assert RUNS["twelve_wide"]["indices"] == [0, 4, 7, 11, 15, 18, 22, 25, 29, 33, 36, 40]
    assert RUNS["twelve_close"]["indices"] == [0, 2, 4, 7, 9, 11, 13, 15, 17, 20, 22, 24]
    assert RUNS["twelve_wide"]["registered_indices"] == [0, 4, 7, 11, 33, 36, 40]
    for label in ("six", "twelve_wide", "twelve_close"):
        indices = RUNS[label]["indices"]
        first, last, count = indices[0], indices[-1], len(indices)
        assert indices == [first + round(i * (last - first) / (count - 1)) for i in range(count)]
    close = [
        _angle(a, b)
        for a, b in zip(
            RUNS["twelve_close"]["indices"], RUNS["twelve_close"]["indices"][1:], strict=False
        )
    ]
    wide = [
        _angle(a, b)
        for a, b in zip(
            RUNS["twelve_wide"]["indices"], RUNS["twelve_wide"]["indices"][1:], strict=False
        )
    ]
    assert min(close) > 19 and max(close) < 31
    assert min(wide) > 29 and max(wide) < 41


def test_the_monotonicity_sweep_matches_its_record(volcanic):
    """Widening the step of a fixed start and count should never turn a refusal into a run.

    At the policy threshold it does, and this pins how often, so the document cannot drift from
    the code: 81 of 452 calibration sequences and 17 of 388 validation sequences. At 10 only 2
    and 1 do, and that threshold refuses the set that registered as well.
    """
    measurement = volcanic[0].graph.measurement
    cache: dict[tuple[int, ...], OverlapMeasurement] = {}
    counts = {}
    for threshold in (8, 10):
        policy = dataclasses.replace(POLICY_V1, edge_min_score=threshold)
        for label, low, high in (("calibration", 0, 112), ("validation", 113, 209)):
            flips = sequences = 0
            for count in (6, 8, 12, 16):
                for start in range(low, high + 1):
                    sequences += 1
                    previous, step = None, 1
                    while start + step * (count - 1) <= high:
                        key = tuple(start + step * k for k in range(count))
                        if key not in cache:
                            cache[key] = measurement.subset(NAMES[i] for i in key)
                        run = verdict_for_measurement(cache[key], policy).worth_attempting
                        flips += previous is False and run
                        previous, step = run, step + 1
            counts[(threshold, label)] = (flips, sequences)
    assert counts == {
        (8, "calibration"): (81, 452),
        (8, "validation"): (17, 388),
        (10, "calibration"): (2, 452),
        (10, "validation"): (1, 388),
    }


def test_a_subset_is_exactly_what_measuring_it_directly_gives(volcanic):
    measurement = volcanic[0].graph.measurement
    indices = RUNS["twelve_wide"]["indices"]
    direct = measure_overlap(
        [Photograph.from_path(NAMES[i], VOLCANIC / NAMES[i]) for i in indices], POLICY_V1.descriptor
    )
    assert direct == measurement.subset(NAMES[i] for i in indices)


def test_the_same_photographs_give_the_same_digest_in_two_processes(volcanic, tmp_path):
    measurement = volcanic[0].graph.measurement
    indices = RUNS["six"]["indices"]
    expected = verdict_for_measurement(measurement.subset(NAMES[i] for i in indices)).sha256()
    again = assess_capture_set(
        [Photograph.from_path(NAMES[i], VOLCANIC / NAMES[i]) for i in indices]
    )
    assert again.sha256() == expected
    code = """import sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from exulanica.capture import Photograph, assess_capture_set
folder = Path(sys.argv[2])
photographs = [Photograph.from_path(name, folder / name) for name in sys.argv[3:]]
print(assess_capture_set(photographs).sha256().hex())
"""
    digests = set()
    for seed in ("0", "4242"):
        env = {key: value for key, value in os.environ.items() if not key.startswith("EXULANICA_")}
        env["PYTHONHASHSEED"] = seed
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                code,
                str(ROOT),
                str(VOLCANIC),
                *(NAMES[i] for i in indices),
            ],
            env=env,
            cwd=tmp_path,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        digests.add(result.stdout.strip())
    assert digests == {expected.hex()}


def _retained_receipt(store: Path, digest: str) -> dict:
    matches = glob.glob(str(store / f"sha-256/*/*/{digest}"))
    if not matches:
        pytest.skip(f"receipt {digest[:12]} is not on this machine")
    data = Path(matches[0]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == digest
    return json.loads(data)


def test_outcomes_read_from_the_real_pose_receipts():
    for label in ("six", "twelve_wide", "twelve_close"):
        run = RUNS[label]
        outcome = outcome_from_pose_receipt(_retained_receipt(SCRATCH_STORE, run["receipt_sha256"]))
        assert outcome.state == _outcome(run)
        assert (outcome.registered_count, outcome.member_count) == (
            run["registered_count"],
            run["source_count"],
        )
    whole = outcome_from_pose_receipt(
        _retained_receipt(RETAINED_STORE, RUNS["all_210"]["receipt_sha256"])
    )
    assert (whole.state, whole.registered_count, whole.member_count) == (
        "registered_scene",
        210,
        210,
    )
    with pytest.raises(ValueError, match="profile"):
        outcome_from_pose_receipt({"profile": "exulanica.colmap-pose-receipt/v1"})


_BOWL_RECEIPTS = {
    "292d697be5d0abdd888fb87e42e9d7893ede87ffdb4bdfb42ec4b6f0e6f267df": ("registered_scene", 51),
    "d3563ac261c60274b337edefa1a82afd045b2184ffd183248fdec808d1350e67": ("registered_scene", 51),
    "2976a64d54ecb4e8dc8d53533b84e38cb4996176efb7655f96b60ded982cb883": ("registered_partial", 40),
}


def test_the_held_out_bowl_is_the_failure_the_document_reports():
    """Measured once, after the policy was fixed. The set registered and trained; v1 refuses it.

    Pinned so a descriptor change cannot quietly turn this into a pass without the document and
    the policy's authorisation being revisited. The bowl is spent as a held-out set for any
    policy chosen after this result.
    """
    if not BOWL.is_dir():
        pytest.skip("the retained bowl photographs are not reachable through .exulanica")
    names = sorted(path.name for path in BOWL.iterdir() if path.suffix.lower() == ".jpg")
    assert len(names) == 51
    digests = {hashlib.sha256((BOWL / name).read_bytes()).hexdigest() for name in names}
    for receipt_digest, (state, count) in _BOWL_RECEIPTS.items():
        receipt = _retained_receipt(RETAINED_STORE, receipt_digest)
        outcome = outcome_from_pose_receipt(receipt)
        assert (outcome.state, outcome.registered_count) == (state, count)
        assert {frame["sha256"] for frame in receipt["manifest"]["frames"]} <= digests
    verdict = assess_capture_set([Photograph.from_path(name, BOWL / name) for name in names])
    graph = verdict.graph
    assert (graph.measured_count, len(graph.edges)) == (51, 75)
    assert (graph.largest_component, graph.groups, graph.isolated) == (20, 6, 3)
    assert verdict.predicted_ceiling == "registered_partial"
    assert verdict.fault == "separate_groups"
    assert verdict.worth_attempting is False, "the known failure: this set registered 51 of 51"
    assert verdict.refusal() is None, "and it is why policy v1 may not refuse"
    assert "held_out" in dict(POLICY_V1.calibration)
