// @vitest-environment happy-dom

import { describe, expect, it, vi } from 'vitest';
import { buildWorldIdentity } from '../src/ui/world-identity.js';
import type { SavedWorldEntry } from '../src/world-entry-api.js';
import { initialWorldShell, updateWorldShell } from '../src/world-shell.js';

const entry = (title = 'My world', revision = 1): SavedWorldEntry => ({
  entryId: '11111111-1111-4111-8111-111111111111',
  worldId: 'world:authored:starter', title, sourceKind: 'authored',
  sourceSnapshotId: '55555555-5555-4555-8555-555555555555',
  sourceSnapshotSha256: 'c'.repeat(64),
  authoredScene: {
    schemaVersion: 1, kind: 'authored-starter', region: {
      regionId: 'region:starter', origin: 'authored',
      module: { key: 'region.authored-ground', version: 1 },
      ground: { kind: 'flat', halfWidthMm: 12000, halfDepthMm: 12000, elevationMm: 0 },
      spawn: { xMm: 0, yMm: 0, zMm: 4000, yawMicroradians: 0 },
    },
  },
  authoredVersionId: '22222222-2222-4222-8222-222222222222',
  authoredStateSha256: 'a'.repeat(64), authoredEditSeq: 0,
  currentAuthoredStateSha256: 'a'.repeat(64), currentAuthoredEditSeq: 0,
  styleVersionId: '33333333-3333-4333-8333-333333333333', revision,
  availability: 'available', unavailableReason: null,
  sourceAttachments: [],
  createdAt: '2026-09-20T12:00:00Z', updatedAt: '2026-09-20T12:00:00Z',
});

describe('world identity controls', () => {
  it('renames through the supplied durable writer and opens photos as a contextual drawer', async () => {
    const intake = document.createElement('details');
    intake.append(document.createElement('summary'));
    const rename = vi.fn(async (title: string) => entry(title, 2));
    const onOpenWorld = vi.fn();
    const onAddObject = vi.fn();
    const onOpenPhotos = vi.fn();
    const identity = buildWorldIdentity({
      entry: entry(), personalIntake: intake, rename, onOpenWorld, onAddObject, onOpenPhotos,
      onClosePhotos: vi.fn(),
    });
    const input = identity.root.querySelector('input') as HTMLInputElement;
    input.value = 'Quiet garden';
    input.dispatchEvent(new Event('input'));
    input.closest('form')?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await Promise.resolve();
    await Promise.resolve();
    expect(rename).toHaveBeenCalledWith('Quiet garden');
    expect(input.value).toBe('Quiet garden');

    (identity.root.querySelector('.world-open-menu') as HTMLButtonElement).click();
    expect(onOpenWorld).toHaveBeenCalledOnce();
    (identity.root.querySelector('.world-add-object') as HTMLButtonElement).click();
    expect(onAddObject).toHaveBeenCalledOnce();
    (identity.root.querySelector('.world-add-photos') as HTMLButtonElement).click();
    expect(onOpenPhotos).toHaveBeenCalledOnce();
    identity.setPhotosVisible(true);
    expect(identity.photosDrawer.hidden).toBe(false);
    expect(identity.photosDrawer.contains(intake)).toBe(true);
    // The header is the drawer's sibling of the scrolling body, never inside what scrolls.
    const body = identity.photosDrawer.querySelector('.photos-drawer-body');
    expect(body?.contains(intake)).toBe(true);
    expect(body?.contains(identity.photosDrawer.querySelector('.photos-drawer-header'))).toBe(false);
  });

  it('returns from the photo workspace to the world canvas with an explicit destination label', () => {
    const intake = document.createElement('details');
    intake.append(document.createElement('summary'));
    let shell = updateWorldShell(initialWorldShell(), { type: 'toggle-photos' });
    expect(shell.primary).toBe('photos');
    const identity = buildWorldIdentity({
      entry: entry('My first world'),
      personalIntake: intake,
      rename: async (title) => entry(title),
      onOpenWorld: () => undefined,
      onAddObject: () => undefined,
      onOpenPhotos: () => undefined,
      onClosePhotos: () => {
        shell = updateWorldShell(shell, { type: 'toggle-photos' });
      },
    });
    identity.setPhotosVisible(true);
    const close = identity.photosDrawer.querySelector('.photos-drawer-close') as HTMLButtonElement;
    expect(close.textContent).toBe('Return to world');
    expect(close.getAttribute('aria-label')).toBe('Return to world');
    close.click();
    expect(shell.primary).toBe('world');
    expect(shell.returnStack).toEqual([]);
  });
});
