"""Pure compatibility navigation derived only from supplied campaign records."""

from copy import deepcopy


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _proposal_key(event):
    version = event.get('version')
    if (not _text(event.get('proposal_id')) or not _text(event.get('proposal_hash'))
            or isinstance(version, bool) or not isinstance(version, int) or version < 1):
        return None
    return event['proposal_id'], event['proposal_hash'], version


def _confirmed_work_product(roadmap):
    """Only ordered, matching confirmation events establish a root label.

    A later unmatched confirmation clears the earlier candidate. Proposal
    `confirmed` flags and roadmap_projection do not establish confirmation.
    """
    if not isinstance(roadmap, dict) or not isinstance(roadmap.get('roadmap_events'), list):
        return None
    proposals = {}
    selected = None
    selected_key = None
    for event in roadmap['roadmap_events']:
        if not isinstance(event, dict):
            continue
        kind = event.get('kind')
        if kind == 'kickoff_proposal':
            key = _proposal_key(event)
            if key is None:
                continue
            product = event.get('work_product')
            if key in proposals and proposals[key] != product:
                # Conflicting records with the same claimed identity are not
                # enough evidence to choose either work product.
                proposals[key] = None
                if selected_key == key:
                    selected = None
                    selected_key = None
            elif key not in proposals:
                proposals[key] = product
        elif kind == 'kickoff_confirm':
            selected = None
            selected_key = None
            key = _proposal_key(event)
            product = proposals.get(key) if key is not None else None
            if (isinstance(product, dict) and _text(product.get('id'))
                    and _text(product.get('name'))):
                selected = product
                selected_key = key
    return deepcopy(selected)


def _confirmed_components(product):
    if not isinstance(product, dict) or not isinstance(product.get('components'), list):
        return []
    components = product['components']
    seen = {product['id'].casefold()}
    for component in components:
        if (not isinstance(component, dict) or not _text(component.get('id'))
                or not _text(component.get('name'))):
            return []
        key = component['id'].casefold()
        if key in seen:
            return []
        seen.add(key)
    return deepcopy(components)


def with_compat_navigation(map_data, roadmap=None):
    """Return a copy with explicit navigation or a shallow compatibility view.

    Explicit paths are authoritative, including intentionally empty paths.
    Otherwise confirmed components determine groups when available. A step
    with several component owners has one canonical root path and related
    paths for read-only references. This helper never creates campaign steps,
    changes ownership, or infers current/featured/acceptance state.
    Legacy records without unique IDs and names retain empty, unclassified
    paths. Existing support roles and other navigation metadata are preserved.
    """
    if not isinstance(map_data, dict):
        raise TypeError('Campaign map must be a dictionary.')
    steps = map_data.get('steps', [])
    if not isinstance(steps, list) or any(not isinstance(step, dict) for step in steps):
        raise ValueError('Campaign steps must be a list of dictionaries.')
    result = deepcopy(map_data)
    result.setdefault('steps', [])
    if any(isinstance(step.get('navigation'), dict)
           and 'path' in step['navigation'] for step in steps):
        result['navigation_mode'] = 'explicit'
        return result

    id_counts = {}
    for step in steps:
        if _text(step.get('id')):
            key = step['id'].casefold()
            id_counts[key] = id_counts.get(key, 0) + 1
    classified = [
        _text(step.get('id')) and _text(step.get('name'))
        and id_counts[step['id'].casefold()] == 1
        for step in steps
    ]
    stable_steps = [step for step, valid in zip(steps, classified) if valid]
    seen = {step['id'].casefold() for step in stable_steps}

    product = _confirmed_work_product(roadmap)
    root_id = product['id'] if product else 'compat-root'
    root_label = (product['name'] if product else
                  map_data['name'] if _text(map_data.get('name')) else 'Project work')
    components = _confirmed_components(product)
    groups = [{'id': root_id, 'label': root_label}]
    paths = {}
    if components:
        groups.extend({'id': component['id'], 'label': component['name']}
                      for component in components)
        valid_components = {component['id'] for component in components}
    else:
        # Derive presentation IDs from stable IDs, never from ordinal or label.
        prefix = 'compat-step:'
        while root_id.casefold().startswith(prefix.casefold()) and root_id[len(prefix):].casefold() in seen:
            prefix = 'compat-' + prefix
        for step in stable_steps:
            group_id = prefix + step['id']
            paths[step['id']] = [root_id, group_id]
            groups.append({'id': group_id, 'label': step['name']})

    for step, valid in zip(result['steps'], classified):
        navigation = step.get('navigation')
        navigation = deepcopy(navigation) if isinstance(navigation, dict) else {}
        for key in ('groups', 'include_paths', 'related_paths'):
            navigation.pop(key, None)
        navigation.setdefault('role', 'primary')
        if not valid:
            # Preserve the legacy record without inventing identity or merging
            # duplicate IDs. The renderer can show it as unclassified.
            navigation['path'] = []
        elif components:
            owners = []
            declared = step.get('component_ids', [])
            if isinstance(declared, list):
                for owner in declared:
                    if isinstance(owner, str) and owner in valid_components and owner not in owners:
                        owners.append(owner)
            navigation['path'] = [root_id, owners[0]] if len(owners) == 1 else [root_id]
            if len(owners) > 1:
                navigation['related_paths'] = [[root_id, owner] for owner in owners]
        else:
            navigation['path'] = paths[step['id']]
        step['navigation'] = navigation

    if result['steps']:
        first = result['steps'][0]['navigation']
        first['groups'] = deepcopy(groups)
        if components:
            first['include_paths'] = [[root_id, component['id']] for component in components]
    result['navigation_mode'] = 'fallback'
    result['navigation_fallback'] = {
        'id': root_id, 'label': root_label,
        'groups': deepcopy(groups), 'components': deepcopy(components),
    }
    return result


def resolve_step(steps, raw):
    """Resolve exact stable ID, then one-based ordinal, then unique name fragment.

    Returns the existing step dictionary without modifying it. An ambiguous
    exact ID or name fragment returns None; ordinal matching never outranks ID.
    """
    if (not isinstance(steps, (list, tuple)) or isinstance(raw, bool)
            or not isinstance(raw, (str, int))):
        return None
    token = str(raw).strip()
    if not token:
        return None
    folded = token.casefold()
    def stable(candidate):
        if not isinstance(candidate, dict) or not _text(candidate.get('id')):
            return None
        identity = candidate['id'].casefold()
        owners = [s for s in steps if isinstance(s, dict)
                  and isinstance(s.get('id'), str) and s['id'].casefold() == identity]
        return candidate if len(owners) == 1 else None
    matches = [step for step in steps if isinstance(step, dict)
               and isinstance(step.get('id'), str) and step['id'].casefold() == folded]
    if matches:
        return stable(matches[0]) if len(matches) == 1 else None
    if token.isascii() and token.isdigit():
        digits = token.lstrip('0') or '0'
        if len(digits) <= len(str(len(steps))):
            ordinal = int(digits)
            if 1 <= ordinal <= len(steps):
                step = steps[ordinal - 1]
                return stable(step)
    matches = [step for step in steps if isinstance(step, dict)
               and isinstance(step.get('name'), str) and folded in step['name'].casefold()]
    return stable(matches[0]) if len(matches) == 1 else None
