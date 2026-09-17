"""A weights manifest pins every file, holds the licence rule, and verifies a download."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from exulanica_appearance.canonical import Refused, canonical_bytes, parse_canonical
from exulanica_appearance.weights import (
    MetadataDirectory,
    build_weights,
    git_blob_sha1,
    read_weights,
    verify_directory,
)

WEIGHTS = Path(__file__).resolve().parents[1] / "weights"
REVISION = "a" * 40
OTHER = "b" * 40
BIG = b"weights " * 64
SMALL = b'{"layers": 2}\n'


def _metadata(
    root: Path, repository: str, revision: str, card: dict, files: dict[str, bytes], lfs: set[str]
) -> Path:
    directory = root / f"{repository.replace('/', '_')}@{revision}"
    directory.mkdir(parents=True)
    (directory / "source.txt").write_text(f"{repository}\n{revision}\n")
    (directory / "revision.json").write_text(
        json.dumps({"id": repository, "sha": revision, "cardData": card})
    )
    tree = []
    for path, raw in files.items():
        if path in lfs:
            tree.append(
                {
                    "type": "file",
                    "path": path,
                    "size": len(raw),
                    "oid": "0" * 40,
                    "lfs": {"oid": hashlib.sha256(raw).hexdigest(), "size": len(raw)},
                }
            )
        else:
            tree.append({"type": "file", "path": path, "size": len(raw), "oid": git_blob_sha1(raw)})
    (directory / "tree.json").write_text(json.dumps(tree))
    (directory / "README.md").write_text(f"---\nlicense: {card.get('license')}\n---\n")
    return directory


def _spec(**changes):
    spec = {
        "repository": "owner/model",
        "revision": REVISION,
        "include": ["transformer/*"],
        "reason": "the transformer the pipeline loads",
        "lineage": [],
    }
    spec.update(changes)
    return spec


@pytest.fixture
def metadata(tmp_path):
    files = {
        "transformer/model.safetensors": BIG,
        "transformer/config.json": SMALL,
        "assets/demo.mp4": b"video",
    }
    own = _metadata(
        tmp_path,
        "owner/model",
        REVISION,
        {"license": "apache-2.0"},
        files,
        {"transformer/model.safetensors", "assets/demo.mp4"},
    )
    base = _metadata(
        tmp_path,
        "base/model",
        OTHER,
        {"license": "mit"},
        {"model.safetensors": BIG},
        {"model.safetensors"},
    )
    blocked = _metadata(
        tmp_path,
        "blocked/model",
        OTHER,
        {"license": "other", "license_name": "nvidia-open-model-license"},
        {"model.safetensors": BIG},
        {"model.safetensors"},
    )
    return {
        (d.repository, d.revision): d for d in map(MetadataDirectory.read, (own, base, blocked))
    }


def test_a_manifest_pins_each_selected_file_by_its_kind_of_digest(metadata):
    raw = build_weights(_spec(), "2026-09-17", metadata)
    document = read_weights(raw)
    assert [f["path"] for f in document["files"]] == [
        "transformer/config.json",
        "transformer/model.safetensors",
    ]
    assert document["files"][0] == {
        "git_blob_sha1": git_blob_sha1(SMALL),
        "path": "transformer/config.json",
        "size": len(SMALL),
    }
    assert document["files"][1]["sha256"] == hashlib.sha256(BIG).hexdigest()
    assert document["licence"]["id"] == "Apache-2.0"
    assert document["total_bytes"] == len(SMALL) + len(BIG)


def test_lineage_is_read_and_held_to_the_rule(metadata):
    identical = {
        "component": "transformer/",
        "kind": "identical-bytes",
        "repository": "base/model",
        "revision": OTHER,
        "path": "model.safetensors",
        "own_path": "transformer/model.safetensors",
        "evidence": "same bytes",
    }
    document = read_weights(build_weights(_spec(lineage=[identical]), "2026-09-17", metadata))
    assert document["lineage"][0]["licence_id"] == "MIT"
    blocked = dict(identical, repository="blocked/model")
    with pytest.raises(Refused, match="section 6"):
        build_weights(_spec(lineage=[blocked]), "2026-09-17", metadata)
    different = dict(identical, own_path="transformer/config.json")
    with pytest.raises(Refused, match="not byte-identical"):
        build_weights(_spec(lineage=[different]), "2026-09-17", metadata)


def test_a_pattern_that_selects_nothing_is_refused(metadata):
    with pytest.raises(Refused, match="selects no file"):
        build_weights(_spec(include=["transformer/*", "text_encoder/*"]), "2026-09-17", metadata)


def _mutated(raw: bytes, change) -> bytes:
    document = parse_canonical(raw, "test")
    change(document)
    return canonical_bytes(document)


@pytest.mark.parametrize(
    "change, words",
    [
        (lambda d: d.update(revision="main"), "40 lowercase hex"),
        (lambda d: d["licence"].update(id="LicenseRef-NVIDIA-Open-Model"), "licence id"),
        (lambda d: d["licence"].update(card={"license": "openrail"}), "section 6"),
        (lambda d: d["files"].reverse(), "sorted by path"),
        (lambda d: d["files"][1].update(git_blob_sha1="c" * 40), "exactly one of"),
        (lambda d: d["files"][0].update(path="../escape"), "relative repository path"),
        (lambda d: d.update(total_bytes=1), "total_bytes"),
        (lambda d: d["selection"].update(include=["vae/*"]), "not selected"),
    ],
)
def test_the_reader_refuses_a_manifest_edited_out_of_shape(metadata, change, words):
    raw = build_weights(_spec(), "2026-09-17", metadata)
    with pytest.raises(Refused, match=words):
        read_weights(_mutated(raw, change))


def test_verify_directory_checks_sizes_and_digests(metadata, tmp_path):
    raw = build_weights(_spec(), "2026-09-17", metadata)
    download = tmp_path / "download"
    (download / "transformer").mkdir(parents=True)
    (download / "transformer" / "model.safetensors").write_bytes(BIG)
    (download / "transformer" / "config.json").write_bytes(SMALL)
    assert verify_directory(raw, download) == len(BIG) + len(SMALL)
    (download / "transformer" / "model.safetensors").write_bytes(BIG[:-1] + b"X")
    with pytest.raises(Refused, match="sha256"):
        verify_directory(raw, download)
    (download / "transformer" / "model.safetensors").write_bytes(BIG)
    (download / "transformer" / "config.json").write_bytes(SMALL.replace(b"2", b"3"))
    with pytest.raises(Refused, match="git blob"):
        verify_directory(raw, download)
    (download / "transformer" / "config.json").unlink()
    with pytest.raises(Refused, match="missing"):
        verify_directory(raw, download)


def test_every_committed_manifest_reads_and_names_an_allowed_licence():
    manifests = sorted(path for path in WEIGHTS.glob("*.json") if path.name != "candidates.json")
    assert len(manifests) == 10
    for path in manifests:
        document = read_weights(path.read_bytes())
        name = f"{document['repository'].replace('/', '__')}@{document['revision'][:12]}.json"
        assert path.name == name


def test_committed_manifests_rebuild_from_the_fetched_metadata(repository):
    root = repository / ".exulanica" / "appearance" / "hf-metadata"
    if not root.is_dir():
        pytest.skip(
            "the fetched Hugging Face metadata lives under .exulanica, which this checkout has not got"
        )
    metadata = {}
    for directory in root.iterdir():
        if (directory / "source.txt").is_file():
            read = MetadataDirectory.read(directory)
            metadata[(read.repository, read.revision)] = read
    spec = json.loads((WEIGHTS / "candidates.json").read_bytes())
    for entry in spec["repositories"]:
        raw = build_weights(entry, spec["read_on"], metadata)
        name = f"{entry['repository'].replace('/', '__')}@{entry['revision'][:12]}.json"
        assert (WEIGHTS / name).read_bytes() == raw, name
