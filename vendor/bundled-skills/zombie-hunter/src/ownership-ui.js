// W10 / P7 — Ownership badge UI contract on radar.
//
// Rules:
//   - Every candidate tile exposes ownership badge fields (owned/keep/failClosed/label/…).
//   - Freeze and Kill controls are HIDDEN when the candidate is Anchor-owned,
//     ownership fail-closed KEEP, or ownership.keep is true.
//   - Observe-only / shadow and freezeKillEnabled=false also hide destructive actions.
//
// B6 W2: Extra ceremony chrome (panels / non-decision banners / explain verbosity)
// may be thinned by ceremonyLevel. Ownership badge + Freeze/Kill visibility are
// SAFETY / decision chrome — never thinned by LITE ceremony.

const { buildOwnershipBadge } = require('./ownership.js');
const { OWNERSHIP_BADGE_FIELDS } = require('./skill-contract.js');

/**
 * B6 ceremony ordinal for optional extra chrome (not Freeze/Kill, not badge).
 * lite=0, spike-first=1, full=2. Unknown → 0 (lean).
 * @param {unknown} level
 * @returns {number}
 */
function ceremonyOrdinal(level) {
  if (level == null) return 2; // default full chrome when unset (backward compatible)
  const key = String(level).trim().toLowerCase().replace(/_/g, '-');
  if (key === 'lite' || key === 'light') return 0;
  if (key === 'spike-first' || key === 'spike' || key === 'spikefirst') return 1;
  if (key === 'full') return 2;
  return 0;
}

/**
 * Whether optional ceremony chrome (extra panels / banners / verbose explain)
 * should render. Never gates Freeze/Kill or ownership badge visibility.
 * @param {object} [opts]
 * @returns {boolean}
 */
function shouldShowCeremonyChrome(opts = {}) {
  if (opts.ceremonyLevel == null && opts.ceremony == null) return true;
  const ord = ceremonyOrdinal(opts.ceremonyLevel != null ? opts.ceremonyLevel : opts.ceremony);
  // LITE: no extra panels/banners; FULL: all ceremony chrome.
  return ord >= 2 ? true : ord >= 1 ? opts.kind !== 'extra_ui_panel' : false;
}

/**
 * Normalize ownership badge from candidate / group shape.
 * @param {object} candidate
 * @returns {object|null}
 */
function resolveOwnershipBadge(candidate) {
  if (!candidate || typeof candidate !== 'object') return null;
  if (candidate.ownershipBadge && typeof candidate.ownershipBadge === 'object') {
    return candidate.ownershipBadge;
  }
  if (candidate.ownership && typeof candidate.ownership === 'object') {
    if (candidate.ownership.label != null || candidate.ownership.owned != null) {
      return candidate.ownership.badge
        || buildOwnershipBadge(candidate.ownership);
    }
  }
  return null;
}

/**
 * True when process must KEEP and never show Freeze/Kill.
 * @param {object|null} badgeOrOwnership
 */
function isOwnedKeep(badgeOrOwnership) {
  if (!badgeOrOwnership || typeof badgeOrOwnership !== 'object') return false;
  return !!(
    badgeOrOwnership.owned
    || badgeOrOwnership.keep
    || badgeOrOwnership.failClosed
  );
}

/**
 * Whether Freeze/Kill action chrome may be shown on a radar tile.
 *
 * @param {object} candidate — group or engine row
 * @param {object} [opts]
 * @param {boolean} [opts.freezeKillEnabled]
 * @param {boolean} [opts.observeOnly]
 * @param {string} [opts.kind] — 'zombie' | 'active' | 'observe'
 * @returns {boolean}
 */
function shouldShowFreezeKill(candidate, opts = {}) {
  if (opts.freezeKillEnabled !== true) return false;
  if (opts.observeOnly === true) return false;
  if (opts.kind === 'observe' || opts.kind === 'active') return false;
  // Only zombie-shaped tiles may ever show Freeze/Kill
  if (opts.kind != null && opts.kind !== 'zombie') return false;

  const badge = resolveOwnershipBadge(candidate);
  if (isOwnedKeep(badge)) return false;
  if (isOwnedKeep(candidate && candidate.ownership)) return false;

  return true;
}

/**
 * Ownership badge UI contract for a single tile.
 * Named gate: test_ownership_badge_ui_contract
 *
 * @param {object} candidate
 * @param {object} [opts]
 * @returns {object}
 */
function ownershipBadgeUiContract(candidate, opts = {}) {
  const badge = resolveOwnershipBadge(candidate);
  const ownedKeep = isOwnedKeep(badge) || isOwnedKeep(candidate && candidate.ownership);
  const freezeKillVisible = shouldShowFreezeKill(candidate, opts);
  // Ceremony chrome is separate from decision chrome (badge + freeze/kill).
  const ceremonyChromeVisible = shouldShowCeremonyChrome(opts);
  const missingFields = [];
  if (badge) {
    for (const f of OWNERSHIP_BADGE_FIELDS) {
      if (!Object.prototype.hasOwnProperty.call(badge, f)
        && f !== 'reasonCodes' /* optional empty */) {
        // reasonCodes may be absent on minimal badges; require core fields
      }
    }
    for (const f of ['owned', 'keep', 'failClosed', 'label']) {
      if (!Object.prototype.hasOwnProperty.call(badge, f)) missingFields.push(f);
    }
  }

  return {
    ok: badge != null && missingFields.length === 0 && (ownedKeep ? !freezeKillVisible : true),
    ownershipBadgeVisible: badge != null,
    badge,
    ownedKeep,
    freezeKillVisible,
    freezeKillHiddenWhenOwned: ownedKeep ? freezeKillVisible === false : true,
    ceremonyChromeVisible,
    missingFields,
    label: badge && badge.label != null ? String(badge.label) : null,
    contractVersion: 'w10-ownership-badge-ui-v1',
  };
}

/**
 * Assert ownership UI contract over a list of radar tiles.
 * @param {object[]} tiles
 * @param {object} [opts]
 * @returns {{ ok: boolean, failures: string[], results: object[] }}
 */
function assertOwnershipBadgeUiContract(tiles, opts = {}) {
  const list = Array.isArray(tiles) ? tiles : [];
  const failures = [];
  const results = [];
  for (const t of list) {
    const c = ownershipBadgeUiContract(t, {
      freezeKillEnabled: opts.freezeKillEnabled === true,
      observeOnly: opts.observeOnly === true,
      kind: t.kind || opts.kind || 'zombie',
    });
    results.push(c);
    if (!c.ownershipBadgeVisible) {
      failures.push(`missing_badge:${t.id || t.pid || t.name || '?'}`);
    }
    if (c.ownedKeep && c.freezeKillVisible) {
      failures.push(`freeze_kill_visible_when_owned:${t.id || t.pid || t.name || '?'}`);
    }
    if (c.missingFields.length) {
      failures.push(`badge_fields_missing:${c.missingFields.join(',')}`);
    }
  }
  return { ok: failures.length === 0, failures, results };
}

/**
 * HTML fragment helpers for radar (server uses these for parity with contract).
 * @param {object|null} badge
 * @param {(s: string) => string} esc
 */
function renderOwnershipBadgeChipHtml(badge, esc) {
  if (!badge) return '';
  const label = badge.label
    || (badge.owned || badge.keep ? 'Anchor-owned' : 'not owned');
  const ownedClass = (badge.owned || badge.keep || badge.failClosed) ? ' owned' : '';
  return `<span class="chip age ownership-badge${ownedClass}" data-owned="${badge.owned ? '1' : '0'}" data-keep="${badge.keep ? '1' : '0'}" data-fail-closed="${badge.failClosed ? '1' : '0'}">${esc(label)}</span>`;
}

/**
 * Build acts HTML: Freeze/Kill only when shouldShowFreezeKill.
 * @param {object} g — tile group
 * @param {object} opts
 * @param {(s: string) => string} esc
 */
function renderTileActsHtml(g, opts, esc) {
  const show = shouldShowFreezeKill(g, opts);
  if (show) {
    return `<div class="acts">
        <button class="btn freeze" onclick="doFreeze('${esc(g.id)}', ${JSON.stringify(g.pids)})">Freeze (reversible)</button>
        <button class="btn reap" onclick="doKill('${esc(g.id)}', ${JSON.stringify(g.pids)}, '${esc(g.name)}')">Kill — stop the spend</button>
        <button class="btn" onclick="why(this)">Why?</button>
      </div>`;
  }
  const ownBadge = resolveOwnershipBadge(g);
  const chip = ownBadge && isOwnedKeep(ownBadge)
    ? 'ownership KEEP · Freeze/Kill hidden'
    : (opts.observeOnly ? 'observe-only · shadow' : 'actions disabled');
  return `<div class="acts">
        <button class="btn" onclick="why(this)">Why?</button>
        <span class="chip age">${esc(chip)}</span>
      </div>`;
}

/**
 * Plumb ownership onto a grouped tile from member engines.
 * Prefer any owned/fail-closed badge in the group (KEEP wins).
 * @param {object} group
 * @param {object[]} members
 */
function attachOwnershipToGroup(group, members) {
  if (!group || typeof group !== 'object') return group;
  const list = Array.isArray(members) ? members : [];
  let chosen = null;
  for (const m of list) {
    const b = resolveOwnershipBadge(m);
    if (!b) continue;
    if (isOwnedKeep(b)) {
      chosen = b;
      break;
    }
    if (!chosen) chosen = b;
  }
  if (chosen) {
    group.ownershipBadge = chosen;
    group.ownership = {
      owned: !!chosen.owned,
      keep: !!chosen.keep,
      failClosed: !!chosen.failClosed,
      label: chosen.label,
      reasonCodes: (chosen.reasonCodes || []).slice(),
      stub: chosen.stub,
      stubMaxWave: chosen.stubMaxWave,
    };
  }
  return group;
}

module.exports = {
  resolveOwnershipBadge,
  isOwnedKeep,
  shouldShowFreezeKill,
  shouldShowCeremonyChrome,
  ceremonyOrdinal,
  ownershipBadgeUiContract,
  assertOwnershipBadgeUiContract,
  renderOwnershipBadgeChipHtml,
  renderTileActsHtml,
  attachOwnershipToGroup,
  OWNERSHIP_BADGE_FIELDS,
};
