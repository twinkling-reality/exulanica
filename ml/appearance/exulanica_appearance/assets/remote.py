"""What a generated asset job does on the rented machine before and around the run.

``prepare`` fetches the pinned upstream code as GitHub archives and holds each extracted tree to
its commit's tree id, applies the one recorded patch, lays DINOv2 out where torch.hub looks for it,
and fetches the route's weights at their pinned revisions, checking every file against its
manifest. Weights already in the bucket are checked again, not fetched. The DINOv2 file TRELLIS
loads is not on Hugging Face: its digest is recorded the first time it is fetched and every later
job is held to that record.

``run`` loads the route's backend and runs the job record (``exulanica_appearance.assets.job``).

``publish`` copies the job's outputs from the machine's own disk to the bucket mount. The mount
takes plain writes but refuses setting a file's mode or times (measured on Nebius, 2026-10-06: a
copytree onto it failed with "Operation not permitted"), so the job does all its work on its own
disk and publishes each output by writing its bytes once: no rename, no mode or time, never over
other bytes.
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

from exulanica_pieces.canonical import Refused, canonical_bytes

from exulanica_appearance.assets.gittree import tree_id
from exulanica_appearance.canonical import Refused as WeightsRefused
from exulanica_appearance.weights import read_weights, verify_directory

__all__ = ["ROUTE_WEIGHTS", "fetch_upstream", "prepare", "publish", "weights_directory"]

#: The weights manifests each route loads, by file name under ml/appearance/weights.
ROUTE_WEIGHTS: Final = {
    "A": (
        "Tongyi-MAI__Z-Image-Turbo@f332072aa78b.json",
        "ZhengPeng7__BiRefNet@e2bf8e4460fc.json",
        "microsoft__TRELLIS-image-large@25e0d31ffbeb.json",
    ),
    # Route B starts from route A's cut-outs: it makes no concept picture or cut-out of its own.
    "B": ("stepfun-ai__Step1X-3D@bf7084495b3a.json",),
    # Route C draws a creature's concept picture following its plan's sketch (Z-Image with the
    # union control, Track A's candidate a2), then takes route A's cut-out and mesh.
    "C": (
        "Tongyi-MAI__Z-Image@04cc4abb7c50.json",
        "alibaba-pai__Z-Image-Fun-Controlnet-Union-2.1@755999a93490.json",
        "ZhengPeng7__BiRefNet@e2bf8e4460fc.json",
        "microsoft__TRELLIS-image-large@25e0d31ffbeb.json",
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
    except WeightsRefused:
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
    return verify_directory(manifest_raw, Path(path), within=cache / f"models--{owner}--{name}")


def prepare(
    *, code: Path, route: str, upstream: Path, weights: Path, torch_home: Path, hf_home: Path
) -> dict[str, Any]:
    """Everything the route needs, fetched or checked; returns what was held to what."""
    sources = json.loads((code / "ml/appearance/container/assets/upstream.json").read_bytes())[
        "sources"
    ]
    trees = fetch_upstream(sources, route, upstream)
    report: dict[str, Any] = {"route": route, "trees": trees, "weights": {}}
    if route in ("A", "C"):
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


def publish(source: Path, target: Path, ledger: Path) -> dict[str, int]:
    """Write every finished file under ``source`` to the same path under ``target``, once.

    ``ledger`` (on the machine's disk) lists what is already published, so a file is read back
    from the mount at most once. A file still being written (``*.partial``) waits for the next
    call. A target that already holds other bytes is refused: outputs are written once."""
    published = set(ledger.read_text(encoding="utf-8").split()) if ledger.exists() else set()
    counts = {"published": 0, "already": 0}
    for path in sorted(p for p in source.rglob("*") if p.is_file()):
        if path.name.endswith(".partial"):
            continue
        relative = path.relative_to(source).as_posix()
        data = path.read_bytes()
        entry = f"{relative}@{hashlib.sha256(data).hexdigest()}"
        if entry in published:
            counts["already"] += 1
            continue
        destination = target / relative
        if destination.exists():
            if destination.read_bytes() != data:
                raise Refused(f"{destination} already holds other bytes; output is written once")
            counts["already"] += 1
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with open(destination, "wb") as handle:
                handle.write(data)
            counts["published"] += 1
        published.add(entry)
        with open(ledger, "a", encoding="utf-8") as handle:
            handle.write(entry + "\n")
    return counts
