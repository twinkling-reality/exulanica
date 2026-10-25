// @vitest-environment happy-dom
// The Integrations page (tools/previews/world-workspace/integrations.ts, DESIGN's frames r30-integrations-a and -b)
// over stand-in answers of the server's own reads: GET /models, GET /door/bridges, GET /door/grants for each saved
// world, a version's society for whom a grant decides for, and its model history after Del ends a grant through
// POST /door/grants/{id}/revoke, the one thing this page writes.
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../../tools/previews/world-workspace/front-door.ts', () => ({
  chosenWorldPicture: () => null,
  openMadeWorld: async () => {},
}));

interface Options { credentials: unknown; entries: readonly { worldId: string }[]; picture: () => string | null }
interface IntegrationsPage {
  offerIntegrations(row: HTMLElement, offer: Record<string, unknown> | null, options: Options): HTMLButtonElement | null;
  mountIntegrations(options: Options & { onClose: () => void }): { readonly isConnected: boolean; remove(): void };
}
// Joined paths: the test runner still finds the files, and the type checker leaves the preview modules out.
const page = async (): Promise<IntegrationsPage> => import('../../../../tools/previews/world-workspace/' + 'integrations.ts') as Promise<IntegrationsPage>;

const CREDENTIALS = { baseUrl: 'https://host.test', token: 'install-token' };
const ENTRIES = [{ worldId: 'world:a' }, { worldId: 'world:b' }, { worldId: 'world:a' }];

const model = (provider: string, name: string, refusal: string | null = null) => ({ provider, model_id: name, name, runtime: { provider_refusal: refusal } });
const KEYED = [model('nebius_token_factory', 'Nemotron 3 Super'), model('ollama_local', 'Qwen3 4B Instruct')];
const AGENTS = { bridge: 'agents', label: 'Outside AI agents', game: 'AI agents', run_by: 'owner', ai: true };
const grant = (id: string, world: string, things: string[] = [], extra: Record<string, unknown> = {}) => ({
  grant_id: id, world_id: world, bridge: 'agents', grant_seq: 1, state: 'active', ended: null, ai: true, declared: null,
  scope: { things, version_id: 'v-1', visitors_maximum: 1 }, issued_at: '2026-10-25T10:00:00Z', expires_at: '2026-10-25T12:00:00Z', ...extra,
});
const SOCIETY = { state: { inhabitants: [
  { id: 'p-1', display_name: 'Uma Sorrel', came_by: 'drawn' },
  { id: 'p-2', display_name: 'Esme Oak', came_by: 'drawn' },
] } };

interface Served {
  models?: unknown[] | null;
  bridges?: unknown[];
  grants?: Record<string, unknown[] | null>;
  history?: unknown;
  /** How the revoke answers: as the server does, or refused with a status and code. */
  revoke?: { status: number; code: string };
}
interface Call { readonly method: string; readonly path: string }

/** Answers the page's reads as the server does, and records each request. */
function serve(served: Served): Call[] {
  const calls: Call[] = [];
  const grants = served.grants ?? {};
  vi.stubGlobal('fetch', vi.fn(async (address: string, init?: RequestInit) => {
    const url = new URL(address);
    const method = init?.method ?? 'GET';
    calls.push({ method, path: `${url.pathname}${url.search}` });
    const answer = (status: number, body: unknown): Response => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
    if (url.pathname === '/models') return served.models === null ? answer(503, { code: 'unavailable' }) : answer(200, { models: served.models ?? KEYED });
    if (url.pathname === '/door/bridges') return answer(200, { bridges: served.bridges ?? [AGENTS] });
    if (url.pathname === '/door/grants') {
      const listed = grants[url.searchParams.get('world_id') ?? ''];
      return listed === null ? answer(503, { code: 'unavailable' }) : answer(200, { grants: listed ?? [], next: null });
    }
    const revoke = /^\/door\/grants\/([^/]+)\/revoke$/u.exec(url.pathname);
    if (revoke && method === 'POST') {
      if (served.revoke) return answer(served.revoke.status, { code: served.revoke.code, detail: 'refused' });
      const one = Object.values(grants).flatMap(list => list ?? []).find(row => (row as { grant_id: string }).grant_id === decodeURIComponent(revoke[1]!));
      return answer(200, { grant: { ...(one as object), state: 'revoked', ended: 'revoked' } });
    }
    if (/^\/world\/versions\/v-1\/society$/u.test(url.pathname)) return answer(200, SOCIETY);
    if (/^\/world\/versions\/v-1\/society\/models\/history$/u.test(url.pathname)) return answer(200, served.history ?? { choices: [] });
    return answer(404, { code: 'unknown_reference' });
  }));
  return calls;
}

const settle = async (): Promise<void> => { for (let i = 0; i < 12; i++) await new Promise((resolve) => setTimeout(resolve, 0)); };
const key = (target: Element, name: string): KeyboardEvent => {
  const event = new KeyboardEvent('keydown', { key: name, code: name, bubbles: true, cancelable: true });
  target.dispatchEvent(event);
  return event;
};
const rows = (): HTMLElement[] => [...document.querySelectorAll<HTMLElement>('.wu-int-row')];
const stateOf = (name: string): { words: string; on: boolean } => {
  const row = rows().find(one => one.querySelector('.wu-int-name')?.textContent === name)!;
  const state = row.querySelector<HTMLElement>('.wu-int-state')!;
  return { words: state.textContent ?? '', on: state.querySelector('.wu-int-dot') !== null };
};
const focused = (): HTMLElement => document.querySelector<HTMLElement>('.wu-int-row[data-focus="true"]')!;
const keyWords = (): string[] => [...document.querySelectorAll('.wu-light-keys .wu-qcmd-word')].map(word => word.textContent ?? '');
const faint = (): string | null => focused().querySelector('.wu-int-faint')?.textContent ?? null;

async function open(served: Served, onClose = () => {}): Promise<Call[]> {
  const calls = serve(served);
  (await page()).mountIntegrations({ credentials: CREDENTIALS, entries: ENTRIES, picture: () => null, onClose });
  await settle();
  return calls;
}

afterEach(() => { vi.unstubAllGlobals(); document.body.replaceChildren(); });

describe('the Integrations button on the front door', () => {
  it('stands beside Create a world only on the install owner\'s own page', async () => {
    const { offerIntegrations } = await page();
    const row = document.createElement('div'); row.className = 'your-worlds-create-row'; document.body.append(row);
    const options = { credentials: CREDENTIALS, entries: ENTRIES, picture: () => null };
    expect(offerIntegrations(row, { own_key: false }, options)).toBeNull();
    expect(offerIntegrations(row, null, options)).toBeNull();
    expect(row.children).toHaveLength(0);
    const opener = offerIntegrations(row, { own_key: true }, options)!;
    expect(opener.textContent).toBe('Integrations');
    expect(row.querySelectorAll('.ux-entry-integrations')).toHaveLength(1);
    // Offered once, however often the offer is read.
    expect(offerIntegrations(row, { own_key: true }, options)).toBeNull();
  });

  it('opens the page, and Esc gives the focus back to the button', async () => {
    serve({});
    const { offerIntegrations } = await page();
    const row = document.createElement('div'); document.body.append(row);
    const opener = offerIntegrations(row, { own_key: true }, { credentials: CREDENTIALS, entries: ENTRIES, picture: () => null })!;
    opener.click();
    await settle();
    expect(document.querySelector('.wu-light[data-form="integrations"]')).not.toBeNull();
    expect(document.getElementById('wu-int-title')?.textContent).toBe('What your worlds connect to');
    key(focused(), 'Escape');
    expect(document.querySelector('.wu-integrations-host')).toBeNull();
    expect(document.activeElement).toBe(opener);
  });
});

describe('the Integrations page', () => {
  it('says what a keyed install with its runner on serves, from the server\'s own reads, each world\'s grants read once', async () => {
    const calls = await open({});
    expect(rows().map(row => row.querySelector('.wu-int-name')?.textContent)).toEqual(['Nebius Token Factory', 'A model on this computer', 'A game', 'An AI agent you build']);
    expect(stateOf('Nebius Token Factory')).toEqual({ words: 'Your key is set', on: true });
    expect(stateOf('A model on this computer')).toEqual({ words: 'Running · Qwen3 4B Instruct', on: true });
    expect(stateOf('A game')).toEqual({ words: 'None admitted on this install', on: false });
    expect(stateOf('An AI agent you build')).toEqual({ words: 'No grant yet', on: false });
    expect(calls.filter(call => call.path.startsWith('/door/grants')).map(call => call.path)).toEqual(['/door/grants?world_id=world%3Aa', '/door/grants?world_id=world%3Ab']);
    // Nothing is written by opening it, and no society is read where no AI grant stands.
    expect(calls.filter(call => call.method !== 'GET')).toEqual([]);
    expect(calls.some(call => call.path.includes('/society'))).toBe(false);
    // The first row is focused and opened to its three lines.
    expect(focused().querySelector('.wu-int-name')?.textContent).toBe('Nebius Token Factory');
    expect([...focused().querySelectorAll('dt')].map(term => term.textContent)).toEqual(['Connects', 'Reads', 'Goes to']);
    expect(focused().querySelector('dd')?.textContent).toBe('The open models offered with your Nebius key, each from its maker, priced per million tokens.');
    expect(rows().filter(row => row.querySelector('dl')).length).toBe(1);
    // Marks are line drawings: shapes in a 24 by 24 box, never a picture.
    for (const row of rows()) {
      expect(row.querySelector('.wu-int-mark svg')?.getAttribute('viewBox')).toBe('0 0 24 24');
      expect(row.querySelector('.wu-int-mark image, .wu-int-mark img')).toBeNull();
    }
    expect(keyWords()).toEqual(['Choose', 'How to set it up ↗', 'Back']);
  });

  it('says what is not set up, and leaves out what this install does not run', async () => {
    await open({ models: [model('nebius_token_factory', 'Nemotron 3 Super', 'provider_credential_absent'), model('ollama_local', 'Qwen3 4B Instruct', 'provider_not_running')], bridges: [] });
    expect(stateOf('Nebius Token Factory')).toEqual({ words: 'No key yet', on: false });
    expect(stateOf('A model on this computer')).toEqual({ words: 'Not running', on: false });
    document.body.replaceChildren();
    await open({ models: [model('nebius_token_factory', 'Nemotron 3 Super'), model('ollama_local', 'Qwen3 4B Instruct', 'provider_not_admitted')] });
    expect(rows().map(row => row.querySelector('.wu-int-name')?.textContent)).toEqual(['Nebius Token Factory', 'A game', 'An AI agent you build']);
  });

  it('says nothing of a row whose read did not answer, rather than a state it cannot know', async () => {
    await open({ models: null, grants: { 'world:a': [grant('g-1', 'world:a', ['p-1'])], 'world:b': null } });
    expect(stateOf('Nebius Token Factory')).toEqual({ words: '', on: false });
    expect(stateOf('An AI agent you build')).toEqual({ words: '', on: false });
    expect(stateOf('A game')).toEqual({ words: 'None admitted on this install', on: false });
    expect(keyWords()).not.toContain('End this grant');
  });

  it('names whom a standing agent grant decides for, and Del ends it through the door\'s revoke, saying who decides again', async () => {
    const calls = await open({
      grants: { 'world:a': [grant('g-1', 'world:a', ['p-1']), grant('g-0', 'world:a', ['p-2'], { ended: 'expired' })] },
      history: { choices: [{ choice_seq: 4, subjects: ['p-1'], decider: { kind: 'routine' } }, { choice_seq: 3, subjects: ['p-1'], decider: { kind: 'external' } }] },
    });
    expect(stateOf('An AI agent you build')).toEqual({ words: 'Deciding for Uma Sorrel', on: true });
    expect(calls.filter(call => call.path.includes('/society')).map(call => call.path)).toEqual(['/world/versions/v-1/society?world_id=world%3Aa']);
    // Del is offered only on the agent's row.
    expect(keyWords()).not.toContain('End this grant');
    key(focused(), 'Delete');
    await settle();
    expect(calls.some(call => call.method === 'POST')).toBe(false);
    for (let i = 0; i < 3; i++) key(focused(), 'ArrowDown');
    expect(focused().querySelector('.wu-int-name')?.textContent).toBe('An AI agent you build');
    expect(keyWords()).toEqual(['Choose', 'How to set it up ↗', 'End this grant', 'Back']);
    expect(focused().querySelector('dl dd:last-of-type')?.textContent).toBe("The agent you run. You can end the grant at any moment, and the person's own routine decides again.");
    key(focused(), 'Delete');
    await settle();
    expect(calls.filter(call => call.method === 'POST').map(call => call.path)).toEqual(['/door/grants/g-1/revoke']);
    expect(stateOf('An AI agent you build')).toEqual({ words: 'Ended.', on: false });
    expect(faint()).toBe("Uma Sorrel's own routine decides again.");
    expect(keyWords()).not.toContain('End this grant');
    // Ended once: Del again writes nothing.
    key(focused(), 'Delete');
    await settle();
    expect(calls.filter(call => call.method === 'POST')).toHaveLength(1);
  });

  it('names no one where the record does not show their routine deciding again, and both where it shows two', async () => {
    await open({
      grants: { 'world:b': [grant('g-1', 'world:b', ['p-1'])] },
      history: { choices: [{ choice_seq: 3, subjects: ['p-1'], decider: { kind: 'external' } }] },
    });
    for (let i = 0; i < 3; i++) key(focused(), 'ArrowDown');
    key(focused(), 'Delete');
    await settle();
    expect(stateOf('An AI agent you build')).toEqual({ words: 'Ended.', on: false });
    expect(faint()).toBeNull();
    vi.unstubAllGlobals(); document.body.replaceChildren();
    await open({
      grants: { 'world:b': [grant('g-1', 'world:b', ['p-1', 'p-2'])] },
      history: { choices: [{ choice_seq: 4, subjects: ['p-1', 'p-2'], decider: { kind: 'routine' } }] },
    });
    for (let i = 0; i < 3; i++) key(focused(), 'ArrowDown');
    key(focused(), 'Delete');
    await settle();
    expect(faint()).toBe('Their own routines decide again: Uma Sorrel and Esme Oak.');
  });

  it('keeps a grant the server would not end standing, says so, and offers Del again', async () => {
    const calls = await open({ grants: { 'world:a': [grant('g-1', 'world:a', ['p-1'])] }, revoke: { status: 503, code: 'door_unavailable' } });
    for (let i = 0; i < 3; i++) key(focused(), 'ArrowDown');
    key(focused(), 'Delete');
    await settle();
    expect(calls.filter(call => call.method === 'POST')).toHaveLength(1);
    expect(stateOf('An AI agent you build')).toEqual({ words: 'Deciding for Uma Sorrel', on: true });
    expect(faint()).toBe('It could not be ended just then; it still stands.');
    expect(keyWords()).toContain('End this grant');
    key(focused(), 'Delete');
    await settle();
    expect(calls.filter(call => call.method === 'POST')).toHaveLength(2);
  });

  it('says a grant the server answers had already ended has ended', async () => {
    await open({ grants: { 'world:a': [grant('g-1', 'world:a', ['p-1'])] }, revoke: { status: 409, code: 'grant_ended' } });
    for (let i = 0; i < 3; i++) key(focused(), 'ArrowDown');
    key(focused(), 'Delete');
    await settle();
    expect(stateOf('An AI agent you build')).toEqual({ words: 'Ended.', on: false });
    expect(faint()).toBeNull();
    expect(keyWords()).not.toContain('End this grant');
  });

  it('counts several standing agent grants, offers no Del for them, and says how each ends instead', async () => {
    const calls = await open({ grants: { 'world:a': [grant('g-1', 'world:a', ['p-1'])], 'world:b': [grant('g-2', 'world:b')] } });
    expect(stateOf('An AI agent you build')).toEqual({ words: '2 grants', on: true });
    for (let i = 0; i < 3; i++) key(focused(), 'ArrowDown');
    expect(focused().querySelector('.wu-int-faint')?.textContent).toBe('Each grant ends by itself at most a day after it was given.');
    expect(keyWords()).not.toContain('End this grant');
    key(focused(), 'Delete');
    await settle();
    expect(calls.some(call => call.method === 'POST')).toBe(false);
  });

  it('says a grant that decides for nobody yet stands', async () => {
    await open({ grants: { 'world:a': [grant('g-1', 'world:a')] } });
    expect(stateOf('An AI agent you build')).toEqual({ words: 'Deciding for nobody yet', on: true });
  });

  it('keeps its keys from the front door under it, opens the focused row\'s guide in a new tab, and holds ↑ ↓ at the ends', async () => {
    const opened = vi.fn();
    vi.stubGlobal('open', opened);
    await open({});
    const reached = vi.fn();
    document.addEventListener('keydown', reached);
    key(focused(), 'ArrowUp');
    expect(focused().querySelector('.wu-int-name')?.textContent).toBe('Nebius Token Factory');
    for (let i = 0; i < 6; i++) key(focused(), 'ArrowDown');
    expect(focused().querySelector('.wu-int-name')?.textContent).toBe('An AI agent you build');
    key(focused(), 'Enter');
    expect(opened).toHaveBeenCalledWith('https://github.com/twinkling-reality/exulanica/blob/main/docs/capabilities/outside-agents.md#on-your-own-install', '_blank', 'noopener');
    // Enter's key is a press drawn as the quiet command, a link to the focused row's guide (fold-in e).
    const guide = document.querySelector<HTMLAnchorElement>('a.wu-int-guide')!;
    expect(guide.href).toBe('https://github.com/twinkling-reality/exulanica/blob/main/docs/capabilities/outside-agents.md#on-your-own-install');
    expect([guide.classList.contains('wu-qcmd'), guide.classList.contains('wu-light-hint'), guide.dataset['place']]).toEqual([true, false, 'row']);
    key(focused(), 'n');
    expect(reached).not.toHaveBeenCalled();
    document.removeEventListener('keydown', reached);
  });
});
