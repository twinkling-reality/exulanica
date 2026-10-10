/** Implemented foundations and planned expansion have distinct status. */
import { buildEditorialPage } from './editorial-page.js';

export function buildRoadmap(): HTMLElement {
  return buildEditorialPage({
    id: 'roadmap', title: 'More room to create.',
    introduction: 'Saved worlds, supported object edits, and authorized agent access are implemented. Richer editing, broader model roles, and more kinds of movement are planned.',
    links: [{ href: 'https://github.com/twinkling-reality/exulanica/blob/main/docs/product-direction.md', label: 'Product direction on GitHub' }],
    compact: true, sections: [],
    note: 'Public access is not yet open. Planned capabilities are not available features or a release schedule.',
  });
}
