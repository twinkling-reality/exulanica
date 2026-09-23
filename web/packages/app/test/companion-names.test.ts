// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import type { GraphSnapshot } from '@exulanica/graph-client';

import { CompanionAskClient, type CompanionAnswer } from '../src/companion-ask-api.js';
import {
  NAME_PREDICATE,
  PLACEHOLDER_SOURCE,
  companionNames,
  spokenText,
  type CompanionNames,
} from '../src/companion-names.js';
import { buildCompanionEncounter } from '../src/ui/companion-encounter.js';
import { say } from '../src/ui/copy.js';

/**
 * The account holder's own names, put back where the server sent a placeholder.
 *
 * The server replaces every saved name before a hosted model sees a request, so a composed answer
 * names a person or a place only as `[person A]` or `[place A]`, and its `names` says which entity
 * each one is. What a person reads is the name they gave that entity, from the library this page
 * holds, and never brackets.
 */

const PERSON = '0190a000-0000-7000-8000-00000000000a';
const PLACE = '0190a000-0000-7000-8000-00000000000b';

interface Named {
  readonly entityId: string;
  readonly displayName: string | null;
  readonly mergedInto?: string | null;
  readonly assertions?: readonly unknown[];
}

/** A library with only what the resolver reads: each entity's id, name, merges and claims. */
function library(entities: readonly Named[], deleted: readonly string[] = []): GraphSnapshot {
  return {
    entities: entities.map((entity) => ({ mergedInto: null, assertions: [], ...entity })),
    deletedEntityIds: deleted,
  } as unknown as GraphSnapshot;
}

/** A naming claim as the graph sends one: its value blanked once consent is withdrawn. */
const naming = (objectValue: string | null, status = 'active') => ({
  predicateKey: NAME_PREDICATE,
  status,
  objectValue,
});

const NAMED = library([
  { entityId: PERSON, displayName: 'Maria Estrada' },
  { entityId: PLACE, displayName: 'Mireland Hall' },
]);

const NAMES = { '[person A]': PERSON, '[place A]': PLACE };

function answer(text: string, names?: Readonly<Record<string, string>>): CompanionAnswer {
  return {
    question: 'who was at the hall?',
    clauses: [{ text, type: 'historical', citations: ['TOKEN00001'] }],
    text,
    abstained: null,
    deterministic: false,
    repaired: false,
    evidence: [],
    ...(names === undefined ? {} : { names }),
    provenance: {
      composed: 'model',
      servedModel: 'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B',
      plannedBy: 'Qwen/Qwen3-235B-A22B-Instruct-2507',
      latencyMs: 4100,
      usedFallback: false,
    },
    promptVersion: 'selection-6',
    calls: [],
  };
}

const HANDLERS = {
  onSelect: () => undefined,
  onSubmit: () => undefined,
  onSay: () => undefined,
  onEvidence: () => undefined,
};

/** The answer as the encounter draws it, through the resolver it was given. */
function drawn(shown: CompanionAnswer, names: CompanionNames): HTMLElement {
  const panel = buildCompanionEncounter(HANDLERS, { names });
  panel.setState('open');
  panel.showAnswer(shown);
  const utterance = panel.root.querySelector<HTMLElement>('.companion-utterance');
  if (utterance === null) throw new Error('the answer drew no utterance');
  return utterance;
}

describe('a placeholder in an answer', () => {
  it('is drawn as the name the account holder gave that entity, person and place alike', () => {
    const utterance = drawn(
      answer('[person A] was photographed at [place A].', NAMES),
      companionNames(() => NAMED),
    );

    expect(utterance.textContent).toBe('Maria Estrada was photographed at Mireland Hall.');
    const names = [...utterance.querySelectorAll<HTMLElement>('.companion-name')];
    expect(names.map((name) => [name.dataset['entityId'], name.dataset['placeholder']])).toEqual([
      [PERSON, '[person A]'],
      [PLACE, '[place A]'],
    ]);
    expect(names.some((name) => name.hasAttribute('data-unresolved'))).toBe(false);
  });

  it('takes the name from the library, never from the words of the answer', () => {
    // The sentence around the placeholder says something else entirely; the library decides.
    const pieces = companionNames(() => library([
      { entityId: PLACE, displayName: 'Grandmother’s house' },
    ])).restore('The sign reads [place A], not Mireland Hall.', { '[place A]': PLACE });

    expect(spokenText(pieces)).toBe('The sign reads Grandmother’s house, not Mireland Hall.');
  });

  it('reads the library when it draws, so a name confirmed after mounting is shown', () => {
    let held: GraphSnapshot = library([]);
    const names = companionNames(() => held);
    expect(spokenText(names.restore('At [place A].', { '[place A]': PLACE }))).toBe(
      `At ${say('name.class.place')} whose name this page has not loaded.`,
    );

    held = NAMED;
    expect(spokenText(names.restore('At [place A].', { '[place A]': PLACE }))).toBe(
      'At Mireland Hall.',
    );
  });

  it('is recognised however the model cased the class word', () => {
    const pieces = companionNames(() => NAMED).restore('[Place A] is on the sign.', NAMES);
    expect(spokenText(pieces)).toBe('Mireland Hall is on the sign.');
  });

  it('is recognised without its brackets when it is one of the answer\'s own labels', () => {
    // Measured on the live composer: "These photographs were taken at place A."
    const names = companionNames(() => NAMED);
    expect(spokenText(names.restore('These photographs were taken at place A.', NAMES))).toBe(
      'These photographs were taken at Mireland Hall.',
    );
    expect(spokenText(names.restore('Place A is on the sign, and so is [place A].', NAMES))).toBe(
      'Mireland Hall is on the sign, and so is Mireland Hall.',
    );
    // Measured too, on a sign painted in capitals: "The sign reads PLACE A."
    expect(spokenText(names.restore('The sign reads PLACE A.', NAMES))).toBe(
      'The sign reads Mireland Hall.',
    );
  });

  it('leaves ordinary words alone that only look like a bare label', () => {
    const names = companionNames(() => NAMED);
    for (const text of [
      'It is a place a friend chose.',
      'The workplace A team met there.',
      'At place AB, not place A1.',
    ]) {
      expect(spokenText(names.restore(text, NAMES)), text).toBe(text);
    }
    // A remembered answer keeps no names, so only the bracketed form is read as a placeholder.
    expect(spokenText(names.restore('Taken at place A.', undefined))).toBe('Taken at place A.');
  });

  it('restores a bare label that could be a word only where no word follows it', () => {
    const names = companionNames(() => NAMED);
    const letterI = { '[place I]': PLACE };
    // The pronoun, the article in capitals and a two-letter label with a word after it stay words.
    for (const [text, labels] of [
      ['It is the place I visited.', letterI],
      ['THE PLACE A FRIEND CHOSE', NAMES],
      ['The place AB was there.', { '[place AB]': PLACE }],
    ] as const) {
      expect(spokenText(names.restore(text, labels)), text).toBe(text);
    }
    // Where punctuation or the end follows, it can only be the label.
    expect(spokenText(names.restore('Taken at place I.', letterI))).toBe('Taken at Mireland Hall.');
    expect(spokenText(names.restore('Taken at place AB', { '[place AB]': PLACE }))).toBe(
      'Taken at Mireland Hall',
    );
    // A letter that is no word is the label anywhere, in running text or in capitals.
    expect(spokenText(names.restore('THE SIGN READS PLACE B NOW', { '[place B]': PLACE }))).toBe(
      'THE SIGN READS Mireland Hall NOW',
    );
  });
});

describe('a placeholder the page cannot resolve', () => {
  const cases: readonly [string, GraphSnapshot | null, Readonly<Record<string, string>> | undefined, string][] = [
    ['deleted', library([{ entityId: PLACE, displayName: 'Mireland Hall' }], [PLACE]), NAMES, 'no longer in your library'],
    [
      'unnamed after its name was taken back',
      library([{ entityId: PLACE, displayName: null, assertions: [naming('Mireland Hall', 'retracted')] }]),
      NAMES,
      'you have not named',
    ],
    ['merged', library([{ entityId: PLACE, displayName: 'Mireland Hall', mergedInto: PERSON }]), NAMES, 'you merged into another'],
    ['unnamed', library([{ entityId: PLACE, displayName: null }]), NAMES, 'you have not named'],
    ['not in this library', library([]), NAMES, 'whose name this page has not loaded'],
    ['no library at all', null, NAMES, 'whose name this page has not loaded'],
    ['not in the answer\'s names', NAMED, {}, 'this answer does not name'],
    ['from an answer with no names', NAMED, undefined, 'this answer does not name'],
  ];

  for (const [why, held, names, words] of cases) {
    it(`says so in words when the place is ${why}, and shows no brackets`, () => {
      const utterance = drawn(
        answer('The sign reads [place A].', names),
        companionNames(() => held),
      );

      expect(utterance.textContent).toBe(`The sign reads ${say('name.class.place')} ${words}.`);
      expect(utterance.textContent).not.toContain('[');
      expect(utterance.querySelector('.companion-name')?.hasAttribute('data-unresolved')).toBe(true);
    });
  }

  it('says a person\'s consent was withdrawn, never that they were not named', () => {
    // The graph keeps a withdrawn person's naming claim, active, with its value blanked.
    const withdrawn = library([
      { entityId: PERSON, displayName: null, assertions: [naming(null)] },
      { entityId: PLACE, displayName: 'Mireland Hall' },
    ]);
    const utterance = drawn(
      answer('[person A] was photographed at [place A].', NAMES),
      companionNames(() => withdrawn),
    );

    const person = say('name.class.person').replace(/^a/, 'A');
    expect(utterance.textContent).toBe(
      `${person} whose consent was withdrawn was photographed at Mireland Hall.`,
    );
    expect(utterance.textContent).not.toContain('you have not named');
    expect(utterance.querySelector('[data-unresolved]')?.getAttribute('data-unresolved')).toBe(
      'withdrawn',
    );
  });

  it('begins a sentence with a capital where the placeholder began one', () => {
    const pieces = companionNames(() => library([])).restore(
      'You were there. [person A] took it.',
      NAMES,
    );
    expect(spokenText(pieces)).toBe(
      'You were there. A person whose name this page has not loaded took it.',
    );
  });

  it('has words for every class of placeholder the server writes', () => {
    // The classes are read out of the pattern the server's own is held to, so a class the
    // server learns fails here until somebody writes what it is called.
    const classes = /\(\?:([^)]+)\)/.exec(PLACEHOLDER_SOURCE)?.[1]?.split('|') ?? [];
    expect(classes.length).toBeGreaterThan(0);
    for (const entityClass of classes) {
      expect(say(`name.class.${entityClass}`), entityClass).not.toBe(`name.class.${entityClass}`);
    }
  });
});

describe('the wire', () => {
  it('carries the answer\'s own placeholder map through to the answer', async () => {
    const fetch = vi.fn(async () => new Response(JSON.stringify({
      answer: { clauses: [{ text: 'At [place A].', type: 'meta', citations: [], value_refs: [] }] },
      plan: null,
      citations: {},
      abstained: null,
      deterministic: false,
      repaired: false,
      execution: { prompt_version: 'selection-6', calls: [] },
      names: { '[place A]': PLACE, '[person B]': 42 },
    }), { status: 200, headers: { 'content-type': 'application/json' } }));
    const received = await new CompanionAskClient({
      baseUrl: 'https://exulanica.test/api',
      token: 'not-a-real-token',
      fetch: fetch as unknown as typeof globalThis.fetch,
    }).ask('what is it called?');

    // An entry that names no id is not a name the page could restore, so it is not carried.
    expect(received.names).toEqual({ '[place A]': PLACE });
  });
});
