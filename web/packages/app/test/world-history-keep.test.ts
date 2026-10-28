// @vitest-environment happy-dom
// [G] Keep on GitHub from History (tools/previews/world-workspace/history-keep.ts, DESIGN's H12): the card asks the
// project's follower for a review, shows it, and Create says yes to exactly that review; a refusal is said by its
// code; Back withdraws the request. A fake host stands for the API; nothing here reaches GitHub.
import { afterEach, describe, expect, it, vi } from 'vitest';

type Json = Record<string, any>;
interface KeepHost {
  readonly worldId: string;
  read(path: string): Promise<any>;
  write(method: 'POST' | 'DELETE', path: string, body?: unknown): Promise<{ readonly status: number; readonly body: any }>;
}
interface KeepCard { readonly element: HTMLElement; keys(): readonly { keys: readonly string[]; word: string; press(): void }[]; key(event: KeyboardEvent): boolean; close(): void }
interface Module {
  openKeepCard(host: KeepHost, project: { project_id: string; publications_per_day?: number | null }, done: { created(): void; closed(): void }, options?: { pollMs?: number; settleMs?: number }): KeepCard;
  keepState(publication: Json | null, name: string, creating?: boolean): { checking: boolean; refusal: string | null; ready: boolean; account: string | null; proposed: string | null };
}
// A joined path: the test runner still finds the file, and the type checker leaves the preview module out.
const module = async (): Promise<Module> => import('../../../../tools/previews/world-workspace/' + 'history-keep.ts') as Promise<Module>;

const WORLD = 'world:generated:0b0e0c1d-0000-4000-8000-000000000001';
const SCOPE = `?world_id=${encodeURIComponent(WORLD)}`;
// A review as the follower writes it (tests/test_world_project_publication.py): the repository is the account's own,
// "owner/name"; the field holds the name alone.
const review = (name: string, readable = false) => ({ owner: 'learner', repository: `learner/${name}`, readable, checkpoints: 3, review_sha256: `r-${name}`, reviewed_at: '2026-10-16T10:00:00Z' });

/** The follower as a fake: each request it is sent is answered by `answer` at its next read. */
function follower(answer: (request: Json) => Json) {
  const requests: Json[] = [];
  const writes: [string, string, unknown][] = [];
  let next = 0;
  const host: KeepHost = {
    worldId: WORLD,
    read: vi.fn(async (path: string) => {
      expect(path).toBe(`/world/github-projects${SCOPE}`);
      return { projects: [], requests: [], publications: requests.map((request) => ({ ...request, ...answer(request) })) };
    }),
    write: vi.fn(async (method: 'POST' | 'DELETE', path: string, body?: unknown) => {
      writes.push([method, path, body]);
      if (method === 'POST' && path === `/world/github-projects/publications${SCOPE}`) {
        const request = { request_id: `q${(next += 1)}`, project_id: (body as Json).project_id, name: (body as Json).name, review: null, refused: null };
        requests.splice(0, requests.length, request);
        return { status: 202, body: request };
      }
      if (method === 'POST' && path.endsWith(`/create${SCOPE}`)) return { status: 202, body: { ...requests[0], confirmed: body } };
      return { status: 204, body: null };
    }),
  };
  return { host, writes };
}

const field = (card: KeepCard) => card.element.querySelector('.wu-hr-keep-field') as HTMLInputElement;
const orb = (card: KeepCard) => card.element.querySelector('.wu-hr-keep-orb') as HTMLButtonElement;
const status = (card: KeepCard) => card.element.querySelector('.wu-hr-keep-status') as HTMLElement;
const text = (card: KeepCard) => [...card.element.querySelectorAll('.wu-hr-keep-line')].map((line) => line.textContent);

afterEach(() => { document.body.replaceChildren(); });

describe('Keep on GitHub, from History', () => {
  it('asks for a review, shows it, and Create says yes to exactly that review', async () => {
    const { host, writes } = follower((request) => ({ review: review(request.name ?? 'exulanica-terraces-on-the-bay') }));
    const done = { created: vi.fn(), closed: vi.fn() };
    const card = (await module()).openKeepCard(host, { project_id: 'project:demo', publications_per_day: 4 }, done, { pollMs: 0, settleMs: 0 });
    document.body.append(card.element);
    // Until the follower answers: checking, Create can say yes to nothing, and the rows a review fills are left out.
    expect(status(card).textContent).toBe('Checking your GitHub account…');
    expect(orb(card).disabled).toBe(true);
    expect((card.element.querySelector('.wu-hr-keep-reviewed') as HTMLElement).hidden).toBe(true);
    expect(writes[0]).toEqual(['POST', `/world/github-projects/publications${SCOPE}`, { project_id: 'project:demo', name: null }]);
    await vi.waitFor(() => expect(orb(card).disabled).toBe(false));
    expect((card.element.querySelector('.wu-hr-keep-reviewed') as HTMLElement).hidden).toBe(false);
    expect(card.element.querySelector('.wu-hr-keep-value')?.textContent).toBe('learner');
    expect([field(card).value, card.element.querySelector('.wu-hr-keep-count')?.textContent]).toEqual(['exulanica-terraces-on-the-bay', '29 of 100']);
    // What goes there, and nothing that explains the card (ROOT's sweep of 27 October).
    expect(text(card)).toEqual(["What goes there: this world's kept changes, without names or the words people wrote."]);
    expect(card.element.querySelector('.wu-hr-keep-question, .wu-hr-keep-once')).toBeNull();
    expect(card.keys().map((key) => `${key.keys.join('')} ${key.word}`)).toEqual(['Enter Create', 'Esc Back']);
    expect(card.key(new KeyboardEvent('keydown', { code: 'Enter', cancelable: true }))).toBe(true);
    await vi.waitFor(() => expect(done.created).toHaveBeenCalledTimes(1));
    expect(writes.at(-1)).toEqual(['POST', `/world/github-projects/publications/q1/create${SCOPE}`, { review_sha256: 'r-exulanica-terraces-on-the-bay' }]);
    expect(card.element.isConnected).toBe(false);
    expect(done.closed).not.toHaveBeenCalled();
  });

  it('checks a new name before Create can take it, and never sends one GitHub would refuse', async () => {
    const { host, writes } = follower((request) => ({ review: review(request.name ?? 'exulanica-world-3f9a12b4c5d6') }));
    const card = (await module()).openKeepCard(host, { project_id: 'project:demo' }, { created: vi.fn(), closed: vi.fn() }, { pollMs: 0, settleMs: 0 });
    document.body.append(card.element);
    await vi.waitFor(() => expect(orb(card).disabled).toBe(false));
    // A name GitHub would refuse is never sent and Create stays dimmed.
    field(card).value = 'my world';
    field(card).dispatchEvent(new Event('input'));
    expect(orb(card).disabled).toBe(true);
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(writes.filter(([method]) => method === 'POST')).toHaveLength(1);
    // A good one is checked; until its review is the name in the field, Create stays dimmed.
    field(card).value = 'bay-terraces';
    field(card).dispatchEvent(new Event('input'));
    expect(orb(card).disabled).toBe(true);
    await vi.waitFor(() => expect(writes.at(-1)).toEqual(['POST', `/world/github-projects/publications${SCOPE}`, { project_id: 'project:demo', name: 'bay-terraces' }]));
    await vi.waitFor(() => expect(orb(card).disabled).toBe(false));
    card.close();
  });

  it('says a refusal by its code in the refusal ink, and checks again by itself when the account changed', async () => {
    let asked = 0;
    const { host } = follower(() => ({ refused: { code: 'gh_missing', at: '2026-10-16T10:00:00Z' } }));
    const card = (await module()).openKeepCard(host, { project_id: 'project:demo' }, { created: vi.fn(), closed: vi.fn() }, { pollMs: 0 });
    document.body.append(card.element);
    await vi.waitFor(() => expect(status(card).textContent).toBe("GitHub's command line tool, gh, is not on this computer. Install it and sign in once, then try again."));
    expect([status(card).dataset.refused, orb(card).disabled]).toEqual(['true', true]);
    // Refused before any review: the account and name rows stay out.
    expect((card.element.querySelector('.wu-hr-keep-reviewed') as HTMLElement).hidden).toBe(true);
    card.close();

    const changing = follower((request) => (request.request_id === 'q1' ? { refused: { code: 'changed', at: '2026-10-16T10:00:00Z' } } : { review: review('exulanica-world-3f9a12b4c5d6') }));
    const again = (await module()).openKeepCard(changing.host, { project_id: 'project:demo' }, { created: vi.fn(), closed: vi.fn() }, { pollMs: 0 });
    document.body.append(again.element);
    await vi.waitFor(() => expect(orb(again).disabled).toBe(false));
    asked = changing.writes.filter(([method, path]) => method === 'POST' && path.startsWith('/world/github-projects/publications?')).length;
    expect(asked).toBe(2);
    expect(status(again).textContent).toBe('');
    again.close();
  });

  it('withdraws the request on Back, and on closing with the page', async () => {
    const { host, writes } = follower(() => ({}));
    const done = { created: vi.fn(), closed: vi.fn() };
    const card = (await module()).openKeepCard(host, { project_id: 'project:demo' }, done, { pollMs: 5 });
    document.body.append(card.element);
    await vi.waitFor(() => expect(writes).toHaveLength(1));
    expect(card.key(new KeyboardEvent('keydown', { code: 'Escape', cancelable: true }))).toBe(true);
    expect(done.closed).toHaveBeenCalledTimes(1);
    await vi.waitFor(() => expect(writes.at(-1)).toEqual(['DELETE', `/world/github-projects/requests/q1${SCOPE}`, undefined]));
    expect(card.element.isConnected).toBe(false);
    // Nothing is read once the card is gone.
    const reads = (host.read as ReturnType<typeof vi.fn>).mock.calls.length;
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect((host.read as ReturnType<typeof vi.fn>).mock.calls.length).toBe(reads);
  });

  it('reads Create as ready only for the reviewed name and only while nothing is being made', async () => {
    const { keepState } = await module();
    expect(keepState(null, '').checking).toBe(true);
    const reviewed = { review: review('bay-terraces') };
    expect(keepState(reviewed, 'bay-terraces')).toMatchObject({ ready: true, account: 'learner', proposed: 'bay-terraces' });
    // The account's name is never part of the name in the field.
    expect(keepState(reviewed, 'learner/bay-terraces').ready).toBe(false);
    expect(keepState(reviewed, 'bay-terraces', true).ready).toBe(false);
    expect(keepState(reviewed, 'other-name').ready).toBe(false);
    expect(keepState({ refused: { code: 'name_taken' } }, 'bay-terraces')).toMatchObject({ ready: false, refusal: 'You already have a repository with that name. Choose another.' });
    expect(keepState({ refused: { code: 'something new' } }, 'x').refusal).toBe('This could not be put on GitHub. Look on GitHub before you try again.');
  });
});
