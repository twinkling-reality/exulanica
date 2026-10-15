"""Every file the API reads at startup is in its image: the reviewed object catalog, the
committed style pack library and the shipped thing library.

``tests/test_image_ships_import_reads.py`` holds the image to what an import reads. The reviewed
furniture is built later, when the API starts: ``reviewed_assets()`` embeds each object's baked
texture sets, and the texture catalog verifies every blob its manifest names. An image without
those blobs builds, passes the import check, and then stops at startup with
``TextureCatalogError``, which is how the judge stack's image failed before its recipe copied them.
The style pack library is read at startup too (``style_pack_library()`` in the API's lifespan),
every pack's manifest and files held to their digests, and so is the thing library
(``thing_library()``), every kind, look and look container. This records the files each call opens
in a fresh interpreter and holds each to the API image with the same allowlist and copy checks.
"""

from __future__ import annotations

import json
import subprocess
import sys

from test_image_ships_import_reads import IMAGES, REPOSITORY

_READS = """
import json, sys
from pathlib import Path
import exulanica
package = Path(exulanica.__file__).resolve().parent
root = package.parent
from exulanica.world.assets import reviewed_assets
from exulanica.world.style_pack_library import load_style_pack_library
from exulanica.world.thing_library import load_thing_library
read = set()
def hook(event, args):
    if event != "open" or not args or not isinstance(args[0], (str, Path)):
        return
    path = Path(args[0]).resolve()
    if root in path.parents and package not in path.parents and ".venv" not in path.parts:
        read.add(path.relative_to(root).as_posix())
sys.addaudithook(hook)
{call}
print(json.dumps(sorted(read)))
"""


def startup_reads(call: str = "reviewed_assets()") -> list[str]:
    done = subprocess.run(
        [sys.executable, "-c", _READS.replace("{call}", call)],
        cwd=REPOSITORY,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_every_file_the_reviewed_object_catalog_reads_ships_in_the_api_image():
    image = IMAGES["api"]
    read = startup_reads()
    # A positive control: the catalog verifies baked texture sets, so the reading saw one.
    assert any(path.startswith("assets/textures/blobs/") for path in read), read
    missing = [path for path in read if not (image.allowlisted(path) and image.shipped(path))]
    assert missing == []


def test_every_file_the_style_pack_library_reads_ships_in_the_api_image():
    image = IMAGES["api"]
    read = startup_reads("load_style_pack_library()")
    # A positive control: the library holds every piece to its digest, so the reading saw one.
    assert any(
        path.startswith("assets/style-packs/packs/") and path.endswith(".glb") for path in read
    ), read
    missing = [path for path in read if not (image.allowlisted(path) and image.shipped(path))]
    assert missing == []


def test_every_file_the_thing_library_reads_ships_in_the_api_image():
    image = IMAGES["api"]
    read = startup_reads("load_thing_library()")
    # A positive control: the library reads every shipped look, so the reading saw one.
    assert any(path.startswith("assets/catalogs/things/looks/") for path in read), read
    missing = [path for path in read if not (image.allowlisted(path) and image.shipped(path))]
    assert missing == []


def test_every_file_the_style_pack_check_and_upload_read_ships_in_the_api_image():
    # The asset preparation process builds its style pack check when it starts (the colour table),
    # and the API its upload runtime (the look families, texture sets and piece budgets); both run
    # from this image.
    image = IMAGES["api"]
    read = startup_reads(
        "from exulanica.world.style_pack_checks import colour_table\n"
        "from exulanica.world.workspace_style_packs import WorkspaceStylePackRuntime\n"
        "from exulanica.store.namespaces import LocalWorkspaceStores\n"
        "colour_table(root)\n"
        "WorkspaceStylePackRuntime.over(LocalWorkspaceStores(root / 'never-made'))"
    )
    # A positive control: the check reads the colour table, so the reading saw it.
    assert "assets/colour/srgb8-linear16.v1.json" in read, read
    missing = [path for path in read if not (image.allowlisted(path) and image.shipped(path))]
    assert missing == []


def test_every_file_a_worlds_setting_is_checked_against_ships_in_the_api_image():
    # Read the first time a world states a setting or a page lists the named parts: the rules, the
    # parts and the colour table the legibility rules read.
    image = IMAGES["api"]
    read = startup_reads(
        "from exulanica.world.world_settings import load_setting_parts, load_setting_rules\n"
        "load_setting_parts(rules=load_setting_rules())"
    )
    # A positive control: each of the three files was opened.
    assert {
        "assets/style-packs/settings/setting-rules.v1.json",
        "assets/style-packs/settings/setting-parts.v1.json",
        "assets/colour/srgb8-linear16.v1.json",
    } <= set(read), read
    missing = [path for path in read if not (image.allowlisted(path) and image.shipped(path))]
    assert missing == []


def test_the_kind_drafting_fixture_vocabulary_ships_in_the_api_image():
    image = IMAGES["api"]
    read = startup_reads(
        "from exulanica.world.kinds.thing_leaves import load_thing_leaves\nload_thing_leaves()"
    )
    assert "assets/catalogs/world-kinds/thing-leaf.v1.json" in read
    assert all(image.allowlisted(path) and image.shipped(path) for path in read)


def test_published_generation_contract_versions_ship_in_the_api_image():
    image = IMAGES["api"]
    read = startup_reads(
        "from exulanica.world.kinds.thing_leaves import load_thing_leaves\n"
        "from exulanica.world.kinds.shape_classes import load_shape_classes\n"
        "from exulanica.selection.kind_drafting import kind_drafting_prompt, PROMPT_PATH\n"
        "from exulanica.world.kinds.catalogs import load_arcade_catalog, load_kind_catalogs\n"
        "load_thing_leaves(version=1)\nload_thing_leaves(version=2)\nload_shape_classes()\n"
        "load_kind_catalogs(bounds_version=3)\nload_arcade_catalog()\n"
        "load_arcade_catalog(version=2)\nload_arcade_catalog(version=3)\n"
        "for version in (5, 6, 7):\n"
        "    kind_drafting_prompt(PROMPT_PATH.with_name(f'kind-drafting.v{version}.json'))"
    )
    assert {
        "assets/catalogs/world-kinds/kind-bound.v1.json",
        "assets/catalogs/world-kinds/kind-bound.v2.json",
        "assets/catalogs/world-kinds/kind-bound.v3.json",
        "assets/catalogs/world-kinds/thing-leaf.v1.json",
        "assets/catalogs/world-kinds/thing-leaf.v2.json",
        "assets/catalogs/world-kinds/shape-class.v1.json",
        "assets/catalogs/world-kinds/structure-arcade.v1.json",
        "assets/catalogs/world-kinds/structure-arcade.v2.json",
        "assets/catalogs/world-kinds/structure-arcade.v3.json",
    } <= set(read)
    assert all(image.allowlisted(path) and image.shipped(path) for path in read)
    # The startup audit excludes package files, so verify these published prompt reads directly.
    for version in (5, 6, 7):
        path = f"exulanica/selection/kind-drafting.v{version}.json"
        assert image.allowlisted(path)
        assert "COPY exulanica ./exulanica" in image.dockerfile
