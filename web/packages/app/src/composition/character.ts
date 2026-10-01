import { createLatestCharacterPreview } from '../ui/latest-character-preview.js';
import type { BodyFamily, BodyRecipe } from '../ui/character-body.js';
import {
  CharacterCatalogs,
  CharacterChoices,
  CharacterCrowdEvaluation,
  CharacterPreview,
  FirstPersonGesture,
  NEAR_CHARACTER_BUDGET,
  designedLook,
  parametricNativeDescriptor,
  worldViews,
  type AtlasBinding,
  type CatalogPublicationEntry,
  type CharacterByteLoader,
  type CharacterCatalog,
  type CharacterLook as PersonLook,
  type NativeCharacterRuntime,
  type ServedCharacterCatalog,
  type ServedLayeredCatalog,
} from '@exulanica/atlas-react/playcanvas';
import { readBrowserAccount } from '../account-session.js';
import {
  characterByteLoader,
  characterCatalogList,
  parseCharacterLooks,
  servedCharacterCatalog,
  workspaceCharacterLoader,
  type CharacterLook,
  type CharacterSelection,
} from '../character-catalog.js';
import { lookInCatalog, sameLook } from '../character-look.js';
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

/**
 * The default a reset returns to: the served people catalog's designed look for the body the person
 * last wore, or its player default. With no people catalog served, the abstract figure, which is
 * the contract's explicit stand-in, never a look the host did not serve.
 */
export function defaultLookChoice(people: ServedLayeredCatalog | null, current: SavedChoice | null): SavedChoice {
  if (people === null) return { kind: 'abstract' };
  const designed = people.looks;
  const base = current?.kind === 'catalog' ? current.look.baseId : null;
  const lookId = (base !== null ? designed.defaults.bases[base] : undefined) ?? designed.defaults.player;
  return { kind: 'catalog', look: designedLook(designed, lookId), catalogSha256: people.catalogSha256 };
}

/** What the studio shows for a saved choice; a choice it has no control for shows the figure. */
function studioChoice(choice: SavedChoice): PeopleChoice {
  if (choice.kind === 'catalog') return { kind: 'catalog', look: choice.look };
  if (choice.kind === 'stylized') return choice;
  if (choice.kind === 'prepared') return { kind: 'stylized', selection: { lookId: choice.representationId, appearance: {} } };
  return { kind: 'abstract' };
}

/**
 * The studio edits recipes over the people catalog served now. A look saved over another revision
 * opens as its nearest look there (`lookInCatalog`), and `moved` says the two differ, so the stage
 * can show what Use in world would save instead of the look the world is still wearing.
 */
export function editableChoice(people: ServedLayeredCatalog, choice: PeopleChoice): { readonly choice: PeopleChoice; readonly moved: boolean } {
  if (choice.kind !== 'catalog') return { choice, moved: false };
  const look = lookInCatalog(people.catalog, people.looks, choice.look);
  return { choice: { kind: 'catalog', look }, moved: !sameLook(look, choice.look) };
}

export function mountCharacter(deps: { env: AppEnvironment; state: SessionState; onClose(): void }) {
  const { env, state } = deps;
  const lifetime = new AbortController();
  // Saved looks. The preview keeps them in this browser. A saved or starter world keeps them in the
  // authenticated history of its version when the session belongs to an account; anywhere else they
  // last for the visit, and the studio says which (see `followWorld`).
  // The people catalog the host served this page, and every served publication by digest.
  let people: ServedLayeredCatalog | null = null;
  const served = new Map<string, ServedCharacterCatalog>();
  let listing: readonly CatalogPublicationEntry[] = [];
  const defaultChoice = (current: SavedChoice | null): SavedChoice => defaultLookChoice(people, current);
  const holding = new CharacterCatalogs();
  /** Hold a served catalog here and in the open world, which draws its people from the same one. */
  function adopt(catalog: ServedCharacterCatalog): void {
    served.set(catalog.catalogSha256, catalog);
    holding.add(catalog);
    people = holding.people;
    if (binding) CharacterCatalogs.forApp(binding.app).add(catalog);
  }
  /** The people catalog a saved catalog look is a recipe over: its own publication, else the current one. */
  function catalogOf(choice: { readonly catalogSha256?: string }): CharacterCatalog | null {
    const held = choice.catalogSha256 === undefined ? people : served.get(choice.catalogSha256);
    return held?.kind === 'layered-people' ? held.catalog : null;
  }
  /** Every catalog the host serves now, fetched by digest once per page. */
  async function ensureServed(): Promise<void> {
    if (!state.credentials || people !== null) return;
    listing = await characterCatalogList(state.credentials);
    for (const entry of listing) {
      if (entry.state === 'current') adopt(await servedCharacterCatalog(state.credentials, entry));
    }
  }
  /** A served publication by digest, retained ones included, as a saved look names it. */
  async function resolveCatalog(catalogSha256: string): Promise<ServedCharacterCatalog | null> {
    const held = served.get(catalogSha256);
    if (held) return held;
    const entry = listing.find((candidate) => candidate.catalog_sha256 === catalogSha256);
    if (!entry || !state.credentials) return null;
    const fetched = await servedCharacterCatalog(state.credentials, entry);
    adopt(fetched);
    return fetched;
  }
  const peopleCatalog = (): CharacterCatalog | null => people?.catalog ?? null;
  let lookStore: LookStore = env.preview
    ? new PreviewLookStore(defaultChoice, undefined, peopleCatalog)
    : new PreviewLookStore(defaultChoice, null, peopleCatalog);
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
  /** Committed catalog containers the stage and the world fetch in the preview. */
  async function ensurePreviewSources(): Promise<void> {
    const sources = await previewSources();
    if (people === null) adopt(await sources.developmentPeopleCatalog(lifetime.signal));
    for (const [digest, file] of sources.catalogCharacterFiles(people!.catalog)) previewFiles.set(digest, file);
    previewLoader ??= sources.developmentCharacterLoader(previewFiles);
  }
  async function showPerson(look: PersonLook, catalog?: CharacterCatalog | null): Promise<void> {
    const revision = ++previewRevision;
    try {
      view.setPeopleStatus('Loading this person…', false);
      if (env.preview) await ensurePreviewSources();
      const renderer = await ensurePreview();
      if (revision !== previewRevision || disposed) return;
      const drawn = catalog ?? peopleCatalog();
      if (drawn === null) throw new Error('people_catalog_unavailable');
      await renderer.showLook(look, drawn);
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
    if (choice.kind === 'prepared') {
      await wearPrepared(choice);
      return;
    }
    state.characterSelection = null;
    if (!binding) return;
    const choices = CharacterChoices.forApp(binding.app);
    const catalogPerson = choice.kind === 'catalog' ? catalogOf(choice) : null;
    if (choice.kind === 'catalog' && catalogPerson !== null) {
      choices.set(PLAYER, { kind: 'catalog', look: choice.look, catalog: catalogPerson });
      return;
    }
    // The abstract figure stands in, and the person is told why: never somebody else's look.
    choices.set(PLAYER, { kind: 'abstract' });
    if (choice.kind === 'unavailable') view.setPeopleStatus(choice.code, true);
    else if (choice.kind === 'catalog') view.setPeopleStatus('catalog_unavailable', true);
  }
  /** A prepared body of a parametric family, drawn by the native runtime from its publication. */
  async function wearPrepared(choice: Extract<SavedChoice, { kind: 'prepared' }>): Promise<void> {
    const publication = served.get(choice.catalogSha256);
    const family = publication?.kind === 'parametric-body'
      ? publication.document.families.find((candidate) => candidate.familyId === choice.familyId)
      : undefined;
    const body = family?.representations.find((candidate) => candidate.representationId === choice.representationId);
    if (!family || !body || !binding) {
      if (binding) CharacterChoices.forApp(binding.app).set(PLAYER, { kind: 'abstract' });
      view.setPeopleStatus('preparation_unavailable', true);
      return;
    }
    const look: CharacterLook = {
      lookId: body.representationId,
      label: family.label,
      file: `${body.asset.assetKey}.glb`,
      creator: family.sources.map((source) => source.title).join(' · '),
      license: 'CC0',
      descriptor: parametricNativeDescriptor(family, body.descriptor, {
        assetKey: body.asset.assetKey,
        mediaType: body.asset.mediaType,
        contentSha256: body.asset.contentSha256,
        byteSize: body.asset.byteSize,
      }),
      defaultColors: family.colourSlots,
      familyId: family.familyId,
    };
    catalog = [...catalog.filter((item) => item.lookId !== look.lookId), look];
    const selection: CharacterSelection = { lookId: look.lookId, appearance: {} };
    state.characterSelection = selection;
    await install(selection);
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
      lookStore = new WorkspaceLookStore(state.credentials, where.target, resolveCatalog);
      lookStoreNote = 'Saved to this world.';
    } else {
      lookStore = new PreviewLookStore(defaultChoice, null, peopleCatalog);
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
    // A look made in the studio is a recipe over the people catalog the page was served.
    const chosen: SavedChoice = choice.kind === 'catalog' && people !== null ? { ...choice, catalogSha256: people.catalogSha256 } : choice;
    try {
      await wear(chosen);
      if (disposed) return;
      if (lookStore.keeps(chosen)) saved = await lookStore.save(chosen, saved.revision);
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
      await showStudioChoice(choice);
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
      if (env.preview) await ensurePreviewSources();
      else await ensureServed();
      saved = await lookStore.read();
      if (!opened || disposed) return;
      view.setSaveNote(lookStoreNote);
      await showStudioChoice(saved.current?.choice ?? defaultChoice(null));
    } catch (error) {
      if (!disposed) view.setFailure(error instanceof Error ? error.message : 'Character looks are unavailable.');
    }
  }
  /**
   * Put a saved choice in the studio. The editor works over the people catalog served now; a look
   * that catalog cannot draw opens as its nearest look there and says so by code, and a saved look
   * the host cannot resolve keeps the host's code beside the abstract figure that stands in.
   */
  async function showStudioChoice(current: SavedChoice): Promise<void> {
    const shown = studioChoice(current);
    const offered = people;
    if (offered === null) {
      // No people catalog is served, so there is nothing to edit; the studio says so by code.
      await reflectSaved();
      if (shown.kind === 'stylized') await showSelection(shown.selection);
      if (!disposed) view.setPeopleStatus(current.kind === 'unavailable' ? current.code : 'people_catalog_unavailable', false);
      return;
    }
    const editable = editableChoice(offered, shown);
    view.setPeople(offered.catalog, offered.looks, editable.choice);
    // After the people are set, so the history names designed looks by their labels.
    await reflectSaved();
    if (editable.choice.kind === 'catalog') {
      await showPerson(editable.choice.look, editable.moved ? offered.catalog : current.kind === 'catalog' ? catalogOf(current) : null);
      // Placeholder words for saved_look_options_not_offered: the page's own wording for this code
      // is not written yet.
      if (editable.moved && !disposed) view.setPeopleStatus('Your saved look uses options this studio no longer offers, so it opens on the nearest look it offers.', true);
    } else if (editable.choice.kind === 'stylized') await showSelection(editable.choice.selection);
    else view.setPeopleStatus(current.kind === 'unavailable' ? current.code : 'You are wearing the abstract figure.', true);
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
      view.setWorldView(worldViews(atlas.worldKind).thirdPerson);
      // The open world draws its inhabitants and the player's default from the catalogs this page
      // holds; a world opened after they arrived is given them at once.
      for (const held of served.values()) CharacterCatalogs.forApp(atlas.app).add(held);
      if (!env.preview) {
        // A signed-in world draws the people its host serves from its reviewed assets, and the
        // player wears what this world keeps for them, else the served designed default.
        if (state.credentials) native = atlas.enableNativeCharacters(workspaceCharacterLoader(state.credentials));
        try {
          await ensureServed();
          if (disposed || binding !== atlas) return;
          await followWorld();
          saved = await lookStore.read();
          if (disposed || binding !== atlas) return;
          await wear(saved.current?.choice ?? defaultChoice(null));
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
        if (disposed) return;
        await wear(saved.current?.choice ?? defaultChoice(null));
      } catch (error) {
        if (!disposed) view.setFailure(error instanceof Error ? error.message : 'Character looks are unavailable.');
      }
    },
    dispose() { disposed = true; bodyUpdates.dispose(); unsubscribeResidents?.(); crowd?.destroy(); lifetime.abort(); previewRevision++; gestureRevision++; preview?.destroy(); gesture?.destroy(); },
  };
}
