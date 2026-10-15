/**
 * Why a person's own world asks no model, or not the model they chose, and why a choice of model was
 * not recorded: the words for the refusal codes the decision host and the models route send. The
 * "Who decides" panel, the Play panel, the comparison start and the world workspace all say them.
 */

/**
 * Why this host asks no model for this world's people, by `HOST_REFUSALS` in
 * `decision_admission.py`: the section and the inspector each say it in a sentence.
 */
export const HOST_REFUSAL_WORDS: Readonly<Record<string, string>> = {
  models_not_run_here: 'this server does not ask models for this world\'s people',
  provider_credential_absent: 'this server has no key for a model service',
  process_budget_spent: 'this server has spent its model budget until it restarts',
  process_share_spent: 'this server\'s model budget is down to the part kept for its other work, until it restarts',
};

/**
 * Why a person's chosen model is not asked here while this host asks others, by `MODEL_REFUSALS`
 * in `decision_admission.py`.
 */
export const MODEL_REFUSAL_WORDS: Readonly<Record<string, string>> = {
  model_no_longer_offered: 'the model you chose is no longer offered for decisions',
  provider_changed: 'the service that runs the model you chose has changed, so choose it again to use it',
  provider_not_admitted: 'this server may not reach the service that runs the model you chose',
  provider_credential_absent: 'this server has no key for the service that runs the model you chose',
  process_budget_spent: 'this server has too little of its model budget left to ask the model you chose, until it restarts',
  process_share_spent: 'this server\'s model budget, less the part kept for its other work, is too little to ask the model you chose, until it restarts',
  question_changed_by_rules: 'this world\'s rules would change the question each person is asked, since a name you saved shares a word with it',
};

/** Why a choice was not recorded, by the code the models route refuses it with. */
export const CHOICE_REFUSAL_WORDS: Readonly<Record<string, string>> = {
  engine_takes_no_model_choice: 'The people of this world cannot be run by a model.',
  person_not_in_this_world: 'Someone you chose is no longer in this world. Look again, then choose again.',
  person_named_twice: 'The same person was named twice. Choose again.',
  model_not_declared: 'That model is not one this server knows.',
  model_not_offered: 'That model is not offered for decisions.',
  model_not_askable: 'That model cannot be asked for a decision here.',
  too_many_model_people: 'That would put more people under models than this world allows.',
  choice_key_reused: 'That choice was already sent with different people. Choose again.',
  subject_chosen_under_another_role: 'That subject is already assigned to a model under another kind of decision.',
  decided_from_outside: 'Someone you chose is decided for from outside this world, by a program a door grant lets in, so no model can be chosen for them until that grant ends.',
  decider_not_allowed: 'Someone you chose is a kind of being that this kind of decider may not decide for.',
  engine_takes_no_traveller_choice: 'Only a society of things takes visitors, so only it takes a mind for a gate\'s travellers.',
  being_played: 'Someone is playing this being now. Choose again once they give it back.',
  engine_takes_no_play: 'Only the beings of a society of things can be played.',
  not_played: 'You are not playing this being.',
};

/** Why a choice was refused, in words; the code stays available to the caller. */
export function choiceRefusalWords(code: string, detail: string): string {
  return CHOICE_REFUSAL_WORDS[code] ?? (detail.length > 0
    ? 'The choice was not recorded. Try again, or choose another model.'
    : 'The choice was not recorded.');
}
