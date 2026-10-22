// [G] Keep on GitHub from History (DESIGN's WORDS.md H12; the R23 build sheet, section 13): H12's question as a card
// at the top right of the light page. Opening it asks the project's follower to review putting the project in a new
// private repository on the person's own GitHub (POST /world/github-projects/publications); the card shows that
// review (the account, the proposed name, what goes there) and Create says yes to it (POST .../{request_id}/create).
// The follower does the rest with the person's own gh sign-in; nothing here sees a token. Back withdraws the request.
import './world-ui-history-keep.css';
import { KEEP_WORDS, nameAllowed, nameCount, refusalWords, sendingWords } from './history-keep-words.mjs';

type Json = Record<string, any>;

export interface KeepHost {
  readonly worldId: string;
  /** GET through the workspace's reader; throws where the server does not answer 200. */
  read(path: string): Promise<any>;
  /** POST or DELETE through the workspace's credentials: the status and the answer's body (null where none). */
  write(method: 'POST' | 'DELETE', path: string, body?: unknown): Promise<{ readonly status: number; readonly body: any }>;
}

export interface KeepProject {
  readonly project_id: string;
  /** At most how many times a day the follower sends changes on its own, as its status serves it. */
  readonly publications_per_day?: number | null;
}

export interface KeepKey { readonly keys: readonly string[]; readonly word: string; press(): void }

export interface KeepCard {
  readonly element: HTMLElement;
  /** The keys the page's row shows while the card is open: H12's alone, and only what works now (GH4). */
  keys(): readonly KeepKey[];
  /** A key while the card is open; true when the card took it. */
  key(event: KeyboardEvent): boolean;
  /** Takes the card away, withdrawing a request not yet said yes to. */
  close(): void;
}

/** The refusals the person mends on this computer (installing gh, signing in): Enter reads the sign-in again (GH4). */
const MENDED_HERE: ReadonlySet<string> = new Set(['gh_missing', 'not_signed_in']);

/** What the card says of the publication request the follower last wrote (pure; the tests read it). */
export function keepState(publication: Json | null, name: string, creating = false) {
  if (!publication) return { checking: true, refusal: null, account: null, proposed: null, readable: null, ready: false };
  if (publication.refused) {
    return { checking: false, refusal: refusalWords(publication.refused.code), code: publication.refused.code as string, account: null, proposed: null, readable: null, ready: false };
  }
  const review = publication.review;
  if (!review) return { checking: true, refusal: null, account: null, proposed: null, readable: null, ready: false };
  // The follower reviews "owner/name" (the account's own repository); the field holds the name, the account shows apart.
  const proposed = String(review.repository).split('/').pop() as string;
  return {
    checking: false, refusal: null, account: review.owner as string, proposed, readable: review.readable === true,
    // Create says yes to exactly what was reviewed: the name in the field is the reviewed one.
    ready: !creating && nameAllowed(name) && name === proposed,
  };
}

function element<K extends keyof HTMLElementTagNameMap>(tag: K, className = '', words = ''): HTMLElementTagNameMap[K] {
  const made = document.createElement(tag);
  if (className) made.className = className;
  if (words) made.textContent = words;
  return made;
}

export function openKeepCard(host: KeepHost, project: KeepProject, done: { created(): void; closed(): void; changed?(): void }, { pollMs = 1500, settleMs = 600 } = {}): KeepCard {
  const scope = `?world_id=${encodeURIComponent(host.worldId)}`;
  const lifetime = new AbortController();
  let request: Json | null = null;
  let publication: Json | null = null;
  let name = '';
  let edited = false;
  let creating = false;
  let failure: string | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let settle: ReturnType<typeof setTimeout> | null = null;
  /** The keys the page was last told of, so it is told again only when they change. */
  let told = '';

  const card = element('section', 'wu-hr-keepcard');
  card.setAttribute('aria-label', KEEP_WORDS.keepOnGitHub);
  const label = element('div', 'wu-hr-keep-label', KEEP_WORDS.keepOnGitHub);
  label.tabIndex = -1;
  const accountValue = element('div', 'wu-hr-keep-value');
  const field = element('input', 'wu-hr-keep-field');
  field.type = 'text';
  field.maxLength = 100;
  field.spellcheck = false;
  field.autocomplete = 'off';
  field.setAttribute('aria-label', KEEP_WORDS.name);
  const count = element('div', 'wu-hr-keep-count');
  const what = element('p', 'wu-hr-keep-line');
  const status = element('p', 'wu-hr-keep-status');
  status.setAttribute('role', 'status');
  const orb = element('button', 'wu-hr-keep-orb', KEEP_WORDS.create);
  orb.type = 'button';
  // The rows a review answers (H12, 14:07): left out until the follower has read the account and proposed the name.
  const reviewed = element('div', 'wu-hr-keep-reviewed');
  reviewed.append(
    element('div', 'wu-hr-keep-name', KEEP_WORDS.account), accountValue,
    element('div', 'wu-hr-keep-name', KEEP_WORDS.name), field, count,
    element('p', 'wu-hr-keep-line', KEEP_WORDS.private), what,
    element('p', 'wu-hr-keep-line', sendingWords(project.publications_per_day ?? null)),
  );
  card.append(
    label,
    element('h2', 'wu-hr-keep-question', KEEP_WORDS.question),
    reviewed,
    element('p', 'wu-hr-keep-line', KEEP_WORDS.signIn),
    status,
    element('div', 'wu-hr-keep-make', ''),
  );
  const make = card.lastElementChild as HTMLElement;
  make.append(orb, element('div', 'wu-hr-keep-once', KEEP_WORDS.madeOnce));

  function draw() {
    // The follower's proposed name fills the field until the person types one of their own.
    const proposed = keepState(publication, name, creating).proposed;
    if (!edited && proposed && field.value !== proposed) {
      name = proposed;
      field.value = name;
    }
    const view = keepState(publication, name, creating);
    reviewed.hidden = view.account === null;
    accountValue.textContent = view.account ?? '';
    count.textContent = nameCount(field.value);
    what.textContent = view.readable === null ? '' : view.readable ? KEEP_WORDS.readable : KEEP_WORDS.notReadable;
    const refusal = failure ?? view.refusal;
    status.textContent = refusal ?? (view.checking || creating ? KEEP_WORDS.checking : '');
    status.dataset.refused = String(refusal !== null);
    orb.disabled = !view.ready || failure !== null;
    const now = keys().map((key) => key.word).join();
    if (now !== told) {
      told = now;
      done.changed?.();
    }
  }

  /** Enter as it works now (GH4): Create once the review is the name in the field, Try again where the person mends
   * the refusal on this computer, else nothing. */
  function enter(): KeepKey | null {
    const view = keepState(publication, name, creating);
    if (view.ready && failure === null) return { keys: ['Enter'], word: KEEP_WORDS.create, press: () => void create() };
    if (failure === null && MENDED_HERE.has(view.code ?? '')) return { keys: ['Enter'], word: KEEP_WORDS.tryAgain, press: () => again() };
    return null;
  }

  function keys(): KeepKey[] {
    const now = enter();
    return [...(now ? [now] : []), { keys: ['Esc'], word: KEEP_WORDS.back, press: () => back() }];
  }

  /** Reads the sign-in again: a new request, which the follower reviews from the start. */
  function again() {
    void ask(edited ? name : null);
  }

  /** Asks the follower to review the project under `wanted` (null: the follower proposes the name). */
  async function ask(wanted: string | null) {
    stopPolling();
    publication = null;
    failure = null;
    draw();
    try {
      const answer = await host.write('POST', `/world/github-projects/publications${scope}`, { project_id: project.project_id, name: wanted });
      if (lifetime.signal.aborted) return;
      if (answer.status !== 202) {
        failure = refusalWords('failed');
        draw();
        return;
      }
      request = answer.body;
      poll();
    } catch {
      if (!lifetime.signal.aborted) {
        failure = refusalWords('failed');
        draw();
      }
    }
  }

  function stopPolling() {
    if (timer !== null) clearTimeout(timer);
    timer = null;
  }

  /** Reads the follower's answer until the review or a refusal is there. */
  function poll() {
    stopPolling();
    timer = setTimeout(async () => {
      if (lifetime.signal.aborted || !request) return;
      try {
        const read = await host.read(`/world/github-projects${scope}`);
        if (lifetime.signal.aborted) return;
        publication = (read.publications ?? []).find((one: Json) => one.request_id === request!.request_id) ?? null;
      } catch {
        publication = null;
      }
      // An account or name that changed since it was checked is checked again by itself.
      if (publication?.refused?.code === 'changed') {
        void ask(edited ? name : null);
        return;
      }
      draw();
      if (!publication?.review && !publication?.refused) poll();
    }, pollMs);
  }

  async function create() {
    const view = keepState(publication, name, creating);
    if (!view.ready || !request || failure !== null) return;
    creating = true;
    draw();
    try {
      const answer = await host.write('POST', `/world/github-projects/publications/${encodeURIComponent(request.request_id)}/create${scope}`, { review_sha256: publication!.review.review_sha256 });
      if (lifetime.signal.aborted) return;
      if (answer.status === 202 || answer.body?.code === 'publication_started') {
        request = null;
        remove();
        done.created();
        return;
      }
      creating = false;
      if (answer.body?.code === 'publication_review_changed') {
        void ask(edited ? name : null);
        return;
      }
      failure = refusalWords(answer.body?.code === 'publication_refused' ? publication?.refused?.code ?? 'failed' : 'failed');
      draw();
    } catch {
      creating = false;
      if (!lifetime.signal.aborted) {
        failure = refusalWords('failed');
        draw();
      }
    }
  }

  function remove() {
    lifetime.abort();
    stopPolling();
    if (settle !== null) clearTimeout(settle);
    card.remove();
  }

  function back() {
    // A request not said yes to is withdrawn, so the follower does not keep a review nobody will use.
    const waiting = request;
    remove();
    if (waiting) void host.write('DELETE', `/world/github-projects/requests/${encodeURIComponent(waiting.request_id)}${scope}`).catch(() => null);
    done.closed();
  }

  field.addEventListener('input', () => {
    name = field.value;
    edited = true;
    failure = null;
    draw();
    if (settle !== null) clearTimeout(settle);
    // A new name is checked once the person stops typing; an invalid one is not sent.
    if (nameAllowed(name)) settle = setTimeout(() => void ask(name), settleMs);
  });
  field.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      void create();
    } else if (event.key === 'Escape') {
      event.preventDefault();
      back();
    }
    event.stopPropagation();
  });
  orb.addEventListener('click', () => void create());
  // A sign-in made in the terminal meanwhile shows when the page has the focus back, without Esc and G (GH4).
  const mendedMeanwhile = () => {
    const view = keepState(publication, name, creating);
    if (!document.hidden && MENDED_HERE.has(view.code ?? '')) again();
  };
  window.addEventListener('focus', mendedMeanwhile, { signal: lifetime.signal });
  document.addEventListener('visibilitychange', mendedMeanwhile, { signal: lifetime.signal });

  draw();
  void ask(null);
  queueMicrotask(() => label.focus({ preventScroll: true }));

  return {
    element: card,
    keys,
    key(event) {
      if (event.code === 'Tab') return false;
      if (event.code === 'Enter') {
        // Enter on the field is the field's; on the orb, the orb's own click.
        if ((event.target as Element | null)?.closest?.('.wu-hr-keep-field, .wu-hr-keep-orb')) return false;
        event.preventDefault();
        enter()?.press();
        return true;
      }
      if (event.code === 'Escape') {
        event.preventDefault();
        back();
        return true;
      }
      return false;
    },
    close: () => {
      const waiting = request;
      remove();
      if (waiting) void host.write('DELETE', `/world/github-projects/requests/${encodeURIComponent(waiting.request_id)}${scope}`).catch(() => null);
    },
  };
}
