/** World creation, editing, inspection and agents share one saved state. */
import { buildEditorialPage } from './editorial-page.js';
import { buildWorldShowcase } from './world-showcase.js';

export function buildCapabilities(options: { atlasHref: string | null } = { atlasHref: null }): HTMLElement {
  return buildEditorialPage({
    id: 'capabilities', title: 'A place to make your own.',
    introduction: 'Create a world, develop its surroundings, and choose the intelligence within it. Keep the result and return to it.',
    links: [{ href: '/docs/world-api', label: 'World API' }, { href: '/developers', label: 'Developer Overview' }],
    feature: buildWorldShowcase(options),
    sections: [
      { id: 'capability-create', title: 'Create', copy: 'Choose a supported world type, configure its settings, and save the result.' },
      { id: 'capability-edit', title: 'Shape', copy: 'Place and move objects, adjust supported appearances and behaviors, and undo object edits.' },
      { id: 'capability-inspect', title: 'Understand', copy: 'Inspect properties, edit history, events, and recorded agent decisions.' },
      { id: 'capability-agents', title: 'Connect', copy: 'Choose an available open model or connect your own agent. Control access and review its actions.' },
    ],
    note: 'Controls depend on the world type and its content. Imported objects do not automatically gain behavior or become editable in every detail.',
  });
}
