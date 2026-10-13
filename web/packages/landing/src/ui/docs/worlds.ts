import { el } from '../dom.js';
import { routeLink, p, table, source, type DocumentPage } from './elements.js';
const steps = (...items: string[]) => el('ol', {}, items.map(text => el('li', { text })));
export function worlds(): DocumentPage {
  return {
    title: 'Worldbuilding',
    introduction: 'Create a durable place, reopen its saved state, and edit the objects it supports.',
    sourcePath: 'docs/saved-world-entry.md',
    chapters: [
      { key: 'create', title: 'Create or Open a World', nodes: [
        p('A world is an owned place with content, agents and saved state. Reopen a saved world from Your worlds, or create a new one. An empty workspace has no world until you create one.'),
        steps('Choose Create a world from Your worlds or the World menu.', 'Make a small town or a market town from a specification preset, and change only values the served schema allows.', 'Follow preparation. The server bakes the town’s tiles off the request. Choose Open world once those tiles are baked.'),
        p('A world drafted from your own words is available only when EXULANICA_KINDS_FROM_PEOPLE is on. A request for an unsupported place, object, or rule does not establish that the system can produce it.'),
        source('docs/world-kinds-contract.md', 'World kinds and validated generation'),
      ] },
      { key: 'starting-points', title: 'Choose a Starting Point', nodes: [
        table(['Starting point', 'What you build on'], [['Authored starter', 'An owned, empty space for placing content without personal source dependencies.'], ['Generated world', 'A place made from a supported world kind and validated values. Town recipes are one example.'], ['Reviewed personal sources', 'A world composed from eligible personal media, with its sources and reconstruction coverage preserved.']]),
        p('Reference attachments and imported 3D assets add content to a world through their own admission and placement workflows. They do not replace its identity or saved edits.'),
        el('p', { class: 'docs-onward' }, [routeLink('/docs/assets', 'Assets and Imports')]),
      ] },
      { key: 'edit', title: 'Edit Your World', nodes: [
        p('Use Add object to place an available catalog object. Select an object to inspect the changes it supports, including its position, appearance, and behavior. The available controls depend on the object and world.'),
        p('Saved edits and their history belong to your world. Return through Your worlds to reopen its saved version. If another client has changed the same state, refresh before attempting the edit again.'),
        p('Add photos is available only for world types that accept photographs. Attaching a reference photograph does not reconstruct its geometry. Generated town recipes do not accept photograph attachments.'),
      ] },
      { key: 'companion', title: 'Create with the Companion', nodes: [p('The Companion helps you ask questions about a world and prepare changes to review. Direct controls and conversation reach the same supported operations.'), p('Ask about an inhabitant’s activity or an event to read an answer grounded in recorded state. For an edit, review the proposed requests and any available preview, then confirm the step. The Companion reports the authority’s receipts rather than treating its own response as a completed change.'), p('A broader rule, object or effect still needs support from the world. Natural-language creation does not give a model permission to invent a runtime mechanism.'), source('docs/capabilities/companion.md', 'Companion questions, proposals and project context')] },
      { key: 'continue', title: 'Connect Models and Inspect Runs', nodes: [el('p', {}, ['Use ', el('a', { href: '/docs/models', text: 'Models and Decisions' }), ' to assign models to supported agent roles and inspect their choices. ', el('a', { href: '/docs/comparisons', text: 'Comparisons and Replay' }), ' explains how to compare models from the same starting state.'])] },
      { key: 'availability', title: 'Unavailable Controls', nodes: [
        p('Read the reason shown beside the control. Model decisions require a configured provider and permission to spend. Creation and editing depend on the world’s supported operations. An unavailable saved world remains listed with its reason.'),
        el('p', {}, ['The browser-only development preview uses fixture data. Use a ', el('a', { href: '/docs/self-hosting', text: 'persistent installation' }), ' for saved worlds and live model decisions.']),
      ] },
    ],
  };
}
