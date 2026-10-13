"""Human invitation withdrawals survive actual older database restores."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from exulanica.participation.contracts import notice_reference
from exulanica.participation.repository import InvitationRepository, ParticipationRefused
from exulanica.world.worlds import register_world

from test_purge import purged as purged
from test_restore_replay import _backup, _restore
from test_restore_replay_search_entries import _seal
from test_restore_replay_search_entries import commands as commands
from test_restore_replay_withdrawals import _replay

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("ending", ["revoke", "leave"])
def test_older_backup_cannot_revive_a_bound_human_invitation(purged, commands, tmp_path, ending):
    workspace, owner, visitor = purged.workspace_id, uuid.uuid4(), uuid.uuid4()
    world = f"world:generated:{uuid.uuid4()}"

    # The lifecycle test needs only the registered parent. Actual farm/society eligibility and
    # browser reads are proved separately in test_participation_postgres.
    def eligible(*_):
        return None

    with purged.database().session(workspace) as connection:
        register_world(
            connection,
            workspace,
            world_id=world,
            kind="generated",
            created_by=owner,
            reason="invitation restore fixture",
        )
        repository = InvitationRepository(connection, workspace)
        invitation = repository.issue(
            world,
            uuid.uuid4(),
            key=uuid.uuid4(),
            actor=owner,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            world_words="A garden",
            eligible=eligible,
        )
        grant = uuid.UUID(invitation["grant_id"])
        repository.redeem(
            grant,
            invitation["invitation"],
            visitor,
            notice_reference()["sha256"],
            eligible=eligible,
        )
        assert repository.scope(grant, visitor, eligible=eligible)
    # This adversarial raw dump retains entries too. Installation backup sets are stricter and
    # omit their rows, so even a still-active restored principal cannot authorize a visitor.
    dump, blobs = _backup(purged, tmp_path)
    with purged.database().session(workspace) as connection:
        repository = InvitationRepository(connection, workspace)
        if ending == "revoke":
            repository.revoke(grant, owner)
        else:
            repository.leave(grant, visitor, eligible=eligible)
        with pytest.raises(ParticipationRefused):
            repository.scope(grant, visitor, eligible=eligible)
    source, marker = _seal(tmp_path)
    _restore(purged, dump, blobs)
    with purged.database().session(workspace) as connection:
        assert InvitationRepository(connection, workspace).scope(grant, visitor, eligible=eligible)
    _replay(source, marker)
    with purged.database().session(workspace) as connection:
        repository = InvitationRepository(connection, workspace)
        with pytest.raises(ParticipationRefused):
            repository.scope(grant, visitor, eligible=eligible)
        assert repository.state(repository.row(grant)) == (
            "revoked" if ending == "revoke" else "departed"
        )
        if ending == "leave":
            assert not connection.execute(
                "select 1 from world_grant_principal where grant_id=%s", (grant,)
            ).fetchone()
            assert not connection.execute(
                "select 1 from world_grant_entry where grant_id=%s", (grant,)
            ).fetchone()
