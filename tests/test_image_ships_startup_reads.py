"""Every file the API reads when it builds the reviewed object catalog at startup is in its image.

``tests/test_image_ships_import_reads.py`` holds the image to what an import reads. The reviewed
furniture is built later, when the API starts: ``reviewed_assets()`` embeds each object's baked
texture sets, and the texture catalog verifies every blob its manifest names. An image without
those blobs builds, passes the import check, and then stops at startup with
``TextureCatalogError``, which is how the judge stack's image failed before its recipe copied them.
This records the files that call opens in a fresh interpreter and holds each to the API image
with the same allowlist and copy checks.
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
read = set()
def hook(event, args):
    if event != "open" or not args or not isinstance(args[0], (str, Path)):
        return
    path = Path(args[0]).resolve()
    if root in path.parents and package not in path.parents and ".venv" not in path.parts:
        read.add(path.relative_to(root).as_posix())
sys.addaudithook(hook)
reviewed_assets()
print(json.dumps(sorted(read)))
"""


def startup_reads() -> list[str]:
    done = subprocess.run(
        [sys.executable, "-c", _READS], cwd=REPOSITORY, capture_output=True, text=True, check=True
    )
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_every_file_the_reviewed_object_catalog_reads_ships_in_the_api_image():
    image = IMAGES["api"]
    read = startup_reads()
    # A positive control: the catalog verifies baked texture sets, so the reading saw one.
    assert any(path.startswith("assets/textures/blobs/") for path in read), read
    missing = [path for path in read if not (image.allowlisted(path) and image.shipped(path))]
    assert missing == []
