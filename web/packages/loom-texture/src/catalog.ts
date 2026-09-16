import type { TextureSetDefinition } from './definition.js';
import { ashlar } from './surfaces/ashlar.js';
import { asphalt } from './surfaces/asphalt.js';
import { brick } from './surfaces/brick.js';
import { concrete } from './surfaces/concrete.js';
import { kerb } from './surfaces/kerb.js';
import { metal } from './surfaces/metal.js';
import { paving } from './surfaces/paving.js';
import { render } from './surfaces/render.js';

/**
 * Every published set: its seed and its version, stated here and nowhere else.
 *
 * A version is a bake input. Any change that alters a set's bytes (a recipe, a palette, the
 * container, the generator itself) must bump that set's version, because the pin a migration
 * holds is (set id, version) -> digest and a pinned pair never names new bytes. A new version
 * also needs a new migration row; `tests/test_texture_set_migration.py` fails until both agree.
 */
export const CATALOG: readonly TextureSetDefinition[] = Object.freeze([
  brick(2026091601, 1),
  ashlar(2026091602, 1),
  render(2026091603, 1),
  concrete(2026091604, 1),
  metal(2026091605, 1),
  asphalt(2026091606, 1),
  paving(2026091607, 1),
  kerb(2026091608, 1),
]);
