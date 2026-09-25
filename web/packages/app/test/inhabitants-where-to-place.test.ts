// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@exulanica/graph-client';
import type { AtlasScene } from '@exulanica/atlas-core';
import { mountEnvironmentSelection } from '../src/composition/environment-selection.js';
import type { LiveSocietyView } from '../src/composition/live-society.js';
import type { AppEnvironment, SessionState } from '../src/composition/session-state.js';
import { say } from '../src/ui/copy.js';
import { buildWorldInhabitants, refusalWords } from '../src/ui/world-inhabitants.js';
import { buildWorldWorkspace } from '../src/ui/world-workspace.js';

/**
 * The inhabitants panel's sentences that say they need somewhere to go also say where a person
 * places something: the Create tab and its "Add and arrange objects" control. The pointer names
 * both controls by the copy keys the controls themselves render, so renaming either one changes
 * the pointer with it, and this file fails if a control stops reading its key.
 */

const POINTER = say('inhabitants.whereToPlace');

describe('where inhabitants need somewhere, the panel says where to place it', () => {
  it('in both refusals that say there is nowhere to go', () => {
    expect(refusalWords({ status: 409, code: 'nowhere_to_arrive', detail: 'no reachable node' }))
      .toMatch(/^They cannot come back yet: .* then ask again\. /);
    expect(refusalWords({ status: 409, code: 'nowhere_to_arrive', detail: '' }).endsWith(POINTER)).toBe(true);
    const fallback = refusalWords({
      status: 409, code: 'no_reachable_targets', detail: 'initial society requires reachable targets',
    });
    expect(fallback).toMatch(/^Nobody came in: /);
    expect(fallback.endsWith(POINTER)).toBe(true);
  });

  it('in the need text shown before anyone lives here', () => {
    const panel = buildWorldInhabitants({
      onBringIn: vi.fn(), onAdvance: vi.fn(), onSendAway: vi.fn(), onBringBack: vi.fn(),
    });
    const society: LiveSocietyView = {
      mode: 'authenticated', status: 'absent', busy: false, snapshot: null, events: [], eventsAvailable: false,
      message: 'Nobody lives in this world yet.', refusal: null,
    } as unknown as LiveSocietyView;
    panel.render({ society, objects: [], walked: 0, advanceBlocked: null });
    const need = [...panel.root.querySelectorAll<HTMLElement>('p.world-help')]
      .find((node) => node.textContent?.startsWith('They need somewhere to go'));
    expect(need?.hidden).toBe(false);
    expect(need?.textContent).toBe(
      `They need somewhere to go: something to rest on or visit. ${POINTER} Nothing comes in until you ask.`,
    );
  });
});

describe('the pointer names the controls a person sees', () => {
  it('names the Create tab and the control that opens the objects', () => {
    expect(POINTER).toContain(say('worldControls.create'));
    expect(POINTER).toContain(say('worldControls.addAndArrange'));
  });

  it('the Create tab reads its key', () => {
    const node = () => document.createElement('div');
    const root = node();
    buildWorldWorkspace({
      root, title: node(), fixture: node(), source: node(), selected: node(), reason: node(), inspector: node(),
      inhabitants: node(), camera: [], tools: [], authoring: node(),
    });
    const tabs = [...root.querySelectorAll('nav.world-local-nav button')].map((button) => button.textContent);
    expect(tabs).toContain(say('worldControls.create'));
  });

  it('the objects control reads its key', () => {
    const missing = () => new ApiError(404, 'unknown_reference', 'no such society');
    const binding = {
      controls: { state: { x: 0, y: 1.68, z: 4 }, onInteract: null, forward: () => ({ x: 0, y: 0, z: -1 }) },
      camera: { forward: { x: 0, y: 0, z: -1 } }, invalidate: vi.fn(),
      ownedDistrict: null, generatedTile: null, authoredSociety: null,
      memoryLayerVisible: true, onMemoryLayerChange: null, setMemoryLayerVisible: vi.fn(),
      cameraMode: 'first-person', setCameraMode: vi.fn(), setCameraFraming: vi.fn(),
      setCityView: vi.fn(), turnCamera: vi.fn(), setWalkAssist: vi.fn(),
    };
    const onObjects = vi.fn();
    const mounted = mountEnvironmentSelection({
      env: { canvas: document.createElement('canvas'), preview: false } as unknown as AppEnvironment,
      state: { atlas: { binding }, activeWorldEntry: null } as unknown as SessionState,
      scene: { islands: [] } as unknown as AtlasScene,
      credentials: { baseUrl: 'https://example.test', token: 'token' },
      showStatus: vi.fn(), admissionId: null,
      worldClient: { connect: vi.fn(async () => { throw missing(); }) } as never,
      societyClient: { read: vi.fn(async () => { throw missing(); }), events: vi.fn(async () => []) } as never,
      societyControlClient: { read: vi.fn(async () => { throw missing(); }) } as never,
      onObjects,
    });
    try {
      const control = [...mounted.root.querySelectorAll<HTMLButtonElement>('button')]
        .find((button) => button.textContent === say('worldControls.addAndArrange'));
      expect(control).toBeDefined();
      control?.click();
      expect(onObjects).toHaveBeenCalledTimes(1);
    } finally {
      mounted.dispose();
    }
  });
});
