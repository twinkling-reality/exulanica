// Synthetic world training data & counterfactual trajectory export (`exulanica.world-trajectory/v1`).
// Pure formatting, metric computation, and deterministic zero-float JSONL serialization for
// exporting a single decision or a world's History run as SFT and DPO training records.

export const TRAJECTORY_PROFILE = 'exulanica.world-trajectory/v1';

export const TRAJECTORY_WORDS = Object.freeze({
  trainingData: 'Training Data',
  exportTrajectories: 'Export Trajectories',
  counterfactualPairs: 'Counterfactual Pairs',
  verifiedDecisions: 'Verified Decisions',
  saveRunsForTraining: 'Save runs for training',
  teachSmallerModel: 'Teach a smaller model',
  agreementRate: 'Agreement Rate',
  meanLatency: 'Mean Latency',
  refusedDecisions: 'Refused Decisions',
});

const USD_PATTERN = /^[0-9]{1,6}(\.[0-9]{1,12})?$/u;
const plain = (value) => (typeof value === 'string' && value.trim() ? value.trim() : null);

/**
 * Round `numerator / denominator` to nearest integer, ties toward zero (`round_half_down` in
 * `exulanica/canonical.py`), using exact BigInt arithmetic so no IEEE-754 float is used.
 */
export function roundHalfDown(numerator, denominator) {
  if (!Number.isSafeInteger(numerator) || !Number.isSafeInteger(denominator)) {
    throw new TypeError('roundHalfDown requires safe integers');
  }
  if (denominator === 0) throw new RangeError('roundHalfDown denominator cannot be zero');
  let num = BigInt(numerator);
  let den = BigInt(denominator);
  if (den < 0n) {
    num = -num;
    den = -den;
  }
  const absNum = num < 0n ? -num : num;
  let quotient = absNum / den;
  const remainder = absNum % den;
  const twice = 2n * remainder;
  if (twice > den) {
    quotient += 1n;
  }
  return Number(num < 0n ? -quotient : quotient);
}

/**
 * Reject any non-integer number (IEEE-754 float, NaN, Infinity) before canonical serialization.
 */
export function assertNoFloats(value, path = '$') {
  if (value === null || typeof value === 'boolean' || typeof value === 'string') return;
  if (typeof value === 'number') {
    if (!Number.isSafeInteger(value)) {
      throw new TypeError(`Float or non-safe integer at ${path}: ${String(value)}`);
    }
    return;
  }
  if (Array.isArray(value)) {
    for (let i = 0; i < value.length; i += 1) assertNoFloats(value[i], `${path}[${i}]`);
    return;
  }
  if (typeof value === 'object') {
    for (const [key, item] of Object.entries(value)) {
      assertNoFloats(item, `${path}.${key}`);
    }
    return;
  }
  throw new TypeError(`Unsupported value at ${path}: ${typeof value}`);
}

/**
 * Canonical RFC 8785 (JCS) JSON serialization with sorted keys and strict zero-float check.
 */
export function canonicalJson(value) {
  assertNoFloats(value);
  const sortValue = (node) => {
    if (node === null || typeof node !== 'object') return node;
    if (Array.isArray(node)) return node.map(sortValue);
    const sorted = {};
    for (const key of Object.keys(node).sort()) {
      if (node[key] !== undefined) sorted[key] = sortValue(node[key]);
    }
    return sorted;
  };
  return JSON.stringify(sortValue(value));
}

function normalizeCostUsd(costUsd) {
  if (costUsd === null || costUsd === undefined) return '0';
  if (typeof costUsd === 'number') {
    if (!Number.isSafeInteger(costUsd)) {
      throw new TypeError('cost_usd must be a canonical decimal string, never a float');
    }
    return String(costUsd);
  }
  const text = plain(String(costUsd));
  if (!text || !USD_PATTERN.test(text)) {
    throw new TypeError(`Invalid cost_usd decimal string: ${String(costUsd)}`);
  }
  return text;
}

function normalizeOptions(rawOptions = []) {
  return (Array.isArray(rawOptions) ? rawOptions : []).map((opt, index) => {
    if (typeof opt === 'string') {
      const label = opt.trim();
      const takesLine = label.toLowerCase().startsWith('say ');
      return {
        option_id: `option:${index + 1}`,
        label,
        kind: takesLine ? 'say_to' : 'action',
        takes_line: takesLine,
        target_id: null,
      };
    }
    assertNoFloats(opt, `$.offered_options[${index}]`);
    const label = plain(opt?.label ?? opt?.words ?? opt?.action) ?? `option_${index + 1}`;
    const kind = plain(opt?.kind ?? opt?.action) ?? 'action';
    const takesLine = typeof opt?.takes_line === 'boolean'
      ? opt.takes_line
      : kind === 'say_to' || kind === 'say_all' || kind === 'spoke' || label.toLowerCase().startsWith('say ');
    const targetId = plain(opt?.target_id ?? opt?.target?.target_id) ?? null;
    return {
      option_id: plain(opt?.option_id) ?? `option:${index + 1}`,
      label,
      kind,
      takes_line: takesLine,
      target_id: targetId,
    };
  });
}

function normalizeMessages(decision, offeredOptions) {
  if (Array.isArray(decision?.messages) && decision.messages.length > 0) {
    return decision.messages.map((msg, index) => {
      assertNoFloats(msg, `$.messages[${index}]`);
      return {
        role: plain(msg?.role) ?? 'user',
        content: String(msg?.content ?? ''),
      };
    });
  }
  const contextLines = [];
  if (Array.isArray(decision?.told)) {
    for (const section of decision.told) {
      const label = plain(section?.label);
      const lines = Array.isArray(section?.lines) ? section.lines.filter(Boolean).join(' ') : '';
      if (label && lines) contextLines.push(`${label}: ${lines}`);
    }
  } else if (plain(decision?.over)) {
    contextLines.push(plain(decision.over));
  }
  const optionLines = offeredOptions.map((opt) => `- ${opt.label}`);
  return [
    {
      role: 'system',
      content: 'You are deciding what one inhabitant of this world does next.',
    },
    {
      role: 'user',
      content: [...contextLines, 'What you can do now:', ...optionLines, 'Choose one by calling act.'].join('\n'),
    },
  ];
}

/**
 * Build a single `exulanica.world-trajectory/v1` SFT record and any DPO counterfactual pairs
 * from a recorded decision or History moment.
 */
export function decisionTrajectoryRecord(decision, { worldId = 'world:default', versionId = 'version:default' } = {}) {
  assertNoFloats(decision, '$.decision');
  const resolvedWorldId = plain(decision?.world_id ?? decision?.worldId) ?? worldId;
  const resolvedVersionId = plain(decision?.version_id ?? decision?.versionId) ?? versionId;
  const requestId = plain(decision?.request_id ?? decision?.requestId ?? decision?.moment_id ?? decision?.id) ?? 'request:1';
  const tick = Number.isSafeInteger(decision?.tick)
    ? decision.tick
    : Number.isSafeInteger(decision?.base_tick)
      ? decision.base_tick
      : 0;
  const subjectId = plain(decision?.subject_id ?? decision?.subjectId ?? decision?.subjects?.[0]) ?? 'subject:1';
  const modelId = plain(
    decision?.model_id
    ?? decision?.modelId
    ?? decision?.decider?.model?.model_id
    ?? decision?.decider?.model?.name
    ?? (typeof decision?.model === 'string' ? decision.model : decision?.model?.model_id ?? decision?.model?.name),
  ) ?? 'unknown-model';

  const rawOptions = decision?.offered_options
    ?? decision?.options
    ?? decision?.context?.options
    ?? (Array.isArray(decision?.choices)
      ? decision.choices.map((c) => ({ label: c.words ?? c.label, chosen: c.chosen }))
      : []);
  const offeredOptions = normalizeOptions(rawOptions.length > 0 ? rawOptions : [{ label: plain(decision?.chosen_label ?? decision?.title ?? decision?.kind) ?? 'carry on' }]);
  const messages = normalizeMessages(decision, offeredOptions);

  const chosenFromChoices = Array.isArray(decision?.choices)
    ? decision.choices.find((c) => c.chosen)
    : null;
  const chosenLabel = plain(
    decision?.chosen_action?.label
    ?? decision?.proposal?.label
    ?? decision?.chosen_label
    ?? chosenFromChoices?.words
    ?? chosenFromChoices?.label
    ?? decision?.action
    ?? decision?.words
    ?? offeredOptions[0]?.label,
  );
  const firstSaid = Array.isArray(decision?.said) ? decision.said[0]?.line : decision?.said;
  const chosenLine = plain(
    decision?.chosen_action?.line
    ?? decision?.proposal?.line
    ?? decision?.line
    ?? (typeof firstSaid === 'string' ? firstSaid : null),
  );
  const matchedOption = offeredOptions.find((opt) => opt.label === chosenLabel) ?? offeredOptions[0];
  const chosenAction = {
    label: chosenLabel,
    kind: plain(decision?.chosen_action?.kind ?? decision?.kind ?? matchedOption?.kind) ?? 'action',
    line: chosenLine,
    target_id: plain(decision?.chosen_action?.target_id ?? decision?.target?.target_id ?? matchedOption?.target_id) ?? null,
  };

  const latencyRaw = decision?.latency_ms ?? decision?.answered?.latencyMs ?? decision?.unanswered?.latencyMs ?? null;
  if (latencyRaw !== null && !Number.isSafeInteger(latencyRaw)) {
    throw new TypeError(`latency_ms must be a safe integer, got ${String(latencyRaw)}`);
  }
  const latencyMs = latencyRaw ?? 0;
  const costUsd = normalizeCostUsd(decision?.cost_usd ?? decision?.answered?.costUsd ?? decision?.unanswered?.costUsd ?? '0');

  const disposition = plain(decision?.disposition) ?? (decision?.unanswered || decision?.late ? 'rejected' : 'applied');
  const status = plain(decision?.status) ?? (disposition === 'applied' ? 'accepted' : 'rejected');
  const isApplied = status === 'accepted' && disposition === 'applied' && offeredOptions.some((opt) => opt.label === chosenLabel);

  const sft = isApplied
    ? {
        profile: TRAJECTORY_PROFILE,
        record_kind: 'sft',
        world_id: resolvedWorldId,
        version_id: resolvedVersionId,
        request_id: requestId,
        tick,
        subject_id: subjectId,
        model_id: modelId,
        messages,
        offered_options: offeredOptions,
        chosen_action: chosenAction,
        tool_call: {
          name: 'act',
          arguments: {
            action: chosenAction.label,
            ...(chosenAction.line !== null ? { line: chosenAction.line } : {}),
          },
        },
        latency_ms: latencyMs,
        cost_usd: costUsd,
      }
    : null;

  const dpoPairs = [];
  if (!isApplied) {
    const fallbackOpt = offeredOptions.find((opt) => !opt.takes_line) ?? offeredOptions[0];
    dpoPairs.push({
      profile: TRAJECTORY_PROFILE,
      record_kind: 'dpo',
      pair_kind: 'validator_rejection',
      world_id: resolvedWorldId,
      version_id: resolvedVersionId,
      request_id: requestId,
      tick,
      subject_id: subjectId,
      context_messages: messages,
      offered_options: offeredOptions,
      chosen_valid_action: {
        label: fallbackOpt.label,
        kind: fallbackOpt.kind,
        line: null,
        target_id: fallbackOpt.target_id,
        model_id: 'routine_fallback',
      },
      rejected_or_alternative_action: {
        label: chosenAction.label,
        kind: chosenAction.kind,
        line: chosenAction.line,
        target_id: chosenAction.target_id,
        model_id: modelId,
        same_choice: false,
      },
      verdict_reason: plain(decision?.reason ?? decision?.unanswered?.reason) ?? (decision?.late ? 'decision_context_changed' : 'answer_not_offered'),
    });
  }

  const branches = Array.isArray(decision?.branches)
    ? decision.branches
    : Array.isArray(decision?.counterfactual_alternatives)
      ? decision.counterfactual_alternatives
      : [];
  for (const branch of branches) {
    assertNoFloats(branch, '$.branch');
    const sameChoice = typeof branch?.same_choice === 'boolean'
      ? branch.same_choice
      : plain(branch?.label ?? branch?.chosen_label) === chosenAction.label;
    if (sameChoice) continue;
    const altLabel = plain(branch?.label ?? branch?.chosen_label ?? branch?.outcome ?? branch?.kind) ?? 'carried_on';
    const altLine = plain(branch?.line ?? branch?.said?.line) ?? null;
    const altModel = plain(branch?.model_id ?? branch?.model?.model_id ?? branch?.model?.name) ?? 'alternative_model';
    dpoPairs.push({
      profile: TRAJECTORY_PROFILE,
      record_kind: 'dpo',
      pair_kind: 'counterfactual_branch',
      world_id: resolvedWorldId,
      version_id: resolvedVersionId,
      request_id: requestId,
      tick,
      subject_id: subjectId,
      context_messages: messages,
      offered_options: offeredOptions,
      chosen_valid_action: {
        ...chosenAction,
        model_id: modelId,
      },
      rejected_or_alternative_action: {
        label: altLabel,
        kind: plain(branch?.kind) ?? 'carried_on',
        line: altLine,
        target_id: plain(branch?.target?.target_id ?? branch?.target_id) ?? null,
        model_id: altModel,
        same_choice: false,
      },
      verdict_reason: plain(branch?.reason ?? branch?.verdict_reason) ?? 'counterfactual_diverged',
    });
  }

  return { sft, dpoPairs, branches, latencyMs, hasLatency: latencyRaw !== null || latencyMs > 0, isApplied };
}

/**
 * Extract SFT records, DPO counterfactual pairs, and pure integer distillation metrics across
 * a History run or list of decisions.
 */
export function historyRunTrajectories(decisionsOrMoments = [], { worldId = 'world:default', versionId = 'version:default' } = {}) {
  const sftRecords = [];
  const dpoPairs = [];
  let totalDecisions = 0;
  let appliedCount = 0;
  let refusedCount = 0;
  let evaluatedBranches = 0;
  let agreedBranches = 0;
  let latencySum = 0;
  let latencyCount = 0;

  for (const item of decisionsOrMoments) {
    // Skip pure routine moments that were not decided by a model, person, or external agent unless they carry branches
    const deciderKind = item?.decider?.kind ?? item?.decider_kind ?? 'model';
    if (deciderKind === 'routine' && (!Array.isArray(item?.branches) || item.branches.length === 0) && !item?.request_id) {
      continue;
    }
    totalDecisions += 1;
    const extracted = decisionTrajectoryRecord(item, { worldId, versionId });
    if (extracted.sft) {
      appliedCount += 1;
      sftRecords.push(extracted.sft);
    } else {
      refusedCount += 1;
    }
    dpoPairs.push(...extracted.dpoPairs);
    if (extracted.hasLatency) {
      latencySum += extracted.latencyMs;
      latencyCount += 1;
    }
    for (const branch of extracted.branches) {
      evaluatedBranches += 1;
      const same = typeof branch?.same_choice === 'boolean'
        ? branch.same_choice
        : plain(branch?.label ?? branch?.chosen_label) === extracted.sft?.chosen_action?.label;
      if (same) agreedBranches += 1;
    }
  }

  const metrics = {
    total_decisions: totalDecisions,
    applied_count: appliedCount,
    refused_count: refusedCount,
    counterfactual_pairs: dpoPairs.length,
    evaluated_branches: evaluatedBranches,
    agreed_branches: agreedBranches,
    agreement_rate_permille: evaluatedBranches > 0 ? roundHalfDown(agreedBranches * 1000, evaluatedBranches) : 0,
    mean_latency_ms: latencyCount > 0 ? roundHalfDown(latencySum, latencyCount) : 0,
  };

  return {
    profile: TRAJECTORY_PROFILE,
    world_id: worldId,
    version_id: versionId,
    sft_records: sftRecords,
    dpo_pairs: dpoPairs,
    metrics,
  };
}

/**
 * Serialize a trajectory bundle or record array into canonical `exulanica.world-trajectory/v1` JSONL.
 */
export function serializeTrajectoryJsonl(bundleOrRecords) {
  const rows = Array.isArray(bundleOrRecords)
    ? bundleOrRecords
    : [...(bundleOrRecords?.sft_records ?? []), ...(bundleOrRecords?.dpo_pairs ?? [])];
  return rows.map((row) => canonicalJson(row)).join('\n');
}

/**
 * Format human-readable summary lines for the Workspace UI (`Training Data`, `Verified Decisions`, `Counterfactual Pairs`).
 */
export function trajectorySummaryWords(metricsOrBundle) {
  const metrics = metricsOrBundle?.metrics ?? metricsOrBundle ?? {};
  const verified = metrics.applied_count ?? 0;
  const pairs = metrics.counterfactual_pairs ?? 0;
  const agreementPermille = metrics.agreement_rate_permille ?? 0;
  const parts = [
    `${TRAJECTORY_WORDS.verifiedDecisions}: ${verified}`,
    `${TRAJECTORY_WORDS.counterfactualPairs}: ${pairs}`,
  ];
  if ((metrics.evaluated_branches ?? 0) > 0) {
    parts.push(`${TRAJECTORY_WORDS.agreementRate}: ${roundHalfDown(agreementPermille, 10)}%`);
  }
  return parts.join(' · ');
}
