import { destinations, p, type DocumentPage } from './elements.js';

export function overview(): DocumentPage {
  return {
    title: 'Documentation',
    introduction: 'Worlds for AI Agents. Build a world, run its agents, and inspect how their decisions shape what happens.',
    sourcePath: 'docs/product-direction.md',
    chapters: [
      { key: 'start', title: 'Start with a World', nodes: [
        p('Exulanica separates the place you build from the open models that decide what happens inside it. Shape its content, assign models to supported roles, and inspect the decisions the engine accepts.'),
        destinations([
          { label: 'Quickstart', detail: 'Create a world, add content, connect a model, and inspect a run.', href: '/docs/quickstart' },
        ]),
      ] },
      { key: 'paths', title: 'Choose Your Path', nodes: [
        destinations([
          { label: 'Worldbuilding', detail: 'Create a place, edit its objects, and reopen its saved state.', href: '/docs/worlds' },
          { label: 'Models and Decisions', detail: 'Assign an open model and inspect a turn.', href: '/docs/models' },
          { label: 'Comparisons and Replay', detail: 'Change one model, keep the starting world fixed, and read the verdict.', href: '/docs/comparisons' },
          { label: 'World API', detail: 'Authenticate a program and read or edit persistent state.', href: '/docs/world-api' },
          { label: 'Agent Integration', detail: 'Let an outside model answer authorized turns from Python or MCP.', href: '/docs/agents' },
        ]),
      ] },
      { key: 'installation', title: 'Use Your Installation', nodes: [
        p('These guides describe Exulanica’s open-source software. Your installation supplies the application address, credentials, catalogs and model services.'),
        destinations([
          { label: 'Installation', detail: 'Run the browser, API, and database on your machine.', href: '/docs/self-hosting' },
          { label: 'Authentication', detail: 'Use the credential that matches the browser, an API client, or one agent.', href: '/docs/authentication' },
        ]),
      ] },
    ],
  };
}
