/** An introduction to the platform through its three core responsibilities. */
import { buildEditorialPage } from './editorial-page.js';

export function buildPurpose(): HTMLElement {
  return buildEditorialPage({
    id: 'purpose', title: 'Worlds you can build on.',
    introduction: 'Build a persistent world, shape its surroundings, and let open AI models act within it. Return to your saved changes and inspect what happened.',
    links: [{ href: '/worlds', label: 'Explore Worlds' }, { href: '/developers', label: 'For developers' }],
    compact: true, sections: [],
  });
}
