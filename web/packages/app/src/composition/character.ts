import { createLatestCharacterPreview } from '../ui/latest-character-preview.js';
import type { BodyFamily, BodyRecipe } from '../ui/character-body.js';
import { CharacterChoices, CharacterCrowdEvaluation, CharacterPreview, FirstPersonGesture, type AtlasBinding, type CharacterByteLoader, type NativeCharacterRuntime } from '@exulanica/atlas-react/playcanvas';
import { characterByteLoader, parseCharacterLooks, type CharacterLook, type CharacterSelection } from '../character-catalog.js';
import { buildCharacterStudio } from '../ui/character-studio.js';
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

export function mountCharacter(deps: { env: AppEnvironment; state: SessionState; onClose(): void }) {
  const { env, state } = deps;
  const lifetime = new AbortController();
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
  const loadCharacterBytes: CharacterByteLoader = (reference, signal) =>
    previewLoader !== null && previewFiles.has(reference.contentSha256)
      ? previewLoader(reference, signal)
      : characterByteLoader([...generatedLooks.values()])(reference, signal);
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
    if (!bodyFamily) {
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
  async function open(): Promise<void> {
    try {
      await ensureCatalog();
      if (!opened || disposed) return;
      const selection = state.characterSelection ?? { lookId: catalog[0]!.lookId, appearance: {} };
      const retained = generatedLooks.get(selection.lookId);
      if (retained && !catalog.some(item => item.lookId === retained.lookId)) catalog = [...catalog.filter(item => !item.familyId), retained];
      view.setCatalog(catalog, selection);
      await showSelection(selection);
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
      if (!env.preview) return;
      try {
        // Catalog people need only the byte loader, never the stylized look list: register it
        // first, so a look list that cannot be read never leaves people as placeholders.
        const sources = await previewSources();
        if (disposed) return;
        for (const [digest, file] of sources.catalogCharacterFiles()) previewFiles.set(digest, file);
        previewLoader ??= sources.developmentCharacterLoader(previewFiles);
        native = atlas.enableNativeCharacters(loadCharacterBytes);
        const crowdSize = previewCrowdSize(window.location.search, env.preview);
        if (crowdSize > 0) crowd = CharacterCrowdEvaluation.mount(atlas, { count: crowdSize, nearBudget: 24 });
        // Ensure the existing player presentation exists without changing the active camera. It
        // wears the catalog's designed default until the person chooses otherwise.
        atlas.setCameraMode(atlas.cameraMode);
        await ensureCatalog();
        if (disposed || !state.characterSelection) return;
        const selection = state.characterSelection;
        await install(selection);
        void prepareGesture(selection);
      } catch (error) {
        if (!disposed) view.setFailure(error instanceof Error ? error.message : 'Character looks are unavailable.');
      }
    },
    dispose() { disposed = true; bodyUpdates.dispose(); unsubscribeResidents?.(); crowd?.destroy(); lifetime.abort(); previewRevision++; gestureRevision++; preview?.destroy(); gesture?.destroy(); },
  };
}
