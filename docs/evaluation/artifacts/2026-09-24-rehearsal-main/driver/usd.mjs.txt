// Decimal US dollar amounts as the product reports them ("0.00026860", "2E-8"), added and compared
// exactly. A float would do for one call; a run adds dozens, and a bound is a comparison.

// Fifteen decimal places: the product's cost figures carry eight, and the provider's per-token
// prices are quoted to twelve.
const SCALE = 15;
const DECIMAL = /^(?<whole>\d+)(?:\.(?<fraction>\d+))?(?:[eE](?<exponent>[+-]?\d+))?$/;

function units(text) {
  const match = DECIMAL.exec(String(text).trim());
  if (match === null) throw new Error(`${JSON.stringify(text)} is not a non-negative decimal amount`);
  const fraction = match.groups.fraction ?? '';
  const exponent = Number(match.groups.exponent ?? 0);
  const digits = BigInt(`${match.groups.whole}${fraction}`);
  const shift = SCALE - fraction.length + exponent;
  return shift >= 0 ? digits * 10n ** BigInt(shift) : digits / 10n ** BigInt(-shift);
}

function text(value) {
  const padded = value.toString().padStart(SCALE + 1, '0');
  const whole = padded.slice(0, -SCALE);
  const fraction = padded.slice(-SCALE).replace(/0+$/, '');
  return fraction.length > 0 ? `${whole}.${fraction}` : whole;
}

export function addUsd(a, b) {
  return text(units(a) + units(b));
}

export function compareUsd(a, b) {
  const difference = units(a) - units(b);
  return difference > 0n ? 1 : difference < 0n ? -1 : 0;
}
