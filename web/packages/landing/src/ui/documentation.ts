import { el } from './dom.js';
import '../documentation.css';

export type DocumentationKind = 'index' | 'world-api' | 'agents';
const REPOSITORY = 'https://github.com/twinkling-reality/exulanica';
const source = (path: string, label: string): HTMLAnchorElement => el('a', { href: `${REPOSITORY}/blob/main/${path}`, text: `${label} ↗`, title: 'View source on GitHub', 'aria-label': label.includes('GitHub') ? label : `${label} (GitHub)` });
const p = (text: string): HTMLParagraphElement => el('p', { text });
const inline = (text: string): HTMLElement => el('code', { text });

function codeBlock(label: string, value: string): HTMLElement {
  const status = el('span', { class: 'docs-copy-status', role: 'status', 'aria-live': 'polite' });
  const button = el('button', { type: 'button', class: 'docs-copy', text: 'Copy', 'aria-label': `Copy ${label}` });
  button.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(value);
      status.textContent = 'Copied';
    } catch {
      status.textContent = 'Select the code to copy it.';
    }
  });
  return el('div', { class: 'docs-code' }, [
    el('div', { class: 'docs-code-toolbar' }, [el('span', { text: label }), status, button]),
    el('pre', { tabindex: '0', 'aria-label': label }, [el('code', { text: value })]),
  ]);
}

function table(headers: string[], rows: string[][]): HTMLElement {
  return el('div', { class: 'docs-table-scroll', tabindex: '0', 'aria-label': headers.join(' and ') }, [
    el('table', {}, [
      el('thead', {}, [el('tr', {}, headers.map((text) => el('th', { scope: 'col', text })))]),
      el('tbody', {}, rows.map((row) => el('tr', {}, row.map((text) => el('td', { text }))))),
    ]),
  ]);
}

interface Chapter { key: string; title: string; nodes: Node[] }
interface DocumentPage { title: string; introduction: string; chapters: Chapter[]; sourcePath: string }

function overview(): DocumentPage {
  return {
    title: 'Build with Exulanica',
    introduction: 'Read a world, change its state, or connect an agent that can act inside it. Start with the interface your project needs.',
    sourcePath: 'docs/capabilities/developer-client.md',
    chapters: [
      { key: 'interfaces', title: 'Choose your interface', nodes: [
        el('div', { class: 'docs-paths' }, [
          el('a', { href: '/docs/world-api' }, [el('span', { text: 'World API' }), p('Read saved worlds, discover available operations, and make changes against a known state.')]),
          el('a', { href: '/docs/agents' }, [el('span', { text: 'Agent Integrations' }), p('Connect your own model or MCP client to the turns a world owner authorizes.')]),
        ]),
      ] },
      { key: 'requirements', title: 'Before you start', nodes: [
        p('You need an Exulanica server address and a credential issued for that server. These guides describe the open-source software; the public landing site does not issue API tokens.'),
        table(['Interface', 'Credential', 'Tools'], [
          ['World API', 'A workspace bearer token with the permissions your requests require', 'Any HTTP client; the Python client requires Python 3.11 or later'],
          ['Agent Integrations', 'An agent key from the world owner', 'Python 3.11 or later; the MCP facade also requires the MCP SDK'],
        ]),
      ] },
      { key: 'first-read', title: 'Make your first read', nodes: [
        p('Clone the repository and enter its Python client directory. Set EXULANICA_TOKEN to your workspace token and EXULANICA_API_URL to your server address in your environment. Use HTTPS, or HTTP on localhost for local development.'),
        codeBlock('Terminal', 'git clone https://github.com/twinkling-reality/exulanica.git\ncd exulanica/clients/python\npython3 -m exulanica_client discover --base-url "$EXULANICA_API_URL"'),
        p('The discover command reads the server’s API description, asset registry, and behavior registry. It does not edit a world. The client uses the Python standard library and requires no package installation.'),
        el('p', {}, ['Next, ', el('a', { href: '/docs/world-api', text: 'discover what your world supports' }), ' or ', el('a', { href: '/docs/agents', text: 'connect an outside agent' }), '.']),
      ] },
      { key: 'source', title: 'Explore the source', nodes: [
        p('The full contracts describe request shapes, permission rules, and refusals. Use the OpenAPI document served by your installation for its exact request and response schemas.'),
        el('ul', {}, [
          el('li', {}, [source('docs/capabilities/world-api.md', 'World API contract')]),
          el('li', {}, [source('docs/capabilities/developer-client.md', 'Python client guide')]),
          el('li', {}, [source('docs/capabilities/outside-agents.md', 'Outside-agent contract')]),
          el('li', {}, [source('docs/deployment.md', 'Deployment guide')]),
        ]),
      ] },
    ],
  };
}

function worldApi(): DocumentPage {
  return {
    title: 'World API',
    introduction: 'Work with the same authenticated world state the application uses. Discover what is available before making a change, and verify the result with a fresh read.',
    sourcePath: 'docs/capabilities/world-api.md',
    chapters: [
      { key: 'authentication', title: 'Authenticate your requests', nodes: [
        el('p', {}, ['Send ', inline('Authorization: Bearer <token>'), ' with each request. A token belongs to one workspace. World-content routes also require a ', inline('world_id'), ' query parameter; the server does not choose a default world.']),
        p('Set EXULANICA_API_URL and EXULANICA_TOKEN in your environment. The following read lists the worlds your token can access and requires world.read.'),
        codeBlock('cURL', 'curl --fail-with-body "$EXULANICA_API_URL/worlds" \\\n  -H "Authorization: Bearer $EXULANICA_TOKEN"'),
      ] },
      { key: 'discover', title: 'Discover available operations', nodes: [
        p('A capability read describes supported operations, required permissions, available choices, and reasons an operation cannot run. Availability and permission are separate: check both.'),
        table(['Read', 'Use it to'], [
          ['GET /worlds/capabilities', 'Discover which kinds of world the workspace can create.'],
          ['GET /world-entries', 'Find saved worlds and the versions they reopen.'],
          ['GET /world/versions/{version_id}/capabilities?world_id=…', 'Discover one version’s regions, operations, prerequisites, and stale-state tokens.'],
        ]),
        p('From clients/python in the cloned repository, this command reads capability descriptions and checks the operations they name against your server’s OpenAPI document. Leave off --exercise to keep it read-only.'),
        codeBlock('Python client', 'python3 -m exulanica_client capabilities \\\n  --base-url "$EXULANICA_API_URL"'),
      ] },
      { key: 'edits', title: 'Make changes against a known state', nodes: [
        el('ol', {}, [
          el('li', {}, ['Read the version and retain its ', inline('state_sha256'), '.']),
          el('li', {}, ['Use the capability description to select a supported operation, valid region, and available asset or behavior.']),
          el('li', {}, ['Send the edit with the required base token. Authored-object edits use ', inline('base_state_sha256'), '.']),
          el('li', {}, ['Read the result. If another edit changed the base, reread and reconcile before retrying.']),
        ]),
        el('p', {}, ['The Python client exposes ', inline('WorldClient'), ' and ', inline('ApiRefusal'), '. It carries the server’s status, code, and detail through to your program. ', source('docs/capabilities/developer-client.md', 'See the object-editing walkthrough'), ' for a complete example that places an asset and verifies the resulting state.']),
        p('Editing a version and updating a saved world’s resume point are distinct operations. The Python client can bind an edit to a saved entry so the saved world reopens at the result.'),
      ] },
      { key: 'responses', title: 'Handle refusals explicitly', nodes: [
        table(['Response', 'Next step'], [
          ['404 unknown_reference', 'Check the world ID and the token’s workspace. A world outside the workspace is not disclosed.'],
          ['409 stale_object_base', 'Read the version again and reconcile your intended edit with its new state.'],
          ['Capability unavailable or unsupported', 'Read the descriptor’s code and dependencies. Do not assume the operation will become available on retry.'],
        ]),
        el('p', {}, ['For all routes, schemas, and permission requirements, consult ', inline('/openapi.json'), ' on your server and the ', source('docs/capabilities/world-api.md', 'full World API contract'), '.']),
      ] },
    ],
  };
}

function agents(): DocumentPage {
  return {
    title: 'Connect an outside agent',
    introduction: 'Bring your own model or agent framework into a world. Its owner controls what the agent can decide for and can end its access at any time.',
    sourcePath: 'docs/capabilities/outside-agents.md',
    chapters: [
      { key: 'connect', title: 'Connect to a world', nodes: [
        p('Ask the world owner for the server address and an agent key. The deployment must admit the agents bridge, and the owner’s grant must name the world version and the things your agent can control, or allow it to enter with its own body.'),
        p('Install the library with Python 3.11 or later. This installs from the project repository; the core client has no third-party runtime dependencies.'),
        codeBlock('Install', 'pip install "exulanica-agent @ git+https://github.com/twinkling-reality/exulanica#subdirectory=bridges/agents"'),
        p('Set EXULANICA_URL to the server address and EXULANICA_AGENT_KEY_FILE to a file containing the key. Keep that file private. Check the connection before starting your model:'),
        codeBlock('Check access', 'exulanica-agent check'),
        p('A successful check reports the agent’s permission and the world’s rules. Run one process per key: multiple processes would compete for the same turns.'),
      ] },
      { key: 'turns', title: 'Respond to a turn', nodes: [
        p('Each turn supplies the messages and action choices a model inside the world receives. Your agent chooses one offered action exactly as written, before the turn’s deadline. The world validates and records the answer.'),
        table(['Python interface', 'Meaning'], [
          ['turn.messages', 'The system and user messages for this decision.'],
          ['turn.tool / turn.tool_choice', 'The action function and the forced function choice for your model call.'],
          ['turn.seconds_left', 'Time remaining to answer.'],
          ['turn.act(action, line)', 'Submit one offered action and a line when the action permits one.'],
        ]),
        el('p', {}, ['The ', source('bridges/agents/examples/quickstart.py', 'complete Python quickstart'), ' connects an open model on Nebius Token Factory. It includes the model request and missed-turn handling; replace that model call with your own implementation. Your model’s credentials and costs belong to your agent, not the world owner.']),
      ] },
      { key: 'mcp', title: 'Use an MCP client', nodes: [
        p('The MCP facade exposes the same turns over stdio. Install the MCP extra, configure the server address and agent key file in your client’s environment, and launch this command from the MCP client:'),
        codeBlock('MCP setup', 'pip install "exulanica-agent[mcp] @ git+https://github.com/twinkling-reality/exulanica#subdirectory=bridges/agents"\nexulanica-agent mcp'),
        table(['Tool', 'What it does'], [
          ['wait_for_turn', 'Wait for a decision and its offered actions.'],
          ['act', 'Answer an open turn.'],
          ['what_happened', 'Read whether answers were accepted and whether access changed.'],
          ['world_rules', 'Read the world’s rules.'],
          ['enter_world', 'Enter with the agent’s own body when its grant allows a visitor.'],
        ]),
        el('p', {}, ['Use the ', source('bridges/agents/examples/mcp-settings.json', 'MCP client configuration example'), ' or the ', source('bridges/agents/examples/nemo-agent-toolkit.yml', 'NeMo Agent Toolkit example'), ' for a complete integration.']),
      ] },
      { key: 'boundaries', title: 'Understand the boundaries', nodes: [
        p('An agent cannot invent actions, decide for things outside its grant, or execute code inside the world. A missing or late response falls back to the world’s routine. Revoking the grant ends access immediately.'),
        p('Visitor bodies require a world version with a society of things and a gate. Visitor speech and nearby conversation are not yet supported through this bridge. Outside agents are not included as model-comparison arms.'),
        el('p', {}, ['See the ', source('docs/capabilities/outside-agents.md', 'outside-agent contract'), ' for grant lifetimes, deadlines, and the full limitations, and the ', source('bridges/agents/README.md', 'bridge guide'), ' for owner commands and key rotation.']),
      ] },
    ],
  };
}

export function buildDocumentation(kind: DocumentationKind): HTMLElement {
  const page = kind === 'index' ? overview() : kind === 'world-api' ? worldApi() : agents();
  const id = kind === 'index' ? 'docs' : `docs-${kind}`;
  const pathname = kind === 'index' ? '/docs' : `/docs/${kind}`;
  const sidebar = el('nav', { class: 'docs-sidebar', 'aria-label': 'Documentation' }, [
    el('p', { class: 'docs-nav-label', text: 'Documentation' }),
    ...([['index', '/docs', 'Overview'], ['world-api', '/docs/world-api', 'World API'], ['agents', '/docs/agents', 'Agent Integrations']] as const).map(([key, href, text]) =>
      el('a', { href, text, ...(key === kind ? { 'aria-current': 'page' } : {}) })),
    el('p', { class: 'docs-nav-label docs-nav-secondary', text: 'Source on GitHub' }),
    source('docs/README.md', 'Full Documentation'),
    source('docs/deployment.md', 'Self-Hosting'),
    source('tests/snapshots/api-openapi.json', 'OpenAPI Schema'),
  ]);
  const article = el('article', { class: 'docs-article' }, [
    el('header', { class: 'docs-heading' }, [
      el('p', { class: 'docs-breadcrumb', text: kind === 'index' ? 'Documentation' : kind === 'world-api' ? 'Documentation / World API' : 'Documentation / Agent Integrations' }),
      el('h1', { id: `${id}-title`, text: page.title }),
      p(page.introduction),
    ]),
    ...page.chapters.map((chapter) => el('section', { id: `${id}-${chapter.key}`, class: 'docs-chapter' }, [el('h2', { text: chapter.title }), ...chapter.nodes])),
    el('footer', { class: 'docs-footer' }, [source(page.sourcePath, 'Read the full guide on GitHub')]),
  ]);
  const contents = el('nav', { class: 'docs-contents', 'aria-label': 'On this page' }, [
    el('p', { class: 'docs-nav-label', text: 'On this page' }),
    ...page.chapters.map((chapter) => el('a', { href: `${pathname}#${id}-${chapter.key}`, text: chapter.title })),
  ]);
  return el('section', { id, class: 'pane documentation-pane', tabindex: '-1', 'aria-labelledby': `${id}-title` }, [
    el('div', { class: 'docs-layout' }, [sidebar, article, contents]),
  ]);
}
