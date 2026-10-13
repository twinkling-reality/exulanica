/** Explanatory mechanism, not a model run. Authority: docs/product-direction.md,
 * First milestone, and docs/society-experiments.md, Comparisons of models.
 * The four strips illustrate the candidate pair and a separate same-model control.
 * Routine/waiting anchors and repeated seeds belong to scoring, outside this recorder.
 */
export const COMPARISON_LANES = [
  { key: 'candidate-a', model: 'a', y: -84, label: 'Model A', purpose: 'Candidate' },
  { key: 'candidate-b', model: 'b', y: -28, label: 'Model B', purpose: 'Candidate' },
  { key: 'control-a', model: 'a', y: 36, label: 'Model A', purpose: 'Control' },
  { key: 'control-repeat', model: 'a', y: 92, label: 'Model A', purpose: 'Control Repeat' },
] as const;

export const COMPARISON_STAGES = [
  { title: 'Starting World', readout: 'One Saved Starting State',
    detail: 'Each run starts with the same world version, group, and paired seed. Only the group’s model changes.' },
  { title: 'Recorded Decisions', readout: 'Separate Runs, Stored Decisions',
    detail: 'A and B decide for the same group. A separate A/A pair measures variation. Each record keeps the observation, model, proposal, and result.' },
  { title: 'Outcome and Replay', readout: 'Stored History, No Model Calls',
    detail: 'The raised model heads leave the stored strips for the readers. Inspect outcomes against the control, then revisit decisions without asking a model again.' },
] as const;

export const COMPARISON_FIGURE = Object.freeze({
  width: 640, height: 450, duration: 18000,
  railStart: -48, railEnd: 132, recordMarks: 12,
});
