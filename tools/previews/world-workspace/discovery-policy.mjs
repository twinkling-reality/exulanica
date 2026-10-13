/** Presentation defaults, separate from the authority and physical reach of any action. */
export const DISCOVERY = Object.freeze({
  leastExtentPx: 2, // Below two pixels the rendered subject cannot be located reliably.
  hitSizePx: 40, // A marker has a usable pointer target even when its glyph is small.
  farGlyphPx: 14,
  nearGlyphPx: 24,
  inspectEnterMetres: 6, // Prototype exploration radius, not an engine's physical-action permission.
  inspectLeaveMetres: 7, // Hysteresis keeps a prompt stable at the boundary.
});

export function inspectionReach(distance, wasReachable = false) {
  return Number.isFinite(distance) && distance >= 0 && distance <= (wasReachable ? DISCOVERY.inspectLeaveMetres : DISCOVERY.inspectEnterMetres);
}

export function promptPresentation(distance) {
  const approach = Math.max(0, Math.min(1, 1 - distance / DISCOVERY.inspectEnterMetres));
  return { height: 46 + approach * 10, key: 28 + approach * 8, font: 14 + approach * 2, opacity: .75 + approach * .25 };
}

export function discoveryPresentation(extent, focused, nameFloor) {
  if (!Number.isFinite(extent) || extent < 0 || !focused && extent < DISCOVERY.leastExtentPx) return null;
  const approach = Math.max(0, Math.min(1, (extent - DISCOVERY.leastExtentPx) / (nameFloor * 4 - DISCOVERY.leastExtentPx)));
  return {
    glyph: Math.min(DISCOVERY.nearGlyphPx, DISCOVERY.farGlyphPx + approach * (DISCOVERY.nearGlyphPx - DISCOVERY.farGlyphPx) + (focused ? 2 : 0)),
    opacity: focused ? .75 + approach * .25 : .5 + approach * .45,
    named: focused || extent >= nameFloor,
  };
}

const overlaps = (a, b) => a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;

/** One ambient hint near the view direction, plus the current focus. Data alone is no cue to label everything. */
export function attentionCandidates(candidates, viewport, selectedKey = null) {
  const focused = candidates.find(item => item.key === selectedKey);
  const ambient = candidates.filter(item => item.key !== selectedKey && item.visible && Math.abs(item.x - viewport.width / 2) <= viewport.width * .28)
    .sort((a, b) => Math.abs(a.x - viewport.width / 2) - Math.abs(b.x - viewport.width / 2) || a.distance - b.distance)[0];
  return [focused, ambient].filter(Boolean);
}

/** Keep each marker over its subject. Overlap suppresses the farther marker; it never moves it. */
export function layoutDiscovery(candidates, viewport, rule, selectedKey = null) {
  const sorted = [...candidates].sort((a, b) => Number(b.key === selectedKey) - Number(a.key === selectedKey) || a.distance - b.distance || a.key.localeCompare(b.key));
  const markers = [], labels = [], result = [];
  let namedArea = 0;
  for (const item of sorted) {
    if (!item.visible || !(item.z > 0) || !Number.isFinite(item.x) || !Number.isFinite(item.y)) continue;
    const presentation = discoveryPresentation(item.extent, item.key === selectedKey, rule.beingLeastPx);
    if (!presentation) continue;
    const half = DISCOVERY.hitSizePx / 2;
    const box = { left: item.x - half, right: item.x + half, top: item.y - DISCOVERY.hitSizePx, bottom: item.y };
    if (box.left < 8 || box.right > viewport.width - 8 || box.top < 8 || box.bottom > viewport.height - 8) continue;
    if (markers.some(other => overlaps(box, other))) continue;
    markers.push(box);
    const nameBox = { left: item.x - item.nameWidth / 2, right: item.x + item.nameWidth / 2, top: box.top - item.nameHeight - 4, bottom: box.top - 4 };
    const nameArea = item.nameWidth * item.nameHeight;
    const focused = item.key === selectedKey;
    const named = presentation.named && nameBox.left >= 8 && nameBox.right <= viewport.width - 8 && nameBox.top >= 8
      && !labels.some(other => overlaps(nameBox, other)) && !markers.some(other => overlaps(nameBox, other))
      && !sorted.some(other => other.key !== item.key && other.visible && overlaps(nameBox, { left: other.x - half, right: other.x + half, top: other.y - DISCOVERY.hitSizePx, bottom: other.y }))
      && (focused || namedArea + nameArea <= viewport.width * viewport.height * rule.screenShare);
    if (named) { labels.push(nameBox); namedArea += nameArea; }
    result.push({ ...item, ...presentation, named });
  }
  return result;
}

/** An exact body hit always wins. Marker assistance only covers displayed, unobstructed markers. */
export function markerAt(markers, pointer) {
  if (!pointer) return null;
  return markers.filter(item => Math.abs(pointer.x - item.x) <= DISCOVERY.hitSizePx / 2 && pointer.y >= item.y - DISCOVERY.hitSizePx && pointer.y <= item.y)
    .sort((a, b) => Math.hypot(pointer.x - a.x, pointer.y - (a.y - DISCOVERY.hitSizePx / 2)) - Math.hypot(pointer.x - b.x, pointer.y - (b.y - DISCOVERY.hitSizePx / 2)))[0] ?? null;
}
