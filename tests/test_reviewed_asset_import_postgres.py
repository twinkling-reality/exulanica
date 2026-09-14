from __future__ import annotations

import hashlib

import psycopg
import pytest
from exulanica.evidence.blob import BlobId
from exulanica.store.local import LocalContentAddressedStore
from exulanica.world.asset_import import import_reviewed_asset

from pg_harness import migrated_schema
from test_reviewed_asset_import import imported_fixture

pytestmark = pytest.mark.postgres


def test_import_is_atomic_idempotent_and_preserves_withdrawal(tmp_path):
    manifest, payload, licence = imported_fixture()
    # Use a different generated payload from the pre-seeded registry row while keeping valid GLB.
    payload = payload.replace(b"exulanica-reviewed-asset/1", b"exulanica-reviewed-asset/2")
    manifest = manifest.model_copy(update={"content_sha256": hashlib.sha256(payload).hexdigest()})
    store = LocalContentAddressedStore(tmp_path / "blobs")
    with migrated_schema() as (_, connection):
        with connection.transaction():
            receipt = import_reviewed_asset(connection, store, manifest, payload, licence)
        assert store.get(BlobId.from_hex(manifest.content_sha256)) == payload
        assert store.get(BlobId.from_hex(manifest.licence_sha256)) == licence
        assert store.get(BlobId.from_hex(receipt))
        with connection.transaction():
            assert import_reviewed_asset(connection, store, manifest, payload, licence) == receipt
        with (
            pytest.raises(ValueError, match="provenance cannot be rewritten"),
            connection.transaction(),
        ):
            import_reviewed_asset(
                connection,
                store,
                manifest.model_copy(update={"source_revision": "another"}),
                payload,
                licence,
            )
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            connection.execute(
                "delete from world_reviewed_asset_import where asset_key=%s",
                (manifest.asset_key,),
            )
        with connection.transaction():
            connection.execute(
                "delete from world_reviewed_asset where asset_key=%s", (manifest.asset_key,)
            )
        with pytest.raises(ValueError, match="withdrawn"), connection.transaction():
            import_reviewed_asset(connection, store, manifest, payload, licence)


def test_failed_publication_does_not_leave_a_registry_row(tmp_path):
    manifest, payload, licence = imported_fixture()
    payload = payload.replace(b"exulanica-reviewed-asset/1", b"exulanica-reviewed-asset/2")
    manifest = manifest.model_copy(update={"content_sha256": hashlib.sha256(payload).hexdigest()})
    store = LocalContentAddressedStore(tmp_path / "blobs")
    with migrated_schema() as (_, connection):
        with pytest.raises(RuntimeError, match="abort"), connection.transaction():
            import_reviewed_asset(connection, store, manifest, payload, licence)
            raise RuntimeError("abort")
        assert (
            connection.execute(
                "select 1 from world_reviewed_asset where asset_key=%s", (manifest.asset_key,)
            ).fetchone()
            is None
        )
        assert (
            connection.execute(
                "select 1 from world_reviewed_asset_import where asset_key=%s",
                (manifest.asset_key,),
            ).fetchone()
            is None
        )
