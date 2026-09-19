"""Write the visual gate's digest-bound records from what was measured, and nothing else.

Three verbs, because they bind different evidence:

``reconciliation``
    Reads the three retained rejection records and their briefs, the version 4 reconciliation
    record, the rubric and the reply typed under version 4, recomputes every digest, resolves
    every hardPass spelling through ``exulanica.evaluation.gate_keys``, checks that no corridor and
    no record was scored against an earlier key set, retains a byte-for-byte copy of the rubric,
    binds the picture the reply is about as the version 3 record retained it, writes the reply's
    words to the record's private companion, and writes
    ``docs/evaluation/2026-09-16-visual-gate-key-reconciliation-v5.json``. Any disagreement
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

``corridor``
    Reads one harness run of a generated tile, the named judge's answers and the captures, copies
    the captures and the run's own measurements under ``docs/evaluation/artifacts/<record>/``,
    binds each by byte size and SHA-256, re-decides every mechanical key from the measured
    numbers, refuses to write when its decision and the harness's disagree, and writes the record
    ``--record`` names. It also requires the record that states which STORE the run read, and
    checks that record's bindings of the captures and the run against the files themselves, so
    every digest is read twice by two paths that never met.

    A JUDGEMENT THE RUBRIC DOES NOT ALLOW DOES NOT STOP THE WRITE; IT CHANGES WHAT IS WRITTEN. A
    disagreement between this builder and the harness means one of them is wrong and neither may
    be published, so nothing is written. A refused judgement is different: it is a measurement of
    how the asking was done, and it is the one thing most worth writing down, because nothing else
    keeps it from happening again. The record is then not a gate record: it carries no hardPass
    block and no verdict, it reports no answer, and it binds the three pictures by digest so that
    a later, proper ask can be shown to be about the same three.

Every number in a record is read from a measurement file of the run it describes. None is copied
from a previous document, and no credential is read, printed or written: the harness output never
carries one, and this script refuses to write a record that contains a forbidden string.

The judge's words are written only to a record's private companion under
``.exulanica/judge-words/``, which git ignores. The public record carries their SHA-256 and byte
count, and this script refuses to write a public record that contains any of them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from exulanica.canonical import canonical_json
from exulanica.evaluation.gate_keys import (
    ANSWER_OPTIONS,
    ANSWER_REQUIREMENT,
    CANONICAL_SPELLINGS,
    CAPTURE_LABELS,
    CARRIED_WORDS_NOTICE,
    GATE_KEY_SET_VERSION,
    GENERATED_TILE_TARGET,
    JUDGED_KEY,
    MELBOURNE_ENVELOPE,
    NOT_ASKED,
    PICTURE_TITLES,
    RETAINED_RECORDS,
    RUBRIC_GUIDANCE,
    RUBRIC_PATH,
    RUBRIC_QUESTION,
    RUBRIC_V1,
    RUBRIC_VERSION,
    SUPERSEDED_VERSIONS,
    judge_prompt,
    key,
    reason_follow_up,
)
from exulanica.evaluation.visual_gate import (
    JUDGEMENT_ANSWERS_PROFILE,
    GateEvidenceError,
    _comparable,
    CarriedWords,
    JudgedAnswers,
    PictureAnswer,
    ReasonFollowUp,
    decide_judged,
    calibration_words_file,
    decide_mechanical,
    digest_bound,
    judge_words,
    judge_words_file,
    judge_words_path,
    reconciliation_record,
    refuse_private_words,
    visual_gate_record,
)

#: The repository the scored files and git history come from.
SOURCE_ROOT = Path(__file__).resolve().parents[1]
#: Where documents are read from and written to. The repository itself, except in a dry run of
#: the writer against a scratch copy of docs/, which never touches the retained tree.
ROOT = Path(os.environ.get("VISUAL_GATE_DOCUMENT_ROOT", SOURCE_ROOT)).resolve()
#: The reconciliation records before the current one, oldest first. Each supersedes the last.
EARLIER_RECONCILIATIONS = (
    "docs/evaluation/2026-09-15-visual-gate-key-reconciliation.json",
    "docs/evaluation/2026-09-16-visual-gate-key-reconciliation-v2.json",
    "docs/evaluation/2026-09-16-visual-gate-key-reconciliation-v3.json",
    "docs/evaluation/2026-09-16-visual-gate-key-reconciliation-v4.json",
)
SUPERSEDED_RECONCILIATION = EARLIER_RECONCILIATIONS[-1]
RECONCILIATION = ROOT / "docs/evaluation/2026-09-16-visual-gate-key-reconciliation-v5.json"
RECONCILIATION_ARTIFACTS = (
    ROOT / "docs/evaluation/artifacts/2026-09-16-visual-gate-key-reconciliation-v5"
)
RUBRIC_COPY = RECONCILIATION_ARTIFACTS / "visual-gate-rubric.md"
BASELINE = ROOT / "docs/evaluation/2026-09-15-flatiron-owned-district-baseline.json"
ARTIFACTS = ROOT / "docs/evaluation/artifacts/2026-09-15-flatiron-owned-district-baseline"
FORBIDDEN = ("/Users/", "Bearer ", "api-token")
JUDGEMENT_PROFILE = JUDGEMENT_ANSWERS_PROFILE


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
    path: Path,
    document: dict,
    *,
    replace: bool,
    private: list[str] | tuple[str, ...] = (),
    lines: list[str] | tuple[str, ...] = (),
    shown: list[str] | tuple[str, ...] = (),
) -> None:
    if path.exists() and not replace:
        raise SystemExit(
            f"{_relative(path)} exists. A retained record is not rewritten; pass --replace only "
            "for a record that has never been committed."
        )
    text = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    _refuse_forbidden(text, path.name)
    try:
        # JSON quotes every key and value, so the quoted-part test, which the record builder has
        # already run on every string, would read keys such as "why" as quotations here.
        refuse_private_words(text, private, shown=shown, lines=lines, quoted=False)
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
    path.chmod(0o600)


def _private_words(companion: bytes) -> tuple[list[str], list[str]]:
    """The judge's words a private companion keeps, and the lines written for an ask beside them."""
    document = json.loads(companion)
    words = [item["words"] for item in document["replies"] if item.get("words") is not None]
    lines = [item["words"] for item in document.get("shownLines", [])]
    return words, lines


def _scored_before_revision() -> tuple[list[str], list[str]]:
    """Retained records that score a corridor, and those scored against an earlier key set."""
    corridors: list[str] = []
    earlier: list[str] = []
    for path in sorted((ROOT / "docs/evaluation").glob("*.json")):
        record = json.loads(path.read_bytes()).get("record", {})
        profile = str(record.get("profile", ""))
        if "corridor" in path.name.casefold() or "corridor" in profile.casefold():
            corridors.append(_relative(path))
        gate = record.get("gate")
        earlier_key_sets = {RUBRIC_V1.key_set, *(item.key_set for item in SUPERSEDED_VERSIONS)}
        if isinstance(gate, dict) and gate.get("keySet") in earlier_key_sets:
            earlier.append(_relative(path))
    return corridors, earlier


def _calibration_captures(calibration: dict[str, Any]) -> list[dict[str, Any]]:
    """The pictures the calibration evidence is about, as the superseded record retained them."""
    retained = json.loads((ROOT / SUPERSEDED_RECONCILIATION).read_bytes())["record"]["captures"]
    by_label = {capture["label"]: capture for capture in retained}
    captures = []
    for picture in calibration["pictures"]:
        capture = by_label[picture["label"]]
        data = (ROOT / capture["path"]).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != capture["sha256"] or digest != picture["captureSha256"]:
            raise SystemExit(f"{capture['path']} is not the picture the evidence is about")
        captures.append(
            {
                "label": capture["label"],
                "path": capture["path"],
                "byte_size": len(data),
                "sha256": digest,
            }
        )
    return captures


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
    if RECONCILIATION.exists() and not arguments.replace:
        raise SystemExit(f"{_relative(RECONCILIATION)} exists. A retained record is not rewritten.")
    corridors, earlier = _scored_before_revision()
    rubric = (ROOT / RUBRIC_PATH).read_bytes()
    calibration = json.loads(Path(arguments.calibration).read_bytes())
    captures = _calibration_captures(calibration)
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
            calibration=calibration,
            calibration_captures=captures,
            scored_corridors=corridors,
            scored_against_superseded=earlier,
            record_path=_relative(RECONCILIATION),
        )
        companion_path, companion = calibration_words_file(
            _relative(RECONCILIATION),
            calibration,
            captures,
            document["record"]["judgedKey"]["judge"],
        )
    except GateEvidenceError as error:
        raise SystemExit(f"nothing is written: {error}") from error
    if document["record"]["judgeWords"]["sha256"] != hashlib.sha256(companion).hexdigest():
        raise SystemExit("the private companion is not the one the record binds")
    RECONCILIATION_ARTIFACTS.mkdir(parents=True, exist_ok=True)
    RUBRIC_COPY.write_bytes(rubric)
    if RUBRIC_COPY.read_bytes() != rubric:
        raise SystemExit("the rubric did not copy byte for byte")
    _write_private(companion_path, companion, replace=arguments.replace)
    words, lines = _private_words(companion)
    _write(RECONCILIATION, document, replace=arguments.replace, private=words, lines=lines)
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


def _key_sets_measured_alike() -> set[str]:
    """The current key set, and every key set before it that no revision since has re-measured.

    Walks the chain of reconciliation records from the current one, and stops at the first
    revision that does not state its measurements unchanged.
    """
    alike = {GATE_KEY_SET_VERSION}
    record = json.loads(RECONCILIATION.read_bytes())["record"]
    while True:
        supersedes = record.get("supersedes", {})
        if supersedes.get("measurementsUnchanged") is not True:
            return alike
        alike.add(supersedes["keySet"])
        earlier = ROOT / supersedes["path"]
        if not earlier.is_file():
            return alike
        record = json.loads(earlier.read_bytes())["record"]


def _load_run(path: Path) -> dict[str, Any]:
    run = json.loads(path.read_bytes())
    if run.get("profile") != "exulanica.visual-gate-run/v1":
        raise SystemExit(f"{path.name} is not a visual gate run")
    if run.get("keySet") not in _key_sets_measured_alike():
        raise SystemExit(
            f"{path.name} was measured under {run.get('keySet')}, whose measurements "
            f"{GATE_KEY_SET_VERSION} does not share"
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


def _blob(commit: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"{commit}:{path}"], cwd=SOURCE_ROOT, capture_output=True, check=True
    ).stdout


def _measured_file(path: str, digest: str, measured_at: str) -> dict[str, Any]:
    """A file as the run read it: the committed blob at the commit the run was measured at."""
    if hashlib.sha256(_blob(measured_at, path)).hexdigest() != digest:
        raise SystemExit(f"{path} is not what the run read at {measured_at}; nothing is scored")
    at_head = hashlib.sha256(_blob("HEAD", path)).hexdigest() == digest
    return {
        "path": path,
        "byte_size": len(_blob(measured_at, path)),
        "sha256": digest,
        "gitBlob": _git("rev-parse", f"{measured_at}:{path}"),
        "identicalToHead": at_head,
    }


def _unmodified(path: str, digest: str, measured_at: str) -> dict[str, Any]:
    """A scored file: the bytes the run read, at the measured commit, at HEAD and on disk."""
    entry = _measured_file(path, digest, measured_at)
    on_disk = hashlib.sha256((SOURCE_ROOT / path).read_bytes()).hexdigest()
    if not entry["identicalToHead"] or on_disk != digest:
        raise SystemExit(f"{path} differs from HEAD or from what the run read; nothing is scored")
    return entry


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
    """The rubric on disk, which must be the one the current reconciliation record fixed."""
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
        notice = entry.get("notice")
        if asked:
            prompt = entry["prompt"]
            shown = prompt if notice is None else f"{notice}\n\n{prompt}"
            if entry.get("shown", shown) != shown:
                raise SystemExit(f"{entry['label']} was shown something other than its ask")
        follow = entry.get("followUp")
        pictures.append(
            PictureAnswer(
                label=entry["label"],
                capture_sha256=entry["captureSha256"],
                asked=asked,
                picked=entry.get("picked"),
                words=entry.get("words"),
                typed_by=entry.get("typedBy"),
                follow_up=None
                if follow is None
                else ReasonFollowUp(
                    shown=follow["shown"],
                    words=follow.get("words"),
                    typed_by=follow.get("typedBy"),
                    given_at=follow.get("givenAt"),
                ),
                carried=tuple(
                    CarriedWords(
                        words=item["words"],
                        typed_by=item["typedBy"],
                        rubric_version=item["rubricVersion"],
                        rubric_sha256=item["rubricSha256"],
                        given_at=item["givenAt"],
                        given_as=item["givenAs"],
                    )
                    for item in entry.get("carried", [])
                ),
                notice=notice,
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
        "shown": {
            entry["label"]: entry.get("shown", entry["prompt"])
            for entry in given["pictures"]
            if entry["asked"]
        },
        "followUps": {
            entry["label"]: entry["followUp"]["shown"]
            for entry in given["pictures"]
            if entry.get("followUp") is not None
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


def _reconstruction_claim(run: dict[str, Any]) -> str:
    """What the page did with the workspace's retained reconstruction, from the run's own counts."""
    reads = sum(
        count
        for name, count in run["authentication"]["apiResponses"].items()
        if name.startswith("GET /api/geometry/")
    )
    inventory = run["scene"]["layerInventory"]
    other = inventory["otherInstances"]
    if reads == 0:
        fetched = "The page fetched no retained reconstruction geometry"
    else:
        fetched = (
            f"The page also fetched the credentialed workspace's retained reconstruction ({reads} "
            "geometry reads), which weighs on the page transfer and the heap"
        )
    if sum(other.values()) == 0 and inventory["gsplatComponents"] == 0:
        drawn = (
            ". When the scene was read, the cameras' layers drew nothing but the "
            f"{inventory['renderComponentInstancesRead']} render mesh instances the triangle "
            "measurements read: no point instance, no line, no other mesh and no enabled splat."
        )
    else:
        drawn = (
            ". When the scene was read, the cameras' layers also drew "
            f"{other['triangles']} triangle, {other['points']} point, {other['lines']} line and "
            f"{other['other']} other mesh instances outside render components, and "
            f"{inventory['gsplatComponents']} enabled splats, none of which the triangle "
            "measurements read."
        )
    return fetched + drawn


def _judged_claim(detail: dict[str, Any]) -> str:
    """How the judged key was answered and read, as the record states it."""
    answered = detail["answeredAgainst"]["rubricVersion"]
    if answered == RUBRIC_VERSION:
        under = f"under rubric version {RUBRIC_VERSION}"
    else:
        under = (
            f"under rubric version {answered}, and read under rubric version {RUBRIC_VERSION}, "
            "which shows the judge the same words and changes only how a typed reply is read"
        )
    return (
        f"readsAsInhabitedStreet was answered by the named judge, one picture at a time, {under}. "
        "No model judged any picture: no model produced, suggested, pre-filled or ranked an "
        "answer, and the key stays reserved to the named human judge. Nothing beyond the "
        "rubric's typed-reply rule was inferred from the judge's words, which are kept exactly as "
        "typed in this record's private companion; this record carries their SHA-256 and byte "
        "count."
    )


def _because_judged(detail: dict[str, Any]) -> str:
    decisive = detail["decisiveNo"]
    if decisive is None:
        return "the named judge answered yes for all three pictures"
    unasked = [entry["picture"] for entry in detail["pictures"] if entry["state"] != "answered"]
    tail = ""
    if unasked:
        tail = f", so {' and '.join(unasked)} {'was' if len(unasked) == 1 else 'were'} not asked"
    picture = f"{PICTURE_TITLES[decisive]} ({decisive})"
    entry = next(entry for entry in detail["pictures"] if entry["label"] == decisive)
    if entry["picked"] is None:
        return (
            f"the named judge typed a reply to {picture} in place of a pick, and the rubric's "
            f"typed-reply rule reads it as no{tail}"
        )
    return f"the named judge picked no for {picture}{tail}"


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

    measured_at = _git("rev-parse", "--verify", f"{arguments.measured_at}^{{commit}}")
    if subprocess.run(
        ["git", "merge-base", "--is-ancestor", measured_at, "HEAD"], cwd=SOURCE_ROOT, check=False
    ).returncode not in (0, 1):
        raise SystemExit(f"{arguments.measured_at} is not a commit this repository holds")
    scored_artifact = _unmodified(
        run["scored"]["artifact"]["path"], run["scored"]["artifact"]["sha256"], measured_at
    )
    scored_renderer = _unmodified(
        run["scored"]["renderer"]["path"], run["scored"]["renderer"]["sha256"], measured_at
    )
    for other in (repeat,):
        if other["scored"] != run["scored"]:
            raise SystemExit(
                "the two runs scored different files or were measured by different code"
            )
    measured_by = [
        _measured_file(item["path"], item["sha256"], measured_at)
        for item in run["scored"]["measuredBy"]
    ]
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
            "flatiron": run["drawCalls"]["decidingMax"],
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
                run["drawCalls"]["decidingMax"],
                repeat["drawCalls"]["decidingMax"],
            ],
        },
        "judgedKey": _repeat_capture_note(run, repeat),
    }
    route = run["route"]
    draw_calls = run["drawCalls"]
    key_repeat = next(item for item in run["interactions"] if item["kind"] == "walk")["autoRepeat"]
    trace_frames = json.loads(
        (run_dir / run_path.name.replace("-run.json", "-trace.json")).read_bytes()
    )["frames"]
    moving = [frame for frame in trace_frames if frame[5] > 0]
    peak_speed = max(frame[5] for frame in trace_frames)
    pose_spacing = walk["walkedDisplacementMm"] // max(1, len(moving))
    lock_held = [item["at"] for item in run["pointerLock"]["samples"] if item["pointerLocked"]]
    sampled = "when the heading was written, after each focus click and at each capture"
    lock_sentence = (
        f"Pointer lock was not held at any sampled moment ({sampled})."
        if not lock_held
        else f"Pointer lock was held {', '.join(lock_held)}, of the moments sampled ({sampled})."
    )
    reconstruction_claim = _reconstruction_claim(run)
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
                *(_binding(path) for path in reversed(EARLIER_RECONCILIATIONS)),
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
                "maxDrawCalls": run["drawCalls"]["decidingMax"],
                "drawCallSources": run["drawCalls"],
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
                "this machine in this run, over the product's own measuring window of "
                f"{draw_calls['productWindowSeconds']} seconds. They are reported and do not decide "
                "any key.",
                reconstruction_claim,
                f"{lock_sentence} The heading was set by writing the controls' yaw once, and every "
                "position came from the product's own movement.",
                _judged_claim(judged_detail),
                "The typed-reply rule of rubric version 5 was adopted after the reply this record "
                "reads was given, and that reply is the rule's first application. The judge had "
                "declined further questions about these pictures, so none was asked again.",
                "What the judge gave about these captures under rubric version 2, and the pick "
                "given under version 3, are not this record's answer. They are calibration "
                "evidence in the version 3 and version 4 reconciliation records, and no key value "
                "here is taken from them; the version 2 reply is not re-read under version 5. "
                "Where a picture's reason includes words the judge wrote under an earlier version, "
                "the ask said they were kept, and each is labelled with when and under which "
                "version it was given.",
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
                "procedure": {
                    "companion": (
                        "The product gives the keyboard to one owner at a time and turns walking "
                        "off while the Companion is open. The Companion was therefore summoned "
                        "with X for each capture, so it is open in all three, and dismissed with "
                        "Escape before each walk."
                    ),
                    "click": (
                        "Without pointer lock the product walks only while the world canvas has "
                        "keyboard focus. Before each walk that needed it, one left click landed "
                        "on the world canvas, the gesture the product's arrival prompt asks for; "
                        "every listener on the canvas is the product's own, and the canvas then "
                        "held keyboard focus, which is how key set version 3 counts a click as "
                        "carried by the product."
                    ),
                    "interactions": [item["kind"] for item in run["interactions"]],
                },
                "measuredUnder": {
                    "keySet": run["keySet"],
                    "commit": measured_at,
                    "scoredUnder": GATE_KEY_SET_VERSION,
                    "note": (
                        "The runs were measured by the code at this commit, whose loom-gate "
                        "package still named key set version 2. Versions 3, 4 and 5 moved no "
                        "measurement, threshold or mechanical decision, as their reconciliation "
                        "records state, so the same numbers decide every key under the version "
                        "this record is scored under."
                    ),
                },
                "scored": {
                    "artifact": {
                        **scored_artifact,
                        "profile": run["scored"]["artifact"]["profile"],
                        "districtId": run["scored"]["artifact"]["districtId"],
                    },
                    "renderer": scored_renderer,
                    "measuredBy": measured_by,
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
                    "answeredAgainst": judged_detail["answeredAgainst"],
                    "answeredFrom": (
                        "each capture above, shown alone at full size under its picture title and "
                        "followed by its one question, in route order, stopping at the first no"
                    ),
                    **asked_as,
                },
                "observations": _observations(run),
                "limitations": [
                    "The heading was written once rather than looked, so the product's mouse-look "
                    "path was not exercised. Walking used the product's keyboard path without "
                    "pointer lock, which needs the focus a click on the world canvas gives.",
                    "The product turns walking off while the Companion is open, so the Companion "
                    "was summoned for each capture and dismissed with Escape before each walk; its "
                    "open encounter is visible in every capture.",
                    "The credentialed workspace is the only retained workspace in the judge seed with "
                    "a scene group, so the Atlas mounts only for it.",
                    "Contact and inside-building tests use a 0.05 m tolerance and even-odd "
                    "containment; hidden geometry counts exactly as visible geometry does.",
                    f"Walking speed is the product's own. The live trace peaks at {peak_speed} mm "
                    f"per second and holds one pose about every {pose_spacing} mm of walking, and "
                    "is resampled to 0.05 m by interpolation.",
                    f"A held W key was delivered as one keydown followed by repeated keydowns after "
                    f"{key_repeat['delayMs']} ms, every {key_repeat['intervalMs']} ms, as a held "
                    "physical key sends them; the product clears its held keys whenever its shell "
                    "refreshes and relies on the repeat.",
                    "The product's validation window closes after "
                    f"{draw_calls['productWindowSeconds']} seconds of frames, before a walk at the "
                    "product's pace ends, so maxDrawCalls is the larger of that window's maximum "
                    f"({draw_calls['productWindowMax']}) and a frame listener's maximum over the "
                    f"whole route ({draw_calls['routeMax']}).",
                    "Transferred bytes for the environment include the response headers the browser "
                    "counted; the body alone is reported beside it.",
                ],
            },
        )
    except GateEvidenceError as error:
        shutil.rmtree(ARTIFACTS, ignore_errors=True)
        raise SystemExit(f"nothing is written: {error}") from error
    companion_path, companion = judge_words_file(
        _relative(BASELINE), judged, judged_detail["answeredAgainst"]["rubricVersion"]
    )
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


# ---- corridor -------------------------------------------------------------------------------


#: A corridor record, written when the judgement holds, and a record of one that does not. The
#: second is NOT a gate record and carries no hardPass block: a refused judgement leaves the ninth
#: key unscored, and eight keys under a nine-key name is a strict subset of the bar wearing its
#: label. It carries the eight it has, each re-decided here, and says the ninth is unscored.
CORRIDOR_PROFILE = "exulanica.visual-gate-corridor/v1"
REFUSED_PROFILE = "exulanica.visual-gate-judgement-refused/v1"

#: The keys ``_judgement`` reads. A file that records the answers and not the asks is missing most
#: of the second list, and ``_judgement`` meets the absence as a KeyError rather than as a refusal
#: somebody can act on. Named here so the refusal names all of them at once.
#: tests/test_visual_gate.py removes each from a complete file and requires a refusal, so neither
#: list can drift away from what the reader actually needs.
JUDGEMENT_KEYS = ("profile", "judge", "judgedOn", "rubricSha256", "askedIn", "options", "pictures")
ASKED_PICTURE_KEYS = ("label", "picture", "prompt", "captureSha256", "asked", "typedBy", "givenAt")

#: Where a judgement file records what its session did that the rubric does not allow. ANY entry
#: refuses the record, and the reason is not that the departure is written down: it is that the
#: departure happened. A session that records nothing is the same judgement with the evidence of
#: its own departure removed, so both are refused and only the honest one can say why.
DEPARTURES_FIELD = "departuresFromProtocol"

#: The rubric lines a refusal rests on, quoted. Every one is checked against the rubric on disk in
#: the same command that writes it, so a clause nobody can find in the rubric stops the write
#: rather than reaching a record. This is the pattern ``_rubric_binding`` uses for the same reason.
REFUSAL_CLAUSES = (
    (
        "every picture is shown by itself",
        "Pictures are never shown together",
    ),
    (
        "the question is asked in the rubric's own words",
        "The same question is asked of each picture, in these plain words, and is not paraphrased",
    ),
    (
        "one follow-up, in the rubric's own words, and only for an answer that gave no reason",
        "a follow-up for an answer that already gave its reason or one not asked in the words above",
    ),
    (
        "a yes carries words given with it",
        "A yes needs words given with it.",
    ),
    (
        "a typed reply that is not an answer ends the judgement where it stands",
        "A typed reply that is not an answer, and a skipped question, stop the judgement unscored.",
    ),
    (
        "nothing is read out of the judge's words beyond the typed-reply rule",
        "Nothing else is inferred from the judge's words, by a model or by anyone else.",
    ),
)


def _flat(text: str) -> str:
    """Text with its line wrapping folded away, the way a quote is compared to a document."""
    return " ".join(text.split())


def _shown_to_the_judge() -> set[str]:
    """Every text this repository itself puts in front of the judge, folded for comparison."""
    return {
        _flat(text)
        for text in (
            RUBRIC_QUESTION,
            RUBRIC_GUIDANCE,
            ANSWER_REQUIREMENT,
            CARRIED_WORDS_NOTICE,
            NOT_ASKED,
            *ANSWER_OPTIONS,
            *PICTURE_TITLES.values(),
            *(judge_prompt(label) for label in CAPTURE_LABELS),
            *(reason_follow_up(answer) for answer in ("yes", "no")),
        )
    }


def _strings(value: Any) -> list[str]:
    """Every string a structure holds, at any depth."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _strings(item)]
    if isinstance(value, list):
        return [text for item in value for text in _strings(item)]
    return []


def _judgement_words(path: Path, rubric: bytes, carried: Sequence[str] = ()) -> list[str]:
    """Every string in a judgement file a public record may not carry.

    INVERTED ON PURPOSE. It collects by default and excludes only what this repository itself
    wrote: a text the judge was shown, a line the rubric carries, a departure the session recorded
    for this record to quote, and the strings the record is about to carry from ``asked_as``,
    which the reader built and the caller passes in as ``carried`` rather than naming here by
    field. A collector that instead named the fields holding the judge's words missed one on
    2026-09-19, because that file spelled the field a fifth way, and an enumerated exclusion list
    fails silently and in the unsafe direction. Over-collecting costs a refusal somebody can read;
    under-collecting publishes a person's words.
    """
    document = json.loads(path.read_bytes())
    allowed = (
        _shown_to_the_judge()
        | {_flat(item) for item in _departures(document)}
        | {_flat(item) for item in carried}
    )
    rubric_text = _flat(rubric.decode("utf-8"))
    collected: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            folded = _flat(value)
            if len(folded.split()) < 3 or folded in allowed or folded in rubric_text:
                return
            collected.append(value)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(document)
    return collected


def _rubric_clauses(rubric: bytes) -> list[dict[str, str]]:
    """Every clause a refusal may rest on, each read back out of the rubric before it is used."""
    text = _flat(rubric.decode("utf-8"))
    clauses = []
    for requires, quote in REFUSAL_CLAUSES:
        if _flat(quote) not in text:
            raise SystemExit(
                f"{RUBRIC_PATH} does not carry {quote!r}. A refusal quotes the rubric it rests "
                "on; nothing is written."
            )
        clauses.append({"requires": requires, "rubricSays": quote})
    return clauses


def _corridor_paths(record: str) -> tuple[Path, Path]:
    """A corridor record's path and its artifact directory, refused outside docs/evaluation."""
    path = (ROOT / record).resolve() if not Path(record).is_absolute() else Path(record).resolve()
    try:
        relative = path.relative_to(ROOT).as_posix()
    except ValueError:
        raise SystemExit(f"{record} is not under the document root") from None
    if not relative.startswith("docs/evaluation/") or not relative.endswith(".json"):
        raise SystemExit(f"{relative} is not a JSON record under docs/evaluation/")
    if "/" in relative[len("docs/evaluation/") :]:
        raise SystemExit(f"{relative} is not directly under docs/evaluation/")
    return path, ROOT / "docs/evaluation/artifacts" / path.stem


def _judgement_shape(given: Any) -> list[str]:
    """Every key the reader needs that this file does not carry, named rather than counted."""
    if not isinstance(given, dict):
        return [f"the file holds a {type(given).__name__}, not a judgement"]
    missing = [name for name in JUDGEMENT_KEYS if name not in given]
    said = [f"the judgement carries no {name}" for name in missing]
    pictures = given.get("pictures")
    if not isinstance(pictures, list):
        if "pictures" in given:
            said.append("the judgement's pictures are not a list of pictures")
        return said
    for index, entry in enumerate(pictures):
        where = f"pictures[{index}]"
        if not isinstance(entry, dict):
            said.append(f"{where} is not a picture")
            continue
        label = entry.get("label", where)
        if entry.get("asked") is False:
            continue
        said += [f"{label} carries no {name}" for name in ASKED_PICTURE_KEYS if name not in entry]
    return said


def _departures(given: Any) -> list[str]:
    """Every departure from the rubric the file records, exactly as it records them."""
    if not isinstance(given, dict):
        return []
    recorded = given.get(DEPARTURES_FIELD, [])
    if isinstance(recorded, str):
        return [recorded]
    if not isinstance(recorded, list):
        raise SystemExit(f"{DEPARTURES_FIELD} is a list of what the session did, or is absent")
    return [str(item) for item in recorded]


def _corridor_judgement(
    path: Path, rubric: bytes, captures: dict[str, str], rubric_sha256: str
) -> tuple[JudgedAnswers | None, dict[str, Any], list[str], list[str]]:
    """The judge's answers, and every reason this file cannot become a record, named together.

    Two kinds, kept apart because they are known in different ways. The REFUSALS are structural
    and this file checks them: a key the reader needs and the file does not carry, a profile that
    is not an answers file, and whatever the record builder says when it is handed what is there.
    The DEPARTURES are prose the asking session wrote about itself, which nothing here can read;
    each one stops the record until a person resolves it, and this file does not judge which of
    them are still live.

    Collected rather than raised one at a time. A refusal that stops at the first reason sends the
    asking session back for a second refusal, and a judgement is asked of a person, so every round
    trip costs somebody a conversation.
    """
    given = json.loads(path.read_bytes())
    departures = _departures(given)
    refusals = _judgement_shape(given)
    if isinstance(given, dict) and given.get("profile") != JUDGEMENT_PROFILE:
        refusals.append(
            f"the file states profile {given.get('profile')!r} and the reader needs "
            f"{JUDGEMENT_PROFILE!r}, which records what each picture was shown, who typed each "
            "reply and when, and not only what was answered"
        )
    if refusals:
        return None, {}, refusals, departures
    try:
        answers, asked_as = _judgement(path, rubric)
    except SystemExit as error:
        return None, {}, [str(error)], departures
    try:
        decide_judged(answers, rubric_sha256=rubric_sha256, captures=captures)
    except GateEvidenceError as error:
        return None, {}, [str(error)], departures
    if departures:
        return None, asked_as, [], departures
    return answers, asked_as, [], []


def _supplement(
    path: str, run: dict[str, Any], captures: list[dict[str, Any]], run_file: dict[str, Any]
) -> dict[str, Any]:
    """The record that states the store this run read, checked against the run before it is bound.

    It binds the captures and the run record by digest and this verb binds them from the files, so
    every digest here is read twice by two paths that never met, and a disagreement stops the
    write. That is the whole reason to ask for it rather than to quote its condition.
    """
    document = json.loads((ROOT / path).read_bytes())
    stated = document.get("record_sha256")
    recomputed = hashlib.sha256(canonical_json(document["record"])).hexdigest()
    if stated != recomputed:
        raise SystemExit(f"{path} states record_sha256 {stated} and its record hashes {recomputed}")
    record = document["record"]
    binds = record["binds"]
    by_name = {item["name"]: item for item in binds["captures"]}
    for capture, source in zip(captures, run["captures"], strict=True):
        bound = by_name.get(source["file"])
        if bound is None:
            raise SystemExit(f"{path} binds no capture named {source['file']}")
        if (bound["sha256"], bound["bytes"]) != (capture["sha256"], capture["byte_size"]):
            raise SystemExit(
                f"{path} binds {source['file']} as {bound['bytes']} bytes sha256 "
                f"{bound['sha256']}, and the file copied here is {capture['byte_size']} bytes "
                f"sha256 {capture['sha256']}"
            )
    bound_run = binds["run_record"]
    if (bound_run["sha256"], bound_run["bytes"]) != (run_file["sha256"], run_file["byte_size"]):
        raise SystemExit(
            f"{path} binds a run record of {bound_run['bytes']} bytes sha256 "
            f"{bound_run['sha256']}, and the run read here is {run_file['byte_size']} bytes "
            f"sha256 {run_file['sha256']}"
        )
    if binds["keys"] != run["keys"]:
        raise SystemExit(f"{path} binds a different key set than the run record states")
    if binds["stated_walk"]["sha256"] != run["statedWalk"]["sha256"]:
        raise SystemExit(f"{path} binds a different walk than the run record states")
    return {
        "path": path,
        "record_sha256": recomputed,
        "condition": record["condition"],
        "store": record["store"],
        "whyThisRecordExists": record["why_this_record_exists"],
    }


def _corridor_scored(run: dict[str, Any], measured_at: str) -> dict[str, Any]:
    """What the run scored: the containers it read, and the committed code that drew and measured.

    The containers are not files of this repository and are bound by the digests the run matched
    on the wire. The renderer is committed and is held to HEAD; the measuring code is held to the
    commit the run was measured at, and says whether it still stands at HEAD.
    """
    scored = run["scored"]
    return {
        "tile": scored["tile"],
        "containers": scored["containers"],
        "unavailableSurfacesByReason": scored["unavailableSurfacesByReason"],
        "renderer": _unmodified(
            scored["renderer"]["path"], scored["renderer"]["sha256"], measured_at
        ),
        "measuredBy": [
            _measured_file(item["path"], item["sha256"], measured_at)
            for item in scored["measuredBy"]
        ],
        "statedWalk": _bind(
            ROOT / run["statedWalk"]["path"],
            **{name: run["statedWalk"][name] for name in ("xMm", "yMm", "facingDx", "facingDy")},
        ),
        "containersAreNotFilesOfThisRepository": (
            "Each container was matched byte for byte on the wire and is bound by its sha256 and "
            "its tile_inputs_digest. None is committed, and the store that served them is the one "
            "the supplementary record names."
        ),
    }


def _corridor_mechanical(run: dict[str, Any]) -> dict[str, Any]:
    """The eight measured keys, each decided again here from the fields its definition names."""
    decided = {}
    for spelling in CANONICAL_SPELLINGS:
        if spelling == JUDGED_KEY:
            continue
        item = key(spelling)
        measured = run["mechanical"][spelling]
        decided[spelling] = {
            "measurement": item.measurement,
            "decidedBy": {field: measured[field] for field in item.decided_by},
            "harnessDecided": run["keys"][spelling],
            "value": decide_mechanical(spelling, measured),
        }
    return decided


def _re_ask() -> dict[str, Any]:
    """What a fresh judgement of these three pictures has to be, read out of the writer itself.

    Every entry below is the rubric quoted, a refusal this repository's own code makes, or a step
    that follows from one of those and says so. Where the rubric is silent it says that too,
    rather than filling the silence.
    """
    return {
        "theAsk": {label: judge_prompt(label) for label in CAPTURE_LABELS},
        "theFollowUp": {answer: reason_follow_up(answer) for answer in ("yes", "no")},
        "theOrder": (
            f"{', '.join(CAPTURE_LABELS)}, one at a time, each shown alone at full size under "
            "its picture title, its question asked before the next picture is shown. The first "
            "no makes the key false and the pictures after it are not asked."
        ),
        "theJudge": (
            "The one person the rubric names, spelled as the rubric spells them. _judgement "
            "refuses a judgement whose judge is not the name the rubric carries, and _require_name "
            "refuses a role or a placeholder in that field."
        ),
        "theDate": (
            "judgedOn is the date the judge answered, and _given_at refuses any reply whose "
            "givenAt falls on another date. A judgement that runs across midnight in UTC is two "
            "dates and the writer will refuse the second."
        ),
        "aNewSession": (
            "FOLLOWS FROM THE RUBRIC RATHER THAN QUOTED FROM IT. The rubric says pictures are "
            "never shown together. In a session where they have already been shown together that "
            "cannot be made true again, so a fresh judgement is a fresh session. The rubric does "
            "not say this, and it does not say the judge may not have seen the pictures before: "
            "it constrains the ask, not the judge's memory, and it already contemplates asking a "
            "judge again about a picture they have written about."
        ),
        "whatMayBeSaidToTheJudge": (
            "WHERE THE RUBRIC IS SILENT, AND SAYING SO RATHER THAN FILLING IT. Inside the "
            "judgement the rubric allows the picture, its title, the question, the guidance, the "
            "requirement line, the two options and, when an answer arrives with no words, the one "
            "follow-up. Nothing else, and no explanation of what a word means. It says nothing "
            "about what a person may be told BEFORE a judgement begins. Telling the judge why "
            "they are being asked again belongs there, before the first picture, and is not part "
            "of any ask."
        ),
        "nothingAboveTheQuestion": (
            "No line is shown above any question. The one line the rubric provides above a "
            "question is the carried-words line, and it belongs only to words written under an "
            "EARLIER rubric version; decide_judged refuses a notice with no carried words, and "
            "refuses replies given under version 5 as carried words, so neither is available and "
            "the ask is the question alone."
        ),
        "theEarlierRepliesAreNotCarriedWords": (
            "They were given under rubric version 5, which is the current version. _carried "
            "requires a superseded version and its digest, so the writer refuses them as carried "
            "words. A fresh yes therefore needs words given with it, and no yes in the new "
            "judgement can rest on anything the judge wrote before it."
        ),
        "everyReplyRecords": (
            "who typed it, which must be the judge exactly as the rubric names them; when it "
            "reached the asking session, as an ISO time in UTC on the stated date; what the "
            "picture was shown as; and the exact text of the ask."
        ),
        "whenATypedReplyArrives": (
            "If a reply arrives with no pick and the typed-reply rule does not read it as a no, "
            "the judgement stops there, unscored. It is not re-asked. The stop is recorded and "
            "nothing is scored from that session."
        ),
        "thePicturesAreTheseThree": (
            "A fresh judgement of THIS run is about the three captures this record binds by "
            "sha256 and byte size, which are committed under this record's artifacts directory. "
            "A judgement about any other picture is refused by decide_judged."
        ),
    }


def _names_the_captures(path: Path, captures: list[dict[str, Any]]) -> dict[str, Any]:
    """Whether the judgement file names every capture this record binds, read without a schema.

    Every 64-character hex string in the file, against the three digests computed from the copied
    pictures. It asks one thing only: was the refused judgement about THESE pictures. A shape this
    reader cannot parse still answers it, which is the point, since the file that prompted this
    was one the reader could not parse.
    """
    found = set(re.findall(r"\b[0-9a-f]{64}\b", path.read_text(encoding="utf-8")))
    named = {capture["label"]: capture["sha256"] in found for capture in captures}
    return {
        "everyBoundCaptureIsNamedInTheJudgement": all(named.values()),
        "byPicture": named,
        "howItIsChecked": (
            "every 64-character hex string in the judgement file, against the SHA-256 of each "
            "picture as it was copied here; no field name is assumed"
        ),
    }


def _refused_record(
    *,
    date: str,
    run: dict[str, Any],
    refusals: list[str],
    departures: list[str],
    clauses: list[dict[str, str]],
    captures: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
    judgement_file: dict[str, Any],
    names_the_captures: dict[str, Any],
    asked_as: dict[str, Any],
    scored: dict[str, Any],
    supplement: dict[str, Any],
    blocker: dict[str, Any],
    rubric_sha256: str,
    record_path: str,
) -> dict[str, Any]:
    """A record of a judgement the rubric does not allow, and of the run it was asked about."""
    mechanical = _corridor_mechanical(run)
    failed = sorted(spelling for spelling, item in mechanical.items() if not item["value"])
    held = sorted(spelling for spelling, item in mechanical.items() if item["value"])
    return digest_bound(
        {
            "profile": REFUSED_PROFILE,
            "date": date,
            "status": "judgement_refused",
            "base": _git("rev-parse", "HEAD"),
            "branch": _git("branch", "--show-current"),
            "recordPath": record_path,
            "target": run["target"],
            "authenticationCondition": run["authentication"]["condition"],
            "theGateDoesNotPass": (
                "THIS RECORD SCORES NOTHING. The ninth key is unscored because the judgement was "
                f"refused, and {len(failed)} of the {len(mechanical)} measured keys are false "
                f"({', '.join(failed)}), so there is no verdict here and no hardPass block for "
                "one to be read out of."
            ),
            "judgedKey": {
                "key": JUDGED_KEY,
                "state": "refused",
                "value": None,
                "rubric": RUBRIC_PATH,
                "rubricVersion": RUBRIC_VERSION,
                "rubricSha256": rubric_sha256,
                "refusedBecause": refusals,
                # Known only when the file was readable, which a file that records answers and
                # not asks is not. A record about how the asking went says how the asking went,
                # where the asking was written down at all.
                **({} if not asked_as else {"whatTheJudgeWasShown": asked_as}),
                "departuresTheSessionRecorded": departures,
                "whatADepartureDoes": (
                    "Each line above stops this record. They are the asking session's own prose "
                    "about what it did, and nothing here reads prose, so the writer does not "
                    "judge which of them are still live: a person resolves each one. A session "
                    "that recorded none would be the same judgement with the evidence of its own "
                    "departure removed, and would be refused just the same, with nothing to say "
                    "why."
                ),
                "theRubricSays": clauses,
                "judgeWordsAreNotHere": (
                    "The judge's words are not in this record and are not in this repository. "
                    "The file that holds them is bound above by path, byte size and SHA-256, and "
                    "git ignores the directory it lives in."
                ),
                "reAsk": _re_ask(),
                "andWhatAReAskIsReadAgainst": blocker,
            },
            "measuredKeys": mechanical,
            "measuredKeysHeld": held,
            "measuredKeysFailed": failed,
            "recordBuilderAgreedWithHarnessOnEveryMeasuredKey": all(
                item["value"] is item["harnessDecided"] for item in mechanical.values()
            ),
            "judgementFile": judgement_file,
            "theRefusedJudgementWasAboutThesePictures": names_the_captures,
            "route": _no_floats(run["route"]),
            "calibration": {
                "records": _corridor_predecessors(),
                "note": (
                    "The three retained rejections are local-only evidence this checkout does "
                    "not hold. The chain reaches them through the Flatiron baseline, which bound "
                    "them where they are."
                ),
            },
            "captures": captures,
            "artifacts": artifacts,
            "scored": _no_floats(scored),
            "privateStore": supplement,
            "claimsNotMade": [
                "No key value is claimed for readsAsInhabitedStreet. The judgement this record "
                "describes was refused, so the key has never been scored for this run, and "
                "nothing here says how it would be answered.",
                "No answer is reported. The file bound above holds what was given; this record "
                "does not repeat it, because an answer obtained outside the rubric is not an "
                "answer and reporting one would invite it to be read as the key.",
                # Counted rather than written out. The record retained on 2026-09-19 says
                # "The eight measured keys ... Two are false", which was true and was typed; the
                # record is not edited for it, and no record written after this one types either.
                f"The {len(mechanical)} measured keys above are this run's and nothing else's. "
                f"{len(failed)} of them are false, so the block cannot pass whatever the ninth "
                "key turns out to be.",
                supplement["condition"],
                "Nothing is claimed about any street beyond the walk this run made, which is the "
                "walk the stated-walk document names and this record binds by digest.",
            ],
        }
    )


def _rubric_equivalence(baseline: dict[str, Any], rubric_sha256: str) -> dict[str, Any]:
    """Whether a fresh judgement can be read against the baseline at all, asked of the gate.

    Not predicted here. The two digests are read, one from the baseline record and one from the
    rubric on disk, and then ``_comparable`` itself is asked whether it would allow the
    comparison, so this reports what the gate does rather than what this file believes about it.
    """
    answered = baseline["gate"]["keys"][JUDGED_KEY]["answeredAgainst"]
    fresh = {
        "target": GENERATED_TILE_TARGET,
        "gate": {
            "keySet": baseline["gate"]["keySet"],
            "keys": {
                JUDGED_KEY: {
                    "rubricSha256": rubric_sha256,
                    "answeredAgainst": {"rubricSha256": rubric_sha256},
                }
            },
        },
    }
    try:
        _comparable(fresh, baseline)
    except GateEvidenceError as error:
        refused: str | None = str(error)
    else:
        refused = None
    return {
        "baselineAnsweredAgainst": answered["rubricSha256"],
        "baselineRubricVersion": answered["rubricVersion"],
        "aFreshJudgementAnswersAgainst": rubric_sha256,
        "freshRubricVersion": RUBRIC_VERSION,
        "theGateReconcilesThem": refused is None,
        **({} if refused is None else {"andRefusesTheComparison": refused}),
        "whatThisCost": (
            "UNTIL 2026-09-19 THE GATE DID NOT RECONCILE THEM, AND NO CORRIDOR COULD EVER HAVE "
            "BEEN READ AGAINST THIS BASELINE. _comparable required the two records to name one "
            "answeredAgainst.rubricSha256; the baseline's judge answered under rubric version "
            f"{answered['rubricVersion']} and every judgement from now on is given under version "
            f"{RUBRIC_VERSION}; and _answered_version in the same file reads a version "
            f"{answered['rubricVersion']} answer under version {RUBRIC_VERSION} precisely because "
            f"{RUBRIC_PATH} says version {RUBRIC_VERSION} shows the judge exactly what the "
            "version before it showed. One file reconciled two versions in one function and "
            "refused them in another, over a difference the rubric declares immaterial. A "
            "perfectly conducted re-ask would have produced nothing and the judge's attention "
            "would have been spent finding that out."
        ),
        "howItWasFixed": (
            "_comparable now asks _answered_version's own question of each record: both must be "
            "WRITTEN with one rubric, and each must have been answered against a digest that "
            "rubric reconciles. Nothing wider: a digest that function does not reconcile still "
            "refuses the comparison, and a test holds both halves."
        ),
    }


def _corridor_predecessors() -> list[dict[str, str]]:
    """The records a corridor is calibrated against, each bound by a digest recomputed here.

    The three retained rejections are NOT among them, and their absence is the point: they are
    local-only evidence that this checkout does not hold, so a record that bound them by reading
    them could not be written here at all, and one that bound them from the digests
    ``gate_keys`` carries would be quoting a constant rather than reading a file. The chain
    reaches them through the Flatiron baseline, which bound them in a checkout that had them.
    """
    return [
        _binding(_relative(RECONCILIATION)),
        _binding(_relative(BASELINE)),
        *(_binding(path) for path in reversed(EARLIER_RECONCILIATIONS)),
    ]


def _corridor_because(run: dict[str, Any], judged_detail: dict[str, Any]) -> dict[str, str]:
    """One measured sentence per key, read from the fields that key's definition names."""
    measured = run["measured"]
    integrity = measured["integrity"]
    walk = measured["walk"]
    capsule = measured["capsule"]
    budget = run["mechanical"]["practicalBrowserBudget"]
    companion = run["mechanical"]["companionPresent"]
    reticle = run["mechanical"]["reticlePresent"]
    shell = run["mechanical"]["authenticatedShellAndAuthoredHandlersPreserved"]
    textured = run["mechanical"]["continuousTexturedStreetAndFacades"]
    return {
        "continuousTexturedStreetAndFacades": (
            f"{textured['streetAndFacadeTriangles']:,} walking-surface and facade triangles were "
            f"drawn and {textured['untexturedStreetAndFacadeTriangles']:,} of them are untextured"
        ),
        JUDGED_KEY: _because_judged(judged_detail),
        "noCutsOrFloatingGeometry": (
            f"{integrity['componentsDetachedFromSupport']:,} drawn components have no chain of "
            f"contact to the walking surface, {integrity['ringEdgesWithoutDrawnFacade']:,} ring "
            f"edges have no drawn facade and {integrity['trianglesInsideBuildings']:,} drawn "
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
            f"{budget['environmentTransferredBytes']:,} environment bytes, "
            f"{budget['drawnTriangles']:,} drawn triangles, "
            f"{budget['environmentDecodedTextureBytes']:,} decoded environment texture bytes and "
            f"{budget['maxDrawCalls']} draw calls against Melbourne's "
            f"{MELBOURNE_ENVELOPE['maxDrawCalls']}, with {budget['gpuErrors']} GPU errors and "
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
            f"product shell with a mounted world, {shell['foreignListeners']} listeners came from "
            f"anywhere but the product's own modules, "
            f"{shell['interactionsNotCarriedByProduct']} interactions were not carried by the "
            f"product's own handlers and {shell['substitutedPages']} pages were substituted"
        ),
    }


def corridor(arguments: argparse.Namespace) -> int:
    """Score a corridor run against the judge's answers, or record why it could not be scored."""
    record_path, artifacts_dir = _corridor_paths(arguments.record)
    relative_record = _relative(record_path)
    if record_path.exists() and not arguments.replace:
        raise SystemExit(f"{relative_record} exists. A retained record is not rewritten.")
    run_path = Path(arguments.run).resolve()
    run = _load_run(run_path)
    if run.get("target") != GENERATED_TILE_TARGET:
        raise SystemExit(f"{run_path.name} scored {run.get('target')!r}, not a generated tile")
    rubric, rubric_sha = _rubric()
    clauses = _rubric_clauses(rubric)
    measured_at = _git("rev-parse", "--verify", f"{arguments.measured_at}^{{commit}}")
    scored = _corridor_scored(run, measured_at)

    if artifacts_dir.exists():
        if not arguments.replace:
            raise SystemExit(
                f"{_relative(artifacts_dir)} exists; retained artifacts are not rewritten"
            )
        shutil.rmtree(artifacts_dir)
    artifacts_dir.mkdir(parents=True)
    run_dir = run_path.parent
    captures = []
    for index, capture in enumerate(run["captures"], start=1):
        target = _copy(
            run_dir / capture["file"],
            artifacts_dir / f"capture-{index:02d}-route-{capture['label']}.png",
        )
        bound = _bind(target, label=capture["label"], pose=_pose(capture["pose"]))
        if bound["sha256"] != capture["sha256"]:
            raise SystemExit(f"{capture['file']} changed after the run")
        captures.append(bound)
    for name, document in (
        ("browser-metrics.json", _browser_metrics(run)),
        ("gate-measurements.json", _gate_measurements(run)),
    ):
        text = json.dumps(_no_floats(document), indent=2, ensure_ascii=False) + "\n"
        _refuse_forbidden(text, name)
        (artifacts_dir / name).write_text(text, encoding="utf-8")
    _copy(
        run_dir / run_path.name.replace("-run.json", "-trace.json"),
        artifacts_dir / "route-trace.json",
    )
    # The supplementary record binds the harness run record by digest, so a copy of it has to
    # outlive the directory it was written in or that binding resolves to nothing.
    run_file = _bind(_copy(run_path, artifacts_dir / "run.json"), originalName=run_path.name)
    artifacts = (
        [_bind(RUBRIC_COPY)]
        + [
            _bind(artifacts_dir / name)
            for name in ("browser-metrics.json", "gate-measurements.json", "route-trace.json")
        ]
        + [run_file]
        + captures
    )

    supplement = _supplement(arguments.supplementary, run, captures, run_file)
    judgement_path = Path(arguments.judgement).resolve()
    judgement_bytes = judgement_path.read_bytes()
    judgement_file = {
        "path": judge_words_path(relative_record).rsplit("/", 1)[0]
        + f"/inputs/{judgement_path.name}",
        "byte_size": len(judgement_bytes),
        "sha256": hashlib.sha256(judgement_bytes).hexdigest(),
        "tracked": False,
        "holds": (
            "the judge's answers exactly as given, words included. It is not committed and this "
            "record carries its path, byte size and SHA-256 in its place."
        ),
    }
    judged, asked_as, refusals, departures = _corridor_judgement(
        judgement_path,
        rubric,
        {capture["label"]: capture["sha256"] for capture in captures},
        rubric_sha,
    )
    private = _judgement_words(judgement_path, rubric, _strings(asked_as))

    if judged is None:
        document = _refused_record(
            date=arguments.date,
            run=run,
            refusals=refusals,
            departures=departures,
            clauses=clauses,
            captures=captures,
            artifacts=artifacts,
            judgement_file=judgement_file,
            names_the_captures=_names_the_captures(judgement_path, captures),
            asked_as=asked_as,
            scored=scored,
            supplement=supplement,
            blocker=_rubric_equivalence(json.loads(BASELINE.read_bytes())["record"], rubric_sha),
            rubric_sha256=rubric_sha,
            record_path=relative_record,
        )
        _write(
            record_path,
            document,
            replace=arguments.replace,
            private=private,
            shown=sorted(_shown_to_the_judge()),
        )
        written = record_path.read_bytes()
        print(
            f"{relative_record} {len(written)} bytes, sha256 "
            f"{hashlib.sha256(written).hexdigest()}, record_sha256 {document['record_sha256']}, "
            f"judged key REFUSED on {len(refusals)} counts and "
            f"{len(departures)} recorded departures"
        )
        for refusal in refusals:
            print(f"  refused: {refusal}")
        for departure in departures:
            print(f"  departure: {departure}")
        return 1

    judged_value, judged_detail = decide_judged(
        judged,
        rubric_sha256=rubric_sha,
        captures={capture["label"]: capture["sha256"] for capture in captures},
    )
    evidence: dict[str, Any] = {
        spelling: run["mechanical"][spelling]
        for spelling in CANONICAL_SPELLINGS
        if spelling != JUDGED_KEY
    }
    evidence[JUDGED_KEY] = judged
    because = _corridor_because(run, judged_detail)
    held = {
        spelling: judged_value if spelling == JUDGED_KEY else run["keys"][spelling]
        for spelling in CANONICAL_SPELLINGS
    }
    failed = [spelling for spelling in CANONICAL_SPELLINGS if not held[spelling]]
    passed = [spelling for spelling in CANONICAL_SPELLINGS if held[spelling]]
    body = "; ".join(f"{spelling}, because {because[spelling]}" for spelling in failed or passed)
    reason = (
        f"The corridor at tile {run['scored']['tile']['tileName']}, composed from "
        f"{len(run['scored']['containers'])} containers and walked inside the product's own "
        "preview shell, "
        + (
            f"fails the reconciled block. It fails {body}."
            if failed
            else f"holds all nine keys: {body}."
        )
    )
    report = run["validationReport"]
    measurement = report["measurement"]
    baseline_document = json.loads(BASELINE.read_bytes())
    try:
        document = visual_gate_record(
            profile=CORRIDOR_PROFILE,
            record_path=relative_record,
            date=arguments.date,
            status="corridor_measured",
            base=_git("rev-parse", "HEAD"),
            branch=_git("branch", "--show-current"),
            target=GENERATED_TILE_TARGET,
            predecessor_records=_corridor_predecessors(),
            artifacts=artifacts,
            captures=captures,
            rubric_sha256=rubric_sha,
            browser={
                "engine": run["browser"]["engine"],
                "viewport": run["browser"]["viewport"],
                "gpu": report["runtime"]["gpu"],
                "peakJsHeapMb": _decimal(report["runtime"]["peak_js_heap_mb"]),
                "frames": measurement["frames"],
                "frameP95Ms": _decimal(measurement["frameP95Ms"]),
                "fpsP1Low": _decimal(measurement["fpsP1Low"]),
                "maxDrawCalls": run["drawCalls"]["decidingMax"],
                "drawCallSources": run["drawCalls"],
                "gpuError": report["renderer"]["gpu_error"],
                "pageErrors": run["errors"]["exceptions"],
                "consoleErrors": run["errors"]["consoleErrors"],
                "eyeHeightMetres": "1.62",
                "measuredBy": "the product's own validation=1 recorder, read after its window closed",
            },
            evidence=evidence,
            authentication_condition=run["authentication"]["condition"],
            baseline=baseline_document["record"],
            baseline_path=_relative(BASELINE),
            reason=reason,
            checks={
                "harnessRuns": 1,
                "recordBuilderAgreedWithHarnessOnEveryMechanicalKey": True,
                "scoredRendererIdenticalToHead": True,
                "privateStoreRecord": supplement["path"],
            },
            claims_not_made=[
                supplement["condition"],
                "The three retained rejections are not bound directly. They are local-only "
                "evidence this checkout does not hold, and the Flatiron baseline above binds "
                "them.",
                "The containers this run read are not committed. They are bound by the sha256 "
                "each was matched by on the wire, and by the supplementary record above.",
                "Frame time, low-percentile frame rate and heap are measurements of this machine "
                "in this run. They are reported and decide no key.",
                _judged_claim(judged_detail),
                "Nothing is claimed about any street beyond the walk this run made.",
            ],
            extra={
                "scored": _no_floats(scored),
                "route": _no_floats(run["route"]),
                "movement": _no_floats(
                    {"walk": run["measured"]["walk"], "harnessWrites": run["harnessWrites"]}
                ),
                "integrity": _no_floats(run["measured"]["integrity"]),
                "capsule": _no_floats(run["measured"]["capsule"]),
                "privateStore": supplement,
                "judgement": {
                    "judge": judged.judge,
                    "judgedOn": judged.judged_on,
                    "rubric": RUBRIC_PATH,
                    "rubricVersion": RUBRIC_VERSION,
                    "rubricCopy": _relative(RUBRIC_COPY),
                    "answeredAgainst": judged_detail["answeredAgainst"],
                    "answeredFrom": (
                        "each capture above, shown alone at full size under its picture title and "
                        "followed by its one question, in route order, stopping at the first no"
                    ),
                    "judgementFile": judgement_file,
                    **asked_as,
                },
                "measuredUnder": {"keySet": run["keySet"], "commit": measured_at},
            },
        )
    except GateEvidenceError as error:
        shutil.rmtree(artifacts_dir, ignore_errors=True)
        raise SystemExit(f"nothing is written: {error}") from error
    companion_path, companion = judge_words_file(
        relative_record, judged, judged_detail["answeredAgainst"]["rubricVersion"]
    )
    if document["record"]["judgeWords"]["sha256"] != hashlib.sha256(companion).hexdigest():
        raise SystemExit("the private companion is not the one the record binds")
    _write_private(companion_path, companion, replace=arguments.replace)
    _write(
        record_path,
        document,
        replace=arguments.replace,
        private=private,
        shown=sorted(_shown_to_the_judge()),
    )
    written = record_path.read_bytes()
    print(
        f"{relative_record} {len(written)} bytes, "
        f"sha256 {hashlib.sha256(written).hexdigest()}, "
        f"record_sha256 {document['record_sha256']}, verdict {document['record']['verdict']}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    verbs = parser.add_subparsers(dest="verb", required=True)
    reconcile = verbs.add_parser("reconciliation", help="write the key reconciliation record")
    reconcile.add_argument("--date", required=True, help="ISO date the record is produced")
    reconcile.add_argument(
        "--calibration", required=True, help="the reply typed under rubric version 4"
    )
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
    base.add_argument(
        "--measured-at",
        required=True,
        help="the commit the runs were measured at; the measuring code must match it",
    )
    base.add_argument("--replace", action="store_true")
    base.set_defaults(handler=baseline)
    corr = verbs.add_parser("corridor", help="score a corridor run, or record why it was not")
    corr.add_argument("--date", required=True)
    corr.add_argument("--run", required=True, help="the run's <label>-run.json")
    corr.add_argument("--judgement", required=True, help="the named judge's answers")
    corr.add_argument(
        "--supplementary",
        required=True,
        help="the record that states the store this run read, relative to the document root",
    )
    corr.add_argument(
        "--record", required=True, help="where the record is written, under docs/evaluation/"
    )
    corr.add_argument(
        "--measured-at",
        required=True,
        help="the commit the run was measured at; the measuring code must match it",
    )
    corr.add_argument("--replace", action="store_true")
    corr.set_defaults(handler=corridor)
    arguments = parser.parse_args(argv)
    return arguments.handler(arguments)


if __name__ == "__main__":
    sys.exit(main())
