"""The parametric body preparer: the pinned Blender, run as a child process under limits, checked.

A parametric family's body is fitted per recipe by ``scripts/parametric_character/blender_build.py``
inside the pinned Blender 4.5.9 with the pinned MPFB 2 source and MakeHuman CC0 system assets. This
module is everything around that build, in the order the material bake path established
(:mod:`exulanica.world.material_bakes`):

1.  **Verify the inputs before anything runs.** ``verify_inputs`` holds the Blender binary, the
    MPFB tree, the system assets, the motion source and every licence receipt to the family's
    ``source-lock.json``; the preparation identity adds the family declaration and the build
    scripts. A host whose inputs do not verify cannot prepare, and says so
    (:class:`PreparerUnavailable`); nothing is queued against it.
2.  **Build in a process of its own**, in a fresh scratch directory, with a minimal environment, a
    wall-clock limit and a resident-memory ceiling this module measures itself, killing the whole
    process group when either is passed.
3.  **Believe nothing it prints.** The container is measured by
    :func:`~exulanica.world.character_bodies.measure_prepared_body` against what the family declares
    for this recipe; the identity is verified again after the build, so a tool or input that changed
    while it ran fails the preparation as stale; and the scale the build reports must equal the one
    measured from its bytes.
4.  **Record only integers.** The receipt and the render descriptor are canonical JSON a saved look
    and the queue can hold; no float the build printed reaches either.

Publication, the queue, claims, leases, cancellation and the workspace store belong to the
preparation queue (lane A2's ``workspace_preparation``); this module is the preparer registered
there for ``character_recipe`` inputs.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.world.character_bodies import BodyRefused, measure_prepared_body
from exulanica.world.character_parametric import (
    PREPARER_ID,
    PREPARER_VERSION,
    Clip,
    Descriptor,
    ParametricFamily,
    body_declaration,
    preparer_recipe,
    recipe_input_sha256,
)

__all__ = [
    "PREPARATION_RECEIPT_PROFILE",
    "PreparationFailed",
    "PreparedBody",
    "PreparerHost",
    "PreparerLimits",
    "PreparerUnavailable",
    "prepare_body",
]

PREPARATION_RECEIPT_PROFILE: Final = "exulanica.character-preparation-receipt/v1"
_REPOSITORY: Final = Path(__file__).resolve().parents[2]
_SCRIPTS: Final = _REPOSITORY / "scripts" / "parametric_character"
_MIB: Final = 1 << 20


class PreparerUnavailable(RuntimeError):
    """This host cannot prepare bodies for the family: an input, tool or script does not verify."""


class PreparationFailed(Exception):
    """One preparation ended without a body, with the queue's failure class and a stable code."""

    def __init__(self, failure_class: str, code: str, detail: str = "") -> None:
        self.failure_class, self.code, self.detail = failure_class, code, detail
        super().__init__(f"{failure_class}: {code}" + (f": {detail}" if detail else ""))


@dataclass(frozen=True, slots=True)
class PreparerLimits:
    """What one build may use.

    Measured on 2026-09-30 (deliveries/C7 evidence, one build of the reviewed default recipe at
    load average 4): 4.8 s of wall time and 347 MiB of peak resident memory, with the output
    identical to the committed body. The ceilings leave room for a loaded host and other recipes
    while stopping a build that has gone wrong in minutes rather than ten.
    """

    timeout_seconds: float = 180.0
    memory_bytes: int = 1024 * _MIB
    poll_seconds: float = 0.05
    output_bytes: int = 32 * _MIB
    log_bytes: int = 65536

    def __post_init__(self) -> None:
        if not 0 < self.timeout_seconds <= 3600:
            raise ValueError("a build's timeout is positive and at most an hour")
        if self.memory_bytes < 256 * _MIB:
            raise ValueError("a Blender build needs at least 256 MiB")
        if not 0 < self.poll_seconds <= 1:
            raise ValueError("the watchdog looks at least once a second")


def _inputs_module(scripts: Path) -> ModuleType:
    path = scripts / "inputs.py"
    if not path.is_file() or not (scripts / "blender_build.py").is_file():
        raise PreparerUnavailable(f"the parametric build scripts are not at {scripts}")
    spec = importlib.util.spec_from_file_location("exulanica_parametric_inputs", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True, slots=True)
class PreparerHost:
    """Where this host keeps the pinned preparation inputs, and the family they were locked for."""

    blender: Path
    source: Path
    family_root: Path
    scripts: Path = _SCRIPTS

    @classmethod
    def from_environment(cls, environ: Mapping[str, str], family_root: Path) -> PreparerHost | None:
        """``EXULANICA_CHARACTER_PREPARER_BLENDER`` and ``..._SOURCE``; None unless both are set."""
        blender = environ.get("EXULANICA_CHARACTER_PREPARER_BLENDER")
        source = environ.get("EXULANICA_CHARACTER_PREPARER_SOURCE")
        if not blender or not source:
            return None
        return cls(blender=Path(blender), source=Path(source), family_root=family_root)

    def identity(self) -> dict[str, Any]:
        """The verified preparation identity, or :class:`PreparerUnavailable` naming what failed."""
        inputs = _inputs_module(self.scripts)
        try:
            verified = inputs.verify_inputs(self.source, self.blender, self.family_root)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise PreparerUnavailable(
                f"the pinned preparation inputs do not verify: {exc}"
            ) from exc
        return inputs.preparation_identity(verified, self.family_root)

    def identity_sha256(self) -> str:
        return hashlib.sha256(canonical_json(self.identity())).hexdigest()


@dataclass(frozen=True, slots=True)
class PreparedBody:
    """One accepted body: its bytes, its canonical receipt and the descriptor a renderer reads."""

    payload: bytes
    receipt: bytes
    descriptor: Descriptor
    measurements: Mapping[str, int]
    elapsed_ms: int
    peak_memory_bytes: int

    @property
    def output_sha256(self) -> str:
        return hashlib.sha256(self.payload).hexdigest()


@dataclass(frozen=True, slots=True)
class _Run:
    returncode: int | None
    payload: bytes | None
    metadata: dict[str, Any] | None
    peak_memory_bytes: int
    elapsed_seconds: float
    stopped: str | None
    log_tail: str


def _memory_reader() -> Any:
    """The child-memory reader the material bake watchdog uses; None where none exists."""
    from exulanica.world import material_bakes

    # The repository's one child-memory reader, which the material bake watchdog also uses.
    return material_bakes._READ_MEMORY


def _kill_group(process: subprocess.Popen[bytes]) -> None:
    from exulanica.world import material_bakes

    material_bakes._kill_group(process)


def _run(
    host: PreparerHost,
    family_document: Mapping[str, Any],
    recipe: Mapping[str, Any],
    limits: PreparerLimits,
) -> _Run:
    read_memory = _memory_reader()
    if read_memory is None:
        raise PreparerUnavailable("no way to measure a child's memory here, so no build runs")
    lock = json.loads((host.family_root / "source-lock.json").read_text())
    animation = (host.family_root / lock["animationSource"]).resolve()
    with tempfile.TemporaryDirectory(prefix="exulanica-character-build-") as scratch:
        work = Path(scratch)
        config = {
            "mpfb": str(host.source / "mpfb2"),
            "cache": str(work / "mpfb-user"),
            "recipe": dict(recipe),
            "family": dict(family_document),
            "assets": str(host.source / "system-assets"),
            "animation": str(animation),
            "output": str(work / "human.glb"),
            "metadata": str(work / "metadata.json"),
        }
        (work / "config.json").write_text(json.dumps(config))
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(work),
            "TMPDIR": str(work),
            "LANG": "C",
            "TZ": "UTC",
        }
        argv = [
            str(host.blender),
            "--background",
            "--factory-startup",
            "--python-exit-code",
            "1",
            "--python",
            str(host.scripts / "blender_build.py"),
            "--",
            str(work / "config.json"),
        ]
        with (work / "build.log").open("w+b") as log:
            started = time.monotonic()
            process = subprocess.Popen(
                argv,
                cwd=work,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            peak, stopped = 0, None
            try:
                while process.poll() is None:
                    resident = read_memory(process.pid)
                    if resident is not None:
                        peak = max(peak, resident)
                    if resident is not None and resident > limits.memory_bytes:
                        stopped = "over_memory"
                    elif time.monotonic() - started > limits.timeout_seconds:
                        stopped = "timed_out"
                    if stopped is not None:
                        _kill_group(process)
                        break
                    time.sleep(limits.poll_seconds)
            finally:
                if process.poll() is None:
                    _kill_group(process)
            elapsed = time.monotonic() - started
            log.seek(0, os.SEEK_END)
            log.seek(max(0, log.tell() - limits.log_bytes))
            tail = log.read().decode("utf-8", "replace")
        payload = metadata = None
        output = work / "human.glb"
        if stopped is None and process.returncode == 0 and output.is_file():
            if output.stat().st_size <= limits.output_bytes:
                payload = output.read_bytes()
            with contextlib.suppress(OSError, ValueError):
                metadata = json.loads((work / "metadata.json").read_text())
        shutil.rmtree(work / "mpfb-user", ignore_errors=True)
    return _Run(process.returncode, payload, metadata, peak, elapsed, stopped, tail)


def prepare_body(
    host: PreparerHost,
    family: ParametricFamily,
    family_sha256: str,
    values: Mapping[str, Any],
    *,
    limits: PreparerLimits | None = None,
    expected_identity_sha256: str | None = None,
) -> PreparedBody:
    """Fit, measure and receipt one body for exactly ``values``, or raise why not.

    ``expected_identity_sha256`` is the identity the request was made against; a host whose
    inputs no longer verify to it fails the preparation as stale rather than building a body for a
    different tool chain.
    """
    limits = limits or PreparerLimits()
    family_document = json.loads((host.family_root / "family.json").read_text())
    identity = host.identity()
    identity_sha256 = hashlib.sha256(canonical_json(identity)).hexdigest()
    if expected_identity_sha256 is not None and identity_sha256 != expected_identity_sha256:
        raise PreparationFailed("stale", "preparation_identity_changed")
    recipe = preparer_recipe(family, values)
    run = _run(host, family_document, recipe, limits)
    if run.stopped == "timed_out":
        raise PreparationFailed("timed_out", "build_timed_out", f"{run.elapsed_seconds:.0f} s")
    if run.stopped == "over_memory":
        raise PreparationFailed(
            "preparer_failed", "build_over_memory", f"{run.peak_memory_bytes} B"
        )
    if run.returncode != 0:
        raise PreparationFailed("preparer_failed", "build_failed", run.log_tail[-2000:])
    if run.payload is None:
        raise PreparationFailed("unverified_output", "output_missing_or_too_large")
    if hashlib.sha256(canonical_json(host.identity())).hexdigest() != identity_sha256:
        raise PreparationFailed("stale", "inputs_changed_during_build")
    try:
        measured = measure_prepared_body(run.payload, body_declaration(family, values))
    except BodyRefused as refused:
        raise PreparationFailed(refused.failure_class, refused.code, refused.detail) from refused
    reported = (run.metadata or {}).get("scale")
    if (
        not isinstance(reported, float | int)
        or abs(measured.unit_scale_millionths - reported * 1_000_000) > 2
    ):
        raise PreparationFailed("unverified_output", "scale_disagrees_with_measurement")
    descriptor = Descriptor(
        unitScaleMillionths=measured.unit_scale_millionths,
        nativeStandingHeightMillionths=measured.native_rest_height_millionths,
        nativeGroundOffsetMillionths=measured.native_idle_floor_millionths,
        forwardYawDegrees=180,
        clips={
            "idle": Clip(name=family.clips["idle"], speedMillimetresPerSecond=0),
            "walk": Clip(
                name=family.clips["walk"],
                speedMillimetresPerSecond=measured.walk_speed_mm_per_s,
            ),
            "run": Clip(
                name=family.clips["run"], speedMillimetresPerSecond=measured.run_speed_mm_per_s
            ),
        },
        materialSlots=_material_slots(run.payload),
    )
    receipt = canonical_json(
        {
            "profile": PREPARATION_RECEIPT_PROFILE,
            "preparer": {"id": PREPARER_ID, "version": PREPARER_VERSION},
            "family": {"family_id": family.familyId, "family_sha256": family_sha256},
            "values": dict(values),
            "recipe_input_sha256": recipe_input_sha256(values),
            "identity": identity,
            "identity_sha256": identity_sha256,
            "output": {
                "sha256": hashlib.sha256(run.payload).hexdigest(),
                "byte_size": len(run.payload),
            },
            "descriptor": descriptor.model_dump(mode="json"),
            "measurements": measured.document(),
            "elapsed_ms": round(run.elapsed_seconds * 1000),
            "peak_memory_bytes": run.peak_memory_bytes,
        }
    )
    return PreparedBody(
        payload=run.payload,
        receipt=receipt,
        descriptor=descriptor,
        measurements=measured.document(),
        elapsed_ms=round(run.elapsed_seconds * 1000),
        peak_memory_bytes=run.peak_memory_bytes,
    )


def _material_slots(payload: bytes) -> dict[str, tuple[str, ...]]:
    """Each material the body draws with, as its own colour slot, as the development builder did."""
    import struct

    length = struct.unpack_from("<I", payload, 12)[0]
    document = json.loads(payload[20 : 20 + length])
    return {m["name"]: (m["name"],) for m in document.get("materials", []) if m.get("name")}
