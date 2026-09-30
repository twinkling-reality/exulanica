"""Draw the rehearsal's synthetic photographs: never a personal photograph, the same bytes every run.

    <worktree>/.venv/bin/python scripts/rehearsal/photographs.py RECIPE.json OUT_DIR

Run with the product's environment (Pillow, numpy and ``exulanica`` for its EXIF reader). The
recipe is the photographs session's ``parameters.photographs`` in ``steps.json``: each entry names a
scene kind of ``scripts/make_place_proposal_d_photographs.py``, the index it is drawn at, the text on
its board and a local capture time with its UTC offset. The scenes are drawn by that script's
``scene()`` and given a camera's surface by ``make_place_photographs.photographic()``, the drawings
the places and Companion runs proposed a place from. Each capture time is read back with the
product's own EXIF reader before the photograph is kept, so a photograph whose time the product
would not read is refused here rather than discovered in an answer. Prints what was drawn as JSON.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

from PIL import Image

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

from make_place_photographs import photographic  # noqa: E402
from make_place_proposal_d_photographs import scene  # noqa: E402

from exulanica.ingest.exif import extract_exif_facts  # noqa: E402

#: The JPEG quality the places lane's end-to-end scenes were saved at.
JPEG_QUALITY = 82
_DATETIME_ORIGINAL = 0x9003
_OFFSET_TIME_ORIGINAL = 0x9011
_EXIF_IFD = 0x8769


def draw(recipe: list[dict[str, object]], out: Path) -> list[dict[str, object]]:
    out.mkdir(parents=True, exist_ok=True)
    drawn = []
    for entry in recipe:
        text = entry["text"]
        image, truth = scene(
            int(entry["scene_index"]),
            str(entry["kind"]),
            str(entry["arm"]),
            tuple(text) if isinstance(text, list) else text,
        )
        image = photographic(image, int(entry["scene_index"]))
        exif = Image.Exif()
        exif[0x010F] = "Exulanica synthetic"
        exif[0x0110] = "Rehearsal synthetic camera"
        exif.get_ifd(_EXIF_IFD)[_DATETIME_ORIGINAL] = entry["captured"]
        exif.get_ifd(_EXIF_IFD)[_OFFSET_TIME_ORIGINAL] = entry["utc_offset"]
        path = out / f"{entry['stem']}.jpg"
        image.save(path, "JPEG", quality=JPEG_QUALITY, exif=exif)
        expected = dt.datetime.strptime(
            f"{entry['captured']} {entry['utc_offset']}", "%Y:%m:%d %H:%M:%S %z"
        )
        with Image.open(path) as opened:
            _, facts = extract_exif_facts(opened)
        if facts.clock is None or facts.clock.utc != expected:
            raise SystemExit(f"{path.name}: the product reads {facts.clock} as its capture time")
        drawn.append(
            {
                "file": path.name,
                "kind": entry["kind"],
                "arm": entry["arm"],
                "board_text": truth["board_text"],
                "place_name": truth["place_name"],
                "captured_at_utc": expected.astimezone(dt.UTC).isoformat(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "bytes": path.stat().st_size,
            }
        )
    return drawn


def main() -> None:
    recipe = json.loads(Path(sys.argv[1]).read_text())
    print(json.dumps(draw(recipe, Path(sys.argv[2])), indent=2))


if __name__ == "__main__":
    main()
