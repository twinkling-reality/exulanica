import { ORBIT_PALETTES } from './world-materials.js';
import '../ambient-field.css';

const SECTION_MATERIALS = { product: 0, 'use-cases': 5, documentation: 1 } as const;

/** One bottom fade for the reading surfaces, using the shared world material colors. */
export function withSectionAtmosphere<T extends HTMLElement>(root: T, section: keyof typeof SECTION_MATERIALS): T {
  root.classList.add('section-atmosphere');
  root.dataset.section = section;
  const colors = ORBIT_PALETTES[SECTION_MATERIALS[section]];
  root.style.setProperty('--section-light', colors[0]);
  root.style.setProperty('--section-color', colors[1]);
  return root;
}
