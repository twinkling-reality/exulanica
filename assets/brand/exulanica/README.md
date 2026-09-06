# Exulanica single-mass symbol

Selected direction: one circular mass, with blue concentrated at the upper-left edge, yellow at the bottom, and green following the lower-right curve. Opposing pairs of masses remain supporting artwork, not an alternate logo.

## Files

- `exulanica-symbol.svg`: editable, resolution-independent color master; no embedded raster, fonts, scripts, external resources, or filter dependencies.
- `exulanica-symbol-4k.png`: 4096 × 4096 RGBA export of the master.
- `exulanica-symbol-1024.png`: 1024 × 1024 RGBA export.
- `exulanica-symbol-monochrome.svg`: solid charcoal circle.
- `exulanica-symbol-reversed.svg`: solid white circle.
- `selected-direction-reference.png`: unchanged generated exploration sheet. The selected concept is the single mass in the left column.

The SVG is a vector reconstruction of the selected visual direction, not an exact pixel trace of the generated sheet. Independent elliptical color fields preserve uneven fades; deterministic vector grain is masked to the colored regions. The blue and yellow have locally stronger values than the landing's decorative palette, matching the selected concept's contrast.

The square artboard has 64 units of clear space on every side: the circle is centered at (512, 512), radius 448, within a 1024-unit viewBox. The 4K export retains this padding.

The exterior is transparent. The disc has an opaque pale #f7f9f7 base; its interior fades toward that color rather than becoming a transparent hole. Use the color version on pale canvases. Use the white version on dark surfaces. At very small sizes, prefer the simple monochrome version; no pixel-hinted favicon has been installed or verified.

Do not AI-upscale the PNG to create a new master. Render the SVG at the required dimensions so the circle, field positions and proportions remain fixed.

Example export with librsvg:

```sh
rsvg-convert -w 4096 -h 4096 exulanica-symbol.svg -o exulanica-symbol-4k.png
```

The browser icon variant `exulanica-icon.svg` adapts the master to a squircle while retaining its
color fields and clear space. Landing, app, and renderer preview use this variant for favicons,
Apple touch icons, and manifest icons. The circular master remains the primary brand asset.

Regenerate all browser assets with `python3 scripts/generate_brand_icons.py` (requires librsvg).
The generator copies the same SVG and renders 32, 180, 192, and 512 pixel PNGs into each public directory.
Manifest icons use `purpose: any` because they already include transparent corners.
