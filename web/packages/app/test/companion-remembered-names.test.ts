// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import type { GraphSnapshot } from '@exulanica/graph-client';

import type { CompanionAnswer } from '../src/companion-ask-api.js';
import {
  CompanionMemoryClient,
  answerToRemember,
  rememberedAsAnswer,
} from '../src/companion-memory-api.js';
import { NAME_PREDICATE, companionNames } from '../src/companion-names.js';
import { buildCompanionEncounter } from '../src/ui/companion-encounter.js';
import { fill, say } from '../src/ui/copy.js';

/**
 * A remembered answer is drawn with its names, read from the library when it is drawn.
 *
 * The answer route says which entity each placeholder stands for, and the memory keeps that map as
 * ids (`companion_answer_name`). After a reload, the remembered answer goes through the same
 * resolver as a fresh one, so a rename shows the new name and a deletion, a withdrawn consent and
 * a library the page has not loaded are each said in their own words.
 */

const PERSON = '0190a000-0000-7000-8000-00000000000a';
const PLACE = '0190a000-0000-7000-8000-00000000000b';
const WHERE = { baseUrl: 'https://exulanica.test/api', token: 'not-a-real-token' };

interface Named {
  readonly entityId: string;
  readonly displayName: string | null;
  readonly mergedInto?: string | null;
  readonly assertions?: readonly unknown[];
}

function library(entities: readonly Named[], deleted: readonly string[] = []): GraphSnapshot {
  return {
    entities: entities.map((entity) => ({ mergedInto: null, assertions: [], ...entity })),
    deletedEntityIds: deleted,
  } as unknown as GraphSnapshot;
}

const NAMED = library([
  { entityId: PERSON, displayName: 'Maria Estrada' },
  { entityId: PLACE, displayName: 'Mireland Hall' },
]);

const TEXT = '[person A] was photographed at [place A].';
const NAMES = { '[person A]': PERSON, '[place A]': PLACE };

/** A fresh answer as the answer route's client builds one. */
function fresh(): CompanionAnswer {
  return {
    question: 'who was at the hall?',
    clauses: [{ text: TEXT, type: 'historical', citations: [] }],
    text: TEXT,
    abstained: null,
    deterministic: false,
    repaired: false,
    evidence: [],
    names: NAMES,
    provenance: {
      composed: 'model',
      servedModel: 'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B',
      plannedBy: 'Qwen/Qwen3-235B-A22B-Instruct-2507',
      latencyMs: 4100,
      usedFallback: false,
    },
    promptVersion: 'selection-7',
    calls: [],
  };
}

/** The row the memory route serves for it, as `GET /companion/memory/recent` writes it. */
function wireRow(names: Record<string, string> | null = NAMES): Record<string, unknown> {
  return {
    answer_id: 'answer-1',
    asked_at: '2026-09-24T08:00:00Z',
    question: 'who was at the hall?',
    answer_text: TEXT,
    abstained: null,
    deterministic: false,
    repaired: false,
    served_model: 'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B',
    planned_by: 'Qwen/Qwen3-235B-A22B-Instruct-2507',
    prompt_version: 'selection-7',
    latency_ms: 4100,
    origin: 'asked',
    supersedes: null,
    correction_note: null,
    citations: [],
    ...(names === null ? {} : { names }),
  };
}

function server(row: Record<string, unknown>) {
  const posted: unknown[] = [];
  const fetch = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    if (init?.method === 'POST') {
      posted.push(JSON.parse(String(init.body)));
      return new Response(JSON.stringify(row), {
        status: 201,
        headers: { 'content-type': 'application/json' },
      });
    }
    expect(String(url)).toContain('/companion/memory/recent');
    return new Response(JSON.stringify({ answers: [row], escapes: [] }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  });
  return {
    client: new CompanionMemoryClient({ ...WHERE, fetch: fetch as unknown as typeof globalThis.fetch }),
    posted,
  };
}

const HANDLERS = {
  onSelect: () => undefined,
  onSubmit: () => undefined,
  onSay: () => undefined,
  onEvidence: () => undefined,
};

/** A remembered answer as the encounter puts it back after a reload. */
function restored(answer: CompanionAnswer, snapshot: () => GraphSnapshot | null): string {
  const panel = buildCompanionEncounter(HANDLERS, { names: companionNames(snapshot) });
  panel.setState('open');
  panel.restoreAnswer(answer);
  expect(panel.root.getAttribute('data-remembered')).toBe('true');
  const utterance = panel.root.querySelector<HTMLElement>('.companion-utterance');
  if (utterance === null) throw new Error('the remembered answer drew no utterance');
  return utterance.textContent ?? '';
}

const unresolved = (reason: string, thing: string, capital = false): string => {
  const phrase = fill(`name.unresolved.${reason}`, { thing: say(`name.class.${thing}`) });
  return capital ? phrase.charAt(0).toUpperCase() + phrase.slice(1) : phrase;
};

describe('keeping an answer keeps which entity each placeholder stood for', () => {
  it('posts the answer route’s names with the answer, and no name', async () => {
    const { client, posted } = server(wireRow());
    await client.rememberAnswer(answerToRemember(fresh()));
    expect(posted).toHaveLength(1);
    expect((posted[0] as { names: unknown }).names).toEqual(NAMES);
    expect(JSON.stringify(posted[0])).not.toContain('Maria');
    expect(JSON.stringify(posted[0])).not.toContain('Mireland');
  });

  it('posts an empty map for an answer that names nothing', async () => {
    const { client, posted } = server(wireRow({}));
    const { names: _dropped, ...unnamed } = fresh();
    await client.rememberAnswer(answerToRemember(unnamed));
    expect((posted[0] as { names: unknown }).names).toEqual({});
  });
});

describe('a remembered answer, read back after a reload', () => {
  it('is drawn with the names the fresh answer was drawn with', async () => {
    const { client } = server(wireRow());
    const [row] = (await client.recent()).answers;
    if (row === undefined) throw new Error('the memory served no answer');
    expect(row.names).toEqual(NAMES);
    expect(restored(rememberedAsAnswer(row), () => NAMED)).toBe(
      'Maria Estrada was photographed at Mireland Hall.',
    );
  });

  it('shows a rename, because the name is read from the library when it is drawn', async () => {
    const { client } = server(wireRow());
    const [row] = (await client.recent()).answers;
    if (row === undefined) throw new Error('the memory served no answer');
    const renamed = library([
      { entityId: PERSON, displayName: 'Maria Estrada-Lind' },
      { entityId: PLACE, displayName: 'Mireland Hall' },
    ]);
    expect(restored(rememberedAsAnswer(row), () => renamed)).toBe(
      'Maria Estrada-Lind was photographed at Mireland Hall.',
    );
  });

  it('says a deleted person, a withdrawn consent and an unloaded library in words', async () => {
    const { client } = server(wireRow());
    const [row] = (await client.recent()).answers;
    if (row === undefined) throw new Error('the memory served no answer');
    const answer = rememberedAsAnswer(row);

    const deleted = library([{ entityId: PLACE, displayName: 'Mireland Hall' }], [PERSON]);
    expect(restored(answer, () => deleted)).toBe(
      `${unresolved('removed', 'person', true)} was photographed at Mireland Hall.`,
    );

    const withdrawn = library([
      {
        entityId: PERSON,
        displayName: null,
        assertions: [{ predicateKey: NAME_PREDICATE, status: 'active', objectValue: null }],
      },
      { entityId: PLACE, displayName: 'Mireland Hall' },
    ]);
    expect(restored(answer, () => withdrawn)).toBe(
      `${unresolved('withdrawn', 'person', true)} was photographed at Mireland Hall.`,
    );

    const merged = library([
      { entityId: PERSON, displayName: 'Maria Estrada', mergedInto: PLACE },
      { entityId: PLACE, displayName: 'Mireland Hall' },
    ]);
    expect(restored(answer, () => merged)).toBe(
      `${unresolved('merged', 'person', true)} was photographed at Mireland Hall.`,
    );

    expect(restored(answer, () => null)).toBe(
      `${unresolved('not_loaded', 'person', true)} was photographed at ` +
        `${unresolved('not_loaded', 'place')}.`,
    );
  });

  it('reads a row with no map, as an older server wrote one, as naming nobody', async () => {
    const { client } = server(wireRow(null));
    const [row] = (await client.recent()).answers;
    if (row === undefined) throw new Error('the memory served no answer');
    expect(row.names).toEqual({});
    expect(restored(rememberedAsAnswer(row), () => NAMED)).toBe(
      `${unresolved('not_identified', 'person', true)} was photographed at ` +
        `${unresolved('not_identified', 'place')}.`,
    );
  });
});
