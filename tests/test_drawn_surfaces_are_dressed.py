"""Every surface the tessellator DRAWS is dressed by a material record, or it is named here.

WHY THIS TEST EXISTS, and why it does not carry a list of kinds to check. The mechanical gate in
``exulanica/grammar/grammars/city/generation/gates.py`` counts unavailable surfaces by asking about
the kinds somebody thought to ask about: it counted tree pits, crossings and bay panels, so an
undressed terrain grid was invisible to it; terrain was added, and a facade's ground band was
invisible in turn. A gate that enumerates what to look at is silent about the class nobody
anticipated, and silence reads as a clean sheet.

So this asks the container instead. A baked tile states, for every surface it draws, whether a
material record dresses it or that none exists. Reading THAT cannot go quiet about a class nobody
anticipated, because it carries no classes: whatever is drawn and undressed appears.

The pinned set below is a difference detector, not an approval. Every line in it is a surface this
fixture draws with no material, and the fixture is a hand-written tile older than the material
catalog that now dresses doors, glazing and street trees in the generated city. A change either way
fails here and has to be looked at: a new undressed class because something drew what nothing
dresses, and a disappearing one because the fixture was dressed.
"""

from __future__ import annotations

import subprocess
from collections import Counter
from pathlib import Path

import pytest

from owd_entries import projections, undressed

ROOT = Path(__file__).resolve().parents[1]
TSX = ROOT / "web" / "node_modules" / ".bin" / "tsx"
CLI = ROOT / "web" / "packages" / "loom-tess" / "src" / "node" / "cli.ts"
DOCUMENT = ROOT / "tests" / "fixtures" / "city-v2" / "tile-document.json"

#: What the fixture draws with no material record, by record kind and surface role. Each is a
#: material the fixture's own hand-written records never state, not a gap in the city grammar: the
#: generated city dresses all of these from the published sets.
UNDRESSED: dict[tuple[str, str], int] = {
    ("city.facade", "door"): 3,
    ("city.facade", "glazing"): 2,
    ("city.street_tree", "trunk"): 2,
    ("city.street_tree", "canopy"): 2,
    ("city.facade", "ground_band"): 1,
    ("city.street_tree", "tree_pit"): 1,
    # Terrain is the one surface no published texture set dresses, by decision rather than by
    # oversight: no set depicts bare ground and none is asked for.
    ("city.terrain", "terrain"): 1,
}


@pytest.fixture(scope="module")
def container(tmp_path_factory) -> Path:
    if not TSX.exists():
        pytest.skip("web/node_modules is not installed, so the tessellator cannot bake")
    out = tmp_path_factory.mktemp("drawn") / "fixture.owd"
    subprocess.run(
        [str(TSX), str(CLI), "bake", str(DOCUMENT), str(out)],
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT / "web",
    )
    return out


def test_every_drawn_surface_is_dressed_or_named_here(container: Path):
    render_batch = next(p for p in projections(container, DOCUMENT) if p["name"] == "render_batch")
    counted = Counter((surface.kind, surface.role) for surface in undressed(render_batch))
    assert dict(counted) == UNDRESSED


def test_the_navigation_projection_dresses_nothing_and_states_no_material(container: Path):
    """The walkable surface carries no materials at all, so nothing there can be undressed.

    Stated because the two projections answer differently and a reader could take this file's
    subject to be the whole container.
    """
    nav = next(p for p in projections(container, DOCUMENT) if p["name"] == "nav_envelope")
    assert undressed(nav) == []
    assert all(entry["surfaces"] == [] for entry in nav["entries"])
