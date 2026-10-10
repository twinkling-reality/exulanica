/** Inspectable model decisions and explicit research questions. */
import { buildEditorialPage } from './editorial-page.js';

export function buildResearch(): HTMLElement {
  return buildEditorialPage({
    id: 'research', title: 'Intelligence in context.',
    introduction: 'Study model behavior in a shared world. Models propose actions; the world validates and records them. Replay recorded decisions without another model call.',
    links: [{ href: '/docs/agents', label: 'How agents connect' }, { href: '/roadmap', label: 'Product direction' }],
    compact: true, sections: [],
    note: 'Whether people prefer discovering open models through a world rather than a list or leaderboard stays an open question.',
  });
}
