// History (r23, the user's yes on 16 October; DESIGN's R23 build sheet, amended 08:36): the world's story on a light
// page over the world faded behind it, read left to right: how the world began, each moment the characters made (its
// picture, the people's portraits, what happened, the lines said, who decided, another model's answer: the same as one
// small line, a different one as a faded branch), the person's own changes as small dots, the runs as brackets, and
// Now. Enter opens the chosen moment, or a grouped changes dot's list, on the same page. It reads the server alone (GET through the workspace's reader);
// the path and the views come from history-rows.mjs and every word from history-words.mjs. Pictures and portraits are
// made one at a time where the host can make them, and the making stops when the page closes.
// The record pages' shared parts load first: History's own stylesheet refines them and must come after.
import { ORBS, element, keyButton, orbs as recordOrbs, pictureBox, px, sentence } from './world-ui-record.ts';
import { changeParts, thingName } from './build-words.mjs';
import { LAYOUTS, historyPath, pathLayout, pathView, rowsWindow, targetObject } from './history-rows.mjs';
import { openKeepCard, type KeepCard } from './history-keep.ts';
import { KEEP_WORDS } from './history-keep-words.mjs';
import { PATH_WORDS, headLine } from './history-words.mjs';
import { page } from './world-ui.ts';
import { storySvg, svgPart } from './world-ui-history.ts';

/** A world generated from words: its draft is read for how it began. */
const GENERATED = 'world:generated:';
/** The newest runs whose own read is fetched for their bracket. */
const RUNS_READ = 20;
/** Narrower than this, the page takes its 1440 sizes. */
const NARROW_BELOW = 1700;
/** While a project is being started or put on GitHub, the projects read is asked again this often. */
const WATCH_MS = 3000;

type Json = Record<string, any>;
export interface Picture { readonly sha256: string; readonly width: number; readonly height: number }

/** The characters History's path names: society subjects (moments, models) and placed beings (personalities). */
export interface Named {
  readonly subjects: readonly string[];
  readonly placed: readonly string[];
}

export interface HistoryHost {
  /** Where the page is appended: the world's root, whose corners hide while a page is open. */
  readonly root: HTMLElement;
  readonly worldId: string;
  readonly versionId: string;
  /** The world's title as written. */
  readonly title: string;
  /** GET through the workspace's reader; throws where the server does not answer 200. */
  read(path: string): Promise<any>;
  /** What these characters are called inside a sentence, as the tag and card call them (J20). */
  names(named: Named): Promise<{ subject(id: string): string; placed(id: string): string; speaker?(id: string): string }>;
  /** The labels of the kinds a workspace made (J20): `label(kind)`, and `listen` for each that lands. */
  readonly kindLabels: { label(kind: unknown): string | null; listen(listener: () => void): () => void };
  /** The world's clock for a tick: its time and day ("06:52", day 1), where the clock is read. */
  worldClock?(tick: number): { readonly hhmm: string; readonly day: number } | null;
  /** The world's minute now, from its live clock, for Now's time where the moments read does not answer. */
  worldNow?(): number | null;
  /** The world's time for a tick alone, where only that is known. */
  worldTime?(tick: number): string | null;
  /** A still of what the world was showing as History opened, as an image address. */
  still?(): string | null;
  /** The saved entry's own picture, where one was kept, as an image address. */
  readonly entryPicture?: string | null;
  /** How the world began, where no entry picture was kept: one first-view render, kept (MOTION's renderer). */
  beginningPicture?(signal: AbortSignal): Promise<string | null>;
  /** The address of a kept picture (a moment's), read once while the page is open; null where it cannot be read. The
   * host keeps the addresses it makes until the page closes, so the page forgets them then. */
  pictureAddress?(picture: Picture, signal: AbortSignal): Promise<string | null>;
  /** Makes a moment's missing picture once (MOTION's renderer); null where it cannot be made. */
  renderMomentPicture?(moment: Json, signal: AbortSignal): Promise<Picture | null>;
  /** A character's round portrait, made once from its look, as an image address; null where it cannot be made. */
  portrait?(subjectId: string, signal: AbortSignal): Promise<string | null>;
  /** Opens the chosen line's decision, or a moment's one decision, in the decision view (frame 10): by its request
   * where the moments read names one, else by the moment, the minute and who decided. */
  openDecision?(decision: { readonly momentId: string; readonly requestId: string | null; readonly tick: number; readonly subject: string | null }): void;
  /** Build mode's undo and redo: not offered here (undo stays in build mode); kept for the host's shape. */
  readonly build?: unknown;
  /** POST or DELETE through the workspace's credentials (H7's keep, H12's question); absent on a read-only copy. */
  readonly write?: ((method: 'POST' | 'DELETE', path: string, body?: unknown) => Promise<{ readonly status: number; readonly body: any }>) | null;
  /** Opens a link outside the workspace (the GitHub project). */
  open(url: string): void;
  /** The page closed: give the world its keys and focus back. */
  closed(): void;
}

export interface History {
  open(): Promise<void>;
  close(): void;
  /** Removes the page with its world, giving nothing back (the world is going). */
  dispose(): void;
  /** A key while the page is open; true when the page took it. */
  key(event: KeyboardEvent): boolean;
  readonly isOpen: boolean;
}

export function mountHistory(host: HistoryHost): History {
  const scope = `?world_id=${encodeURIComponent(host.worldId)}`;
  const version = `/world/versions/${encodeURIComponent(host.versionId)}`;
  const optional = async (path: string): Promise<any> => {
    try {
      return await host.read(path);
    } catch {
      return null;
    }
  };
  const clock = (tick: number) => {
    if (!Number.isInteger(tick)) return null;
    const read = host.worldClock?.(tick);
    if (read) return read;
    const hhmm = host.worldTime?.(tick) ?? null;
    return hhmm ? { hhmm, day: 0 } : null;
  };

  let made: ReturnType<typeof page> | null = null;
  let path: ReturnType<typeof historyPath> | null = null;
  let project: Json | null | undefined;
  let request: Json | null = null;
  let momentsFailed = false;
  let state: 'loading' | 'ready' | 'offline' = 'loading';
  let chosen: string | null = null;
  /** The moment or grouped changes opened over the story: a moment's chosen line, a list's row at its top (H15). */
  let opened: { readonly id: string; line: number; first: number } | null = null;
  /** How far the line has slid, kept between draws so a choice in view moves nothing. */
  let offset: number | null = null;
  let held: { readonly compose: () => ReturnType<typeof historyPath> } | null = null;
  let unlisten: (() => void) | null = null;
  let making: AbortController | null = null;
  /** What the characters are called, from the last read. */
  let called: { subject(id: string): string; speaker?(id: string): string } = { subject: () => '' };
  /** The page's lasting parts, made once when it opens, so the focus on its title stays through every draw. */
  let lasting: { readonly world: HTMLElement; readonly head: HTMLElement; readonly kept: HTMLElement; readonly layer: HTMLElement } | null = null;
  /** H12's question, while it is open over the page. */
  let card: KeepCard | null = null;
  /** After Create, until the follower links the project: the head says it is being put on GitHub. */
  let putting = false;
  /** A server that keeps no projects answers K once; K is not offered again there. */
  let keepsProjects = true;
  let watching: ReturnType<typeof setTimeout> | null = null;
  /** The card just opened: the story under it fades out over a frame rather than vanishing. */
  let fadeNext = false;
  /** The card grows when its review answers: what lies under it is measured again then. */
  let cardSize: ResizeObserver | null = null;
  /** Pictures and portraits made while the page is open, by moment and by subject. */
  const pictures = new Map<string, string | null>();
  const portraits = new Map<string, string | null>();

  async function reads() {
    const generated = host.worldId.startsWith(GENERATED);
    const [view, parts, models, characters, listed, projects, draft, moments] = await Promise.all([
      host.read(`${version}${scope}`),
      optional(`${version}/parts${scope}`),
      optional(`${version}/society/models/history${scope}`),
      optional(`${version}/things/characters/history${scope}`),
      optional(`${version}/society/control/sessions${scope}`),
      optional(`/world/github-projects${scope}`),
      generated ? optional(`/worlds/drafts/${encodeURIComponent(host.worldId.slice(GENERATED.length))}`) : null,
      optional(`${version}/history/moments${scope}`),
    ]);
    momentsFailed = moments === null;
    // Placed things and made parts named as build mode names them: by kind (a made creature by its label, J20),
    // by the parts read's label; a building's storeys change is build mode's too (W6).
    const things = new Map<string, Json>((view.things ?? []).map((thing: Json) => [thing.thing_id, thing]));
    const thingOf = (id: unknown) => (typeof id === 'string' && things.has(id) ? thingName(things.get(id), host.kindLabels.label) : null);
    const partLabels = new Map<string, string>((parts?.parts ?? []).map((part: Json) => [part.part_id, part.label]));
    const partNameOf = (id: string) => partLabels.get(id) ?? null;
    const sessions: Json[] = (listed?.sessions ?? []).slice(0, RUNS_READ);
    const runs = (await Promise.all(sessions.map((one) => optional(`${version}/society/control/sessions/${encodeURIComponent(one.session_id)}${scope}`))))
      .filter(Boolean)
      .map((run: Json) => ({
        session_id: run.session_id,
        start_tick: run.opened?.start_tick,
        end_tick: run.closed?.end_tick ?? null,
        spent: run.used?.usd ?? '0',
        ends_by: run.opened?.ends_by ?? null,
        closed: run.closed ?? null,
        world_minutes: run.used?.minutes ?? null,
      }));
    const momentList: Json[] = moments?.moments ?? [];
    const records: Json[] = characters?.records ?? [];
    const choices: Json[] = models?.choices ?? [];
    const named = await host.names({
      subjects: [...new Set<string>([
        ...momentList.flatMap((one) => [
          ...(one.subjects ?? []),
          ...(one.said ?? []).map((line: Json) => line.by),
          ...(one.branches ?? []).flatMap((branch: Json) => [branch.with, branch.by]).filter((id: unknown) => typeof id === 'string'),
        ]),
        ...choices.flatMap((one) => one.subjects ?? []),
      ])],
      placed: [...new Set<string>(records.map((record) => record.placed_id))],
    });
    called = named;
    const names = {
      subject: (id: string) => named.subject(id),
      // Who said a line, in J20's title form where a kind names them ("Canopy strider").
      speaker: (id: string) => named.speaker?.(id) ?? named.subject(id),
      placed: (id: string) => named.placed(id),
      thing: (id: string) => thingOf(id),
      place: (place: Json) => thingOf(place?.thing_id),
      // A going's target is a placed thing's use (named as build mode names it) or a destination with no name.
      target: (target: Json) => thingOf(targetObject(target?.target_id)),
    };
    project = projects ? (projects.projects ?? []).find((one: Json) => one.version_id === host.versionId) ?? null : undefined;
    request = (projects?.requests ?? []).find((one: Json) => one.version_id === host.versionId) ?? null;
    const creation = draft
      ? { at: draft.started_at, readyWorld: null, sentence: draft.description || null, picture: host.entryPicture ?? null }
      : null;
    const nowTick = moments?.now?.tick ?? host.worldNow?.() ?? null;
    const listing = { creation, edits: view.edits ?? [], models: choices, characters: records, runs, moments: momentList, nowTick };
    held = { compose: () => historyPath(listing, names, (edit: Json, edits: Json[]) => changeParts(edit, edits, (id: string) => thingOf(id), partNameOf), clock, Date.now()) };
    path = held.compose();
    const newest = [...path.items].reverse().find((item: Json) => item.kind === 'moment');
    if (!chosen || !path.items.some((item: Json) => item.id === chosen)) chosen = newest?.id ?? null;
  }

  async function load() {
    state = 'loading';
    draw();
    try {
      await reads();
      state = 'ready';
    } catch {
      state = 'offline';
    }
    draw();
    void makePictures();
  }

  /** Makes each missing picture and portrait once, one at a time, the chosen moment's first; stops on close. */
  async function makePictures() {
    making?.abort();
    const controller = new AbortController();
    making = controller;
    const order = [...moments()].sort((a, b) => Number(b.id === chosen) - Number(a.id === chosen) || b.at - a.at);
    const creation = (path?.items ?? []).find((item: Json) => item.kind === 'creation');
    if (creation && !creation.picture && host.beginningPicture && !pictures.has(creation.id)) {
      const address = await host.beginningPicture(controller.signal).catch(() => null);
      if (controller.signal.aborted) return;
      pictures.set(creation.id, address);
      draw();
    }
    for (const moment of order) {
      if (controller.signal.aborted) return;
      // A kept picture is read at its address; a missing one is made once, then read.
      if (!pictures.has(moment.id) && host.pictureAddress && (moment.picture || host.renderMomentPicture)) {
        const kept = moment.picture ?? (await host.renderMomentPicture?.(moment, controller.signal).catch(() => null)) ?? null;
        if (controller.signal.aborted) return;
        const address = kept ? await host.pictureAddress(kept as Picture, controller.signal).catch(() => null) : null;
        if (controller.signal.aborted) return;
        pictures.set(moment.id, address);
        draw();
      }
      for (const subject of moment.subjects.slice(0, ORBS)) {
        if (controller.signal.aborted || portraits.has(subject) || !host.portrait) continue;
        portraits.set(subject, await host.portrait(subject, controller.signal).catch(() => null));
        if (controller.signal.aborted) return;
        draw();
      }
    }
  }

  function pictureOf(item: Json): string | null {
    // How the world began carries the entry picture's address; a moment, its kept picture's or one made here.
    if (typeof item.picture === 'string') return item.picture;
    return pictures.get(item.id) ?? null;
  }

  function moments(): Json[] {
    return (path?.items ?? []).filter((item: Json) => item.kind === 'moment');
  }

  /** Where [←] [→] stop: each moment and each grouped changes dot (H15); a single change is passed over. */
  function stops(): Json[] {
    return (path?.items ?? []).filter((item: Json) => item.kind === 'moment' || (item.kind === 'change' && item.changes));
  }

  function move(by: number) {
    const list = stops();
    const index = list.findIndex((item) => item.id === chosen);
    const next = list[Math.min(list.length - 1, Math.max(0, (index < 0 ? list.length - 1 : index) + by))];
    if (next && next.id !== chosen) {
      chosen = next.id;
      draw();
    }
  }

  /** Reads where the world is kept again while a project is being started or put on GitHub, until it settles. */
  function watchProjects() {
    if (watching !== null) clearTimeout(watching);
    watching = null;
    const unsettled = (project === null && request && !request.refused) || (putting && project && !project.link);
    if (!made || !unsettled) return;
    watching = setTimeout(async () => {
      watching = null;
      if (!made) return;
      try {
        const projects = await host.read(`/world/github-projects${scope}`);
        project = (projects.projects ?? []).find((one: Json) => one.version_id === host.versionId) ?? null;
        request = (projects.requests ?? []).find((one: Json) => one.version_id === host.versionId) ?? null;
        if (project?.link) putting = false;
      } catch {
        // A read that fails is asked again at the next turn.
      }
      draw();
      watchProjects();
    }, WATCH_MS);
  }

  /** [K] Keep in a project (H7): asked of the server at once, readable text not kept. */
  async function keepInProject() {
    if (!host.write || !offersKeep()) return;
    const answer = await host.write('POST', `/world/github-projects${scope}`, { version_id: host.versionId, readable: false }).catch(() => null);
    if (!made) return;
    if (answer?.status === 202) request = answer.body;
    else if (answer?.status === 409 && answer.body?.code === 'projects_not_kept') keepsProjects = false;
    else request = { version_id: host.versionId, refused: { code: 'failed' } };
    draw();
    watchProjects();
  }

  /** K is offered where no project keeps the world and none is being started; G Keep on GitHub where a project is
   * kept on this computer only. Neither on a read-only copy, nor where it could only fail. */
  function offersKeep(): boolean {
    return Boolean(host.write) && keepsProjects && state === 'ready' && project === null && (!request || Boolean(request.refused));
  }

  function offersGitHub(): boolean {
    return Boolean(host.write) && state === 'ready' && !putting && Boolean(project && !project.link && project.project_id);
  }

  function keepOnGitHub() {
    if (!offersGitHub() || card || !made) return;
    opened = null;
    fadeNext = true;
    const unwatch = () => {
      cardSize?.disconnect();
      cardSize = null;
    };
    card = openKeepCard({ worldId: host.worldId, read: host.read, write: host.write! }, project as { project_id: string; publications_per_day?: number | null }, {
      created: () => {
        unwatch();
        card = null;
        putting = true;
        draw();
        watchProjects();
      },
      closed: () => {
        unwatch();
        card = null;
        draw();
      },
    });
    if (typeof ResizeObserver !== 'undefined') {
      cardSize = new ResizeObserver(() => {
        if (card && lasting) fadeUnderCard(lasting.layer);
      });
      cardSize.observe(card.element);
    }
    draw();
  }

  function githubUrl(): string | null {
    if (!project?.link) return null;
    const pull = project.github?.pull_request;
    return pull ? `https://github.com/${project.link.repository}/pull/${pull.number}` : `https://github.com/${project.link.repository}`;
  }

  /** The people's round portraits: a made portrait, or the first letter of the name as the tag says it. */
  function orbs(subjects: readonly string[], size: number): HTMLDivElement {
    return recordOrbs(subjects, size, (id) => portraits.get(id), (id) => called.subject(id));
  }

  /** A card's words: time, title, the creation's quote or the first lines said, who decided, a same answer. */
  function cardText(item: Json): HTMLDivElement {
    const text = element('div', 'wu-hr-text');
    if (item.when) text.append(element('div', 'wu-hr-time', item.when));
    text.append(element('div', 'wu-hr-words', item.words));
    if (item.kind === 'creation' && item.quote) text.append(element('div', 'wu-hr-said quote', `“${item.quote}”`));
    for (const said of item.shown ?? []) text.append(element('div', 'wu-hr-said', said));
    if (item.more) text.append(element('div', 'wu-hr-more', item.more));
    if (item.by) text.append(sentence('div', 'wu-hr-who', item.by));
    if (item.same) text.append(sentence('div', 'wu-hr-who same', item.same));
    return text;
  }

  function draw() {
    if (!made) return;
    const width = host.root.clientWidth || window.innerWidth;
    const narrow = width < NARROW_BELOW;
    const layout = narrow ? LAYOUTS.narrow : LAYOUTS.wide;
    made.root.classList.toggle('wu-hr-narrow', narrow);
    made.root.classList.toggle('wu-hr-opened', opened !== null);
    if (!lasting) {
      const world = element('div', 'wu-hr-world');
      const head = element('div', 'wu-hr-head');
      const title = element('h1', 'wu-hr-title', host.title);
      title.tabIndex = -1;
      const kept = element('p', 'wu-hr-kept');
      head.append(element('div', 'wu-hr-over', PATH_WORDS.history), title, kept);
      const layer = element('div', 'wu-hr-layer');
      made.content.replaceChildren(world, element('div', 'wu-hr-wash'), head, layer, element('div', 'wu-hr-cardslot'));
      lasting = { world, head, kept, layer };
    }
    const ground = host.still?.() ?? host.entryPicture ?? null;
    lasting.world.style.backgroundImage = ground ? `url("${ground}")` : '';
    const kept = headLine(project, request, putting);
    lasting.kept.textContent = kept.words;
    lasting.kept.dataset.refused = String(kept.refused);
    const content = lasting.layer;
    content.replaceChildren();

    const story = element('div', 'wu-hr-story');
    const track = element('div', 'wu-hr-track');
    story.append(track);
    content.append(story);
    const items: Json[] = state === 'ready' ? path?.items ?? [] : [];
    const placed = pathLayout(items, layout);
    const view = pathView(items, placed, layout, width, chosen, offset);
    offset = view.offset;
    track.style.transform = `translateX(${view.offset}px)`;
    const local = (screen: number) => screen - view.offset;
    const svg = storySvg(Math.max(width, placed.nowAt + layout.margin) - Math.min(0, view.offset), Math.max(layout.lineY + 360, (made.root.clientHeight || window.innerHeight)));
    if (state === 'ready') svg.append(svgPart('path', { d: `M ${local(view.from)} ${layout.lineY} L ${local(view.to)} ${layout.lineY}` }, 'line'));
    track.append(svg);

    for (const span of path?.spans ?? []) {
      if (!view.drawn.has(span.first) || !view.drawn.has(span.last)) continue;
      const from = placed.x.get(span.first)!;
      const right = placed.x.get(span.last)! + layout.card;
      svg.append(svgPart('path', { d: `M ${from} ${layout.bracketY + 8} L ${from} ${layout.bracketY} L ${right} ${layout.bracketY} L ${right} ${layout.bracketY + 8}` }, 'bracket'));
      const words = element('div', 'wu-hr-run', span.words);
      px(words, from, layout.bracketY - 22);
      track.append(words);
    }

    for (const item of items) {
      if (!view.drawn.has(item.id)) continue;
      const x = placed.x.get(item.id)!;
      if (item.kind === 'change') {
        svg.append(svgPart('circle', { cx: x, cy: layout.lineY, r: 4 }, 'dot small'));
        // A grouped dot is a stop: chosen it gains a ring and dark words, and it opens on a click (H15).
        const group = Boolean(item.changes);
        const words = element(group ? 'button' : 'div', 'wu-hr-change');
        if (group) {
          const open = () => openMoment(item.id);
          if (item.id === chosen) {
            svg.append(svgPart('circle', { cx: x, cy: layout.lineY, r: 9 }, 'ring'));
            words.setAttribute('aria-current', 'true');
          }
          const hit = svgPart('circle', { cx: x, cy: layout.lineY, r: 12 }, 'hit');
          hit.addEventListener('click', open);
          svg.append(hit);
          (words as HTMLButtonElement).type = 'button';
          words.addEventListener('click', open);
        }
        if (item.when) words.append(element('div', 'wu-hr-time', item.when));
        words.append(sentence('div', 'wu-hr-change-words', item.words));
        track.append(words);
        // Its last line 16px above the line: placed by its own height where the page is laid out.
        words.style.left = `${x - 70}px`;
        const height = words.offsetHeight;
        words.style.top = `${layout.lineY - 16 - (height > 0 ? height : 78)}px`;
        continue;
      }
      if (item.kind === 'day') {
        const mark = element('div', 'wu-hr-day', item.words);
        px(mark, x, layout.lineY - 22);
        track.append(mark);
        continue;
      }
      const isChosen = item.id === chosen;
      const dot = svgPart('circle', { cx: x, cy: layout.lineY, r: 6 }, 'dot');
      dot.setAttribute('data-chosen', String(isChosen && item.kind === 'moment'));
      svg.append(dot);
      const card = element(item.kind === 'moment' ? 'button' : 'div', item.kind === 'creation' ? 'wu-hr-card first' : 'wu-hr-card');
      if (card instanceof HTMLButtonElement) card.type = 'button';
      if (isChosen && item.kind === 'moment') card.setAttribute('aria-current', 'true');
      card.style.width = `${layout.card + 30}px`;
      px(card, x, layout.lineY - layout.picture);
      const box = pictureBox(pictureOf(item), layout.card, layout.picture);
      if (item.kind === 'moment' && item.subjects.length) box.append(orbs(item.subjects, layout.orb));
      const text = cardText(item);
      card.append(box, text);
      if (item.kind === 'moment') {
        card.addEventListener('click', () => {
          if (chosen === item.id) openMoment(item.id);
          else {
            chosen = item.id;
            draw();
          }
        });
      }
      track.append(card);
      if (item.branch) {
        // The branch card's top sits 16px under the box of its moment's last line of text, never at a fixed y.
        const last = text.lastElementChild as HTMLElement | null;
        const bottom = last && last.offsetHeight > 0 ? layout.lineY - layout.picture + last.offsetTop + last.offsetHeight : 0;
        const top = bottom > 0 ? Math.round(bottom + layout.branchUnder) : layout.branchY;
        const meet = top + layout.branchMeet;
        svg.append(svgPart('path', { d: `M ${x} ${layout.lineY} L ${x} ${meet - 11} Q ${x} ${meet} ${x + 11} ${meet} L ${x + 32} ${meet}` }, 'branch'));
        const ghost = element('div', 'wu-hr-ghost');
        ghost.style.width = `${layout.branchWords}px`;
        px(ghost, x + 32, top);
        const ghostText = element('div', 'wu-hr-text');
        ghostText.append(sentence('div', 'wu-hr-words', item.branch.head), element('div', 'wu-hr-said', item.branch.outcome));
        ghost.append(pictureBox(pictureOf(item), layout.branchCard, layout.branchPicture), ghostText);
        track.append(ghost);
      }
    }

    // Nothing on the story line enters the 24px over the key row's caps (H15): a card or a branch that would reach
    // that band keeps its words to one line.
    const band = (host.root.clientHeight || window.innerHeight) - layout.band;
    for (const part of track.querySelectorAll<HTMLElement>('.wu-hr-card, .wu-hr-ghost')) {
      if (part.offsetHeight > 0 && part.offsetTop + part.offsetHeight > band) part.classList.add('wu-hr-clamped');
    }

    if (state === 'ready' && view.now !== null) {
      svg.append(svgPart('circle', { cx: local(view.now), cy: layout.lineY, r: 9 }, 'now'), svgPart('circle', { cx: local(view.now), cy: layout.lineY, r: 3.5 }, 'now-dot'));
      const nowLabel = element('div', 'wu-hr-now', PATH_WORDS.now);
      if (path?.now.when) nowLabel.append(element('span', 'wu-hr-time', path.now.when));
      px(nowLabel, local(view.now) - 24, layout.lineY + 30);
      track.append(nowLabel);
    }

    const note = state === 'offline' || (state === 'ready' && momentsFailed)
      ? { words: PATH_WORDS.momentsFailed, refused: true }
      : state === 'ready' && !items.some((item) => item.kind === 'moment' || item.kind === 'change')
        ? { words: PATH_WORDS.nothingYet, refused: false }
        : null;
    if (note) {
      // Centred between the creation card's right edge and Now, 40px under the line (sheet "States").
      const creation = items.find((item) => item.kind === 'creation' && view.drawn.has(item.id));
      const left = creation ? placed.x.get(creation.id)! + layout.card : layout.margin;
      const right = view.now !== null ? local(view.now) : local(width - layout.nowFromRight);
      const said = element('p', 'wu-hr-note', note.words);
      said.dataset.refused = String(note.refused);
      said.setAttribute('role', 'status');
      px(said, Math.round((left + right) / 2), layout.lineY + 40);
      track.append(said);
    }

    const keys = element('div', 'wu-hr-keys');
    const choice = stops().find((one) => one.id === chosen) ?? null;
    const slot = made.content.querySelector('.wu-hr-cardslot') as HTMLElement;
    if (card && card.element.parentElement !== slot) slot.replaceChildren(card.element);
    if (!card) slot.replaceChildren();
    if (card) {
      // While H12's question is open, the row shows its keys alone.
      for (const one of card.keys()) keys.append(keyButton(one.keys, one.word, () => one.press()));
    } else if (opened) {
      const moment = moments().find((one) => one.id === opened!.id);
      const changes = moment ? null : openedChanges();
      if (moment) {
        content.append(openedView(moment, layout));
        if (moment.lines.length > 1) keys.append(keyButton(['↑', '↓'], PATH_WORDS.chooseLine, () => chooseLine(1)));
        if (host.openDecision) keys.append(keyButton(['Enter'], PATH_WORDS.seeDecision, () => seeDecision()));
      } else if (changes) {
        const list = changesView(changes, layout);
        content.append(list.view);
        // Measured where it stands: a list longer than the column moves a row at a time, its foot faded while more
        // lies past it, and [↑] [↓] offered only while there is somewhere to move.
        const rows = [...list.rows.children].map((row) => [(row as HTMLElement).offsetTop, (row as HTMLElement).offsetTop + (row as HTMLElement).offsetHeight]);
        const shown = rowsWindow(rows, list.rows.clientHeight, opened.first);
        opened.first = shown.first;
        if (shown.height !== null) {
          // The list shows whole rows only: its foot is the last whole row's, and the fade lies over that row.
          list.rows.style.flex = '0 0 auto';
          list.rows.style.height = `${shown.height}px`;
        }
        list.rows.scrollTop = shown.scroll;
        list.rows.classList.toggle('more', shown.later);
        if (shown.earlier || shown.later) keys.append(keyButton(['↑', '↓'], PATH_WORDS.earlierLater, () => moveRows(1)));
      }
      keys.append(keyButton(['Esc'], PATH_WORDS.backToStory, () => closeMoment()));
    } else {
      if (stops().length >= 2) keys.append(keyButton(['←', '→'], PATH_WORDS.earlierLater, () => move(1)));
      if (choice) keys.append(keyButton(['Enter'], choice.kind === 'moment' ? PATH_WORDS.openMoment : PATH_WORDS.openChanges, () => openMoment(choice.id)));
      // One GitHub key at most (sheet section 11): open it once it is there, keep it there, or keep it at all.
      const url = githubUrl();
      if (url) keys.append(keyButton(['G'], PATH_WORDS.openOnGitHub, () => host.open(url)));
      else if (offersGitHub()) keys.append(keyButton(['G'], KEEP_WORDS.keepOnGitHub, () => keepOnGitHub()));
      else if (offersKeep()) keys.append(keyButton(['K'], KEEP_WORDS.keepInProject, () => void keepInProject()));
      keys.append(keyButton(['Esc'], PATH_WORDS.back, () => close()));
    }
    content.append(keys);
    if (card && fadeNext) requestAnimationFrame(() => fadeUnderCard(content));
    else if (card) fadeUnderCard(content);
    fadeNext = false;
  }

  /** While H12's card is open, every part of the story under it or within 24px of its edges fades out (H12, 14:07),
   * Now's words included, so nothing peeks past the card. */
  function fadeUnderCard(content: HTMLElement) {
    const box = card?.element.getBoundingClientRect();
    if (!box || box.width === 0) return;
    const near = { left: box.left - 24, right: box.right + 24, top: box.top - 24, bottom: box.bottom + 24 };
    for (const part of content.querySelectorAll<Element>('.wu-hr-track > div, .wu-hr-track > button, .wu-hr-path circle, .wu-hr-path .bracket')) {
      const at = part.getBoundingClientRect();
      const under = at.right > near.left && at.left < near.right && at.bottom > near.top && at.top < near.bottom;
      part.classList.toggle('wu-hr-under', under);
    }
  }

  /** The chosen moment opened over the story (sheet section 12): its picture large, and every line said. */
  function openedView(moment: Json, layout: (typeof LAYOUTS)['wide']): HTMLElement {
    const sizes = layout.opened;
    const view = element('div', 'wu-hr-moment');
    view.setAttribute('role', 'group');
    view.setAttribute('aria-label', moment.words);
    const box = pictureBox(pictureOf(moment), sizes.width, sizes.height);
    box.classList.add('large');
    if (moment.subjects.length) box.append(orbs(moment.subjects, sizes.orb));
    px(box, sizes.left, sizes.top);
    const column = element('div', 'wu-hr-column');
    px(column, sizes.column, sizes.top, sizes.columnRight - sizes.column);
    if (moment.when) column.append(element('div', 'wu-hr-time', moment.when));
    column.append(element('div', 'wu-hr-moment-title', moment.words));
    const lines = element('div', 'wu-hr-lines');
    moment.lines.forEach((one: Json, index: number) => {
      const said = element('div', 'wu-hr-line');
      if (index === opened?.line) said.setAttribute('aria-current', 'true');
      said.append(element('div', 'wu-hr-speaker', (called.speaker ?? called.subject)(one.subject)), element('div', 'wu-hr-line-said', one.quote));
      if (one.by) said.append(sentence('div', 'wu-hr-who', one.by));
      lines.append(said);
    });
    if (!moment.lines.length && moment.by) lines.append(sentence('div', 'wu-hr-who', moment.by));
    column.append(lines);
    if (moment.answers.length) {
      const asked = element('div', 'wu-hr-asked');
      asked.append(element('div', 'wu-hr-asked-head', PATH_WORDS.askedAgain));
      for (const answer of moment.answers) asked.append(sentence('div', 'wu-hr-answer', answer));
      column.append(asked);
    }
    const run = (path?.spans ?? []).find((span: Json) => span.session === moment.session);
    if (run) {
      const small = element('div', 'wu-hr-small', run.small);
      if (run.ended) small.append(element('div', 'wu-hr-ended', run.ended));
      column.append(small);
    }
    view.append(box, column);
    return view;
  }

  /** A grouped changes dot opened over the story (H15, sheet section 7): the time, the title and every change, oldest
   * first, its time over its You sentence. No picture: edits have none, so nothing stands in for one. */
  function changesView(item: Json, layout: (typeof LAYOUTS)['wide']): { readonly view: HTMLElement; readonly rows: HTMLElement } {
    const sizes = layout.changes;
    const view = element('div', 'wu-hr-changes');
    view.setAttribute('role', 'group');
    view.setAttribute('aria-label', item.words);
    const column = element('div', 'wu-hr-column');
    px(column, sizes.left, sizes.top, sizes.width);
    column.style.bottom = `${sizes.foot}px`;
    if (item.when) column.append(element('div', 'wu-hr-time', item.when));
    column.append(element('div', 'wu-hr-moment-title', item.words));
    const rows = element('div', 'wu-hr-rows');
    for (const change of item.changes) {
      const row = element('div', 'wu-hr-row');
      row.append(element('div', 'wu-hr-time', change.when), sentence('div', 'wu-hr-row-words', change.words));
      rows.append(row);
    }
    column.append(rows);
    view.append(column);
    return { view, rows };
  }

  function openedChanges(): Json | null {
    return opened ? stops().find((one) => one.id === opened!.id && one.kind === 'change') ?? null : null;
  }

  /** Opens the chosen moment, or a grouped changes dot's list, on the same page. */
  function openMoment(id: string) {
    chosen = id;
    opened = { id, line: 0, first: 0 };
    draw();
  }

  /** Moves an opened list of changes a row at a time; draw holds it where its last row ends at the foot. */
  function moveRows(by: number) {
    if (!opened || !openedChanges()) return;
    opened.first = Math.max(0, opened.first + by);
    draw();
  }

  function closeMoment() {
    opened = null;
    draw();
  }

  function chooseLine(by: number) {
    const moment = opened ? moments().find((one) => one.id === opened!.id) : null;
    if (!opened || !moment || moment.lines.length < 2) return;
    opened.line = Math.min(moment.lines.length - 1, Math.max(0, opened.line + by));
    draw();
  }

  function seeDecision() {
    const moment = opened ? moments().find((one) => one.id === opened!.id) : null;
    if (!opened || !moment) return;
    const line = moment.lines[opened.line] ?? null;
    host.openDecision?.({
      momentId: moment.moment_id, requestId: line ? line.request : moment.request,
      tick: line?.tick ?? moment.tick, subject: line?.subject ?? moment.subjects[0] ?? null,
    });
  }

  /** Takes the page away; nothing more is made or told once it is gone. */
  function remove() {
    making?.abort();
    making = null;
    // The host takes back the addresses it made for this page as it closes; the next open reads them again.
    pictures.clear();
    portraits.clear();
    card?.close();
    card = null;
    cardSize?.disconnect();
    cardSize = null;
    putting = false;
    if (watching !== null) clearTimeout(watching);
    watching = null;
    made?.close();
    made = null;
    lasting = null;
    opened = null;
    offset = null;
    unlisten?.();
    unlisten = null;
  }

  function close() {
    if (!made) return;
    remove();
    host.closed();
  }

  return {
    get isOpen() {
      return made !== null;
    },
    async open() {
      if (made) return;
      made = page({ form: 'full' });
      made.root.classList.add('wu-record', 'wu-history-r23');
      made.root.setAttribute('aria-label', PATH_WORDS.history);
      // A made creature's label that lands while the page is open re-words the path.
      unlisten = host.kindLabels.listen(() => {
        if (made && state === 'ready' && held) {
          path = held.compose();
          draw();
        }
      });
      made.open(host.root);
      draw();
      made.root.querySelector<HTMLElement>('.wu-hr-title')?.focus({ preventScroll: true });
      await load();
    },
    close,
    dispose: remove,
    key(event) {
      if (!made) return false;
      const command = event.metaKey || event.ctrlKey;
      const target = event.target as Element | null;
      if (event.code === 'Tab' || ((event.code === 'Enter' || event.code === 'Space') && target?.closest?.('.wu-page button:not(.wu-hr-card)'))) return false;
      // The repository name field types for itself; its Enter and Esc are its own.
      if (target?.closest?.('.wu-hr-keepcard input')) return false;
      // A combination the page does not use keeps the browser's own shortcut, as in the world (K8).
      if (command || event.altKey) return false;
      event.preventDefault();
      if (event.repeat && !event.code.startsWith('Arrow')) return true;
      if (card) {
        card.key(event);
        return true;
      }
      if (opened) {
        if (event.code === 'Escape') closeMoment();
        else if (event.code === 'KeyH') close();
        else if (event.code === 'ArrowUp' || event.code === 'ArrowDown') {
          const by = event.code === 'ArrowUp' ? -1 : 1;
          if (openedChanges()) moveRows(by);
          else chooseLine(by);
        }
        else if (event.code === 'Enter') seeDecision();
        return true;
      }
      if (event.code === 'Escape' || event.code === 'KeyH') close();
      else if (event.code === 'ArrowLeft') move(-1);
      else if (event.code === 'ArrowRight') move(1);
      else if (event.code === 'Enter') {
        if (chosen && stops().some((one) => one.id === chosen)) openMoment(chosen);
      } else if (event.code === 'KeyG' && githubUrl()) host.open(githubUrl() as string);
      else if (event.code === 'KeyG' && offersGitHub()) keepOnGitHub();
      else if (event.code === 'KeyK' && offersKeep()) void keepInProject();
      return true;
    },
  };
}
