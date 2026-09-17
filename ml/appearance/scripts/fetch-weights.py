#!/usr/bin/env python3
"""Download exactly the files a staged job's weights manifests name, and verify each as it lands.

    python3 scripts/fetch-weights.py STAGED_DIR WEIGHTS_ROOT

Runs on the rented machine's host, where there is network; the container that loads the weights has
none. Nothing but the listed files is fetched, each from its pinned revision, and each is checked
against the manifest's sha256 (LFS files) or git blob id (small files in git) before it is put in
place. A file already present and correct is left alone, so an interrupted download resumes cheaply.

The standard library only: no Hugging Face client, no token, and no repository listing. The manifests
say what to fetch.
"""

from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path

CHUNK = 1 << 20
PARALLEL = 4


def blob_sha1(raw: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(raw) + raw).hexdigest()  # git's own object id, not a security digest


def correct(path: Path, item: dict) -> bool:
    if not path.is_file() or path.stat().st_size != item["size"]:
        return False
    if "sha256" in item:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while block := handle.read(CHUNK):
                digest.update(block)
        return digest.hexdigest() == item["sha256"]
    return blob_sha1(path.read_bytes()) == item["git_blob_sha1"]


def fetch(repository: str, revision: str, item: dict, *, root: Path) -> str:
    target = root / item["path"]
    if correct(target, item):
        return f"kept {item['path']}"
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".partial")
    url = f"https://huggingface.co/{repository}/resolve/{revision}/{item['path']}"
    digest = hashlib.sha256()
    size = 0
    with urllib.request.urlopen(url, timeout=120) as response, partial.open("wb") as handle:  # https only, built from the manifest
        while block := response.read(CHUNK):
            digest.update(block)
            size += len(block)
            handle.write(block)
    if size != item["size"]:
        partial.unlink()
        raise SystemExit(f"{item['path']}: {size} bytes, not the {item['size']} its manifest names")
    if "sha256" in item:
        if digest.hexdigest() != item["sha256"]:
            partial.unlink()
            raise SystemExit(f"{item['path']}: sha256 {digest.hexdigest()} is not the one its manifest names")
    elif blob_sha1(partial.read_bytes()) != item["git_blob_sha1"]:
        partial.unlink()
        raise SystemExit(f"{item['path']}: git blob id is not the one its manifest names")
    partial.replace(target)
    return f"fetched {item['path']} ({size} bytes)"


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    staged, weights_root = Path(argv[1]), Path(argv[2])
    total = 0
    for manifest_path in sorted((staged / "weights").glob("*.json")):
        manifest = json.loads(manifest_path.read_bytes())
        repository, revision = manifest["repository"], manifest["revision"]
        root = weights_root / f"{repository.replace('/', '__')}@{revision}"
        print(f"== {repository} at {revision} into {root}", flush=True)
        with ThreadPoolExecutor(PARALLEL) as pool:
            for line in pool.map(partial(fetch, repository, revision, root=root), manifest["files"]):
                print(f"   {line}", flush=True)
        total += manifest["total_bytes"]
    print(f"{total} bytes are in place")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
