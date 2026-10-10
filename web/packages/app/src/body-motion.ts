/**
 * The figures a drafted body's motion is drawn by and a long body's turn is bounded by, read from
 * the one data file that states each with its reason,
 * `assets/catalogs/thing-presentation/body-motion.v1.json`. Presentation only: nothing here changes
 * a recorded position, path, ability or event.
 */
import { readBodyMotion, type BodyMotion } from '@exulanica/atlas-react/things';
import catalogText from '../../../../assets/catalogs/thing-presentation/body-motion.v1.json?raw';

/** The table every figure of the page is posed by. */
export const BODY_MOTION: BodyMotion = readBodyMotion(JSON.parse(catalogText));
