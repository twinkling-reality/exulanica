"""``exulanica.appearance-generation/v1``: how one model output was made, as a data object.

A generation record names everything a person needs to know what an output is and where it came
from: every weights component by role (each an ``exulanica.appearance-weights/v1`` digest, and the
digest of the list, which is what a model-made maker names), the code by commit and source digest,
the container by digest, every conditioning picture by the sha256 of its raw pixels and of the file
the model read and the structure or recipe it was derived from, the prompt, the seed, the sampler
and every setting, whether guardrails ran, the GPU and library versions, and every output by digest.

**Every fixed value carries its reason.** The reader refuses a record whose ``reasons`` do not give
exactly one reason for the seed, the inputs, the guardrails, the container, each component, each
conditioning role and each sampler setting.

**Stated plainly:** GPU generation is not bit-exact across hardware, drivers or library versions.
The stored output bytes are the artifact. Running a record again makes a new version with new
digests; it is never a replay, and the record says so in its own words.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Final

from exulanica_appearance.canonical import (
    Refused,
    canonical_bytes,
    exact_keys,
    is_count,
    is_revision,
    is_sha256,
    is_text,
    parse_canonical,
    sha256_hex,
)

__all__ = [
    "COMPONENTS_PROFILE",
    "GENERATION_PROFILE",
    "REGENERATION",
    "build_generation",
    "components_sha256",
    "read_generation",
    "required_reasons",
]

GENERATION_PROFILE: Final = "exulanica.appearance-generation/v1"
COMPONENTS_PROFILE: Final = "exulanica.appearance-components/v1"
REGENERATION: Final = (
    "GPU generation is not bit-exact across hardware, drivers or library versions. These output "
    "bytes are the artifact. Running this record again makes a new version with new digests; it "
    "is never a replay."
)
TRACKS: Final = ("frames", "texture")
_KEYS: Final = (
    "code",
    "components",
    "components_sha256",
    "conditioning",
    "container",
    "finished_at",
    "generated",
    "guardrails",
    "inputs",
    "outputs",
    "profile",
    "reasons",
    "regeneration",
    "runtime",
    "sampler",
    "seed",
    "started_at",
    "track",
    "truth",
)
_KEY: Final = re.compile(r"[a-z][a-z0-9_]*")
_ROLE: Final = re.compile(r"[a-z][a-z0-9_-]*")
_IMAGE: Final = re.compile(r"[a-z0-9][a-z0-9._/:-]*@sha256:[0-9a-f]{64}")
_MEDIA: Final = re.compile(r"[a-z]+/[a-z0-9.+-]+")
_INSTANT: Final = "%Y-%m-%dT%H:%M:%SZ"


def components_sha256(components: Sequence[Mapping[str, str]]) -> str:
    """The one digest that names every weights component of a generation, by role."""
    listing = sorted(
        (
            {"role": c["role"], "subfolder": c["subfolder"], "weights_sha256": c["weights_sha256"]}
            for c in components
        ),
        key=lambda item: item["role"],
    )
    return sha256_hex(canonical_bytes({"components": listing, "profile": COMPONENTS_PROFILE}))


def required_reasons(document: Mapping[str, Any]) -> set[str]:
    """Exactly the reason keys a record with these fields must carry."""
    keys = {"container", "guardrails", "inputs", "seed"}
    keys |= {f"components.{item['role']}" for item in document["components"]}
    keys |= {f"conditioning.{item['role']}" for item in document["conditioning"]}
    keys |= {f"sampler.{key}" for key in document["sampler"]}
    return keys


def _settings(value: object) -> bool:
    return isinstance(value, dict) and all(
        isinstance(key, str)
        and _KEY.fullmatch(key)
        and (
            (is_count(item) or (isinstance(item, int) and not isinstance(item, bool)))
            or is_text(item)
        )
        for key, item in value.items()
    )


def _instant(value: object, where: str) -> datetime:
    if not isinstance(value, str):
        raise Refused(f"{where} is a UTC instant, YYYY-MM-DDTHH:MM:SSZ")
    try:
        return datetime.strptime(value, _INSTANT).replace(tzinfo=UTC)
    except ValueError as error:
        raise Refused(f"{where} is a UTC instant, YYYY-MM-DDTHH:MM:SSZ") from error


def build_generation(document: Mapping[str, Any]) -> bytes:
    """Canonical bytes for a record; ``components_sha256`` and ``regeneration`` are filled in."""
    full = dict(document)
    full["components"] = sorted(full["components"], key=lambda item: item["role"])
    full["conditioning"] = sorted(full["conditioning"], key=lambda item: item["role"])
    full["outputs"] = sorted(full["outputs"], key=lambda item: item["role"])
    full["components_sha256"] = components_sha256(full["components"])
    full["regeneration"] = REGENERATION
    raw = canonical_bytes(full)
    read_generation(raw)
    return raw


def read_generation(raw: bytes) -> dict[str, Any]:
    where = "the generation record"
    document = exact_keys(parse_canonical(raw, where), _KEYS, where)
    if document["profile"] != GENERATION_PROFILE:
        raise Refused(f"{where}: profile is {GENERATION_PROFILE}")
    if document["truth"] != "invented" or document["generated"] is not True:
        raise Refused(
            f"{where}: truth is invented and generated is true; it is never evidence about a place"
        )
    if document["track"] not in TRACKS:
        raise Refused(f"{where}: track is one of {', '.join(TRACKS)}")
    if document["regeneration"] != REGENERATION:
        raise Refused(f"{where}: regeneration states that a rerun is a new version, never a replay")

    components = document["components"]
    if not isinstance(components, list) or not components:
        raise Refused(f"{where}: components lists at least one weights component")
    roles = []
    for item in components:
        entry = exact_keys(item, ("role", "subfolder", "weights_sha256"), f"{where}: component")
        if not isinstance(entry["role"], str) or not _ROLE.fullmatch(entry["role"]):
            raise Refused(f"{where}: a component role is lowercase")
        if not isinstance(entry["subfolder"], str) or (
            entry["subfolder"] and not is_text(entry["subfolder"])
        ):
            raise Refused(f"{where}: a component subfolder is empty or a repository path")
        if not is_sha256(entry["weights_sha256"]):
            raise Refused(f"{where}: a component names its weights manifest by sha256")
        roles.append(entry["role"])
    if roles != sorted(set(roles)):
        raise Refused(f"{where}: components are sorted by role, each once")
    if document["components_sha256"] != components_sha256(components):
        raise Refused(f"{where}: components_sha256 is the digest of the components listing")

    code = exact_keys(document["code"], ("commit", "source_sha256"), f"{where}: code")
    if not is_revision(code["commit"]) or not is_sha256(code["source_sha256"]):
        raise Refused(f"{where}: code names a 40-hex commit and the sha256 of its source")
    container = exact_keys(document["container"], ("image",), f"{where}: container")
    if not isinstance(container["image"], str) or not _IMAGE.fullmatch(container["image"]):
        raise Refused(f"{where}: container image is pinned by sha256 digest")

    conditioning = document["conditioning"]
    if not isinstance(conditioning, list):
        raise Refused(f"{where}: conditioning is a list")
    order = []
    for item in conditioning:
        at = f"{where}: conditioning"
        entry = exact_keys(
            item, ("encoding", "file_sha256", "parameters", "pixels_sha256", "role", "sources"), at
        )
        if (
            not isinstance(entry["role"], str)
            or not _ROLE.fullmatch(entry["role"])
            or not is_text(entry["encoding"])
        ):
            raise Refused(f"{at}: each input has a lowercase role and its encoding's name")
        if not is_sha256(entry["file_sha256"]) or not is_sha256(entry["pixels_sha256"]):
            raise Refused(f"{at}: each input names its file and its raw pixels by sha256")
        sources = entry["sources"]
        if not isinstance(sources, list) or not sources or not all(is_sha256(s) for s in sources):
            raise Refused(
                f"{at}: each input names the structure or recipe records it came from, in order"
            )
        if not _settings(entry["parameters"]):
            raise Refused(f"{at}: parameters are integers and printable ASCII under lowercase keys")
        order.append(entry["role"])
    if order != sorted(set(order)):
        raise Refused(f"{where}: conditioning is sorted by role, each once")

    inputs = document["inputs"]
    prompt = isinstance(inputs, dict) and set(inputs) == {"prompt"} and is_text(inputs["prompt"])
    parameters = (
        isinstance(inputs, dict)
        and set(inputs) == {"parameters"}
        and _settings(inputs["parameters"])
        and bool(inputs["parameters"])
    )
    if not (prompt or parameters):
        raise Refused(f"{where}: inputs has exactly a prompt, or parameters")
    if not is_count(document["seed"]) or document["seed"] > 0xFFFFFFFF:
        raise Refused(f"{where}: seed is an unsigned 32-bit integer")
    sampler = document["sampler"]
    if not _settings(sampler) or not is_text(sampler.get("name")):
        raise Refused(f"{where}: sampler has a name and its settings, integers and printable ASCII")
    guardrails = exact_keys(document["guardrails"], ("enabled",), f"{where}: guardrails")
    if not isinstance(guardrails["enabled"], bool):
        raise Refused(f"{where}: guardrails states whether guardrails ran, true or false")

    runtime = exact_keys(
        document["runtime"], ("cuda", "driver", "hardware", "libraries"), f"{where}: runtime"
    )
    if not all(is_text(runtime[key]) for key in ("cuda", "driver", "hardware")):
        raise Refused(f"{where}: runtime names the hardware, the driver and the CUDA version")
    libraries = runtime["libraries"]
    names = []
    if not isinstance(libraries, list) or not libraries:
        raise Refused(f"{where}: runtime lists at least one library")
    for item in libraries:
        entry = exact_keys(item, ("name", "version"), f"{where}: runtime library")
        if not is_text(entry["name"]) or not is_text(entry["version"]):
            raise Refused(f"{where}: a library is a name and its version")
        names.append(entry["name"])
    if names != sorted(set(names)):
        raise Refused(f"{where}: libraries are sorted by name, each once")

    outputs = document["outputs"]
    if not isinstance(outputs, list) or not outputs:
        raise Refused(f"{where}: outputs lists at least one output")
    output_roles = []
    for item in outputs:
        entry = exact_keys(
            item, ("byte_length", "media_type", "role", "sha256"), f"{where}: output"
        )
        if (
            not isinstance(entry["role"], str)
            or not _ROLE.fullmatch(entry["role"])
            or not isinstance(entry["media_type"], str)
            or not _MEDIA.fullmatch(entry["media_type"])
            or not is_sha256(entry["sha256"])
            or not is_count(entry["byte_length"], 1)
        ):
            raise Refused(f"{where}: an output is a role, a media type, a sha256 and a byte length")
        output_roles.append(entry["role"])
    if output_roles != sorted(set(output_roles)):
        raise Refused(f"{where}: outputs are sorted by role, each once")

    started = _instant(document["started_at"], f"{where}: started_at")
    finished = _instant(document["finished_at"], f"{where}: finished_at")
    if finished < started:
        raise Refused(f"{where}: finished_at is not before started_at")

    reasons = document["reasons"]
    expected = required_reasons(document)
    if not isinstance(reasons, dict) or set(reasons) != expected:
        missing = sorted(expected - set(reasons)) if isinstance(reasons, dict) else sorted(expected)
        extra = sorted(set(reasons) - expected) if isinstance(reasons, dict) else []
        raise Refused(
            f"{where}: reasons give exactly one reason per fixed value; missing {missing}, unexpected {extra}"
        )
    if not all(is_text(text) for text in reasons.values()):
        raise Refused(f"{where}: every reason is printable ASCII")
    return document
