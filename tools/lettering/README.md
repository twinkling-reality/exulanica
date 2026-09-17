# Lettering tool

Turns the four committed open-licence fonts under `assets/fonts/` into the glyph catalogs under
`assets/catalogs/lettering/`, once. The product never runs it and never imports it: the catalogs
are data, and `exulanica.lettering` and `@exulanica/loom-lettering` read them without a font
parser. The rules it applies, and why, are in `docs/lettering.md`.

It has its own environment, because fontTools must never enter the product's `uv.lock` (every lane
runs `uv sync --locked --offline`). The `[tool.uv]` table in `pyproject.toml` matters: without one,
uv takes the ROOT project's settings and writes the root's dependency metadata into this lock.

    uv run --directory tools/lettering --locked --offline python -m exulanica_lettering_tool build
    uv run --directory tools/lettering --locked --offline python -m exulanica_lettering_tool check
    uv run --directory tools/lettering --locked --offline pytest

`build` writes the catalogs named in `catalogs.json`; `check` rebuilds them in memory and fails if
any committed byte differs. Each build runs the exhaustive cap-height scan, about 90 seconds for all
four on six processes.
