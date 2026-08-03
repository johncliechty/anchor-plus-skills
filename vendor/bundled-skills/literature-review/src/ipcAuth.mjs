// Wave 1 — cryptographic authentication for telemetry IPC.
// Each spawned worker shares a per-spawn random secret with its parent; every
// envelope is HMAC-SHA256 signed over a canonical (sorted-key) JSON encoding,
// so a message that was tampered with, forged, or reflected fails verification.

import { createHmac, randomBytes, timingSafeEqual } from 'node:crypto';

export function createIpcSecret() {
  return randomBytes(32).toString('hex');
}

// Deterministic JSON encoding: object keys sorted recursively, JSON semantics
// otherwise (undefined object members dropped, NaN/Infinity -> null).
export function canonicalStringify(value) {
  if (value === null) return 'null';
  const t = typeof value;
  if (t === 'number' || t === 'boolean') return JSON.stringify(value);
  if (t === 'string') return JSON.stringify(value);
  if (t === 'bigint') throw new TypeError('cannot canonicalize a bigint value');
  if (t === 'undefined' || t === 'function' || t === 'symbol') return undefined;
  if (Array.isArray(value)) {
    return `[${value.map(v => canonicalStringify(v) ?? 'null').join(',')}]`;
  }
  const keys = Object.keys(value).sort();
  const parts = [];
  for (const key of keys) {
    const encoded = canonicalStringify(value[key]);
    if (encoded !== undefined) parts.push(`${JSON.stringify(key)}:${encoded}`);
  }
  return `{${parts.join(',')}}`;
}

export function eventSignature(event, secret) {
  const { sig, ...unsigned } = event;
  return createHmac('sha256', secret).update(canonicalStringify(unsigned)).digest('hex');
}

export function signEvent(event, secret) {
  return { ...event, sig: eventSignature(event, secret) };
}

export function verifyEvent(event, secret) {
  if (!event || typeof event !== 'object' || Array.isArray(event)) return false;
  if (typeof event.sig !== 'string' || event.sig.length === 0) return false;
  let expected;
  try {
    expected = eventSignature(event, secret);
  } catch {
    return false;
  }
  const actualBuf = Buffer.from(event.sig, 'hex');
  const expectedBuf = Buffer.from(expected, 'hex');
  if (actualBuf.length !== expectedBuf.length || expectedBuf.length === 0) return false;
  return timingSafeEqual(actualBuf, expectedBuf);
}
