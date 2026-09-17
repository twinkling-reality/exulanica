import type * as pc from 'playcanvas';
import { describe, expect, it, vi } from 'vitest';
import { CharacterChoices } from '../src/playcanvas/character/choices.js';
import { designedLook } from '../src/playcanvas/character/look.js';
import { DESIGNED_LOOKS } from '../src/playcanvas/character/looks-data.js';

const player = { kind: 'player', playerId: 'local-viewer' } as const;
const app = () => ({}) as pc.AppBase;

describe('character choices', () => {
  it('dress an unchosen player in the designed default and keep choices per application', () => {
    const first = CharacterChoices.forApp(app());
    const expected = designedLook(DESIGNED_LOOKS, DESIGNED_LOOKS.defaults.player);
    expect(first.choice(player)).toEqual({ kind: 'catalog', look: expected });
    first.set(player, { kind: 'abstract' });
    expect(first.choice(player)).toEqual({ kind: 'abstract' });
    expect(CharacterChoices.forApp(app()).choice(player).kind).toBe('catalog');
  });

  it('tell only the subject whose look changed, until it stops listening', () => {
    const application = app();
    const choices = CharacterChoices.forApp(application);
    expect(CharacterChoices.forApp(application)).toBe(choices);
    const mine = vi.fn(), theirs = vi.fn();
    const stop = choices.subscribe(player, mine);
    choices.subscribe({ kind: 'player', playerId: 'someone-else' }, theirs);
    const look = designedLook(DESIGNED_LOOKS, 'suit-masculine');
    choices.set(player, { kind: 'catalog', look });
    expect(mine).toHaveBeenCalledWith({ kind: 'catalog', look });
    expect(theirs).not.toHaveBeenCalled();
    stop();
    choices.set(player, { kind: 'stylized' });
    expect(mine).toHaveBeenCalledOnce();
  });
});
