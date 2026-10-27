"""How a running instance builds the workers it runs beside its requests: drafts of kinds of place
and of worlds, model probes, creature drafts and reference reads.

Each builder reads the fields of :class:`~exulanica.api.services.Services` that say whether this
process runs that worker and with what, and returns the worker or None. Services inherits them, so
each is called as ``services.build_kind_draft_worker()`` as before. The builders of the playback,
comparison and derivative workers stay in :mod:`exulanica.api.services`, beside the names their
tests replace there.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from exulanica.api.kind_draft_worker import KindDraftWorker
from exulanica.api.reference_pictures import reference_picture_source
from exulanica.epistemics.hosted_requests import WorkspaceRequestPolicy, no_place_released
from exulanica.references.worker import ReferenceWorker
from exulanica.selection.creature_drafts import CreatureDraftWorker
from exulanica.world.model_probe_worker import ModelProbeWorker

if TYPE_CHECKING:
    from exulanica.api.world_draft_worker import WorldDraftWorker


class WorkerFactories:
    """The builders above, mixed into :class:`~exulanica.api.services.Services`, whose fields they
    read."""

    __slots__ = ()

    def build_kind_draft_worker(self) -> KindDraftWorker:
        """Native kind jobs remain readable without a provider; overdue work is scrubbed."""
        return KindDraftWorker(
            self.database,
            client=self.model_client if self.kinds_from_people else None,
            spending=self.spending,
            holder=self.kind_drafts,
            policy_for=lambda workspace: self.request_policy(
                workspace,
                lambda: self.readonly_database.session(workspace),
                released_places=no_place_released,
            ),
            workspaces=lambda: (
                (frozenset() if self.tokens is None else self.tokens.workspaces)
                | self.watched_workspaces()
            ),
        )

    def build_world_draft_worker(self) -> WorldDraftWorker | None:
        """The native world maker under durable job and spending authority."""
        if not self.kinds_from_people or self.model_client is None or self.spending is None:
            return None
        from exulanica.api.world_draft_worker import WorldDraftWorker

        return WorldDraftWorker(
            self.database,
            client=self.model_client,
            spending=self.spending,
            holder=self.kind_drafts,
            store=self.store,
            policy_for=lambda workspace: self.request_policy(
                workspace,
                lambda: self.readonly_database.session(workspace),
                released_places=no_place_released,
            ),
            workspaces=lambda: (
                (frozenset() if self.tokens is None else self.tokens.workspaces)
                | self.watched_workspaces()
            ),
            on_land=self.worlds_on_land,
        )

    def build_model_probe_worker(self) -> ModelProbeWorker | None:
        if (
            not self.runs_model_probe_worker
            or not self.model_probe_workspaces
            or self.model_client is None
            or self.spending is None
        ):
            return None

        def policy_for(workspace_id: uuid.UUID) -> WorkspaceRequestPolicy:
            return self.request_policy(
                workspace_id,
                lambda: self.readonly_database.session(workspace_id),
                released_places=no_place_released,
            )

        return ModelProbeWorker(
            self.database,
            client=self.model_client,
            spending=self.spending,
            policy_for=policy_for,
            workspaces=lambda: self.model_probe_workspaces,
        )

    def build_creature_worker(self) -> CreatureDraftWorker | None:
        """What drafts the creatures of the workspaces they are offered to, or None where this
        process has no model client, no looks namespace or no such workspace. Each draft's requests
        carry the workspace's rules, with no place's name released: a creature is not a use a
        place-name right offers."""
        if (
            self.model_client is None
            or self.content_stores is None
            or not (self.creature_workspaces or self.notes_and_creatures_for_everyone)
            or not self.runs_creature_worker
        ):
            return None
        readonly = self.readonly_database
        looks = self.content_stores.looks
        listed = self.creature_workspaces

        def policy_for(workspace_id: uuid.UUID) -> WorkspaceRequestPolicy:
            return self.request_policy(
                workspace_id,
                lambda: readonly.session(workspace_id),
                released_places=no_place_released,
            )

        from exulanica.api.reference_pictures import creature_picture_notes_authority

        return CreatureDraftWorker(
            self.database,
            client=self.model_client,
            policy_for=policy_for,
            looks_for=looks.for_workspace,
            workspaces=lambda: self.offered_workspaces(listed),
            picture_notes_authority=creature_picture_notes_authority(
                manifest=self.model_client.manifest,
                offered_to=self.pictures_offered_to,
            ),
        )

    def build_reference_worker(self) -> ReferenceWorker | None:
        """What plays the reference jobs of the workspaces web notes are offered to, or None
        where this process has no model client, no durable spending, no such workspace or no
        source configuration. Each job's requests carry the workspace's rules, with no place's
        name released: a search is not a use a place-name right offers."""
        if (
            self.model_client is None
            or self.spending is None
            or not (self.reference_workspaces or self.notes_and_creatures_for_everyone)
            or self.reference_adapter_for is None
            or not self.references_offered_here()
        ):
            return None
        database = self.database
        readonly = self.readonly_database
        listed = self.reference_workspaces

        def policy_for(workspace_id: uuid.UUID) -> WorkspaceRequestPolicy:
            # Saved names and rights are read on the read-only database, as a person's decisions
            # read them.
            return self.request_policy(
                workspace_id,
                lambda: readonly.session(workspace_id),
                released_places=no_place_released,
            )

        return ReferenceWorker(
            database,
            client=self.model_client,
            policy_for=policy_for,
            spending=self.spending,
            adapter_for=self.reference_adapter_for,
            workspaces=lambda: self.offered_workspaces(listed),
            # A person's own pictures are read only where pictures are turned on, from the
            # read-only database as the request policy reads rights.
            picture_source=(
                reference_picture_source(readonly.session, self.store)
                if self.picture_reading_here()
                else None
            ),
        )
