"""What a generated asset job does on the rented machine before and around the run.

``prepare`` fetches the pinned upstream code as GitHub archives and holds each extracted tree to
its commit's tree id, applies the one recorded patch, lays DINOv2 out where torch.hub looks for it,
and fetches the route's weights at their pinned revisions, checking every file against its
manifest. Weights already in the bucket are checked again, not fetched. The DINOv2 file TRELLIS
loads is not on Hugging Face: its digest is recorded the first time it is fetched and every later
job is held to that record.

``run`` loads the route's backend and runs the job record (``exulanica_appearance.assets.job``).
"""

from __future__ import annotations

import hashlib
import importlib
import json
import shutil
import tarfile
import urllib.request
from pathlib import Path
from typing import Any, Final

from exulanica_appearance.assets.gittree import tree_id
from exulanica_appearance.canonical import Refused, canonical_bytes
from exulanica_appearance.weights import read_weights, verify_directory

__all__ = ["ROUTE_WEIGHTS", "fetch_upstream", "prepare", "weights_directory"]

#: The weights manifests each route loads, by file name under ml/appearance/weights.
ROUTE_WEIGHTS: Final = {
    "A": (
        "Tongyi-MAI__Z-Image-Turbo@f332072aa78b.json",
        "ZhengPeng7__BiRefNet@e2bf8e4460fc.json",
        "microsoft__TRELLIS-image-large@25e0d31ffbeb.json",
    ),
    "B": (
        "Tongyi-MAI__Z-Image-Turbo@f332072aa78b.json",
        "ZhengPeng7__BiRefNet@e2bf8e4460fc.json",
        "stepfun-ai__Step1X-3D@bf7084495b3a.json",
    ),
}
#: Read by repository id through the Hugging Face cache rather than from a path.
ROUTE_CACHED: Final = {"B": ("facebook__dinov2-with-registers-large@e4c89a4e0558.json",)}
_CHUNK: Final = 1 << 20


def weights_directory(weights: Path, repository: str) -> Path:
    return weights / repository.replace("/", "__")


def _archive(repository: str, commit: str, into: Path) -> Path:
    url = f"https://codeload.github.com/{repository}/tar.gz/{commit}"
    into.mkdir(parents=True, exist_ok=True)
    with (
        urllib.request.urlopen(url, timeout=120) as response,
        tarfile.open(fileobj=response, mode="r|gz") as tar,
    ):
        tar.extractall(into, filter="data")
    [top] = [path for path in into.iterdir() if path.is_dir()]
    return top


def fetch_upstream(sources: list[dict[str, Any]], route: str, root: Path) -> dict[str, str]:
    """Fetch every source the route needs under ``root/<name>``; return the tree each was held to."""
    held: dict[str, str] = {}
    for source in sources:
        if route not in source["routes"]:
            continue
        staging = root / f".{source['name']}"
        shutil.rmtree(staging, ignore_errors=True)
        top = _archive(source["repository"], source["commit"], staging)
        found = tree_id(top, source.get("gitlinks"))
        if found != source["tree"]:
            raise Refused(
                f"{source['repository']} at {source['commit']} has tree {found}, not {source['tree']}"
            )
        destination = root / source.get("place_in", source["name"])
        shutil.rmtree(destination, ignore_errors=True)
        destination.parent.mkdir(parents=True, exist_ok=True)
        top.rename(destination)
        shutil.rmtree(staging)
        patch = source.get("patch")
        if patch:
            path = destination / patch["file"]
            text = path.read_text(encoding="utf-8")
            if text.count(patch["replace"]) != 1:
                raise Refused(
                    f"{source['name']}: the patch's line is not in {patch['file']} exactly once"
                )
            path.write_text(text.replace(patch["replace"], patch["with"]), encoding="utf-8")
        held[source["name"]] = found
    return held


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _torch_hub(sources: list[dict[str, Any]], upstream: Path, torch_home: Path) -> dict[str, Any]:
    """Put DINOv2's code where torch.hub caches it, and its weights, pinned on first fetch."""
    [source] = [s for s in sources if s.get("torch_hub")]
    hub = torch_home / "hub"
    target = hub / source["torch_hub"]
    shutil.rmtree(target, ignore_errors=True)
    hub.mkdir(parents=True, exist_ok=True)
    shutil.copytree(upstream / source["name"], target)
    weights = source["weights"]
    checkpoint = hub / "checkpoints" / weights["file"]
    record = hub / "checkpoints" / f"{weights['file']}.pinned.json"
    if not checkpoint.exists():
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        partial = checkpoint.with_suffix(".partial")
        with (
            urllib.request.urlopen(weights["url"], timeout=600) as response,
            partial.open("wb") as handle,
        ):
            shutil.copyfileobj(response, handle, _CHUNK)
        partial.rename(checkpoint)
    size = checkpoint.stat().st_size
    if size != weights["size"]:
        raise Refused(f"{weights['file']} is {size} bytes, not {weights['size']}")
    digest = _sha256(checkpoint)
    if record.exists():
        pinned = json.loads(record.read_bytes())
        if pinned["sha256"] != digest:
            raise Refused(f"{weights['file']} is not the file pinned on its first fetch")
        return pinned
    pinned = {"pinned": "on first fetch", "sha256": digest, "size": size, "url": weights["url"]}
    record.write_bytes(canonical_bytes(pinned))
    return pinned


def _fetch_weights(manifest_raw: bytes, directory: Path) -> int:
    from huggingface_hub import snapshot_download

    manifest = read_weights(manifest_raw)
    try:
        return verify_directory(manifest_raw, directory)
    except Refused:
        snapshot_download(
            repo_id=manifest["repository"],
            revision=manifest["revision"],
            allow_patterns=manifest["selection"]["include"],
            local_dir=str(directory),
        )
        return verify_directory(manifest_raw, directory)


def _fetch_cached(manifest_raw: bytes, hf_home: Path) -> int:
    """A repository read by id: fetched into the Hugging Face cache, its main ref at the revision."""
    from huggingface_hub import snapshot_download

    manifest = read_weights(manifest_raw)
    owner, name = manifest["repository"].split("/")
    cache = hf_home / "hub"
    path = snapshot_download(
        repo_id=manifest["repository"],
        revision=manifest["revision"],
        allow_patterns=manifest["selection"]["include"],
        cache_dir=str(cache),
    )
    refs = cache / f"models--{owner}--{name}" / "refs"
    refs.mkdir(parents=True, exist_ok=True)
    (refs / "main").write_text(manifest["revision"], encoding="ascii")
    return verify_directory(manifest_raw, Path(path))


def prepare(
    *, code: Path, route: str, upstream: Path, weights: Path, torch_home: Path, hf_home: Path
) -> dict[str, Any]:
    """Everything the route needs, fetched or checked; returns what was held to what."""
    sources = json.loads((code / "ml/appearance/container/assets/upstream.json").read_bytes())[
        "sources"
    ]
    trees = fetch_upstream(sources, route, upstream)
    report: dict[str, Any] = {"route": route, "trees": trees, "weights": {}}
    if route == "A":
        report["dinov2_checkpoint"] = _torch_hub(sources, upstream, torch_home)
    for name in ROUTE_WEIGHTS[route]:
        raw = (code / "ml/appearance/weights" / name).read_bytes()
        manifest = read_weights(raw)
        report["weights"][name] = _fetch_weights(
            raw, weights_directory(weights, manifest["repository"])
        )
    for name in ROUTE_CACHED.get(route, ()):
        report["weights"][name] = _fetch_cached(
            (code / "ml/appearance/weights" / name).read_bytes(), hf_home
        )
    return report


def backend_for(route: str, weights: Path) -> Any:
    from exulanica_appearance.assets.backends import ROUTES

    module_name, class_name = ROUTES[route].split(":")
    return getattr(importlib.import_module(module_name), class_name)(weights)
