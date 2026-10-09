"""A creator uploads their own style pack over HTTP, and it is checked, served and withdrawn.

The app runs as a provisioned runtime role (not the owner, no BYPASSRLS), as deployed, over two
workspaces. The upload is the committed cozy pack re-labelled as a creator's own
(``style_pack_upload_support``). Each body the route refuses states its status and code by hand.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.db.roles import provision_runtime_role
from exulanica.db.session import Database
from exulanica.store.local import LocalContentAddressedStore
from exulanica.store.namespaces import LocalWorkspaceStores
from exulanica.world.style_pack_checks import (
    CheckOutcome,
    StylePackCheckWorker,
    colour_table,
    library_palettes,
)
from exulanica.world.style_pack_library import style_pack_library
from exulanica.world.workspace_style_packs import WorkspaceStylePackRuntime
from fastapi.testclient import TestClient

from conftest import scratch_role_database
from style_pack_upload_support import Upload, upload
from tests_support_api import EVERY_PERMISSION

pytestmark = pytest.mark.postgres

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROLE = "exulanica_workspace_style_pack_suite"
OWNER_TOKEN = "workspace-style-pack-owner-token-long-enough-for-tests"
STRANGER_TOKEN = "workspace-style-pack-stranger-token-long-enough-for-tests"


@dataclass
class PacksApi:
    client: TestClient
    database: Database
    stores: LocalWorkspaceStores
    owner: uuid.UUID
    stranger: uuid.UUID

    def headers(self, who: str = "owner") -> dict[str, str]:
        return {"Authorization": f"Bearer {OWNER_TOKEN if who == 'owner' else STRANGER_TOKEN}"}

    def send(self, made: Upload, *, who: str = "owner", declaration: bytes | None = None) -> Any:
        files: list[tuple[str, Any]] = [
            (
                "declaration",
                (None, made.declaration_bytes() if declaration is None else declaration),
            ),
            ("manifest", (None, made.manifest_bytes)),
        ]
        files.extend((path, (path.rsplit("/", 1)[-1], data)) for path, data in made.files.items())
        return self.client.post("/workspace-style-packs", headers=self.headers(who), files=files)

    def raw(self, body: bytes, content_type: str) -> httpx.Response:
        return self.client.post(
            "/workspace-style-packs",
            headers={**self.headers(), "Content-Type": content_type},
            content=body,
        )

    def get(self, path: str, who: str = "owner") -> httpx.Response:
        return self.client.get(path, headers=self.headers(who))

    def check(self) -> CheckOutcome:
        return StylePackCheckWorker(
            self.database,
            self.stores,
            frozenset({self.owner, self.stranger}),
            table=colour_table(ROOT),
            library=library_palettes,
        ).drain()


def _api(repository: Any, spine_schema: Any, tmp_path: Path, **bounds: int) -> Iterator[PacksApi]:
    _psycopg, scratch = spine_schema
    admin = repository.connection
    provision_runtime_role(admin, role=RUNTIME_ROLE)
    admin.commit()
    database = scratch_role_database(scratch, RUNTIME_ROLE)
    owner, stranger = repository.workspace_id, uuid.uuid4()
    grants = {
        OWNER_TOKEN: {
            "workspace_id": str(owner),
            "actor": str(uuid.uuid4()),
            "permissions": EVERY_PERMISSION,
        },
        STRANGER_TOKEN: {
            "workspace_id": str(stranger),
            "actor": str(uuid.uuid4()),
            "permissions": EVERY_PERMISSION,
        },
    }
    stores = LocalWorkspaceStores(tmp_path / "workspace-style-packs")
    services = Services(
        database=database,
        readonly_database=database,
        store=LocalContentAddressedStore(tmp_path / "blobs"),
        tokens=load_token_directory({"EXULANICA_API_TOKENS": json.dumps(grants)}),
        executor_shares_the_write_role=True,
        model_client=None,
        workspace_style_packs=WorkspaceStylePackRuntime.over(stores, **{"uploads": True, **bounds}),
    )
    app = create_app(services, verify=False)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield PacksApi(client, database, stores, owner, stranger)


@pytest.fixture
def api(repository, spine_schema, tmp_path) -> Iterator[PacksApi]:
    yield from _api(repository, spine_schema, tmp_path)


#: Written out by hand, not read from the route's constant, so a header dropped there fails here.
_EXPECTED_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; sandbox",
    "Cache-Control": "private, no-store",
    "Cross-Origin-Resource-Policy": "same-origin",
}


def _sends_content_headers(response: httpx.Response) -> None:
    for name, value in _EXPECTED_HEADERS.items():
        assert response.headers.get(name) == value, (name, response.status_code)
    assert response.headers.get("Content-Disposition", "").startswith("attachment")


def test_an_upload_is_admitted_checked_listed_and_served(api: PacksApi):
    made = upload()
    first = api.send(made)
    assert first.status_code == 201, first.text
    _sends_content_headers(first)
    digest = first.json()["manifest_sha256"]
    assert (first.json()["state"], first.json()["ready"]) == ("requested", False)
    assert api.send(made).status_code == 200

    outcome = api.check()
    assert (outcome.ready, outcome.errors) == (1, []), outcome
    version = api.get(f"/workspace-style-packs/{digest}")
    assert version.status_code == 200 and version.json()["ready"]
    assert version.json()["manifest"] == made.manifest
    listing = api.get("/world/style-packs").json()
    assert [pack["source"] for pack in listing["packs"]] == ["library"] * len(listing["packs"])
    assert [pack["manifest_sha256"] for pack in listing["workspace_packs"]] == [digest]

    bus = next(file for file in made.manifest["files"] if file["path"] == "pieces/bus.glb")
    served = api.get(f"/workspace-style-packs/{digest}/files/{bus['sha256']}")
    assert served.status_code == 200
    assert served.content == made.files["pieces/bus.glb"]
    assert served.headers["content-type"] == "model/gltf-binary"
    _sends_content_headers(served)
    assert api.get(f"/workspace-style-packs/{digest}/files/{'0' * 64}").status_code == 404


def test_another_workspace_answers_as_for_a_digest_never_made(api: PacksApi):
    made = upload()
    digest = api.send(made).json()["manifest_sha256"]
    api.check()
    bus = made.manifest["files"][0]["sha256"]
    for path in (
        f"/workspace-style-packs/{digest}",
        f"/workspace-style-packs/{digest}/files/{bus}",
    ):
        theirs, invented = api.get(path, "stranger"), api.get(path.replace(digest, "f" * 64))
        assert (theirs.status_code, theirs.json()["code"]) == (404, "unknown_reference")
        assert (invented.status_code, invented.json()) == (theirs.status_code, theirs.json())
        _sends_content_headers(theirs)
    assert api.get("/world/style-packs", "stranger").json()["workspace_packs"] == []


def test_a_withdrawn_version_is_neither_listed_nor_served(api: PacksApi):
    made = upload()
    digest = api.send(made).json()["manifest_sha256"]
    api.check()
    withdrawn = api.client.post(f"/workspace-style-packs/{digest}/withdraw", headers=api.headers())
    assert withdrawn.status_code == 200 and withdrawn.json()["withdrew"] is True
    bus = made.manifest["files"][0]["sha256"]
    gone = api.get(f"/workspace-style-packs/{digest}/files/{bus}")
    assert (gone.status_code, gone.json()["code"]) == (410, "withdrawn")
    _sends_content_headers(gone)
    assert api.get("/world/style-packs").json()["workspace_packs"] == []


def test_a_version_not_yet_checked_is_not_served(api: PacksApi):
    made = upload()
    digest = api.send(made).json()["manifest_sha256"]
    bus = made.manifest["files"][0]["sha256"]
    waiting = api.get(f"/workspace-style-packs/{digest}/files/{bus}")
    assert (waiting.status_code, waiting.json()["code"]) == (409, "style_pack_not_ready")
    assert api.get(f"/workspace-style-packs/{digest}").json()["manifest"] is None


def test_a_library_base_is_admitted_only_as_the_library_holds_it(api: PacksApi):
    """A version's library base is the library's, never text the creator chose: an id, version or
    digest the library does not hold is refused before anything is recorded."""
    cozy = style_pack_library().pack("exulanica.cozy-town")
    assert cozy is not None
    held = {
        "pack_id": cozy.pack_id,
        "version": cozy.version,
        "manifest_sha256": cozy.manifest_sha256,
    }
    for named in (
        {**held, "pack_id": "exulanica.nowhere"},
        {**held, "version": cozy.version + 1},
        {**held, "manifest_sha256": "0" * 64},
    ):
        made = upload("maker.cozy-coop")
        made.manifest["base"] = named
        refused = api.send(made)
        assert (refused.status_code, refused.json()["code"], refused.json()["path"]) == (
            422,
            "style_pack_base_unavailable",
            "base",
        ), named
    assert api.get("/workspace-style-packs").json()["versions"] == []
    made = upload("maker.cozy-coop")
    made.manifest["base"] = held
    admitted = api.send(made)
    assert admitted.status_code == 201, admitted.text
    assert admitted.json()["base"] == {"source": "library", **held}


def _multipart(*parts: bytes) -> bytes:
    return b"".join(b"--b\r\n" + part + b"\r\n" for part in parts) + b"--b--\r\n"


def test_every_body_the_route_does_not_take_is_refused_by_name(api: PacksApi):
    made = upload()
    declaration = b'Content-Disposition: form-data; name="declaration"\r\n\r\n' + (
        made.declaration_bytes()
    )
    manifest_field = (
        b'Content-Disposition: form-data; name="manifest"\r\n\r\n' + made.manifest_bytes
    )
    manifest_file = (
        b'Content-Disposition: form-data; name="manifest"; filename="manifest.json"\r\n\r\n'
        + made.manifest_bytes
    )
    nine = (
        b'Content-Disposition: form-data; name="declaration"\r\n'
        + b"".join(b"X-Header-%d: 1\r\n" % n for n in range(9))
        + b"\r\n"
        + made.declaration_bytes()
    )
    long_line = (
        b'Content-Disposition: form-data; name="declaration"\r\nX-Long: '
        + b"y" * 5000
        + b"\r\n\r\n"
        + made.declaration_bytes()
    )
    over = b'Content-Disposition: form-data; name="declaration"\r\n\r\n' + b" " * (300 * 1024)
    # Every file the manifest lists, so that in a case below the one fault is the one it names.
    every_file = [
        f'Content-Disposition: form-data; name="{path}"; filename="f"\r\n\r\n'.encode() + data
        for path, data in made.files.items()
    ]
    stranger = b'Content-Disposition: form-data; name="pieces/stowaway.glb"; filename="s"\r\n\r\nx'
    form = "multipart/form-data; boundary=b"
    cases = {
        "a url-encoded body": (
            b"declaration=x&manifest=y",
            "application/x-www-form-urlencoded",
            415,
        ),
        "a plain text body": (b"hello", "text/plain", 415),
        "a manifest sent as a file": (_multipart(declaration, manifest_file), form, 422),
        "a second declaration": (_multipart(declaration, declaration, manifest_field), form, 422),
        "a file sent twice": (
            _multipart(declaration, manifest_field, *every_file, every_file[0]),
            form,
            422,
        ),
        "nine part headers": (_multipart(nine, manifest_field), form, 422),
        "a 5,000-byte header line": (_multipart(long_line, manifest_field), form, 422),
        "a declaration over its bound": (_multipart(over, manifest_field), form, 422),
        "a file the manifest does not list": (
            _multipart(declaration, manifest_field, stranger),
            form,
            422,
        ),
    }
    for name, (body, content_type, status) in cases.items():
        response = api.raw(body, content_type)
        assert response.status_code == status, (name, response.text)
        _sends_content_headers(response)


def test_an_attempt_is_counted_before_the_body_is_read(repository, spine_schema, tmp_path):
    for limited in _api(repository, spine_schema, tmp_path, workspace_day_attempts=1):
        assert limited.raw(b"hello", "text/plain").status_code == 415
        refused = limited.send(upload())
        assert (refused.status_code, refused.json()["code"], refused.json()["bound"]) == (
            429,
            "style_pack_quota_exceeded",
            "workspace",
        )
        _sends_content_headers(refused)


def test_a_ready_version_downloads_as_the_same_tar_archive_every_time(api: PacksApi):
    import io
    import tarfile

    made = upload()
    digest = api.send(made).json()["manifest_sha256"]
    assert api.get(f"/workspace-style-packs/{digest}/archive").status_code == 409
    api.check()
    first = api.get(f"/workspace-style-packs/{digest}/archive")
    assert first.status_code == 200, first.text
    assert first.headers["content-type"] == "application/x-tar"
    assert first.headers["content-disposition"] == "attachment; filename=style-pack.tar"
    assert api.get(f"/workspace-style-packs/{digest}/archive").content == first.content
    with tarfile.open(fileobj=io.BytesIO(first.content)) as archive:
        members = archive.getmembers()
        assert [member.name for member in members] == [
            "manifest.json",
            *[file["path"] for file in made.manifest["files"]],
        ]
        assert {(m.mode, m.uid, m.gid, m.uname, m.gname, m.mtime) for m in members} == {
            (0o644, 0, 0, "", "", 0)
        }
        assert archive.extractfile("manifest.json").read() == made.manifest_bytes + b"\n"
        for path, data in made.files.items():
            assert archive.extractfile(path).read() == data, path
    assert api.get(f"/workspace-style-packs/{digest}/archive", "stranger").status_code == 404


def test_a_creator_asks_for_a_ready_version_to_be_published(api: PacksApi):
    made = upload()
    digest = api.send(made).json()["manifest_sha256"]
    path = f"/workspace-style-packs/{digest}/publish-request"
    body = {"licence_id": "CC0-1.0", "statement": "my own work, given to the library"}
    waiting = api.client.post(path, headers=api.headers(), json=body)
    assert (waiting.status_code, waiting.json()["code"]) == (409, "style_pack_not_ready")
    api.check()
    asked = api.client.post(path, headers=api.headers(), json=body)
    assert asked.status_code == 201, asked.text
    _sends_content_headers(asked)
    unattributed = api.client.post(
        path, headers=api.headers(), json={**body, "licence_id": "CC-BY-4.0"}
    )
    assert (unattributed.status_code, unattributed.json()["code"]) == (
        422,
        "invalid_publish_request",
    )
    theirs = api.client.post(path, headers=api.headers("stranger"), json=body)
    assert (theirs.status_code, theirs.json()["code"]) == (404, "unknown_reference")


def test_a_piece_coloured_outside_the_packs_palette_fails_its_check(api: PacksApi):
    from exulanica.world.style_pack_pieces import read_palette_piece

    made = upload()
    # One swatch a committed piece is coloured with takes a colour nothing uses: the manifest still
    # reads, and that piece no longer matches its palette.
    used = read_palette_piece(made.files["pieces/bus.glb"], colour_table(ROOT)).colours
    swatches = made.manifest["palette"]["swatches"]
    swatch = next(swatch for swatch in swatches if tuple(swatch["srgb8"]) in used)
    taken = {tuple(other["srgb8"]) for other in swatches}
    swatch["srgb8"] = next([r, 1, 7] for r in range(256) if (r, 1, 7) not in taken)
    digest = api.send(made).json()["manifest_sha256"]
    outcome = api.check()
    assert (outcome.ready, outcome.refused, outcome.errors) == (0, 1, []), outcome
    version = api.get(f"/workspace-style-packs/{digest}").json()
    assert (version["state"], version["failure"]["class"]) == ("failed", "refused")
    assert "no swatch of the pack's palette" in version["failure"]["message"]


def test_uploads_are_off_unless_the_installation_turns_them_on(repository, spine_schema, tmp_path):
    for closed in _api(repository, spine_schema, tmp_path, uploads=False):
        refused = closed.send(upload())
        assert (refused.status_code, refused.json()["code"]) == (503, "style_pack_uploads_off")
        _sends_content_headers(refused)
        # Reading stays open: an installation that took uploads before still serves what it holds.
        assert closed.get("/workspace-style-packs").status_code == 200
