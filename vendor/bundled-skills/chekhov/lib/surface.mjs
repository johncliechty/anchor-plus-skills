import fs from 'node:fs';
export const SURFACE_CONTRACT = Object.freeze(JSON.parse(fs.readFileSync(new URL('./surface-contract.json', import.meta.url), 'utf8')));
export const STATUS_FIELDS = Object.freeze(SURFACE_CONTRACT.fields.map((f) => f.name));
const limits = new WeakMap();
export const surfaceText = (value) => String(value ?? '').replace(/[\r\n\t|]+/g, ' ').replace(/\s+/g, ' ').trim();
export function setSurfaceLimit(status, max = 3) {
  if (!Number.isSafeInteger(max) || max < 1) throw new Error('surface.max_waiting_per_unit must be a positive integer');
  limits.set(status, max);
  return status;
}
export function renderWaiting(status, max = limits.get(status) || 3) {
  const groups = Object.entries(status.waiting_on_john || {}).filter(([, asks]) => asks.length);
  return groups.length ? groups.map(([unit, asks]) => `${surfaceText(unit)}: ${asks.slice(0, max).map(surfaceText).join('; ')}${asks.length > max ? ` +${asks.length - max}` : ''}`).join(' / ') : 'none';
}
/** The sole rendering template for the ordered status fields. */
export function renderLine1(status) {
  return SURFACE_CONTRACT.fields.map((field) => `${field.label}: ${field.name === 'waiting_on_john'
    ? renderWaiting(status) : surfaceText(status[field.name]) || field.empty}`).join(' | ');
}
export function humanFieldList() { return STATUS_FIELDS.join(', '); }
