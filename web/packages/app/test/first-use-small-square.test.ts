// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import { buildCompanionPanel } from '../src/ui/companion-panel.js';
import { createFirstUseGuidance, type FirstUsePromptAction } from '../src/ui/first-use-guidance.js';
import { OBJECT_ROLE_LABELS } from '../src/world-objects-api.js';

/**
 * "Start with a small square" on the welcome card.
 *
 * The card offers the square only where the Create panel would, and it never answers for the
 * person: a role is chosen, never inferred, so the offer asks it with one control per role the one
 * role table holds. What the chosen role then does is the Create panel's own square
 * (test/arrangement.test.ts).
 */

const NOOP = {
  onSelect: () => undefined,
  onSubmit: () => undefined,
  onSay: () => undefined,
  onEvidence: () => undefined,
};

const storage = () => ({ getItem: () => null, setItem: () => undefined });

const labels = (actions: readonly FirstUsePromptAction[] | undefined): string[] =>
  (actions ?? []).map((action) => action.label);

describe('the welcome offers a small square where the Create panel would', () => {
  it('offers it beside Start building only when the world takes one', () => {
    const offered = createFirstUseGuidance(storage(), { smallSquareOffered: () => true });
    expect(offered.prompt('converse')?.actions).toEqual([
      { label: 'Start building', activate: 'summon-companion' },
      { label: 'Start with a small square', activate: 'small-square' },
      { key: 'Esc', label: 'Dismiss', activate: 'dismiss' },
    ]);
    const notOffered = createFirstUseGuidance(storage(), { smallSquareOffered: () => false });
    expect(labels(notOffered.prompt('converse')?.actions)).toEqual(['Start building', 'Dismiss']);
    // Asking for a role where no square is offered changes nothing on the card.
    notOffered.askSmallSquareRole();
    expect(labels(notOffered.prompt('converse')?.actions)).toEqual(['Start building', 'Dismiss']);
  });

  it('asks what the square is to the person, one control per role, and sends no role itself', () => {
    const guidance = createFirstUseGuidance(storage(), { smallSquareOffered: () => true });
    guidance.askSmallSquareRole();
    const asked = guidance.prompt('converse');
    expect(asked?.kind).toBe('welcome');
    expect(asked?.statement).toBe('Place a small square in front of you. What is it to you?');
    const roles = Object.keys(OBJECT_ROLE_LABELS);
    expect(asked?.actions).toEqual([
      ...roles.map((role) => ({
        label: OBJECT_ROLE_LABELS[role as keyof typeof OBJECT_ROLE_LABELS],
        activate: 'place-small-square',
        role,
      })),
      { key: 'Esc', label: 'Dismiss', activate: 'dismiss' },
    ]);
    // Nothing on the welcome itself carries a role: the only role on the card is one a person picks.
    const welcome = createFirstUseGuidance(storage(), { smallSquareOffered: () => true }).prompt('converse');
    expect(welcome?.actions.some((action) => 'role' in action)).toBe(false);
  });

  it('stops asking once the greeting is over or the world holds something', () => {
    const finished = createFirstUseGuidance(storage(), { smallSquareOffered: () => true });
    finished.askSmallSquareRole();
    finished.complete();
    expect(finished.prompt('converse')).toBeNull();

    let content = false;
    const building = createFirstUseGuidance(storage(), {
      smallSquareOffered: () => true, worldHasContent: () => content,
    });
    building.askSmallSquareRole();
    content = true;
    expect(building.prompt('converse')).toBeNull();
  });
});

describe('the card renders the offer and the question as real controls', () => {
  it('hands the picked role to the host, and keeps keyboard focus on the card', () => {
    const onFirstUseAction = vi.fn();
    const panel = buildCompanionPanel(NOOP, { onFirstUseAction });
    document.body.replaceChildren(panel.root);
    const guidance = createFirstUseGuidance(storage(), { smallSquareOffered: () => true });
    panel.setFirstUsePrompt(guidance.prompt('converse'));
    const button = (label: string): HTMLButtonElement => {
      const found = [...panel.root.querySelectorAll<HTMLButtonElement>('button.companion-prompt-button')]
        .find((node) => node.textContent === label);
      if (found === undefined) throw new Error(`no “${label}” control`);
      return found;
    };

    const start = button('Start with a small square');
    start.focus();
    start.click();
    expect(onFirstUseAction).toHaveBeenLastCalledWith({
      label: 'Start with a small square', activate: 'small-square',
    });

    guidance.askSmallSquareRole();
    panel.setFirstUsePrompt(guidance.prompt('converse'));
    const invented = button(OBJECT_ROLE_LABELS.fictional);
    // The control that asked is gone; focus moves to the question's first answer, not the page.
    expect(document.activeElement).toBe(panel.root.querySelector('button.companion-prompt-button'));
    invented.click();
    expect(onFirstUseAction).toHaveBeenLastCalledWith({
      label: OBJECT_ROLE_LABELS.fictional, activate: 'place-small-square', role: 'fictional',
    });
  });
});
