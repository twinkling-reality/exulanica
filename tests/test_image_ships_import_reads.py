"""Every file the package reads when it is imported is in each image that installs it, where it
is read.

A module finds a catalog two directories above its own file (``Path(__file__).parents[2]``), which
is the repository in a checkout and site-packages in an image, whose install is not editable. A file
read at import that an image does not ship stops every process in it before it starts. This imports
every module in a fresh interpreter, records each file opened under the repository but outside the
package, and holds each to every image that installs the package: its build context's allowlist
admits the file, a runtime ``COPY`` puts it under a directory, and a ``RUN`` links that directory
as ``assets`` in the image's site-packages.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import pytest

REPOSITORY = Path(__file__).resolve().parents[1]

_READS = """
import importlib, json, pkgutil, sys
from pathlib import Path
import exulanica
package = Path(exulanica.__file__).resolve().parent
root = package.parent
read = set()
def hook(event, args):
    if event != "open" or not args or not isinstance(args[0], (str, Path)):
        return
    path = Path(args[0]).resolve()
    if root in path.parents and package not in path.parents and ".venv" not in path.parts:
        read.add(path.relative_to(root).as_posix())
sys.addaudithook(hook)
failed = []
absent = []
for module in pkgutil.walk_packages([str(package)], "exulanica."):
    try:
        importlib.import_module(module.name)
    except ModuleNotFoundError as exc:
        # CI installs no extras, so a module that needs an optional stack cannot be imported
        # there; its reads are checked wherever the extras are installed.
        missing = (exc.name or "").split(".")[0]
        if missing and missing != "exulanica":
            absent.append(f"{module.name}: {missing}")
        else:
            failed.append(f"{module.name}: {type(exc).__name__}")
    except Exception as exc:
        failed.append(f"{module.name}: {type(exc).__name__}")
print(json.dumps({"read": sorted(read), "failed": failed, "absent": absent}))
"""


def import_reads() -> dict[str, list[str]]:
    """The files every module's import opens outside the package, from a fresh interpreter."""
    done = subprocess.run(
        [sys.executable, "-c", _READS], cwd=REPOSITORY, capture_output=True, text=True, check=True
    )
    return json.loads(done.stdout.strip().splitlines()[-1])


@dataclass(frozen=True)
class Image:
    """One image that installs the package: its recipe and its build context's allowlist."""

    dockerfile: str
    dockerignore: str

    def allowlisted(self, path: str) -> bool:
        """Whether the build context's allowlist admits ``path``."""
        admitted = [
            line[1:].strip() for line in self.dockerignore.splitlines() if line.startswith("!")
        ]
        return any(path == entry or path.startswith(entry.rstrip("/") + "/") for entry in admitted)

    def shipped(self, path: str) -> bool:
        """Whether a runtime ``COPY`` puts ``path`` under a directory the image links as
        site-packages' ``assets``, which is where the installed package reads it."""
        runtime = self.dockerfile.split(" AS runtime", 1)[1]
        links = re.findall(
            r"^RUN ln -s (\S+)/assets \"\$\((\S+)/bin/python -c 'import sysconfig; "
            r"print\(sysconfig.get_paths\(\)\[\"purelib\"\]\)'\)/assets\"$",
            runtime,
            re.MULTILINE,
        )
        linked = {PurePosixPath(root) for root, _venv in links}
        for source, destination in re.findall(r"^COPY\s+(?!--)(\S+)\s+(\S+)\s*$", runtime, re.M):
            inside = path == source or path.startswith(source.rstrip("/") + "/")
            if not inside or not source.startswith("assets/"):
                continue
            if any(PurePosixPath(destination) == root / source for root in linked):
                return True
        return False


#: Every image recipe that installs the package, with the allowlist its build context uses.
IMAGES = {
    "api": Image(
        (REPOSITORY / "Dockerfile").read_text(encoding="utf-8"),
        (REPOSITORY / ".dockerignore").read_text(encoding="utf-8"),
    ),
    "material-bake": Image(
        (REPOSITORY / "deploy/material-bake/Dockerfile").read_text(encoding="utf-8"),
        (REPOSITORY / "deploy/material-bake/Dockerfile.dockerignore").read_text(encoding="utf-8"),
    ),
}


def test_every_image_that_installs_the_package_is_checked():
    """A recipe that installs the package non-editably is one whose imports read site-packages."""
    installing = sorted(
        path.relative_to(REPOSITORY).as_posix()
        for path in REPOSITORY.glob("**/Dockerfile")
        if ".venv" not in path.parts
        and "node_modules" not in path.parts
        and "--no-editable" in path.read_text(encoding="utf-8")
    )
    assert installing == ["Dockerfile", "deploy/material-bake/Dockerfile"]


@pytest.mark.parametrize("name", sorted(IMAGES))
def test_every_file_the_package_reads_at_import_ships_where_it_is_read(name):
    image = IMAGES[name]
    found = import_reads()
    assert found["failed"] == []
    # A positive control: the society's routine is read at import, so the reading saw something.
    assert any(path.startswith("assets/catalogs/society/") for path in found["read"])
    missing = [
        path for path in found["read"] if not (image.allowlisted(path) and image.shipped(path))
    ]
    assert missing == []


@pytest.mark.parametrize("name", sorted(IMAGES))
def test_the_check_refuses_a_read_the_image_does_not_ship(name):
    """Positive control for the two checks: a file outside the allowlist and the copies."""
    image = IMAGES[name]
    assert not image.allowlisted("assets/characters/stylized-looks.json")
    assert not image.shipped("assets/characters/stylized-looks.json")
    assert image.allowlisted("assets/catalogs/society/society-need.v1.json")
    assert image.shipped("assets/catalogs/society/society-need.v1.json")
