"""Use the same installed CLI's bundled priorities only to resolve native ties.

Accept JSON models arrays or objects containing models. Preserve native
availability, effort support, ordering, and unique winners. Never select by ID
spelling or array order. Invalid/unresolved input returns native unchanged.
"""
from copy import deepcopy
import math


def _index(source):
    models = source.get("models") if isinstance(source, dict) else source
    if not isinstance(models, list) or not models:
        raise ValueError("invalid models array")
    result = {}
    for index, model in enumerate(models):
        if not isinstance(model, dict):
            raise ValueError("invalid model")
        ids = [model[key] for key in ("slug", "model", "id") if key in model]
        if (not ids or any(not isinstance(x, str) or not x or x.strip() != x for x in ids)
                or len(set(ids)) != 1 or ids[0] in result):
            raise ValueError("missing, conflicting, or duplicate model ID")
        visible = True
        if "visibility" in model:
            if model["visibility"] in ("hide", "hidden", "none"):
                visible = False
            elif model["visibility"] not in ("list", "visible", "show"):
                raise ValueError("invalid visibility")
        for key, hides_when in (("hidden", True), ("isHidden", True), ("selectable", False), ("visible", False)):
            if key in model:
                if not isinstance(model[key], bool):
                    raise ValueError("invalid visibility flag")
                visible = visible and model[key] is not hides_when
        result[ids[0]] = (index, model, visible)
    return result


def _rank(model):
    value = model.get("priority")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("invalid priority")
    return value


def reconcile_codex_catalog(native, bundled):
    """Return a copy only when bundled ranks uniquely resolve a native top tie.

    The caller obtains bundled metadata from the same installed executable.
    Effort metadata remains native. A consumer must still reject top-rank ties.
    """
    try:
        entries = _index(native)
        ranks = {key: _rank(entry[1]) for key, entry in entries.items() if entry[2]}
        if not ranks:
            return native
        minimum = min(ranks.values())
        tied = [key for key, rank in ranks.items() if rank == minimum]
        if len(tied) == 1:
            return native
        bundle = _index(bundled)
        if any(key not in bundle or not bundle[key][2] for key in tied):
            return native
        bundled_ranks = {key: _rank(bundle[key][1]) for key in tied}
        best = min(bundled_ranks.values())
        winners = [key for key, rank in bundled_ranks.items() if rank == best]
        if len(winners) != 1:
            return native
        winner = winners[0]
        result = deepcopy(native)
        models = result["models"] if isinstance(result, dict) else result
        promoted = minimum - 1
        if math.isfinite(promoted) and promoted < minimum:
            models[entries[winner][0]]["priority"] = promoted
        else:
            # Extreme finite floats may not represent minimum - 1 distinctly.
            ordinal = {value: index + 1 for index, value in enumerate(sorted(set(ranks.values())))}
            for key, rank in ranks.items():
                models[entries[key][0]]["priority"] = 0 if key == winner else ordinal[rank]
        evidence = {"ranking_source": "installed_cli_priority_for_native_tie",
                    "availability_source": "native_debug_models", "model_attested": False,
                    "native_tied_model_ids": sorted(tied), "selected_model_id": winner,
                    "bundled_priorities": bundled_ranks}
        models[entries[winner][0]]["_codex_catalog_evidence"] = evidence
        if isinstance(result, dict):
            result["_codex_catalog_evidence"] = evidence
        return result
    except (TypeError, ValueError, OverflowError):
        return native
