"""The backend image carries the character catalogs it publishes, and they are enough to publish.

Every serving database runs ``exulanica-character-catalog publish --apply`` after ``exulanica-db``
(deploy/judge's ``catalogs`` job, the installation, the acceptance launcher), and the command reads
the catalogs from the image's own ``assets/characters``. The build context is an allowlist, so a
container the catalog names and the allowlist leaves out would make every image-based deployment
fail to publish, and draw nobody, while the repository's own tests pass. These tests hold the
Dockerfile's copies and the allowlist to exactly what publishing reads, by publishing a dry run
from a directory that holds only those paths.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from exulanica.world.character_catalog_publication import catalog_documents, catalog_imports
from exulanica.world.character_catalogs import read_publication_document

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
DOCKERIGNORE = (ROOT / ".dockerignore").read_text(encoding="utf-8")
CHARACTERS = ROOT / "assets" / "characters"
#: What the image carries of assets/characters: the catalogs and the folders they name.
CARRIED = (
    "assets/characters/catalog.json",
    "assets/characters/looks.json",
    "assets/characters/parametric-catalog.json",
    "assets/characters/makehuman-people-v1",
    "assets/characters/makehuman-parametric-v1",
)


def test_the_build_context_allows_and_the_image_copies_every_carried_path():
    allowed = {line.strip() for line in DOCKERIGNORE.splitlines()}
    copies = " ".join(
        line for line in DOCKERFILE.splitlines() if re.match(r"COPY assets/characters", line)
    )
    for path in CARRIED:
        assert f"!{path}" in allowed, f"{path} is not in the build context"
        assert path in copies, f"the image does not copy {path}"
    assert "/app/assets/characters" in copies


def test_what_the_image_carries_is_enough_to_publish(tmp_path):
    """Derive and check every document and container from the carried paths alone."""
    image = tmp_path / "assets" / "characters"
    for path in CARRIED:
        source, target = ROOT / path, tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copyfile(source, target)
    carried = catalog_documents(image)
    whole = catalog_documents(CHARACTERS)
    assert [read_publication_document(d).catalog_sha256 for d in carried] == [
        read_publication_document(d).catalog_sha256 for d in whole
    ]
    for document in carried:
        assert len(catalog_imports(document, image)) == len(catalog_imports(document, CHARACTERS))
