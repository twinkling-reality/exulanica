// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import type { BandRow, ConfirmationSummary } from '@exulanica/companion-runtime';

import { buildConfirm } from '../src/ui/confirm.js';

function pendingRow(labelKey: string, value: unknown): BandRow {
  return {
    rowKey: 'pending-1',
    verbatim: null,
    labelKey,
    value,
    evidence: [],
    methodKey: null,
    confidence: null,
    editable: true,
    removable: true,
    rejectable: false,
    pending: true,
  };
}

function summary(row: BandRow): ConfirmationSummary {
  return {
    draftId: 'draft-1',
    tier: 2,
    policy: {},
    bands: [
      { band: 'told', toneKey: 'warm', rows: [row], omitted: false },
      { band: 'captures', toneKey: 'neutral', rows: [], omitted: false },
      { band: 'inferred', toneKey: 'cool', rows: [], omitted: false },
      { band: 'unknown', toneKey: 'plain', rows: [], omitted: false },
    ],
    external: null,
    blastRadius: {
      anchorCount: 2,
      islandCount: 2,
      anchorIds: [],
      islandIds: [],
    },
    reversible: true,
    permittedHere: true,
  } as unknown as ConfirmationSummary;
}

describe('proposal confirmation copy', () => {
  it('describes a structured same-person proposal without stringifying its payload', () => {
    const onConfirm = vi.fn();
    const onVisibilityChange = vi.fn();
    const panel = buildConfirm({ onConfirm, onCancel: vi.fn(), onVisibilityChange });
    document.body.append(panel.root);
    panel.show(
      'proposal-1',
      summary(pendingRow('row.sameEntityAs', {
        predicateKey: 'same_entity_as',
        matchId: 'match-1',
        candidateEntityId: 'entity-2',
      })),
      'Yes, the same person',
    );

    expect(panel.root.querySelector('blockquote')?.textContent).toBe('Yes, the same person');
    expect(panel.root.textContent).toContain(
      'This will record that these records show the same person.',
    );
    expect(panel.root.textContent).toContain('2 evidence points across 2 memory regions');
    expect(panel.root.textContent).toContain(
      'This build does not yet expose the undo control.',
    );
    expect(panel.root.textContent).not.toContain('[object Object]');
    expect(onVisibilityChange).toHaveBeenLastCalledWith(true);
    expect(panel.root.getAttribute('role')).toBe('dialog');
    expect(document.activeElement?.textContent).toBe('Confirm');

    panel.root.querySelector<HTMLButtonElement>('button.primary')?.click();
    expect(onConfirm).toHaveBeenCalledWith('proposal-1');
    panel.hide();
    expect(onVisibilityChange).toHaveBeenLastCalledWith(false);
  });

  it('renders a concrete name from the proposal payload', () => {
    const panel = buildConfirm({ onConfirm: vi.fn(), onCancel: vi.fn() });
    panel.show(
      'proposal-2',
      summary(pendingRow('row.name', { predicateKey: 'name_is', displayName: 'Julie' })),
      'That is Julie',
    );
    expect(panel.root.textContent).toContain('This will record the name “Julie”.');
  });

  it('names the available undo control only for a reversible operation', () => {
    const panel = buildConfirm({ onConfirm: vi.fn(), onCancel: vi.fn() });
    const proposed = summary(pendingRow('row.note', { text: 'Move the cube' }));
    panel.show('move', proposed, 'Move the cube', { undoControlAvailable: true });
    expect(panel.root.textContent).toContain('Use “Take back the last change” in the object panel');
    expect(panel.root.textContent).not.toContain('does not yet expose');
    panel.show('bootstrap', { ...proposed, reversible: false }, 'Open a version', {
      undoControlAvailable: true,
    });
    expect(panel.root.textContent).toContain('This cannot be undone.');
    expect(panel.root.textContent).not.toContain('Take back the last change');
    panel.show('other-caller', proposed, 'Another proposal');
    expect(panel.root.textContent).toContain('does not yet expose the undo control');
  });
});
