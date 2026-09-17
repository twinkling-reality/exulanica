"""What this lane hands the texture lane: a candidate set, with the fields a maker manifest carries.

The texture lane decided the model-made maker's shape (its answers to Q4, accepted by the
orchestrator on 2026-09-17), and this module builds exactly that from a generation record:

- **models**: a sorted list of one entry per role, each naming the model's id, its revision and its
  ``appearance-weights`` digest. The list itself travels, not one bundle digest, so a reader sees
  which models ran without fetching anything.
- **generation_sha256**: the ``appearance-generation`` record, named by digest, and beside it only
  the fields a reader checks (models, seed, sampler, map sources). The code commit and the container
  digest live in the record alone, and :func:`check_projection` compares the two so they cannot drift.
- **map_sources**: one entry per map of the class's procedural layout, each either the recipe it
  rebakes from or the generation that made it. A Track A set keeps the recipe's normal and occlusion,
  so those maps stay rebakeable by anyone with the maker; only the painted colour is unreproducible.
- **licence**: CC0-1.0 on the set, with the three statements the texture lane asked for, and the
  third-party look record that must exist before a set is pinned.

Nothing here publishes anything. The texture lane publishes, or does not.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final

from exulanica_appearance.canonical import (
    Refused,
    canonical_bytes,
    exact_keys,
    is_sha256,
    is_text,
    parse_canonical,
    sha256_hex,
)
from exulanica_appearance.generation import read_generation

__all__ = [
    "CANDIDATE_PROFILE",
    "PROCEDURAL_LAYOUT",
    "build_candidate",
    "check_projection",
    "licence_statements",
    "maker_generation",
    "read_candidate",
]

CANDIDATE_PROFILE: Final = "exulanica.appearance-texture-candidate/v1"
#: The procedural layout of each material class, in the container's stored order, from the texture
#: lane's proposal 1. A model-made Track A set keeps this layout and states each map's source.
PROCEDURAL_LAYOUT: Final = {
    "opaque": ("base_color", "normal", "orm"),
    "cutout": ("base_color_coverage", "normal", "orm"),
    "decal": ("base_color_coverage", "normal", "orm"),
    "glazing": ("base_color", "transmission_roughness"),
}


def maker_generation(
    record_raw: bytes, *, recipe_sha256: str, material_class: str, model_made: Sequence[str]
) -> dict[str, Any]:
    """The generation block a model-made maker manifest carries, projected from the record."""
    record = read_generation(record_raw)
    layout = PROCEDURAL_LAYOUT.get(material_class)
    if layout is None:
        raise Refused(f"{material_class!r} is not a material class with a stated procedural layout")
    unknown = [name for name in model_made if name not in layout]
    if unknown or not model_made:
        raise Refused(
            f"the model-made maps must be maps of the {material_class} layout; {unknown} are not"
        )
    if not is_sha256(recipe_sha256):
        raise Refused("the recipe the kept maps rebake from is named by sha256")
    return {
        "generation_sha256": sha256_hex(record_raw),
        "map_sources": {
            name: (
                {"generation_sha256": sha256_hex(record_raw)}
                if name in model_made
                else {"recipe_sha256": recipe_sha256}
            )
            for name in layout
        },
        "models": sorted(
            (
                {
                    "id": component["id"],
                    "revision": component["revision"],
                    "role": component["role"],
                    "weights_sha256": component["weights_sha256"],
                }
                for component in record["components"]
            ),
            key=lambda item: item["role"],
        ),
        "sampler": dict(record["sampler"]),
        "seed": record["seed"],
    }


def check_projection(block: Mapping[str, Any], record_raw: bytes) -> None:
    """Refuse a block that says anything its generation record does not."""
    record = read_generation(record_raw)
    if block.get("generation_sha256") != sha256_hex(record_raw):
        raise Refused("the block names another generation record")
    if block.get("seed") != record["seed"] or block.get("sampler") != record["sampler"]:
        raise Refused("the block's seed or sampler is not the record's")
    models = {
        (item["role"], item["id"], item["revision"], item["weights_sha256"])
        for item in block.get("models", [])
    }
    if models != {
        (c["role"], c["id"], c["revision"], c["weights_sha256"]) for c in record["components"]
    }:
        raise Refused("the block's models are not the record's components")
    for name, source in (block.get("map_sources") or {}).items():
        if set(source) not in ({"generation_sha256"}, {"recipe_sha256"}):
            raise Refused(f"map {name} states neither one recipe nor one generation as its source")
        if "generation_sha256" in source and source["generation_sha256"] != sha256_hex(record_raw):
            raise Refused(f"map {name} names another generation record")


def licence_statements(*, licence_ids: Sequence[str], third_party_look_sha256: str) -> list[str]:
    """The three statements the texture lane asked to travel with a CC0-1.0 model-made set."""
    if not is_sha256(third_party_look_sha256):
        raise Refused(
            "a set is not pinned before every map has been looked at: the look record is named by sha256"
        )
    unique = sorted(set(licence_ids))
    statements = [
        "Apache-2.0 and MIT place no condition on what a model's output may be used for, so the "
        "generated maps carry no obligation from the models that made them; every component's "
        "licence is named in its weights manifest at a pinned revision. This set's components: "
        + ", ".join(unique)
        + ".",
    ]
    if "OpenMDW-1.1" in unique:
        statements.append(
            "OpenMDW-1.1 is recorded as the generated appearance lane's reading, taken from the raw "
            "Hugging Face card data at the pinned revision, with the sha256 of the licence text read "
            "in the weights manifest. It places no restriction or obligation on outputs, and it has "
            "no guardrail clause; that reading is the lane's, not counsel's."
        )
    statements.append(
        "Before this set was pinned, every map was looked at at full resolution for recognisable "
        "third-party content (a logo, lettering, a mark). What was looked at and what was found is "
        f"in the third-party look record {third_party_look_sha256}; anything that might be such "
        "content went to the operator, who decides."
    )
    return statements


def build_candidate(
    *,
    record_raw: bytes,
    material_class: str,
    model_made: Sequence[str],
    source_set: Mapping[str, Any],
    maps: Mapping[str, Mapping[str, Any]],
    measurements: Mapping[str, Any],
    licence_ids: Sequence[str],
    third_party_look_sha256: str,
) -> bytes:
    """One candidate set, ready to hand over: what it is, how it was made, and what was measured."""
    block = maker_generation(
        record_raw,
        recipe_sha256=source_set["recipe_sha256"],
        material_class=material_class,
        model_made=model_made,
    )
    check_projection(block, record_raw)
    document = {
        "licence": {
            "id": "CC0-1.0",
            "statements": licence_statements(
                licence_ids=licence_ids, third_party_look_sha256=third_party_look_sha256
            ),
        },
        "maker_generation": block,
        "maps": {name: dict(value) for name, value in maps.items()},
        "material_class": material_class,
        "measurements": dict(measurements),
        "profile": CANDIDATE_PROFILE,
        "source_set": dict(source_set),
        "third_party_look_sha256": third_party_look_sha256,
        "truth": "invented",
    }
    raw = canonical_bytes(document)
    read_candidate(raw)
    return raw


def read_candidate(raw: bytes) -> dict[str, Any]:
    where = "the texture candidate"
    document = exact_keys(
        parse_canonical(raw, where),
        (
            "licence",
            "maker_generation",
            "maps",
            "material_class",
            "measurements",
            "profile",
            "source_set",
            "third_party_look_sha256",
            "truth",
        ),
        where,
    )
    if document["profile"] != CANDIDATE_PROFILE or document["truth"] != "invented":
        raise Refused(f"{where}: profile is {CANDIDATE_PROFILE} and truth is invented")
    if document["material_class"] not in PROCEDURAL_LAYOUT:
        raise Refused(f"{where}: material_class is one of {', '.join(PROCEDURAL_LAYOUT)}")
    licence = exact_keys(document["licence"], ("id", "statements"), f"{where}: licence")
    if (
        licence["id"] != "CC0-1.0"
        or len(licence["statements"]) < 2
        or not all(is_text(s) for s in licence["statements"])
    ):
        raise Refused(f"{where}: the set is CC0-1.0 and carries its statements")
    source = exact_keys(
        document["source_set"],
        ("content_sha256", "recipe_sha256", "set_id", "version"),
        f"{where}: source_set",
    )
    if not is_sha256(source["content_sha256"]) or not is_sha256(source["recipe_sha256"]):
        raise Refused(f"{where}: source_set names the set's bytes and its recipe by sha256")
    if not is_sha256(document["third_party_look_sha256"]):
        raise Refused(f"{where}: third_party_look_sha256 is 64 lowercase hex")
    layout = PROCEDURAL_LAYOUT[document["material_class"]]
    if tuple(sorted(document["maker_generation"]["map_sources"])) != tuple(sorted(layout)):
        raise Refused(
            f"{where}: map_sources covers exactly the {document['material_class']} layout"
        )
    if set(document["maps"]) - set(layout):
        raise Refused(f"{where}: maps are maps of the {document['material_class']} layout")
    return document
