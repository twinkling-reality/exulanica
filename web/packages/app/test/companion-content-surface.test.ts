// @vitest-environment happy-dom
import { describe, expect, it } from 'vitest';

import {
  contentRowFields,
  parseContentRow,
  parseContentSurface,
  type CompanionContentRow,
} from '../src/companion-content.js';
import type { CompanionAnswer } from '../src/companion-ask-api.js';
import { buildCompanionPanel } from '../src/ui/companion-panel.js';
import { say } from '../src/ui/copy.js';

const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/;

/** The label/value pairs one rendered CONTENT item shows. */
function fieldsOf(item: Element | null | undefined): Record<string, string> {
  const labels = [...(item?.querySelectorAll('dt') ?? [])].map((dt) => dt.textContent ?? '');
  const values = [...(item?.querySelectorAll('dd') ?? [])].map((dd) => dd.textContent ?? '');
  return Object.fromEntries(labels.map((label, index) => [label, values[index] ?? '']));
}

const NOOP = {
  onSelect: () => undefined,
  onSubmit: () => undefined,
  onSay: () => undefined,
  onEvidence: () => undefined,
};

function opened() {
  const panel = buildCompanionPanel(NOOP);
  panel.setState('open');
  return panel;
}

function row(over: Partial<CompanionContentRow> = {}): CompanionContentRow {
  return {
    resultKind: 'memory_capture',
    originKind: 'personal',
    contentKind: 'capture',
    authoredRole: null,
    placeRelationship: 'captured_at',
    matchReason: 'confirmed_memory_place',
    memoryPlaceEntityId: 'bc9a2107-cd67-4fe5-be70-570158cffdfa',
    canonicalPlaceId: 'bc9a2107-cd67-4fe5-be70-570158cffdfa',
    worldId: null,
    versionId: null,
    sourceId: 'source:memory',
    lineageIds: ['lineage:memory'],
    label: 'Harbour photograph',
    availability: 'available',
    personalVisitEvidence: true,
    ...over,
  };
}

function answer(over: Partial<CompanionAnswer> = {}): CompanionAnswer {
  return {
    question: 'What belongs to this place?',
    clauses: [{
      text: 'Authorized content for this confirmed place.',
      type: 'meta',
      citations: [],
    }],
    text: 'Authorized content for this confirmed place.',
    abstained: null,
    deterministic: true,
    repaired: false,
    evidence: [],
    content: {
      placeConfirmed: true,
      totalMatched: 1,
      rows: [row()],
    },
    provenance: {
      composed: 'none',
      servedModel: null,
      plannedBy: null,
      latencyMs: 0,
      usedFallback: false,
    },
    promptVersion: 'content-selection-1',
    calls: [],
    ...over,
  };
}

describe('companion CONTENT surface', () => {
  it('renders origin, place, availability, and permission from existing CONTENT rows', () => {
    const panel = opened();
    panel.showAnswer(answer({
      content: {
        placeConfirmed: true,
        totalMatched: 2,
        rows: [
          row(),
          row({
            resultKind: 'authored_environment_instance',
            originKind: 'authored',
            contentKind: 'environment_instance',
            authoredRole: 'fictional',
            placeRelationship: 'derived_from',
            matchReason: 'authored_from_canonical_place',
            worldId: 'atlas',
            versionId: '1b39b2b3-9534-441d-88e6-0b62623ef22a',
            sourceId: 'source:authored',
            label: 'Illuminated Flatiron',
            availability: 'available',
            personalVisitEvidence: false,
          }),
        ],
      },
    }));

    const items = panel.root.querySelectorAll('.companion-content-item');
    expect(items).toHaveLength(2);
    expect(items[0]?.getAttribute('data-origin')).toBe('personal');
    expect(items[1]?.getAttribute('data-origin')).toBe('authored');
    const text = panel.root.textContent ?? '';
    expect(text).toContain('Harbour photograph');
    expect(text).toContain('Your own photographs');
    expect(text).toContain('Taken at this place');
    expect(text).toContain('Yes, your own photograph from here');
    expect(text).toContain('Illuminated Flatiron');
    expect(text).toContain('Authored addition to a world, invented for this world');
    expect(text).toContain('Made in a world, not observed');
    // Authored rows are never phrased as personal memories or as a visit.
    expect(items[1]?.textContent ?? '').not.toMatch(/your own photograph/i);
    expect(fieldsOf(items[1])['Counts as a visit']).toBe('No');
    // No identifier is printed as a description.
    expect(text).not.toMatch(UUID);
    expect(text).not.toContain('source:authored');
    expect(text).not.toContain('atlas');
  });

  it('shows an explicit empty state for a confirmed place with no CONTENT rows', () => {
    const panel = opened();
    panel.showAnswer(answer({
      clauses: [{
        text: 'No authorized content matches that confirmed place relationship.',
        type: 'meta',
        citations: [],
      }],
      text: 'No authorized content matches that confirmed place relationship.',
      abstained: 'UNANSWERABLE_NOT_CAPTURED',
      content: { placeConfirmed: true, totalMatched: 0, rows: [] },
    }));

    expect(panel.root.querySelector('.companion-content-empty')?.textContent).toBe(
      'Nothing is linked to this place yet.',
    );
    expect(panel.root.querySelectorAll('.companion-content-item')).toHaveLength(0);
    // A place with nothing linked is not a photograph search: the photograph sentence is absent.
    expect(panel.root.textContent).not.toContain(say('abstention.UNANSWERABLE_NOT_CAPTURED'));
    expect(panel.root.querySelector('.companion-abstention')).toBeNull();
  });

  it('keeps the photograph abstention for an ordinary capture answer', () => {
    const panel = opened();
    panel.showAnswer(answer({
      clauses: [],
      text: '',
      abstained: 'UNANSWERABLE_NOT_CAPTURED',
      content: { placeConfirmed: false, totalMatched: 0, rows: [] },
    }));
    expect(panel.root.querySelector('.companion-abstention')?.textContent)
      .toBe(say('abstention.UNANSWERABLE_NOT_CAPTURED'));
  });

  it('shows unavailable availability and withheld personal-visit permission honestly', () => {
    const panel = opened();
    panel.showAnswer(answer({
      content: {
        placeConfirmed: true,
        totalMatched: 1,
        rows: [row({
          availability: 'unavailable_bytes',
          personalVisitEvidence: false,
          originKind: 'imported',
          resultKind: 'admitted_environment_source',
          label: 'NYC Open Data',
        })],
      },
    }));

    const item = panel.root.querySelector('.companion-content-item');
    expect(item?.getAttribute('data-availability')).toBe('unavailable_bytes');
    expect(item?.getAttribute('data-visit-evidence')).toBe('no');
    const fields = fieldsOf(item);
    expect(fields['Available']).toBe('Recorded, but its file is missing');
    expect(fields['Counts as a visit']).toBe('No');
    expect(fields['Where it comes from']).toBe('An admitted outside source');
    expect(fields['What it is']).toBe('Admitted source record');
    expect(panel.root.textContent).not.toContain('unavailable_bytes');
  });

  it('does not invent CONTENT chrome for ordinary capture answers', () => {
    const panel = opened();
    panel.showAnswer(answer({
      content: { placeConfirmed: false, totalMatched: 0, rows: [] },
    }));
    expect(panel.root.querySelector('.companion-content-heading')).toBeNull();
    expect(panel.root.querySelector('.companion-content-empty')).toBeNull();
  });
});

describe('CONTENT row parsing', () => {
  it('keeps missing fields explicit rather than filled in', () => {
    const parsed = parseContentRow({
      result_kind: 'memory_capture',
      origin_kind: 'personal',
      content_kind: 'capture',
      authored_role: null,
      place_relationship: 'captured_at',
      match_reason: 'confirmed_memory_place',
      memory_place_entity_id: 'bc9a2107-cd67-4fe5-be70-570158cffdfa',
      canonical_place_id: null,
      world_id: null,
      version_id: null,
      source_id: 'source:memory',
      lineage_ids: [],
      label: null,
      availability: 'unknown',
      personal_visit_evidence: true,
    });
    expect(parsed).not.toBeNull();
    const fields = contentRowFields(parsed!);
    // A memory capture has no label; it is described, never named by its source id.
    expect(fields.find((field) => field.label === 'Record')?.value).toBe('A photograph in your library');
    expect(fields.find((field) => field.label === 'Available')?.value).toBe('Not checked');
    expect(fields.some((field) => field.value.includes('source:memory'))).toBe(false);
    expect(parsed!.sourceId).toBe('source:memory');
    expect(parseContentSurface({ content: [], total_matched: 0 }, { placeConfirmed: true })).toEqual({
      rows: [],
      placeConfirmed: true,
      totalMatched: 0,
    });
  });
});
