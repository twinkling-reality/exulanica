/**
 * The action registry: every action a person can take, declared once.
 *
 * An entry says what the action is called, its icon, its group, where it may be offered (the tool
 * rail, the top bar, a panel, the command palette), its keyboard shortcut, and, for an action that
 * changes the world, the route key of the operation it performs and the words for each refusal
 * that operation can answer. Surfaces render entries; they do not declare buttons of their own.
 * A new backend operation becomes one entry here plus its run binding in the composition root.
 *
 * Availability is the server's. An action with an operation takes its state from that operation's
 * capability descriptor (`GET /world/versions/{v}/capabilities`, or `GET /worlds/capabilities` for
 * making a world); an action with none (opening a
 * panel, the map) is local and available whenever its binding exists. The interface never guesses
 * that a write is possible; the operation still decides when it runs.
 */

import type { CapabilityDescriptor, OperationDescriptors } from '../../capabilities-api.js';
import type { InterfaceState } from '../system/components.js';
import type { IconName } from '../system/icon.js';
import { REQUEST_REFUSALS } from '../words/problems.js';

export type ActionGroup = 'build' | 'people' | 'ask' | 'explore' | 'system';
/** `companion`: offered only as a step of a Companion plan (`ui/actions/planned.ts`). */
export type ActionPlacement = 'rail' | 'top-bar' | 'palette' | 'panel:people' | 'panel:objects' | 'companion';

/** A refusal as a person reads it: what happened, then what to do next. */
export interface RefusalWords {
  readonly happened: string;
  readonly next: string;
}

export interface ActionSpec {
  readonly id: string;
  readonly label: string;
  /** One line for the palette and tooltips: what the action does. */
  readonly hint: string;
  readonly icon: IconName;
  readonly group: ActionGroup;
  readonly placement: readonly ActionPlacement[];
  readonly shortcut?: string;
  /** The route key of the operation it performs; absent for an action that only shows something. */
  readonly operation?: string;
  /** The descriptor's `bind` values that pick this action's operation when a route has several. */
  readonly bind?: Readonly<Record<string, string>>;
  /** Words for each refusal code the operation can answer, as a descriptor state or a response. */
  readonly refusals?: Readonly<Record<string, RefusalWords>>;
  /**
   * A world's route rather than a version's (new pieces of a world's look): no version's capability
   * read lists it, so the plan step, or the route's own refusal, says whether it can be asked.
   */
  readonly worldScoped?: boolean;
  /** For such a route that asks no model and costs nothing (playing a being): never marked as spending. */
  readonly spendsNothing?: boolean;
}

export const GROUP_LABEL: Readonly<Record<ActionGroup, string>> = {
  build: 'Build',
  people: 'People',
  ask: 'Ask',
  explore: 'Explore',
  system: 'Settings',
};

const SOCIETY = 'POST /world/versions/{version_id}/society';
const CONTROL = 'PUT /world/versions/{version_id}/society/control';
const CONTROL_STEP = 'POST /world/versions/{version_id}/society/control/steps';
const OBJECT_UNDO = 'POST /world/versions/{version_id}/objects/undo';
const OBJECT_PLACE = 'POST /world/versions/{version_id}/compositions/apply';
const OBJECT_MOVE = 'POST /world/versions/{version_id}/objects/{object_id}/move';
const OBJECT_REMOVE = 'POST /world/versions/{version_id}/objects/{object_id}/remove';
const ARRANGEMENT_PLACE = 'POST /world/versions/{version_id}/arrangements/apply';
/** A thing added by its kind, and one of a world's beings asked to go to or use a place. */
const THING_PLACE = 'POST /world/versions/{version_id}/things';
const DIRECT = 'POST /world/versions/{version_id}/society/actions';
const PIECES = 'POST /world/piece-requests';
/** Who decides for a society's people: the models route, bound to the people's role. */
const MIND = 'POST /world/versions/{version_id}/models/{role_key}';
const PEOPLE_ROLE = 'society_decision';
const THING_MOVE = 'POST /world/versions/{version_id}/things/{thing_id}/move';
const THING_REMOVE = 'POST /world/versions/{version_id}/things/{thing_id}/remove';
const PRESENCE = 'POST /world/versions/{version_id}/society/presence';
/** A person playing one being, and giving it back: a society's routes no version's capability read lists. */
const PLAY = 'POST /world/versions/{version_id}/society/play';
const PLAY_GIVE_BACK = 'POST /world/versions/{version_id}/society/play/{subject_id}/give-back';
/** Making a town, read from the workspace's creation descriptors (`GET /worlds/capabilities`). */
const MAKE_GENERATED = 'POST /worlds/generated';

const NOBODY_HERE: RefusalWords = {
  happened: 'Nobody lives in this world yet.',
  next: 'Bring people in first.',
};
const STALE_WORLD: RefusalWords = {
  happened: 'This world changed while you were deciding, so nothing was changed.',
  next: 'Look at it again, then try once more.',
};
const SOURCE_GONE: RefusalWords = {
  happened: 'The place this world was built on was deleted, so it can no longer be changed.',
  next: 'What you already made is kept.',
};
const CLOCK_REFUSED: RefusalWords = {
  happened: 'The world’s clock did not change.',
  next: 'Look at People for what the world is doing now, then try again.',
};
const CLOCK_STALE: RefusalWords = {
  happened: 'The world moved on while you were deciding, so its clock did not change.',
  next: 'Look at People for what the world is doing now, then try again.',
};
const PEOPLE_UNREAD: RefusalWords = {
  happened: 'The people of this world cannot be read right now.',
  next: 'Try again in a moment.',
};
/** What adding a thing can meet: the route's own refusals, and those its checks give a plan. */
const THING_REFUSALS: Readonly<Record<string, RefusalWords>> = {
  stale_object_base: STALE_WORLD,
  invalidated_source_version: SOURCE_GONE,
  unavailable_society_input: PEOPLE_UNREAD,
  invalid_thing_placement: {
    happened: 'That thing cannot be put there.',
    next: 'Point somewhere else in this world, then ask again.',
  },
  thing_limit_reached: {
    happened: 'This world holds as many placed things as it can.',
    next: 'Take one back first, then ask again.',
  },
  invalid_object_state: {
    happened: 'Something here already has the name it was given.',
    next: 'Ask again and I will plan it afresh.',
  },
  no_free_place_near: {
    happened: 'There is no free room for it there.',
    next: 'Make some space, or ask to put it somewhere else.',
  },
  anchor_not_here: {
    happened: 'What it was to go beside is not here any more.',
    next: 'Ask again, naming something that is here.',
  },
};
/**
 * What asking one of a world's beings can meet: the actions route's names
 * (`ACTION_REFUSALS` in exulanica/world/society_actions.py) and the two that only mean waiting
 * for the world's next minute.
 */
const DIRECT_REFUSALS: Readonly<Record<string, RefusalWords>> = {
  unavailable_society_input: PEOPLE_UNREAD,
  action_context_changed: {
    happened: 'The world changed since you asked.',
    next: 'Look again, then ask again.',
  },
  canonical_target_changed: {
    happened: 'That place changed since it was chosen.',
    next: 'Ask again and I will plan against what is there now.',
  },
  decided_from_outside: {
    happened: 'That one came from another program, which decides what it does.',
    next: 'It cannot be asked from here.',
  },
  destination_full: {
    happened: 'Every place there is taken.',
    next: 'Ask again when someone leaves.',
  },
  // Their options this minute do not offer that act (out of reach, or their hands or the thing do
  // not allow it now): nothing about where the person points.
  act_not_offered: {
    happened: 'They are not offered that right now.',
    next: 'It may be offered at a later minute, or ask someone else.',
  },
  inhabitant_action_in_progress: {
    happened: 'They are in the middle of something.',
    next: 'Ask again in a minute of the world’s time.',
  },
  inhabitant_already_there: {
    happened: 'They are already there, using it now.',
    next: 'Nothing needed to change.',
  },
  target_unreachable: {
    happened: 'They cannot reach that place from where they are.',
    next: 'Ask them to go somewhere nearer.',
  },
  unknown_inhabitant: {
    happened: 'They are not in this world any more.',
    next: 'Ask someone who is here.',
  },
  society_input_queued: {
    happened: 'The world has not taken in the last change yet.',
    next: 'Ask again in a minute of the world’s time.',
  },
  engine_takes_no_directed_actions: {
    happened: 'People in this kind of world choose for themselves.',
    next: 'They cannot be asked to go somewhere.',
  },
};

/** What asking for new pieces of a world's look can meet: the plan's codes and the route's. */
const PIECE_REFUSALS: Readonly<Record<string, RefusalWords>> = {
  look_not_served: {
    happened: 'This world wears no look new pieces can be made in.',
    next: 'Choose a look for it first, then ask again.',
  },
  look_without_style_words: {
    happened: 'This world\'s look does not say how its pieces should look.',
    next: 'Choose another look, or ask its maker to describe it.',
  },
  no_piece_needed: {
    happened: 'Everything you asked about already has pieces in this look.',
    next: 'Ask about something else here.',
  },
  generation_session_off: {
    happened: 'The piece maker is not running now, so nothing was asked.',
    next: 'Ask again while it runs.',
  },
  budget_exceeded: {
    happened: 'This would cost more than this world\'s allowance has left.',
    next: 'Ask for fewer pieces, or wait for the allowance.',
  },
  piece_quota_exceeded: {
    happened: 'This world has as many pieces waiting as it may.',
    next: 'Ask again when some have been made.',
  },
  look_limit: {
    happened: 'This world\'s look holds as many new pieces as it may.',
    next: 'Take some back first, then ask again.',
  },
};

/**
 * What a choice of who decides can meet: the models route's own codes (said for one person as Who
 * decides says them for the people ticked there) and the plan's, when a group or a mind is gone.
 */
const MIND_REFUSALS: Readonly<Record<string, RefusalWords>> = {
  too_many_model_people: {
    happened: 'That would put more beings under AI models than this world runs at once.',
    next: 'Choose fewer of them, or give some their own routine back first.',
  },
  being_played: {
    happened: 'Someone is playing them now.',
    next: 'Ask again once they are given back.',
  },
  decided_from_outside: {
    happened: 'A program from outside this world decides for them.',
    next: 'A mind can be chosen for them once that program\'s grant ends.',
  },
  decider_not_allowed: {
    happened: 'That kind of being cannot be given that kind of mind.',
    next: 'Choose their own routine, or ask about someone else.',
  },
  person_not_in_this_world: {
    happened: 'They are not in this world any more.',
    next: 'Ask about someone who is here.',
  },
  subject_chosen_under_another_role: {
    happened: 'A model already decides for them in another way.',
    next: 'Change that choice in Who decides first.',
  },
  engine_takes_no_model_choice: {
    happened: 'The people of this world cannot be run by an AI model.',
    next: 'They keep their own routine.',
  },
  model_not_declared: { happened: 'That AI model is not one this server knows.', next: 'Ask for one of the minds listed in Who decides.' },
  model_not_offered: { happened: 'That AI model is not offered for decisions here.', next: 'Ask for one of the minds listed in Who decides.' },
  model_not_askable: { happened: 'That AI model cannot be asked for a decision in this world.', next: 'Ask for one of the minds listed in Who decides.' },
  mind_not_offered: { happened: 'That mind is no longer offered here.', next: 'Ask again and I will list the ones there are.' },
  group_not_here: { happened: 'This world no longer holds that group.', next: 'Ask again and I will list who is here.' },
  too_many_subjects_for_one_choice: {
    happened: 'That is more beings than one choice can name.',
    next: 'Ask for a smaller group, one at a time.',
  },
  choice_key_reused: {
    happened: 'This world changed while I was preparing that choice.',
    next: 'Ask again and I will prepare it against what it is now.',
  },
  society_unavailable: NOBODY_HERE,
  unavailable_society_input: {
    happened: 'This world\'s people cannot be read right now.',
    next: 'Something they were made from is not available. Nothing was changed.',
  },
};

/** What moving or removing a placed thing can meet: the things routes' codes and the plan's. */
const THING_EDIT_REFUSALS: Readonly<Record<string, RefusalWords>> = {
  invalid_object_state: {
    happened: 'That thing is not in this world any more.',
    next: 'Ask about something that is here.',
  },
  invalid_thing_placement: {
    happened: 'It cannot go where you are pointing.',
    next: 'Point somewhere else in the same part of this world, then ask again.',
  },
  no_free_place_near: {
    happened: 'There is no free place near where you are pointing.',
    next: 'Point somewhere with more room, then ask again.',
  },
  thing_kind_erased: {
    happened: 'What that thing was made as is no longer kept, so it cannot be moved.',
    next: 'It can still be removed.',
  },
  stale_object_base: STALE_WORLD,
  invalidated_source_version: SOURCE_GONE,
};

/** What playing a being, or giving it back, can meet: the play routes' codes and the plan's. */
const PLAY_REFUSALS: Readonly<Record<string, RefusalWords>> = {
  engine_takes_no_play: {
    happened: 'The people of this world cannot be played.',
    next: 'Only beings in a world with placed things can be.',
  },
  being_played: { happened: 'Someone else is playing them now.', next: 'Ask again once they are given back.' },
  decided_from_outside: {
    happened: 'A program from outside this world decides for them.',
    next: 'They cannot be played while it does.',
  },
  decider_not_allowed: { happened: 'That kind of being cannot be played.', next: 'Ask to play someone else.' },
  person_not_in_this_world: { happened: 'They are not in this world any more.', next: 'Ask about someone who is here.' },
  not_played: { happened: 'You are not playing anyone here.', next: 'Nothing needed to change.' },
  no_change: { happened: 'You are playing them already.', next: 'Nothing needed to change.' },
  society_unavailable: NOBODY_HERE,
};

/** What sending everyone away, or bringing them back, can meet: the presence route's names. */
const PRESENCE_REFUSALS: Readonly<Record<string, RefusalWords>> = {
  nobody_to_send_away: { happened: 'Nobody is here to send away.', next: 'Nothing needed to change.' },
  already_here: { happened: 'They are already here.', next: 'Nothing needed to change.' },
  a_request_is_waiting: {
    happened: 'Someone was just asked to do something, and that waits for the world\'s next minute.',
    next: 'Move the world on a minute, then ask again.',
  },
  nowhere_to_arrive: {
    happened: 'They cannot come back yet: there is nowhere here they could reach.',
    next: 'Add something to rest on or visit near where you arrive, then ask again.',
  },
  engine_keeps_its_people: {
    happened: 'The people of this world cannot be sent away yet.',
    next: 'A world with placed things keeps its people for now. You can pause the world instead.',
  },
  stale_society_state: CLOCK_STALE,
  society_unavailable: NOBODY_HERE,
};

/** What every clock action can meet, whether a rail button or a Companion plan step sent it. */
const CLOCK_REFUSALS: Readonly<Record<string, RefusalWords>> = {
  society_unavailable: NOBODY_HERE,
  invalid_society_control: CLOCK_REFUSED,
  stale_society_state: CLOCK_STALE,
  stale_clock_revision: CLOCK_STALE,
  clock_lead_exhausted: {
    happened: 'The people cannot run further ahead of this town’s traffic yet.',
    next: 'Let the traffic catch up, then try again.',
  },
};

export const ACTIONS: readonly ActionSpec[] = Object.freeze([
  {
    id: 'objects.open', label: 'Add object', hint: 'Add, move and arrange objects in this world',
    icon: 'object', group: 'build', placement: ['top-bar', 'palette'], shortcut: 'P',
  },
  {
    id: 'objects.undo', label: 'Take back', hint: 'Take back the last change to this world',
    icon: 'undo', group: 'build', placement: ['rail', 'palette'], operation: OBJECT_UNDO,
    refusals: {
      invalid_object_state: { happened: 'There is nothing left to take back.', next: 'Add or move something first.' },
      stale_object_base: STALE_WORLD,
      invalidated_source_version: SOURCE_GONE,
    },
  },
  {
    id: 'objects.place', label: 'Place an object', hint: 'Place a reviewed object where you are pointing',
    icon: 'object', group: 'build', placement: ['companion'], operation: OBJECT_PLACE,
    refusals: { stale_object_base: STALE_WORLD, invalidated_source_version: SOURCE_GONE },
  },
  {
    id: 'objects.move', label: 'Move an object', hint: 'Move an object to where you are pointing',
    icon: 'arrange', group: 'build', placement: ['companion'], operation: OBJECT_MOVE,
    refusals: { stale_object_base: STALE_WORLD, invalidated_source_version: SOURCE_GONE },
  },
  {
    id: 'objects.remove', label: 'Remove an object', hint: 'Take an object out of this world',
    icon: 'remove', group: 'build', placement: ['companion'], operation: OBJECT_REMOVE,
    refusals: { stale_object_base: STALE_WORLD, invalidated_source_version: SOURCE_GONE },
  },
  {
    id: 'arrangements.place', label: 'Place an arrangement', hint: 'Place a published group of objects in one change',
    icon: 'place', group: 'build', placement: ['companion'], operation: ARRANGEMENT_PLACE,
    refusals: { stale_object_base: STALE_WORLD, invalidated_source_version: SOURCE_GONE },
  },
  {
    id: 'pieces.request', label: 'Make new pieces for how things look here',
    hint: 'Ask the piece maker for new pieces of this world\'s look, after seeing the time and the cost',
    icon: 'spends', group: 'build', placement: ['companion'], operation: PIECES, worldScoped: true,
    refusals: PIECE_REFUSALS,
  },
  {
    id: 'things.place', label: 'Add a thing', hint: 'Add a thing by its kind, beside something or where you are pointing',
    icon: 'object', group: 'build', placement: ['companion'], operation: THING_PLACE,
    refusals: THING_REFUSALS,
  },
  {
    id: 'things.move', label: 'Move a thing', hint: 'Move a placed thing to where you are pointing',
    icon: 'arrange', group: 'build', placement: ['companion'], operation: THING_MOVE,
    refusals: THING_EDIT_REFUSALS,
  },
  {
    id: 'things.remove', label: 'Remove a thing', hint: 'Take a placed thing out of this world',
    icon: 'remove', group: 'build', placement: ['companion'], operation: THING_REMOVE,
    refusals: THING_EDIT_REFUSALS,
  },
  {
    id: 'creatures.make', label: 'Make a creature', hint: 'Describe a creature in your own words and it comes to stand in front of you',
    icon: 'add', group: 'build', placement: ['rail', 'palette'],
  },
  {
    id: 'people.direct', label: 'Ask someone', hint: 'Ask one of the beings here to go to a place or use it',
    icon: 'people', group: 'people', placement: ['companion'], operation: DIRECT,
    refusals: DIRECT_REFUSALS,
  },
  {
    id: 'minds.choose', label: 'Choose who decides',
    hint: 'Give a being, a kind, a role or everyone an AI model, or their own routine back, after seeing what it comes to',
    icon: 'people', group: 'people', placement: ['companion'], operation: MIND, bind: { role_key: PEOPLE_ROLE },
    refusals: MIND_REFUSALS,
  },
  {
    id: 'beings.play', label: 'Play this being',
    hint: 'You choose what one being does, in the world, until you give it back; its mind rests meanwhile',
    icon: 'people', group: 'people', placement: ['companion'], operation: PLAY, worldScoped: true, spendsNothing: true,
    refusals: PLAY_REFUSALS,
  },
  {
    id: 'beings.give-back', label: 'Give it back', hint: 'Give back the being you play; its own mind decides again',
    icon: 'people', group: 'people', placement: ['companion'], operation: PLAY_GIVE_BACK, worldScoped: true,
    spendsNothing: true,
    refusals: PLAY_REFUSALS,
  },
  {
    id: 'people.send-away', label: 'Send everyone away',
    hint: 'Send the people who live here away for now; the world and its history stay',
    icon: 'people', group: 'people', placement: ['companion'], operation: PRESENCE,
    refusals: PRESENCE_REFUSALS,
  },
  {
    id: 'people.bring-back', label: 'Bring them back', hint: 'Bring back the people who were sent away',
    icon: 'people', group: 'people', placement: ['companion'], operation: PRESENCE,
    refusals: PRESENCE_REFUSALS,
  },
  {
    id: 'people.open', label: 'People', hint: 'See who lives here and what they are doing',
    icon: 'people', group: 'people', placement: ['rail', 'palette'],
  },
  {
    id: 'people.bring-in', label: 'Bring people in', hint: 'Bring simulated people into this world',
    icon: 'add', group: 'people', placement: ['palette', 'panel:people'], operation: SOCIETY,
    refusals: {
      no_reachable_targets: {
        happened: 'Nobody came in: there is nowhere here they could reach yet.',
        next: 'Add something to rest on or visit near where you arrive, such as a bench or a small square, then try again.',
      },
      society_engine_differs: {
        happened: 'Nobody came in: what this world holds changed while I was getting them.',
        next: 'Bring them in again.',
      },
      engine_not_for_this_ground: {
        happened: 'Nobody came in: this page asked for another kind of people than this world takes.',
        next: 'Reload the page, then bring them in again.',
      },
      unavailable_society_input: {
        happened: 'People cannot be brought into this world.',
        next: 'Its source photos were withdrawn, so there is nowhere for them to start.',
      },
    },
  },
  {
    id: 'clock.play', label: 'Play', hint: 'Let the world run on its own',
    icon: 'play', group: 'people', placement: ['top-bar', 'palette'], operation: CONTROL,
    refusals: CLOCK_REFUSALS,
  },
  {
    id: 'clock.pause', label: 'Pause', hint: 'Stop the world where it is',
    icon: 'pause', group: 'people', placement: ['top-bar', 'palette'], operation: CONTROL,
    refusals: CLOCK_REFUSALS,
  },
  {
    id: 'clock.speed', label: 'Change speed', hint: 'Change how fast the world plays',
    icon: 'clock', group: 'people', placement: ['companion'], operation: CONTROL,
    refusals: CLOCK_REFUSALS,
  },
  {
    id: 'clock.advance', label: 'Next minute', hint: 'Advance the world by one minute',
    icon: 'next-minute', group: 'people', placement: ['top-bar', 'palette'], operation: CONTROL_STEP,
    refusals: CLOCK_REFUSALS,
  },
  {
    id: 'people.decides', label: 'Who decides', hint: 'Choose an open model to decide for some of the people here',
    icon: 'model', group: 'people', placement: ['rail', 'palette'], shortcut: 'R',
  },
  {
    id: 'compare.open', label: 'Compare', hint: 'See what different models chose for the same people',
    icon: 'compare', group: 'people', placement: ['rail', 'palette'],
  },
  {
    id: 'companion.open', label: 'Companion', hint: 'Ask your Companion about this world',
    icon: 'companion', group: 'ask', placement: ['rail', 'palette'], shortcut: 'X',
  },
  {
    id: 'map.open', label: 'Map', hint: 'See this world from above',
    icon: 'map', group: 'explore', placement: ['rail', 'palette'], shortcut: 'M',
  },
  {
    id: 'library.open', label: 'Library', hint: 'People, places and photos you have',
    icon: 'library', group: 'explore', placement: ['rail', 'palette'], shortcut: 'I',
  },
  {
    id: 'character.open', label: 'Character', hint: 'Choose how you look in this world',
    icon: 'character', group: 'explore', placement: ['rail', 'palette'], shortcut: 'K',
  },
  {
    id: 'photos.open', label: 'Add photos', hint: 'Add and review photos for this world',
    icon: 'photos', group: 'build', placement: ['top-bar', 'palette'],
  },
  {
    id: 'about.open', label: 'About this place', hint: 'Camera, movement and where this world comes from',
    icon: 'info', group: 'explore', placement: ['palette'],
  },
  {
    id: 'world.make', label: 'Create a world', hint: 'Start a new town from a recipe',
    icon: 'world', group: 'system', placement: ['palette'], operation: MAKE_GENERATED,
    refusals: {
      world_limit_reached: {
        happened: 'This workspace already holds as many towns as it may.',
        next: 'Open one of the towns you already have instead.',
      },
      generated_tiles_not_installed: {
        happened: 'This server cannot build new towns.',
        next: 'Open a town that is already here.',
      },
      worlds_read_only: {
        happened: 'This server does not make new worlds.',
        next: 'You can open and explore the worlds already here.',
      },
    },
  },
  {
    id: 'design.open', label: 'Design', hint: 'Light, colour and material of this world',
    icon: 'design', group: 'system', placement: ['palette'], shortcut: 'O',
  },
  {
    id: 'settings.open', label: 'Settings', hint: 'Display, movement and controls',
    icon: 'settings', group: 'system', placement: ['palette'], shortcut: '?',
  },
  {
    id: 'menu.open', label: 'World menu', hint: 'Every place in the app',
    icon: 'menu', group: 'system', placement: ['top-bar'], shortcut: 'H',
  },
] satisfies readonly ActionSpec[]);

export type ActionId = typeof ACTIONS[number]['id'];

export function actionSpec(id: string): ActionSpec {
  const spec = ACTIONS.find((candidate) => candidate.id === id);
  if (spec === undefined) throw new Error(`no action ${id}`);
  return spec;
}

/**
 * Refusals any operation may answer at request time (interface packet 5a): the same words for
 * every action, under the action's own.
 */
export const COMMON_REFUSALS: Readonly<Record<string, RefusalWords>> = REQUEST_REFUSALS;

/** The generic words for a refusal the action has no words for; its code goes to the record. */
export const UNRECOGNISED_REFUSAL: RefusalWords = {
  happened: 'That could not be done just now.',
  next: 'Nothing was changed. Try again, or look at the technical details.',
};

/** Words for each descriptor state, when the action has none more precise for its code. */
const STATE_WORDS: Readonly<Partial<Record<InterfaceState, RefusalWords>>> = {
  unavailable: { happened: 'Not available right now.', next: 'Something it needs is not ready.' },
  unsupported: { happened: 'Not in this world.', next: 'This kind of world does not offer it.' },
  'not-permitted': { happened: 'Your access does not include this.', next: 'Ask the owner of this workspace.' },
  unknown: { happened: 'Can’t tell yet whether this is possible.', next: 'Try again in a moment.' },
};

export interface ActionAvailability {
  readonly state: InterfaceState;
  /** The descriptor's code, for the technical record; never shown as the message. */
  readonly code: string | null;
  readonly words: RefusalWords | null;
  readonly spends: boolean;
  readonly descriptor: CapabilityDescriptor | null;
}

export function descriptorFor(spec: ActionSpec, capabilities: OperationDescriptors | null): CapabilityDescriptor | null {
  if (spec.operation === undefined || capabilities === null) return null;
  return capabilities.operations.find((descriptor) => descriptor.operation === spec.operation
    && Object.entries(spec.bind ?? {}).every(([key, value]) => descriptor.bind[key] === value)) ?? null;
}

/**
 * How available an action is: local actions are available; an action with an operation takes its
 * descriptor's state (unsupported first, then permission, then the state). Without a capability
 * read yet, an operation's state is unknown, never assumed available.
 */
export function availability(spec: ActionSpec, capabilities: OperationDescriptors | null): ActionAvailability {
  if (spec.operation === undefined) {
    return { state: 'available', code: null, words: null, spends: false, descriptor: null };
  }
  if (spec.worldScoped === true) {
    return { state: 'available', code: null, words: null, spends: spec.spendsNothing !== true, descriptor: null };
  }
  const descriptor = descriptorFor(spec, capabilities);
  if (descriptor === null) {
    return { state: 'unknown', code: null, words: STATE_WORDS.unknown ?? null, spends: false, descriptor: null };
  }
  const state: InterfaceState = descriptor.state === 'unsupported' ? 'unsupported'
    : !descriptor.permitted ? 'not-permitted'
      : descriptor.state === 'available' ? 'available'
        : descriptor.state === 'unavailable' ? 'unavailable' : 'unknown';
  const words = state === 'available' ? null
    : (descriptor.code === null ? undefined : spec.refusals?.[descriptor.code] ?? COMMON_REFUSALS[descriptor.code])
      ?? STATE_WORDS[state] ?? null;
  return { state, code: descriptor.code, words, spends: descriptor.spends, descriptor };
}

/**
 * The availability of one operation by its route key, for a panel control that is not itself a
 * registry entry (a row's Remove): the same reading as `availability`, with the shared words.
 */
export function operationAvailability(
  operation: string, capabilities: OperationDescriptors | null, bind: Readonly<Record<string, string>> = {},
): ActionAvailability {
  return availability({
    id: `operation:${operation}`, label: operation, hint: operation, icon: 'info', group: 'build',
    placement: [], operation, bind,
  }, capabilities);
}

/** The words for a refusal an operation answered when it ran. */
export function refusalWords(spec: ActionSpec, code: string | null): RefusalWords {
  if (code === null) return UNRECOGNISED_REFUSAL;
  return spec.refusals?.[code] ?? COMMON_REFUSALS[code] ?? UNRECOGNISED_REFUSAL;
}

export function actionsFor(placement: ActionPlacement): readonly ActionSpec[] {
  return ACTIONS.filter((spec) => spec.placement.includes(placement));
}
