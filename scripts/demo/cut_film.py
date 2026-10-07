"""Cut the demo's film from recorded takes, by a cut list that is data.

    uv run python scripts/demo/cut_film.py <cut-list.json> --out <film.mp4> [--dry-run]

A cut list (``exulanica.film-cut/v1``) states the frame (width, height, frames a second), the font
(a file, relative to the cut list), the ground and ink colours, and in order the film's parts: a
card (lines of words on the film's ground, for a number of seconds) or a stretch of a take (a file
relative to the cut list, its in and out points in seconds, a speed, and a caption). A stretch
played faster than it was recorded carries its speed on screen ("4x"), so nothing is quietly
hurried, and a take is fitted inside the frame without stretching. Cards and captions are drawn
here as pictures with the cut list's font and laid over the takes by ffmpeg, so the film needs no
ffmpeg built with a text renderer. The script names no scene, beat or caption: everything it shows
comes from the cut list. ``--dry-run`` draws the pictures and prints the ffmpeg command instead of
running it.

Pillow draws; ffmpeg 6 or later on the path cuts.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

CUT_PROFILE = "exulanica.film-cut/v1"
#: The most a stretch may be sped up: beyond it a viewer cannot follow what happens.
SPEED_MAXIMUM = 8
_COLOUR = re.compile(r"#[0-9a-f]{6}")


class CutRefused(ValueError):
    """A cut list this script will not cut, by what is wrong."""


def read_cut(path: Path) -> dict[str, Any]:
    cut = json.loads(path.read_text(encoding="utf-8"))
    if cut.get("profile") != CUT_PROFILE:
        raise CutRefused(f"{path} is not an {CUT_PROFILE} document")
    frame = cut["frame"]
    if any(type(frame[k]) is not int or frame[k] <= 0 for k in ("width", "height", "fps")):
        raise CutRefused("the frame states a whole width, height and frames a second")
    for key in ("ground", "ink"):
        if _COLOUR.fullmatch(cut[key]) is None:
            raise CutRefused(f"{key} is a colour written #rrggbb")
    if not cut["parts"]:
        raise CutRefused("a film has at least one part")
    for index, part in enumerate(cut["parts"]):
        where = f"parts[{index}]"
        if part["kind"] == "card":
            if not part["lines"] or not part["seconds"] > 0:
                raise CutRefused(f"{where}: a card states its lines and how long it shows")
        elif part["kind"] == "take":
            if not 0 <= part["in_s"] < part["out_s"]:
                raise CutRefused(f"{where}: a take ends after it starts")
            if type(part["speed"]) is not int or not 1 <= part["speed"] <= SPEED_MAXIMUM:
                raise CutRefused(f"{where}: a whole speed from 1 to {SPEED_MAXIMUM}")
        else:
            raise CutRefused(f"{where}: a part is a card or a take")
    return cut


def seconds(cut: Mapping[str, Any]) -> float:
    """How long the film runs, from the cut list alone."""
    total = 0.0
    for part in cut["parts"]:
        if part["kind"] == "card":
            total += part["seconds"]
        else:
            total += (part["out_s"] - part["in_s"]) / part["speed"]
    return total


def _rgb(colour: str, alpha: int = 255) -> tuple[int, int, int, int]:
    return (int(colour[1:3], 16), int(colour[3:5], 16), int(colour[5:7], 16), alpha)


def _size(frame: Mapping[str, int]) -> int:
    """The film's text size, in pixels, for its frame."""
    return max(24, frame["height"] // 30)


def draw_card(cut: Mapping[str, Any], lines: Sequence[str], font: Path) -> Image.Image:
    """A card: its first line large, the rest below, centred on the film's ground."""
    frame = cut["frame"]
    width, height, size = frame["width"], frame["height"], _size(frame)
    image = Image.new("RGB", (width, height), _rgb(cut["ground"])[:3])
    pen = ImageDraw.Draw(image)
    faces = [
        ImageFont.truetype(str(font), round(size * (1.6 if n == 0 else 1.0)))
        for n in range(len(lines))
    ]
    step = round(size * 1.6)
    top = height // 2 - step * len(lines) // 2
    for n, (line, face) in enumerate(zip(lines, faces, strict=True)):
        pen.text((width // 2, top + n * step), line, font=face, fill=_rgb(cut["ink"]), anchor="mm")
    return image


def draw_overlay(
    cut: Mapping[str, Any], caption: str | None, speed: int, font: Path
) -> Image.Image:
    """What lies over a take: its caption in a box at the foot of the frame, and its speed at the
    top right when it plays faster than it was recorded; transparent elsewhere."""
    frame = cut["frame"]
    width, height, size = frame["width"], frame["height"], _size(frame)
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)
    face = ImageFont.truetype(str(font), size)
    box = _rgb(cut["ground"], round(255 * 0.72))
    if caption:
        left, top, right, bottom = pen.textbbox(
            (width // 2, height - 2 * size), caption, font=face, anchor="mm"
        )
        margin = size // 2
        pen.rectangle((left - margin, top - margin, right + margin, bottom + margin), fill=box)
        pen.text(
            (width // 2, height - 2 * size), caption, font=face, fill=_rgb(cut["ink"]), anchor="mm"
        )
    if speed != 1:
        mark = f"{speed}x"
        left, top, right, bottom = pen.textbbox((width - size, size), mark, font=face, anchor="ra")
        margin = size // 3
        pen.rectangle((left - margin, top - margin, right + margin, bottom + margin), fill=box)
        pen.text((width - size, size), mark, font=face, fill=_rgb(cut["ink"]), anchor="ra")
    return image


def command(cut: Mapping[str, Any], base: Path, pictures: Path, out: Path) -> list[str]:
    """Draw every card and overlay into ``pictures`` and return the ffmpeg command that cuts the
    film: one filter graph, every part fitted to the frame, then joined in order."""
    frame = cut["frame"]
    width, height, fps = frame["width"], frame["height"], frame["fps"]
    ground = "0x" + cut["ground"][1:]
    font = base / cut["font"]
    pictures.mkdir(parents=True, exist_ok=True)
    inputs: list[str] = []
    chains: list[str] = []
    count = 0

    def add(*arguments: str) -> int:
        nonlocal count
        inputs.extend(arguments)
        count += 1
        return count - 1

    for n, part in enumerate(cut["parts"]):
        if part["kind"] == "card":
            card = pictures / f"card-{n:02d}.png"
            draw_card(cut, part["lines"], font).save(card)
            i = add(
                "-loop", "1", "-framerate", str(fps), "-t", str(part["seconds"]), "-i", str(card)
            )
            chains.append(f"[{i}:v]scale={width}:{height},setsar=1,fps={fps},format=yuv420p[p{n}]")
            continue
        overlay = pictures / f"over-{n:02d}.png"
        draw_overlay(cut, part.get("caption"), part["speed"], font).save(overlay)
        take = add("-i", str(base / part["file"]))
        over = add("-loop", "1", "-framerate", str(fps), "-i", str(overlay))
        chains.append(
            f"[{take}:v]trim=start={part['in_s']}:end={part['out_s']},"
            f"setpts=(PTS-STARTPTS)/{part['speed']},"
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color={ground},setsar=1,fps={fps}[t{n}];"
            f"[t{n}][{over}:v]overlay=0:0:shortest=1,format=yuv420p[p{n}]"
        )
    joined = "".join(f"[p{n}]" for n in range(len(cut["parts"])))
    chains.append(f"{joined}concat=n={len(cut['parts'])}:v=1:a=0[film]")
    return [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *inputs,
        "-filter_complex", ";".join(chains), "-map", "[film]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(out),
    ]  # fmt: skip


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("cut", type=Path, help="the cut list")
    parser.add_argument("--out", type=Path, required=True, help="the film to write")
    parser.add_argument("--dry-run", action="store_true", help="print the ffmpeg command only")
    args = parser.parse_args(argv)
    try:
        cut = read_cut(args.cut)
    except CutRefused as refused:
        print(f"not cut: {refused}", file=sys.stderr)
        return 1
    pictures = args.out.with_name(args.out.stem + "-pictures")
    run = command(cut, args.cut.parent, pictures, args.out)
    print(f"{seconds(cut):.1f} s of film from {len(cut['parts'])} parts", file=sys.stderr)
    if args.dry_run:
        print(shlex.join(run))
        return 0
    if shutil.which("ffmpeg") is None:
        print("ffmpeg is not on the path", file=sys.stderr)
        return 2
    return subprocess.run(run, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
