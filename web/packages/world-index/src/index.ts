/**
 * @exulanica/world-index
 *
 * The index UI, entity detail and the provenance panel. Forbidden: the renderer
 * (architecture-overview.md 1.1).
 *
 * That ban is what makes this package the accessibility route and the default entry on touch
 * devices: it has to work with no canvas at all. Pointer Lock is unsupported on iOS Safari and
 * Android Chrome (https://caniuse.com/pointerlock, interaction-model.md 2.1), so browser-only
 * mobile has no first-person Atlas and this is where it lands instead.
 *
 * WHAT THIS PACKAGE IS, AND WHAT IT IS NOT. It is the view model and the interaction rules: the
 * facets and their URL encoding, the row projection with its epistemic marks, the fixed-order
 * entity detail, the action tiers, the review-queue preset and the mobile entry decision. It is
 * not markup. This package has no view-framework dependency; everything here is
 * framework-free so every rule above is testable without a DOM.
 *
 * The two places this package refuses to reimplement anything:
 *   - the four-band provenance panel comes from companion-runtime (5.2 is "one component with
 *     two mount points", and this is the second mount point).
 *   - row order comes from companion-runtime's value function (6.3: the queue, the Companion and
 *     the ambient counter must agree, or "the product would feel like two systems arguing").
 */

export type { IndexFacets } from './facets.js';
export {
  ALL_FACETS,
  FACET_KEYS,
  FACET_VALUES,
  applyFacets,
  decodeFacets,
  encodeFacets,
} from './facets.js';

export type {
  ExternalBadge,
  HonestPlaceholder,
  IndexRow,
  ProvenanceTriad,
} from './rows.js';
export { showsConfidence, toRow } from './rows.js';

export type { ParsedSearch, SemanticQuery } from './search.js';
export { SEMANTIC_RESULT_LIMIT, parseSearch, semanticQuery } from './search.js';

export type { ActionOffer, IndexAction } from './actions.js';
export {
  ACTION_ORDER,
  ACTION_TIER,
  REVIEW_PRODUCES,
  assertBatchAllowed,
  availableActions,
  batchableActions,
} from './actions.js';

export type {
  DetailSection,
  EntityDetailInput,
  EntityDetailView,
  OccurrenceCitation,
} from './detail.js';
export { DETAIL_SECTION_ORDER, buildEntityDetail } from './detail.js';

export type { ReviewQueueView } from './review-queue.js';
export { REVIEW_QUEUE_FACETS, isReviewQueue, reviewQueue } from './review-queue.js';

export type { DeviceCapabilities, EntrySurface, TravelRequest } from './mobile.js';
export { MIN_TOUCH_TARGET_PX, VIRTUAL_JOYSTICK_SUPPORTED, entrySurface, travelTo } from './mobile.js';

export type { DeleteConsequences } from './proposals.js';
export {
  confirmationFor,
  deleteConsequences,
  draftDelete,
  draftEdit,
  draftMerge,
  draftSplit,
} from './proposals.js';

export type { IndexView, IndexViewInput } from './view.js';
export { buildIndexView } from './view.js';
