"""Render shared browser icons from the Exulanica vector master (requires rsvg-convert)."""
from pathlib import Path
import json
import math
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / 'assets/brand/exulanica'
master = (BRAND / 'exulanica-symbol.svg').read_text()
# A fourth-order superellipse preserves continuous corners and the master's clear space.
points = []
for i in range(256):
    angle = 2 * math.pi * i / 256
    c, s = math.cos(angle), math.sin(angle)
    points.append((512 + 448 * math.copysign(abs(c)**0.5, c),
                   512 + 448 * math.copysign(abs(s)**0.5, s)))
outline = 'M' + ' L'.join(f'{x:.3f},{y:.3f}' for x, y in points) + ' Z'
symbol = master.replace('<circle cx="512" cy="512" r="448"', f'<path d="{outline}"')
symbol = symbol.replace('Exulanica — single mass', 'Exulanica squircle icon')
symbol = symbol.replace('A pale circular mass', 'A pale squircle').replace('Transparent outside the circle.', 'Transparent outside the squircle.')
icon = BRAND / 'exulanica-icon.svg'
icon.write_text(symbol)
renderer = shutil.which('rsvg-convert')
if renderer is None:
    raise SystemExit('Install librsvg to provide rsvg-convert.')
for package in ('landing', 'app', 'bakeoff'):
    public = ROOT / 'web/packages' / package / 'public'
    public.mkdir(exist_ok=True)
    shutil.copyfile(icon, public / 'favicon.svg')
    for name, size in [('favicon-32.png', 32), ('apple-touch-icon.png', 180),
                       ('icon-192.png', 192), ('icon-512.png', 512)]:
        subprocess.run([renderer, '-w', str(size), '-h', str(size), str(icon),
                        '-o', str(public / name)], check=True)
    manifest = {
        'name': 'Exulanica', 'short_name': 'Exulanica',
        'icons': [{'src': f'icon-{size}.png', 'sizes': f'{size}x{size}',
                   'type': 'image/png', 'purpose': 'any'} for size in (192, 512)],
        'theme_color': '#f7f9f7', 'background_color': '#f7f9f7', 'display': 'browser',
    }
    (public / 'site.webmanifest').write_text(json.dumps(manifest, indent=2) + '\n')
