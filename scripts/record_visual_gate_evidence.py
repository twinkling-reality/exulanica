"""Write the visual gate's digest-bound records from what was measured, and nothing else.

Two verbs, because they bind different evidence:

``reconciliation``
    Reads the three retained rejection records and their briefs, the version 1 reconciliation
    record and the rubric, recomputes every digest, resolves every hardPass spelling through
    ``exulanica.evaluation.gate_keys``, checks that no corridor and no record was scored against
    version 1, retains a byte-for-byte copy of the rubric and writes
    ``docs/evaluation/2026-09-16-visual-gate-key-reconciliation-v2.json``. Any disagreement
    between the files and the reconciled table stops the write and says so.

``baseline``
    Reads the harness output of two runs (``scripts/capture_visual_gate.mjs``) and the named
    judge's answers, copies the first run's captures and measurements under
    ``docs/evaluation/artifacts/2026-09-15-flatiron-owned-district-baseline/``, binds each file by
    byte size and SHA-256, re-decides every mechanical key from the measured numbers, refuses to
    write when its decision and the harness's disagree, and writes
    ``docs/evaluation/2026-09-15-flatiron-owned-district-baseline.json``. The judged key is decided
    by the record builder against the rubric as it is on disk and the captures as they are bound,
    so every refusal the rubric names happens in one place.

Every number in a record is read from a measurement file of the run it describes. None is copied
from a previous document, and no credential is read, printed or written: the harness output never
carries one, and this script refuses to write a record that contains a forbidden string.

The judge's words are written only to the record's private companion under
``.exulanica/judge-words/``, which git ignores. The public record carries their SHA-256 and byte
count, and this script refuses to write a public record that contains any of them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from exulanica.canonical import canonical_json
from exulanica.evaluation.gate_keys import (
    CANONICAL_SPELLINGS,
    CAPTURE_LABELS,
    GATE_KEY_SET_VERSION,
    JUDGED_KEY,
    PICTURE_TITLES,
    RETAINED_RECORDS,
    RUBRIC_PATH,
    RUBRIC_V1,
    RUBRIC_VERSION,
    judge_prompt,
    key,
)
from exulanica.evaluation.visual_gate import (
    GateEvidenceError,
    JudgedAnswers,
    PictureAnswer,
    decide_judged,
    decide_mechanical,
    judge_words,
    judge_words_file,
    reconciliation_record,
    refuse_private_words,
    visual_gate_record,
)

#: The repository the scored files and git history come from.
SOURCE_ROOT = Path(__file__).resolve().parents[1]
#: Where documents are read from and written to. The repository itself, except in a dry run of
#: the writer against a scratch copy of docs/, which never touches the retained tree.
ROOT = Path(os.environ.get("VISUAL_GATE_DOCUMENT_ROOT", SOURCE_ROOT)).resolve()
SUPERSEDED_RECONCILIATION = "docs/evaluation/2026-09-15-visual-gate-key-reconciliation.json"
RECONCILIATION = ROOT / "docs/evaluation/2026-09-16-visual-gate-key-reconciliation-v2.json"
RECONCILIATION_ARTIFACTS = (
    ROOT / "docs/evaluation/artifacts/2026-09-16-visual-gate-key-reconciliation-v2"
)
RUBRIC_COPY = RECONCILIATION_ARTIFACTS / "visual-gate-rubric.md"
BASELINE = ROOT / "docs/evaluation/2026-09-15-flatiron-owned-district-baseline.json"
ARTIFACTS = ROOT / "docs/evaluation/artifacts/2026-09-15-flatiron-owned-district-baseline"
FORBIDDEN = ("/Users/", "Bearer ", "api-token")
JUDGEMENT_PROFILE = "exulanica.visual-gate-judgement/v2"


def _git(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=SOURCE_ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def _relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def _refuse_forbidden(text: str, where: str) -> None:
    for forbidden in FORBIDDEN:
        if forbidden in text:
            raise SystemExit(f"refusing to write {where}: it contains {forbidden!r}")


def _write(
    path: Path, document: dict, *, replace: bool, private: list[str] | tuple[str, ...] = ()
) -> None:
    if path.exists() and not replace:
        raise SystemExit(
            f"{_relative(path)} exists. A retained record is not rewritten; pass --replace only "
            "for a record that has never been committed."
        )
    text = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    _refuse_forbidden(text, path.name)
    try:
        refuse_private_words(text, private)
    except GateEvidenceError as error:
        raise SystemExit(f"refusing to write {path.name}: {error}") from error
    path.write_text(text, encoding="utf-8")


def _write_private(relative: str, data: bytes, *, replace: bool) -> None:
    """Write a record's private companion, which git ignores, and never over other words."""
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", relative.split("/", 1)[0]], cwd=SOURCE_ROOT, check=False
    )
    if ignored.returncode != 0:
        raise SystemExit(f"{relative} would not be ignored by git; the judge's words stay private")
    path = ROOT / relative
    if path.exists() and path.read_bytes() != data and not replace:
        raise SystemExit(
            f"{relative} exists with other words; pass --replace only for a record that has never "
            "been committed"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _scored_before_revision() -> tuple[list[str], list[str]]:
    """Retained records that score a corridor, and those scored against version 1's key set."""
    corridors: list[str] = []
    against_version_1: list[str] = []
    for path in sorted((ROOT / "docs/evaluation").glob("*.json")):
        record = json.loads(path.read_bytes()).get("record", {})
        profile = str(record.get("profile", ""))
        if "corridor" in path.name.casefold() or "corridor" in profile.casefold():
            corridors.append(_relative(path))
        gate = record.get("gate")
        if isinstance(gate, dict) and gate.get("keySet") == RUBRIC_V1.key_set:
            against_version_1.append(_relative(path))
    return corridors, against_version_1


def reconciliation(arguments: argparse.Namespace) -> int:
    retained = {}
    briefs = {}
    for record in RETAINED_RECORDS:
        record_path = ROOT / record.path
        brief_path = ROOT / record.brief_path
        if not record_path.is_file() or not brief_path.is_file():
            raise SystemExit(
                f"{record.path} or {record.brief_path} is not in this checkout. They are "
                "local-only retained evidence; copy docs/ from the checkout that holds them."
            )
        retained[record.label] = json.loads(record_path.read_bytes())
        briefs[record.label] = brief_path.read_bytes()
    if RECONCILIATION_ARTIFACTS.exists() and not arguments.replace:
        raise SystemExit(f"{_relative(RECONCILIATION_ARTIFACTS)} exists; it is not rewritten")
    corridors, against_version_1 = _scored_before_revision()
    rubric = (ROOT / RUBRIC_PATH).read_bytes()
    try:
        document = reconciliation_record(
            date=arguments.date,
            base=_git("rev-parse", "HEAD"),
            branch=_git("branch", "--show-current"),
            retained=retained,
            briefs=briefs,
            superseded=json.loads((ROOT / SUPERSEDED_RECONCILIATION).read_bytes()),
            superseded_path=SUPERSEDED_RECONCILIATION,
            rubric=rubric,
            rubric_copy_path=_relative(RUBRIC_COPY),
            scored_corridors=corridors,
            scored_against_superseded=against_version_1,
        )
    except GateEvidenceError as error:
        raise SystemExit(f"nothing is written: {error}") from error
    if RECONCILIATION.exists() and not arguments.replace:
        raise SystemExit(f"{_relative(RECONCILIATION)} exists. A retained record is not rewritten.")
    RECONCILIATION_ARTIFACTS.mkdir(parents=True, exist_ok=True)
    RUBRIC_COPY.write_bytes(rubric)
    if RUBRIC_COPY.read_bytes() != rubric:
        raise SystemExit("the rubric did not copy byte for byte")
    _write(RECONCILIATION, document, replace=arguments.replace)
    written = RECONCILIATION.read_bytes()
    print(
        f"{_relative(RECONCILIATION)} {len(written)} bytes, "
        f"sha256 {hashlib.sha256(written).hexdigest()}, record_sha256 {document['record_sha256']}, "
        f"rubric sha256 {hashlib.sha256(rubric).hexdigest()}"
    )
    return 0


# ---- baseline -------------------------------------------------------------------------------


def _decimal(value: float | int | None) -> str | None:
    """A measured non-integer as the decimal string the product itself rounded it to."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise SystemExit("a boolean is not a measured number")
    return repr(float(value)) if isinstance(value, float) else str(value)


def _mm(value: float) -> int:
    """Metres to integer millimetres, half toward zero, the canonical rule."""
    from fractions import Fraction

    from exulanica.canonical import round_half_down

    exact = Fraction(value) * 1000
    return round_half_down(exact.numerator, exact.denominator)


def _micro(value: float) -> int:
    from fractions import Fraction

    from exulanica.canonical import round_half_down

    exact = Fraction(value) * 1_000_000
    return round_half_down(exact.numerator, exact.denominator)


def _no_floats(value: Any) -> Any:
    """Every float in an artifact becomes the decimal string it prints as."""
    if isinstance(value, bool) or value is None or isinstance(value, int | str):
        return value
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, dict):
        return {name: _no_floats(item) for name, item in value.items()}
    if isinstance(value, list):
        return [_no_floats(item) for item in value]
    raise SystemExit(f"unexpected value in a run file: {type(value).__name__}")


def _bind(path: Path, **extra: Any) -> dict[str, Any]:
    data = path.read_bytes()
    return {
        "path": _relative(path),
        "byte_size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        **extra,
    }


def _binding(path: str) -> dict[str, str]:
    document = json.loads((ROOT / path).read_bytes())
    return {
        "path": path,
        "record_sha256": hashlib.sha256(canonical_json(document["record"])).hexdigest(),
    }


def _pose(pose: dict[str, Any]) -> dict[str, int]:
    return {
        "xMm": _mm(pose["x"]),
        "yMm": _mm(pose["y"]),
        "zMm": _mm(pose["z"]),
        "yawMicroradians": _micro(pose["yaw"]),
        "pitchMicroradians": _micro(pose["pitch"]),
    }


def _earlier_record(scored: dict[str, Any]) -> dict[str, Any]:
    """What the Flatiron artifact's own earlier record bound, read from that record."""
    path = "docs/evaluation/2026-09-13-owned-world-local-proof.json"
    record = json.loads((ROOT / path).read_bytes())["record"]
    bound = next(item for item in record["artifacts"] if item["path"] == scored["path"])
    return {
        "path": path,
        "record_sha256": _binding(path)["record_sha256"],
        "boundArtifactByteSize": bound["byte_size"],
        "boundArtifactSha256": bound["sha256"],
        "sameArtifact": bound["sha256"] == scored["sha256"],
        "hasHardPassBlock": "hardPass" in record,
    }


def _planar_mm(first: dict[str, Any], second: dict[str, Any]) -> int:
    return _mm(((first["x"] - second["x"]) ** 2 + (first["z"] - second["z"]) ** 2) ** 0.5)


def _repeat_capture_note(run: dict[str, Any], repeat: dict[str, Any]) -> str:
    """How the repeat run's captures relate to the ones the judge answered for."""
    parts = []
    for first, second in zip(run["captures"], repeat["captures"], strict=True):
        if first["sha256"] == second["sha256"]:
            parts.append(f"{first['label']} byte-identical to the first run's")
        else:
            distance = _planar_mm(first["pose"], second["pose"])
            parts.append(f"{first['label']} {distance} mm from the first run's pose")
    return (
        "Not re-scored. The judge answered for the first run's captures. The repeat run's "
        f"captures are {', '.join(parts)}."
    )


def _interaction(item: dict[str, Any]) -> dict[str, Any]:
    """An interaction with any length in integer millimetres, whichever unit the run wrote."""
    converted = {name: value for name, value in item.items() if name != "targetAlongMetres"}
    if "targetAlongMetres" in item:
        converted["targetAlongMm"] = _mm(item["targetAlongMetres"])
    return converted


def _load_run(path: Path) -> dict[str, Any]:
    run = json.loads(path.read_bytes())
    if run.get("profile") != "exulanica.visual-gate-run/v1":
        raise SystemExit(f"{path.name} is not a visual gate run")
    if run.get("keySet") != GATE_KEY_SET_VERSION:
        raise SystemExit(
            f"{path.name} was measured under {run.get('keySet')}, not {GATE_KEY_SET_VERSION}"
        )
    if [capture["label"] for capture in run["captures"]] != list(CAPTURE_LABELS):
        raise SystemExit(f"{path.name} does not hold the three route captures in order")
    for spelling in CANONICAL_SPELLINGS:
        if key(spelling).evidence_kind == "judged":
            if run["keys"][spelling] != "awaiting-named-judge":
                raise SystemExit(f"{path.name} decided {spelling}, which only the judge may do")
            continue
        decided = decide_mechanical(spelling, run["mechanical"][spelling])
        if decided is not run["keys"][spelling]:
            raise SystemExit(
                f"{path.name}: the harness decided {spelling} {run['keys'][spelling]} and the "
                f"record builder decides {decided} from the same numbers; nothing is written"
            )
    return run


def _unmodified(path: str, digest: str) -> dict[str, Any]:
    """The scored file is the committed file, byte for byte, and the run read those bytes."""
    committed = subprocess.run(
        ["git", "show", f"HEAD:{path}"], cwd=SOURCE_ROOT, capture_output=True, check=True
    ).stdout
    on_disk = (SOURCE_ROOT / path).read_bytes()
    same = (
        hashlib.sha256(committed).hexdigest() == digest
        and hashlib.sha256(on_disk).hexdigest() == digest
    )
    if not same:
        raise SystemExit(f"{path} differs from HEAD or from what the run read; nothing is scored")
    return {
        "path": path,
        "byte_size": len(on_disk),
        "sha256": digest,
        "gitBlob": _git("rev-parse", f"HEAD:{path}"),
        "identicalToHead": True,
    }


def _database_role(url: str) -> dict[str, Any]:
    if (
        "@" in url.split("//", 1)[-1].split("/", 1)[0]
        and ":" in url.split("//", 1)[-1].split("@", 1)[0]
    ):
        raise SystemExit("pass the API database URL without a password")
    with psycopg.connect(url, row_factory=dict_row) as connection:
        row = connection.execute(
            "select current_user as role_name, current_database() as database_name, "
            "r.rolsuper, r.rolbypassrls, exists ("
            "  select 1 from pg_class c join pg_namespace n on n.oid = c.relnamespace "
            "   where n.nspname = current_schema() and c.relrowsecurity and c.relowner = r.oid"
            ") as owns_rls_table, "
            "(select max(version) from schema_migrations) as schema_head "
            "from pg_roles r where r.rolname = current_user"
        ).fetchone()
    assert row is not None
    return {
        "role": row["role_name"],
        "database": row["database_name"],
        "superuser": row["rolsuper"],
        "bypassRls": row["rolbypassrls"],
        "ownsRowLevelSecurityTable": row["owns_rls_table"],
        "schemaHead": row["schema_head"],
    }


def _rubric() -> tuple[bytes, str]:
    """The rubric on disk, which must be the one the version 2 reconciliation record fixed."""
    rubric = (ROOT / RUBRIC_PATH).read_bytes()
    digest = hashlib.sha256(rubric).hexdigest()
    fixed = json.loads(RECONCILIATION.read_bytes())["record"]["judgedKey"]
    if fixed["rubricSha256"] != digest or RUBRIC_COPY.read_bytes() != rubric:
        raise SystemExit(
            f"{RUBRIC_PATH} is not the rubric {_relative(RECONCILIATION)} fixed; a changed rubric "
            "needs a new reconciliation record before anything is scored against it"
        )
    return rubric, digest


def _judgement(path: Path, rubric: bytes) -> tuple[JudgedAnswers, dict[str, Any]]:
    """The judge's answers exactly as retained, for the record builder to decide or refuse."""
    given = json.loads(path.read_bytes())
    if given.get("profile") != JUDGEMENT_PROFILE:
        raise SystemExit(f"{path.name} is not a {JUDGEMENT_PROFILE} judgement")
    if f"Named human judge: {given['judge']}\n".encode() not in rubric:
        raise SystemExit("the judge named in the answers is not the judge the rubric names")
    pictures = []
    for entry in given["pictures"]:
        if entry.get("picture") != PICTURE_TITLES.get(entry.get("label")):
            raise SystemExit(f"{entry.get('label')} was not shown under its own picture title")
        asked = entry["asked"]
        if asked and entry.get("prompt") != judge_prompt(entry["label"]):
            raise SystemExit(f"{entry['label']} was not asked in the rubric's words")
        pictures.append(
            PictureAnswer(
                label=entry["label"],
                capture_sha256=entry["captureSha256"],
                asked=asked,
                picked=entry.get("picked"),
                words=entry.get("words"),
                typed_by=entry.get("typedBy"),
                given_at=entry.get("givenAt"),
            )
        )
    answers = JudgedAnswers(
        judge=given["judge"],
        judged_on=given["judgedOn"],
        rubric_sha256=given["rubricSha256"],
        pictures=tuple(pictures),
    )
    asked_as = {
        "askedIn": given["askedIn"],
        "prompts": {
            entry["label"]: entry["prompt"] for entry in given["pictures"] if entry["asked"]
        },
        "options": given["options"],
    }
    return answers, asked_as


def _copy(source: Path, target: Path) -> Path:
    shutil.copyfile(source, target)
    if source.read_bytes() != target.read_bytes():
        raise SystemExit(f"{target.name} did not copy byte for byte")
    return target


def _browser_metrics(run: dict[str, Any]) -> dict[str, Any]:
    report = run["validationReport"]
    measurement = report["measurement"]
    return {
        "profile": "exulanica.visual-gate-browser-metrics/v1",
        "engine": run["browser"]["engine"],
        "viewport": run["browser"]["viewport"],
        "deviceScaleFactor": run["browser"]["deviceScaleFactor"],
        "mountMs": run["browser"]["mountMs"],
        "productValidationReport": {
            "profile": report["profile"],
            "measurement": {
                name: value
                for name, value in measurement.items()
                if name not in ("camera_segments",)
            },
            "runtime": {
                name: value
                for name, value in report["runtime"].items()
                if name not in ("browser_user_agent",)
            },
            "renderer": report["renderer"],
            "network": report["network"],
            "memoryWorkspace": {
                "scene": report["scene"],
                "uploadedPointMaps": report["geometry"]["uploaded_point_map_count"],
                "uploadedPoints": report["geometry"]["uploaded_point_count"],
                "authenticatedNetworkBytes": report["geometry"]["authenticated_network_bytes"],
            },
        },
        "environment": run["network"]["environment"],
        "scene": run["scene"],
        "pageNetwork": {
            name: value for name, value in run["network"].items() if name != "environment"
        },
        "errors": run["errors"],
        "authentication": run["authentication"],
    }


def _gate_measurements(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "profile": "exulanica.visual-gate-measurements/v1",
        "keySet": run["keySet"],
        "route": run["route"],
        "arrival": run["arrival"],
        "interactions": run["interactions"],
        "harnessWrites": run["harnessWrites"],
        "harnessObservers": run["harnessObservers"],
        "measured": run["measured"],
        "observation": run["observation"],
        "mechanical": run["mechanical"],
        "keys": run["keys"],
        "listeners": run["listeners"],
        "authoredObjects": run["authoredObjects"],
        "captureStates": [
            {
                "label": capture["label"],
                "pose": capture["pose"],
                "stats": capture["stats"],
                "alongMetres": capture["alongMetres"],
                "state": capture["state"],
            }
            for capture in run["captures"]
        ],
        "trace": run["trace"],
    }


def _differences(first: Any, second: Any, path: str = "") -> list[str]:
    if isinstance(first, dict) and isinstance(second, dict):
        found = []
        for name in sorted(set(first) | set(second)):
            found += _differences(
                first.get(name), second.get(name), f"{path}.{name}" if path else name
            )
        return found
    return [] if first == second else [path]


def _because_judged(detail: dict[str, Any]) -> str:
    decisive = detail["decisiveNo"]
    if decisive is None:
        return "the named judge answered yes for all three pictures"
    unasked = [entry["picture"] for entry in detail["pictures"] if entry["state"] != "answered"]
    tail = ""
    if unasked:
        tail = f", so {' and '.join(unasked)} {'was' if len(unasked) == 1 else 'were'} not asked"
    return f"the named judge answered no to {PICTURE_TITLES[decisive]} ({decisive}){tail}"


def baseline(arguments: argparse.Namespace) -> int:
    run_path = Path(arguments.run).resolve()
    repeat_path = Path(arguments.repeat).resolve()
    run = _load_run(run_path)
    repeat = _load_run(repeat_path)
    if run["keys"] != repeat["keys"]:
        raise SystemExit("the repeat run did not produce the same key set; nothing is written")
    rubric, rubric_sha = _rubric()
    judged, asked_as = _judgement(Path(arguments.judgement).resolve(), rubric)
    try:
        judged_value, judged_detail = decide_judged(
            judged,
            rubric_sha256=rubric_sha,
            captures={capture["label"]: capture["sha256"] for capture in run["captures"]},
        )
    except GateEvidenceError as error:
        raise SystemExit(f"nothing is written: {error}") from error

    scored_artifact = _unmodified(
        run["scored"]["artifact"]["path"], run["scored"]["artifact"]["sha256"]
    )
    scored_renderer = _unmodified(
        run["scored"]["renderer"]["path"], run["scored"]["renderer"]["sha256"]
    )
    for other in (repeat,):
        if other["scored"] != run["scored"]:
            raise SystemExit("the two runs scored different files")
    role = _database_role(arguments.api_database_url)
    if role["superuser"] or role["bypassRls"] or role["ownsRowLevelSecurityTable"]:
        raise SystemExit(f"the API role is privileged: {role}")

    if ARTIFACTS.exists():
        if not arguments.replace:
            raise SystemExit(f"{_relative(ARTIFACTS)} exists; retained artifacts are not rewritten")
        shutil.rmtree(ARTIFACTS)
    ARTIFACTS.mkdir(parents=True)
    run_dir = run_path.parent
    repeat_dir = repeat_path.parent

    captures = []
    for index, capture in enumerate(run["captures"], start=1):
        target = _copy(
            run_dir / capture["file"],
            ARTIFACTS / f"capture-{index:02d}-route-{capture['label']}.png",
        )
        bound = _bind(target, label=capture["label"], pose=_pose(capture["pose"]))
        if bound["sha256"] != capture["sha256"]:
            raise SystemExit(f"{capture['file']} changed after the run")
        captures.append(bound)
    repeat_captures = []
    for index, capture in enumerate(repeat["captures"], start=1):
        target = _copy(
            repeat_dir / capture["file"],
            ARTIFACTS / f"repeat-capture-{index:02d}-route-{capture['label']}.png",
        )
        repeat_captures.append(_bind(target, label=capture["label"], pose=_pose(capture["pose"])))

    written = {
        "browser-metrics.json": _browser_metrics(run),
        "gate-measurements.json": _gate_measurements(run),
        "repeat-browser-metrics.json": _browser_metrics(repeat),
        "repeat-gate-measurements.json": _gate_measurements(repeat),
    }
    for name, document in written.items():
        text = json.dumps(_no_floats(document), indent=2, ensure_ascii=False) + "\n"
        _refuse_forbidden(text, name)
        (ARTIFACTS / name).write_text(text, encoding="utf-8")
    for label, directory, source in (
        ("route-trace.json", run_dir, run_path.name.replace("-run.json", "-trace.json")),
        (
            "repeat-route-trace.json",
            repeat_dir,
            repeat_path.name.replace("-run.json", "-trace.json"),
        ),
    ):
        _copy(directory / source, ARTIFACTS / label)
    checks_log = Path(arguments.checks_log).resolve()
    checks_text = checks_log.read_text(encoding="utf-8")
    _refuse_forbidden(checks_text, checks_log.name)
    (ARTIFACTS / "checks.log.txt").write_text(checks_text, encoding="utf-8")

    artifacts = [_bind(RUBRIC_COPY)]
    for name in (
        "browser-metrics.json",
        "gate-measurements.json",
        "route-trace.json",
        "repeat-browser-metrics.json",
        "repeat-gate-measurements.json",
        "repeat-route-trace.json",
        "checks.log.txt",
    ):
        artifacts.append(_bind(ARTIFACTS / name))
    artifacts += captures
    artifacts += repeat_captures

    mechanical_differences = {
        spelling: _differences(run["mechanical"][spelling], repeat["mechanical"][spelling])
        for spelling in CANONICAL_SPELLINGS
        if spelling != JUDGED_KEY
    }
    report = run["validationReport"]
    measurement = report["measurement"]
    repeat_measurement = repeat["validationReport"]["measurement"]
    melbourne = json.loads(
        (ROOT / "docs/evaluation/2026-09-12-melbourne-c4-29-visual-feasibility.json").read_bytes()
    )["record"]
    capture_states = [capture["state"] for capture in run["captures"]]

    evidence: dict[str, Any] = {
        spelling: run["mechanical"][spelling]
        for spelling in CANONICAL_SPELLINGS
        if spelling != JUDGED_KEY
    }
    evidence[JUDGED_KEY] = judged
    integrity = run["measured"]["integrity"]
    walk = run["measured"]["walk"]
    capsule = run["measured"]["capsule"]
    measured = run["measured"]
    budget = run["mechanical"]["practicalBrowserBudget"]
    companion = run["mechanical"]["companionPresent"]
    reticle = run["mechanical"]["reticlePresent"]
    shell = run["mechanical"]["authenticatedShellAndAuthoredHandlersPreserved"]
    held = {
        spelling: judged_value if spelling == JUDGED_KEY else run["keys"][spelling]
        for spelling in CANONICAL_SPELLINGS
    }
    because = {
        "continuousTexturedStreetAndFacades": (
            f"{measured['walkingTriangles'] + measured['facadeTriangles']:,} walking-surface and "
            f"facade triangles were drawn and "
            f"{measured['untexturedWalkingTriangles'] + measured['untexturedFacadeTriangles']:,} "
            "of them are untextured"
        ),
        "readsAsInhabitedStreet": _because_judged(judged_detail),
        "noCutsOrFloatingGeometry": (
            f"{integrity['componentsDetachedFromSupport']:,} drawn components have no chain of "
            f"contact to the walking surface and {integrity['trianglesInsideBuildings']:,} drawn "
            "triangles lie inside building volumes"
        ),
        "usefulEyeLevelMovement": (
            f"the product's own movement carried the player {walk['walkedDisplacementMm']:,} mm "
            f"with {walk['maxLateralDeviationMm']} mm lateral deviation, "
            f"{walk['routeSupportGapSamples']} support gaps and a largest eye-height error of "
            f"{walk['maxEyeHeightErrorMm']} mm over {walk['traceSamples']:,} samples"
        ),
        "completeCapsuleClearanceVerification": (
            f"{capsule['capsuleSamplesChecked']:,} of {capsule['capsuleSamples']:,} samples were "
            f"checked with {capsule['capsuleTriangleContactSamples']} triangle and "
            f"{capsule['capsuleRingContactSamples']} ring contacts"
        ),
        "practicalBrowserBudget": (
            f"{budget['environmentTransferredBytes']:,} "
            f"environment bytes, {measured['drawnTriangles']:,} drawn triangles, "
            f"{budget['environmentDecodedTextureBytes']:,} "
            f"decoded environment texture bytes and "
            f"{budget['maxDrawCalls']} draw calls, with {budget['gpuErrors']} GPU errors and "
            f"{budget['pageErrors']} uncaught page exceptions"
        ),
        "companionPresent": (
            f"the Companion was shown in {companion['capturesWithCompanionShown']} of "
            f"{companion['captures']} captures"
        ),
        "reticlePresent": (
            f"the reticle was drawn and centred in {reticle['capturesWithReticleCentred']} of "
            f"{reticle['captures']} captures"
        ),
        "authenticatedShellAndAuthoredHandlersPreserved": (
            f"{shell['capturesInProductShell']} of {shell['captures']} captures were taken in the "
            "product shell with a mounted world; of the listeners on the window, document and "
            f"canvas, {run['listeners']['counts']['product']} came from the product's modules and "
            f"{shell['foreignListeners']} from anywhere else; "
            f"{shell['interactionsNotCarriedByProduct']} interactions were not carried by the "
            f"product's own handlers and {shell['substitutedPages']} pages were substituted"
        ),
    }
    failed = [spelling for spelling in CANONICAL_SPELLINGS if not held[spelling]]
    passed = [spelling for spelling in CANONICAL_SPELLINGS if held[spelling]]
    reason = (
        "The shipped Flatiron district, scored unmodified inside the authenticated product shell, "
        + (
            "fails the reconciled block. It fails "
            + "; ".join(f"{spelling}, because {because[spelling]}" for spelling in failed)
            + ". It holds "
            + "; ".join(f"{spelling}, because {because[spelling]}" for spelling in passed)
            + "."
            if failed
            else "holds all nine keys: "
            + "; ".join(f"{spelling}, because {because[spelling]}" for spelling in passed)
            + "."
        )
    )
    melbourne_browser = melbourne["browser"]
    melbourne_preprocessing = melbourne["preprocessing"]
    comparison = {
        "note": (
            "Melbourne's values are quoted from its retained record for comparison. Only the "
            "first four decide practicalBrowserBudget; the rest vary between runs and are "
            "reported, not gated."
        ),
        "environmentTransferredBytes": {
            "flatiron": run["mechanical"]["practicalBrowserBudget"]["environmentTransferredBytes"],
            "melbourne": melbourne_preprocessing["totalBrowserAssetBytes"],
        },
        "drawnTriangles": {
            "flatiron": measured["drawnTriangles"],
            "melbourne": melbourne_preprocessing["emittedFaces"],
        },
        "environmentDecodedTextureBytes": {
            "flatiron": run["mechanical"]["practicalBrowserBudget"][
                "environmentDecodedTextureBytes"
            ],
            "melbourne": melbourne_preprocessing["decodedAtlasBytes"],
        },
        "maxDrawCalls": {
            "flatiron": report["renderer"]["max_draw_calls"],
            "melbourne": melbourne_browser["maxDrawCalls"],
        },
        "frames": {"flatiron": measurement["frames"], "melbourne": melbourne_browser["frames"]},
        "frameP95Ms": {
            "flatiron": _decimal(measurement["frameP95Ms"]),
            "melbourne": melbourne_browser["frameP95Ms"],
        },
        "fpsP1Low": {
            "flatiron": _decimal(measurement["fpsP1Low"]),
            "melbourne": melbourne_browser["fpsP1Low"],
        },
        "peakJsHeapMb": {
            "flatiron": _decimal(report["runtime"]["peak_js_heap_mb"]),
            "melbourne": melbourne_browser["peakJsHeapMb"],
        },
        "firstMeaningfulRenderMs": {
            "flatiron": _decimal(measurement["first_meaningful_render_ms"]),
            "melbourne": melbourne_browser["firstMeaningfulRenderMs"],
        },
        "gpuError": {
            "flatiron": report["renderer"]["gpu_error"],
            "melbourne": melbourne_browser["gpuError"],
        },
        "completeCapsuleClearanceVerification": {
            "flatiron": held["completeCapsuleClearanceVerification"],
            "melbourne": melbourne["hardPass"]["completeCapsuleClearanceVerification"],
        },
        "gpu": {"flatiron": report["runtime"]["gpu"], "melbourne": melbourne_browser["gpu"]},
    }
    repeat_report = repeat["validationReport"]
    repeat_block = {
        "run": _relative(ARTIFACTS / "repeat-gate-measurements.json"),
        "keySetIdentical": run["keys"] == repeat["keys"],
        "mechanicalKeysIdentical": all(
            run["keys"][spelling] == repeat["keys"][spelling]
            for spelling in CANONICAL_SPELLINGS
            if spelling != JUDGED_KEY
        ),
        "mechanicalFieldsThatDiffered": {
            spelling: [
                {
                    "field": field,
                    "firstRun": run["mechanical"][spelling][field],
                    "repeatRun": repeat["mechanical"][spelling][field],
                }
                for field in fields
            ]
            for spelling, fields in mechanical_differences.items()
            if fields
        },
        "captures": repeat_captures,
        "captureDisplacementFromFirstRunMm": [
            _planar_mm(first["pose"], second["pose"])
            for first, second in zip(run["captures"], repeat["captures"], strict=True)
        ],
        "variableMeasurements": {
            "frames": [measurement["frames"], repeat_measurement["frames"]],
            "frameP95Ms": [
                _decimal(measurement["frameP95Ms"]),
                _decimal(repeat_measurement["frameP95Ms"]),
            ],
            "fpsP1Low": [
                _decimal(measurement["fpsP1Low"]),
                _decimal(repeat_measurement["fpsP1Low"]),
            ],
            "peakJsHeapMb": [
                _decimal(report["runtime"]["peak_js_heap_mb"]),
                _decimal(repeat_report["runtime"]["peak_js_heap_mb"]),
            ],
            "firstMeaningfulRenderMs": [
                _decimal(measurement["first_meaningful_render_ms"]),
                _decimal(repeat_measurement["first_meaningful_render_ms"]),
            ],
            "maxDrawCalls": [
                report["renderer"]["max_draw_calls"],
                repeat_report["renderer"]["max_draw_calls"],
            ],
        },
        "judgedKey": _repeat_capture_note(run, repeat),
    }
    route = run["route"]
    try:
        document = visual_gate_record(
            profile="exulanica.visual-gate-flatiron-baseline/v1",
            record_path=_relative(BASELINE),
            date=arguments.date,
            status="baseline_measured",
            base=_git("rev-parse", "HEAD"),
            branch=_git("branch", "--show-current"),
            predecessor_records=[
                _binding(_relative(RECONCILIATION)),
                _binding(SUPERSEDED_RECONCILIATION),
                *(_binding(record.path) for record in RETAINED_RECORDS),
            ],
            artifacts=artifacts,
            captures=captures,
            rubric_sha256=rubric_sha,
            browser={
                "engine": run["browser"]["engine"],
                "viewport": run["browser"]["viewport"],
                "gpu": report["runtime"]["gpu"],
                "peakJsHeapMb": _decimal(report["runtime"]["peak_js_heap_mb"]),
                "firstMeaningfulRenderMs": _decimal(measurement["first_meaningful_render_ms"]),
                "frames": measurement["frames"],
                "frameP95Ms": _decimal(measurement["frameP95Ms"]),
                "fpsP1Low": _decimal(measurement["fpsP1Low"]),
                "maxDrawCalls": report["renderer"]["max_draw_calls"],
                "gpuError": report["renderer"]["gpu_error"],
                "reticlePresent": all(state["reticle"]["centred"] for state in capture_states),
                "companionPresent": all(state["companion"]["shown"] for state in capture_states),
                "authenticatedShellPresent": all(
                    state["inProductShell"] for state in capture_states
                ),
                "pageErrors": run["errors"]["exceptions"],
                "consoleErrors": run["errors"]["consoleErrors"],
                "previewApi404s": [
                    item
                    for item in run["authentication"]["previewApiRequests"]
                    if item["status"] == 404
                ],
                "authoredObjectIds": run["authoredObjects"]["objectIds"],
                "eyeHeightMetres": "1.62",
                "measuredBy": "the product's own validation=1 recorder, read after its window closed",
            },
            evidence=evidence,
            authentication_condition=run["authentication"]["condition"],
            reason=reason,
            checks={
                "harnessRuns": 2,
                "repeatKeySetIdentical": repeat_block["keySetIdentical"],
                "recordBuilderAgreedWithHarnessOnEveryMechanicalKey": True,
                "scoredFilesIdenticalToHead": True,
                "checksRunBeforeThisRecordWasWritten": _relative(ARTIFACTS / "checks.log.txt"),
            },
            claims_not_made=[
                "No capture shows observed street geometry. The building footprints and heights come "
                "from NYC Open Data and are extruded by the renderer; the ground and the road are "
                "generated, and the artifact marks both generated: true; windows, cornices, doors, "
                "rooftop boxes, trees, lamps and every colour are invented by the compiler or the "
                "renderer and observe nothing.",
                "No texture is claimed. None is bound anywhere in the district, and the decoded "
                "environment texture bytes were measured as zero.",
                "Frame time, low-percentile frame rate, heap and first render are measurements of "
                "this machine in this run. They are reported and do not decide any key. The page also "
                "fetched and uploaded the credentialed workspace's retained reconstruction, which the "
                "district view does not draw and which dominates the page transfer and the heap.",
                "Pointer lock was never held. The heading was set by writing the controls' yaw, and "
                "every position came from the product's own movement.",
                "readsAsInhabitedStreet was answered by the named judge, one picture at a time under "
                "rubric version 2. No model produced, suggested, pre-filled or ranked an answer, and "
                "nothing was inferred from the judge's words. The words are kept exactly as typed in "
                "this record's private companion, and this record carries their SHA-256 and byte "
                "count.",
                "A picture listed as not asked after a decisive no was not shown to the judge for an "
                "answer, and nothing is claimed about how it would have been answered.",
                "The three retained rejections are not scored or re-scored here.",
                "The Flatiron artifact and its renderer were scored unmodified and were not "
                "regenerated.",
                "Nothing is claimed about any street, district or city beyond the route walked.",
                "The credential is a lane-local development token for a scratch copy of the retained "
                "judge seed. Nothing is claimed about accounts or production credentials.",
            ],
            extra={
                "naming": (
                    "The file name carries 2026-09-15, the date the phase 0 plan fixed for it; date is "
                    "the day the run was made."
                ),
                "scored": {
                    "artifact": {
                        **scored_artifact,
                        "profile": run["scored"]["artifact"]["profile"],
                        "districtId": run["scored"]["artifact"]["districtId"],
                    },
                    "renderer": scored_renderer,
                    "earlierRecordOfThisArtifact": _earlier_record(scored_artifact),
                },
                "contentPlanes": {
                    "buildingFootprintsAndHeights": (
                        "source-derived, NYC Open Data dataset 5zhs-2jue, as recorded in the "
                        "artifact's source records"
                    ),
                    "sidewalkOutlines": (
                        "source-derived, NYC Open Data dataset 52n9-sdep, drawn by the renderer as "
                        "fans from each outline's centroid"
                    ),
                    "groundAndRoad": "generated: the artifact's ground and road_completion are generated: true",
                    "facadeDetailAndStreetFurniture": (
                        "invented at draw time by the renderer and not present in the artifact"
                    ),
                    "materials": "assigned by the compiler from an integer index, not observed",
                },
                "authentication": {
                    "condition": run["authentication"]["condition"],
                    "relativeToMelbourne": (
                        "stronger: Melbourne used the Vite-only preview API; this run used a real "
                        "bearer token against a real API that refused the same read without one"
                        if run["authentication"]["condition"] == "credentialed-api"
                        else "equal: the Vite-only preview API, as in Melbourne"
                    ),
                    "anonymousGraphReadStatus": run["authentication"]["anonymousGraphReadStatus"],
                    "apiResponses": run["authentication"]["apiResponses"],
                    "previewApiRequests": run["authentication"]["previewApiRequests"],
                    "apiDatabase": role,
                    "bootGuard": (
                        "exulanica/api/app.py calls assert_runtime_role at startup, which refuses a "
                        "superuser, a BYPASSRLS role or an owner of a row-level-security table"
                    ),
                    "workspace": {
                        "id": arguments.workspace_id,
                        "description": arguments.workspace_description,
                    },
                    "credential": (
                        "a lane-local development token given to the dev server as "
                        "VITE_EXULANICA_TOKEN, never read by the harness and never recorded"
                    ),
                },
                "route": {
                    **route,
                    "rule": (
                        "From the product's arrival pose, every heading at half-degree steps; a "
                        "heading qualifies when a 0.34 m capsule clears the route length plus the "
                        "stop margin; the most 1 m samples with collision rings within the frontage "
                        "search on both sides wins, then the heading most parallel to that frontage, "
                        "then the smaller angle."
                    ),
                    "ruleParameters": route["rule"],
                    "arrivalPose": _pose(run["arrival"]),
                    "captureAlongRouteMm": [
                        _mm(capture["alongMetres"]) for capture in run["captures"]
                    ],
                },
                "movement": {
                    "interactions": [_interaction(item) for item in run["interactions"]],
                    "harnessWrites": run["harnessWrites"],
                    "harnessObservers": run["harnessObservers"],
                    "traceFrames": run["trace"]["frames"],
                    "walk": walk,
                },
                "integrity": integrity,
                "capsule": capsule,
                "classification": {
                    "drawnMeshes": measured["drawnMeshes"],
                    "drawnTriangles": measured["drawnTriangles"],
                    "walkingTriangles": measured["walkingTriangles"],
                    "facadeTriangles": measured["facadeTriangles"],
                    "untexturedWalkingTriangles": measured["untexturedWalkingTriangles"],
                    "untexturedFacadeTriangles": measured["untexturedFacadeTriangles"],
                    "texturedMeshes": measured["texturedMeshes"],
                    "deviceTextureBytes": run["scene"]["deviceTextureBytes"],
                    "environmentTextures": run["scene"]["environmentTextures"],
                },
                "listeners": run["listeners"]["counts"],
                "melbourneComparison": comparison,
                "repeatRun": repeat_block,
                "judgement": {
                    "judge": judged.judge,
                    "judgedOn": judged.judged_on,
                    "rubric": RUBRIC_PATH,
                    "rubricVersion": RUBRIC_VERSION,
                    "rubricCopy": _relative(RUBRIC_COPY),
                    "answeredFrom": (
                        "each capture above, shown alone at full size under its picture title and "
                        "followed by its one question, in route order, stopping at the first no"
                    ),
                    **asked_as,
                },
                "observations": _observations(run),
                "limitations": [
                    "Pointer lock is not granted to automation, so the heading was written rather "
                    "than looked, and the product's mouse-look path was not exercised.",
                    "The Companion was summoned so that the product keeps walking available without "
                    "pointer lock; its open encounter is visible in every capture.",
                    "The credentialed workspace is the only retained workspace in the judge seed with "
                    "a scene group, so the Atlas mounts only for it. Its reconstruction is fetched "
                    "and uploaded but not drawn in the district view.",
                    "Contact and inside-building tests use a 0.05 m tolerance and even-odd "
                    "containment; hidden geometry counts exactly as visible geometry does.",
                    "Walking speed is the product's 32 m/s city speed, so the live trace holds about "
                    "one pose every 0.5 m and is resampled to 0.05 m by interpolation.",
                    "Transferred bytes for the environment include the response headers the browser "
                    "counted; the body alone is reported beside it.",
                ],
            },
        )
    except GateEvidenceError as error:
        shutil.rmtree(ARTIFACTS, ignore_errors=True)
        raise SystemExit(f"nothing is written: {error}") from error
    companion_path, companion = judge_words_file(_relative(BASELINE), judged)
    if document["record"]["judgeWords"]["sha256"] != hashlib.sha256(companion).hexdigest():
        raise SystemExit("the private companion is not the one the record binds")
    _write_private(companion_path, companion, replace=arguments.replace)
    private = [reply["words"] for reply in judge_words(judged) if reply["words"] is not None]
    _write(BASELINE, document, replace=arguments.replace, private=private)
    written_bytes = BASELINE.read_bytes()
    print(
        f"{_relative(BASELINE)} {len(written_bytes)} bytes, "
        f"sha256 {hashlib.sha256(written_bytes).hexdigest()}, "
        f"record_sha256 {document['record_sha256']}, verdict {document['record']['verdict']}"
    )
    return 0


def _observations(run: dict[str, Any]) -> list[str]:
    """Measured facts about the renderer that no key decides, stated so nobody rediscovers them."""
    integrity = run["measured"]["integrity"]
    observations = []
    for mesh_id, tally in sorted(run["measured"]["classifiedByMesh"].items()):
        if tally["drawn"] > 0 and 0 < tally["walking"] < tally["drawn"] and tally["facade"] == 0:
            culled = next(m["cull"] for m in run["scene"]["meshes"] if m["id"] == mesh_id)
            observations.append(
                f"{mesh_id.rsplit('/', 1)[-1]} draws {tally['drawn']:,} flat triangles with "
                f"{culled}-face culling, and only {tally['walking']:,} of them face upward as a "
                "floor; the rest face down and are not drawn from above."
            )
    detached = integrity["detachedByMesh"]
    if detached:
        observations.append(
            "Components with no chain of contact to the walking surface, by mesh: "
            + ", ".join(
                f"{name.rsplit('/', 1)[-1]} {count:,}" for name, count in sorted(detached.items())
            )
            + ". They are planes offset from their walls with nothing joining them."
        )
    inside = integrity["insideByMesh"]
    if inside:
        observations.append(
            "Drawn triangles inside building volumes, by mesh: "
            + ", ".join(
                f"{name.rsplit('/', 1)[-1]} {count:,}" for name, count in sorted(inside.items())
            )
            + f", across {len(integrity['buildingsWithDrawnGeometryInside'])} buildings."
        )
    return observations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    verbs = parser.add_subparsers(dest="verb", required=True)
    reconcile = verbs.add_parser("reconciliation", help="write the key reconciliation record")
    reconcile.add_argument("--date", required=True, help="ISO date the record is produced")
    reconcile.add_argument("--replace", action="store_true")
    reconcile.set_defaults(handler=reconciliation)
    base = verbs.add_parser("baseline", help="write the Flatiron baseline record")
    base.add_argument("--date", required=True)
    base.add_argument("--run", required=True, help="the first run's <label>-run.json")
    base.add_argument("--repeat", required=True, help="the repeat run's <label>-run.json")
    base.add_argument("--judgement", required=True, help="the named judge's answers")
    base.add_argument("--checks-log", required=True, help="the checks run before this record")
    base.add_argument(
        "--api-database-url",
        required=True,
        help="the API's database URL, without a password, to confirm its role read-only",
    )
    base.add_argument("--workspace-id", required=True, help="the workspace the token is bound to")
    base.add_argument(
        "--workspace-description", required=True, help="what that workspace holds, in words"
    )
    base.add_argument("--replace", action="store_true")
    base.set_defaults(handler=baseline)
    arguments = parser.parse_args(argv)
    return arguments.handler(arguments)


if __name__ == "__main__":
    sys.exit(main())
