"""Exercise preparation integrity and workspace isolation without installing Blender."""

import json
import sys
import threading
from http.client import HTTPConnection
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
from parametric_character import inputs
from parametric_character import preview_server as server
from prepare_parametric_character import publish_default


@pytest.fixture
def preparation(tmp_path, monkeypatch):
    source = tmp_path / "source"
    family = tmp_path / "family"
    files = {
        source / "mpfb2/src/model.py": "pinned mesh source",
        source / "system-assets/clothes/suit.mhclo": "pinned garment",
        source / "mpfb2/LICENSE.ASSETS.md": "CC0 assets",
        source / "mpfb2/LICENSE.CODE.md": "GPL source",
        family / "LICENSE.md": "CC0 distributed assets",
        family / "hoodie.glb": "pinned motion bytes",
        family / "men-LICENSE.txt": "CC0 motion",
        family / "hoodie.import.json": "motion import receipt",
        family / "family.json": json.dumps(server.FAMILY),
        tmp_path / "blender": "pinned executable",
    }
    for path, contents in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)
    blender = tmp_path / "blender"
    state = SimpleNamespace(dirty="", version="Blender 4.5.9 LTS\nbuild hash: pinned-build\n")

    def output(command, **kwargs):
        if command[-1] == "HEAD":
            return "pinned-head\n"
        if command[-1] == "--untracked-files=all":
            return state.dirty
        assert command == [str(blender), "--version"]
        return state.version

    monkeypatch.setattr(inputs.subprocess, "check_output", output)
    lock = {
        "mpfbCommit": "pinned-head",
        "animationSource": "hoodie.glb",
        "mpfbTreeSha256": inputs.tree_digest(source / "mpfb2/src"),
        "systemAssetsTreeSha256": inputs.tree_digest(source / "system-assets"),
        "animationSha256": inputs.file_digest(family / "hoodie.glb"),
        "blenderBinarySha256": inputs.file_digest(blender),
        "blenderVersion": "Blender 4.5.9 LTS",
        "blenderBuildHash": "pinned-build",
        "systemAssetsSha256": "pinned-archive",
        "licenseReceipts": {
            "mpfbAssets": inputs.file_digest(source / "mpfb2/LICENSE.ASSETS.md"),
            "mpfbCode": inputs.file_digest(source / "mpfb2/LICENSE.CODE.md"),
            "distributedAssets": inputs.file_digest(family / "LICENSE.md"),
            "animationAssets": inputs.file_digest(family / "men-LICENSE.txt"),
            "animationImport": inputs.file_digest(family / "hoodie.import.json"),
        },
    }
    (family / "source-lock.json").write_text(json.dumps(lock))
    monkeypatch.setattr(server, "FAMILY_ROOT", family)
    return SimpleNamespace(source=source, family=family, blender=blender, state=state)


@pytest.mark.parametrize(
    "relative",
    [
        "source/mpfb2/src/model.py",
        "source/system-assets/clothes/suit.mhclo",
        "family/hoodie.glb",
        "family/LICENSE.md",
        "family/hoodie.import.json",
        "blender",
    ],
)
def test_changed_inputs_cannot_reuse_a_warm_cache(preparation, relative):
    p = preparation
    builder = server.Builder(p.blender, p.source)
    recipe = {c["key"]: c["default"] for c in server.FAMILY["controls"] + server.FAMILY["choices"]}
    identity = inputs.preparation_identity(
        inputs.verify_inputs(p.source, p.blender, p.family), p.family
    )
    key = inputs.cache_key(identity, recipe)
    asset = builder.output / ("human-" + key + ".glb")
    asset.write_bytes(b"previously verified character")
    saved = {
        "file": asset.name,
        "descriptor": {"asset": {"contentSha256": inputs.file_digest(asset)}},
    }
    directory = p.source / "builds" / key
    directory.mkdir(parents=True)
    (directory / "result.json").write_text(json.dumps(saved))
    assert builder.generate(recipe) == saved
    (p.source.parent / relative).write_text("modified input")
    with pytest.raises(ValueError, match="pinned receipt"):
        builder.generate(recipe)
    assert not builder.lock.locked()


def test_dirty_source_and_wrong_blender_are_rejected(preparation):
    p = preparation
    p.state.dirty = " M src/model.py\n"
    with pytest.raises(ValueError, match="dirty"):
        server.Builder(p.blender, p.source)
    p.state.dirty = ""
    p.state.version = "Blender 4.6\nbuild hash: other\n"
    with pytest.raises(ValueError, match="Blender version"):
        server.Builder(p.blender, p.source)


def test_license_receipt_is_part_of_cache_identity(preparation):
    p = preparation
    before = inputs.preparation_identity(
        inputs.verify_inputs(p.source, p.blender, p.family), p.family
    )
    (p.family / "LICENSE.md").write_text("new approved receipt")
    lock = json.loads((p.family / "source-lock.json").read_text())
    lock["licenseReceipts"]["distributedAssets"] = inputs.file_digest(p.family / "LICENSE.md")
    (p.family / "source-lock.json").write_text(json.dumps(lock))
    after = inputs.preparation_identity(
        inputs.verify_inputs(p.source, p.blender, p.family), p.family
    )
    assert inputs.cache_key(before, {}) != inputs.cache_key(after, {})


def test_default_publication_creates_a_clean_checkout_destination(tmp_path):
    asset = tmp_path / "human.glb"
    asset.write_bytes(b"prepared GLB")
    destination = tmp_path / "web/packages/app/public/fixtures/characters"
    publish_default(asset, destination)
    assert (destination / "human-default.glb").read_bytes() == asset.read_bytes()


@pytest.mark.parametrize(
    "value",
    [
        "*",
        "https://example.com:5194",
        "http://127.0.0.1:0",
        "http://localhost",
        "http://localhost:5194/path",
        "http://localhost.evil:5194",
        "http://user@localhost:5194",
    ],
)
def test_origin_configuration_rejects_non_loopback_or_ambiguous_origins(value):
    with pytest.raises(ValueError):
        server.loopback_origin(value)


@pytest.mark.parametrize(
    "allowed, accepted, rejected",
    [
        (server.DEFAULT_ORIGINS, "http://127.0.0.1:5192", "http://127.0.0.1:5194"),
        (
            ["http://127.0.0.1:5194", "http://localhost:5194"],
            "http://localhost:5194",
            "http://127.0.0.1:5192",
        ),
    ],
)
def test_worker_accepts_only_configured_workspace_origins(tmp_path, allowed, accepted, rejected):
    calls = []

    def generate(body):
        calls.append(body)
        return {"prepared": True}

    http = server.create_server(SimpleNamespace(output=tmp_path, generate=generate), 0, allowed)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    try:
        for origin, expected in [
            (accepted, 200),
            (rejected, 403),
            ("http://example.com:5194", 403),
            (None, 200),
        ]:
            client = HTTPConnection("127.0.0.1", http.server_port, timeout=5)
            headers = {"Content-Type": "application/json"}
            if origin:
                headers["Origin"] = origin
            client.request("POST", "/generate", "{}", headers)
            response = client.getresponse()
            assert response.status == expected
            response.read()
            client.close()
        assert calls == [{}, {}]
    finally:
        http.shutdown()
        http.server_close()
        thread.join(timeout=5)
