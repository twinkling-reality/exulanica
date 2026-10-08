import {
  type AtlasScene,
  type DistrictSubject,
  type IslandId,
} from '@exulanica/atlas-core';
import { ApiError } from '@exulanica/graph-client';
import { problemSentence, type ProblemWords } from '../ui/words/problems.js';
import {
  hostGeneratedSociety,
  hostRegionSociety,
  localizeNYCFeatures,
  openingIsland,
  NEAR_CHARACTER_BUDGET,
  NYCSemanticOverlay,
  NYC_REFERENCE_FRAME,
  worldLayers,
  worldViews,
  type OwnedSocietyState,
  type NYCLocalFeature,
  type WorldKind,
  type WorldViews,
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
  type SocietyEvent,
  type SocietySnapshot,
} from '../society-api.js';
import {
  SocietyControlClient,
  type SocietyPlaybackControl,
  type SocietyPlaybackMode,
  type SocietyPlaybackSpeed,
} from '../society-control-api.js';
import { createLiveSociety, type LiveSociety, type LiveSocietyView } from './live-society.js';
import {
  mountSocietyModels, type ChoiceOutcome, type DecidesTarget, type MountedSocietyModels, type PersonMind,
} from './society-models-mount.js';
import type { ModelRef, NamedModelRef, SocietyModel, SocietyModelsClient } from '../society-models-api.js';
import { unreadMinutes } from './society-unread-minutes.js';
import { SocietyDistrictClient, type SocietyDistrictPlacement, type SocietyDistrictView } from '../society-district-api.js';
import {
  EnvironmentSelectionClient,
  type EnvironmentCatalog,
  type EnvironmentPlacementRequest,
  type EnvironmentProposal,
} from '../environment-selection-api.js';
import { say } from '../ui/copy.js';
import { el, setText } from '../ui/dom.js';
import { characterDisplayDetails } from '../ui/character-details.js';
import { buildRepresentationInspector } from '../ui/representation-inspector.js';
import {
  buildSocietyDirectedAction,
  type SocietyDirectedActionControl,
} from '../ui/society-directed-action.js';
import {
  buildWorldInhabitants,
  inhabitantWords,
  placeRows,
  type InhabitedObject,
  type PeopleOperation,
  type MovedWithoutWalking,
  type Noticing,
} from '../ui/world-inhabitants.js';
import { buildWorldWorkspace } from '../ui/world-workspace.js';
import { aboutWorld, aboutWorldLayers } from '../world-about.js';
import '../ui/living-world-inspector.css';
import type { CompanionSocietyContext, SimulationCitation, SocietyQuestion } from '../companion-ask-api.js';
import { drawSimulated, type SimulatedReferences, type SocietyNames } from '../companion-simulated.js';
import { hasInhabitantWords, livingInhabitantWords, livingNeedLabel, outcomeWords, phrase } from '../society-inhabitant-words.js';
import { ACTION_LABELS, ACTIVITY_LABELS, filled, objectActivity } from '../society-activity-words.js';
import { createLivingWorldInspector, type InspectionNote } from '../ui/living-world-inspector.js';
import {
  OBJECT_ROLE_LABELS,
  WorldObjectsClient,
  WorldObjectsContractError,
  objectWriteFailure,
  type AlternateVersion,
  type ObjectRole,
  type PlacedThing,
} from '../world-objects-api.js';
import type { AppEnvironment, SessionState } from './session-state.js';
import { seatingLayout } from './seating-layout.js';
import { pointerRay, type SeatingLayout } from '@exulanica/atlas-react/playcanvas';
import type { SocietyPlaces } from '../society-api.js';
import { engineCreatedOver, societyEngine } from '../society-engines.js';
import type { SavedWorldFlight, SavedWorldFlightStatus } from './saved-world-flight.js';
import { looksReadDue, mountThings, THING_PICK_EVENT, type MountedThings, type ThingPickDetail, type ThingPickVia, type ThingsDependencies } from './things.js';
import { AttachedMarks, type MarkedSubject } from '@exulanica/atlas-react/things';
import { markLabel, markOf, type MarkInput } from './thing-marks.js';
import { LineWatch, thingLine } from './thing-lines.js';
import { DoorBridgesClient, type DoorBridge } from '../door-bridges-api.js';
import { ThingLooksClient, type ThingLookChoice } from '../thing-looks-api.js';
import { visitorNotice, VisitorNoticeWatch, type FreshEvent, type KindReference } from './visitor-notices.js';
import '../ui/thing-marks.css';

/** Where the development preview's real-engine society recording is served. */
const SOCIETY_RECORDING_URL = '/preview-api/society/recording';
const RECORDING_SPEEDS = [
  [1, 'Real time'],
  [10, '10 times faster'],
  [60, '60 times faster'],
] as const;
/** What became of a directed request, in the words the society's own outcome states. */
const dispositionWords = (disposition: string): string =>
  outcomeWords(`action_request_${disposition}`) ?? 'did not take up your request, for a reason the page has no words for';
const activityLabel = (kind: string): string =>
  ACTIVITY_LABELS.get(kind) ?? ACTION_LABELS[kind] ?? `an activity the page has no words for (${kind})`;
/**
 * While a world plays on its own the page reads its playback control about every two seconds, a
 * cheap read, and reads the society only when the control says the tick moved. A pace faster than
 * that is read at half its interval, so a minute is rarely missed, and never more often than every
 * half second, so a fast pace cannot become a stream of requests.
 */
const CONTROL_POLL_MS = 2_000;
const CONTROL_POLL_FLOOR_MS = 500;

export interface EnvironmentSelectionDependencies {
  readonly env: AppEnvironment;
  readonly state: SessionState;
  readonly scene: AtlasScene;
  readonly credentials: Credentials;
  readonly onPanelOpen?: () => void;
  readonly onObjects?: () => void;
  readonly showStatus: (message: string, kind?: 'progress' | 'failure') => void;
  /**
   * Tell the person, in one sentence, that somebody crossed in from outside, left again or was
   * turned away; `seeWho` opens the visitor's card while it is still here, and is null otherwise.
   */
  readonly onVisitorNotice?: (notice: ShownVisitorNotice) => void;
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
  readonly societyModelsClient?: SocietyModelsClient;
  /** The looks chosen for a society of things' things; read with the credentials when left out. */
  readonly thingLooksClient?: { read(versionId: string): Promise<ReadonlyMap<string, ThingLookChoice>> };
  readonly societyDistrictClient?: SocietyDistrictClient;
  /** The open saved world's flight, read ahead of the page's clock; none when omitted. */
  readonly flight?: (world: {
    readonly worldId: string;
    readonly versionId: string;
    readonly regionId: string;
    readonly onStatus: (status: SavedWorldFlightStatus) => void;
  }) => SavedWorldFlight;
  readonly onDistrictPlacementChange?: () => void;
  /** Ask the Companion about the simulated person selected in the inspector. */
  readonly onAskAboutInhabitant?: (question: string, asked: SocietyQuestion) => void;
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

/** What Selected knows about a selected person, for another surface's view of them. */
export interface SelectedPerson {
  /** The inspector's own words and record for them. */
  readonly note: InspectionNote;
  /** Who runs them now, or null where nobody here takes a model choice or before the first read. */
  readonly mind: PersonMind | null;
  /** Set where they are a thing of a society of things: what its state says they are. */
  readonly being?: SelectedBeing;
}

/** A person of a society of things, as its drawn state says: its kind, how it came, what it holds. */
export interface SelectedBeing {
  readonly kind: KindReference;
  readonly cameBy: 'populated' | 'placed' | 'crossed';
  /** The version's placed thing it is, for one its author placed. */
  readonly placedId: string | null;
  /**
   * For a visitor: the bridge it crossed through and the door's entry for it, null where the door
   * does not list that bridge here (or has not been read yet).
   */
  readonly crossing: { readonly bridge: string; readonly entry: DoorBridge | null } | null;
  /** The things it holds now, by the state's own ids and kinds. */
  readonly holding: readonly { readonly id: string; readonly kind: KindReference }[];
  /** The saved world and version it lives in, for the looks chosen for its things. */
  readonly world: { readonly worldId: string; readonly versionId: string } | null;
}

/** A visitor notice as Selected hands it out: its sentence, its tone, and how to see who. */
export interface ShownVisitorNotice {
  readonly message: string;
  readonly tone: 'info' | 'caution';
  readonly seeWho: (() => void) | null;
}

/** Whether a person is typing in a field, where no click on the world may pick anything. */
const typingInField = (): boolean => {
  const active = document.activeElement;
  return active instanceof HTMLElement && (active.isContentEditable || active.closest('input, textarea, select') !== null);
};

/** A placed thing picked in a saved world, for another surface's view of it. */
export interface SelectedThing {
  readonly placed: PlacedThing;
  readonly worldId: string;
  readonly versionId: string;
}

/**
 * A view another surface shows at the top of Selected for a person (the thing card). The
 * inspector stays under it with only the person's controls and its record.
 */
export interface InhabitantView {
  readonly root: HTMLElement;
  /** Show this person; false leaves them to the inspector. Called again on every refresh. */
  show(subjectId: string, about: SelectedPerson): boolean;
  /** Show a placed thing that is nobody (an object, or a being nothing runs yet) in Selected alone. */
  showThing?(thing: SelectedThing): boolean;
  hide(): void;
}

export interface MountedEnvironmentSelection {
  readonly root: HTMLElement;
  begin(): Promise<void>;
  dispose(): void;
  closePanels(): void;
  openPanel(name: 'nearby' | 'decides' | 'authoring' | 'details'): void;
  /**
   * Open Who decides with these subjects chosen, for another surface (the thing card's model
   * swap). Returns how many it chose; 0 where this world offers no such choice.
   */
  openDecides(target: DecidesTarget): number;
  /**
   * Choose who decides for these people from another surface, by Who decides' own choose: what
   * the server recorded, in the panel's words. Where nobody here takes a model choice, says so.
   */
  decide(target: { readonly role: 'people'; readonly subjectIds: readonly string[]; readonly model: ModelRef | null }): Promise<ChoiceOutcome>;
  /** The models the last read of Who decides offered for people, or null. */
  models(): readonly SocietyModel[] | null;
  /**
   * Another surface's view of a selected person (the thing card), shown in Selected in place of
   * the inspector whenever `show` answers true for the person selected; null puts the inspector
   * back for everyone.
   */
  useInhabitantView(view: InhabitantView | null): void;
  setWelcomeVisible(visible: boolean): void;
  afterAuthoredEdit(versionId: string): Promise<void>;
  districtPlacement(): SocietyDistrictPlacement | null;
  /**
   * The saved world's society, by its version, and the inhabitant selected in it, for a question
   * to the Companion; null where this world shows no society of its own.
   */
  societyContext(): CompanionSocietyContext | null;
  /** Each simulated person's name and each usable place's label, as the inspector draws them. */
  societyNames(): SocietyNames | null;
  /**
   * Select the person a simulation citation names, and show the cited words beside them, each
   * placeholder drawn as `references`, the answer's own maps, say.
   */
  showSimulation(cited: SimulationCitation, references: SimulatedReferences): void;
  /**
   * The people of this world and its clock, for surfaces other than the People panel (the top
   * bar, the command palette). Each call is the same request the panel's own buttons make.
   */
  readonly people: PeopleControls;
}

/** What the world clock shows: the saved playback control and whether a request is in flight. */
export interface PeopleClock {
  /** `absent`: nobody lives here yet; `unconnected`: this world shows no society of its own. */
  readonly society: 'unconnected' | 'loading' | 'absent' | 'present' | 'unavailable';
  readonly mode: SocietyPlaybackMode | null;
  readonly speed: SocietyPlaybackSpeed | null;
  readonly minute: number | null;
  readonly busy: boolean;
  /** Why one minute cannot be advanced by hand now, in the panel's own words, or null. */
  readonly advanceBlocked: string | null;
  readonly playEligible: boolean;
}

export interface PeopleControls {
  clock(): PeopleClock;
  /** Called after every change the People panel draws; returns the unsubscribe. */
  onChange(listener: () => void): () => void;
  /** What the world's capability descriptors allow; the People panel draws refused writes so. */
  setGate(gate: (operation: PeopleOperation) => string | null): void;
  bringIn(): Promise<void>;
  play(): Promise<void>;
  pause(): Promise<void>;
  setSpeed(speed: SocietyPlaybackSpeed): Promise<void>;
  advance(): Promise<void>;
  /**
   * Read the society and its control again and redraw, after a write this panel did not make
   * (a Companion plan step sent to the same routes).
   */
  reread(): Promise<void>;
}

/** The People and clock refusals this surface meets, in words (codes stay in the technical record). */
const PEOPLE_PROBLEMS: Readonly<Record<string, ProblemWords>> = {
  // Thrown by this module when the place a saved world opens at cannot be drawn.
  arrival_source_unavailable: {
    happened: 'The place this world opens at is not available here, so its people cannot be shown.',
    next: 'Reload the page; if it stays, open the world again from the list.',
  },
  society_unavailable: { happened: 'Nobody lives in this world yet.', next: 'Bring people in first.' },
  invalid_society_control: {
    happened: 'The world’s clock did not change.',
    next: 'Look at what the world is doing now, then try again.',
  },
  unavailable_society_input: {
    happened: 'The people of this world cannot be read right now.',
    next: 'Its source photos were withdrawn, so there is nowhere for them to start.',
  },
};
const CLOCK_UNREAD: ProblemWords = {
  happened: 'The world’s clock could not be read.',
  next: 'Try again in a moment.',
};
const CLOCK_UNCHANGED: ProblemWords = {
  happened: 'The world’s clock did not change.',
  next: 'Try again in a moment.',
};
const MINUTE_NOT_ADVANCED: ProblemWords = {
  happened: 'The world did not move on a minute.',
  next: 'Try again in a moment.',
};
const PEOPLE_UNREAD: ProblemWords = {
  happened: 'The people of this world could not be read.',
  next: 'Reload the page to try again.',
};

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
  /** Another surface's view of a selected person, shown in place of the inspector when it can. */
  let inhabitantView: InhabitantView | null = null;
  /** Selected shows the inspector: what any selection but a person another view shows uses. */
  const showInspector = (): void => {
    inhabitantView?.hide();
    if (inhabitantView !== null) inhabitantView.root.hidden = true;
    inspector.setUnderView(false);
    inspector.root.hidden = false;
  };
  /** Once the inspector holds this person, another surface's view may take the top of Selected. */
  const offerInhabitantView = (id: string): void => {
    const note = inspector.note();
    if (inhabitantView === null || note === null) return;
    const being = beingOf(id);
    const shown = inhabitantView.show(id, { note, mind: societyModels?.mindOf(id) ?? null, ...(being === null ? {} : { being }) });
    inhabitantView.root.hidden = !shown;
    if (!shown) inhabitantView.hide();
    inspector.setUnderView(shown);
  };
  const title = el('h2', { text: 'NYC Open Data' });
  // Says what the open world is once the renderer has decided it (see `attach`); nothing is
  // claimed before then, because a sentence written here would describe one kind of world for all.
  const source = el('p', { class: 'environment-selection-source' });
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
  // The framing select joins this section only in a world with a third-person camera (`offerViews`).
  const framing=el('details',{},[el('summary',{text:'Camera framing'}),turnView]);
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
    // Offered once the renderer has decided what kind of world is open (`offerViews`).
    camera: [],
    // The memory layer switch joins them only in a world that has one (`offerLayers`).
    tools: [framing, movement], authoring: editDetails,
  });


  const liveStatus = el('p', { role: 'status', 'aria-live': 'polite', text: 'Persisted society is not connected.' });
  const playbackStatus = el('p', { role: 'status', 'aria-live': 'polite', text: 'Playback controls are not connected.' });
  const playbackMode = el('button', { type: 'button', text: 'Play society', disabled: true });
  const playbackSpeed = el('select', { 'aria-label': 'Society playback speed', disabled: true });
  for (const speed of [1, 2, 4] as const) {
    playbackSpeed.append(el('option', { value: String(speed), text: `${speed}× speed` }));
  }
  const advanceSociety = el('button', { type: 'button', text: 'Next minute', 'data-action': 'clock.advance', disabled: true });
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
  const liveHelp = el('p', { text: 'Play, pause, change speed, or advance one simulated minute. Authored edits affect the next step. Restoring objects retains earlier simulation history.' });
  const liveControls = el('details', { hidden: deps.env.preview }, [
    el('summary', { text: 'Living world simulation' }),
    liveStatus,
    playbackStatus,
    liveHelp,
    playbackMode, playbackSpeed, advanceSociety, refreshSociety,
  ]);
  /**
   * In a saved world, Play, Pause and pace live beside the people, in People nearby; this section
   * says where they are rather than offering a second set.
   */
  function pointToPeopleNearby(): void {
    liveHelp.textContent = 'Play, pause and pace are in People nearby, beside the inhabitants.';
    for (const node of [playbackStatus, playbackMode, playbackSpeed, advanceSociety]) node.remove();
  }
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
    const objectButton = el('button', { type: 'button', text: say('worldControls.addAndArrange') });
    objectButton.addEventListener('click', () => { workspace.close(false); deps.onObjects?.(); });
    workspace.authoring.children[1]?.before(el('p', { text: 'Use the available object catalog to place and arrange objects.' }), objectButton);
  }

  const admissionId = deps.admissionId === undefined ? nycOpenDataAdmissionId() : deps.admissionId;
  const environmentClient = deps.environmentClient ?? new EnvironmentSelectionClient(deps.credentials);
  const worldClient = deps.worldClient ?? new WorldObjectsClient(deps.credentials);
  let liveSociety: LiveSociety | null = null;
  /** Surfaces outside the People panel that draw the people and the clock (see `people`). */
  const peopleListeners = new Set<() => void>();
  let peopleGate: (operation: PeopleOperation) => string | null = () => null;
  // The flyers a saved world's objects host, read from its flight while the world is open.
  let savedFlight: SavedWorldFlight | null = null;
  /** Why the saved world's flight stopped, as the inhabitants panel says it, or null. */
  let flightWords: string | null = null;
  /** Flyers the saved world's objects host that have no home, as the panel says it, or null. */
  let flightUnplaced: string | null = null;
  const districtAbort = new AbortController();
  const districtClient = deps.societyDistrictClient ?? new SocietyDistrictClient({ ...deps.credentials, signal: districtAbort.signal });
  const controlAbort = new AbortController();
  // Every society request names the open world. The preview has none, and sends none.
  const mountedEntry = deps.env.preview ? null : deps.state.activeWorldEntry;
  const openWorldId = mountedEntry?.worldId ?? null;
  const controlClient = deps.societyControlClient ?? new SocietyControlClient({
    ...deps.credentials, signal: controlAbort.signal, worldId: openWorldId,
  });
  let districtView: SocietyDistrictView | null = null;
  let districtEpoch = 0;
  let districtFailure = 'Authorized district placement is not connected.';
  let catalog: EnvironmentCatalog | null = null;
  let current: AlternateVersion | null = null;
  /** The open saved world's placed things, drawn by their looks; null until it is attached. */
  let things: MountedThings | null = null;
  /** Whether the society's crowd draws its things through `things`, and whether that is being set up. */
  let figuresSet = false;
  let thingsMounting = false;
  /** Who runs each being of the open saved world's society, marked over it; null until attached. */
  let marks: AttachedMarks | null = null;
  /** The door's bridges by key, read when a visitor's bridge is first seen; null before any read. */
  let bridges: ReadonlyMap<string, DoorBridge> | null = null;
  /** When the bridges were last asked for, so a bridge the door does not list is asked at most once a minute. */
  let bridgesAskedAt = Number.NEGATIVE_INFINITY;
  /** Whether the looks chosen for the society's things have been read, the things a read covered, and when one was asked. */
  let looksRead = false;
  const looksSeen = new Set<string>();
  let looksAskedAt = Number.NEGATIVE_INFINITY;
  let bridgesReading = false;
  /** Which of a society's events are new, and the bridge each visitor crossed through. */
  const visitorWatch = new VisitorNoticeWatch();
  /** The lines said since the page first read the society. */
  const lineWatch = new LineWatch();
  /** Crossings read but not yet told, while the door says which bridge they came through. */
  let heldNotices: readonly FreshEvent[] = [];
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
  /** Who decides for a saved world's people, beside them in People nearby. */
  let societyModels: MountedSocietyModels | null = null;
  let savedWorldActionClient: SocietyClient | null = null;
  const inhabitantsPanel = buildWorldInhabitants({
    onBringIn: () => void bringInInhabitants(),
    onAdvance: () => void stepPlayback(),
    // The person's own requests; the server records each as one minute of the world's history.
    onSendAway: () => void changePresence('away'),
    onBringBack: () => void changePresence('here'),
    onPlay: () => void configurePlayback('playing'),
    onPause: () => void configurePlayback('paused'),
    onPace: (speed) => void configurePlayback(societyControl?.mode ?? 'paused', speed),
  });
  /** How long the last poll's reads took, measured here: the crowd waits that long plus the poll. */
  let readRoundMs = 0;
  /** Changed by every request the person makes, so a poll that was already out cannot undo it. */
  let controlEpoch = 0;
  /** Everyone the last drawn minutes moved without walking, as the crowd named them. */
  let moved: readonly MovedWithoutWalking[] = [];
  /** The object last placed or moved while people were here, and the input it arrived in. */
  let noticing: (Noticing & { readonly afterInputSeq: number }) | null = null;
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
  let attachedControls: {
    onInteract: (() => void) | null;
    onPointerPick: ((clientX: number, clientY: number) => boolean) | null;
  } | null = null;
  let installedPointerPick: ((clientX: number, clientY: number) => boolean) | null = null;
  let priorPointerPick: ((clientX: number, clientY: number) => boolean) | null = null;

  overview.addEventListener('click', () => deps.state.atlas?.binding.setCityView('overview'));
  street.addEventListener('click', () => deps.state.atlas?.binding.setCityView('street'));
  /**
   * Offer the camera views this world carries out, and no other: a control for a view the world
   * does not have changes nothing on the screen. Decided by the kind of world the renderer drew,
   * never by its name, as the sentence above them is. Turning the view and movement assistance
   * work in every world and are always offered.
   */
  const offerViews = (views: WorldViews): void => {
    workspace.setCamera([
      ...(views.cityViews ? [overview, street] : []),
      ...(views.thirdPerson ? [cameraToggle] : []),
    ]);
    if (views.thirdPerson) framing.insertBefore(cameraFraming, turnView);
    else cameraFraming.remove();
  };
  const memoryCheckbox = memoryLayer.querySelector('input') as HTMLInputElement;
  const reflectMemoryLayer = (visible: boolean): void => {
    memoryCheckbox.checked = visible;
    const kind = deps.state.atlas?.worldKind;
    source.textContent = kind === undefined ? '' : aboutWorldLayers(kind, visible);
  };
  memoryCheckbox.addEventListener('change', () => {
    deps.state.atlas?.binding.setMemoryLayerVisible(memoryCheckbox.checked);
    reflectMemoryLayer(memoryCheckbox.checked);
  });
  /**
   * Offer the memory layer switch only in a world where switching the layer off leaves a world
   * drawn (`worldLayers`); elsewhere the layer holds the ground itself. Where it is offered, it
   * starts from what the binding shows and follows every change the binding announces, since travel
   * switches the layer on by itself: the control follows the world rather than only leading it.
   */
  const offerLayers = (kind: WorldKind): void => {
    const binding = deps.state.atlas?.binding;
    if (!worldLayers(kind).memoryLayer || binding === undefined) {
      memoryLayer.remove();
      return;
    }
    framing.before(memoryLayer);
    reflectMemoryLayer(binding.memoryLayerVisible);
    binding.onMemoryLayerChange = reflectMemoryLayer;
  };

  function inspectSubject(subject: DistrictSubject, keepInhabitant = false): void {
    const runtime = deps.state.atlas?.binding.ownedDistrict;
    const doc = runtime?.interpretation;
    if (!doc) return;
    workspace.inspect();
    showInspector();
    if (!keepInhabitant) selectedInhabitant = null;
    inspectedInhabitant = null;
    citedWords = null;
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
      const actionClient = deps.societyClient ?? new SocietyClient({ ...deps.credentials, worldId: openWorldId });
      directedAction = buildSocietyDirectedAction({
        client: actionClient,
        getSnapshot: () => society,
        getSubjectId: () => selectedInhabitant,
        targetId: destination.destination_id,
        affordance: destination.affordance,
        serverGate: () => peopleGate('direct'),
      });
      inspector.addAction(directedAction.root);
    }
  }

  function clearInspector(): void {
    inspector.clear();
    inspectedInhabitant = null;
    directedAction = null;
    citedWords = null;
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

  /**
   * The saved world's flight: the inhabitants panel says in words why it stopped and which flyers
   * have no home, and the canvas states it for tools (flying, retrying or refused, and the code).
   */
  function reflectFlight(status: SavedWorldFlightStatus): void {
    if (flightWords !== status.refusalWords || flightUnplaced !== status.unplacedWords) {
      flightWords = status.refusalWords;
      flightUnplaced = status.unplacedWords;
      renderInhabitantsPanel();
    }
    const canvas = deps.env.canvas;
    if (!canvas) return;
    canvas.dataset.flightState = status.state;
    canvas.dataset.flightFlyers = String(status.flyers);
    canvas.dataset.flightUnplaced = status.unplaced.map((row) => `${row.objectId}:${row.reason}`).join(' ');
    canvas.dataset.flightUndrawn = status.undrawnKinds.join('; ');
    canvas.dataset.flightFailure = status.failure ?? '';
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
    for (const [index, inhabitant] of (state?.inhabitants ?? []).entries()) {
      if (visible.has(inhabitant.id)) {
        const label = state?.profile === engineCreatedOver('town')
          ? livingInhabitantWords({ role: inhabitant.role ?? null, has_home: inhabitant.has_home === true,
            has_work: inhabitant.has_work === true, action: inhabitant.action ?? null,
            goal: inhabitant.goal && 'activity' in inhabitant.goal ? inhabitant.goal : null }, index).who
          : `${inhabitantLabel(inhabitant)} · ${inhabitant.id.slice(0, 8)}`;
        inhabitantsList.append(el('option', {value: inhabitant.id, text: label}));
      }
    }
    if (selectedInhabitant && visible.has(selectedInhabitant)) inhabitantsList.value = selectedInhabitant;
    reflectCrowd();
  }

  /** The words a Companion citation opened this person with, kept while they stay selected. */
  let citedWords: { readonly inhabitantId: string; readonly text: string } | null = null;

  function inspectInhabitant(id: string, reveal = true): boolean {
    crowd()?.revealInhabitant(id);deps.state.atlas?.binding.invalidate();
    const state = society?.state ?? previewState;
    const inhabitant = state?.inhabitants.find(held => held.id === id);
    if (!inhabitant || !state) return false;
    if (reveal) workspace.inspect();
    // A citation's words belong to the person it opened; selecting anybody else forgets them.
    if (citedWords?.inhabitantId !== id) citedWords = null;
    selectedInhabitant = id;
    inspectedInhabitant = id;
    directedAction = null;
    chosen = null;
    deps.onSelect?.(null);
    setRepresentationHighlight(null);
    place.disabled = true; modify.disabled = true; remove.disabled = true;
    invalidateProposal('Select an authored object before editing.');
    selected.textContent = 'Selected synthetic inhabitant';
    showInspector();
    // Which reader applies is the state's family in the engine table, never its engine's name.
    const family = societyEngine(state.profile).stateFamily;
    if (family === 'living') { inspectLivingInhabitant(inhabitant, state); offerInhabitantView(id); return true; }
    // A society of things' people walk and choose as the purposeful society's do, beside its things.
    const purposeful = family === 'purposeful' || family === 'things';
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
    // Resting is the simulation's state. A catalog person sits on the seat their place has, or on
    // the ground in front of a place with none; the abstract figure stands.
    const resting = purposeful && inhabitant.action?.kind === 'rest' && inhabitant.action.status === 'active';
    const onSeat = deps.state.atlas?.binding.authoredSociety?.inhabitantSeatAtPlace(id) === true;
    const restDrawn = onSeat ? 'Sitting on the seat at the place.' : 'Sitting on the ground in front of the place.';
    // In a person's own world the top says who this is, what they are doing and why, in words,
    // naming places by the titles of the person's objects; the recorded details stay below.
    // Words, and questions to the Companion, only where the words catalog has words for the
    // engine: a stored society of a retired engine shares the purposeful family and has none.
    const worded = savedWorld !== null && purposeful && hasInhabitantWords(state.profile);
    const words = worded && society?.places
      ? inhabitantWords(inhabitant, placeRows(savedObjects() ?? [], society.places), state.inhabitants, state.profile)
      : null;
    inspector.show({
      subject: id,
      title: words?.who ?? inhabitant.display_name ?? `Synthetic ${inhabitant.role ?? 'inhabitant'}`,
      description: words?.what ?? 'A fictional inhabitant of this world. This is not a remembered person.',
      activity: words !== null
        ? `${words.doing} ${words.why}${citedWords?.inhabitantId === id ? ` ${citedWords.text}` : ''}`
        : purposeful
          ? `${inhabitant.explanation?.summary ?? 'Explanation unavailable.'}${resting ? ` Drawn ${onSeat ? 'sitting on the seat at' : 'sitting on the ground in front of'} the place.` : ''}`
          : 'No persisted goal or action is available in this preview or legacy society.',
      details: [
        ...(citedWords?.inhabitantId === id ? [['Cited by the Companion', citedWords.text] as const] : []),
        ...(words !== null ? [
          ['Recorded explanation', inhabitant.explanation?.summary ?? 'Unavailable'],
          ...(societyModels?.personDetails(id) ?? []),
          ...(resting ? [['Drawn as', restDrawn] as const] : []),
        ] as const : []),
        ['Plane / origin', 'Simulation · synthetic'],
        ['Visibility', crowd()?.visibleInhabitantIds.includes(id) ? 'In the nearby display' : 'Outside the nearby display; identity is retained'],
        ['Current activity', purposeful && inhabitant.action ? `${inhabitant.action.kind} · ${inhabitant.action.status}: ${inhabitant.action.reason}` : 'Unavailable'],
        ['Goal / destination', purposeful && goal ? (goal.target_id === null ? (goal.kind === 'make_room' ? 'Making room at a busy place' : `${goal.kind}: ${goal.reason}`) : `${goal.kind} · ${goal.target_id}: ${goal.reason}`) : 'Unavailable'],
        ['Recorded event details', eventText || (liveSociety?.view.eventsAvailable ? 'No event references for this activity.' : 'Event documents unavailable in this view.')],
        ['Event references', purposeful ? inhabitant.explanation?.event_ids.join(', ') || 'No recorded event references' : 'Unavailable'],
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
        ['Unavailable dependencies', purposeful ? 'Personal evidence and model explanation not established by this view.' : 'Routes, goals, event history and authenticated persistence unavailable.'],
      ],
    });
    if (savedWorld !== null && purposeful) {
      if (worded) addAskActions();
      addSavedWorldActions();
    }
    offerInhabitantView(id);
    return true;
  }

  /**
   * A placed thing picked in the world that is nobody opens its card in Selected alone (the view's
   * showThing); a pick that names a person opens theirs as aiming at them does.
   */
  function inspectPlacedThing(placedId: string): boolean {
    const placed = current?.things?.find((thing) => thing.thingId === placedId && !thing.removed);
    const view = inhabitantView;
    if (placed === undefined || savedWorld === null || view?.showThing === undefined) return false;
    workspace.inspect();
    clearInspector();
    selectedInhabitant = null;
    setRepresentationHighlight(null);
    selected.textContent = 'Selected placed thing';
    inspector.setUnderView(false);
    inspector.root.hidden = true;
    const shown = view.showThing({ placed, worldId: savedWorld.worldId, versionId: savedWorld.versionId });
    view.root.hidden = !shown;
    if (!shown) showInspector();
    return true;
  }
  function onThingPick(event: Event): void {
    const detail = (event as CustomEvent<ThingPickDetail>).detail;
    if (detail === null) return;
    if (detail.subjectId !== null) { inspectInhabitant(detail.subjectId); return; }
    if (detail.placedId !== null) inspectPlacedThing(detail.placedId);
  }
  // The pick event is raised on the shell and bubbles; listening at the document hears it from any surface.
  document.addEventListener(THING_PICK_EVENT, onThingPick);

  /** On a selected inhabitant of a saved world: ask the Companion who they are, what and why. */
  function addAskActions(): void {
    const ask = deps.onAskAboutInhabitant;
    if (ask === undefined) return;
    for (const [code, aspect] of [['ask_who', 'who'], ['ask_doing', 'doing'], ['ask_why', 'why']] as const) {
      const question = phrase(code);
      const button = el('button', { type: 'button', class: 'world-inhabitants-ask', text: question });
      button.addEventListener('click', () => ask(question, { scope: 'selected', aspect }));
      inspector.addAction(button);
    }
  }

  function societyNames(): SocietyNames | null {
    if (savedWorld === null || society === null) return null;
    const spots = new Map<string, string>();
    for (const row of society.places === null ? [] : placeRows(savedObjects() ?? [], society.places)) {
      if (row.status.kind === 'usable') spots.set(row.status.targetId, row.label);
    }
    return {
      versionId: society.versionId,
      people: new Map(society.state.inhabitants.map((person) => [person.id, inhabitantLabel(person)])),
      spots,
    };
  }

  /**
   * After an edit, the object it placed or moved while people are here: they notice it at the next
   * simulated minute, which is the server's current tick plus one, and the input that minute
   * consumes is later than the one the drawn state consumed.
   */
  function noticeChangedObject(before: ReadonlyMap<string, InhabitedObject>): void {
    const snapshot = liveSociety?.view.snapshot ?? null;
    if (snapshot === null || snapshot.presence.status !== 'here' || snapshot.places === null) return;
    const objects = savedObjects() ?? [];
    const changed = objects.find((object) => {
      const held = before.get(object.objectId);
      return held === undefined || held.xMm !== object.xMm || held.zMm !== object.zMm;
    });
    if (changed === undefined) return;
    const label = placeRows(objects, snapshot.places).find((row) => row.object.objectId === changed.objectId)?.label ?? changed.title;
    noticing = { label, minute: snapshot.currentTick + 1, noticed: false, afterInputSeq: snapshot.places.inputSeq };
  }

  /**
   * The person's objects in the region the society lives in, as the inhabitants panel names and
   * places them. An object in another region of a world made from photographs is in another place:
   * the society never reads it, so it is neither listed nor noticed.
   */
  function savedObjects(): readonly InhabitedObject[] | null {
    if (current === null) return null;
    const regionId = savedWorld?.regionId ?? null;
    return current.objects.filter((object) => !object.removed && (regionId === null || object.regionId === regionId)).map((object) => ({
      objectId: object.objectId, title: object.asset.title,
      xMm: object.transform.xMm, zMm: object.transform.zMm,
    }));
  }

  /** How a directed action is said in a person's own world: what happens, not its receipt. */
  function plainRecord(place: string, affordance: string) {
    const verb = filled(objectActivity(affordance).verbAtPlace, { place });
    return (record: SocietyActionRecord): string => {
      if (record.status === 'pending') {
        return `Asked to ${verb}. They set off at the next simulated minute. This is simulation, not a memory.`;
      }
      const disposition = record.consumption?.disposition ?? 'unknown';
      return disposition === 'applied'
        ? `Taken up at simulated minute ${record.consumption?.tick}: they are on their way to ${verb}.`
        : `Not taken up at simulated minute ${record.consumption?.tick}: they ${dispositionWords(disposition)}.`;
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
          label: filled(objectActivity(affordance).directLabel, { place: row.label }),
          describeRecord: plainRecord(row.label, affordance),
          idleText: 'Asks this simulated person to go there next. It is recorded as simulation, never as something that happened.',
          serverGate: () => peopleGate('direct'),
        });
        control.root.classList.add('world-inhabitants-action');
        savedWorldActions.set(targetId, control);
      }
      control.reflect();
      inspector.addAction(control.root);
    }
    for (const targetId of [...savedWorldActions.keys()]) if (!usable.has(targetId)) savedWorldActions.delete(targetId);
  }

  function inspectEarlierLivingInhabitant(
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

  function inspectLivingInhabitant(
    inhabitant: OwnedSocietyState['inhabitants'][number],
    state: OwnedSocietyState,
  ): void {
    if (state.profile !== engineCreatedOver('town')) {
      inspectEarlierLivingInhabitant(inhabitant, state);
      return;
    }
    const runtime = crowd();
    const goal = inhabitant.goal && 'activity' in inhabitant.goal ? inhabitant.goal : null;
    const detail = runtime?.inhabitantDetail(inhabitant.id) ?? 'not-drawn';
    const shown = { near: 'A full character near you', far: 'A simple distant figure of the same person',
      indoors: 'Inside premises; interiors are not drawn', 'not-drawn': 'Too far away to draw; identity is retained' }[detail];
    // A site world's places are named in its kind's own words, served with its places; a town's
    // read as they always have.
    const placeWords = society?.places?.placeWords ?? null;
    const where = (destination: string | null | undefined) => {
      if (!destination) return 'an open spot';
      const place = society?.places?.livingDestinations?.get(destination);
      if (placeWords !== null) return place?.label || `a place ${placeWords.here}`;
      if (place?.useClass === 'residential') return 'home';
      if (place?.useClass === 'bench') return 'a bench';
      if (place?.label && place.label !== place.useClass) return place.label;
      if (place?.useClass) return 'a place in town';
      return 'a place in town';
    };
    const live = liveSociety?.inspect(inhabitant.id);
    const ordinal = state.inhabitants.findIndex((person) => person.id === inhabitant.id);
    const words = livingInhabitantWords({ role: inhabitant.role ?? null, has_home: inhabitant.has_home === true, has_work: inhabitant.has_work === true, action: inhabitant.action ?? null, goal }, ordinal, placeWords);
    const needs = Object.keys(inhabitant.needs ?? {}).map(livingNeedLabel).join(', ');
    const simulationClock = state.day === undefined || state.minute_of_day === undefined
      ? 'Unavailable'
      : `Day ${state.day} · ${clockText(state.minute_of_day)}`;
    inspector.show({
      subject: inhabitant.id,
      title: words.who,
      showSubject: false,
      description: words.what,
      activity: `${words.doing}${goal?.destination_id ? ` at ${where(goal.destination_id)}` : ''}. ${words.why}`,
      details: [
        ['Origin', 'Simulated person; not a memory'],
        ['Shown as', shown],
        ['Role', inhabitant.role ?? 'Resident'],
        ['Destination', goal ? where(goal.destination_id) : 'No destination chosen'],
        ['Needs tracked', needs || 'None available'],
        ['Recent events', live?.events.length ? `${live.events.length} recorded events available` : 'No recent events available'],
        ['Simulation clock', simulationClock],
        ['Population', `${state.inhabitants.length} simulated residents`],
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
    const panel = el('details', { class: 'world-recording-disclosure' }, [
      el('summary', { text: 'Living society' }),
      crowdStatus, recordingStatus, recordingPlay, recordingNext, recordingRestart, recordingSpeedSelect,
    ]);
    workspace.details.insertBefore(panel, workspace.details.children[1] ?? null);
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
      recordingStatus.textContent = `The recorded people could not be shown. ${problemSentence(error, PEOPLE_PROBLEMS)}`;
    }
  }

  function reportSelection(feature: NYCLocalFeature, reveal = true): void {
    if (reveal) workspace.inspect();
    showInspector();
    selectedInhabitant = null;
    inspectedInhabitant = null;
    directedAction = null;
    citedWords = null;
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
      : ` Model: ${value.modelName ?? 'not reported'} · prompt: ${value.promptVersion}.`;
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
      modelName: null,
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
      modelName: null,
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
    setText(playbackStatus, control.mode === 'playing'
      ? `Saved as playing at ${control.speed}×. When the playback worker is online, it waits at least ${control.tickIntervalMs} ms after each completed batch. Saved at minute ${control.currentTick}.${control.reason ? ` ${control.reason}` : ''}`
      : `Paused at minute ${control.currentTick}. Speed is set to ${control.speed}×.${eligibility}`);
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
    for (const listener of peopleListeners) listener();
    if (savedWorld === null || liveSociety === null) return;
    const view = liveSociety.view;
    const walked = view.snapshot?.state.inhabitants
      .filter((person) => (person.motion_path_mm?.length ?? 0) > 1).length ?? 0;
    inhabitantsPanel.render({
      society: view, objects: savedObjects(), walked, advanceBlocked: advanceBlocked(),
      playback: { control: societyControl, busy: controlBusy }, moved, noticing, flight: flightWords,
      flightUnplaced, gate: peopleGate,
    });
  }

  /** How long between control reads while this world plays: see `CONTROL_POLL_MS`. */
  function pollDelayMs(): number {
    const interval = societyControl?.hostPlayback?.intervalMs ?? societyControl?.tickIntervalMs ?? CONTROL_POLL_MS;
    return Math.max(CONTROL_POLL_FLOOR_MS, Math.min(CONTROL_POLL_MS, interval / 2));
  }

  function scheduleControlPoll(): void {
    stopControlPoll();
    if (phase === 'disposed' || societyControl === null) return;
    // Keep reading a saved world's control while paused: another client may start its host.
    if (savedWorld !== null && societyControl.hostPlayback?.running !== true) return;
    if (savedWorld === null && societyControl.mode !== 'playing') return;
    controlTimer = window.setTimeout(() => void (savedWorld !== null ? pollPlayback() : refreshPlayback(true)),
      savedWorld !== null ? pollDelayMs() : Math.max(CONTROL_POLL_FLOOR_MS, societyControl.tickIntervalMs));
  }

  /**
   * One background read while a saved world plays: the control, and the society only when the
   * control's tick is not the one drawn. It never disables a control the person could be using.
   */
  async function pollPlayback(): Promise<void> {
    controlTimer = null;
    if (phase === 'disposed' || current === null || controlBusy) return;
    const epoch = controlEpoch;
    const started = performance.now();
    try {
      const read = await controlClient.read(current.versionId);
      if ((phase as string) === 'disposed' || epoch !== controlEpoch) return;
      societyControl = read;
      if (read.currentTick !== liveSociety?.view.snapshot?.currentTick) await liveSociety?.refresh();
      readRoundMs = performance.now() - started;
    } catch (error) {
      if ((phase as string) === 'disposed' || epoch !== controlEpoch) return;
      societyControl = null;
      playbackStatus.textContent = problemSentence(error, PEOPLE_PROBLEMS, CLOCK_UNREAD);
    } finally {
      if ((phase as string) !== 'disposed' && epoch === controlEpoch) { reflectPlayback(); scheduleControlPoll(); }
    }
  }

  async function refreshPlayback(refreshSocietyState = false): Promise<void> {
    if (phase === 'disposed' || deps.env.preview || current === null || controlBusy) return;
    controlEpoch += 1;
    stopControlPoll(); controlBusy = true; reflectPlayback();
    try {
      if (refreshSocietyState) await liveSociety?.refresh();
      societyControl = await controlClient.read(current.versionId);
    } catch (error) {
      societyControl = null;
      playbackStatus.textContent = problemSentence(error, PEOPLE_PROBLEMS, CLOCK_UNREAD);
    } finally {
      controlBusy = false; reflectPlayback(); scheduleControlPoll();
    }
  }

  async function configurePlayback(
    mode: SocietyPlaybackMode, selectedSpeed?: SocietyPlaybackSpeed,
  ): Promise<void> {
    const control = societyControl;
    if (phase === 'disposed' || control === null || controlBusy) return;
    controlEpoch += 1;
    stopControlPoll(); controlBusy = true; reflectPlayback();
    try {
      societyControl = await controlClient.configure(
        control, mode, selectedSpeed ?? control.speed,
      );
      if (mode === 'paused') await liveSociety?.refresh();
    } catch (error) {
      playbackStatus.textContent = problemSentence(error, PEOPLE_PROBLEMS, CLOCK_UNCHANGED);
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
    controlEpoch += 1;
    stopControlPoll(); controlBusy = true; reflectPlayback();
    try {
      if (savedWorld === null && !await refreshDistrict()) {
        throw new Error('Authorized district placement is unavailable.');
      }
      const result = await controlClient.step(control, snapshot);
      societyControl = result.control;
      await liveSociety?.refresh();
    } catch (error) {
      playbackStatus.textContent = problemSentence(error, PEOPLE_PROBLEMS, MINUTE_NOT_ADVANCED);
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
      const before = new Map((savedObjects() ?? []).map((object) => [object.objectId, object]));
      await readSavedVersion();
      refreshSeatingLayout();
      noticeChangedObject(before);
      const atlas = deps.state.atlas?.binding;
      if (atlas && savedWorld !== null && (phase as string) !== 'disposed') await drawPlacedThings(atlas, savedWorld.regionId);
      void savedFlight?.restart();
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
    setText(liveStatus, `${society ? `Saved at minute ${society.currentTick}. ` : ''}${districtView ? view.message : districtFailure}`);
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
    void societyModels?.refresh(society?.currentTick ?? null, societyPeople());
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
    setText(liveStatus, `${society ? `Saved at minute ${society.currentTick}. ` : ''}${view.message}`);
    liveControls.dataset['state'] = view.status;
    refreshSociety.disabled = view.busy;
    const canvas = deps.env.canvas;
    if (society === null || runtime === null) {
      runtime?.clearSociety();
      things?.setSociety(null);
      renderedSnapshot = null;
      marks?.set(new Map());
      if (selectedInhabitant) { selectedInhabitant = null; clearInspector(); selected.textContent = 'Selected inhabitant is unavailable.'; }
      delete canvas.dataset.societyPopulation;
      delete canvas.dataset.societyRendered;
      delete canvas.dataset.societyTick;
    } else {
      // Event and status updates must not restart the interpolation of the same state. A state
      // that skips minutes waits for its events, which record how people walked them.
      const skips = renderedSnapshot !== null && renderedSnapshot.societyId === society.societyId
        && society.currentTick > renderedSnapshot.currentTick + 1;
      const waitForEvents = skips && !view.eventsAvailable && view.status === 'loading';
      if (!waitForEvents && (renderedSnapshot?.stateSha256 !== society.stateSha256 || renderedSnapshot?.societyId !== society.societyId)) {
        drawSavedWorldMinutes(runtime, society, skips && view.eventsAvailable ? view.events : null);
        renderedSnapshot = society;
        if (noticing !== null && !noticing.noticed && (society.places?.inputSeq ?? 0) > noticing.afterInputSeq) {
          noticing = { ...noticing, noticed: true };
        }
      }
      // Who crossed in, left or was turned away since the page last read the world's events.
      visitorWatch.see(society.state.inhabitants);
      if (view.eventsAvailable) {
        heldNotices = [...heldNotices, ...visitorWatch.take(society.societyId, view.events)];
        tellVisitors();
        showLines(society.societyId, view.events, society.state);
      }
      canvas.dataset.societyPopulation = String(society.populationSize);
      canvas.dataset.societyRendered = String(runtime.drawnInhabitantCount);
      canvas.dataset.societyTick = String(society.currentTick);
      if (selectedInhabitant !== null && inspectedInhabitant === selectedInhabitant) {
        inspectInhabitant(selectedInhabitant, false);
      }
    }
    for (const control of savedWorldActions.values()) control.reflect();
    void societyModels?.refresh(society?.currentTick ?? null, societyPeople());
    reflectNearby();
    reflectPlayback();
    atlas?.invalidate();
  }

  /** The connected society's people, as People nearby names them. */
  function societyPeople(): readonly { readonly id: string; readonly name: string }[] {
    return (society?.state.inhabitants ?? []).map((person) => ({ id: person.id, name: inhabitantLabel(person) }));
  }

  /**
   * Who decides for the people of a connected society, in a saved world or a district alike. The
   * section shows only where the served engine lets the world's owner choose a model for a person
   * (`takes_model_choices`), so no kind of world is named here.
   */
  function mountModels(world: { readonly worldId: string; readonly versionId: string }): MountedSocietyModels {
    return mountSocietyModels({
      credentials: deps.credentials, world,
      ...(deps.societyModelsClient ? { client: deps.societyModelsClient } : {}),
      // A read that changes who decides for the inspected person says so in the open inspector.
      onRead: () => {
        if (selectedInhabitant !== null && inspectedInhabitant === selectedInhabitant) inspectInhabitant(selectedInhabitant, false);
        refreshMarks();
      },
    });
  }

  /**
   * Mark who runs each person of the drawn state, decided by the one function the card shares
   * (`markOf`): the model asked for them by the last models read, or the bridge a visitor crossed
   * through. A visitor whose bridge is not yet known asks the door, at most once a minute.
   */
  function refreshMarks(state: OwnedSocietyState | null = renderedSnapshot?.state ?? null): void {
    if (marks === null) return;
    const people = state?.inhabitants ?? [];
    const running = societyModels?.runningModels() ?? new Map();
    const kinds = things?.layer.maker.library.list.kinds ?? [];
    const subjects = new Map<string, MarkedSubject>();
    let unknownBridge = false;
    for (const person of people) {
      const crossing = person.came_by === 'crossed' ? person.crossing ?? null : null;
      if (crossing !== null && bridges?.get(crossing.bridge) == null) unknownBridge = true;
      const mark = markOf(markInputFor(person, running));
      if (mark === null) continue;
      const kind = person.kind;
      const label = kind === undefined ? null
        : kinds.find((one) => one.kind === kind.kind && one.version === kind.version && one.sha256 === kind.sha256)?.label ?? null;
      subjects.set(person.id, { mark, label, spoken: markLabel(mark) });
    }
    marks.set(subjects);
    if (deps.env.canvas) deps.env.canvas.dataset['thingMarks'] = String(subjects.size);
    if (unknownBridge) readBridges();
  }

  /** What decides who runs a person (`markOf`'s input), from the models read and the door's bridges. */
  function markInputFor(
    person: OwnedSocietyState['inhabitants'][number],
    running: ReadonlyMap<string, NamedModelRef> = societyModels?.runningModels() ?? new Map(),
  ): MarkInput {
    const crossing = person.came_by === 'crossed' ? person.crossing ?? null : null;
    const bridge = crossing === null ? null : bridges?.get(crossing.bridge) ?? null;
    return { running: running.get(person.id) ?? null, crossing, bridge, declared: null };
  }

  /**
   * Draw each line said since the page first read the society over its speaker, opening with the
   * line's own mark (`thingLine`), oldest first; a speaker no longer drawn shows no bubble.
   */
  function showLines(societyId: string, events: readonly SocietyEvent[], state: OwnedSocietyState): void {
    const lines = lineWatch.take(societyId, events);
    if (marks === null || lines.length === 0) return;
    const kinds = things?.layer.maker.library.list.kinds ?? [];
    const people = new Map(state.inhabitants.map((person) => [person.id, person]));
    const words = {
      kindLabel: (kind: { kind: string; version: number; sha256: string }) =>
        kinds.find((one) => one.kind === kind.kind && one.version === kind.version && one.sha256 === kind.sha256)?.label ?? null,
      countOf: (kind: { kind: string; version: number; sha256: string }) =>
        state.inhabitants.filter((person) => person.kind?.kind === kind.kind && person.kind.version === kind.version && person.kind.sha256 === kind.sha256).length,
      modelName: (model: ModelRef) =>
        societyModels?.models()?.find((one) => one.provider === model.provider && one.modelId === model.modelId) ?? null,
    };
    for (const line of lines) {
      const speaker = people.get(line.speakerId);
      marks.showLine(thingLine(line, speaker === undefined ? null : markInputFor(speaker), words));
    }
    if (deps.env.canvas) deps.env.canvas.dataset['thingLinesSaid'] = String(Number(deps.env.canvas.dataset['thingLinesSaid'] ?? '0') + lines.length);
  }

  /**
   * Read the looks chosen for a society of things' things when one is first drawn, and again when a
   * state lists a thing no read has covered (a visitor's look is recorded in the minute that brings
   * it in), at most once a minute; then draw them (`MountedThings.setLooks`) and ask the crowd again.
   */
  function readLooksFor(state: OwnedSocietyState): void {
    const world = savedWorld;
    if (things === null || world === null) return;
    const ids = [...state.inhabitants.map((person) => person.id), ...(state.things ?? []).map((thing) => thing.id)];
    const now = performance.now();
    if (!looksReadDue(ids, looksSeen, looksRead, looksAskedAt, now)) return;
    looksAskedAt = now;
    // Only a read issued covers a thing: one skipped by the minute's limit is asked for after it.
    for (const id of ids) looksSeen.add(id);
    const client = deps.thingLooksClient ?? new ThingLooksClient({ ...deps.credentials, worldId: world.worldId });
    void client.read(world.versionId).then((read) => {
      if ((phase as string) === 'disposed' || things === null) return;
      looksRead = true;
      things.setLooks(read);
      deps.state.atlas?.binding.authoredSociety?.refreshFigures();
      if (deps.env.canvas) deps.env.canvas.dataset['thingLooksChosen'] = String(read.size);
    }, (error: unknown) => {
      // A read that failed covered nothing: its things are asked for again after the minute.
      for (const id of ids) looksSeen.delete(id);
      if (deps.env.canvas) deps.env.canvas.dataset['thingLooksFailure'] = error instanceof Error ? error.message : String(error);
    });
  }

  function readBridges(): void {
    const now = performance.now();
    if (now - bridgesAskedAt < 60_000) return;
    bridgesAskedAt = now;
    bridgesReading = true;
    void new DoorBridgesClient(deps.credentials).read().then((read) => {
      bridgesReading = false;
      if ((phase as string) === 'disposed') return;
      bridges = read;
      refreshMarks();
      // The open card and any held notice name the bridge now.
      if (selectedInhabitant !== null && inspectedInhabitant === selectedInhabitant) offerInhabitantView(selectedInhabitant);
      tellVisitors();
    }, () => {
      bridgesReading = false;
      // A door that answers nothing names no bridge: such visitors stay marked as from outside.
      bridges ??= new Map();
      tellVisitors();
    });
  }

  /** A person of the drawn society of things, as the card reads them; null for anyone else. */
  function beingOf(id: string): SelectedBeing | null {
    const state = society?.state ?? null;
    const person = state?.inhabitants.find((held) => held.id === id);
    if (person?.kind === undefined || person.came_by === undefined) return null;
    const crossing = person.came_by === 'crossed' ? person.crossing ?? null : null;
    if (crossing !== null && bridges?.has(crossing.bridge) !== true) readBridges();
    return {
      kind: person.kind,
      cameBy: person.came_by,
      placedId: person.placed_id ?? null,
      crossing: crossing === null ? null : { bridge: crossing.bridge, entry: bridges?.get(crossing.bridge) ?? null },
      holding: (state?.things ?? []).filter((thing) => thing.held_by === id).map((thing) => ({ id: thing.id, kind: thing.kind })),
      world: savedWorld === null ? null : { worldId: savedWorld.worldId, versionId: savedWorld.versionId },
    };
  }

  /**
   * Hand on the notices of the crossings a newly read minute recorded. One that names a bridge
   * the door has not been asked about waits for that answer, so it says where the visitor came from.
   */
  function tellVisitors(): void {
    const tell = deps.onVisitorNotice;
    if (tell === undefined || heldNotices.length === 0) { heldNotices = []; return; }
    const unknown = heldNotices.some((held) => held.bridgeKey !== null && bridges?.has(held.bridgeKey) !== true);
    if (unknown && (bridgesReading || performance.now() - bridgesAskedAt >= 60_000)) { readBridges(); return; }
    const kinds = things?.layer.maker.library.list.kinds ?? [];
    const words = {
      kindLabel: (kind: KindReference) => kinds.find((one) => one.kind === kind.kind && one.version === kind.version && one.sha256 === kind.sha256)?.label ?? null,
      bridge: (key: string) => bridges?.get(key) ?? null,
    };
    for (const held of heldNotices) {
      const notice = visitorNotice(held.event, words, held.bridgeKey);
      if (notice === null) continue;
      const subjectId = notice.subjectId;
      tell({
        message: notice.message,
        tone: notice.tone,
        seeWho: subjectId === null ? null : () => {
          if (!inspectInhabitant(subjectId)) deps.showStatus('They are no longer in this world.');
        },
      });
    }
    heldNotices = [];
  }

  /**
   * Hand the crowd the seating the drawn objects give now, so a seat moved or taken away is got up
   * from at once, and record anyone drawn as everyone is although their state says what they do.
   */
  function refreshSeatingLayout(): void {
    const runtime = deps.state.atlas?.binding.authoredSociety ?? null;
    if (runtime === null || society === null) return;
    runtime.setSeatingLayout(seatingNow(society.places));
    reflectSeatingMisses(runtime);
  }

  /** The seating last built from a version the page read, kept while a re-read fails. */
  let lastSeating: SeatingLayout | null = null;

  /**
   * The seating the drawn objects give, or, when the saved version could not be read again, the
   * last one built from a version that was: people stay on their seats rather than all standing
   * up, and the canvas says which (`data-society-seating-layout`).
   */
  function seatingNow(places: SocietyPlaces | null): SeatingLayout | null {
    const kept = current === null && authoredWorldFailure !== null && lastSeating !== null;
    deps.env.canvas.dataset.societySeatingLayout = kept ? 'kept-after-failed-read' : 'current';
    if (kept) return lastSeating;
    lastSeating = seatingLayout(worldClient.assets(), current, places);
    return lastSeating;
  }

  function reflectSeatingMisses(runtime: NonNullable<NonNullable<SessionState['atlas']>['binding']['authoredSociety']>): void {
    deps.env.canvas.dataset.societySeatingMisses = runtime.seatingMisses.map((miss) => miss.reason).sort().join(' ');
  }

  /**
   * Hand the crowd a saved world's new state, walked at the host's pace. Minutes the page never
   * read are walked first where the events record them; the crowd names anyone it could not walk.
   */
  function drawSavedWorldMinutes(
    runtime: NonNullable<NonNullable<SessionState['atlas']>['binding']['authoredSociety']>,
    next: SocietySnapshot,
    events: LiveSocietyView['events'] | null,
  ): void {
    const control = societyControl;
    const playing = control?.mode === 'playing' && control.hostPlayback?.running === true;
    const intervalMs = control?.hostPlayback?.intervalMs ?? control?.tickIntervalMs;
    const timing = {
      ...(intervalMs === undefined ? {} : { intervalMs }),
      // Playing, each minute is learnt of up to one poll and one read late; stepped by hand, at once.
      startLagMs: playing ? pollDelayMs() + readRoundMs : 0,
    };
    const observer = [deps.state.atlas!.binding.controls.state.x, deps.state.atlas!.binding.controls.state.z] as const;
    const shown = renderedSnapshot?.societyId === next.societyId ? renderedSnapshot.state : null;
    const unread = shown !== null && events !== null ? unreadMinutes(shown, next.state, events) : [];
    // One line per person, however many of the minutes moved them: the latest reason stands.
    const named = new Map<string, MovedWithoutWalking>();
    const layout = seatingNow(next.places);
    // A society of things draws its things by their looks: the crowd through the things' figures.
    if (next.state.things !== undefined) {
      if (things === null && savedWorld !== null && !thingsMounting) {
        thingsMounting = true;
        const atlas = deps.state.atlas!.binding;
        void drawPlacedThings(atlas, savedWorld.regionId, true).then(() => {
          thingsMounting = false;
          if (things !== null && (phase as string) !== 'disposed') {
            runtime.setFigures(things.crowdFigures);
            figuresSet = true;
            things.setSociety(renderedSnapshot?.state ?? next.state);
            atlas.invalidate();
          }
        });
      } else if (things !== null && !figuresSet) {
        runtime.setFigures(things.crowdFigures);
        figuresSet = true;
      }
    }
    for (const minute of [...unread, next.state]) {
      runtime.setSociety(minute, observer, timing, layout);
      for (const jump of runtime.societyJumps ?? []) named.set(jump.inhabitantId, jump);
    }
    things?.setSociety(next.state.things === undefined ? null : next.state);
    reflectSeatingMisses(runtime);
    // The state just drawn: `renderedSnapshot` names it only once this returns.
    refreshMarks(next.state);
    if (next.state.things !== undefined) readLooksFor(next.state);
    moved = [...named.values()];
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

  /** The person's own request to send everyone away or bring them back. */
  async function changePresence(wanted: 'away' | 'here'): Promise<void> {
    if (savedWorld === null || liveSociety === null || phase === 'disposed') return;
    await (wanted === 'away' ? liveSociety.sendAway() : liveSociety.bringBack());
    if ((phase as string) === 'disposed') return;
    await refreshPlayback();
  }

  /** The person's own request. Nothing else creates a saved world's society. */
  async function bringInInhabitants(): Promise<void> {
    if (savedWorld === null || liveSociety === null || phase === 'disposed') return;
    await liveSociety.bringIn();
    if ((phase as string) === 'disposed') return;
    await refreshPlayback();
  }

  /**
   * The region a saved world's people live in: the starter's one authored region, or, in a world
   * made from photographs, the region its society already lives in, else the one the world opens
   * in (`openingIsland`, the page's own pick). A made world's crowd is hung from that region's
   * island here (`hostRegionSociety`), as the starter's is built with its authored region. Null
   * where the world has neither, or its region is not drawn.
   */
  async function societyRegion(entry: NonNullable<SessionState['activeWorldEntry']>): Promise<string | null> {
    if (entry.arrivalUnavailableReason != null || deps.state.arrivalUnavailableReason != null) {
      throw new Error('arrival_source_unavailable');
    }
    if (entry.authoredScene != null) return entry.authoredScene.region.regionId;
    const binding = deps.state.atlas?.binding;
    // A generated world's people live in the one region its entry declares, in the city's frame
    // its tiles are drawn in, standing where a person arrives (`hostGeneratedSociety`).
    // A world made from a world kind is drawn in its site's frame the same way.
    const generated = entry.generatedGround ?? entry.generatedSite ?? null;
    if (generated != null) {
      const { regionId, arrivalMm } = generated;
      return binding?.generatedTile == null || hostGeneratedSociety(binding, regionId, arrivalMm[1]) === null
        ? null : regionId;
    }
    if (entry.declaredFloor == null || binding === undefined) return null;
    const client = deps.societyClient ?? new SocietyClient({ ...deps.credentials, worldId: entry.worldId });
    const stored = await client.read(entry.authoredVersionId).catch((error: unknown) => {
      if (error instanceof ApiError && error.status === 404) return null;
      throw error;
    });
    if (entry.arrival != null && !deps.state.arrivalVerified) {
      throw new Error('arrival_source_unavailable');
    }
    const regionId = entry.arrival?.regionId ?? stored?.regionId
      ?? openingIsland(deps.scene, deps.state.placementRegionIds ?? [])?.islandId ?? null;
    if (regionId === null) return null;
    return hostRegionSociety(binding, regionId as IslandId) === null ? null : regionId;
  }

  /** People nearby offered with the saved world's inhabitants panel, whether or not they can be shown. */
  function offerInhabitantsPanel(): void {
    pointToPeopleNearby();
    root.dataset['state'] = 'ready';
    workspace.setAvailability(true);
    const heading = workspace.nearby.firstElementChild;
    if (heading) heading.after(inhabitantsPanel.root); else workspace.nearby.prepend(inhabitantsPanel.root);
  }

  /**
   * Draw the version's placed things in the frames their regions are drawn in: the society's region
   * is the frame its people walk in (`hostRegionSociety`, `hostGeneratedSociety`), and any other is
   * the authored objects' region root. A library that cannot be read leaves the world as it was and
   * says why on the canvas, never stood in for.
   */
  async function drawPlacedThings(atlas: NonNullable<SessionState['atlas']>['binding'], regionId: string, forSociety = false): Promise<void> {
    const placed = current?.things ?? [];
    if (placed.length === 0 && things === null && !forSociety) return;
    try {
      things ??= await mountThings({
        app: atlas.app,
        camera: atlas.camera,
        shell: deps.env.shell,
        credentials: deps.credentials,
        regionRoot: (id) => (id === regionId
          ? (atlas.authoredSociety?.root.parent as ReturnType<ThingsDependencies['regionRoot']> | undefined) ?? null
          : atlas.regionRoots.get(id as IslandId) ?? null),
        invalidate: () => atlas.invalidate(),
        reducedMotion: () => deps.env.systemReducedMotion.matches,
      });
      if ((phase as string) === 'disposed') { things.destroy(); things = null; return; }
      await things.setPlaced(placed);
      if (deps.env.canvas) deps.env.canvas.dataset['thingsDrawn'] = String(things.layer.drawn.length);
      if (deps.env.canvas) deps.env.canvas.dataset['thingsMissed'] = String(things.misses.length);
    } catch (error) {
      if (deps.env.canvas) deps.env.canvas.dataset['thingsFailure'] = error instanceof Error ? error.message : String(error);
    }
  }

  async function attachSavedWorld(entry: NonNullable<SessionState['activeWorldEntry']>, regionId: string): Promise<void> {
    savedWorld = { worldId: entry.worldId, versionId: entry.authoredVersionId, regionId };
    offerInhabitantsPanel();
    societyModels = mountModels(savedWorld);
    workspace.decides.append(societyModels.root);
    const atlas = deps.state.atlas?.binding;
    if (atlas?.authoredSociety == null) {
      inhabitantsPanel.unavailable('This world is not drawn here, so nobody can be shown in it.');
      return;
    }
    await readSavedVersion();
    if ((phase as string) === 'disposed') return;
    await drawPlacedThings(atlas, regionId);
    if ((phase as string) === 'disposed') return;
    attachedControls = atlas.controls;
    priorInteract = atlas.controls.onInteract;
    // The nearest along a ray wins: a placed thing, or one of the world's people in front of it.
    // Aiming and pressing E and a click on the world before looking around pick the same way.
    const pickAlong = (
      origin: readonly [number, number, number], direction: readonly [number, number, number], via: ThingPickVia,
    ): boolean => {
      const thing = things?.pick(origin, direction) ?? null;
      const inhabitantId = atlas.authoredSociety?.pickInhabitant(origin, direction, thing?.distance ?? Number.POSITIVE_INFINITY);
      if (inhabitantId) { inspectInhabitant(inhabitantId); return true; }
      if (thing !== null) { things?.raise(thing.pick, via); return true; }
      return false;
    };
    installedInteract = () => {
      const ray = atlas.interactionRay?.();
      const position = ray ? { x: ray.origin[0], y: ray.origin[1], z: ray.origin[2] } : atlas.controls.state;
      const forward = ray ? { x: ray.direction[0], y: ray.direction[1], z: ray.direction[2] } : atlas.controls.forward?.() ?? atlas.camera.forward;
      if (!pickAlong([position.x, position.y, position.z], [forward.x, forward.y, forward.z], 'aim')) priorInteract?.();
    };
    atlas.controls.onInteract = installedInteract;
    priorPointerPick = atlas.controls.onPointerPick;
    installedPointerPick = (clientX, clientY) => {
      // No click opens a card while a person types in a field or a surface holds the world modal.
      if (typingInField() || document.querySelector('[aria-modal="true"]:not([hidden])') !== null) return false;
      const ray = atlas.interactionRay === undefined ? null : pointerRay(atlas, clientX, clientY);
      return ray !== null && pickAlong(ray.origin, ray.direction, 'pointer');
    };
    atlas.controls.onPointerPick = installedPointerPick;
    phase = 'attached';
    // The marks write into the element the world shows through, beside the anchor overlay's nodes.
    const stage = atlas.overlay?.root.parentElement ?? null;
    if (stage !== null) {
      marks = new AttachedMarks({
        app: atlas.app, camera: atlas.camera, parent: stage,
        anchors: () => atlas.authoredSociety ?? null,
        selected: () => selectedInhabitant,
        onPick: (id) => { inspectInhabitant(id); },
        invalidate: () => atlas.invalidate(),
      });
    }
    liveSociety = createLiveSociety({
      preview: false, credentials: deps.credentials, worldId: entry.worldId,
      versionId: entry.authoredVersionId, placeId: null, regionId,
      // The engine a saved world's society is created with is the engine table's for its ground,
      // which the server derives and serves with the entry; an entry built without it is a saved
      // world's own. Opening the world never creates anything; the person asks.
      profile: entry.societyEngine ?? engineCreatedOver('saved_world'),
      createOnConnect: false, places: true,
      ...(deps.societyClient ? { client: deps.societyClient } : {}),
      onChange: reflectSavedWorldSociety,
    });
    await liveSociety.connect();
    if ((phase as string) === 'disposed') return;
    // Flyers are read over the starter's ground; a made world's regions host none here.
    savedFlight = entry.authoredScene == null ? null : deps.flight?.({
      worldId: entry.worldId, versionId: entry.authoredVersionId, regionId,
      onStatus: reflectFlight,
    }) ?? null;
    void savedFlight?.start();
    await refreshPlayback();
    if ((phase as string) === 'disposed') return;
    renderInhabitantsPanel();
    reflectNearby();
    void societyModels.refresh(society?.currentTick ?? null, societyPeople(), true);
    atlas.invalidate();
  }

  async function attach(): Promise<void> {
    const kind = deps.state.atlas?.worldKind;
    if (kind !== undefined) {
      // Said before the layers are offered: where a switch is, it says the layer it shows.
      source.textContent = aboutWorld(kind);
      offerViews(worldViews(kind));
      offerLayers(kind);
    }
    const entry = deps.state.activeWorldEntry;
    if (!deps.env.preview && entry != null
      && (entry.authoredScene != null || entry.declaredFloor != null || entry.generatedGround != null
        || entry.generatedSite != null)) {
      try {
        const regionId = await societyRegion(entry);
        if ((phase as string) === 'disposed') return;
        if (regionId === null) {
          offerInhabitantsPanel();
          inhabitantsPanel.unavailable('This world is not drawn here, so nobody can be shown in it.');
          return;
        }
        await attachSavedWorld(entry, regionId);
      } catch (error) {
        if ((phase as string) === 'disposed') return;
        phase = 'idle';
        // Said where the person looks for people, whether or not the panel was offered yet.
        offerInhabitantsPanel();
        inhabitantsPanel.unavailable(problemSentence(error, PEOPLE_PROBLEMS, PEOPLE_UNREAD));
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
      const interpretation = atlas.ownedDistrict?.interpretation;
      if (interpretation) {
        const destinations = el('details', {}, [el('summary', { text: 'Places inhabitants can use' })]);
        for (const destination of interpretation.navigation.destinations) {
          const subject = interpretation.subjects.find(s => s.subject_id === destination.subject_id);
          if (!subject) continue;
          const button = el('button', {type: 'button', text: filled(objectActivity(destination.affordance).markerLabel, { node: destination.node_id })});
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
          preview: false, credentials: deps.credentials, worldId: current.worldId, versionId: current.versionId,
          placeId: catalog.placeId, regionId: String(deps.scene.islands[0]!.islandId),
          ...(deps.societyClient ? { client: deps.societyClient } : {}),
          onChange: reflectLiveSociety,
        });
        societyModels = mountModels({ worldId: current.worldId, versionId: current.versionId });
        workspace.decides.append(societyModels.root);
        await liveSociety.connect();
        if ((phase as string) === 'disposed') return;
        void societyModels.refresh(society?.currentTick ?? null, societyPeople(), true);
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
    decide: (target) => societyModels?.decide(target.subjectIds, target.model)
      ?? Promise.resolve({ recorded: false, words: 'Nobody here can be decided for by a model.' }),
    models: () => societyModels?.models() ?? null,
    useInhabitantView: (view) => {
      if (inhabitantView !== null && inhabitantView !== view) { inhabitantView.hide(); inhabitantView.root.remove(); }
      inhabitantView = view;
      if (view !== null) {
        view.root.hidden = true;
        inspector.root.before(view.root);
      }
      inspector.setUnderView(false);
      inspector.root.hidden = false;
      if (selectedInhabitant !== null && inspectedInhabitant === selectedInhabitant) inspectInhabitant(selectedInhabitant, false);
    },
    openDecides: (target) => {
      workspace.openPanel('decides');
      return societyModels?.chooseFor(target) ?? 0;
    },
    setWelcomeVisible: (visible) => workspace.setWelcomeVisible(visible),
    afterAuthoredEdit,
    districtPlacement: () => districtView?.placement ?? null,
    societyContext: () => {
      if (savedWorld === null || society === null) return null;
      const chosen = selectedInhabitant;
      const inhabitantId = chosen !== null && society.state.inhabitants.some((person) => person.id === chosen)
        ? chosen
        : null;
      return { versionId: society.versionId, inhabitantId };
    },
    societyNames,
    people: {
      clock: (): PeopleClock => {
        const view = liveSociety?.view ?? null;
        const control = societyControl;
        const societyState: PeopleClock['society'] = savedWorld === null || view === null ? 'unconnected'
          : view.status === 'absent' ? 'absent'
            : view.snapshot !== null ? 'present'
              : view.status === 'loading' || view.status === 'idle' ? 'loading' : 'unavailable';
        return {
          society: societyState,
          mode: control?.mode ?? null,
          speed: control?.speed ?? null,
          minute: view?.snapshot?.currentTick ?? control?.currentTick ?? null,
          busy: controlBusy || view?.busy === true,
          advanceBlocked: advanceBlocked(),
          playEligible: control?.playEligible === true,
        };
      },
      onChange: (listener) => { peopleListeners.add(listener); return () => peopleListeners.delete(listener); },
      setGate: (gate) => {
        peopleGate = gate;
        for (const control of savedWorldActions.values()) control.reflect();
        directedAction?.reflect();
        if (savedWorld === null || liveSociety === null) return;
        const view = liveSociety.view;
        const walked = view.snapshot?.state.inhabitants
          .filter((person) => (person.motion_path_mm?.length ?? 0) > 1).length ?? 0;
        inhabitantsPanel.render({
          society: view, objects: savedObjects(), walked, advanceBlocked: advanceBlocked(),
          playback: { control: societyControl, busy: controlBusy }, moved, noticing, flight: flightWords,
          flightUnplaced, gate: peopleGate,
        });
      },
      bringIn: async () => {
        await bringInInhabitants();
        // The panel draws a refusal itself; a caller elsewhere hears it as the server's problem.
        const refusal = liveSociety?.view.refusal ?? null;
        if (refusal !== null) throw new ApiError(refusal.status, refusal.code, refusal.detail);
      },
      play: () => configurePlayback('playing'),
      pause: () => configurePlayback('paused'),
      setSpeed: (speed) => configurePlayback(societyControl?.mode ?? 'paused', speed),
      advance: () => stepPlayback(),
      reread: () => refreshPlayback(true),
    },
    showSimulation: (cited, references) => {
      const names = societyNames();
      const line = drawSimulated([{ kind: 'text', text: cited.line }], references, names)
        .map((piece) => piece.text)
        .join('');
      citedWords = {
        inhabitantId: cited.inhabitantId,
        // An event's line says its own minute; a person's state is said with the minute it is from.
        text: cited.eventId === null
          ? phrase('citation_shown', { minute: cited.tick, line })
          : phrase('citation_shown_event', { line }),
      };
      if (names?.versionId !== cited.versionId || !inspectInhabitant(cited.inhabitantId)) {
        citedWords = null;
        deps.showStatus(phrase('citation_gone'), 'failure');
      }
    },
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
      societyModels?.dispose();
      savedFlight?.stop();
      savedFlight = null;
      flightWords = null;
      flightUnplaced = null;
      for (const key of ['flightState', 'flightFlyers', 'flightUnplaced', 'flightUndrawn', 'flightFailure']) {
        if (deps.env.canvas) delete deps.env.canvas.dataset[key];
      }
      if (liveSociety || recording) crowd()?.clearSociety();
      things?.destroy();
      things = null;
      figuresSet = false;
      marks?.destroy();
      marks = null;
      bridges = null;
      looksRead = false;
      looksSeen.clear();
      looksAskedAt = Number.NEGATIVE_INFINITY;
      visitorWatch.reset();
      lineWatch.reset();
      heldNotices = [];
      if (deps.env.canvas) delete deps.env.canvas.dataset['thingMarks'];
      if (deps.env.canvas) for (const key of ['thingsDrawn', 'thingsMissed', 'thingsFailure']) delete deps.env.canvas.dataset[key];
      savedWorldActions.clear();
      recording = null;
      recordingPlaying = false;
      liveSociety = null;
      society = null;
      renderedSnapshot = null;
      if (attachedControls !== null && attachedControls.onInteract === installedInteract) {
        attachedControls.onInteract = priorInteract;
      }
      if (attachedControls !== null && attachedControls.onPointerPick === installedPointerPick) {
        attachedControls.onPointerPick = priorPointerPick;
      }
      document.removeEventListener(THING_PICK_EVENT, onThingPick);
      installedInteract = null;
      priorInteract = null;
      installedPointerPick = null;
      priorPointerPick = null;
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
