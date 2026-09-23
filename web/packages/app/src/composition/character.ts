import { createLatestCharacterPreview } from '../ui/latest-character-preview.js';
import type { BodyFamily, BodyRecipe } from '../ui/character-body.js';
import {
  CHARACTER_CATALOG,
  CharacterChoices,
  CharacterCrowdEvaluation,
  CharacterPreview,
  DESIGNED_LOOKS,
  FirstPersonGesture,
  NEAR_CHARACTER_BUDGET,
  designedLook,
  type AtlasBinding,
  type CharacterByteLoader,
  type CharacterLook as PersonLook,
  type NativeCharacterRuntime,
} from '@exulanica/atlas-react/playcanvas';
import { readBrowserAccount } from '../account-session.js';
import { characterByteLoader, parseCharacterLooks, workspaceCharacterLoader, type CharacterLook, type CharacterSelection } from '../character-catalog.js';
import { PreviewLookStore, StaleLookError, WorkspaceLookStore, worldLookTarget, type LookStore, type SavedChoice, type SavedLooks } from '../character-looks-store.js';
import { buildCharacterStudio, type PeopleChoice } from '../ui/character-studio.js';
import { el } from '../ui/dom.js';
import type { AppEnvironment, SessionState } from './session-state.js';

const PLAYER = { kind: 'player', playerId: 'local-viewer' } as const;

/**
 * How many people the development crowd evaluation places beside the player, from `?crowd=N`.
 * Zero unless the page is the development preview and N is a whole number from 1 to 128.
 */
export function previewCrowdSize(search: string, preview: boolean): number {
  if (!preview) return 0;
  const value = new URLSearchParams(search).get('crowd');
  if (value === null || !/^[1-9][0-9]{0,2}$/.test(value)) return 0;
  const count = Number(value);
  return count <= 128 ? count : 0;
}

/** Development containers exist only in a development build; production has no such module. */
function previewSources(): Promise<typeof import('../dev/character-sources.js')> {
  return import.meta.env.DEV
    ? import('../dev/character-sources.js')
    : Promise.reject(new Error('Character examples are available only on the development preview.'));
}

/** The default a reset returns to: the designed look for the body the person last wore. */
export function defaultLookChoice(current: SavedChoice | null): SavedChoice {
  const base = current?.kind === 'catalog' ? current.look.baseId : null;
  const lookId = (base !== null ? DESIGNED_LOOKS.defaults.bases[base] : undefined) ?? DESIGNED_LOOKS.defaults.player;
  return { kind: 'catalog', look: designedLook(DESIGNED_LOOKS, lookId) };
}

export function mountCharacter(deps: { env: AppEnvironment; state: SessionState; onClose(): void }) {
  const { env, state } = deps;
  const lifetime = new AbortController();
  // Saved looks. The preview keeps them in this browser. A saved or starter world keeps them in the
  // authenticated history of its version when the session belongs to an account; anywhere else they
  // last for the visit, and the studio says which (see `followWorld`).
  let lookStore: LookStore = env.preview ? new PreviewLookStore(defaultLookChoice) : new PreviewLookStore(defaultLookChoice, null);
  let lookStoreNote = env.preview ? 'Saved in this browser for this preview.' : 'Kept for this visit.';
  let saved: SavedLooks = { revision: 0, current: null };
  let disposed = false;
  let opened = false;
  let catalog: readonly CharacterLook[] = [];
  const generatedLooks = new Map<string, CharacterLook>();
  if (state.characterGeneratedLook) {
    generatedLooks.set(state.characterGeneratedLook.lookId, state.characterGeneratedLook);
  }
  let failedBodyRecipe: BodyRecipe | null = null;
  let bodyFamily: BodyFamily | null = null;
  // Committed containers by digest, filled from the development sources on the preview route.
  const previewFiles = new Map<string, string>();
  let previewLoader: CharacterByteLoader | null = null;
  let crowd: CharacterCrowdEvaluation | null = null;
  // A signed-in world fetches every catalog container as a reviewed asset of the session's own API.
  const loadCharacterBytes: CharacterByteLoader = (reference, signal) => {
    if (previewLoader !== null && previewFiles.has(reference.contentSha256)) return previewLoader(reference, signal);
    const generated = [...generatedLooks.values()];
    const isGenerated = generated.some(item => item.generated && item.descriptor.asset.contentSha256 === reference.contentSha256);
    if (!isGenerated && !env.preview && state.credentials) return workspaceCharacterLoader(state.credentials)(reference, signal);
    return characterByteLoader(generated)(reference, signal);
  };
  let catalogPromise: Promise<readonly CharacterLook[]> | null = null;
  let preview: CharacterPreview | null = null;
  let previewPromise: Promise<CharacterPreview> | null = null;
  let previewLook: string | null = null;
  let previewRevision = 0;
  let binding: AtlasBinding | null = null;
  let native: NativeCharacterRuntime | null = null;
  let unsubscribeResidents: (() => void) | null = null;
  let applying = false;
  const gestureCanvas = el('canvas', { class: 'first-person-gesture', 'aria-hidden': 'true' });
  gestureCanvas.hidden = true;
  let gesture: FirstPersonGesture | null = null;
  let gesturePromise: Promise<FirstPersonGesture> | null = null;
  let gestureReady = false;
  let gestureRevision = 0;

  const bodyUpdates = createLatestCharacterPreview<BodyRecipe, CharacterLook>({
    build: generateBody,
    pending: () => { previewRevision++; view.setBodyUpdating(); },
    ready: result => {
      failedBodyRecipe = null;
      generatedLooks.set(result.lookId, result);
      state.characterGeneratedLook = result;
      catalog = [...catalog.filter(item => !item.familyId), result];
      view.showGenerated(result);
    },
    failed: error => view.setFailure(error instanceof Error ? error.message : 'Preview update failed. Adjust a setting or try again.'),
  });
  const view = buildCharacterStudio({
    onPreviewLook: look => { void showPerson(look); },
    onApplyChoice: choice => { void applyChoice(choice); },
    onResetLook: restoreRevision => { void resetLook(restoreRevision); },
    onSelect: () => { bodyUpdates.cancel(); failedBodyRecipe = null; },
    onGenerateBody: recipe => bodyUpdates.request(recipe),
    onClose: () => { if (!applying) deps.onClose(); },
    onPreview: selection => { void showSelection(selection); },
    onApply: selection => { void apply(selection); },
    onRotate: yaw => preview?.rotate(yaw),
    onZoom: zoom => preview?.setZoom(zoom),
    onMotion: motion => preview?.setMotion(motion),
    onGestures: enabled => { state.characterGestures = enabled; if (!enabled) gesture?.cancel(); },
    onRetry: () => { if (failedBodyRecipe) bodyUpdates.request(failedBodyRecipe); else void open(); },
  });
  view.setGestures(state.characterGestures);
  function reducedMotion(): boolean {
    return env.systemReducedMotion.matches || state.preferences.transition === 'fade';
  }
  function reflectMotion(): void {
    const reduced = reducedMotion();
    view.setReducedMotion(reduced);
    preview?.setReducedMotion(reduced);
    if (reduced) gesture?.cancel();
  }
  env.systemReducedMotion.addEventListener('change', reflectMotion, { signal: lifetime.signal });
  window.addEventListener('keydown', event => {
    if (['Escape', 'KeyW', 'KeyA', 'KeyS', 'KeyD', 'Space', 'KeyC'].includes(event.code) &&
      !(event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement || event.target instanceof HTMLSelectElement)) gesture?.cancel();
  }, { signal: lifetime.signal });
  document.addEventListener('pointerlockchange', () => { if (document.pointerLockElement) gesture?.cancel(); }, { signal: lifetime.signal });

  async function prepareGesture(selection: CharacterSelection): Promise<void> {
    gestureReady = false;
    view.setGestureAvailable(false);
    gestureCanvas.dataset['availability'] = 'loading';
    gesture?.cancel();
    const revision = ++gestureRevision;
    const look = catalog.find(item => item.lookId === selection.lookId);
    if (!look?.gesture || disposed) return;
    try {
      gesturePromise ??= FirstPersonGesture.create(gestureCanvas, loadCharacterBytes, () =>
        !disposed && !opened && state.characterGestures && !reducedMotion() && binding?.cameraMode === 'first-person' &&
        env.shell.dataset['primary'] === 'world' && env.shell.dataset['camera'] === 'ground').then(result => {
        if (disposed) { result.destroy(); throw new Error('Gesture presentation closed.'); }
        gesture = result;
        return result;
      });
      const renderer = await gesturePromise;
      if (disposed || revision !== gestureRevision) return;
      await renderer.prepare(look.gesture.descriptor, selection.appearance);
      if (!disposed && revision === gestureRevision) {
        gestureReady = true;
        view.setGestureAvailable(true);
        gestureCanvas.dataset['availability'] = 'ready';
        delete gestureCanvas.dataset['failure'];
      }
    } catch (error) {
      // Tools remain immediately usable if this optional presentation cannot be drawn.
      gestureReady = false;
      view.setGestureAvailable(false);
      gestureCanvas.dataset['availability'] = 'unavailable';
      gestureCanvas.dataset['failure'] = error instanceof Error ? error.message : 'Gesture could not be loaded.';
    }
  }
  async function ensureCatalog(): Promise<readonly CharacterLook[]> {
    if (!env.preview) throw new Error('Character customization is not connected to this workspace yet.');
    catalogPromise ??= previewSources()
      .then(async sources => {
        const { looks, files } = await sources.developmentStylizedLooks(lifetime.signal);
        for (const [digest, file] of files) previewFiles.set(digest, file);
        previewLoader ??= sources.developmentCharacterLoader(previewFiles);
        return parseCharacterLooks(looks);
      })
      .catch(error => { catalogPromise = null; throw error; });
    if (!catalog.length) catalog = await catalogPromise;
    const retained = state.characterGeneratedLook;
    if (retained && state.characterSelection?.lookId === retained.lookId &&
        !catalog.some(item => item.lookId === retained.lookId)) {
      catalog = [...catalog.filter(item => !item.familyId), retained];
    }
    if (!bodyFamily && !lookStore) {
      try {
        const response = await fetch('/__character/family', { signal: lifetime.signal });
        if (!response.ok) throw new Error('Body builder unavailable');
        bodyFamily = await response.json() as BodyFamily;
        view.setBodyFamily(bodyFamily);
      } catch { view.setBodyUnavailable(); }
    }
    return catalog;
  }
  async function generateBody(recipe: BodyRecipe): Promise<CharacterLook> {
    failedBodyRecipe = recipe;
    const response = await fetch('/__character/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(recipe), signal: lifetime.signal });
    const result = await response.json() as CharacterLook & { error?: string };
    if (!response.ok) throw new Error(result.error ?? 'Preview update failed. Adjust a setting or try again.');
    return result;
  }
  async function ensurePreview(): Promise<CharacterPreview> {
    previewPromise ??= CharacterPreview.create(view.canvas, loadCharacterBytes).then(result => {
      if (disposed) { result.destroy(); throw new Error('Character view closed.'); }
      preview = result;
      result.setVisible(opened);
      reflectMotion();
      return result;
    }).catch(error => { previewPromise = null; throw error; });
    return previewPromise;
  }
  async function showSelection(selection: CharacterSelection): Promise<void> {
    const revision = ++previewRevision;
    const look = catalog.find(item => item.lookId === selection.lookId);
    if (!look) return;
    try {
      if (preview && previewLook === look.lookId) {
        preview.setAppearance(selection.appearance);
      } else {
        view.setStatus('Loading this look…', false);
        const renderer = await ensurePreview();
        if (revision !== previewRevision || disposed) return;
        await renderer.show(look.descriptor, selection.appearance);
        if (revision !== previewRevision || disposed) return;
        previewLook = look.lookId;
      }
      view.setStatus('Preview your look, then use it in the world.', true);
    } catch (error) {
      if (revision !== previewRevision || disposed) return;
      previewLook = null;
      view.setFailure(error instanceof Error ? error.message : 'The character could not be loaded.');
    }
  }
  function peopleChoice(): PeopleChoice {
    const choice = saved.current?.choice ?? defaultLookChoice(null);
    return choice;
  }
  /** Committed catalog containers the stage and the world fetch in the preview. */
  async function ensurePreviewSources(): Promise<void> {
    const sources = await previewSources();
    for (const [digest, file] of sources.catalogCharacterFiles()) previewFiles.set(digest, file);
    previewLoader ??= sources.developmentCharacterLoader(previewFiles);
  }
  async function showPerson(look: PersonLook): Promise<void> {
    const revision = ++previewRevision;
    try {
      view.setPeopleStatus('Loading this person…', false);
      if (env.preview) await ensurePreviewSources();
      const renderer = await ensurePreview();
      if (revision !== previewRevision || disposed) return;
      await renderer.showLook(look);
      if (revision !== previewRevision || disposed) return;
      previewLook = null;
      view.setPeopleStatus('Preview this person, then use them in the world.', true);
    } catch (error) {
      if (revision !== previewRevision || disposed) return;
      view.setPeopleStatus(error instanceof Error ? error.message : 'This person could not be loaded. Choose another look or try again.', false);
    }
  }
  /** Put a saved choice on the player in the world. */
  async function wear(choice: SavedChoice): Promise<void> {
    if (choice.kind === 'stylized') {
      await ensureCatalog();
      state.characterSelection = choice.selection;
      await install(choice.selection);
      void prepareGesture(choice.selection);
      return;
    }
    state.characterSelection = null;
    if (binding) CharacterChoices.forApp(binding.app).set(PLAYER, choice.kind === 'catalog' ? { kind: 'catalog', look: choice.look } : { kind: 'abstract' });
  }
  async function reflectSaved(): Promise<void> {
    view.setHistory(await lookStore.history());
  }
  let actorPromise: Promise<string | null> | null = null;
  /** The account the session belongs to, or null for a session opened without one. */
  function accountActor(): Promise<string | null> {
    actorPromise ??= readBrowserAccount().then(
      account => (account.kind === 'authenticated' ? account.session.actor : null),
      () => null,
    );
    return actorPromise;
  }
  /**
   * Saved looks follow the world open now: a saved or starter world keeps them with its version,
   * as the signed-in account's avatar. The owned district holds no version the client can name,
   * and a session opened with an operator token names no account, so there they last for the visit.
   */
  async function followWorld(): Promise<void> {
    if (env.preview || !state.credentials) return;
    const entry = state.activeWorldEntry;
    const where = worldLookTarget(entry, entry ? await accountActor() : null);
    if (where.target) {
      lookStore = new WorkspaceLookStore(state.credentials, where.target);
      lookStoreNote = 'Saved to this world.';
    } else {
      lookStore = new PreviewLookStore(defaultLookChoice, null);
      lookStoreNote = where.missing === 'account'
        ? 'Kept for this visit: saving looks to this world needs an account sign-in.'
        : 'Kept for this visit: this place has no saved version to keep looks with.';
    }
    saved = { revision: 0, current: null };
  }
  async function applyChoice(choice: PeopleChoice): Promise<void> {
    if (applying || disposed) return;
    applying = true;
    view.setPeopleStatus('Applying your look…', false);
    try {
      await wear(choice);
      if (disposed) return;
      if (lookStore.keeps(choice)) saved = await lookStore.save(choice, saved.revision);
      await reflectSaved();
      binding?.setCameraMode('third-person');
      binding?.setCameraFraming(2.4);
      applying = false;
      deps.onClose();
    } catch (error) {
      if (disposed) return;
      if (error instanceof StaleLookError) {
        saved = await lookStore.read();
        await reflectSaved();
      }
      view.setPeopleStatus(error instanceof Error ? error.message : 'This look could not be applied.', true);
    } finally { applying = false; }
  }
  async function resetLook(restoreRevision?: number): Promise<void> {
    if (applying || disposed) return;
    try {
      saved = await lookStore.reset(saved.revision, restoreRevision);
      const choice = saved.current!.choice;
      await wear(choice);
      if (disposed) return;
      view.setPeople(CHARACTER_CATALOG, DESIGNED_LOOKS, choice);
      await reflectSaved();
      if (choice.kind === 'catalog') await showPerson(choice.look);
      else if (choice.kind === 'stylized') await showSelection(choice.selection);
      else view.setPeopleStatus('You are wearing the abstract figure.', true);
    } catch (error) {
      if (disposed) return;
      if (error instanceof StaleLookError) {
        saved = await lookStore.read();
        await reflectSaved();
      }
      view.setPeopleStatus(error instanceof Error ? error.message : 'Your saved look could not be restored.', true);
    }
  }
  async function open(): Promise<void> {
    try {
      if (env.preview) {
        // Premade examples and the generated body builder exist only on the development preview.
        await ensureCatalog();
        if (!opened || disposed) return;
        const selection = state.characterSelection ?? { lookId: catalog[0]!.lookId, appearance: {} };
        const retained = generatedLooks.get(selection.lookId);
        if (retained && !catalog.some(item => item.lookId === retained.lookId)) catalog = [...catalog.filter(item => !item.familyId), retained];
        view.setCatalog(catalog, selection);
      }
      saved = await lookStore.read();
      if (!opened || disposed) return;
      const choice = peopleChoice();
      view.setPeople(CHARACTER_CATALOG, DESIGNED_LOOKS, choice);
      view.setSaveNote(lookStoreNote);
      await reflectSaved();
      if (choice.kind === 'catalog') await showPerson(choice.look);
      else if (choice.kind === 'stylized') await showSelection(choice.selection);
      else view.setPeopleStatus('You are wearing the abstract figure.', true);
    } catch (error) {
      if (!disposed) view.setFailure(error instanceof Error ? error.message : 'Character looks are unavailable.');
    }
  }
  async function install(selection: CharacterSelection): Promise<void> {
    if (!binding || !native) throw new Error('The world is still loading. Try again in a moment.');
    const look = catalog.find(item => item.lookId === selection.lookId);
    if (!look) throw new Error('That look is no longer available.');
    // A stylized example is drawn by the native runtime, which adopts the player once the player
    // is no longer wearing a catalog person.
    CharacterChoices.forApp(binding.app).set(PLAYER, { kind: 'stylized' });
    for (let frame = 0; frame < 60 && !native.inspect(PLAYER); frame++) {
      if (disposed) return;
      await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
    }
    await native.install(PLAYER, look.descriptor, selection.appearance,
      () => ({ presence: disposed ? 'denied' : 'allowed', source: 'available' }));
    if (native.inspect(PLAYER)?.status !== 'ready') throw new Error('The character could not be applied. Try another look.');
  }
  async function apply(selection: CharacterSelection): Promise<void> {
    if (applying || disposed) return;
    applying = true;
    view.setStatus('Applying your look…', false);
    try {
      await install(selection);
      if (disposed) return;
      state.characterSelection = selection;
      void prepareGesture(selection);
      binding!.setCameraMode('third-person');
      binding!.setCameraFraming(2.4);
      applying = false;
      deps.onClose();
    } catch (error) {
      if (!disposed) view.setStatus(error instanceof Error ? error.message : 'This look could not be applied.', true);
    } finally { applying = false; }
  }
  return {
    root: view.root, gestureRoot: gestureCanvas,
    reach() {
      if (env.preview && gestureReady && state.characterGestures && !reducedMotion() &&
        !opened && binding?.cameraMode === 'first-person') gesture?.play(state.preferences.fieldOfView);
    },
    setVisible(visible: boolean) {
      const changed = opened !== visible;
      opened = visible;
      if (visible) gesture?.cancel();
      else { bodyUpdates.cancel(); failedBodyRecipe = null; }
      view.setVisible(visible);
      preview?.setVisible(visible);
      reflectMotion();
      if (visible && changed) void open();
    },
    async attach(atlas: AtlasBinding): Promise<void> {
      unsubscribeResidents?.();
      unsubscribeResidents = null;
      crowd?.destroy();
      crowd = null;
      binding = atlas;
      if (!env.preview) {
        // A signed-in world draws the same catalog people from its reviewed assets, and the player
        // wears what this world keeps for them.
        if (state.credentials) native = atlas.enableNativeCharacters(workspaceCharacterLoader(state.credentials));
        try {
          await followWorld();
          saved = await lookStore.read();
          if (disposed || binding !== atlas || !saved.current) return;
          await wear(saved.current.choice);
        } catch (error) {
          if (!disposed) view.setPeopleStatus(error instanceof Error ? error.message : 'Your saved look could not be read.', true);
        }
        return;
      }
      try {
        // Catalog people need only the byte loader, never the stylized look list: register it
        // first, so a look list that cannot be read never leaves people as placeholders.
        await ensurePreviewSources();
        if (disposed) return;
        native = atlas.enableNativeCharacters(loadCharacterBytes);
        const crowdSize = previewCrowdSize(window.location.search, env.preview);
        if (crowdSize > 0) crowd = CharacterCrowdEvaluation.mount(atlas, { count: crowdSize, nearBudget: NEAR_CHARACTER_BUDGET });
        // Ensure the existing player presentation exists without changing the active camera. It
        // wears the catalog's designed default until the person chooses otherwise.
        atlas.setCameraMode(atlas.cameraMode);
        saved = await lookStore.read();
        if (disposed || !saved.current) return;
        await wear(saved.current.choice);
      } catch (error) {
        if (!disposed) view.setFailure(error instanceof Error ? error.message : 'Character looks are unavailable.');
      }
    },
    dispose() { disposed = true; bodyUpdates.dispose(); unsubscribeResidents?.(); crowd?.destroy(); lifetime.abort(); previewRevision++; gestureRevision++; preview?.destroy(); gesture?.destroy(); },
  };
}
