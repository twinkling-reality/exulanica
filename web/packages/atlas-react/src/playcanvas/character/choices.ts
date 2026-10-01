/**
 * Which look each subject wears in one application.
 *
 * The composition that knows the person decides: a catalog look over a published catalog, the
 * abstract figure, or a body the native runtime draws. A subject nobody has chosen for yet wears
 * the designed default of the people catalog the host serves, and the abstract figure, the
 * contract's explicit stand-in, while none is served. Choosing never moves a subject or changes
 * who it is; it only changes what is drawn where the subject already stands.
 */
import type * as pc from 'playcanvas';
import { characterSubjectKey, type CharacterSubject } from '@exulanica/atlas-core';
import type { CharacterCatalog } from './catalog.js';
import type { CharacterLook } from './look.js';
import { designedLook } from './look.js';
import { CharacterCatalogs } from './served.js';

export type CharacterChoice =
  /** A catalog person: a look and the published catalog it is a recipe over. */
  | { readonly kind: 'catalog'; readonly look: CharacterLook; readonly catalog: CharacterCatalog }
  | { readonly kind: 'abstract' }
  /** A body the native character runtime draws over the abstract root (an example or a prepared body). */
  | { readonly kind: 'stylized' };

const APPLICATIONS = new WeakMap<pc.AppBase, CharacterChoices>();

export class CharacterChoices {
  private readonly chosen = new Map<string, CharacterChoice>();
  private readonly listeners = new Map<string, Set<(choice: CharacterChoice) => void>>();

  private constructor(private readonly app: pc.AppBase) {}

  static forApp(app: pc.AppBase): CharacterChoices {
    let choices = APPLICATIONS.get(app);
    if (!choices) APPLICATIONS.set(app, (choices = new CharacterChoices(app)));
    return choices;
  }

  /** The player's designed default before anyone chooses: the served people catalog's, if any. */
  defaultChoice(): CharacterChoice {
    const people = CharacterCatalogs.forApp(this.app).people;
    if (people === null) return { kind: 'abstract' };
    return { kind: 'catalog', look: designedLook(people.looks, people.looks.defaults.player), catalog: people.catalog };
  }

  choice(subject: CharacterSubject): CharacterChoice {
    return this.chosen.get(characterSubjectKey(subject)) ?? this.defaultChoice();
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
