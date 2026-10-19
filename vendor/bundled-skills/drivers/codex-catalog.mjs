/** Same-installed-CLI bundled ranks may resolve native ties, never availability.
 * Accept JSON models arrays or { models: [...] }. Keep native effort metadata,
 * ordering, and unique winners. Invalid/unresolved input returns native itself.
 */
const own = (value, key) => Object.prototype.hasOwnProperty.call(value, key);
const object = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);

function indexCatalog(source) {
  const models = object(source) ? source.models : source;
  if (!Array.isArray(models) || !models.length) throw new Error('invalid models array');
  const result = new Map();
  models.forEach((model, index) => {
    if (!object(model)) throw new Error('invalid model');
    const ids = ['slug', 'model', 'id'].filter((key) => own(model, key)).map((key) => model[key]);
    if (!ids.length || ids.some((id) => typeof id !== 'string' || !id || id.trim() !== id) ||
        new Set(ids).size !== 1 || result.has(ids[0])) throw new Error('missing, conflicting, or duplicate model ID');
    let visible = true;
    if (own(model, 'visibility')) {
      if (['hide', 'hidden', 'none'].includes(model.visibility)) visible = false;
      else if (!['list', 'visible', 'show'].includes(model.visibility)) throw new Error('invalid visibility');
    }
    for (const [key, hidesWhen] of [['hidden', true], ['isHidden', true], ['selectable', false], ['visible', false]]) {
      if (own(model, key)) {
        if (typeof model[key] !== 'boolean') throw new Error('invalid visibility flag');
        visible = visible && model[key] !== hidesWhen;
      }
    }
    result.set(ids[0], { index, model, visible });
  });
  return result;
}

function rank(model) {
  if (typeof model.priority !== 'number' || !Number.isFinite(model.priority)) throw new Error('invalid priority');
  return model.priority;
}
function cloneJson(value) {
  if (Array.isArray(value)) return value.map(cloneJson);
  return object(value) ? Object.fromEntries(Object.entries(value).map(([key, item]) => [key, cloneJson(item)])) : value;
}

/** Caller obtains bundled metadata from the same executable; selectors must
 * still reject unresolved top-rank ties. No model-ID or version inference. */
export function reconcileCodexCatalog(native, bundled) {
  try {
    const entries = indexCatalog(native);
    const ranks = new Map([...entries].filter(([, entry]) => entry.visible).map(([id, entry]) => [id, rank(entry.model)]));
    if (!ranks.size) return native;
    const minimum = Math.min(...ranks.values());
    const tied = [...ranks].filter(([, value]) => value === minimum).map(([id]) => id);
    if (tied.length === 1) return native;
    const bundle = indexCatalog(bundled);
    if (tied.some((id) => !bundle.has(id) || !bundle.get(id).visible)) return native;
    const bundledRanks = new Map(tied.map((id) => [id, rank(bundle.get(id).model)]));
    const best = Math.min(...bundledRanks.values());
    const winners = [...bundledRanks].filter(([, value]) => value === best).map(([id]) => id);
    if (winners.length !== 1) return native;
    const winner = winners[0];
    const result = cloneJson(native);
    const models = object(result) ? result.models : result;
    const promoted = minimum - 1;
    if (Number.isFinite(promoted) && promoted < minimum) models[entries.get(winner).index].priority = promoted;
    else {
      const ordinal = new Map([...new Set(ranks.values())].sort((a, b) => a - b).map((value, index) => [value, index + 1]));
      for (const [id, value] of ranks) models[entries.get(id).index].priority = id === winner ? 0 : ordinal.get(value);
    }
    const evidence = { ranking_source: 'installed_cli_priority_for_native_tie',
      availability_source: 'native_debug_models', model_attested: false,
      native_tied_model_ids: [...tied].sort(), selected_model_id: winner,
      bundled_priorities: Object.fromEntries(bundledRanks) };
    models[entries.get(winner).index]._codex_catalog_evidence = evidence;
    if (object(result)) result._codex_catalog_evidence = evidence;
    return result;
  } catch {
    return native;
  }
}
