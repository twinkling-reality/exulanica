"""The generated tier: what a world model imagined, and the receipt that keeps it separate.

Roadmap Phase 10 capability 2. A generative world model asked to fill in the part of a kitchen no
photograph covered produces something plausible. That output is useful and it is not a record, and
the whole design problem is keeping those two facts attached to the same bytes forever.

The answer here is a tier, not a flag. Generated content is an artifact of its own kind, in its own
stage, below every recorded rung, and the receipt below is what travels with it. Four fields carry
the weight:

**The model, by identity and version.** Not a role. Roles (``vision``, ``depth``) name a slot the
platform routes through its own reviewed manifest, and a world model supplied per request is not
one of those. Recording ``model_role`` on this stage would also change the set of model-bearing
stages that the retained record ``docs/evaluation/2026-09-05-unblocked-goal-d.json`` is bound to,
and amending a retained record so a new field fits is the wrong direction of causation.

**The prompt digest.** The prompt is not stored. Its digest is, so a later reader can prove two
generations shared a prompt, or did not, without the prompt itself entering the corpus.

**The conditioning digests.** What the model was shown. Exactly one entry is required and checked:
the World Read bundle's ``recorded_sha256``, the digest over the observed world alone, which
``exulanica.ingest.generated_scene`` verifies against the scene's current value before storing
anything. That is what makes the tier falsifiable rather than decorative: "the model was
conditioned on the real scene" becomes something a recipient recomputes rather than reads.

Further entries may name individual artifacts the model was given, and nothing requires them or
checks them. A caller listing every point map it passed is recording more than the minimum; a
caller listing none has still bound itself to the bundle, which references those artifacts by
digest anyway.

**The seam.** One sentence naming, in words, where the record stops and the imagination starts.
Atlas draws it, and a receipt without it is refused, because a generated surface a viewer cannot
tell from a photographed one is the failure this whole product exists to avoid.

Everything in :func:`GeneratedSceneReceipt.document` is canonical-JSON safe, and
:func:`generation_input_digest` folds the model identity, prompt and conditioning into the value
the artifact's idempotency key is built from. That is what makes a model swap produce a different
artifact rather than silently reusing the previous one. The blob-subject stages get this property
from ``binding_digest``; scene-subject stages have no binding plumbing, and rather than extend
``_scene_key`` and bump its frozen format version for one stage, the identity goes where the scene
key already looks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final

from exulanica.canonical import canonical_json, sha256_of_canonical

__all__ = [
    "GENERATED_SCENE_KIND",
    "GENERATED_SCENE_PROFILE",
    "GENERATED_SCENE_STAGE",
    "ConditioningDigest",
    "GeneratedSceneReceipt",
    "GenerationModel",
    "generation_input_digest",
]

GENERATED_SCENE_PROFILE: Final = "exulanica.generated-scene/v1"

#: Spelled here as well as in the stage registry, for the same reason ``POINT_MAP_KIND`` is: the
#: layering contract forbids ``exulanica.graph`` and ``exulanica.reconstruction`` from importing
#: ``exulanica.ingest``, and a test pins the two spellings together.
GENERATED_SCENE_KIND: Final = "generated_scene"
GENERATED_SCENE_STAGE: Final = "generated_scene"

#: Containers a generated scene may arrive in. Deliberately the two the renderer already knows how
#: to draw and verify. A new container is a reviewed change to the renderer, not a string a caller
#: may invent, because a container nothing can validate is bytes the browser would have to trust.
GENERATED_CONTAINERS: Final = ("sog/1", "opm/2")

#: Roles a conditioning digest may declare. ``world-read-bundle`` is mandatory and is checked
#: separately: a generation that cannot name the bundle it read has no claim to have been
#: conditioned on this place at all.
CONDITIONING_ROLES: Final = (
    "world-read-bundle",
    "point_map",
    "trained_geometry",
    "pose_receipt",
    "photograph",
)

_SHA256: Final = re.compile(r"^[0-9a-f]{64}$")
_MIN_SEAM_CHARACTERS: Final = 24


def _text(value: str, field: str, *, minimum: int = 1) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    stripped = value.strip()
    if len(stripped) < minimum:
        raise ValueError(f"{field} must be at least {minimum} characters of actual content")
    return stripped


def _digest(value: str, field: str) -> str:
    if not isinstance(value, str) or not _SHA256.match(value):
        raise ValueError(f"{field} must be a lowercase hexadecimal SHA-256")
    return value


@dataclass(frozen=True, slots=True)
class GenerationModel:
    """Which model produced this, at which version, from which provider.

    All three are required and none is inferred. A generated artifact whose model nobody can name
    is indistinguishable from a hand-placed asset, and the tier's only value is that it can be
    named.
    """

    provider: str
    model_id: str
    model_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", _text(self.provider, "provider"))
        object.__setattr__(self, "model_id", _text(self.model_id, "model_id"))
        object.__setattr__(self, "model_version", _text(self.model_version, "model_version"))

    def document(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model_id": self.model_id,
            "model_version": self.model_version,
        }


@dataclass(frozen=True, slots=True)
class ConditioningDigest:
    """One exact thing the model was shown."""

    role: str
    sha256: str

    def __post_init__(self) -> None:
        if self.role not in CONDITIONING_ROLES:
            raise ValueError(
                f"conditioning role {self.role!r} is not one of {list(CONDITIONING_ROLES)}"
            )
        object.__setattr__(self, "sha256", _digest(self.sha256, f"conditioning[{self.role}]"))

    def document(self) -> dict[str, Any]:
        return {"role": self.role, "sha256": self.sha256}


@dataclass(frozen=True, slots=True)
class GeneratedSceneReceipt:
    """What a world model produced for one scene, and everything it was produced from."""

    model: GenerationModel
    prompt_sha256: str
    conditioning: tuple[ConditioningDigest, ...]
    container: str
    content_sha256: str
    byte_size: int
    seam: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "prompt_sha256", _digest(self.prompt_sha256, "prompt_sha256"))
        object.__setattr__(self, "content_sha256", _digest(self.content_sha256, "content_sha256"))
        if self.container not in GENERATED_CONTAINERS:
            raise ValueError(
                f"container {self.container!r} is not one of {list(GENERATED_CONTAINERS)}. A "
                "container the renderer cannot validate is bytes the browser would have to trust."
            )
        if not isinstance(self.byte_size, int) or self.byte_size <= 0:
            raise ValueError("byte_size must be a positive integer")
        if not self.conditioning:
            raise ValueError(
                "a generated scene must record what it was conditioned on. Without it, the claim "
                "that a model read the real place is a sentence rather than a checkable fact."
            )
        roles = [item.role for item in self.conditioning]
        if roles.count("world-read-bundle") != 1:
            raise ValueError(
                "a generated scene must name exactly one world-read-bundle digest: the bundle it "
                "actually read. Zero means it was conditioned on nothing verifiable here, and "
                "more than one means nobody can say which place it was shown."
            )
        if len({(item.role, item.sha256) for item in self.conditioning}) != len(self.conditioning):
            raise ValueError("conditioning digests must be distinct")
        object.__setattr__(self, "seam", _text(self.seam, "seam", minimum=_MIN_SEAM_CHARACTERS))

    @property
    def bundle_sha256(self) -> str:
        """The World Read bundle this generation was conditioned on."""
        return next(item.sha256 for item in self.conditioning if item.role == "world-read-bundle")

    def identity(self) -> dict[str, Any]:
        """The provenance of this generation: what produced it and what it was shown.

        Model, prompt and conditioning, and nothing about the output. This says whether two
        generations share an origin. It is deliberately NOT the artifact key: see
        :func:`generation_input_digest`, whose docstring records why using this as the key was
        wrong.
        """
        return {
            "profile": GENERATED_SCENE_PROFILE,
            "model": self.model.document(),
            "prompt_sha256": self.prompt_sha256,
            "conditioning": sorted(
                (item.document() for item in self.conditioning),
                key=lambda item: (item["role"], item["sha256"]),
            ),
        }

    def document(self) -> dict[str, Any]:
        """The full receipt, which is what the artifact's bytes are."""
        return {
            **self.identity(),
            "tier": "generated",
            "container": self.container,
            "content_sha256": self.content_sha256,
            "byte_size": self.byte_size,
            "seam": self.seam,
            "epistemics": {
                "citable": False,
                "promotes_rung": False,
                "is_evidence": False,
                "statement": (
                    "This surface was produced by a model, not observed by a camera. It supports "
                    "no claim, satisfies no reconstruction gate, and carries no rung."
                ),
            },
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json(self.document())

    def digest(self) -> str:
        return sha256_of_canonical(self.document()).hex()


def generation_input_digest(receipt: GeneratedSceneReceipt) -> bytes:
    """The artifact ``input_digest`` for one generation: the whole receipt, not just its origin.

    This is the scene-subject equivalent of the blob-subject ``binding_digest``, whose docstring
    records why it exists: without it, swapping the model behind a stage would leave every artifact
    keyed as though nothing had changed and the corpus would never reprocess.

    **It covers the entire receipt document, and the first version's narrower key was a real
    defect.** That version hashed :meth:`identity` alone, on the reasoning that two runs of one
    model on one prompt and one bundle are the same generation attempt even though sampling makes
    their bytes differ. The reasoning is backwards. ADR-0017's whole point is that a sampled
    generation is not reproducible, so two runs are two artifacts, not one artifact seen twice.
    Under the narrow key the second run collided with the first, ``insert ... on conflict do
    nothing`` discarded it, its bytes were never written to the store, and the caller was handed a
    ``receipt_sha256`` naming bytes that do not exist anywhere.

    Hashing the document keeps idempotency where it belongs, on filing the identical receipt twice,
    and gives every distinct generation its own artifact.
    """
    return sha256_of_canonical(receipt.document())
