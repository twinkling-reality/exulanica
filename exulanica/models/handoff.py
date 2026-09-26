"""Which models one call can reach, and where the bytes it carries go.

A model identity is stated the way the manifest states it: a provider, a role, an identifier and,
for a checkpoint this codebase runs itself, the full commit it is pinned to. A hosted provider
exposes no per-model revision, so a hosted identity carries none rather than an invented one.

A hand-over is every identity one call can reach plus the one destination the bytes travel to. A
hosted role names its whole chain, because the client falls back on a withdrawn identifier and
either model can receive the same request. The destination is ``local-process`` for a checkpoint
loaded in this process, or the exact origin the egress allowlist would have to declare, spelled
as :class:`exulanica.models.egress.Origin` spells it.

These are plain values with no knowledge of storage, evidence or the database, which is why they
live beside the manifest: a component in any layer can state what it is about to call, and the
component that decides whether it may, ``exulanica.ingest.model_rights``, compares the statement
with a stored right.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final

from exulanica.models.egress import declared_origin
from exulanica.models.manifest import Manifest, Role

__all__ = [
    "LOCAL_PROCESS",
    "LOCAL_PROVIDER",
    "ModelHandoff",
    "ModelIdentity",
    "canonical_destination",
    "egress_origin",
]

#: The provider of a checkpoint this codebase loads and runs itself.
LOCAL_PROVIDER: Final = "local"
#: The destination of bytes that never leave this process.
LOCAL_PROCESS: Final = "local-process"

_NAME: Final = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_MODEL_ID: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
_REVISION: Final = re.compile(r"^[0-9a-f]{40}$")


#: The origin the egress allowlist would have to declare for a URL, in its one spelling. The
#: function lives beside the allowlist, so the manifest derives a provider's origin with it too.
egress_origin = declared_origin


def canonical_destination(value: str) -> str:
    """``local-process``, or the one spelling of the origin ``value`` names."""
    return value if value == LOCAL_PROCESS else egress_origin(value)


@dataclass(frozen=True, slots=True)
class ModelIdentity:
    """One model as the manifest states it.

    ``revision`` is a full lowercase commit for a local checkpoint and ``None`` for a hosted model
    whose provider exposes none. A hosted identity with ``None`` never matches a right that names a
    revision, and the reverse, so the two cannot stand in for each other.
    """

    provider: str
    role: str
    model_id: str
    revision: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.provider, str) or not _NAME.fullmatch(self.provider):
            raise ValueError(f"model provider {self.provider!r} is not a provider key")
        if not isinstance(self.role, str) or not _NAME.fullmatch(self.role):
            raise ValueError(f"model role {self.role!r} is not a role name")
        if not isinstance(self.model_id, str) or not _MODEL_ID.fullmatch(self.model_id):
            raise ValueError(f"model identifier {self.model_id!r} is not an identifier")
        if self.revision is not None and (
            not isinstance(self.revision, str) or not _REVISION.fullmatch(self.revision)
        ):
            raise ValueError(f"{self.model_id} revision must be a full lowercase commit")
        if self.provider == LOCAL_PROVIDER and self.revision is None:
            raise ValueError(f"local checkpoint {self.model_id} must be pinned to a full commit")

    @classmethod
    def local(cls, role: str, model_id: str, revision: str) -> ModelIdentity:
        return cls(provider=LOCAL_PROVIDER, role=role, model_id=model_id, revision=revision)

    @property
    def ref(self) -> str:
        """``model@revision`` when pinned, the bare identifier otherwise."""
        return self.model_id if self.revision is None else f"{self.model_id}@{self.revision}"

    def as_record(self) -> dict[str, str | None]:
        return {
            "provider": self.provider,
            "role": self.role,
            "model_id": self.model_id,
            "revision": self.revision,
        }


@dataclass(frozen=True, slots=True)
class ModelHandoff:
    """Every model one hand-over can reach, and the one destination the bytes travel to.

    A hand-over needs a right for each identity. ``destination`` is :data:`LOCAL_PROCESS` or an
    origin, normalised on construction; bytes that stay in this process can only reach local
    checkpoints.
    """

    identities: tuple[ModelIdentity, ...]
    destination: str

    def __post_init__(self) -> None:
        identities = tuple(self.identities)
        if not identities or not all(isinstance(item, ModelIdentity) for item in identities):
            raise ValueError("a model hand-over names at least one model identity")
        if len(set(identities)) != len(identities):
            raise ValueError("a model hand-over names each model once")
        destination = canonical_destination(self.destination)
        if destination == LOCAL_PROCESS and any(
            item.provider != LOCAL_PROVIDER for item in identities
        ):
            raise ValueError("bytes kept in this process can only reach local checkpoints")
        object.__setattr__(self, "identities", identities)
        object.__setattr__(self, "destination", destination)

    @classmethod
    def local(cls, *identities: ModelIdentity) -> ModelHandoff:
        return cls(identities=identities, destination=LOCAL_PROCESS)

    @classmethod
    def hosted(cls, manifest: Manifest, role: Role | str) -> ModelHandoff:
        """A manifest role's whole chain, sent to the origin of the provider serving it.

        The chain rather than the primary: the client falls back on a withdrawn identifier, so
        either model can receive the same request, and a right for one is not a right for both.
        A role's chain stays on one provider, so the hand-over names one destination.
        """
        binding = manifest[role]
        return cls(
            identities=tuple(
                ModelIdentity(
                    provider=spec.provider,
                    role=str(binding.role),
                    model_id=spec.model_id,
                    revision=None,
                )
                for spec in binding.chain
            ),
            destination=manifest.provider(binding.provider).origin,
        )

    @classmethod
    def chosen(cls, manifest: Manifest, role: Role | str, model_id: str) -> ModelHandoff:
        """One model a world chose for a chosen role, sent to its provider's origin.

        A choice names one model and its calls have no fallback, so the hand-over names exactly
        that model. A model the manifest does not offer the role is refused by the manifest.
        """
        spec = manifest.offered(role, model_id)
        return cls(
            identities=(
                ModelIdentity(
                    provider=spec.provider,
                    role=str(Role(role)),
                    model_id=spec.model_id,
                    revision=None,
                ),
            ),
            destination=manifest.provider(spec.provider).origin,
        )

    def as_record(self) -> dict[str, Any]:
        return {
            "models": [identity.as_record() for identity in self.identities],
            "destination": self.destination,
        }
