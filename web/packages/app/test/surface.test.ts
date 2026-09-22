// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { BAND_ORDER } from '@exulanica/companion-runtime';
import type { EntityRecord, GraphSnapshot, OccurrenceRecord } from '@exulanica/graph-client';

import { EvidenceCache } from '../src/evidence.js';
import { buildDetail } from '../src/ui/detail.js';
import { buildWorldIndex } from '../src/ui/world-index.js';
import { MAP_ORIENTATION_CAPTION, buildStatus } from '../src/ui/status.js';

/**
 * The rules a redesign of this surface must not quietly remove.
 *
 * Each one is specified somewhere and each one is the kind of thing that looks like an
 * improvement when you are making a screen calmer: hide the empty bands, drop the permanent
 * caption, warm up the placeholder text. They are asserted here because a review gate is a person
 * remembering, and the next person to work on this surface should find out from a red suite
 * rather than from a reviewer.
 *
 * A DOM environment is used deliberately. Every one of these is a fact about what renders, and
 * checking a view model instead would be checking a proxy for the thing under test. The docblock
 * above scopes happy-dom to this file: atlas-core and companion-runtime compile without lib.dom
 * on purpose, and a workspace-wide DOM would weaken that.
 */

const NO_EVIDENCE = new EvidenceCache({ evidenceBytes: () => Promise.reject(new Error('none')) });
const HANDLERS = {
  onName: () => undefined,
  onEvidenceOpened: () => undefined,
  onLocate: () => undefined,
  onClose: () => undefined,
};

function entity(overrides: Partial<EntityRecord> = {}): EntityRecord {
  return {
    entityId: 'e1',
    kind: 'object',
    displayName: null,
    status: 'inferred_only',
    occurrenceCount: 4,
    islandIds: ['isl'],
    firstSeenMs: null,
    lastSeenMs: null,
    confidence: 'low',
    openQuestionCount: 0,
    citingAnswerCount: 0,
    assertions: [],
    relations: [],
    contradictions: [],
    history: [],
    mergedInto: null,
    ...overrides,
  };
}

function occurrence(id: string, entityId: string | null = null): OccurrenceRecord {
  return {
    occurrenceId: id,
    anchorId: id,
    islandId: 'isl',
    kind: 'object',
    entityId,
    linkState: entityId === null ? 'proposed' : 'confirmed',
    confidence: 'low',
    evidence: [`span-${id}`],
    capturedAtMs: null,
  };
}

function snapshot(entities: readonly EntityRecord[], occurrences: readonly OccurrenceRecord[]): GraphSnapshot {
  return {
    stateVersion: 3,
    entities,
    occurrences,
    islands: [
      {
        islandId: 'isl',
        captureIds: ['c1'],
        firstCapturedAtMs: null,
        lastCapturedAtMs: null,
        positionedCaptureCount: 0,
        spreadMetres: null,
        rung: null,
        rungCaptureCount: 0,
      },
    ],
    matchProposals: [],
    neverSame: [],
    deletedEntityIds: [],
  };
}

// ---------------------------------------------------------------------------------------------
// The four-band panel

describe('the provenance panel', () => {
  function panelOf(record: EntityRecord): HTMLElement {
    const detail = buildDetail(NO_EVIDENCE, HANDLERS);
    detail.showEntity(snapshot([record], [occurrence('o1', record.entityId)]), record);
    return detail.root.querySelector('.band-panel')!;
  }

  it('draws all four bands, in the fixed order, for an entity nobody has said anything about', () => {
    // Band 4 is never omitted, and the other three are not omitted either when they are empty.
    // What the system does not know is information, and a panel that showed only what it knew
    // would be the panel this one exists instead of.
    const bands = [...panelOf(entity()).querySelectorAll('.band')];
    expect(bands).toHaveLength(4);
    expect(bands.map((b) => b.className.match(/band-(\w+)/)?.[1])).toEqual([...BAND_ORDER]);
  });

  it('never leaves a band as a heading with nothing under it', () => {
    // A band draws either its rows or a sentence saying nothing is recorded. A heading with a
    // void beneath it reads as a rendering fault, which is the one reading that would make an
    // empty band say nothing at all rather than saying that nothing is known.
    for (const band of panelOf(entity()).querySelectorAll('.band')) {
      const rows = band.querySelectorAll('.band-row').length;
      const sentence = (band.querySelector('.band-empty')?.textContent ?? '').length;
      expect(rows + sentence, `${band.className} has a heading and nothing else`).toBeGreaterThan(
        0,
      );
    }
  });

  it('writes a sentence in a band that genuinely holds nothing', () => {
    // Band 1 over an entity nobody has spoken about is the case: the panel has to say that you
    // have not said anything, rather than showing a gap where your words would go.
    const told = panelOf(entity()).querySelector('.band-told')!;
    expect(told.querySelectorAll('.band-row')).toHaveLength(0);
    expect((told.querySelector('.band-empty')?.textContent ?? '').length).toBeGreaterThan(0);
  });

  it('never renders a raw message key where a sentence belongs', () => {
    // These packages emit keys and refuse to author prose. If the copy table has no entry, the
    // key renders, which is findable on purpose; it must not be findable in a shipped panel.
    const text = panelOf(entity()).textContent ?? '';
    expect(text).not.toMatch(/\b(row|unknown|method|external)\.[a-zA-Z]/);
  });
});

describe('the desktop viewport boundary', () => {
  it('has an explicit way back to the index', () => {
    let closed = false;
    const detail = buildDetail(NO_EVIDENCE, {
      ...HANDLERS,
      onClose: () => {
        closed = true;
      },
    });
    detail.showOccurrence(occurrence('o1'));
    const back = detail.root.querySelector<HTMLButtonElement>('.detail-close');
    expect(back?.textContent).toContain('Index');
    back?.click();
    expect(closed).toBe(true);
  });

  it('does not silently switch into a mobile Index layout', () => {
    const style = readFileSync('packages/app/src/style.css', 'utf8');
    const start = style.indexOf('@media (max-width: 60rem)');
    const end = style.indexOf('@media (prefers-reduced-motion: reduce)', start);
    const narrowRules = style.slice(start, end);
    expect(start).toBeGreaterThanOrEqual(0);
    expect(narrowRules).not.toContain('grid-template');
    expect(narrowRules).not.toContain('.rail {');
    expect(narrowRules).toContain('.viewport-boundary');
    expect(narrowRules).toContain('visibility: hidden');
  });

  it('uses a directional atmosphere rather than decorative gradient circles', () => {
    const appearance = readFileSync('packages/app/src/appearance.css', 'utf8');
    // This also asserted that appearance.css consumed `var(--field-image)`. Its only consumer
    // there was the atmosphere-picker's swatches, including a `[data-atmosphere='blue-hour']`
    // variant for a treatment atlas-visual-language.md lists among the rejected ones. No `.ts`
    // in the workspace has emitted that markup for some time, so the assertion was guarding dead
    // rules for a dropped feature. The token is still defined once in tokens.css and still used
    // once by the landing page, and both of those are asserted by their own suites
    // (presentation/test/system.test.ts and landing/test/viewport-boundary.test.ts). What is real
    // here is the prohibition, so that is what stays.
    expect(appearance).not.toContain('radial-gradient');
  });
});

describe('the Index evidence workspace', () => {
  it('exposes the existing four facet contracts and emits a typed facet change', () => {
    const onFacets = vi.fn();
    const rail = buildWorldIndex({
      onEntity: () => undefined,
      onOccurrence: () => undefined,
      onSearch: () => undefined,
      onFacets,
    });
    rail.render(snapshot([entity({ kind: 'person' })], [occurrence('o1', 'e1')]), '', null);

    expect([...rail.root.querySelectorAll('fieldset legend')].map((node) => node.textContent)).toEqual([
      'Kind', 'Status', 'Presence', 'Source of knowledge',
    ]);
    const people = rail.root.querySelector<HTMLInputElement>('input[value="person"]')!;
    people.checked = true;
    people.dispatchEvent(new Event('change'));
    expect(onFacets).toHaveBeenCalledWith(expect.objectContaining({ kinds: ['person'] }));
    expect(rail.root.textContent).toContain('Knowledge marks');
  });

  it('preserves keyboard focus while a presence facet rerenders the results', () => {
    const graph = snapshot([entity({ kind: 'person' })], [occurrence('o1', 'e1')]);
    let rail: ReturnType<typeof buildWorldIndex>;
    rail = buildWorldIndex({
      onEntity: () => undefined,
      onOccurrence: () => undefined,
      onSearch: () => undefined,
      onFacets: (facets) => rail.render(graph, facets, null),
    });
    document.body.append(rail.root);
    rail.render(graph, '', null);

    const presence = rail.root.querySelector<HTMLInputElement>('.index-presence-facet input')!;
    presence.focus();
    presence.checked = true;
    presence.dispatchEvent(new Event('change'));
    expect(document.activeElement).toBe(presence);
    rail.root.remove();
  });

  it('identifies keyboard row activation so focus can move into the detail pane', () => {
    const onEntity = vi.fn();
    const rail = buildWorldIndex({
      onEntity,
      onOccurrence: () => undefined,
      onSearch: () => undefined,
    });
    rail.render(snapshot([entity({ displayName: 'Mara' })], [occurrence('o1', 'e1')]), '', null);
    rail.root.querySelector<HTMLButtonElement>('.rail-row')?.dispatchEvent(
      new MouseEvent('click', { bubbles: true, detail: 0 }),
    );
    expect(onEntity).toHaveBeenCalledWith('e1', 'keyboard');
  });
});

describe('citation-to-world navigation', () => {
  it('offers a location action even when synthetic evidence cannot be opened', () => {
    let located: readonly [string | null, string] | null = null;
    const detail = buildDetail(NO_EVIDENCE, {
      ...HANDLERS,
      onLocate: (anchorId, islandId) => {
        located = [anchorId, islandId];
      },
    }, { preview: true });
    detail.showOccurrence(occurrence('o1'));
    const locate = detail.root.querySelector<HTMLButtonElement>('.citation-locate');
    const original = detail.root.querySelector<HTMLButtonElement>('.citation-open');
    expect(locate?.disabled).toBe(false);
    expect(original?.disabled).toBe(true);
    locate?.click();
    expect(located).toEqual(['o1', 'isl']);
  });
});

// ---------------------------------------------------------------------------------------------
// The Map orientation caption

describe('the Map orientation caption', () => {
  const status = () =>
    buildStatus({
      omittedRegionCount: 0,
      undrawable: new Map(),
    });

  it('says exactly what interaction-model.md 6.2 fixes it to say', () => {
    expect(MAP_ORIENTATION_CAPTION).toBe(
      'Positions show how these memories relate, not where they happened.',
    );
  });

  it('does not leave the orientation sentence in the ground-view status area', () => {
    const bar = status();
    expect(bar.querySelectorAll('button, a, input, [role="button"]')).toHaveLength(0);
    expect(bar.textContent).not.toContain(MAP_ORIENTATION_CAPTION);
  });

  it('keeps diagnostics out of the normal world view', () => {
    const text = status().textContent ?? '';
    expect(text).not.toContain('state version');
    expect(text).not.toContain('detections');
    expect(text).not.toContain('reconstruction');
  });

  it('states what was left out instead of showing a smaller world as the whole one', () => {
    const bar = buildStatus({
      omittedRegionCount: 3,
      undrawable: new Map([['voice', 7]]),
    });
    const warnings = [...bar.querySelectorAll('.status-warning')].map((n) => n.textContent ?? '');
    expect(warnings).toEqual(['3 regions and 7 detections not shown in your world.']);
  });

  it('states authenticated source failures without substituting media', () => {
    const bar = buildStatus({
      omittedRegionCount: 0,
      undrawable: new Map(),
      notices: [
        'Missing source evidence: no evidence was recorded',
        'Source not authorized: this session cannot load the source',
      ],
    });
    expect(bar.textContent).toContain('Missing source evidence');
    expect(bar.textContent).toContain('Source not authorized');
    expect(bar.querySelectorAll('img, video, canvas')).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------------------------
// The honest placeholder

describe('a name and a placeholder are not the same kind of thing', () => {
  function railOf(record: EntityRecord): HTMLElement {
    const rail = buildWorldIndex({
      onEntity: () => undefined,
      onOccurrence: () => undefined,
      onSearch: () => undefined,
    });
    rail.render(snapshot([record], [occurrence('o1', record.entityId)]), '', null);
    return rail.root;
  }

  it('marks an unnamed entity’s label as a placeholder', () => {
    // id-1: the occurrence is anonymous and the entity holds the name. id-6: names come solely
    // from the account holder. So a name-shaped string nobody said must be visibly not a name.
    const label = railOf(entity()).querySelector('.rail-name');
    expect(label?.classList.contains('is-placeholder')).toBe(true);
    expect(label?.textContent).toContain('Unnamed');
  });

  it('does not mark a real name as a placeholder', () => {
    const label = railOf(entity({ displayName: 'Julie', status: 'user_asserted' })).querySelector(
      '.rail-name',
    );
    expect(label?.classList.contains('is-placeholder')).toBe(false);
    expect(label?.textContent).toBe('Julie');
  });

  it('says which zero it is when nothing has been identified', () => {
    // "Nothing is identified" and "nothing matched your filter" are different facts, and only one
    // of them means the library is empty.
    const rail = buildWorldIndex({
      onEntity: () => undefined,
      onOccurrence: () => undefined,
      onSearch: () => undefined,
    });
    rail.render(snapshot([], [occurrence('o1')]), '', null);
    expect(rail.root.querySelector('.rail-empty')?.textContent).toContain('has been identified yet');
  });

  it('never renders the open-question count as a fraction or a percentage', () => {
    // 5.5: the counter is allowed to read the same number forever. There is no completion metric
    // anywhere in this product, so there must be nothing here a progress ring could be built from.
    const rail = buildWorldIndex({
      onEntity: () => undefined,
      onOccurrence: () => undefined,
      onSearch: () => undefined,
    });
    rail.render(snapshot([entity({ openQuestionCount: 3 })], []), '', null);
    const counter = rail.root.querySelector('.rail-counter')?.textContent ?? '';
    expect(counter).toBe('3 open questions');
    expect(counter).not.toMatch(/%|\bof\b|\/|\bcomplete\b/);
  });
});
