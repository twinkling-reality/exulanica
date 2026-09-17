/**
 * Which look each subject wears in one application.
 *
 * The composition that knows the person decides: a catalog look, the abstract figure, or a
 * stylized example the native runtime draws. A subject nobody has chosen for yet wears the
 * catalog's designed default. Choosing never moves a subject or changes who it is; it only
 * changes what is drawn where the subject already stands.
 */
import type * as pc from 'playcanvas';
import { characterSubjectKey, type CharacterSubject } from '@exulanica/atlas-core';
import type { CharacterLook } from './look.js';
import { designedLook } from './look.js';
import { DESIGNED_LOOKS } from './looks-data.js';

export type CharacterChoice =
  | { readonly kind: 'catalog'; readonly look: CharacterLook }
  | { readonly kind: 'abstract' }
  /** A premade stylized example; the native character runtime draws it over the abstract root. */
  | { readonly kind: 'stylized' };

const APPLICATIONS = new WeakMap<pc.AppBase, CharacterChoices>();

export class CharacterChoices {
  private readonly chosen = new Map<string, CharacterChoice>();
  private readonly listeners = new Map<string, Set<(choice: CharacterChoice) => void>>();

  static forApp(app: pc.AppBase): CharacterChoices {
    let choices = APPLICATIONS.get(app);
    if (!choices) APPLICATIONS.set(app, (choices = new CharacterChoices()));
    return choices;
  }

  /** The player's designed default, before anyone chooses. */
  static defaultChoice(): CharacterChoice {
    return { kind: 'catalog', look: designedLook(DESIGNED_LOOKS, DESIGNED_LOOKS.defaults.player) };
  }

  choice(subject: CharacterSubject): CharacterChoice {
    return this.chosen.get(characterSubjectKey(subject)) ?? CharacterChoices.defaultChoice();
  }

  set(subject: CharacterSubject, choice: CharacterChoice): void {
    const key = characterSubjectKey(subject);
    this.chosen.set(key, choice);
    for (const listener of [...(this.listeners.get(key) ?? [])]) listener(choice);
  }

  subscribe(subject: CharacterSubject, listener: (choice: CharacterChoice) => void): () => void {
    const key = characterSubjectKey(subject);
    let set = this.listeners.get(key);
    if (!set) this.listeners.set(key, (set = new Set()));
    set.add(listener);
    return () => {
      set.delete(listener);
      if (set.size === 0 && this.listeners.get(key) === set) this.listeners.delete(key);
    };
  }
}
