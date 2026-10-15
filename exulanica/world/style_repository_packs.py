"""The style packs a world's style proposal may name, and the pack each binding resolves to.

A part of :class:`~exulanica.world.repository.WorldStyleRepository` (its methods read the
repository's connection, workspace and style pack store): whether the workspace's library holds a
pack, the pack a request names, the requirements a binding is held to (a library pack, a creator's
own pack, a setting), and the chain a binding resolves through.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from exulanica.db.read_check import lock_asset_reads_until_commit
from exulanica.world.errors import (
    InvalidStyleData,
)
from exulanica.world.models import (
    StylePackBinding,
    StyleProposal,
)
from exulanica.world.style_pack_library import (
    style_pack_context,
    style_pack_library,
)
from exulanica.world.style_packs import StylePackRefused
from exulanica.world.world_settings import CHAIN_MAXIMUM, SettingRefused, bound_setting


class StylePackReads:
    """The style pack reads of :class:`~exulanica.world.repository.WorldStyleRepository`."""

    def _library_holds(self, binding: StylePackBinding) -> bool:
        """Whether the library holds ``binding``'s pack at exactly its version and manifest, its
        current version or an earlier one it still serves."""
        library = self._style_packs if self._style_packs is not None else style_pack_library()
        return library.holds(binding.pack_id, binding.version, binding.manifest_sha256)

    def requested_pack(
        self,
        binding: StylePackBinding,
        *,
        setting: Any = None,
        setting_parts: Mapping[str, str] | None = None,
    ) -> StylePackBinding:
        """Resolve a request's exact identity in the library or this workspace's wearable packs.

        No request-supplied workspace or source selects the authority. Preview and apply still
        recheck availability under their write/asset locks; this read grants no later write.
        """
        if not self._library_holds(binding):
            binding = self._own_pack(replace(binding, source="workspace"), resolve=True)
            if not binding.wearable:
                raise InvalidStyleData(
                    f"style pack {binding.pack_id} version {binding.version} with manifest "
                    f"{binding.manifest_sha256} is not an available pack of this host's library "
                    "or this workspace"
                )
        chain = self._pack_chain(binding)
        if chain is None:
            raise InvalidStyleData("the style pack's complete manifest chain is unavailable")
        try:
            selected = bound_setting(
                chain, style_pack_context(), document=setting, chosen=setting_parts
            )
        except (SettingRefused, StylePackRefused) as refused:
            raise InvalidStyleData(f"the world's setting is refused: {refused}") from refused
        return replace(binding, setting=selected)

    def _require_library_pack(self, binding: StylePackBinding) -> None:
        if not self._library_holds(binding):
            raise InvalidStyleData(
                f"style pack {binding.pack_id} version {binding.version} with manifest "
                f"{binding.manifest_sha256} is not a pack of this host's library"
            )

    def _require_pack(self, binding: StylePackBinding) -> None:
        """A pack new state may name: the library's at exactly that version and digest, or a version
        of this workspace's own pack, by its own id, version and digest, while it may be worn (the
        schema holds the same at insert). The appearance route resolves request identities against
        this workspace before these locked checks run again."""
        if binding.source == "library":
            self._require_library_pack(binding)
            self._require_setting(binding)
            return
        if binding.source == "workspace":
            # The last question before the write: no withdrawal commits between it and the commit.
            lock_asset_reads_until_commit(
                self.connection, outside="a world names its own look only inside its write"
            )
        if binding.source != "workspace" or not self._own_pack(binding, resolve=True).wearable:
            raise InvalidStyleData(
                f"style pack {binding.pack_id} version {binding.version} with manifest "
                f"{binding.manifest_sha256} is not a version of this workspace's own pack that "
                "may be worn"
            )
        self._require_setting(binding)

    def _require_setting(self, binding: StylePackBinding) -> None:
        """A setting new state may name: one its pack, as the host holds it, can be drawn in. It is
        read and applied to the pack's manifests exactly as a page applies it
        (:func:`~exulanica.world.world_settings.bound_setting`), and must be stored as it reads,
        so the setting a version states is the one that was checked."""
        if binding.setting is None:
            return
        chain = self._pack_chain(binding)
        if chain is None:
            raise InvalidStyleData(
                f"the manifests of style pack {binding.pack_id} version {binding.version} are not "
                "all held here, so no setting can be checked against it"
            )
        try:
            checked = bound_setting(
                chain, style_pack_context(), document=json.loads(binding.setting)
            )
        except (SettingRefused, StylePackRefused) as refused:
            raise InvalidStyleData(f"the world's setting is refused: {refused}") from refused
        if checked != binding.setting:
            raise InvalidStyleData(
                "the world's setting is not stated as its canonical JSON, or changes nothing"
            )

    def _pack_chain(self, binding: StylePackBinding) -> tuple[Mapping[str, Any], ...] | None:
        """The manifest ``binding`` names and each base it is drawn on, nearest first: the
        library's, or this workspace's own versions down to the library version they end at."""
        library = self._style_packs if self._style_packs is not None else style_pack_library()
        if binding.source == "library":
            return library.chain(binding.manifest_sha256)
        found: list[Mapping[str, Any]] = []
        digest: str | None = binding.manifest_sha256
        while digest is not None and len(found) < CHAIN_MAXIMUM:
            held = library.chain(digest)
            if held is not None:
                return (*found, *held)
            row = self.connection.execute(
                "select manifest_canonical from workspace_style_pack_version "
                "where workspace_id = %s and manifest_sha256 = %s and erased_at is null",
                (self.workspace_id, digest),
            ).fetchone()
            if row is None or row["manifest_canonical"] is None:
                return None
            manifest = json.loads(bytes(row["manifest_canonical"]))
            found.append(manifest)
            digest = None if manifest["base"] is None else manifest["base"]["manifest_sha256"]
        return tuple(found) if digest is None and found else None

    def _resolved_pack(self, binding: StylePackBinding | None) -> StylePackBinding | None:
        """``binding`` with its base and whether it may be worn now, when it names this
        workspace's own pack and states neither yet; anything else as it is."""
        if binding is None or binding.source != "workspace" or binding.wearable is not None:
            return binding
        return self._own_pack(binding, resolve=True)

    def _own_pack(self, binding: StylePackBinding, *, resolve: bool) -> StylePackBinding:
        """``binding``, a version of this workspace's own pack, with the library version it is drawn
        on and, when ``resolve``, whether it may be worn now. A version drawn on another of the
        workspace's own versions states the library version at the end of its chain."""
        row = self.connection.execute(
            "select v.pack_id, v.version, b.base_pack_id, b.base_version, b.base_manifest_sha256, "
            "  case when %s then workspace_style_pack_wearable(v.workspace_id, v.manifest_sha256) "
            "  end as wearable "
            "from workspace_style_pack_version v "
            "left join lateral (select c.base_pack_id, c.base_version, c.base_manifest_sha256 "
            "  from workspace_style_pack_chain(v.workspace_id, v.manifest_sha256) w "
            "  join workspace_style_pack_version c on c.workspace_id = v.workspace_id "
            "   and c.manifest_sha256 = w.manifest_sha256 "
            "  where c.base_source = 'library' limit 1) b on true "
            "where v.workspace_id = %s and v.manifest_sha256 = %s and v.erased_at is null",
            (resolve, self.workspace_id, binding.manifest_sha256),
        ).fetchone()
        if row is None or (row["pack_id"], row["version"]) != (binding.pack_id, binding.version):
            return StylePackBinding(
                binding.pack_id,
                binding.version,
                binding.manifest_sha256,
                binding.source,
                wearable=False if resolve else None,
                setting=binding.setting,
            )
        base = (
            None
            if row["base_pack_id"] is None
            else StylePackBinding(
                row["base_pack_id"], row["base_version"], row["base_manifest_sha256"]
            )
        )
        if base is not None and not self._library_holds(base):
            base = None
        return StylePackBinding(
            binding.pack_id,
            binding.version,
            binding.manifest_sha256,
            binding.source,
            base=base,
            wearable=None if not resolve else bool(row["wearable"]),
            setting=binding.setting,
        )

    def _validate_proposal_style_pack(self, proposal: StyleProposal) -> None:
        """A proposal names a pack for the whole world, and only a pack the library holds."""
        if not proposal.style_pack_stated:
            return
        if proposal.scope.kind != "global":
            raise InvalidStyleData(
                "a style pack dresses the whole world; a regional proposal names none"
            )
        if proposal.style_pack is not None:
            self._require_pack(proposal.style_pack)
