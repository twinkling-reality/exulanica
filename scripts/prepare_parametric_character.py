"""Install pinned preparation inputs and/or prepare the editable preview's default human.

The build environment stays in ignored local storage. Only the generated CC0 asset,
recipe and descriptor enter the character catalog. Requires Blender 4.5.9.
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path

from exulanica.env import resolve_briefs_path
from parametric_character.preview_server import Builder, FAMILY, FAMILY_ROOT, ROOT


def install(source):
    lock = json.loads((FAMILY_ROOT / "source-lock.json").read_text())
    source.mkdir(parents=True, exist_ok=True)
    repo = source / "mpfb2"
    if not repo.exists():
        subprocess.run(
            [
                "git",
                "clone",
                "--filter=blob:none",
                "--no-checkout",
                lock["mpfbRepository"],
                str(repo),
            ],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "checkout", "--detach", lock["mpfbCommit"]], check=True
        )
    archive = source / "system-assets.zip"
    if not archive.exists():
        urllib.request.urlretrieve(lock["systemAssetsUrl"], archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != lock["systemAssetsSha256"]:
        raise ValueError("System assets do not match the pinned digest")
    if not (source / "system-assets").exists():
        with zipfile.ZipFile(archive) as bundle:
            for name in bundle.namelist():
                if Path(name).is_absolute() or ".." in Path(name).parts:
                    raise ValueError("Unsafe archive member")
            bundle.extractall(source / "system-assets")


def publish_default(asset, destination):
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(asset, destination / "human-default.glb")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=resolve_briefs_path("parametric-human", root=ROOT),
    )
    parser.add_argument("--blender", type=Path, required=True)
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()
    source = args.source.resolve()
    if args.install:
        install(source)
    builder = Builder(args.blender.resolve(), source)
    recipe = {c["key"]: c["default"] for c in FAMILY["controls"] + FAMILY["choices"]}
    look = builder.generate(recipe)
    shutil.copy2(builder.output / look["file"], FAMILY_ROOT / "human-default.glb")
    look.update(file="human-default.glb", generated=False, lookId="editable-human")
    (FAMILY_ROOT / "default.look.json").write_text(json.dumps(look, indent=2) + "\n")
    publish_default(
        FAMILY_ROOT / "human-default.glb", ROOT / "web/packages/app/public/fixtures/characters"
    )
    print(
        "Prepared the default editable human. Run prepare_character_preview.py to refresh the catalog."
    )
