// History (DESIGN's frame 23, specification 8.19): everything that changed in this world version,
// newest first, on a full page over the dimmed world: the timeline, the list by day, the chosen
// change with its facts, what happened and what GitHub holds of it. It reads the server alone (GET
// through the workspace's reader); its rows come from history-rows.mjs and its words from
// history-words.mjs. Undo and redo are build mode's own (build.undo(), build.redo()).
import { changeWords, thingName } from './build-words.mjs';
import { byDay, historyRows, timelineMarks } from './history-rows.mjs';
import { HISTORY_WORDS, chosenLabel, clockAt, dayHeading, onGitHub, subLine } from './history-words.mjs';
import { chip, keyRow, keyWord, label, page } from './world-ui.ts';
import { historyRow, timeline } from './world-ui-history.ts';

/** The marks the timeline draws around the chosen change, "Now" after them. */
const MARKS = 7;
/** The newest runs whose own read is fetched for their spend and decisions. */
const RUNS_READ = 20;
/** A world made from words: its draft is read for how it began. */
const GENERATED = 'world:generated:';

type Json = Record<string, any>;

export interface HistoryHost {
  /** Where the page is appended: the world's root, whose corners hide while a page is open. */
  readonly root: HTMLElement;
  readonly worldId: string;
  readonly versionId: string;
  /** The world's title as written, for the sub-line. */
  readonly title: string;
  /** GET through the workspace's reader; throws where the server does not answer 200. */
  read(path: string): Promise<any>;
  /** What a society subject and a placed thing are called (a name, else its kind). */
  names(): Promise<{ subject(id: string): string; placed(id: string): string }>;
  /** Build mode's undo and redo, each resolving after the version is read again; null where this page may not change the world. */
  readonly build: { undo(): Promise<string | null>; redo(): Promise<string | null> } | null;
  /** The world's clock for a society minute ("06:14"), where the clock is read. */
  worldTime?(tick: number): string | null;
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

function element<K extends keyof HTMLElementTagNameMap>(tag: K, className = '', words = ''): HTMLElementTagNameMap[K] {
  const made = document.createElement(tag);
  if (className) made.className = className;
  if (words) made.textContent = words;
  return made;
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
  let shown: ReturnType<typeof page> | null = null;
  let rows: any[] = [];
  /** The GitHub project following this version; null where none does, undefined where unread. */
  let project: Json | null | undefined;
  let chosen: string | null = null;
  let state: 'loading' | 'ready' | 'offline' = 'loading';

  async function reads() {
    const [named, view, parts, listed, models, characters, comparisons, projects, draft] = await Promise.all([
      host.names(),
      host.read(`${version}${scope}`),
      optional(`${version}/parts${scope}`),
      optional(`${version}/society/control/sessions${scope}`),
      optional(`${version}/society/models/history${scope}`),
      optional(`${version}/things/characters/history${scope}`),
      optional(`${version}/society/comparisons${scope}`),
      optional(`/world/github-projects${scope}`),
      host.worldId.startsWith(GENERATED) ? optional(`/worlds/drafts/${encodeURIComponent(host.worldId.slice(GENERATED.length))}`) : null,
    ]);
    // Placed things and made parts named as build mode names them: by kind, by the parts read's label.
    const things = new Map<string, Json>((view.things ?? []).map((thing: Json) => [thing.thing_id, thing]));
    const partLabels = new Map<string, string>((parts?.parts ?? []).map((part: Json) => [part.part_id, part.label]));
    const nameOf = (id: string) => (things.has(id) ? thingName(things.get(id)) : null);
    const partNameOf = (id: string) => partLabels.get(id) ?? null;
    // A model by Manifest.model_name, as the model history serves it; a run reads models by id alone.
    const choices: Json[] = models?.choices ?? [];
    const modelNames = new Map<string, string>(choices.filter((one) => one.model).map((one) => [`${one.model.provider}/${one.model.model_id}`, one.model.name]));
    const sessions: Json[] = (listed?.sessions ?? []).slice(0, RUNS_READ);
    const runs = (await Promise.all(sessions.map((one) => optional(`${version}/society/control/sessions/${encodeURIComponent(one.session_id)}${scope}`))))
      .filter(Boolean)
      .map((run: Json) => ({
        session_id: run.session_id,
        opened_at: run.opened.opened_at,
        minutes: run.used?.minutes ?? 0,
        decisions: run.used?.decisions ?? 0,
        done: run.measures?.counts?.applied ?? 0,
        spent: run.used?.usd ?? '0',
        limit: run.opened.limits?.usd ?? null,
        subjects: [...new Set<string>((run.decisions ?? []).filter((one: Json) => one.decider === 'model').map((one: Json) => one.subject_id))],
        models: (run.by_model ?? []).map((one: Json) => modelNames.get(`${one.provider}/${one.model_id}`)).filter(Boolean),
        ended: run.closed?.words ?? null,
        from: host.worldTime?.(run.opened.start_tick) ?? null,
        to: run.closed ? host.worldTime?.(run.closed.end_tick) ?? null : null,
      }));
    project = projects ? (projects.projects ?? []).find((one: Json) => one.version_id === host.versionId) ?? null : undefined;
    rows = historyRows({
      edits: view.edits ?? [],
      runs,
      models: choices,
      characters: characters?.records ?? [],
      comparisons: (comparisons?.comparisons ?? []).map((one: Json) => ({
        comparison_id: one.comparison_id,
        created_at: one.created_at,
        subject: null,
        models: (one.arms ?? []).map((arm: Json) => arm.decider?.name).filter(Boolean),
        spent: one.start?.spent_usd ?? null,
      })),
      creation: draft ? { at: draft.started_at, readyWorld: null, spent: draft.accounting?.reported_usd ?? null } : null,
    }, named, (edit: Json, edits: Json[]) => changeWords(edit, edits, nameOf, partNameOf));
    if (!chosen || !rows.some((row) => row.id === chosen)) chosen = rows[0]?.id ?? null;
  }

  async function load() {
    // The first read says it is reading; a read again after an undo keeps the rows until it answers.
    if (state !== 'ready') {
      state = 'loading';
      draw();
    }
    try {
      await reads();
      state = 'ready';
    } catch {
      state = 'offline';
    }
    draw();
  }

  function choose(id: string) {
    chosen = id;
    draw();
  }

  function move(by: number) {
    const index = rows.findIndex((row) => row.id === chosen);
    const next = rows[Math.min(rows.length - 1, Math.max(0, index + by))];
    if (next) choose(next.id);
  }

  async function undoing(redo: boolean) {
    if (!host.build) return;
    const said = redo ? await host.build.redo() : await host.build.undo();
    if (said !== null) await load();
  }

  function githubUrl(): string | null {
    if (!project?.link) return null;
    const pull = project.github?.pull_request;
    return pull ? `https://github.com/${project.link.repository}/pull/${pull.number}` : `https://github.com/${project.link.repository}`;
  }

  function draw() {
    if (!shown) return;
    const now = Date.now();
    const { content, keys } = shown;
    content.replaceChildren(keys);
    const head = element('div', 'wu-history-head');
    head.append(element('h1', 'wu-page-title', HISTORY_WORDS.title), element('p', 'wu-page-sub', subLine(host.title, project)));
    content.prepend(head);
    const list = element('div', 'wu-history-list');
    content.append(list);
    if (state === 'loading') {
      list.append(label(HISTORY_WORDS.today), element('p', 'wu-body wu-faint', HISTORY_WORDS.loading));
    } else if (state === 'offline') {
      list.append(element('p', 'wu-body', HISTORY_WORDS.worldOffline));
    } else if (rows.length === 0) {
      list.append(label(HISTORY_WORDS.today), element('p', 'wu-body', HISTORY_WORDS.empty));
    } else {
      const marks = timelineMarks(rows, chosen, MARKS).map((mark: any) => ({ ...mark, time: clockAt(mark.at) }));
      content.append(timeline(marks, { words: HISTORY_WORDS.now, time: clockAt(now) }, choose));
      for (const day of byDay(rows, (at: number) => dayHeading(at, now))) {
        const block = element('div', 'wu-history-day');
        block.append(label(day.heading));
        for (const row of day.rows) {
          block.append(historyRow({ time: clockAt(row.at), words: row.words, cost: row.cost, chosen: row.id === chosen, onPress: () => choose(row.id) }));
        }
        list.append(block);
      }
      const row = rows.find((one) => one.id === chosen);
      if (row) content.append(chosenView(row, now));
    }
    const prompts = [keyWord({ keys: ['←', '→'], word: HISTORY_WORDS.earlierLater })];
    if (host.build) prompts.push(keyWord({ keys: ['⌘Z'], word: HISTORY_WORDS.undo, shortcut: 'Meta+Z', onPress: () => void undoing(false) }));
    const url = githubUrl();
    if (url) prompts.push(keyWord({ keys: ['G'], word: HISTORY_WORDS.openOnGitHub, shortcut: 'G', onPress: () => host.open(url) }));
    if (state === 'offline') prompts.push(keyWord({ keys: ['Enter'], word: HISTORY_WORDS.tryAgain, shortcut: 'Enter', onPress: () => void load() }));
    prompts.push(keyWord({ keys: ['Esc'], word: HISTORY_WORDS.back, shortcut: 'Escape', onPress: () => close() }));
    keys.replaceChildren(keyRow(prompts));
  }

  function chosenView(row: any, now: number): HTMLElement {
    const view = element('div', 'wu-history-chosen');
    view.append(label(chosenLabel(row.at, now)), element('h2', 'wu-quote-title', row.words));
    if (row.kind === 'run' || row.models?.length) {
      const facts = element('div', 'wu-facts');
      for (const name of row.models ?? []) facts.append(chip(name, { page: true }));
      if (row.facts) facts.append(element('span', 'wu-small-text', row.facts));
      view.append(facts);
      if (row.ended) view.append(element('p', 'wu-small-text', row.ended));
    }
    if (row.happened) {
      view.append(element('div', 'wu-hairline'), label(HISTORY_WORDS.whatHappened), element('p', 'wu-body', row.happened));
    }
    const github = onGitHub(project, row.at);
    if (github) view.append(element('div', 'wu-hairline'), label(HISTORY_WORDS.onGitHub), element('p', 'wu-body', github));
    return view;
  }

  function close() {
    if (!shown) return;
    shown.close();
    shown = null;
    host.closed();
  }

  return {
    get isOpen() {
      return shown !== null;
    },
    async open() {
      if (shown) return;
      shown = page({ form: 'full' });
      shown.root.setAttribute('aria-label', HISTORY_WORDS.title);
      shown.open(host.root);
      await load();
    },
    close,
    dispose() {
      shown?.close();
      shown = null;
    },
    key(event) {
      if (!shown) return false;
      const command = event.metaKey || event.ctrlKey;
      // Tab moves the focus among the page's rows and prompts; Enter presses the one focused.
      if (event.code === 'Tab' || (event.code === 'Enter' && (event.target as Element | null)?.closest?.('.wu-page button'))) return false;
      // A combination the page does not use keeps the browser's own shortcut, as in the world (K8).
      if ((command || event.altKey) && !(command && event.code === 'KeyZ' && !event.altKey)) return false;
      event.preventDefault();
      if (event.repeat && !event.code.startsWith('Arrow')) return true;
      if (event.code === 'Escape' || (event.code === 'KeyH' && !command)) close();
      else if (event.code === 'ArrowLeft' || event.code === 'ArrowDown') move(1);
      else if (event.code === 'ArrowRight' || event.code === 'ArrowUp') move(-1);
      else if (command && event.code === 'KeyZ') void undoing(event.shiftKey);
      else if (event.code === 'KeyG' && !command && githubUrl()) host.open(githubUrl() as string);
      else if (event.code === 'Enter' && state === 'offline') void load();
      return true;
    },
  };
}
