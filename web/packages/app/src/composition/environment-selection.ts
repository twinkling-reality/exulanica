import {
  type AtlasScene,
  type DistrictSubject,
} from '@exulanica/atlas-core';
import {
  localizeNYCFeatures,
  NEAR_CHARACTER_BUDGET,
  NYCSemanticOverlay,
  NYC_REFERENCE_FRAME,
  type OwnedSocietyState,
  type NYCLocalFeature,
} from '@exulanica/atlas-react/playcanvas';
import { nycOpenDataAdmissionId } from '../config.js';
import type { Credentials } from '../config.js';
import {
  clockText,
  parseLivingSocietyRecording,
  recordingState,
  type LivingSocietyRecording,
} from '../society-preview-presentation.js';
import {
  SocietyClient,
  type SocietyActionRecord,
  type SocietySnapshot,
} from '../society-api.js';
import {
  SocietyControlClient,
  type SocietyPlaybackControl,
  type SocietyPlaybackMode,
  type SocietyPlaybackSpeed,
} from '../society-control-api.js';
import { createLiveSociety, type LiveSociety, type LiveSocietyView } from './live-society.js';
import { SocietyDistrictClient, type SocietyDistrictPlacement, type SocietyDistrictView } from '../society-district-api.js';
import {
  EnvironmentSelectionClient,
  type EnvironmentCatalog,
  type EnvironmentPlacementRequest,
  type EnvironmentProposal,
} from '../environment-selection-api.js';
import { el } from '../ui/dom.js';
import { characterDisplayDetails } from '../ui/character-details.js';
import { buildRepresentationInspector } from '../ui/representation-inspector.js';
import {
  buildSocietyDirectedAction,
  type SocietyDirectedActionControl,
} from '../ui/society-directed-action.js';
import {
  buildWorldInhabitants,
  placeRows,
  type InhabitedObject,
} from '../ui/world-inhabitants.js';
import { buildWorldWorkspace } from '../ui/world-workspace.js';
import '../ui/living-world-inspector.css';
import { createLivingWorldInspector } from '../ui/living-world-inspector.js';
import {
  OBJECT_ROLE_LABELS,
  WorldObjectsClient,
  WorldObjectsContractError,
  objectWriteFailure,
  type AlternateVersion,
  type ObjectRole,
} from '../world-objects-api.js';
import type { AppEnvironment, SessionState } from './session-state.js';

/** Where the development preview's real-engine society recording is served. */
const SOCIETY_RECORDING_URL = '/preview-api/society/recording';
const RECORDING_SPEEDS = [
  [1, 'Real time'],
  [10, '10 times faster'],
  [60, '60 times faster'],
] as const;
const ACTIVITY_LABELS: Readonly<Record<string, string>> = {
  idle: 'waiting', move: 'walking', stroll: 'pausing on a walk', visit: 'visiting', rest: 'resting',
  eat_at_home: 'eating at home', eat_out: 'eating out', shop: 'shopping', sleep: 'sleeping',
  stay_home: 'at home', work: 'working',
};
const activityLabel = (kind: string): string => ACTIVITY_LABELS[kind] ?? kind.replaceAll('_', ' ');

export interface EnvironmentSelectionDependencies {
  readonly env: AppEnvironment;
  readonly state: SessionState;
  readonly scene: AtlasScene;
  readonly credentials: Credentials;
  readonly onPanelOpen?: () => void;
  readonly onObjects?: () => void;
  readonly showStatus: (message: string, kind?: 'progress' | 'failure') => void;
  /**
   * The admitted building now selected, or null. Only the admission and feature: the server
   * resolves the canonical place and any confirmed bridge from them when the Companion asks.
   */
  readonly onSelect?: (context: {
    readonly admissionId: string;
    readonly featureId: string;
  } | null) => void;
  readonly admissionId?: string | null;
  readonly environmentClient?: EnvironmentSelectionClient;
  readonly worldClient?: WorldObjectsClient;
  readonly societyClient?: SocietyClient;
  readonly societyControlClient?: SocietyControlClient;
  readonly societyDistrictClient?: SocietyDistrictClient;
  readonly onDistrictPlacementChange?: () => void;
  readonly createOverlay?: (
    features: readonly NYCLocalFeature[],
  ) => {
    pick(
      origin: readonly [number, number, number],
      direction: readonly [number, number, number],
    ): NYCLocalFeature | null;
    destroy(): void;
  };
}

export interface MountedEnvironmentSelection {
  readonly root: HTMLElement;
  begin(): Promise<void>;
  dispose(): void;
  closePanels(): void;
  openPanel(name: 'nearby' | 'authoring' | 'details'): void;
  setWelcomeVisible(visible: boolean): void;
  afterAuthoredEdit(versionId: string): Promise<void>;
  districtPlacement(): SocietyDistrictPlacement | null;
}

const instanceId = (feature: NYCLocalFeature): string =>
  `nyc-open-data:${feature.providerFeatureId.replace(':', '-')}`;

export function mountEnvironmentSelection(
  deps: EnvironmentSelectionDependencies,
): MountedEnvironmentSelection {
  const root = el('aside', {
    class: 'environment-selection',
    'aria-label': 'NYC Open Data semantic selection',
  });
  const inspector = createLivingWorldInspector();
  const title = el('h2', { text: 'NYC Open Data' });
  const source = el('p', {
    class: 'environment-selection-source',
    text: 'Source-backed building forms and sidewalks. Surface details are provisional.',
  });
  const selected = el('p', {
    class: 'environment-selection-selected',
    text: 'Aim at a building and press E to inspect its source.',
  });
  const reason = el('p', { class: 'environment-selection-reason' });
  const inhabitantsList = el('select', { 'aria-label': 'Inspect nearby inhabitant', hidden: true });
  inhabitantsList.addEventListener('change', () => { if (inhabitantsList.value) inspectInhabitant(inhabitantsList.value); });
  const overview = el('button', { type: 'button', text: 'City overview' });
  const street = el('button', { type: 'button', text: 'Street level' });
  const cameraToggle = el('button', { type: 'button', text: 'Third person (C)' });
  cameraToggle.addEventListener('click', () => {
    const binding = deps.state.atlas?.binding;
    if (!binding) return;
    binding.setCameraMode(binding.cameraMode === 'first-person' ? 'third-person' : 'first-person');
    cameraToggle.textContent = binding.cameraMode === 'first-person' ? 'Third person (C)' : 'First person (C)';
  });
  const reflectCamera = () => { cameraToggle.textContent = deps.state.atlas?.binding.cameraMode === 'third-person' ? 'First person (C)' : 'Third person (C)'; };
  deps.env.canvas?.addEventListener('camera-mode-change', reflectCamera);
  deps.env.canvas?.addEventListener('society-nearby-change', reflectNearby);
  const cameraFraming=el('select',{'aria-label':'Third-person framing'});
  for(const [value,text] of [['3.8','Follow'],['2.4','Figure study'],['.85','Portrait'],['6','Wide']])cameraFraming.append(el('option',{value,text}));
  cameraFraming.addEventListener('change',()=>{const binding=deps.state.atlas?.binding;binding?.setCameraMode('third-person');binding?.setCameraFraming(Number(cameraFraming.value));});
  const turnView=el('button',{type:'button',text:'Rotate view 90°'});
  turnView.addEventListener('click',()=>{deps.state.atlas?.binding.turnCamera(Math.PI/2);});
  const movementStatus=el('p',{'aria-live':'polite',text:'Hands-free movement follows the same collision controls. Escape stops.'});
  const movement=el('details',{},[el('summary',{text:'Movement assistance'}),movementStatus]);
  for(const [value,text] of [['walk','Walk forward'],['run','Run forward'],['off','Stop moving']] as const){
    const button=el('button',{type:'button',text});button.addEventListener('click',()=>{deps.state.atlas?.binding.setWalkAssist(value);movementStatus.textContent=value==='off'?'Stopped.':`${text}. Escape or Stop moving ends assistance.`;});movement.append(button);
  }
  const framing=el('details',{},[el('summary',{text:'Camera framing'}),cameraFraming,turnView]);
  const memoryLayer = el('label', { class: 'environment-selection-layer' }, [
    el('input', { type: 'checkbox' }),
    document.createTextNode(' Compose memory layer'),
  ]);
  const role = el('select', { 'aria-label': 'Authored role' });
  for (const value of ['fictional', 'personal'] as const) {
    role.append(el('option', { value, text: OBJECT_ROLE_LABELS[value] }));
  }
  const request = el('input', {
    type: 'text',
    'aria-label': 'Environment edit request',
    placeholder: 'Try “place this building”',
  });
  const ask = el('button', { type: 'button', text: 'Preview request', disabled: true });
  const place = el('button', { type: 'button', text: 'Bring into my world', disabled: true });
  const modify = el('button', { type: 'button', text: 'Lift and illuminate', disabled: true });
  const remove = el('button', { type: 'button', text: 'Preview removal', disabled: true });
  const undo = el('button', { type: 'button', text: 'Preview undo latest edit', disabled: true });
  const controls = el('div', {
    class: 'environment-selection-controls',
  }, [role, place, modify, remove, undo]);
  const language = el('div', { class: 'environment-selection-language' }, [request, ask]);
  const previewText = el('p', {
    class: 'environment-selection-preview',
    'aria-live': 'polite',
    text: 'No edit is waiting for review.',
  });
  const apply = el('button', { type: 'button', text: 'Apply', disabled: true });
  const discard = el('button', { type: 'button', text: 'Discard', disabled: true });
  const previewControls = el('div', {
    class: 'environment-selection-preview-controls',
    hidden: true,
  }, [apply, discard]);
  const editDetails = el('details', {}, [el('summary', { text: 'Authored changes' }), language, controls, previewText, previewControls]);
  const fixture = el('p', { class: 'living-world-fixture', text: 'Preview', hidden: !deps.env.preview });
  const workspace = buildWorldWorkspace({
    root, preview: deps.env.preview, title, fixture, source, selected, reason,
    onOpen: () => deps.onPanelOpen?.(),
    inspector: inspector.root, inhabitants: inhabitantsList,
    camera: [overview, street, cameraToggle],
    tools: [memoryLayer, framing, movement], authoring: editDetails,
  });


  const liveStatus = el('p', { role: 'status', 'aria-live': 'polite', text: 'Persisted society is not connected.' });
  const playbackStatus = el('p', { role: 'status', 'aria-live': 'polite', text: 'Playback controls are not connected.' });
  const playbackMode = el('button', { type: 'button', text: 'Play society', disabled: true });
  const playbackSpeed = el('select', { 'aria-label': 'Society playback speed', disabled: true });
  for (const speed of [1, 2, 4] as const) {
    playbackSpeed.append(el('option', { value: String(speed), text: `${speed}× speed` }));
  }
  const advanceSociety = el('button', { type: 'button', text: 'Advance one minute', disabled: true });
  const refreshSociety = el('button', { type: 'button', text: 'Refresh persisted society', disabled: true });
  playbackMode.addEventListener('click', () => void configurePlayback(
    societyControl?.mode === 'playing' ? 'paused' : 'playing',
  ));
  playbackSpeed.addEventListener('change', () => void configurePlayback(
    societyControl?.mode ?? 'paused', Number(playbackSpeed.value) as SocietyPlaybackSpeed,
  ));
  advanceSociety.addEventListener('click', () => void stepPlayback());
  refreshSociety.addEventListener('click', () => void (async () => {
    await refreshDistrict(); await refreshPlayback(true);
  })());
  const liveControls = el('details', { hidden: deps.env.preview }, [
    el('summary', { text: 'Living world simulation' }),
    liveStatus,
    playbackStatus,
    el('p', { text: 'Play, pause, change speed, or advance one simulated minute. Authored edits affect the next step. Restoring objects retains earlier simulation history.' }),
    playbackMode, playbackSpeed, advanceSociety, refreshSociety,
  ]);
  const representation = buildRepresentationInspector(() => deps.state.atlas?.binding ?? null, {
    starterGround: () => {
      const scene = deps.state.activeWorldEntry?.authoredScene;
      if (scene === null || scene === undefined) return null;
      // Rendered only when the atlas has mounted the authored region that draws this ground.
      return { renderedInView: deps.state.atlas != null };
    },
  });
  workspace.details.append(representation.root, liveControls);

  const authoringAvailability = el('p', { role: 'status', text: deps.env.preview
    ? 'Source-building edits require an authenticated world. Objects from the preview catalog are temporary and are never saved.'
    : 'Editing is unavailable until an authored world is connected.' });
  workspace.authoring.append(authoringAvailability);
  if (deps.onObjects) {
    const objectButton = el('button', { type: 'button', text: 'Add and arrange objects' });
    objectButton.addEventListener('click', () => { workspace.close(false); deps.onObjects?.(); });
    workspace.authoring.children[1]?.before(el('p', { text: 'Use the available object catalog to place and arrange objects.' }), objectButton);
  }

  const admissionId = deps.admissionId === undefined ? nycOpenDataAdmissionId() : deps.admissionId;
  const environmentClient = deps.environmentClient ?? new EnvironmentSelectionClient(deps.credentials);
  const worldClient = deps.worldClient ?? new WorldObjectsClient(deps.credentials);
  let liveSociety: LiveSociety | null = null;
  const districtAbort = new AbortController();
  const districtClient = deps.societyDistrictClient ?? new SocietyDistrictClient({ ...deps.credentials, signal: districtAbort.signal });
  const controlAbort = new AbortController();
  // A saved world's playback lives in that world, so its requests name it.
  const mountedEntry = deps.env.preview ? null : deps.state.activeWorldEntry;
  const controlClient = deps.societyControlClient ?? new SocietyControlClient({
    ...deps.credentials, signal: controlAbort.signal,
    ...(mountedEntry?.authoredScene == null ? {} : { worldId: mountedEntry.worldId }),
  });
  let districtView: SocietyDistrictView | null = null;
  let districtEpoch = 0;
  let districtFailure = 'Authorized district placement is not connected.';
  let catalog: EnvironmentCatalog | null = null;
  let current: AlternateVersion | null = null;
  let authoredWorldFailure: string | null = null;
  let chosen: NYCLocalFeature | null = null;
  let admittedFeaturesByProvider = new Map<string, NYCLocalFeature>();
  let releaseRepresentationSelection: (() => void) | null = null;
  let proposal: EnvironmentProposal | null = null;
  let contextEpoch = 0;
  let requestPending = false;
  let phase: 'idle' | 'attaching' | 'attached' | 'disposed' = 'idle';
  let beginPromise: Promise<void> | null = null;
  let overlay: {
    pick(
      origin: readonly [number, number, number],
      direction: readonly [number, number, number],
    ): NYCLocalFeature | null;
    destroy(): void;
  } | null = null;
  let installedInteract: (() => void) | null = null;
  let priorInteract: (() => void) | null = null;
  let societyTimer: number | null = null;
  let controlTimer: number | null = null;
  let societyControl: SocietyPlaybackControl | null = null;
  let controlBusy = false;
  let society: SocietySnapshot | null = null;
  let renderedSnapshot: SocietySnapshot | null = null;
  let selectedInhabitant: string | null = null;
  // What the inspector is showing. A society refresh re-renders an inspected inhabitant and
  // re-gates a destination's directed-action control; it never swaps one view for the other.
  let inspectedInhabitant: string | null = null;
  let directedAction: SocietyDirectedActionControl | null = null;
  /**
   * The saved world this mount serves, when it serves one. Its inhabitants are drawn over its
   * authored region and it has no district: nothing below that reads a district applies to it.
   */
  let savedWorld: { readonly worldId: string; readonly versionId: string; readonly regionId: string } | null = null;
  /** One directed-action control per usable place, kept across re-renders of the same person. */
  const savedWorldActions = new Map<string, SocietyDirectedActionControl>();
  let savedWorldActionClient: SocietyClient | null = null;
  const inhabitantsPanel = buildWorldInhabitants({
    onBringIn: () => void bringInInhabitants(),
    onAdvance: () => void stepPlayback(),
  });
  let previewState: OwnedSocietyState | null = null;
  let recording: LivingSocietyRecording | null = null;
  let recordingFrame = 0;
  let recordingSpeed = 1;
  let recordingPlaying = false;
  const recordingStatus = el('p', { class: 'living-world-fixture', 'aria-live': 'polite' });
  const crowdStatus = el('p', { role: 'status', class: 'living-society-counts' });
  const recordingPlay = el('button', { type: 'button', text: 'Pause' });
  const recordingNext = el('button', { type: 'button', text: 'Next minute' });
  const recordingRestart = el('button', { type: 'button', text: 'Restart recording' });
  const recordingSpeedSelect = el('select', { 'aria-label': 'Recorded society speed' });
  for (const [value, label] of RECORDING_SPEEDS) recordingSpeedSelect.append(el('option', { value: String(value), text: label }));
  let attachedControls: { onInteract: (() => void) | null } | null = null;

  overview.addEventListener('click', () => deps.state.atlas?.binding.setCityView('overview'));
  street.addEventListener('click', () => deps.state.atlas?.binding.setCityView('street'));
  const memoryCheckbox = memoryLayer.querySelector('input') as HTMLInputElement;
  const reflectMemoryLayer = (visible: boolean): void => {
    memoryCheckbox.checked = visible;
    source.textContent = visible
      ? 'City and memory layers are intentionally composed. Purple memory forms are not city semantics.'
      : 'Official BUILDING footprints. Memory and fantasy layers are separate from the geographic view.';
  };
  memoryCheckbox.addEventListener('change', () => {
    deps.state.atlas?.binding.setMemoryLayerVisible(memoryCheckbox.checked);
    reflectMemoryLayer(memoryCheckbox.checked);
  });

  function inspectSubject(subject: DistrictSubject, keepInhabitant = false): void {
    const runtime = deps.state.atlas?.binding.ownedDistrict;
    const doc = runtime?.interpretation;
    if (!doc) return;
    workspace.inspect();
    if (!keepInhabitant) selectedInhabitant = null;
    inspectedInhabitant = null;
    directedAction = null;
    chosen = null;
    deps.onSelect?.(null);
    setRepresentationHighlight(null);
    place.disabled = true; modify.disabled = true; remove.disabled = true;
    invalidateProposal('Select a source building before previewing an authored placement.');
    const destination = doc.navigation.destinations.find(d => d.subject_id === subject.subject_id);
    const names: Record<string, string> = { entrance: 'Exterior arrival marker', 'civic-object': 'Rest pad', sidewalk: 'Sidewalk', ground: 'Ground', facade: 'Facade pattern', roof: 'Roof and parapet', building: 'Building' };
    selected.textContent = names[subject.kind] ?? subject.kind;
    inspector.show({ subject: subject.subject_id, title: names[subject.kind] ?? subject.kind,
      description: subject.uncertainty,
      activity: destination ? `Inhabitants may ${destination.affordance} here for ${destination.duration_ticks} simulated minute${destination.duration_ticks === 1 ? '' : 's'}.` : 'No inhabitant action is declared for this subject.',
      details: [
        ['Plane / origin', subject.epistemic_status], ['Producer', doc.producer],
        ['Source references', subject.source_refs.map(r => `${r.dataset_id} · ${r.feature_id} · ${r.sha256}`).join('; ') || 'No direct source claim; district dependencies still apply.'],
        ['Permitted uses', subject.permitted_uses.join(', ')], ['Recipe', subject.recipe.kind],
        ['Branch / time', `${current?.versionId ?? 'Source interpretation'} · ${doc.document_sha256}`],
        ['Unavailable dependencies', doc.navigation.unavailable_reason ?? doc.unsupported.join('; ')],
      ],
    });
    // Existing destination buttons already open this inspector. When the place declares a
    // visit/rest affordance, mount the directed-action control that posts to record_action.
    if (destination && !deps.env.preview) {
      const actionClient = deps.societyClient ?? new SocietyClient(deps.credentials);
      directedAction = buildSocietyDirectedAction({
        client: actionClient,
        getSnapshot: () => society,
        getSubjectId: () => selectedInhabitant,
        targetId: destination.destination_id,
        affordance: destination.affordance,
      });
      inspector.addAction(directedAction.root);
    }
  }

  function clearInspector(): void {
    inspector.clear();
    inspectedInhabitant = null;
    directedAction = null;
  }

  /** The crowd this world draws: the owned district's, or a saved world's over its own region. */
  function crowd() {
    const binding = deps.state.atlas?.binding;
    return binding?.ownedDistrict ?? binding?.authoredSociety ?? null;
  }

  function inhabitantLabel(inhabitant: OwnedSocietyState['inhabitants'][number]): string {
    const place = deps.state.atlas?.binding.ownedDistrict?.district.name ?? 'this place';
    return inhabitant.display_name ?? (inhabitant.role ? `A ${inhabitant.role}` : `A person in ${place}`);
  }

  function reflectCrowd(): void {
    const runtime = crowd();
    const canvas = deps.env.canvas;
    const state = society?.state ?? previewState;
    if (!runtime || !canvas || !state) { crowdStatus.textContent = ''; return; }
    const counts = runtime.societyCounts;
    const walking = state.inhabitants.filter((person) => (person.motion_path_mm?.length ?? 0) > 1).length;
    canvas.dataset.societyNear = String(counts.near);
    canvas.dataset.societyFar = String(counts.far);
    canvas.dataset.societyIndoors = String(counts.indoors);
    const clock = state.minute_of_day === undefined ? '' : `${clockText(state.minute_of_day)} · `;
    crowdStatus.textContent = `${clock}${counts.population} inhabitants, ${counts.drawn} drawn `
      + `(${counts.near} as characters, ${counts.far} as distant figures), ${counts.indoors} indoors, `
      + `${walking} walked in the last minute.`;
  }

  function reflectNearby(): void {
    const state = society?.state ?? previewState;
    const visible = new Set(crowd()?.visibleInhabitantIds ?? []);
    inhabitantsList.hidden = !state || visible.size === 0;
    // In a saved world nobody lives in yet, the inhabitants section says so; this line would repeat it.
    workspace.setNearby(state ? visible.size : 0, savedWorld !== null && state === null);
    inhabitantsList.replaceChildren(el('option', {value: '', text: 'Inspect a nearby inhabitant'}));
    for (const inhabitant of state?.inhabitants ?? []) {
      if (visible.has(inhabitant.id)) inhabitantsList.append(el('option', {value: inhabitant.id, text: `${inhabitantLabel(inhabitant)} · ${inhabitant.id.slice(0, 8)}`}));
    }
    if (selectedInhabitant && visible.has(selectedInhabitant)) inhabitantsList.value = selectedInhabitant;
    reflectCrowd();
  }

  function inspectInhabitant(id: string, reveal = true): void {
    crowd()?.revealInhabitant(id);deps.state.atlas?.binding.invalidate();
    const state = society?.state ?? previewState;
    const inhabitant = state?.inhabitants.find(held => held.id === id);
    if (!inhabitant || !state) return;
    if (reveal) workspace.inspect();
    selectedInhabitant = id;
    inspectedInhabitant = id;
    directedAction = null;
    chosen = null;
    deps.onSelect?.(null);
    setRepresentationHighlight(null);
    place.disabled = true; modify.disabled = true; remove.disabled = true;
    invalidateProposal('Select an authored object before editing.');
    selected.textContent = 'Selected synthetic inhabitant';
    if (state.profile === 'exulanica-society/v4') { inspectLivingInhabitant(inhabitant, state); return; }
    const v2 = state.profile === 'exulanica-society/v2';
    const goal = inhabitant.goal && 'kind' in inhabitant.goal ? inhabitant.goal : null;
    const representation = crowd()?.inhabitantRepresentation(id);
    const liveInspection = liveSociety?.inspect(id);
    const eventText = liveInspection
      ? liveInspection.events.map(event => `Tick ${event.tick}: ${event.document.summary} [${event.event_id}]`).join(' ')
        + (liveInspection.missingEventIds.length ? ` Referenced events unavailable in the latest event window: ${liveInspection.missingEventIds.join(', ')}.` : '')
      : '';
    const inputBinding = state.input_sha256 === undefined
      ? 'Unavailable'
      : `${state.input_seq === undefined ? 'Sequence unavailable' : `Sequence ${state.input_seq}`} · ${state.input_sha256}`;
    const nativeCharacter = representation ? deps.state.atlas?.binding.nativeCharacters?.inspect(representation.subject) : null;
    // Resting is the simulation's state. A catalog person sits on the ground in front of the
    // place; the abstract figure stands.
    const resting = v2 && inhabitant.action?.kind === 'rest' && inhabitant.action.status === 'active';
    inspector.show({
      subject: id,
      title: inhabitant.display_name ?? `Synthetic ${inhabitant.role ?? 'inhabitant'}`,
      description: 'A fictional inhabitant of this world. This is not a remembered person.',
      activity: v2
        ? `${inhabitant.explanation?.summary ?? 'Explanation unavailable.'}${resting ? ' Drawn sitting on the ground in front of the place.' : ''}`
        : 'No persisted goal or action is available in this preview or legacy society.',
      details: [
        ['Plane / origin', 'Simulation · synthetic'],
        ['Visibility', crowd()?.visibleInhabitantIds.includes(id) ? 'In the nearby display' : 'Outside the nearby display; identity is retained'],
        ['Current activity', v2 && inhabitant.action ? `${inhabitant.action.kind} · ${inhabitant.action.status}: ${inhabitant.action.reason}` : 'Unavailable'],
        ['Goal / destination', v2 && goal ? `${goal.kind} · ${goal.target_id}: ${goal.reason}` : 'Unavailable'],
        ['Recorded event details', eventText || (liveSociety?.view.eventsAvailable ? 'No event references for this activity.' : 'Event documents unavailable in this view.')],
        ['Event references', v2 ? inhabitant.explanation?.event_ids.join(', ') || 'No recorded event references' : 'Unavailable'],
        ['Producer', state.profile ?? 'Static preview fixture'],
        ['Authored branch', state.branch_id ?? society?.versionId ?? 'Unavailable'],
        ['Simulation tick', String(state.tick)],
        ['Simulation clock', 'Unavailable'],
        ['Tick duration', 'Unavailable'],
        ['Routine catalogs', 'Unavailable'],
        ['Routine digest', 'Unavailable'],
        ['Input binding', inputBinding],
        ['Permitted use', 'Inspect simulation state; not historical evidence'],
        ['Shared position', `${crowd()?.coincidentInhabitants(inhabitant.id).length ?? 1} inhabitants at this position, all drawn where the simulation placed them.`],
        ...characterDisplayDetails(nativeCharacter, representation?.representationId, NEAR_CHARACTER_BUDGET),
        ['Unavailable dependencies', v2 ? 'Personal evidence and model explanation not established by this view.' : 'Routes, goals, event history and authenticated persistence unavailable.'],
      ],
    });
    if (savedWorld !== null && v2) addSavedWorldActions();
  }

  /** The person's objects, as the inhabitants panel names and places them. */
  function savedObjects(): readonly InhabitedObject[] | null {
    if (current === null) return null;
    return current.objects.filter((object) => !object.removed).map((object) => ({
      objectId: object.objectId, title: object.asset.title,
      xMm: object.transform.xMm, zMm: object.transform.zMm,
    }));
  }

  /** How a directed action is said in a person's own world: what happens, not its receipt. */
  function plainRecord(place: string, affordance: 'visit' | 'rest') {
    const verb = affordance === 'rest' ? 'rest at' : 'visit';
    return (record: SocietyActionRecord): string => {
      if (record.status === 'pending') {
        return `Asked to ${verb} ${place}. They set off at the next simulated minute. This is simulation, not a memory.`;
      }
      const disposition = record.consumption?.disposition ?? 'unknown';
      return disposition === 'applied'
        ? `Taken up at simulated minute ${record.consumption?.tick}: they are on their way to ${verb} ${place}.`
        : `Not taken up at simulated minute ${record.consumption?.tick} (${disposition.replaceAll('_', ' ')}).`;
    };
  }

  /**
   * On a selected inhabitant of a saved world: one action per place they can use. Each control is
   * kept per place, so a refresh that re-renders this person keeps what the last request said.
   */
  function addSavedWorldActions(): void {
    const world = savedWorld;
    const places = society?.places;
    if (world === null || !places) return;
    const client = deps.societyClient
      ?? (savedWorldActionClient ??= new SocietyClient({ ...deps.credentials, worldId: world.worldId }));
    const usable = new Set<string>();
    for (const row of placeRows(savedObjects() ?? [], places)) {
      if (row.status.kind !== 'usable') continue;
      const { targetId, affordance } = row.status;
      usable.add(targetId);
      let control = savedWorldActions.get(targetId);
      if (control === undefined) {
        control = buildSocietyDirectedAction({
          client, getSnapshot: () => society, getSubjectId: () => selectedInhabitant,
          targetId, affordance,
          label: affordance === 'rest' ? `Rest at ${row.label}` : `Visit ${row.label}`,
          describeRecord: plainRecord(row.label, affordance),
          idleText: 'Asks this simulated person to go there next. It is recorded as simulation, never as something that happened.',
        });
        control.root.classList.add('world-inhabitants-action');
        savedWorldActions.set(targetId, control);
      }
      control.reflect();
      inspector.addAction(control.root);
    }
    for (const targetId of [...savedWorldActions.keys()]) if (!usable.has(targetId)) savedWorldActions.delete(targetId);
  }

  function inspectLivingInhabitant(
    inhabitant: OwnedSocietyState['inhabitants'][number],
    state: OwnedSocietyState,
  ): void {
    const runtime = crowd();
    const representation = runtime?.inhabitantRepresentation(inhabitant.id);
    const nativeCharacter = representation ? deps.state.atlas?.binding.nativeCharacters?.inspect(representation.subject) : null;
    const goal = inhabitant.goal && 'activity' in inhabitant.goal ? inhabitant.goal : null;
    const action = inhabitant.action;
    const detail = runtime?.inhabitantDetail(inhabitant.id) ?? 'not-drawn';
    const shown = { near: 'A full character near you', far: 'A simple distant figure of the same person',
      indoors: 'Inside premises; interiors are not drawn', 'not-drawn': 'Too far away to draw; identity is retained' }[detail];
    const where = (destination: string | null | undefined) => destination
      ? `${destination.split('/').at(-1)}${recording?.destinations.get(destination) ? ` (holds ${recording.destinations.get(destination)!.capacity})` : ''}`
      : 'an open spot on the sidewalk';
    const live = liveSociety?.inspect(inhabitant.id);
    const recorded = live
      ? live.events.map((event) => ({ tick: event.tick, summary: event.document.summary, eventId: event.event_id }))
      : recording?.eventsBySubject.get(inhabitant.id) ?? [];
    const history = recorded
      .filter((event) => event.tick <= state.tick).slice(-6)
      .map((event) => `Tick ${event.tick}: ${event.summary} [${event.eventId}]`).join(' ');
    const needs = Object.entries(inhabitant.needs ?? {}).map(([key, value]) => `${key} ${value}`).join(', ');
    const routineVersions = state.routine === undefined
      ? 'Unavailable'
      : Object.entries(state.routine.catalog_versions)
        .map(([catalog, version]) => `${catalog} v${version}`).join(', ');
    const inputBinding = state.input_sha256 === undefined
      ? 'Unavailable'
      : `${state.input_seq === undefined ? 'Sequence unavailable' : `Sequence ${state.input_seq}`} · ${state.input_sha256}`;
    const eventCoverage = liveSociety !== null
      ? !liveSociety.view.eventsAvailable
        ? 'Persisted event documents are unavailable in this view.'
        : live?.missingEventIds.length
          ? `Latest bounded persisted event window; referenced events absent from it: ${live.missingEventIds.join(', ')}.`
          : 'Latest bounded persisted event window; all current references are present. Earlier history may be absent.'
      : recording !== null
        ? `Recorded preview window, ticks 0 through ${recording.frames.at(-1)!.tick}; not persisted and not complete history.`
        : 'No event document source is connected to this preview or legacy state.';
    const simulationClock = state.day === undefined || state.minute_of_day === undefined
      ? 'Unavailable'
      : `Day ${state.day} · ${clockText(state.minute_of_day)}`;
    inspector.show({
      subject: inhabitant.id,
      title: inhabitantLabel(inhabitant),
      description: 'A fictional inhabitant of this world, identified only by a synthetic identity. This is not a remembered person.',
      activity: goal
        ? `${activityLabel(goal.activity)} at ${where(goal.destination_id)}, because ${goal.because}.`
        : inhabitant.explanation?.summary ?? 'Awaiting its first choice.',
      details: [
        ['Plane / origin', 'Simulation · synthetic'],
        ['Shown as', shown],
        ['Role', inhabitant.role ? inhabitant.role : `Unavailable (${(inhabitant.role_reason ?? 'no premises').replaceAll('_', ' ')})`],
        ['Current activity', action ? `${activityLabel(action.kind)} · ${action.status}: ${action.reason.replaceAll('_', ' ')}` : 'Unavailable'],
        ['Destination', goal ? where(goal.destination_id) : 'None chosen'],
        ['Needs (of 1000)', needs || 'Unavailable'],
        ['Recorded events', history || 'No events are present in the available window.'],
        ['Event coverage', eventCoverage],
        ['Event references', inhabitant.explanation?.event_ids.join(', ') || 'No recorded event references'],
        ['Producer', `${state.profile} · ${deps.env.preview ? 'recorded by the real engine' : 'persisted'}`],
        ['Authored branch', state.branch_id ?? society?.versionId ?? 'Unavailable'],
        ['Simulation tick', String(state.tick)],
        ['Simulation clock', simulationClock],
        ['Tick duration', state.tick_seconds === undefined
          ? 'Unavailable' : `${state.tick_seconds} simulated seconds per tick`],
        ['Routine catalogs', routineVersions],
        ['Routine digest', state.routine?.sha256 ?? 'Unavailable'],
        ['Input binding', inputBinding],
        ['Inspection scope', 'These bindings identify the displayed state. This view does not verify replay or send them to Companion.'],
        ['Population', recording ? `${recording.population.size} of ${recording.population.capacity} places this district can hold. ${recording.population.reason}` : `${state.inhabitants.length} inhabitants`],
        ['Permitted use', 'Inspect simulation state; not historical evidence'],
        ['Shared position', `${runtime?.coincidentInhabitants(inhabitant.id).length ?? 1} inhabitants at this position`],
        ...characterDisplayDetails(nativeCharacter, representation?.representationId),
        ['Unavailable dependencies', recording
          ? [...recording.unsupported, ...Object.entries(recording.environment).map(([key, value]) => `${key}: ${value.reason}`)].join('; ')
          : 'Personal evidence and model explanation are not established by this view.'],
      ],
    });
  }

  function showRecordedFrame(index: number): void {
    const atlas = deps.state.atlas?.binding;
    if (!recording || phase === 'disposed' || !atlas?.ownedDistrict) return;
    const last = recording.frames.length - 1;
    recordingFrame = Math.max(0, Math.min(last, index));
    const state = recordingState(recording, recordingFrame);
    previewState = state;
    atlas.ownedDistrict.setSociety(state, [atlas.controls.state.x, atlas.controls.state.z], { intervalMs: 60_000 / recordingSpeed });
    const canvas = deps.env.canvas;
    canvas.dataset.societyPopulation = String(state.inhabitants.length);
    canvas.dataset.societyRendered = String(atlas.ownedDistrict.drawnInhabitantCount);
    canvas.dataset.societyTick = String(state.tick);
    canvas.dataset.societyMinute = String(state.minute_of_day ?? '');
    recordingNext.disabled = recordingFrame >= last;
    recordingStatus.textContent = recordingFrame >= last
      ? `The recording ends at ${clockText(recording.frames[last]!.minuteOfDay)}. Restart it to watch again.`
      : `Recorded minute ${recordingFrame} of ${last}, played ${recordingSpeed === 1 ? 'in real time' : `${recordingSpeed} times faster than real time`}.`;
    reflectNearby();
    if (selectedInhabitant) inspectInhabitant(selectedInhabitant, false);
    atlas.invalidate();
  }

  function scheduleRecording(delayMs = 60_000 / recordingSpeed): void {
    if (societyTimer !== null) window.clearTimeout(societyTimer);
    societyTimer = null;
    const ended = !recording || recordingFrame >= recording.frames.length - 1;
    if (ended) recordingPlaying = false;
    recordingPlay.textContent = recordingPlaying ? 'Pause' : 'Play';
    if (!recordingPlaying || phase === 'disposed') return;
    societyTimer = window.setTimeout(() => {
      societyTimer = null;
      showRecordedFrame(recordingFrame + 1);
      scheduleRecording();
    }, delayMs);
  }

  recordingPlay.addEventListener('click', () => {
    if (!recording) return;
    if (!recordingPlaying && recordingFrame >= recording.frames.length - 1) showRecordedFrame(0);
    recordingPlaying = !recordingPlaying;
    scheduleRecording(recordingPlaying ? 0 : undefined);
  });
  recordingNext.addEventListener('click', () => { recordingPlaying = false; scheduleRecording(); showRecordedFrame(recordingFrame + 1); });
  recordingRestart.addEventListener('click', () => { showRecordedFrame(0); recordingPlaying = true; scheduleRecording(0); });
  recordingSpeedSelect.addEventListener('change', () => {
    recordingSpeed = Number(recordingSpeedSelect.value);
    if (recordingPlaying) scheduleRecording();
  });

  async function attachRecordedSociety(): Promise<void> {
    const atlas = deps.state.atlas?.binding;
    const runtime = atlas?.ownedDistrict;
    if (!runtime) return;
    const panel = el('details', { open: true }, [
      el('summary', { text: 'Living society (recorded preview)' }),
      crowdStatus, recordingStatus, recordingPlay, recordingNext, recordingRestart, recordingSpeedSelect,
    ]);
    workspace.details.prepend(panel);
    fixture.textContent = 'Recorded preview';
    if (!runtime.interpretation) {
      recordingStatus.textContent = 'Living society unavailable: this district publishes no interpretation to walk on.';
      return;
    }
    recordingStatus.textContent = 'Recording the living society with the simulation engine.';
    try {
      const response = await fetch(SOCIETY_RECORDING_URL, { signal: districtAbort.signal });
      const body = await response.json() as unknown;
      if (!response.ok) {
        const detail = (body as { detail?: unknown } | null)?.detail;
        throw new Error(typeof detail === 'string' ? detail : `the recording route answered ${response.status}`);
      }
      const parsed = parseLivingSocietyRecording(body, runtime.interpretation.document_sha256);
      if ((phase as string) === 'disposed') return;
      recording = parsed;
      panel.append(el('p', { text: parsed.status }), el('p', { text: parsed.population.reason }));
      showRecordedFrame(0);
      recordingPlaying = true;
      scheduleRecording(250);
    } catch (error) {
      if ((phase as string) === 'disposed') return;
      recordingPlay.disabled = true; recordingNext.disabled = true; recordingRestart.disabled = true;
      recordingStatus.textContent = `Living society unavailable: ${error instanceof Error ? error.message : String(error)}`;
    }
  }

  function reportSelection(feature: NYCLocalFeature, reveal = true): void {
    if (reveal) workspace.inspect();
    selectedInhabitant = null;
    inspectedInhabitant = null;
    directedAction = null;
    if (representationAvailability(feature.providerFeatureId) === 'unavailable') {
      representation.refresh();
      return;
    }
    if (chosen?.id !== feature.id) {
      invalidateProposal('The selection changed. Request a fresh proposal.');
    }
    chosen = feature;
    setRepresentationHighlight(feature.providerFeatureId);
    if (catalog !== null) {
      deps.onSelect?.({ admissionId: catalog.admissionId, featureId: feature.id });
    }
    const doitt = feature.providerFeatureId.replace('doitt_id:', '');
    selected.textContent = 'Source-backed building · NYC Open Data';
    reason.textContent = 'Selected from the admitted building footprint.';
    const district = deps.state.atlas?.binding.ownedDistrict?.district;
    const building = district?.buildings.find(held => held.id === feature.providerFeatureId);
    inspector.show({ subject: feature.providerFeatureId, title: feature.name ?? 'Unnamed building',
      description: 'A building form derived from an admitted NYC footprint and height.',
      activity: 'Building use, interiors and occupants are not established by these source records.',
      details: [
        ['Plane / origin', 'Spatial representation · admitted source'],
        ['Building identifiers', `DOITT_ID ${doitt} · BIN ${feature.bin?.replace('bin:', '') ?? 'not supplied'}`],
        ['Source references', district?.source_records.map(held => `${held.dataset_id} · ${held.provider_revision} · ${held.sha256}`).join('; ') ?? catalog?.sourceSha256 ?? 'Unavailable'],
        ['Producer / version', district?.profile ?? 'NYC semantic overlay'],
        ['Height', building ? `${(building.height_cm / 100).toFixed(1)} m, source-derived mass` : 'Unavailable'],
        ['Uncertainty', 'Facade and roof appearance is provisional; not photographed detail.'],
        ['Permitted uses', district?.source_records.map(held => Object.entries(held.operation_rights).filter(([, allowed]) => allowed).map(([use]) => use).join(', ')).join('; ') ?? 'See admission'],
        ['Branch / time', current ? `${current.versionId} · authored edit ${current.editSeq}` : 'Source view; authored version unavailable'],
        ['Unavailable dependencies', 'No validated interior, personal memory association or inhabitant affordance in this source record.'],
      ],
    });
    const doc = deps.state.atlas?.binding.ownedDistrict?.interpretation;
    if (doc) {
      for (const part of doc.subjects.filter(s => (s.recipe.kind === 'facade-grid' || s.recipe.kind === 'roof-parapet') && s.recipe.feature_id === feature.providerFeatureId)) {
        const button = el('button', {type:'button', text: part.kind === 'roof' ? 'Inspect roof recipe' : 'Inspect facade recipe'});
        button.addEventListener('click', () => inspectSubject(part)); inspector.addAction(button);
      }
    }
    place.disabled = current === null;
    reflectRequestButton();
    remove.disabled = current?.environmentInstances?.some((held) =>
      held.instanceId === instanceId(feature) && !held.removed) !== true;
    modify.disabled = remove.disabled;
  }

  function setRepresentationHighlight(
    subjectId: string | null,
  ): 'selected' | 'unregistered' | 'unavailable' {
    const binding = deps.state.atlas?.binding;
    if (binding?.setRepresentationSelection === undefined) return 'unregistered';
    if (subjectId !== null) {
      const availability = representationAvailability(subjectId);
      if (availability !== 'available') return availability;
    }
    if (binding.representationReport.selection !== subjectId) {
      binding.setRepresentationSelection(subjectId);
    }
    representation.refresh();
    return 'selected';
  }

  function representationAvailability(
    subjectId: string,
  ): 'available' | 'unregistered' | 'unavailable' {
    const binding = deps.state.atlas?.binding;
    if (binding?.setRepresentationSelection === undefined) return 'unregistered';
    const registered = binding.representationReport.subjects.find(
      entry => entry.subject.subjectId === subjectId,
    );
    if (registered === undefined) return 'unregistered';
    return registered.subject.availability === 'available' ? 'available' : 'unavailable';
  }

  function reflectRepresentationSelection(
    subjectId: string | null,
    selectionReason: 'explicit' | 'unavailable' | 'unregistered',
  ): void {
    const feature = subjectId === null ? undefined : admittedFeaturesByProvider.get(subjectId);
    if (feature !== undefined) {
      if (chosen?.id !== feature.id) reportSelection(feature);
      else representation.refresh();
      return;
    }
    const authorityCleared = subjectId === null && selectionReason !== 'explicit';
    if (chosen !== null) invalidateProposal(subjectId === null
      ? authorityCleared
        ? 'The selected source building is no longer available.'
        : 'The source-building selection was cleared.'
      : 'The data-view selection is not an admitted source building.');
    chosen = null;
    deps.onSelect?.(null);
    place.disabled = true;
    modify.disabled = true;
    remove.disabled = true;
    clearInspector();
    selected.textContent = subjectId === null
      ? authorityCleared
        ? 'Selected source-backed building is unavailable.'
        : 'No source-backed building is selected.'
      : 'Another data-view subject is selected; no admitted building context.';
    reason.textContent = subjectId === null
      ? authorityCleared
        ? 'Its overlay and semantic context were cleared when its current authority changed.'
        : 'Select an available source building to inspect or reuse it.'
      : 'This subject keeps the context of the surface that owns it and does not become city context.';
    representation.refresh();
  }

  function reflectVersion(): void {
    const undone = new Set(current?.edits
      .map((edit) => edit.undoneEditId)
      .filter((id): id is string => id !== null) ?? []);
    editDetails.hidden = current === null;
    authoringAvailability.hidden = current !== null;
    if (current === null && authoredWorldFailure !== null) {
      authoringAvailability.textContent = `Editing this saved world is unavailable. ${authoredWorldFailure}`;
    }
    undo.disabled = current === null || !current.edits.some((edit) =>
      edit.kind !== 'undo' && !undone.has(edit.editId));
    if (chosen !== null) reportSelection(chosen, false);
    if (current?.environmentInstances?.some(instance => !instance.removed && instance.availability === 'available')) {
      reason.textContent = 'Authored placement is saved. Its pinned source and district-frame rendering adapter are unavailable.';
    }
    deps.state.atlas?.binding.ownedDistrict?.setAuthoredInstances(
      current?.environmentInstances ?? [],
    );
  }

  function reflectRequestButton(): void {
    ask.disabled = current === null || requestPending || chosen === null || request.value.trim().length === 0;
  }

  function clearProposal(message = 'No edit is waiting for review.'): void {
    proposal = null;
    previewText.textContent = message;
    previewControls.hidden = true;
    apply.disabled = true;
    discard.disabled = true;
  }

  function invalidateProposal(message: string): void {
    contextEpoch += 1;
    requestPending = false;
    clearProposal(message);
    reflectRequestButton();
  }

  function showProposal(value: EnvironmentProposal): void {
    proposal = value;
    previewControls.hidden = false;
    apply.disabled = false;
    discard.disabled = false;
    if (value.operation === 'place_selected_feature') {
      previewText.textContent = `Proposed operation: place_selected_feature · feature `
        + `${value.featureId} · publication ${value.publicationId} · `
        + `role ${OBJECT_ROLE_LABELS[value.originRole]}.`;
    } else if (value.operation === 'remove_selected_authored_instance') {
      previewText.textContent = 'Proposed operation: remove_selected_authored_instance · '
        + `instance ${value.instanceId}.`;
    } else {
      previewText.textContent = 'Restore the state before the latest authored edit. This does not erase simulation history.';
    }
    previewText.textContent += value.promptVersion === 'deterministic-environment-preview-1'
      ? ' Deterministic preview; no model ran.'
      : ` Model: ${value.modelId ?? 'not reported'} · prompt: ${value.promptVersion}.`;
  }

  function placementRequest(): EnvironmentPlacementRequest | null {
    if (chosen === null) return null;
    const west = chosen.bbox[0], south = chosen.bbox[1];
    const east = chosen.bbox[2], north = chosen.bbox[3];
    return {
      instanceId: instanceId(chosen),
      feature: chosen,
      sourceAnchor: [Math.round((west + east) / 2), Math.round((south + north) / 2)],
      regionId: String(deps.scene.islands[0]!.islandId),
      transform: {
        xMm: -270_000,
        yMm: 0,
        zMm: 260_000,
        yawMicroradians: 0,
        scaleMilli: 1000,
      },
      originRole: role.value as ObjectRole,
    };
  }

  async function applyResult(result: Awaited<ReturnType<EnvironmentSelectionClient['add']>>):
    Promise<boolean> {
    if (phase === 'disposed') return false;
    contextEpoch += 1;
    requestPending = false;
    current = result.kind === 'recorded' ? result.version : result.current;
    reflectVersion();
    if (result.kind === 'stale') {
      deps.showStatus('The world changed. Current state was reloaded; review and try again.', 'failure');
      clearProposal('The preview is stale. Request a fresh proposal.');
      return false;
    }
    await afterAuthoredEdit(current.versionId);
    return (phase as string) !== 'disposed';
  }

  request.addEventListener('input', () => {
    invalidateProposal('The request changed. Submit it again for a fresh proposal.');
  });
  role.addEventListener('change', () => invalidateProposal(
    'The role changed. Request a fresh proposal.',
  ));

  place.addEventListener('click', () => {
    const placement = placementRequest();
    if (catalog === null || current === null || placement === null) {
      deps.showStatus('Open an authored version and select a feature before previewing.', 'failure');
      return;
    }
    invalidateProposal('Preparing deterministic placement preview.');
    showProposal(environmentClient.deterministicPlace(current, catalog, placement));
  });

  remove.addEventListener('click', () => {
    if (current === null || chosen === null) return;
    invalidateProposal('Preparing deterministic removal preview.');
    showProposal({
      operation: 'remove_selected_authored_instance',
      versionId: current.versionId,
      baseStateSha256: current.stateSha256,
      instanceId: instanceId(chosen),
      modelId: null,
      promptVersion: 'deterministic-environment-preview-1',
    });
  });

  modify.addEventListener('click', () => void (async () => {
    if (current === null || chosen === null) return;
    const selectedInstanceId = instanceId(chosen);
    const instance = current.environmentInstances?.find(
      (held) => held.instanceId === selectedInstanceId && !held.removed,
    );
    if (instance === undefined) return;
    try {
      const ok = await applyResult(await environmentClient.move(
        current,
        instance.instanceId,
        {
          ...instance.transform,
          yMm: 6_000,
          yawMicroradians: 260_000,
          scaleMilli: 1120,
        },
      ));
      if (ok) deps.showStatus('Lifted and illuminated. Reload and undo preserve the source.');
    } catch (error) {
      deps.showStatus(objectWriteFailure(error), 'failure');
    }
  })());

  undo.addEventListener('click', () => {
    if (current === null) return;
    invalidateProposal('Preparing deterministic undo preview.');
    showProposal({
      operation: 'undo_latest_version_edit',
      versionId: current.versionId,
      baseStateSha256: current.stateSha256,
      modelId: null,
      promptVersion: 'deterministic-environment-preview-1',
    });
  });

  ask.addEventListener('click', () => void (async () => {
    if (requestPending) return;
    const placement = placementRequest();
    if (catalog === null || current === null || placement === null) return;
    const epoch = ++contextEpoch;
    requestPending = true;
    clearProposal('Requesting a typed environment proposal…');
    reflectRequestButton();
    try {
      const result = await environmentClient.propose(
        current, catalog, placement, request.value.trim(),
      );
      if (epoch !== contextEpoch || phase === 'disposed') return;
      requestPending = false;
      reflectRequestButton();
      if (result.kind === 'refused') {
        clearProposal(`No proposal: ${result.detail}`);
        deps.showStatus(`No environment proposal: ${result.detail}`, 'failure');
      } else {
        showProposal(result.proposal);
      }
    } catch (error) {
      if (epoch !== contextEpoch || phase === 'disposed') return;
      requestPending = false;
      reflectRequestButton();
      deps.showStatus(objectWriteFailure(error), 'failure');
    }
  })());

  discard.addEventListener('click', () =>
    invalidateProposal('Proposal discarded. Nothing changed.'));

  apply.addEventListener('click', () => void (async () => {
    if (proposal === null) return;
    apply.disabled = true;
    try {
      const operation = proposal.operation;
      const ok = await applyResult(await environmentClient.apply(proposal));
      if (ok) {
        clearProposal('Applied. No edit is waiting for review.');
        deps.showStatus(
          operation === 'undo_latest_version_edit'
            ? 'Latest authored edit restored. Simulation history is retained.'
            : operation === 'remove_selected_authored_instance'
              ? 'Environment placement removed. Undo latest edit remains available.'
              : 'NYC Open Data feature placed in the authored version.',
        );
      }
    } catch (error) {
      deps.showStatus(objectWriteFailure(error), 'failure');
      apply.disabled = false;
    } finally {
      if (phase !== 'disposed') reflectVersion();
    }
  })());

  function stopControlPoll(): void {
    if (controlTimer !== null) window.clearTimeout(controlTimer);
    controlTimer = null;
  }

  function reflectPlayback(): void {
    const control = societyControl;
    if (control === null) {
      playbackStatus.textContent = 'Playback controls are not connected.';
      playbackMode.disabled = true; playbackSpeed.disabled = true; advanceSociety.disabled = true;
      renderInhabitantsPanel();
      return;
    }
    playbackSpeed.value = String(control.speed);
    playbackMode.textContent = control.mode === 'playing' ? 'Pause society' : 'Play society';
    const eligibility = control.playEligible ? '' : ` ${control.playIneligibleReason ?? 'Playback is unavailable.'}`;
    playbackStatus.textContent = control.mode === 'playing'
      ? `Saved as playing at ${control.speed}×. When the playback worker is online, it waits at least ${control.tickIntervalMs} ms after each completed batch. Persisted tick ${control.currentTick}.${control.reason ? ` ${control.reason}` : ''}`
      : `Paused at persisted tick ${control.currentTick}. Speed is set to ${control.speed}×.${eligibility}`;
    playbackMode.disabled = controlBusy || !scopeReady()
      || (!control.playEligible && control.mode === 'paused');
    playbackSpeed.disabled = controlBusy;
    advanceSociety.disabled = controlBusy || !scopeReady()
      || control.mode !== 'paused' || !control.playEligible
      || !liveSociety?.view.snapshot || !liveSociety.view.eventsAvailable;
    refreshSociety.disabled = controlBusy || liveSociety?.view.busy === true;
    renderInhabitantsPanel();
  }

  /** Whether the world the society lives in is connected: a saved world, or a placed district. */
  function scopeReady(): boolean {
    return savedWorld !== null || districtView !== null;
  }

  /** Why the inhabitants panel cannot advance a minute right now, or null when it can. */
  function advanceBlocked(): string | null {
    const control = societyControl;
    if (controlBusy) return 'Advancing…';
    if (control === null) return 'Playback controls are not connected.';
    if (control.mode === 'playing') return 'Pause the simulation to advance one minute by hand.';
    if (!liveSociety?.view.eventsAvailable) return 'Reconnect to this world\'s inhabitants first.';
    return null;
  }

  function renderInhabitantsPanel(): void {
    if (savedWorld === null || liveSociety === null) return;
    const view = liveSociety.view;
    const walked = view.snapshot?.state.inhabitants
      .filter((person) => (person.motion_path_mm?.length ?? 0) > 1).length ?? 0;
    inhabitantsPanel.render({
      society: view, objects: savedObjects(), walked, advanceBlocked: advanceBlocked(),
    });
  }

  function scheduleControlPoll(): void {
    stopControlPoll();
    if (phase === 'disposed' || societyControl?.mode !== 'playing') return;
    controlTimer = window.setTimeout(() => void refreshPlayback(true),
      Math.max(500, societyControl.tickIntervalMs));
  }

  async function refreshPlayback(refreshSocietyState = false): Promise<void> {
    if (phase === 'disposed' || deps.env.preview || current === null || controlBusy) return;
    stopControlPoll(); controlBusy = true; reflectPlayback();
    try {
      if (refreshSocietyState) await liveSociety?.refresh();
      societyControl = await controlClient.read(current.versionId);
    } catch (error) {
      societyControl = null;
      playbackStatus.textContent = `Playback controls unavailable. ${error instanceof Error ? error.message : 'The request failed.'}`;
    } finally {
      controlBusy = false; reflectPlayback(); scheduleControlPoll();
    }
  }

  async function configurePlayback(
    mode: SocietyPlaybackMode, selectedSpeed?: SocietyPlaybackSpeed,
  ): Promise<void> {
    const control = societyControl;
    if (phase === 'disposed' || control === null || controlBusy) return;
    stopControlPoll(); controlBusy = true; reflectPlayback();
    try {
      societyControl = await controlClient.configure(
        control, mode, selectedSpeed ?? control.speed,
      );
      if (mode === 'paused') await liveSociety?.refresh();
    } catch (error) {
      playbackStatus.textContent = `Playback change was not saved. ${error instanceof Error ? error.message : 'The request failed.'}`;
      try { societyControl = current ? await controlClient.read(current.versionId) : null; } catch { societyControl = null; }
    } finally {
      controlBusy = false; reflectPlayback(); scheduleControlPoll();
    }
  }

  async function stepPlayback(): Promise<void> {
    const control = societyControl;
    const snapshot = liveSociety?.view.snapshot;
    if (phase === 'disposed' || control === null || snapshot === null || snapshot === undefined
      || controlBusy || control.mode !== 'paused') return;
    stopControlPoll(); controlBusy = true; reflectPlayback();
    try {
      if (savedWorld === null && !await refreshDistrict()) {
        throw new Error('Authorized district placement is unavailable.');
      }
      const result = await controlClient.step(control, snapshot);
      societyControl = result.control;
      await liveSociety?.refresh();
    } catch (error) {
      playbackStatus.textContent = `The society did not advance. ${error instanceof Error ? error.message : 'The request failed.'}`;
      try { societyControl = current ? await controlClient.read(current.versionId) : null; } catch { societyControl = null; }
    } finally {
      controlBusy = false; reflectPlayback(); scheduleControlPoll();
    }
  }

  function clearDistrict(notifyObjects = false): void {
    const hadFrame = districtView !== null;
    districtView = null;
    if (hadFrame) deps.state.atlas?.binding.setDistrictObjectFrame(null);
    if ((hadFrame || notifyObjects) && phase !== 'disposed') deps.onDistrictPlacementChange?.();
  }

  async function refreshDistrict(): Promise<boolean> {
    const atlas = deps.state.atlas?.binding;
    if (phase === 'disposed' || deps.env.preview || !current || !catalog || !atlas?.ownedDistrict) return false;
    const epoch = ++districtEpoch;
    advanceSociety.disabled = true;
    refreshSociety.disabled = true;
    try {
      const requested = current;
      const admittedBefore = (await worldClient.connect(requested.versionId)).version;
      if ((phase as string) === 'disposed' || epoch !== districtEpoch
        || current?.versionId !== requested.versionId
        || current.stateSha256 !== requested.stateSha256
        || current.editSeq !== requested.editSeq) return false;
      if (admittedBefore === null) throw new Error('The saved authored version is unavailable.');
      current = admittedBefore;
      authoredWorldFailure = null;
      const version = admittedBefore;
      const result = await districtClient.read({
        worldId: version.worldId, versionId: version.versionId, sourceSnapshotId: version.sourceSnapshotId,
        placeId: catalog.placeId, renderedBase: atlas.ownedDistrict.district,
      });
      if ((phase as string) === 'disposed' || epoch !== districtEpoch
        || current?.versionId !== version.versionId
        || current.stateSha256 !== version.stateSha256
        || current.editSeq !== version.editSeq) return false;
      const admittedAfter = (await worldClient.connect(version.versionId)).version;
      if ((phase as string) === 'disposed' || epoch !== districtEpoch
        || current?.versionId !== version.versionId
        || current.stateSha256 !== version.stateSha256
        || current.editSeq !== version.editSeq) return false;
      if (admittedAfter === null) throw new Error('The saved authored version is unavailable.');
      const cursorUnchanged = admittedAfter.versionId === version.versionId
        && admittedAfter.stateSha256 === version.stateSha256
        && admittedAfter.editSeq === version.editSeq;
      current = admittedAfter;
      authoredWorldFailure = null;
      if (!cursorUnchanged) return false;
      const changed = !districtView || JSON.stringify(result.placement) !== JSON.stringify(districtView.placement)
        || result.baseArtifactSha256 !== districtView.baseArtifactSha256 || result.interpretationArtifactSha256 !== districtView.interpretationArtifactSha256;
      districtView = result;
      districtFailure = '';
      if (changed) {
        atlas.setDistrictObjectFrame({ regionId: result.placement.regionId, translationMm: result.placement.translationMm });
        deps.onDistrictPlacementChange?.();
      }
      return true;
    } catch (error) {
      if ((phase as string) === 'disposed' || epoch !== districtEpoch) return false;
      let authorityError: unknown = error;
      let needsReconciliation = error instanceof WorldObjectsContractError
        && error.code === 'saved_entry_reconciliation_required';
      if (!needsReconciliation && current !== null) {
        const held = current;
        try {
          await worldClient.connect(held.versionId);
        } catch (validationError) {
          if (validationError instanceof WorldObjectsContractError
            && validationError.code === 'saved_entry_reconciliation_required') {
            authorityError = validationError;
            needsReconciliation = true;
          }
        }
        if ((phase as string) === 'disposed' || epoch !== districtEpoch
          || current?.versionId !== held.versionId
          || current.stateSha256 !== held.stateSha256
          || current.editSeq !== held.editSeq) return false;
      }
      if (needsReconciliation) {
        current = null;
        authoredWorldFailure = objectWriteFailure(authorityError);
        reflectVersion();
      }
      clearDistrict(needsReconciliation);
      districtFailure = `Authorized district placement unavailable. ${authorityError instanceof Error ? authorityError.message : 'The request failed.'}`;
      atlas.ownedDistrict.clearSociety();
      renderedSnapshot = null;
      return false;
    } finally {
      if ((phase as string) !== 'disposed' && epoch === districtEpoch) {
        if (liveSociety) reflectLiveSociety(liveSociety.view, false);
        else { liveStatus.textContent = districtFailure; refreshSociety.disabled = false; }
        reflectPlayback();
      }
    }
  }

  async function afterAuthoredEdit(versionId: string): Promise<void> {
    if (savedWorld !== null) {
      if (phase === 'disposed' || versionId !== savedWorld.versionId || !liveSociety) return;
      await readSavedVersion();
      await liveSociety.afterAuthoredEdit();
      renderInhabitantsPanel();
      return;
    }
    if (phase === 'disposed' || deps.env.preview || current?.versionId !== versionId || !liveSociety) return;
    await refreshDistrict();
    await liveSociety?.afterAuthoredEdit();
  }

  function reflectLiveSociety(view: LiveSocietyView, fromClient = true): void {
    if (phase === 'disposed') return;
    const atlas = deps.state.atlas?.binding;
    if (!atlas?.ownedDistrict) return;
    if (fromClient && view.snapshot === null && ['unauthorized', 'unavailable'].includes(view.status)) { districtFailure = view.message; clearDistrict(); }
    society = districtView ? view.snapshot : null;
    liveStatus.textContent = `${society ? `Persisted tick ${society.currentTick}. ` : ''}${districtView ? view.message : districtFailure}`;
    liveControls.dataset['state'] = view.status;
    advanceSociety.disabled = view.busy || !society || !view.eventsAvailable || !['ready', 'stale'].includes(view.status);
    refreshSociety.disabled = view.busy;
    const canvas = deps.env.canvas;
    if (society === null) {
      atlas.ownedDistrict.clearSociety();
      renderedSnapshot = null;
      if (selectedInhabitant) { selectedInhabitant = null; clearInspector(); selected.textContent = 'Selected inhabitant is unavailable.'; }
      delete canvas.dataset.societyPopulation;
      delete canvas.dataset.societyRendered;
      delete canvas.dataset.societyTick;
    } else {
      // Event/status updates must not restart a renderer's interpolation for the same state.
      if (renderedSnapshot?.stateSha256 !== society.stateSha256 || renderedSnapshot?.societyId !== society.societyId) {
        atlas.ownedDistrict.setSociety(society.state, [atlas.controls.state.x, atlas.controls.state.z]);
        renderedSnapshot = society;
      }
      canvas.dataset.societyPopulation = String(society.populationSize);
      canvas.dataset.societyRendered = String(atlas.ownedDistrict.drawnInhabitantCount);
      canvas.dataset.societyTick = String(society.currentTick);
      if (selectedInhabitant !== null && inspectedInhabitant === selectedInhabitant) {
        inspectInhabitant(selectedInhabitant, false);
      }
    }
    directedAction?.reflect();
    reflectNearby();
    reflectPlayback();
    atlas.invalidate();
  }

  /** A saved world's society, drawn over its authored region; no district gates it. */
  function reflectSavedWorldSociety(view: LiveSocietyView): void {
    if (phase === 'disposed') return;
    const atlas = deps.state.atlas?.binding;
    const runtime = atlas?.authoredSociety ?? null;
    society = view.snapshot;
    liveStatus.textContent = `${society ? `Persisted tick ${society.currentTick}. ` : ''}${view.message}`;
    liveControls.dataset['state'] = view.status;
    refreshSociety.disabled = view.busy;
    const canvas = deps.env.canvas;
    if (society === null || runtime === null) {
      runtime?.clearSociety();
      renderedSnapshot = null;
      if (selectedInhabitant) { selectedInhabitant = null; clearInspector(); selected.textContent = 'Selected inhabitant is unavailable.'; }
      delete canvas.dataset.societyPopulation;
      delete canvas.dataset.societyRendered;
      delete canvas.dataset.societyTick;
    } else {
      // Event and status updates must not restart the interpolation of the same state.
      if (renderedSnapshot?.stateSha256 !== society.stateSha256 || renderedSnapshot?.societyId !== society.societyId) {
        runtime.setSociety(society.state, [atlas!.controls.state.x, atlas!.controls.state.z]);
        renderedSnapshot = society;
      }
      canvas.dataset.societyPopulation = String(society.populationSize);
      canvas.dataset.societyRendered = String(runtime.drawnInhabitantCount);
      canvas.dataset.societyTick = String(society.currentTick);
      if (selectedInhabitant !== null && inspectedInhabitant === selectedInhabitant) {
        inspectInhabitant(selectedInhabitant, false);
      }
    }
    for (const control of savedWorldActions.values()) control.reflect();
    reflectNearby();
    reflectPlayback();
    atlas?.invalidate();
  }

  async function readSavedVersion(): Promise<void> {
    const world = savedWorld;
    if (world === null) return;
    try {
      current = (await worldClient.connect(world.versionId)).version;
      authoredWorldFailure = null;
    } catch (error) {
      current = null;
      authoredWorldFailure = objectWriteFailure(error);
    }
  }

  /** The person's own request. Nothing else creates a saved world's society. */
  async function bringInInhabitants(): Promise<void> {
    if (savedWorld === null || liveSociety === null || phase === 'disposed') return;
    await liveSociety.bringIn();
    if ((phase as string) === 'disposed') return;
    await refreshPlayback();
  }

  async function attachSavedWorld(entry: NonNullable<SessionState['activeWorldEntry']>): Promise<void> {
    const scene = entry.authoredScene!;
    savedWorld = { worldId: entry.worldId, versionId: entry.authoredVersionId, regionId: scene.region.regionId };
    root.dataset['state'] = 'ready';
    workspace.setAvailability(true);
    const heading = workspace.nearby.firstElementChild;
    if (heading) heading.after(inhabitantsPanel.root); else workspace.nearby.prepend(inhabitantsPanel.root);
    const atlas = deps.state.atlas?.binding;
    if (atlas?.authoredSociety == null) {
      inhabitantsPanel.unavailable('This world is not drawn here, so nobody can be shown in it.');
      return;
    }
    await readSavedVersion();
    if ((phase as string) === 'disposed') return;
    attachedControls = atlas.controls;
    priorInteract = atlas.controls.onInteract;
    installedInteract = () => {
      const ray = atlas.interactionRay?.();
      const position = ray ? { x: ray.origin[0], y: ray.origin[1], z: ray.origin[2] } : atlas.controls.state;
      const forward = ray ? { x: ray.direction[0], y: ray.direction[1], z: ray.direction[2] } : atlas.controls.forward?.() ?? atlas.camera.forward;
      const inhabitantId = atlas.authoredSociety?.pickInhabitant(
        [position.x, position.y, position.z], [forward.x, forward.y, forward.z]);
      if (inhabitantId) { inspectInhabitant(inhabitantId); return; }
      priorInteract?.();
    };
    atlas.controls.onInteract = installedInteract;
    phase = 'attached';
    liveSociety = createLiveSociety({
      preview: false, credentials: deps.credentials, worldId: entry.worldId,
      versionId: entry.authoredVersionId, placeId: null, regionId: scene.region.regionId,
      // Directed actions are a v2 foundation, and the living society has no place contract for
      // an authored ground. Opening the world never creates anything; the person asks.
      profile: 'exulanica-society/v2', createOnConnect: false, places: true,
      ...(deps.societyClient ? { client: deps.societyClient } : {}),
      onChange: reflectSavedWorldSociety,
    });
    await liveSociety.connect();
    if ((phase as string) === 'disposed') return;
    await refreshPlayback();
    if ((phase as string) === 'disposed') return;
    renderInhabitantsPanel();
    reflectNearby();
    atlas.invalidate();
  }

  async function attach(): Promise<void> {
    const entry = deps.state.activeWorldEntry;
    if (!deps.env.preview && entry?.authoredScene != null) {
      try {
        await attachSavedWorld(entry);
      } catch (error) {
        if (phase !== 'disposed') phase = 'idle';
        inhabitantsPanel.unavailable(`Inhabitants are unavailable. ${error instanceof Error ? error.message : String(error)}`);
      }
      return;
    }
    if (admissionId === null) {
      root.dataset['state'] = 'unavailable';
      workspace.setAvailability(false);
      reason.textContent = 'No admitted NYC Open Data catalog is configured.';
      return;
    }
    const atlas = deps.state.atlas?.binding;
    workspace.setPlace(atlas?.ownedDistrict?.district.name ?? 'NYC source view');
    if (atlas === undefined || deps.scene.islands.length === 0) return;
    try {
      catalog = await environmentClient.catalog(admissionId);
      try {
        current = (await worldClient.connect()).version;
        authoredWorldFailure = null;
      } catch (error) {
        // Semantic city reading remains available in the read-only development preview and
        // whenever authored-world state is temporarily unavailable.
        current = null;
        authoredWorldFailure = objectWriteFailure(error);
      }
      if (phase === 'disposed') return;
      const features = localizeNYCFeatures(
        catalog.features,
        catalog.coordinateScale,
        NYC_REFERENCE_FRAME,
      );
      admittedFeaturesByProvider = new Map(features.map(feature => [feature.providerFeatureId, feature]));
      releaseRepresentationSelection?.();
      releaseRepresentationSelection = atlas.observeRepresentationSelection?.(
        reflectRepresentationSelection,
      ) ?? null;
      const initialRepresentationSelection = atlas.representationReport?.selection ?? null;
      if (releaseRepresentationSelection !== null && initialRepresentationSelection !== null) {
        reflectRepresentationSelection(initialRepresentationSelection, 'explicit');
      }
      overlay = deps.createOverlay?.(features)
        ?? (atlas.ownedDistrict != null || atlas.generatedTile != null
          ? { pick: () => null, destroy: () => undefined }
          : new NYCSemanticOverlay(atlas.device, atlas.environmentRoot, features));
      reflectMemoryLayer(atlas.memoryLayerVisible);
      // Travel to a region switches the layer on by itself, so the control has to follow the world
      // rather than only lead it.
      atlas.onMemoryLayerChange = reflectMemoryLayer;
      const interpretation = atlas.ownedDistrict?.interpretation;
      if (interpretation) {
        const destinations = el('details', {}, [el('summary', { text: 'Places inhabitants can use' })]);
        for (const destination of interpretation.navigation.destinations) {
          const subject = interpretation.subjects.find(s => s.subject_id === destination.subject_id);
          if (!subject) continue;
          const button = el('button', {type: 'button', text: destination.affordance === 'rest' ? `Rest pad · ${destination.node_id}` : 'Exterior visit marker'});
          // Keep a selected inhabitant so the same destination control can issue perform.
          button.addEventListener('click', () => inspectSubject(subject, true)); destinations.append(button);
        }
        workspace.nearby.append(destinations);
      }
      attachedControls = atlas.controls;
      priorInteract = atlas.controls.onInteract;
      installedInteract = () => {
        /*
         * Standing inside a memory outranks whatever the ray finds.
         *
         * This picker casts from the eye and a district is wall to wall facades, so over any
         * memory in a street canyon the building behind the landmark took the key every time and
         * the memory could only be opened by aiming at empty sky. Inside a memory's own footprint
         * is a few metres wide and is the one place that trade is obviously wrong: the visitor is
         * standing in the thing they would be selecting. Everywhere else the ray still decides.
         */
        // Loose null check on purpose: a binding without this reading is not inside anything.
        if (atlas.occupiedRegion != null) { priorInteract?.(); return; }
        const ray = atlas.interactionRay?.();
        const position = ray ? { x: ray.origin[0], y: ray.origin[1], z: ray.origin[2] } : atlas.controls.state;
        const forward = ray ? { x: ray.direction[0], y: ray.direction[1], z: ray.direction[2] } : atlas.controls.forward?.() ?? atlas.camera.forward;
        const inhabitantId = atlas.ownedDistrict?.pickInhabitant?.(
          [position.x, position.y, position.z], [forward.x, forward.y, forward.z]);
        if (inhabitantId) { inspectInhabitant(inhabitantId); return; }
        const subject = atlas.ownedDistrict?.pickSubject?.(
          [position.x, position.y, position.z], [forward.x, forward.y, forward.z]);
        if (subject && subject.kind !== 'building') { inspectSubject(subject); return; }
        const owned = atlas.ownedDistrict?.pickBuilding(
          [position.x, position.y, position.z],
          [forward.x, forward.y, forward.z],
        );
        const hit = owned == null
          ? overlay!.pick(
            [position.x, position.y, position.z],
            [forward.x, forward.y, forward.z],
          )
          : features.find((feature) => feature.providerFeatureId === owned.id) ?? null;
        if (hit === null) priorInteract?.();
        else reportSelection(hit);
      };
      atlas.controls.onInteract = installedInteract;
      phase = 'attached';
      root.dataset['state'] = 'ready';
      workspace.setAvailability(true);
      reason.textContent = `${catalog.attribution}. ${features.length} authorized features loaded.`;
      reflectVersion();
      if (atlas.ownedDistrict != null && current !== null && !deps.env.preview) {
        await refreshDistrict();
        if ((phase as string) === 'disposed') return;
        liveSociety = createLiveSociety({
          preview: false, credentials: deps.credentials, versionId: current.versionId,
          placeId: catalog.placeId, regionId: String(deps.scene.islands[0]!.islandId),
          ...(deps.societyClient ? { client: deps.societyClient } : {}),
          onChange: reflectLiveSociety,
        });
        await liveSociety.connect();
        if ((phase as string) === 'disposed') return;
        await refreshPlayback();
        if ((phase as string) === 'disposed') return;
      } else if (atlas.ownedDistrict != null && deps.env.preview) {
        await attachRecordedSociety();
        if ((phase as string) === 'disposed') return;
      }
      reflectNearby();
      atlas.invalidate();
    } catch (error) {
      root.dataset['state'] = 'unavailable';
      workspace.setAvailability(false);
      reason.textContent = error instanceof Error ? error.message : String(error);
      if (phase !== 'disposed') phase = 'idle';
    }
  }

  return {
    root,
    begin: () => {
      if (phase === 'disposed') {
        return Promise.reject(new Error('NYC environment selection mount is disposed'));
      }
      if (beginPromise !== null) return beginPromise;
      phase = 'attaching';
      beginPromise = attach();
      return beginPromise;
    },
    closePanels: () => workspace.close(false),
    openPanel: (name) => workspace.openPanel(name),
    setWelcomeVisible: (visible) => workspace.setWelcomeVisible(visible),
    afterAuthoredEdit,
    districtPlacement: () => districtView?.placement ?? null,
    dispose: () => {
      workspace.dispose();
      representation.dispose();
      releaseRepresentationSelection?.();
      releaseRepresentationSelection = null;
      if (phase === 'disposed') return;
      contextEpoch += 1;
      requestPending = false;
      phase = 'disposed';
      districtEpoch += 1;
      districtAbort.abort();
      controlAbort.abort();
      stopControlPoll();
      if (!deps.env.preview) clearDistrict();
      liveSociety?.dispose();
      if (liveSociety || recording) crowd()?.clearSociety();
      savedWorldActions.clear();
      recording = null;
      recordingPlaying = false;
      liveSociety = null;
      society = null;
      renderedSnapshot = null;
      if (attachedControls !== null && attachedControls.onInteract === installedInteract) {
        attachedControls.onInteract = priorInteract;
      }
      installedInteract = null;
      priorInteract = null;
      attachedControls = null;
      if (societyTimer !== null) window.clearTimeout(societyTimer);
      societyTimer = null;
      const canvas = deps.env.canvas;
      canvas?.removeEventListener('camera-mode-change', reflectCamera);
      canvas?.removeEventListener('society-nearby-change', reflectNearby);
      if (canvas !== undefined) {
        for (const key of ['societyPopulation', 'societyRendered', 'societyTick', 'societyMinute', 'societyNear', 'societyFar', 'societyIndoors']) {
          delete canvas.dataset[key];
        }
      }
      overlay?.destroy();
      overlay = null;
      admittedFeaturesByProvider.clear();
      deps.onSelect?.(null);
      root.remove();
    },
  };
}
