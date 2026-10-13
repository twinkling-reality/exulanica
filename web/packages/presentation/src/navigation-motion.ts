/** Navigation timing shared by the website and the world workshop. */
export const NAVIGATION_MOTION = Object.freeze({
  page: 180,
  leave: 160,
  landscape: 420,
  inputShape: 320,
  easing: 'cubic-bezier(.22,1,.36,1)',
});

export function navigationMotion(reduced: boolean, kind: 'page' | 'leave' | 'landscape' = 'page') {
  return { duration: reduced ? 0 : NAVIGATION_MOTION[kind], easing: NAVIGATION_MOTION.easing };
}
