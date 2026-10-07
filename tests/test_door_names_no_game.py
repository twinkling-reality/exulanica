"""The product knows no game: no game's name in its source, and nothing of ``bridges/`` imported.

The door is one door for every outside program, and a game is an adapter outside the product plus
a mapping file, which is data (``docs/door-contract.md``). This holds that by reading the source,
so the second game's adapter cannot add a line to the product without this failing: the import
contracts in ``pyproject.toml`` see imports, and this sees words, which is how a game-specific
branch would most likely arrive.

The names are the games and engines the door's adapters are written for or were considered for,
each matched as a whole word, ignoring case. A game may be named in documents, in ``bridges/``,
in the deployment's bridge directory (configuration) and in tests' prose about the rule itself.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
#: Whole words, so a digest that happens to contain the letters of one is not a name.
GAME_NAMES = re.compile(
    r"(?<![A-Za-z0-9_])("
    r"luanti|minetest|pyrogenesis|zero_ad|0ad|0 a\.d\.?|wildfire games|mineflayer|minecraft"
    r"|skyrim|voxelibre|mineclon(?:e2?|ia)|xonotic"
    r")(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
#: Where the product's source lives: the backend, the piece formats, the web application's
#: packages and the catalogs it ships.
PRODUCT = ("exulanica", "exulanica_pieces", "assets/catalogs", "web/packages")
_SUFFIXES = {".py", ".sql", ".json", ".ts", ".tsx", ".js", ".mjs", ".css", ".html", ".toml"}
_SKIPPED = {"node_modules", "dist", "build", ".turbo", "__pycache__"}


def _product_files() -> list[Path]:
    found = []
    for top in PRODUCT:
        base = ROOT / top
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.suffix in _SUFFIXES and not _SKIPPED & set(path.parts) and path.is_file():
                found.append(path)
    return found


def _named(text: str) -> list[str]:
    return sorted({match.group(1).lower() for match in GAME_NAMES.finditer(text)})


def test_the_search_finds_a_name_where_one_is_written():
    """The guard on the guard: a name in a line is found, a digest's letters are not."""
    assert _named("an adapter for Luanti") == ["luanti"]
    assert _named("from 0 A.D. or minecraft:stone") == ["0 a.d.", "minecraft"]
    assert _named("0AD, 0 A.D without its dot, VoxeLibre, MineClone2, Mineclonia, Xonotic") == [
        "0 a.d",
        "0ad",
        "mineclone2",
        "mineclonia",
        "voxelibre",
        "xonotic",
    ]
    assert _named("sha256 9c0ade1f, zero_adapter, minetests, 10ad") == []


def test_no_game_is_named_in_the_product():
    files = _product_files()
    assert len(files) > 500, "the search found too little of the product to mean anything"
    offenders = {
        str(path.relative_to(ROOT)): names
        for path in files
        if (names := _named(path.read_text(encoding="utf-8", errors="replace")))
    }
    assert offenders == {}, (
        "the product names a game; a game belongs in bridges/ and its mapping file, which is data"
    )


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module)
    return found


def test_nothing_in_the_product_imports_an_adapter():
    offenders = sorted(
        str(path.relative_to(ROOT))
        for top in ("exulanica", "exulanica_pieces")
        for path in (ROOT / top).rglob("*.py")
        if any(name.split(".")[0] == "bridges" for name in _imports(path))
    )
    assert offenders == []


#: Files under ``bridges/`` that are media of our own making, each named with what it is. A game's
#: textures, models, sounds and archives are never committed there.
OUR_OWN_MEDIA: dict[str, str] = {}
_MEDIA = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".tga",
    ".bmp",
    ".ogg",
    ".wav",
    ".mp3",
    ".flac",
    ".b3d",
    ".obj",
    ".x",
    ".dae",
    ".pmd",
    ".glb",
    ".gltf",
    ".fbx",
    ".blend",
    ".zip",
    ".tar",
    ".gz",
    ".7z",
    ".zst",
    ".pk3",
    ".mts",
    ".schem",
}


def test_no_game_media_or_archive_is_kept_with_the_adapters():
    found = sorted(
        str(path.relative_to(ROOT))
        for path in (ROOT / "bridges").rglob("*")
        if path.is_file() and path.suffix.lower() in _MEDIA
    )
    assert found == sorted(OUR_OWN_MEDIA), (
        "bridges/ holds media nobody declared as our own; a game's media is never committed"
    )
