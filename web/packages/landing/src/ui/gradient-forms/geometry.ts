/** Dimensions are local art units. An attachment places two rims exactly gap units apart. */
export interface FormSpec {
  readonly id: string;
  readonly radius: number;
  readonly attach?: { readonly to: string; readonly angle: number; readonly gap: number };
  /** Direction of the illuminated rim, in degrees. */
  readonly light: number;
}
export interface PlacedForm extends FormSpec { readonly x: number; readonly y: number }
export interface FormLayout {
  readonly forms: readonly PlacedForm[];
  readonly bounds: { readonly x: number; readonly y: number; readonly width: number; readonly height: number };
}

export function layoutForms(specs: readonly FormSpec[]): FormLayout {
  if (!specs.length) throw new Error('Gradient forms need at least one shape.');
  const forms: PlacedForm[] = [];
  for (const spec of specs) {
    if (!spec.id || forms.some((form) => form.id === spec.id)) throw new Error('Form ids must be unique.');
    if (!Number.isFinite(spec.radius) || spec.radius <= 0 || !Number.isFinite(spec.light)) {
      throw new Error('A form needs a positive radius and a finite light angle.');
    }
    let x = 0;
    let y = 0;
    if (spec.attach) {
      const parent = forms.find((form) => form.id === spec.attach?.to);
      const { gap, angle } = spec.attach;
      if (!parent || !Number.isFinite(gap) || gap < 0 || !Number.isFinite(angle)) {
        throw new Error('Attach to an earlier form with a nonnegative gap and finite angle.');
      }
      const distance = parent.radius + spec.radius + gap;
      x = parent.x + Math.cos(angle * Math.PI / 180) * distance;
      y = parent.y + Math.sin(angle * Math.PI / 180) * distance;
    } else if (forms.length) {
      throw new Error('Only the first form may omit an attachment.');
    }
    for (const other of forms) {
      if (Math.hypot(x - other.x, y - other.y) < spec.radius + other.radius - 1e-6) {
        throw new Error(`Forms ${spec.id} and ${other.id} intersect.`);
      }
    }
    forms.push({ ...spec, x, y });
  }
  const left = Math.min(...forms.map((form) => form.x - form.radius));
  const top = Math.min(...forms.map((form) => form.y - form.radius));
  const right = Math.max(...forms.map((form) => form.x + form.radius));
  const bottom = Math.max(...forms.map((form) => form.y + form.radius));
  return { forms, bounds: { x: left, y: top, width: right - left, height: bottom - top } };
}
