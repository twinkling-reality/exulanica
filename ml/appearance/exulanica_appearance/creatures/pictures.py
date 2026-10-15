"""Route P's paid step: for each asked creature, its picture, the picture's cut-out and the 3D model
made from it, and nothing else.

Runs on the rented machine with route A's three models (Z-Image-Turbo, BiRefNet and
TRELLIS-image-large at their pinned revisions, ``assets/remote.py``), from
``container/assets/job.sh``; on this Mac with :class:`StandIn`. Per item, in the job's order: the
picture is the one kept with the creature (a v2 request's picture, travelling beside the request by
digest) or a concept drawn from the request's appearance words in a framing of the creature looks
catalog (``assets/catalogs/generation/creature-looks.v1.json``: no structure control, and never the
colour words, which the colour step answers); then the cut-out and the 3D model, each written
once. Nothing is fitted here: the fit needs no GPU (``creatures/fit.py``) and runs after the fetch,
so no paid minute is spent on it.

Every item is checked before the first model runs: its request and picture are given, its framing
is the catalog's, and its prompt holds no numeral (a model paints the numbers it is told). The run
stops before an item whose estimate, half as much again, would pass the job's stop, so what was
made is published whole. Everything is written once under the output directory:

    inputs/<sha256>.png      pictures and cut-outs
    meshes/<sha256>.npz      3D models as the model returned them, in its own frame
    progress-<job sha256>-<item>.json   the results so far, after each item
    results-<job sha256>-<ended at>.json
"""

from __future__ import annotations

import hashlib
import io
import platform
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Protocol

import numpy as np
from exulanica_pieces.canonical import (
    Refused,
    canonical_bytes,
    exact_keys,
    is_count,
    is_sha256,
    parse_strict,
    sha256_hex,
)
from exulanica_pieces.geometry.mesh import Mesh

from exulanica_appearance.creatures.geometry import voxel_surface
from exulanica_appearance.creatures.request import CreatureRequest, RequestRefused, read_request

__all__ = [
    "CATALOG_ID",
    "CATALOG_PATH",
    "JOB_PROFILE",
    "RESULTS_PROFILE",
    "Framing",
    "PictureBackend",
    "Planned",
    "Prepared",
    "StandIn",
    "framed_prompt",
    "load_framings",
    "make_job",
    "prepare_picture_job",
    "read_framings",
    "read_picture_job",
    "run_picture_job",
]

JOB_PROFILE: Final = "exulanica.creature-picture-job/v1"
RESULTS_PROFILE: Final = "exulanica.creature-picture-results/v1"
#: Relative to the repository root.
CATALOG_PATH: Final = "assets/catalogs/generation/creature-looks.v1.json"
CATALOG_ID: Final = "creature-looks"
#: The run stops before an item whose estimate times this would pass the job's stop.
STOP_MARGIN: Final = 1.5
_KEY: Final = "{appearance}"
_ENTRY_KEYS: Final = ("key", "licence", "reason", "words")
_LICENCE_KEYS: Final = ("content_source", "licence_source", "origin", "spdx", "verdict")
_SEED_MAXIMUM: Final = (1 << 63) - 1
_WORDS_MAXIMUM: Final = 600
_REASON_WORDS: Final = 5


@dataclass(frozen=True)
class Framing:
    """A catalog entry: the words a concept picture is drawn from, the request's appearance words
    standing where ``{appearance}`` is."""

    key: str
    words: str
    reason: str


def read_framings(raw: bytes) -> dict[str, Framing]:
    """The creature looks catalog, strictly, or :class:`Refused` naming what is wrong."""
    where = CATALOG_PATH
    document = exact_keys(
        parse_strict(raw, where),
        ("catalog_id", "catalog_version", "entries", "schema_version"),
        where,
    )
    if document["schema_version"] != 1 or document["catalog_id"] != CATALOG_ID:
        raise Refused(f"{where} is schema version 1 of catalog {CATALOG_ID!r}")
    if not is_count(document["catalog_version"], 1):
        raise Refused(f"{where}: catalog_version is a whole number from 1")
    entries = document["entries"]
    if not isinstance(entries, list) or not entries:
        raise Refused(f"{where}: entries is a list of at least one framing")
    found: dict[str, Framing] = {}
    for index, value in enumerate(entries):
        at = f"{where}: entries[{index}]"
        entry = exact_keys(value, _ENTRY_KEYS, at)
        exact_keys(entry["licence"], _LICENCE_KEYS, f"{at}.licence")
        key, words, reason = entry["key"], entry["words"], entry["reason"]
        if not isinstance(key, str) or not key.replace("-", "").isalpha() or not key.islower():
            raise Refused(f"{at}.key is lowercase words joined by hyphens")
        if key in found:
            raise Refused(f"{at}.key repeats {key!r}")
        if (
            not isinstance(words, str)
            or not 0 < len(words) <= _WORDS_MAXIMUM
            or words.count(_KEY) != 1
            or words.replace(_KEY, "").count("{") + words.replace(_KEY, "").count("}") != 0
        ):
            raise Refused(f"{at}.words holds {_KEY} once and no other braces")
        if any(character.isdigit() for character in words):
            raise Refused(f"{at}.words holds a numeral; a model paints the numbers it is told")
        if not isinstance(reason, str) or len(reason.split()) < _REASON_WORDS:
            raise Refused(f"{at}.reason says why the framing exists")
        found[key] = Framing(key, words, reason)
    return found


def load_framings(repository: Path) -> tuple[dict[str, Framing], str]:
    """The committed catalog and its digest, which a job and its results name."""
    raw = (repository / CATALOG_PATH).read_bytes()
    return read_framings(raw), sha256_hex(raw)


def framed_prompt(framing: Framing, appearance: str) -> str:
    """The concept picture's words: the appearance words in the framing, a capital first."""
    prompt = framing.words.replace(_KEY, appearance.strip().rstrip("."))
    if any(character.isdigit() for character in prompt):
        raise Refused("the prompt holds a numeral; a model paints the numbers it is told")
    return prompt[:1].upper() + prompt[1:]


class PictureMesh(Protocol):
    mesh: Mesh
    up: str
    front: str


class PictureBackend(Protocol):
    """Route A's backend (``assets/backends/trellis.py``) or :class:`StandIn`."""

    route: str

    def concept(self, prompt: str, seed: int) -> bytes:
        """A PNG of the figure on a plain background."""

    def cutout(self, picture: bytes) -> bytes:
        """An RGBA PNG: the figure, its background transparent."""

    def mesh(self, cutout: bytes, seed: int, request: Mapping[str, Any]) -> PictureMesh:
        """The 3D model on the cut-out; ``request`` is there for a stand-in, not a model."""

    def runtime(self) -> dict[str, Any]:
        """The machine and library versions the results state."""


def read_picture_job(raw: bytes) -> dict[str, Any]:
    """A creature picture job record, or :class:`Refused` naming the field at fault."""
    job = exact_keys(
        parse_strict(raw, "the job record"),
        (
            "catalog_sha256",
            "code_sha256",
            "components_sha256",
            "container",
            "items",
            "profile",
            "route",
            "stop",
        ),
        f"a job record ({JOB_PROFILE})",
    )
    if job["profile"] != JOB_PROFILE:
        raise Refused(f"the job record's profile is {JOB_PROFILE}")
    if job["route"] != "P":
        raise Refused("a creature picture job takes route P")
    for field in ("catalog_sha256", "code_sha256", "components_sha256"):
        if not is_sha256(job[field]):
            raise Refused(f"{field} is 64 lowercase hex digits")
    container = job["container"]
    if (
        not isinstance(container, str)
        or not container.startswith("sha256:")
        or not is_sha256(container.removeprefix("sha256:"))
    ):
        raise Refused("container is the image's sha256 digest")
    items = job["items"]
    if not isinstance(items, list) or not 1 <= len(items) <= 64:
        raise Refused("a job holds 1 to 64 items")
    seen = set()
    for index, value in enumerate(items):
        item = exact_keys(
            value, ("framing", "request_sha256", "seed", "variant"), f"items[{index}]"
        )
        if (
            not is_sha256(item["request_sha256"])
            or not is_count(item["seed"])
            or item["seed"] > _SEED_MAXIMUM
            or not is_count(item["variant"])
            or item["variant"] >= 16
            or not (item["framing"] is None or isinstance(item["framing"], str))
        ):
            raise Refused(
                f"items[{index}] is a request's sha256, a seed, a variant and a framing or null"
            )
        key = (item["request_sha256"], item["variant"])
        if key in seen:
            raise Refused(f"items[{index}] repeats a request's variant")
        seen.add(key)
    stop = exact_keys(job["stop"], ("estimate_seconds", "item_seconds", "stop_at_seconds"), "stop")
    if (
        not all(is_count(value, 1) for value in stop.values())
        or stop["stop_at_seconds"] < stop["estimate_seconds"]
        or stop["item_seconds"] > stop["estimate_seconds"]
    ):
        raise Refused(
            "stop holds the job's estimate, an item's, and a stop at or after the job's, "
            "in whole seconds"
        )
    return job


@dataclass(frozen=True)
class Planned:
    item: Mapping[str, Any]
    request: CreatureRequest
    #: The concept's words, or None when the picture is the one kept with the creature.
    prompt: str | None
    picture: bytes | None


@dataclass(frozen=True)
class Prepared:
    job: Mapping[str, Any]
    job_sha256: str
    catalog_sha256: str
    planned: tuple[Planned, ...]


def prepare_picture_job(
    *,
    job_raw: bytes,
    requests: Sequence[bytes],
    pictures: Mapping[str, bytes],
    repository: Path,
) -> Prepared:
    """Every item checked before a model is loaded: ``pictures`` holds the kept pictures by
    sha256. A refusal names the item and what it lacks."""
    job = read_picture_job(job_raw)
    framings, catalog_sha256 = load_framings(repository)
    if catalog_sha256 != job["catalog_sha256"]:
        raise Refused("the job names another creature looks catalog than this code's")
    by_digest: dict[str, CreatureRequest] = {}
    for raw in requests:
        try:
            by_digest[sha256_hex(raw)] = read_request(raw)
        except RequestRefused as exc:
            raise Refused(f"request {sha256_hex(raw)}: {exc}") from exc
    planned = []
    for index, item in enumerate(job["items"]):
        request = by_digest.get(item["request_sha256"])
        if request is None:
            raise Refused(f"items[{index}] names a request that was not given")
        if request.picture_sha256 is not None:
            picture = pictures.get(request.picture_sha256)
            if picture is None or len(picture) != request.picture_bytes:
                raise Refused(f"items[{index}]: the picture its request names was not given")
            if item["framing"] is not None:
                raise Refused(f"items[{index}] has a kept picture, so it takes no framing")
            planned.append(Planned(item, request, None, picture))
            continue
        framing = framings.get(item["framing"]) if item["framing"] is not None else None
        if framing is None:
            raise Refused(f"items[{index}] needs a framing of the catalog: {sorted(framings)}")
        prompt = framed_prompt(framing, request.appearance)
        planned.append(Planned(item, request, prompt, None))
    return Prepared(job, sha256_hex(job_raw), catalog_sha256, tuple(planned))


#: The job's setup before its first item, in seconds: weights, wheels and models loaded (J1 took
#: about ten to twelve minutes on Nebius AI Cloud's RTX PRO 6000; fifteen covers a slow mirror).
SETUP_SECONDS: Final = 900


def make_job(
    requests: Sequence[bytes],
    *,
    repository: Path,
    framing: str,
    seeds: Sequence[int],
    item_seconds: int = 25,
) -> bytes:
    """A route P job record for ``requests``, each drawn once per seed in ``framing``, seed-major so
    a stop still leaves every request drawn once: the code archive's, the components' and the
    catalog's digests from ``repository``, the image this tooling runs, and the stops (the job's
    estimate its setup and every item; its stop half as much again). Every item is checked by
    :func:`prepare_picture_job` before the record is returned."""
    from exulanica_appearance.assets.nebius import IMAGE, code_archive
    from exulanica_appearance.assets.remote import components_sha256

    if not requests or not seeds or len(set(seeds)) != len(seeds):
        raise Refused("a job draws at least one request, each seed once")
    _framings, catalog_sha256 = load_framings(repository)
    items = [
        {"request_sha256": sha256_hex(raw), "seed": seed, "variant": variant, "framing": framing}
        for variant, seed in enumerate(seeds)
        for raw in requests
    ]
    estimate = SETUP_SECONDS + item_seconds * len(items)
    job = canonical_bytes(
        {
            "profile": JOB_PROFILE,
            "route": "P",
            "code_sha256": sha256_hex(code_archive(repository)),
            "components_sha256": components_sha256(repository, "P"),
            "container": IMAGE.split("@", 1)[1],
            "catalog_sha256": catalog_sha256,
            "items": items,
            "stop": {
                "estimate_seconds": estimate,
                "item_seconds": item_seconds,
                "stop_at_seconds": -(-estimate * 3 // 2),
            },
        }
    )
    prepare_picture_job(job_raw=job, requests=requests, pictures={}, repository=repository)
    return job


def _write_once(path: Path, data: bytes) -> None:
    if path.exists():
        if path.read_bytes() != data:
            raise Refused(f"{path} already holds other bytes; output is written once")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.write_bytes(data)
    partial.replace(path)


def _mesh_npz(raw: PictureMesh) -> tuple[bytes, dict[str, Any]]:
    """The model as ``fit.model_from_npz`` reads it, and what it holds."""
    mesh = raw.mesh
    buffer = io.BytesIO()
    np.savez_compressed(
        buffer,
        positions=np.asarray(mesh.positions, dtype=np.float32),
        triangles=np.asarray(mesh.triangles, dtype=np.int32),
        colours=np.asarray(mesh.colours, dtype=np.uint8),
    )
    return buffer.getvalue(), {
        "frame": {"front": raw.front, "up": raw.up},
        "triangles": len(mesh.triangles),
        "vertices": len(mesh.positions),
    }


def _rest(request: CreatureRequest) -> dict[str, Any]:
    return {"ends": request.ends, "joints": request.joints, "radii": request.radii}


def run_picture_job(
    prepared: Prepared,
    backend: PictureBackend,
    out: Path,
    *,
    started: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Run every planned item until the stop. ``started`` is when the job began on ``clock``
    (job.sh's start, setup included), by default now."""
    # A stand-in runs any job on this Mac; on the rented machine only route A's models draw.
    if backend.route not in ("A", "stand-in"):
        raise Refused(f"route P draws with route A's models, not route {backend.route}'s")
    began = clock() if started is None else started
    stop = prepared.job["stop"]
    results: dict[str, Any] = {
        "catalog_sha256": prepared.catalog_sha256,
        "components_sha256": prepared.job["components_sha256"],
        "items": [],
        "job_sha256": prepared.job_sha256,
        "profile": RESULTS_PROFILE,
        "runtime": backend.runtime(),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "stopped": None,
    }
    for index, plan in enumerate(prepared.planned):
        elapsed = clock() - began
        if elapsed + STOP_MARGIN * stop["item_seconds"] > stop["stop_at_seconds"]:
            results["stopped"] = (
                f"before item {index}: {round(elapsed)} s run, an item's estimate "
                f"{stop['item_seconds']} s, the stop at {stop['stop_at_seconds']} s"
            )
            break
        item = plan.item
        record: dict[str, Any] = {
            "framing": item["framing"],
            "inputs": {},
            "prompt_sha256": (
                hashlib.sha256(plan.prompt.encode("utf-8")).hexdigest() if plan.prompt else None
            ),
            "request_sha256": item["request_sha256"],
            "seconds": {},
            "seed": item["seed"],
            "variant": item["variant"],
        }
        seconds: dict[str, int] = record["seconds"]
        try:
            record["stage"] = "picture"
            start = clock()
            picture = (
                plan.picture
                if plan.picture is not None
                else backend.concept(plan.prompt or "", item["seed"])
            )
            seconds["picture"] = round(clock() - start)
            record["inputs"]["picture"] = sha256_hex(picture)
            _write_once(out / "inputs" / f"{record['inputs']['picture']}.png", picture)
            record["stage"] = "cutout"
            start = clock()
            cutout = backend.cutout(picture)
            seconds["cutout"] = round(clock() - start)
            record["inputs"]["cutout"] = sha256_hex(cutout)
            _write_once(out / "inputs" / f"{record['inputs']['cutout']}.png", cutout)
            record["stage"] = "mesh"
            start = clock()
            raw = backend.mesh(cutout, item["seed"], _rest(plan.request))
            data, measured = _mesh_npz(raw)
            seconds["mesh"] = round(clock() - start)
            record["mesh"] = {"sha256": sha256_hex(data), **measured}
            _write_once(out / "meshes" / f"{record['mesh']['sha256']}.npz", data)
            record["outcome"] = "made"
        except Exception as error:  # noqa: BLE001 - one item's failure must not lose a paid batch
            record["outcome"] = "failed"
            record["failure"] = {
                "code": f"{record['stage']}_failed",
                "detail": f"{type(error).__name__}: {error}"[:500],
            }
        results["items"].append(record)
        _write_once(
            out / f"progress-{prepared.job_sha256}-{index:03d}.json", canonical_bytes(results)
        )
    results["ended_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    stamp = results["ended_at"].replace(":", "").replace("-", "")
    _write_once(out / f"results-{prepared.job_sha256}-{stamp}.json", canonical_bytes(results))
    return results


@dataclass(frozen=True)
class StandInMesh:
    mesh: Mesh
    up: str = "+Z"
    front: str = "-Y"


class StandIn:
    """Stand-ins for route A's three models, so the whole job runs on this Mac with no GPU: a
    drawn figure tinted by its words and seed, its non-white pixels as the cut-out, and a 3D model
    of the request's own rest skeleton (each bone a capsule of its thickness, filled on a grid and
    its surface taken), given as TRELLIS gives one: +Z up, its front toward -Y, in a unit box,
    coloured as the cut-out."""

    route = "stand-in"
    #: Cells along the skeleton's longest side.
    cells = 48

    def concept(self, prompt: str, seed: int) -> bytes:
        from PIL import Image, ImageDraw

        digest = hashlib.sha256(f"{prompt}{seed}".encode()).digest()
        tint = tuple(20 + value % 200 for value in digest[:3])
        image = Image.new("RGB", (256, 256), (255, 255, 255))
        draw = ImageDraw.Draw(image)
        draw.ellipse((78, 40, 178, 150), fill=tint)
        draw.ellipse((98, 120, 158, 230), fill=tuple(max(value - 40, 0) for value in tint))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    def cutout(self, picture: bytes) -> bytes:
        from PIL import Image

        image = np.asarray(Image.open(io.BytesIO(picture)).convert("RGB"))
        alpha = np.where(image.min(axis=2) < 250, 255, 0).astype(np.uint8)
        buffer = io.BytesIO()
        Image.fromarray(np.dstack([image, alpha])).save(buffer, format="PNG")
        return buffer.getvalue()

    def mesh(self, cutout: bytes, seed: int, request: Mapping[str, Any]) -> StandInMesh:
        from PIL import Image

        del seed
        joints, ends, radii = request["joints"], request["ends"], request["radii"]
        points = np.vstack([np.stack(list(joints.values())), np.stack(list(ends.values()))])
        reach = max(radii.values())
        low, high = points.min(axis=0) - reach, points.max(axis=0) + reach
        voxel = float((high - low).max()) / self.cells
        shape = tuple(int(n) for n in np.ceil((high - low) / voxel))
        centres = low + (np.indices(shape).reshape(3, -1).T + 0.5) * voxel
        inside = np.zeros(len(centres), dtype=bool)
        for bone, joint in joints.items():
            end = ends[bone]
            along = end - joint
            t = np.clip((centres - joint) @ along / max(float(along @ along), 1e-12), 0.0, 1.0)
            near = np.linalg.norm(centres - (joint + t[:, None] * along), axis=1)
            inside |= near <= max(radii[bone], voxel)
        positions, triangles = voxel_surface(inside.reshape(shape), low, voxel)
        # The slot frame (x across, y forward, z up) as TRELLIS's, whose front is -Y: x and y turn
        # half way round; then into a unit box, as TRELLIS's structure is.
        trellis = np.stack([-positions[:, 0], -positions[:, 1], positions[:, 2]], axis=1)
        box_low, box_high = trellis.min(axis=0), trellis.max(axis=0)
        trellis = (trellis - (box_low + box_high) / 2) / float((box_high - box_low).max())
        rgba = np.asarray(Image.open(io.BytesIO(cutout)).convert("RGBA"))
        shown = rgba[..., 3] > 0
        colour = rgba[..., :3][shown].mean(axis=0) if shown.any() else np.full(3, 128.0)
        colours = np.tile(np.rint(colour).astype(np.uint8), (len(trellis), 1))
        return StandInMesh(Mesh(trellis, triangles, colours))

    def runtime(self) -> dict[str, Any]:
        return {
            "machine": platform.platform(),
            "models": "stand-in",
            "python": platform.python_version(),
        }
