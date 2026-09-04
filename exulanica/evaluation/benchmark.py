"""Licensed benchmark acquisition outside production ingest.

The committed manifest fixes one official archive, its license document, and every file that may
enter evaluation. This module downloads and verifies those bytes, but knows nothing about the API,
database, or reconstruction workers. Production still receives ordinary files through intake.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Final

from exulanica.canonical import canonical_json

__all__ = [
    "BENCHMARK_MANIFEST_PATH",
    "BenchmarkAcquisitionError",
    "BenchmarkFixture",
    "acquire_benchmark",
    "load_benchmark_manifest",
    "verify_benchmark_tree",
]

BENCHMARK_MANIFEST_PATH: Final = Path(__file__).with_name("benchmarks") / "eth3d-pipes-v1.json"
_DIGEST_BOUND_PROFILE: Final = "exulanica.digest-bound-record/v1"


class BenchmarkAcquisitionError(ValueError):
    """The benchmark source, license, archive, or materialized files failed verification."""


@dataclass(frozen=True, slots=True)
class BenchmarkFixture:
    root: Path
    image_directory: Path
    calibration_directory: Path
    source_manifest_path: Path
    source_manifest_digest: str
    acquisition_receipt_path: Path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _check_digest(path: Path, expected: str, *, label: str) -> None:
    actual = _sha256_file(path)
    if actual != expected:
        raise BenchmarkAcquisitionError(
            f"{label} SHA-256 mismatch: expected {expected}, observed {actual}"
        )


def load_benchmark_manifest(path: Path = BENCHMARK_MANIFEST_PATH) -> tuple[dict[str, Any], str]:
    """Load one canonical digest-bound manifest and return its record plus digest."""
    try:
        envelope = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as error:
        raise BenchmarkAcquisitionError(
            f"cannot read benchmark manifest {path}: {error}"
        ) from error
    if not isinstance(envelope, dict) or envelope.get("profile") != _DIGEST_BOUND_PROFILE:
        raise BenchmarkAcquisitionError("benchmark manifest is not a digest-bound record")
    record = envelope.get("record")
    expected = envelope.get("record_sha256")
    if not isinstance(record, dict) or not isinstance(expected, str):
        raise BenchmarkAcquisitionError("benchmark manifest record and digest are required")
    actual = hashlib.sha256(canonical_json(record)).hexdigest()
    if actual != expected:
        raise BenchmarkAcquisitionError("benchmark manifest record digest does not verify")
    if record.get("corpus_class") != "benchmark":
        raise BenchmarkAcquisitionError("benchmark manifest corpus_class must be benchmark")
    return record, actual


def _download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "Exulanica-Evaluation/1"})
    partial = destination.with_suffix(destination.suffix + ".partial")
    try:
        with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as stream:
            shutil.copyfileobj(response, stream, length=1024 * 1024)
        os.replace(partial, destination)
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def _safe_archive_members(listing: str, expected_files: set[str]) -> None:
    observed_files: set[str] = set()
    for line in listing.splitlines():
        member = line.strip()
        if not member:
            continue
        pure = PurePosixPath(member.rstrip("/"))
        if pure.is_absolute() or ".." in pure.parts or not pure.parts:
            raise BenchmarkAcquisitionError(f"unsafe benchmark archive member: {member!r}")
        if not member.endswith("/"):
            observed_files.add(member)
    if observed_files != expected_files:
        missing = sorted(expected_files - observed_files)
        unexpected = sorted(observed_files - expected_files)
        raise BenchmarkAcquisitionError(
            f"benchmark archive inventory differs; missing={missing}, unexpected={unexpected}"
        )


def verify_benchmark_tree(root: Path, manifest: dict[str, Any]) -> None:
    """Require the materialized tree to contain exactly the manifest inventory."""
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise BenchmarkAcquisitionError("benchmark manifest has no file inventory")
    expected: dict[str, dict[str, Any]] = {}
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise BenchmarkAcquisitionError("benchmark manifest file entry is invalid")
        expected[item["path"]] = item
    observed: dict[str, Path] = {}
    if root.exists():
        for path in root.rglob("*"):
            if path.is_symlink():
                raise BenchmarkAcquisitionError(
                    f"benchmark materialization contains symlink: {path}"
                )
            if path.is_file():
                observed[path.relative_to(root).as_posix()] = path
    if set(observed) != set(expected):
        missing = sorted(set(expected) - set(observed))
        unexpected = sorted(set(observed) - set(expected))
        raise BenchmarkAcquisitionError(
            f"benchmark materialization differs; missing={missing}, unexpected={unexpected}"
        )
    for relative, item in expected.items():
        path = observed[relative]
        if path.stat().st_size != item["bytes"]:
            raise BenchmarkAcquisitionError(f"benchmark file size mismatch: {relative}")
        _check_digest(path, item["sha256"], label=relative)


def _extract_archive(archive: Path, destination: Path, expected_files: set[str]) -> None:
    executable = shutil.which("bsdtar")
    if executable is None:
        raise BenchmarkAcquisitionError("bsdtar is required to extract the official 7-Zip archive")
    listed = subprocess.run(
        [executable, "-tf", str(archive)],
        check=True,
        capture_output=True,
        text=True,
    )
    _safe_archive_members(listed.stdout, expected_files)
    subprocess.run(
        [
            executable,
            "--no-same-owner",
            "--no-same-permissions",
            "-xf",
            str(archive),
            "-C",
            str(destination),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def acquire_benchmark(
    destination: Path,
    *,
    manifest_path: Path = BENCHMARK_MANIFEST_PATH,
) -> BenchmarkFixture:
    """Acquire the fixed ETH3D scene and refuse any byte outside its manifest."""
    manifest, manifest_digest = load_benchmark_manifest(manifest_path)
    destination.mkdir(parents=True, exist_ok=True)
    archive_record = manifest["archive"]
    license_record = manifest["license"]
    archive = destination / archive_record["filename"]
    license_document = destination / license_record["filename"]
    for record, path, label in (
        (archive_record, archive, "benchmark archive"),
        (license_record, license_document, "license document"),
    ):
        if not path.exists():
            _download(record["url"], path)
        if path.stat().st_size != record["bytes"]:
            raise BenchmarkAcquisitionError(f"{label} byte size does not match the manifest")
        _check_digest(path, record["sha256"], label=label)

    materialized = destination / "materialized"
    expected_files = {item["path"] for item in manifest["files"]}
    if not materialized.exists():
        temporary = Path(tempfile.mkdtemp(prefix="eth3d-pipes-", dir=destination))
        try:
            _extract_archive(archive, temporary, expected_files)
            verify_benchmark_tree(temporary, manifest)
            os.replace(temporary, materialized)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    verify_benchmark_tree(materialized, manifest)

    receipt_record = {
        "archive_sha256": archive_record["sha256"],
        "corpus_class": "benchmark",
        "license_document_sha256": license_record["sha256"],
        "profile": "exulanica.benchmark-acquisition-receipt/v1",
        "source_manifest_sha256": manifest_digest,
        "verified_file_count": len(manifest["files"]),
    }
    receipt_digest = hashlib.sha256(canonical_json(receipt_record)).hexdigest()
    receipt = destination / "acquisition-receipt.json"
    receipt.write_bytes(
        canonical_json(
            {
                "profile": _DIGEST_BOUND_PROFILE,
                "record": receipt_record,
                "record_sha256": receipt_digest,
            }
        )
    )
    return BenchmarkFixture(
        root=materialized,
        image_directory=materialized / manifest["image_directory"],
        calibration_directory=materialized / manifest["calibration_directory"],
        source_manifest_path=manifest_path,
        source_manifest_digest=manifest_digest,
        acquisition_receipt_path=receipt,
    )
