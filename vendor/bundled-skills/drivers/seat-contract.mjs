// Internal physical-attempt channel shared by drivers and the logical dispatcher.
// The symbol prevents a driver's private receipts from escaping through the public
// `onReceipt`, which is reserved for one finalized trio.seat.v1 receipt.

export const PHYSICAL_RECEIPT_HOOK = Symbol.for('trio.seat.physical-receipt');

export function reportPhysicalReceipt(opts, entry) {
  const hook = opts?.[PHYSICAL_RECEIPT_HOOK];
  if (typeof hook === 'function') hook(entry);
}

export function rawTransportError(rec, familyName = 'model') {
  const status = String(rec?.status || 'missing_receipt');
  const aborted = status === 'aborted' || rec?.aborted === true;
  const error = new Error(aborted
    ? `${familyName} transport aborted`
    : `${familyName} transport unavailable (${status})`);
  error.aborted = aborted;
  if (!aborted) error.seat_unavailable = true;
  error.requested_model = rec?.requested_model ?? null;
  error.served_model = rec?.model_served ?? null;
  error.seat_status = status;
  error.raw_receipt = rec ?? null;
  return error;
}

export function localAbortReceipt(label, requestedModel = null) {
  return {
    label,
    ok: false,
    status: 'aborted',
    error: 'seat aborted before transport spawn',
    requested_model: requestedModel,
    model_served: null,
    model_family: null,
    family_attested: false,
    model_attested: false,
    degraded: true,
    aborted: true,
  };
}

