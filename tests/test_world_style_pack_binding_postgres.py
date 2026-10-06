"""A world's appearance names the style pack it is drawn in, through preview, apply and rollback.

The packs are the committed library's; each expected binding is read from the committed manifest
file itself (its canonical JSON and one newline), not from the library loader the repository asks.
A library without the pack, given to the repository in its place, stands for a host that no longer
holds it.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import replace
from pathlib import Path

import pytest
from exulanica.world import (
    InvalidStyleData,
    ProposalOrigin,
    ProposalProvenance,
    StylePackBinding,
    StyleScope,
    WorldStyleRepository,
)
from exulanica.world.committed_content import CommittedContent
from exulanica.world.style_pack_library import StylePackLibrary

from test_world_style_postgres import fixture_styles, proposal, topology

pytestmark = pytest.mark.postgres

PACKS = Path(__file__).resolve().parents[1] / "assets" / "style-packs" / "packs"
#: A host whose library holds no pack at all.
EMPTY = StylePackLibrary(packs=(), content=CommittedContent(()))


def committed(pack_id: str) -> StylePackBinding:
    text = (PACKS / pack_id / "manifest.json").read_bytes()
    return StylePackBinding(
        pack_id, json.loads(text)["version"], hashlib.sha256(text[:-1]).hexdigest()
    )


def naming(current, pack: StylePackBinding | None, **more):
    """A proposal over ``current`` that names ``pack`` (None: no pack)."""
    return replace(proposal(current, **more), style_pack_stated=True, style_pack=pack)


def apply(styles: WorldStyleRepository, preview, base):
    return styles.apply(
        preview.preview_id,
        base_style_version_id=base.version_id,
        base_topology_digest="topology-a",
        applied_by=uuid.uuid4(),
    )


def test_a_named_pack_is_previewed_applied_and_kept_until_another_is_named(repository):
    styles = fixture_styles(repository)
    initial = styles.register_topology(topology())
    assert initial.style_pack is None
    cozy = committed("exulanica.cozy-town")

    previewed = styles.preview(naming(initial, cozy))
    assert previewed.candidate.style_pack == cozy
    assert styles.current().style_pack is None
    first = apply(styles, previewed, initial)
    assert first.style_pack == cozy
    assert styles.current().style_pack == cozy
    row = repository.connection.execute(
        "select style_pack_id,style_pack_version,style_pack_manifest_sha256 "
        "from world_style_version where version_id=%s",
        (first.version_id,),
    ).fetchone()
    assert (
        row["style_pack_id"],
        row["style_pack_version"],
        row["style_pack_manifest_sha256"],
    ) == (cozy.pack_id, cozy.version, cozy.manifest_sha256)

    # A proposal that names no pack keeps its base's.
    kept = apply(styles, styles.preview(proposal(first, parameters={"vitality": 0.6})), first)
    assert kept.style_pack == cozy
    assert kept.global_style.parameters["vitality"] == 0.6

    # One that names none clears it; one that names another changes it.
    cleared = apply(styles, styles.preview(naming(kept, None)), kept)
    assert cleared.style_pack is None
    toon = committed("exulanica.toon-town")
    changed = apply(styles, styles.preview(naming(cleared, toon)), cleared)
    assert changed.style_pack == toon
    assert [version.style_pack for version in styles.versions()] == [
        None,
        cozy,
        cozy,
        None,
        toon,
    ]


def test_a_proposal_records_the_pack_as_it_named_it(repository):
    styles = fixture_styles(repository)
    initial = styles.register_topology(topology())
    cozy = committed("exulanica.cozy-town")
    unnamed = styles.preview(proposal(initial))
    named = styles.preview(naming(initial, cozy))
    none = styles.preview(naming(initial, None))
    stored = {
        row["proposal_id"]: row["style_pack"]
        for row in repository.connection.execute(
            "select proposal_id,style_pack from world_style_proposal where proposal_id = any(%s)",
            (
                [
                    unnamed.proposal.proposal_id,
                    named.proposal.proposal_id,
                    none.proposal.proposal_id,
                ],
            ),
        ).fetchall()
    }
    assert stored[unnamed.proposal.proposal_id] is None
    assert stored[named.proposal.proposal_id] == {
        "pack": {
            "pack_id": cozy.pack_id,
            "version": cozy.version,
            "manifest_sha256": cozy.manifest_sha256,
        }
    }
    assert stored[none.proposal.proposal_id] == {"pack": None}
    read = {
        record.proposal.proposal_id: record.proposal
        for record in (
            styles.proposal(unnamed.proposal.proposal_id),
            styles.proposal(named.proposal.proposal_id),
            styles.proposal(none.proposal.proposal_id),
        )
    }
    assert (
        read[unnamed.proposal.proposal_id].style_pack_stated,
        read[unnamed.proposal.proposal_id].style_pack,
    ) == (False, None)
    assert (
        read[named.proposal.proposal_id].style_pack_stated,
        read[named.proposal.proposal_id].style_pack,
    ) == (True, cozy)
    assert (
        read[none.proposal.proposal_id].style_pack_stated,
        read[none.proposal.proposal_id].style_pack,
    ) == (True, None)


@pytest.mark.parametrize(
    "change",
    [
        {"pack_id": "exulanica.nowhere-town"},
        # A version the library does not hold: the committed one's next.
        {"version": committed("exulanica.cozy-town").version + 1},
        {"manifest_sha256": "0" * 64},
    ],
)
def test_a_pack_the_library_does_not_hold_is_refused_and_audited(repository, change):
    styles = fixture_styles(repository)
    initial = styles.register_topology(topology())
    asked = replace(committed("exulanica.cozy-town"), **change)
    refused = naming(initial, asked)
    with pytest.raises(InvalidStyleData, match="is not a pack of this host's library"):
        styles.preview(refused)
    row = repository.connection.execute(
        "select status,validation_issues,style_pack from world_style_proposal where proposal_id=%s",
        (refused.proposal_id,),
    ).fetchone()
    assert row["status"] == "rejected"
    assert row["validation_issues"] == ["invalid_style_data"]
    assert row["style_pack"]["pack"]["pack_id"] == asked.pack_id
    audited = repository.connection.execute(
        "select event_type from world_style_audit_event where proposal_id=%s",
        (refused.proposal_id,),
    ).fetchall()
    assert [event["event_type"] for event in audited] == ["proposal_rejected"]
    assert styles.current() == initial


@pytest.mark.parametrize("pack", [None, "exulanica.cozy-town"])
def test_a_regional_proposal_names_no_pack(repository, pack):
    styles = fixture_styles(repository)
    initial = styles.register_topology(topology())
    regional = naming(
        initial,
        None if pack is None else committed(pack),
        scope=StyleScope("region", "region-a"),
    )
    with pytest.raises(InvalidStyleData, match="a regional proposal names none"):
        styles.preview(regional)


def test_apply_and_rollback_refuse_a_pack_the_host_no_longer_holds(repository):
    styles = fixture_styles(repository)
    initial = styles.register_topology(topology())
    cozy = committed("exulanica.cozy-town")
    elsewhere = WorldStyleRepository(
        repository.connection,
        repository.workspace_id,
        world_id=styles.world_id,
        style_packs=EMPTY,
    )
    # Previewed while the host held the pack; applied after it stopped holding it.
    previewed = styles.preview(naming(initial, cozy))
    with pytest.raises(InvalidStyleData, match="is not a pack of this host's library"):
        apply(elsewhere, previewed, initial)
    assert styles.current() == initial
    first = apply(styles, previewed, initial)
    second = apply(styles, styles.preview(naming(first, None)), first)
    provenance = ProposalProvenance(ProposalOrigin.USER, uuid.uuid4())
    with pytest.raises(InvalidStyleData, match="is not a pack of this host's library"):
        elsewhere.rollback(
            first.version_id,
            base_style_version_id=second.version_id,
            base_topology_digest="topology-a",
            provenance=provenance,
        )
    assert styles.current().version_id == second.version_id
    restored = styles.rollback(
        first.version_id,
        base_style_version_id=second.version_id,
        base_topology_digest="topology-a",
        provenance=provenance,
    )
    assert restored.style_pack == cozy
    assert restored.rollback_target_version_id == first.version_id


def test_a_version_naming_a_pack_the_host_does_not_hold_reads_with_a_warning(repository):
    styles = fixture_styles(repository)
    initial = styles.register_topology(topology())
    cozy = committed("exulanica.cozy-town")
    applied = apply(styles, styles.preview(naming(initial, cozy)), initial)
    assert applied.warnings == ()
    elsewhere = WorldStyleRepository(
        repository.connection,
        repository.workspace_id,
        world_id=styles.world_id,
        style_packs=EMPTY,
    )
    read = elsewhere.current()
    assert read.style_pack == cozy
    assert any(cozy.pack_id in warning for warning in read.warnings)
