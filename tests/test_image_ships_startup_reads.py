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
