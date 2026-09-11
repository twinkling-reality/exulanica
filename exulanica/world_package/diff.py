"""Semantic, value-redacted differences between two independently verified packages."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from exulanica.canonical import canonical_json
from exulanica.world_package.package import MANIFEST_PATH, verify_package

#: How a list item is recognised as the same item across two packages, so a change reads as one
#: entry added or removed rather than as the whole list replaced.
#:
#: ``artifact_id`` and ``scene_id`` were added for ADR-0009 D9, whose no-ship rule is that
#: deleting one of a scene's members changes the export. Without them every item in
#: ``reconstruction/artifacts.json`` is unidentified, ``_identified`` returns None for the list,
#: and the entire list collapses to a single opaque ``replaced`` change. Section 6.6 promises
#: that "the diff between two versions is the honest answer to what changed"; a diff that cannot
#: name which artifact went is not that answer.
_IDENTITY_KEYS = (
    "@id",
    "id",
    "artifact_id",
    "capture_id",
    "entity_id",
    "occurrence_id",
    "scene_id",
    "tombstone_id",
    # The authored-world extension. Appended rather than interleaved, and none of them is a key
    # of any 1.0 list item, so a diff between two 1.0 packages reads exactly as it did.
    "version_id",
    "edit_id",
    "object_id",
    "snapshot_id",
)


@dataclass(frozen=True, slots=True)
class PackageDiff:
    from_root_sha256: str
    to_root_sha256: str
    added_files: tuple[str, ...]
    removed_files: tuple[str, ...]
    changed_files: tuple[str, ...]
    semantic_changes: tuple[dict[str, str], ...]

    @property
    def changed(self) -> bool:
        return self.from_root_sha256 != self.to_root_sha256

    def as_dict(self) -> dict[str, Any]:
        return {
            "added_files": list(self.added_files),
            "changed": self.changed,
            "changed_files": list(self.changed_files),
            "from_root_sha256": self.from_root_sha256,
            "removed_files": list(self.removed_files),
            "semantic_changes": list(self.semantic_changes),
            "to_root_sha256": self.to_root_sha256,
        }


def diff_packages(before: Path, after: Path) -> PackageDiff:
    before_report = verify_package(before)
    after_report = verify_package(after)
    before_manifest = _json(before / MANIFEST_PATH)
    after_manifest = _json(after / MANIFEST_PATH)
    before_hashes = {entry["path"]: entry["sha256"] for entry in before_manifest["entries"]}
    after_hashes = {entry["path"]: entry["sha256"] for entry in after_manifest["entries"]}
    before_paths = set(before_hashes)
    after_paths = set(after_hashes)
    changed_files = tuple(
        sorted(
            path
            for path in before_paths & after_paths
            if before_hashes[path] != after_hashes[path]
        )
    )
    changes: list[dict[str, str]] = []
    for path in changed_files:
        # Native geometry receipts retain their original floating-point representation. Their
        # file hashes already describe a change; the canonical metadata walk accepts no floats.
        if path.endswith(".json") and not path.startswith("assets/"):
            _walk(_json(before / path), _json(after / path), f"/{_escape(path)}", changes)
    return PackageDiff(
        from_root_sha256=before_report.merkle_root_sha256,
        to_root_sha256=after_report.merkle_root_sha256,
        added_files=tuple(sorted(after_paths - before_paths)),
        removed_files=tuple(sorted(before_paths - after_paths)),
        changed_files=changed_files,
        semantic_changes=tuple(changes),
    )


def _walk(before: Any, after: Any, pointer: str, changes: list[dict[str, str]]) -> None:
    if type(before) is not type(after):
        changes.append(_change(pointer, "replaced", before, after))
        return
    if isinstance(before, Mapping):
        before_keys = set(before)
        after_keys = set(after)
        for key in sorted(before_keys - after_keys):
            changes.append(_change(f"{pointer}/{_escape(str(key))}", "removed", before[key], None))
        for key in sorted(after_keys - before_keys):
            changes.append(_change(f"{pointer}/{_escape(str(key))}", "added", None, after[key]))
        for key in sorted(before_keys & after_keys):
            _walk(before[key], after[key], f"{pointer}/{_escape(str(key))}", changes)
        return
    if isinstance(before, list):
        identified_before = _identified(before)
        identified_after = _identified(after)
        if identified_before is not None and identified_after is not None:
            before_keys = set(identified_before)
            after_keys = set(identified_after)
            for key in sorted(before_keys - after_keys):
                changes.append(
                    _change(f"{pointer}/@{_escape(key)}", "removed", identified_before[key], None)
                )
            for key in sorted(after_keys - before_keys):
                changes.append(
                    _change(f"{pointer}/@{_escape(key)}", "added", None, identified_after[key])
                )
            for key in sorted(before_keys & after_keys):
                _walk(
                    identified_before[key],
                    identified_after[key],
                    f"{pointer}/@{_escape(key)}",
                    changes,
                )
        elif before != after:
            changes.append(_change(pointer, "replaced", before, after))
        return
    if before != after:
        changes.append(_change(pointer, "replaced", before, after))


def _identified(values: Sequence[Any]) -> dict[str, Any] | None:
    if not values:
        return {}
    result: dict[str, Any] = {}
    for value in values:
        if not isinstance(value, Mapping):
            return None
        identity = next((value[key] for key in _IDENTITY_KEYS if key in value), None)
        if not isinstance(identity, str) or identity in result:
            return None
        result[identity] = value
    return result


def _change(pointer: str, kind: str, before: Any, after: Any) -> dict[str, str]:
    value: dict[str, str] = {"kind": kind, "pointer": pointer}
    if before is not None:
        value["before_sha256"] = hashlib.sha256(canonical_json(before)).hexdigest()
    if after is not None:
        value["after_sha256"] = hashlib.sha256(canonical_json(after)).hexdigest()
    return value


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _escape(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")
