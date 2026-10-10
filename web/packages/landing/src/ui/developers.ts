/** Public interfaces for applications and agents working with saved worlds. */
import { el } from './dom.js';
import { buildEditorialPage } from './editorial-page.js';

export function buildDevelopers(): HTMLElement {
  const example = el('section', { class: 'developer-example', 'aria-labelledby': 'developer-example-title' }, [
    el('div', {}, [
      el('h2', { id: 'developer-example-title', text: 'Start with a world.' }),
      el('p', { text: 'Set your server address and a workspace token with world.read permission to list the worlds you can access.' }),
    ]),
    el('pre', { tabindex: '0', 'aria-label': 'Read accessible worlds with cURL' }, [
      el('code', { text: 'curl --fail-with-body "$EXULANICA_API_URL/worlds" \\\n  -H "Authorization: Bearer $EXULANICA_TOKEN"' }),
    ]),
  ]);
  return buildEditorialPage({
    id: 'developers', title: 'One world. Your tools.',
    introduction: 'Connect applications and agents to the same world. Read its state, make permitted changes, and inspect what happened.',
    links: [{ href: '/docs', label: 'Read the Documentation' }],
    feature: example,
    sections: [
      { id: 'developers-api', title: 'World API', copy: 'Work with worlds, objects, versions, and recorded events. Discover supported operations before making a change.', href: '/docs/world-api', link: 'Explore the API' },
      { id: 'developers-agents', title: 'Agent Integrations', copy: 'Bring your own model or framework. Connect through the Python bridge or MCP, with access controlled by the world owner.', href: '/docs/agents', link: 'Connect an Agent' },
    ],
  });
}
