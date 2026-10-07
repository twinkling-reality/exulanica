"""The demo film's cutter: a cut list is data, and the cut is drawn and joined from it alone.

What is shown here, without ffmpeg or any take: a cut list reads only when every part is a card or a
take with sound figures, and is refused by name otherwise (against a positive control); the film's
length is the cards' seconds plus each take's stretch divided by its speed; every card and overlay
is drawn as a picture at the frame's size, a take played faster carries its speed, and the ffmpeg
command joins every part, in order, at the frame's size and rate.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
FONT = ROOT / "assets/fonts/barlow/Barlow-SemiBold.ttf"


def _cutter():
    spec = importlib.util.spec_from_file_location("cut_film", ROOT / "scripts/demo/cut_film.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["cut_film"] = module
    spec.loader.exec_module(module)
    return module


def _cut() -> dict:
    return {
        "profile": "exulanica.film-cut/v1",
        "frame": {"width": 640, "height": 360, "fps": 30},
        "font": str(FONT),
        "ground": "#111725",
        "ink": "#e9edf4",
        "parts": [
            {"kind": "card", "seconds": 2, "lines": ["A title", "a line below it"]},
            {
                "kind": "take",
                "file": "a.mp4",
                "in_s": 1.0,
                "out_s": 5.0,
                "speed": 1,
                "caption": "one",
            },
            {
                "kind": "take",
                "file": "b.mp4",
                "in_s": 0.0,
                "out_s": 8.0,
                "speed": 4,
                "caption": "two",
            },
        ],
    }


def _write(path: Path, cut: dict) -> Path:
    path.write_text(json.dumps(cut), encoding="utf-8")
    return path


def test_a_cut_list_reads_and_a_faulty_one_is_refused_by_name(tmp_path):
    cutter = _cutter()
    cutter.read_cut(_write(tmp_path / "cut.json", _cut()))  # the positive control
    faults = []
    for key, value, words in (
        ("speed", 9, "speed from 1 to 8"),
        ("speed", 1.5, "whole speed"),
        ("out_s", 0.0, "ends after it starts"),  # it starts at 0.0
        ("kind", "clip", "a card or a take"),
    ):
        cut = _cut()
        cut["parts"][2][key] = value
        faults.append((cut, words))
    blank = _cut()
    blank["parts"][0]["lines"] = []
    faults.append((blank, "states its lines"))
    pale = _cut()
    pale["ink"] = "white"
    faults.append((pale, "#rrggbb"))
    for cut, words in faults:
        with pytest.raises(cutter.CutRefused, match=words):
            cutter.read_cut(_write(tmp_path / "faulty.json", cut))


def test_the_film_lasts_its_cards_and_its_takes_at_their_speeds():
    # 2 s of card, 4 s of a take at its own speed, 8 s of a take at four times: 8 s in all.
    assert _cutter().seconds(_cut()) == 8.0


def test_every_part_is_drawn_at_the_frame_and_joined_in_order(tmp_path):
    cutter = _cutter()
    cut = _cut()
    run = cutter.command(cut, tmp_path, tmp_path / "pictures", tmp_path / "film.mp4")
    pictures = sorted((tmp_path / "pictures").iterdir())
    assert [p.name for p in pictures] == ["card-00.png", "over-01.png", "over-02.png"]
    for picture in pictures:
        assert Image.open(picture).size == (640, 360)
    graph = run[run.index("-filter_complex") + 1]
    assert "[p0][p1][p2]concat=n=3:v=1:a=0[film]" in graph
    assert "setpts=(PTS-STARTPTS)/4" in graph and "setpts=(PTS-STARTPTS)/1" in graph
    assert graph.count("scale=640:360") == 3 and graph.count("fps=30") == 3
    # The faster take carries its speed: its overlay differs from the one at its own speed only by
    # the mark at the top right.
    slow, fast = (
        Image.open(tmp_path / "pictures" / name) for name in ("over-01.png", "over-02.png")
    )
    corner = (640 - 120, 0, 640, 60)
    assert slow.crop(corner).getbbox() is None and fast.crop(corner).getbbox() is not None
    same = copy.deepcopy(cut)
    same["parts"][2]["speed"] = 1
    cutter.command(same, tmp_path, tmp_path / "again", tmp_path / "film.mp4")
    assert Image.open(tmp_path / "again" / "over-02.png").crop(corner).getbbox() is None
