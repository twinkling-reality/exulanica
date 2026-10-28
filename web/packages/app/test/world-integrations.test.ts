// @vitest-environment happy-dom
// The Integrations page (tools/previews/world-workspace/integrations.ts, ROOT's mock of 27 October) over stand-in
// answers of the server's own reads: the served catalog (GET /integrations), GET /models, the owner's GET /spending,
// GET /world/github-projects/kept, GET /door/bridges and GET /door/grants for each saved world with a version's society
// for whom a grant decides for; and a guest's page, which reads the host's figures from GET /auth/session's allowance.
// The page writes two things: a grant's end through POST /door/grants/{id}/revoke, and Connect's project request.
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../../tools/previews/world-workspace/front-door.ts', () => ({
  openMadeWorld: async () => {},
}));

interface Entry { worldId: string; entryId: string; title: string; authoredVersionId: string }
interface Options { credentials: unknown; entries: readonly Entry[]; chosen?: () => Entry | null }
interface IntegrationsPage {
  offerIntegrations(row: HTMLElement, offer: Record<string, unknown> | null, options: Options): HTMLButtonElement | null;
  mountIntegrations(options: Options & { onClose: () => void; guest?: boolean; notes?: Record<string, unknown> | null }): { readonly isConnected: boolean; remove(): void };
}
// Joined paths: the test runner still finds the files, and the type checker leaves the preview modules out.
const page = async (): Promise<IntegrationsPage> => import('../../../../tools/previews/world-workspace/' + 'integrations.ts') as Promise<IntegrationsPage>;

const CREDENTIALS = { baseUrl: 'https://host.test', token: 'install-token' };
const ENTRIES: readonly Entry[] = [
  { worldId: 'world:a', entryId: 'e-a', title: 'Fishing village', authoredVersionId: 'v-1' },
  { worldId: 'world:b', entryId: 'e-b', title: 'Night market', authoredVersionId: 'v-2' },
];
const NOTES = { offered: true, code: null, searches_at_most: 3, maximum_usd: '0.02000000' };
const mark = [{ circle: { cx: 12, cy: 12, r: 3 } }];
const CATALOG = {
  profile: 'exulanica.integrations/v1', version: 1, guides: 'https://example.test/blob/main/',
  entries: [
    { key: 'nebius_token_factory', kind: 'provider', local: false, name: 'Nebius Token Factory', line: 'Open models answer for your people.', mark, guide: { document: 'docs/development-setup.md', heading: 'Your own key' } },
    { key: 'ollama_local', kind: 'provider', local: true, name: 'Ollama', line: 'Runs open models on this computer.', mark, guide: { document: 'docs/development-setup.md', heading: 'A runner' } },
    { key: 'tavily_search', kind: 'web', name: 'Tavily', line: 'Searches the web before something is made.', mark },
    { key: 'github', kind: 'github', name: 'GitHub', line: 'Keeps a world’s versions in a repository.', mark },
    { key: 'door', kind: 'door', name: 'Agents and games', line: 'Act for people you grant them, through MCP.', mark },
    { key: 'door.agent', kind: 'grant', ai: true, name: 'AI agents', line: 'Decide for people you grant them, through MCP.', mark: [{ path: { d: 'M1 1h2' } }] },
    { key: 'door.game', kind: 'grant', ai: false, name: 'Games', line: 'Play people you grant them, or bring their own.', mark },
  ],
};
const model = (provider: string, name: string, refusal: string | null = null) => ({ provider, model_id: name, name, runtime: { provider_refusal: refusal } });
const MODELS = [model('nebius_token_factory', 'Nemotron 3 Super'), model('ollama_local', 'Qwen3 4B', 'provider_not_running')];
const AGENTS = { bridge: 'agents', label: 'AI agents', game: 'AI agents', run_by: 'owner', ai: true };
const grant = (id: string, world: string, things: string[] = [], extra: Record<string, unknown> = {}) => ({
  grant_id: id, world_id: world, bridge: 'agents', grant_seq: 1, state: 'active', ended: null, ai: true,
  declared: { name: 'Claude Code', maker: 'Anthropic', mind: null },
  scope: { things, version_id: 'v-1', visitors_maximum: 1 }, issued_at: '2026-10-25T10:00:00Z', expires_at: '2026-10-25T12:00:00Z', ...extra,
});
const SOCIETY = { state: { inhabitants: [
  { id: 'p-1', display_name: 'Ada', came_by: 'drawn' },
  { id: 'p-2', display_name: 'Theo', came_by: 'drawn' },
] } };

interface Served {
  catalog?: unknown;
  models?: unknown[];
  grants?: Record<string, unknown[]>;
  revoke?: { status: number; code: string };
}
interface Call { readonly method: string; readonly path: string; readonly body: unknown }

/** Answers the page's reads as the server does, and records each request. */
function serve(served: Served): Call[] {
  const calls: Call[] = [];
  const grants = served.grants ?? {};
  vi.stubGlobal('fetch', vi.fn(async (address: string, init?: RequestInit) => {
    const url = new URL(address);
    const method = init?.method ?? 'GET';
    calls.push({ method, path: `${url.pathname}${url.search}`, body: init?.body ? JSON.parse(String(init.body)) : null });
    const answer = (status: number, body: unknown): Response => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
    if (url.pathname === '/integrations') return answer(200, served.catalog ?? CATALOG);
    if (url.pathname === '/models') return answer(200, { models: served.models ?? MODELS });
    if (url.pathname === '/spending') return answer(200, { providers: [{ provider: 'nebius_token_factory', available_usd: '3.20000000', available_calls: 400 }] });
    if (url.pathname === '/auth/session') return answer(200, { kind: 'guest', allowance: [
      { provider: 'nebius_token_factory', state: 'active', available_usd: '0.48000000', available_calls: 20 },
      { provider: 'tavily_search', state: 'active', available_usd: '0.00000000', available_calls: 15 },
    ] });
    if (url.pathname === '/world/github-projects/kept') return answer(200, { profile: 'exulanica.world-github-keeping/v1', kept_here: true, on_github: 0 });
    if (url.pathname === '/world/github-projects' && method === 'POST') return answer(202, { request_id: 'q1' });
    if (url.pathname === '/door/bridges') return answer(200, { bridges: [AGENTS] });
    if (url.pathname === '/door/grants') return answer(200, { grants: grants[url.searchParams.get('world_id') ?? ''] ?? [], next: null });
    const revoke = /^\/door\/grants\/([^/]+)\/revoke$/u.exec(url.pathname);
    if (revoke && method === 'POST') {
      if (served.revoke) return answer(served.revoke.status, { code: served.revoke.code, detail: 'refused' });
      const one = Object.values(grants).flat().find(row => (row as { grant_id: string }).grant_id === decodeURIComponent(revoke[1]!));
      return answer(200, { grant: { ...(one as object), state: 'revoked', ended: 'revoked' } });
    }
    if (/^\/world\/versions\/v-1\/society$/u.test(url.pathname)) return answer(200, SOCIETY);
    return answer(404, { code: 'unknown_reference' });
  }));
  return calls;
}

const settle = async (): Promise<void> => { for (let i = 0; i < 16; i++) await new Promise((resolve) => setTimeout(resolve, 0)); };
const rows = (): HTMLElement[] => [...document.querySelectorAll<HTMLElement>('.wu-int-row')];
const shown = (): string[][] => rows().map(row => [
  row.querySelector('.wu-int-name')?.textContent ?? '', row.querySelector('.wu-int-line')?.textContent ?? '',
  row.querySelector('.wu-int-state')?.textContent ?? '', row.querySelector<HTMLElement>('.wu-int-state')?.dataset['kind'] ?? '',
  row.querySelector('button.wu-int-act')?.textContent ?? '',
]);
const actOn = (name: string): HTMLButtonElement => rows().find(row => row.querySelector('.wu-int-name')?.textContent === name)!.querySelector<HTMLButtonElement>('button.wu-int-act')!;

async function open(served: Served, more: { guest?: boolean } = {}, onClose = () => {}): Promise<Call[]> {
  const calls = serve(served);
  (await page()).mountIntegrations({ credentials: CREDENTIALS, entries: ENTRIES, chosen: () => ENTRIES[0]!, onClose, notes: NOTES, ...more });
  await settle();
  return calls;
}

afterEach(() => { vi.unstubAllGlobals(); document.body.replaceChildren(); });

describe('the Integrations button on the front door', () => {
  it('stands beside Create a world once the offer says whose page it is, and opens the page; Esc gives the focus back', async () => {
    serve({});
    const { offerIntegrations } = await page();
    const row = document.createElement('div'); document.body.append(row);
    const options = { credentials: CREDENTIALS, entries: ENTRIES, chosen: () => ENTRIES[0]! };
    expect(offerIntegrations(row, null, options)).toBeNull();
    expect(offerIntegrations(row, {}, options)).toBeNull();
    const opener = offerIntegrations(row, { own_key: true, notes: NOTES }, options)!;
    expect(opener.textContent).toBe('Integrations');
    expect(offerIntegrations(row, { own_key: true }, options)).toBeNull();
    opener.click();
    await settle();
    expect(document.querySelector('.wu-create[data-form="integrations"]')).not.toBeNull();
    expect(document.getElementById('wu-int-title')?.textContent).toBe('Integrations');
    expect(document.querySelector('.wu-create-mark')?.textContent).toBe('exulanica');
    expect(document.querySelector('.wu-create-corner .wu-qcmd-word')?.textContent).toBe('Your worlds');
    document.querySelector<HTMLElement>('.wu-int-host')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', bubbles: true, cancelable: true }));
    expect(document.querySelector('.wu-int-host')).toBeNull();
    expect(document.activeElement).toBe(opener);
  });
});

describe('the Integrations page', () => {
  it('draws each row from data: the served catalog names it, describes it and draws its mark; the live reads say its state', async () => {
    const calls = await open({ grants: { 'world:a': [grant('g1', 'world:a', ['p-1', 'p-2'])] } });
    expect(shown()).toEqual([
      ['Nebius Token Factory', 'Open models answer for your people.', 'Key set · $3.20 left', 'on', 'Models'],
      ['Ollama', 'Runs open models on this computer.', 'Not running', 'off', 'Guide'],
      ['Tavily', 'Searches the web before something is made.', 'Up to 3 searches a making', 'on', ''],
      ['GitHub', 'Keeps a world’s versions in a repository.', 'Not connected', 'off', 'Connect'],
      ['Claude Code', 'Decides for Ada and Theo in Fishing village.', 'Deciding', 'on', 'End'],
    ]);
    // A grant's mark is the catalog's for its kind, drawn as plain shapes.
    expect(rows()[4]!.querySelector('.wu-int-mark svg path')?.getAttribute('d')).toBe('M1 1h2');
    // Nothing is written by opening it; the owner's figures are their own spending, never a guest's session read.
    expect(calls.filter(call => call.method !== 'GET')).toEqual([]);
    expect(calls.map(call => call.path)).toContain('/spending');
    expect(calls.map(call => call.path)).not.toContain('/auth/session');
    // Another catalog's words are the page's words: the page names no service itself.
    document.body.replaceChildren();
    await open({ catalog: { ...CATALOG, entries: CATALOG.entries.filter(entry => entry.key !== 'github').map(entry => (entry.key === 'ollama_local' ? { ...entry, name: 'A runner here' } : entry)) } });
    expect(shown().map(row => row[0])).toEqual(['Nebius Token Factory', 'A runner here', 'Tavily', 'Agents and games']);
  });

  it('ends a grant through the door\'s revoke when End is pressed, and says it ended; a refused end says so and keeps End', async () => {
    const calls = await open({ grants: { 'world:a': [grant('g1', 'world:a', ['p-1'])] } });
    actOn('Claude Code').click();
    await settle();
    expect(calls.filter(call => call.method === 'POST').map(call => call.path)).toEqual(['/door/grants/g1/revoke']);
    expect(shown().at(-1)).toEqual(['Claude Code', 'Decides for Ada in Fishing village.', 'Ended', 'off', '']);
    document.body.replaceChildren();
    await open({ grants: { 'world:a': [grant('g1', 'world:a', ['p-1'])] }, revoke: { status: 409, code: 'grant_not_active' } });
    actOn('Claude Code').click();
    await settle();
    expect(shown().at(-1)).toEqual(['Claude Code', 'Decides for Ada in Fishing village.', 'It could not be ended. Try again.', 'refused', 'End']);
  });

  it('asks the chosen world\'s follower to keep it when Connect is pressed', async () => {
    const calls = await open({});
    actOn('GitHub').click();
    await settle();
    expect(calls.filter(call => call.method === 'POST').map(call => [call.path, call.body])).toEqual([['/world/github-projects?world_id=world%3Aa', { version_id: 'v-1', readable: false }]]);
    expect(shown()[3]!.slice(2)).toEqual(['Asked to keep Fishing village', 'off', '']);
  });

  it('shows a guest the host\'s figures from their allowance, and Not on this server for what they cannot use', async () => {
    const calls = await open({ models: [model('nebius_token_factory', 'Nemotron 3 Super')] }, { guest: true });
    expect(shown()).toEqual([
      ['Nebius Token Factory', 'Open models answer for your people.', 'Host’s key · $0.48 left', 'on', 'Models'],
      ['Ollama', 'Runs open models on this computer.', 'Not on this server', 'na', ''],
      ['Tavily', 'Searches the web before something is made.', 'Up to 3 searches a making · 15 left', 'on', ''],
      ['GitHub', 'Keeps a world’s versions in a repository.', 'Not on this server', 'na', ''],
      ['Agents and games', 'Act for people you grant them, through MCP.', 'Not on this server', 'na', ''],
    ]);
    // A guest's page reads no door, GitHub or spending, and writes nothing.
    const paths = calls.map(call => call.path);
    expect(paths).toContain('/auth/session');
    expect(paths.some(path => path.startsWith('/door/') || path.startsWith('/world/github-projects') || path === '/spending')).toBe(false);
    expect(calls.filter(call => call.method !== 'GET')).toEqual([]);
  });
});
