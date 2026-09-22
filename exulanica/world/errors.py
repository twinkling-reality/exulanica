"""Failures at the protected world-style boundary.

Each class maps to a distinct API problem code.  Callers must be able to tell malformed style
data from optimistic-concurrency failures, topology protection, and missing bytes; flattening
them into one conflict would make the recovery action guesswork.
"""

from __future__ import annotations

from exulanica.errors import ExulanicaError

__all__ = [
    "EnvironmentBindingDrift",
    "EnvironmentCompositionDenied",
    "EnvironmentSourceWithdrawn",
    "InvalidEnvironmentData",
    "InvalidEnvironmentState",
    "InvalidInteractionData",
    "InvalidInteractionPreviewState",
    "InvalidObjectData",
    "InvalidObjectState",
    "InvalidPointMapPlacement",
    "InvalidPreviewState",
    "InvalidStructuralData",
    "InvalidStructuralPreviewState",
    "InvalidStyleData",
    "InvalidatedSourceVersion",
    "PointMapNotPermitted",
    "PointMapNotProduced",
    "PointMapNotReadable",
    "PointMapReviewDiffers",
    "PointMapTooSparse",
    "ProtectedTopologyConflict",
    "SourceAuthorityExpired",
    "SourceNotCurrentMembership",
    "StaleInteractionPolicy",
    "StaleObjectBase",
    "StaleStructuralBase",
    "StaleStyleVersion",
    "UnavailableAsset",
    "UnknownWorldResource",
    "WorldNotConfigured",
    "WorldStyleError",
]


class WorldStyleError(ExulanicaError):
    """Base class for errors owned by the world-style service."""


class InvalidStyleData(WorldStyleError):
    """A profile, parameter, scope, or provenance value is not in the reviewed contract."""


class StaleStyleVersion(WorldStyleError):
    """The caller based a mutation on a style version that is no longer current."""


class ProtectedTopologyConflict(WorldStyleError):
    """The protected topology changed after the proposal was created."""


class UnavailableAsset(WorldStyleError):
    """An authorised topology source slot exists but cannot currently supply bytes."""


class UnknownWorldResource(WorldStyleError):
    """A preview, version, or source slot is absent or belongs to another workspace."""


class InvalidPreviewState(WorldStyleError):
    """A preview is known but is not open and applicable."""


class WorldNotConfigured(WorldStyleError):
    """No protected topology has been registered for this workspace and world."""


class InvalidStructuralData(WorldStyleError):
    """A structural candidate is non-canonical, inconsistent, unsafe, or unsupported."""


class StaleStructuralBase(WorldStyleError):
    """A structural preview no longer names every protected current base."""


class InvalidStructuralPreviewState(WorldStyleError):
    """A structural preview is absent, closed, or otherwise cannot become current."""


class InvalidInteractionData(WorldStyleError):
    """An interaction capability, provenance record, explanation, or input is invalid."""


class StaleInteractionPolicy(WorldStyleError):
    """An interaction proposal no longer names the current policy and structural bases."""


class InvalidInteractionPreviewState(WorldStyleError):
    """An interaction preview is absent, closed, or otherwise cannot be applied."""


class InvalidObjectData(WorldStyleError):
    """An authored object's asset, region, transform, origin, or behaviour is not acceptable."""


class StaleObjectBase(WorldStyleError):
    """An object edit named a version state that another edit has already replaced."""


class InvalidObjectState(WorldStyleError):
    """The edit is well formed but the version cannot be in the state it would produce."""


class InvalidatedSourceVersion(WorldStyleError):
    """The alternate version's source snapshot was invalidated by a committed deletion."""


class InvalidEnvironmentData(WorldStyleError):
    """An environment source, selection, anchor, destination, or role is malformed."""


class InvalidEnvironmentState(WorldStyleError):
    """A valid environment edit cannot apply to the instance's current state."""


class EnvironmentCompositionDenied(WorldStyleError):
    """Current operation rights do not authorize this environment composition."""


class EnvironmentSourceWithdrawn(WorldStyleError):
    """A pinned source, render asset, or feature index has been withdrawn."""


class EnvironmentBindingDrift(WorldStyleError):
    """A feature placement no longer names the current exact publication."""


class SourceNotCurrentMembership(WorldStyleError):
    """The photograph is not currently a reference of this saved world.

    Distinct from an attachment nobody ever made: the recovery is to add it back, which needs a
    new review, and a message that said "no such attachment" would send the person looking for a
    typing mistake instead.
    """


class SourceAuthorityExpired(WorldStyleError):
    """The personal authority or the human review this reference pins has run out.

    Separate from a photograph that was never eligible: nothing is wrong with the photograph and
    the recovery is to review it again, which is a sentence a person can act on.
    """


class PointMapNotPermitted(WorldStyleError):
    """No current depth right lets this photograph's estimate be used."""


class PointMapNotProduced(WorldStyleError):
    """No depth estimate exists for the exact bytes and screening this reference pins."""


class PointMapReviewDiffers(WorldStyleError):
    """An estimate exists and was made under a different human review than this reference pins.

    Separate from :class:`PointMapNotProduced` because the recoveries differ and the cause is not
    the person's mistake: the worker builds from the newest eligible screening, so a photograph
    reviewed twice can have an estimate the current reference does not name.
    """


class PointMapTooSparse(WorldStyleError):
    """The estimate recovered too little of its frame to be worth standing in front of."""


class PointMapNotReadable(WorldStyleError):
    """The estimate's bytes are absent, or what stands behind them no longer allows a read."""


class InvalidPointMapPlacement(WorldStyleError):
    """The region, transform, origin role or instance id is not acceptable."""
