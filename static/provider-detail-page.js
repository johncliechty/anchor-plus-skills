/* Single-Provider Detail, Mothership Auto-Discovery, OS Vault & Usage Page. */
(function () {
  'use strict';
  const FAMILIES = ['claude', 'gemini', 'chatgpt', 'grok'];
  const SHORT_NAMES = { claude: 'Claude', gemini: 'Gemini', chatgpt: 'ChatGPT / Codex', grok: 'Grok (xAI)' };
  let activeFamily = 'claude';
  let switchSectionFn = null;
  let lastNotice = '';
  let lastError = '';

  function el(tag, txt, cls) {
    const n = document.createElement(tag);
    if (txt !== undefined && txt !== null) n.textContent = String(txt);
    if (cls) n.className = cls;
    return n;
  }

  async function fetchDetail(family) {
    const api = window.AnchorProviders;
    try {
      return await api.request('/api/provider-setup/detail?family=' + encodeURIComponent(family));
    } catch (err) {
      if (err && err.status === 404) {
        return await api.request('/api/provider-setup?detail=1&family=' + encodeURIComponent(family));
      }
      throw err;
    }
  }

  async function postDetail(subpath, fallbackAction, payload) {
    const api = window.AnchorProviders;
    try {
      return await api.request('/api/provider-setup/' + subpath, payload);
    } catch (err) {
      if (err && err.status === 404) {
        return await api.request('/api/provider-setup/apply', Object.assign({ detail_action: fallbackAction }, payload));
      }
      throw err;
    }
  }

  function updateUrl(sectionName, family) {
    try {
      const u = new URL(location.href);
      u.searchParams.set('section', sectionName);
      if (family) u.searchParams.set('family', family);
      history.replaceState(null, '', u.pathname + '?' + u.searchParams.toString());
    } catch (_) {}
  }

  function backToStage2() {
    lastNotice = '';
    lastError = '';
    updateUrl('providers', activeFamily);
    if (typeof switchSectionFn === 'function') {
      switchSectionFn('providers');
    } else {
      const p = document.getElementById('setup-section-providers');
      const d = document.getElementById('setup-section-provider-detail');
      if (d) d.hidden = true;
      if (p) p.hidden = false;
    }
  }

  function addKv(dl, key, valNodeOrStr, ddClass) {
    const dt = el('dt', key);
    const dd = document.createElement('dd');
    if (ddClass) dd.className = ddClass;
    if (valNodeOrStr instanceof Node) dd.append(valNodeOrStr);
    else dd.textContent = String(valNodeOrStr ?? '');
    dl.append(dt, dd);
  }

  function buildAllowanceBox(title, winObj) {
    const box = el('div', null, 'pd-ubox');
    const top = el('div', null, 'wave2-matrix-top');
    top.append(el('strong', title));
    const pct = (winObj && typeof winObj.remaining_percent === 'number') ? Math.max(0, Math.min(100, Math.round(winObj.remaining_percent))) : null;
    const rst = (winObj && winObj.reset_text) ? winObj.reset_text : 'Not published by CLI';
    top.append(el('span', pct !== null ? (pct + '% remaining · resets ' + rst) : ('Quota % unreported · ' + rst), 'small muted'));
    box.append(top);
    const meter = el('div', null, 'provider-meter');
    meter.style.marginTop = '6px';
    const fill = document.createElement('span');
    fill.style.width = (pct !== null ? pct : 0) + '%';
    if (pct !== null && pct <= 20) fill.style.background = 'var(--ps-amber)';
    meter.append(fill);
    box.append(meter);
    return box;
  }

  function renderErrorState(root, family, err) {
    root.replaceChildren();
    const hdr = el('div', null, 'pd-hdr');
    const titleRow = el('div', null, 'pd-title-row');
    const backBtn = el('button', '← Setup Stage 2 (All Providers)');
    backBtn.type = 'button';
    backBtn.id = 'btnBackStage2';
    backBtn.onclick = backToStage2;
    titleRow.append(backBtn, el('h2', SHORT_NAMES[family] || family), el('span', '⚠ ' + (err.badge || 'UNAVAILABLE'), 'w3-badge w3-badge-amber'));
    hdr.append(titleRow);
    const card = el('article', null, 'setup-card');
    card.append(el('h3', 'Provider Detail Unavailable'), el('p', err.message || 'Unable to load provider detail.', 'error'));
    root.append(hdr, card);
  }

  function renderDetail(detail) {
    const root = document.getElementById('provider-detail-root');
    if (!root || !detail) return;
    root.replaceChildren();
    const fam = detail.family || activeFamily;
    const sub = detail.subscription || {};
    const cli = sub.cli || {};
    const scan = sub.mothership_scan || {};
    const role = sub.role || {};
    const vault = detail.vault || {};
    const allow = detail.allowance || {};
    const usage = detail.usage || {};

    const hdr = el('div', null, 'pd-hdr');
    const titleRow = el('div', null, 'pd-title-row');
    const backBtn = el('button', '← Setup Stage 2 (All Providers)');
    backBtn.type = 'button';
    backBtn.id = 'btnBackStage2';
    backBtn.onclick = backToStage2;
    const badgeCls = 'w3-badge ' + (detail.warn ? 'w3-badge-amber' : 'w3-badge-emerald');
    const statusBadge = el('span', (detail.warn ? '⚠ ' : '● ') + (detail.status || detail.badge || 'Ready'), badgeCls);
    statusBadge.id = 'pd-status-chip';
    titleRow.append(backBtn, el('h2', detail.name || SHORT_NAMES[fam] || fam), statusBadge);

    const rightControls = el('div', null, 'setup-actions');
    rightControls.style.margin = '0';
    FAMILIES.forEach(k => {
      const pill = el('button', SHORT_NAMES[k], 'btn-mini' + (k === fam ? ' btn-amber' : ''));
      pill.type = 'button';
      pill.dataset.detailFamilyTab = k;
      pill.onclick = () => open(k, switchSectionFn);
      rightControls.append(pill);
    });
    const testBtn = el('button', '⚡ Test Live Connection', 'primary');
    testBtn.type = 'button';
    testBtn.dataset.actTest = fam;
    testBtn.onclick = async () => {
      testBtn.disabled = true;
      lastError = '';
      try {
        const next = await postDetail('probe-mothership', 'probe_mothership', { family: fam });
        lastNotice = 'Probed ' + (next.name || fam) + ' on Mothership (' + ((next.probe && next.probe.auth) || 'checked') + ').';
        renderDetail(next);
      } catch (e) {
        lastError = e.message || 'Live connection probe failed.';
        renderDetail(detail);
      } finally {
        testBtn.disabled = false;
      }
    };
    rightControls.append(testBtn);
    hdr.append(titleRow, rightControls);
    root.append(hdr);

    if (lastNotice) {
      const note = el('p', '✓ ' + lastNotice, 'setup-notice usable');
      note.id = 'pd-toast-notice';
      root.append(note);
    }
    if (lastError) {
      const errP = el('p', '⚠ ' + lastError, 'setup-notice error');
      errP.id = 'pd-toast-error';
      root.append(errP);
    }

    if (detail.status_kind === 'empty-but-valid') {
      const emptyCard = el('article', null, 'setup-card');
      emptyCard.append(el('h3', 'No Configured Provider Connections'), el('p', detail.message || 'Provider store is empty.', 'muted'));
      root.append(emptyCard);
      return;
    }

    const grid = el('div', null, 'pd-grid');

    // Card 1: Subscription & Mothership Auto-Discovery
    const c1 = el('article', null, 'setup-card');
    c1.id = 'pd-card-mothership';
    const c1Top = el('div', null, 'wave2-matrix-top');
    c1Top.append(el('h3', '1 · Subscription & Mothership Auto-Discovery'), el('span', 'Recommended', 'w3-badge w3-badge-sky'));
    const dl1 = el('dl', null, 'pd-kv');
    addKv(dl1, 'Subscription Status', sub.sub_account_text || 'Unchecked');
    addKv(dl1, 'Mothership CLI', el('code', cli.display || 'Not installed'));
    addKv(dl1, 'Mothership Scan', scan.summary || 'Click below to check signed-in Mothership session', scan.found ? 'usable' : 'muted');
    addKv(dl1, 'Assigned Role', (role.label || 'Seat') + ' (' + (role.model || 'latest_supported') + ')');
    const c1Btns = el('div', null, 'setup-actions');
    const adoptBtn = el('button', '🔍 Use Signed-In Subscription from Mothership', 'primary');
    adoptBtn.type = 'button';
    adoptBtn.id = 'btnAdoptMothership';
    adoptBtn.dataset.actDiscover = fam;
    adoptBtn.onclick = async () => {
      adoptBtn.disabled = true;
      lastError = '';
      try {
        const next = await postDetail('adopt-mothership', 'adopt_mothership', { family: fam });
        lastNotice = 'Adopted signed-in Mothership subscription for ' + (next.name || fam) + '.';
        if (window.parent !== window) {
          try { window.parent.postMessage({ type: 'anchor-setup-saved' }, location.origin); } catch (_) {}
        }
        renderDetail(next);
      } catch (e) {
        lastError = e.message || 'Mothership subscription adoption failed.';
        renderDetail(detail);
      } finally {
        adoptBtn.disabled = false;
      }
    };
    const signBtn = el('button', '🔐 Sign In / Switch Subscription Account');
    signBtn.type = 'button';
    signBtn.dataset.actLogin = fam;
    signBtn.onclick = async () => {
      lastError = '';
      try {
        const res = await window.AnchorProviders.request('/api/onboard-wizard/action', { action: 'launch_service_login', family: fam });
        lastNotice = res.message || ('Launched native subscription sign-in for ' + fam + ' on Mothership.');
        renderDetail(detail);
      } catch (e) {
        lastError = e.message || 'Unable to launch sign-in flow.';
        renderDetail(detail);
      }
    };
    c1Btns.append(adoptBtn, signBtn);
    c1.append(c1Top, dl1, c1Btns);
    if (detail.passive_auth_unknown) {
      c1.append(el('p', 'Honest capability note: agy CLI exposes no passive account/auth report; Anchor never submits a billable turn during status reads.', 'small muted'));
    }

    // Card 2: API Key & OS Credential Vault
    const c2 = el('article', null, 'setup-card');
    c2.id = 'pd-card-vault';
    const c2Top = el('div', null, 'wave2-matrix-top');
    c2Top.append(el('h3', '2 · API Key & OS Credential Vault'), el('span', 'advapi32 Encrypted', 'w3-badge'));
    const dl2 = el('dl', null, 'pd-kv');
    addKv(dl2, 'Vault API Key', vault.status_text || 'Not stored');

    const modeWrap = document.createElement('div');
    ['subscription', 'api_key'].forEach(modeVal => {
      const lbl = el('label', null, 'w3-checkbox-label');
      lbl.style.marginRight = '14px';
      const radio = document.createElement('input');
      radio.type = 'radio';
      radio.name = 'pd-billing-mode';
      radio.value = modeVal;
      radio.checked = detail.billing_mode === modeVal;
      radio.onchange = async () => {
        if (!radio.checked) return;
        lastError = '';
        try {
          const next = await postDetail('billing-mode', 'billing_mode', { family: fam, billing_mode: modeVal });
          lastNotice = 'Set active billing mode to ' + (modeVal === 'subscription' ? 'Subscription Seat' : 'API Key Billing') + '.';
          renderDetail(next);
        } catch (e) {
          lastError = e.message || 'Billing mode switch refused.';
          renderDetail(detail);
        }
      };
      lbl.append(radio, el('span', modeVal === 'subscription' ? 'Subscription Seat' : 'API Key Billing'));
      modeWrap.append(lbl);
    });
    addKv(dl2, 'Active Billing Mode', modeWrap);

    const keyRow = el('div', null, 'w3-form-row');
    const keyInput = document.createElement('input');
    keyInput.type = 'password';
    keyInput.id = 'pd-vault-api-key';
    keyInput.autocomplete = 'off';
    keyInput.placeholder = 'Paste API key to store/rotate in OS Vault...';
    keyInput.style.flex = '1';
    const saveKeyBtn = el('button', '🔑 Validate & Save to Vault', 'btn-amber');
    saveKeyBtn.type = 'button';
    saveKeyBtn.id = 'btnSaveVaultKey';
    saveKeyBtn.disabled = !vault.client_can_enter_api || !vault.available;
    saveKeyBtn.onclick = async () => {
      const val = (keyInput.value || '').trim();
      if (!val) { lastError = 'Paste an API key first.'; renderDetail(detail); return; }
      keyInput.value = '';
      saveKeyBtn.disabled = true;
      lastError = '';
      try {
        const next = await postDetail('billing-mode', 'save_api_key', { family: fam, billing_mode: detail.billing_mode || 'subscription', api_key: val });
        lastNotice = 'Validated & stored API key in OS Credential Vault (' + ((next.vault && next.vault.masked_key) || 'masked') + ').';
        renderDetail(next);
      } catch (e) {
        lastError = e.message || 'API key validation failed.';
        renderDetail(detail);
      } finally {
        saveKeyBtn.disabled = false;
      }
    };
    keyRow.append(keyInput, saveKeyBtn);
    c2.append(c2Top, dl2, keyRow, el('p', 'Raw keys never touch JSON files or browser responses; validation runs a zero-token model-catalog GET on the Mothership.', 'small muted'));

    // Card 3: Current Usage, Rate-Limit Allowance & Spend Attribution
    const c3 = el('article', null, 'setup-card pd-full');
    c3.id = 'pd-card-usage';
    const c3Top = el('div', null, 'wave2-matrix-top');
    c3Top.append(el('h3', '3 · Current Usage, Rate-Limit Allowance & Spend Attribution'), el('span', 'Auto-refreshed every 15m + on every CLI turn', 'w3-badge w3-badge-sky'));
    const ubars = el('div', null, 'pd-ubars');
    ubars.append(buildAllowanceBox('5-Hour Burst Allowance', allow.window_5h), buildAllowanceBox('7-Day Rolling Allowance', allow.window_7d));
    const dl3 = el('dl', null, 'pd-kv');
    addKv(dl3, '7-Day Anchor Usage', (usage.window_7d && usage.window_7d.display) || '0 tokens (~$0.00 API-equiv)');
    addKv(dl3, '30-Day Anchor Usage', (usage.window_30d && usage.window_30d.display) || '0 tokens (~$0.00 API-equiv)');
    addKv(dl3, 'Top Cockpits (7d)', usage.top_cockpits_text || 'No recorded cockpit turns in last 7d');
    c3.append(c3Top, ubars, dl3);

    grid.append(c1, c2, c3);
    root.append(grid);
  }

  async function open(family, sectionSwitcher) {
    if (typeof sectionSwitcher === 'function') switchSectionFn = sectionSwitcher;
    const norm = String(family || activeFamily || 'claude').trim().toLowerCase();
    activeFamily = FAMILIES.includes(norm) ? norm : 'claude';
    lastNotice = '';
    lastError = '';
    updateUrl('provider-detail', activeFamily);
    if (typeof switchSectionFn === 'function') {
      switchSectionFn('provider-detail', true);
    } else {
      ['host', 'providers', 'chart', 'comms'].forEach(s => { const n = document.getElementById('setup-section-' + s); if (n) n.hidden = true; });
      const d = document.getElementById('setup-section-provider-detail');
      if (d) d.hidden = false;
    }
    const root = document.getElementById('provider-detail-root');
    if (root) root.replaceChildren(el('p', 'Loading ' + (SHORT_NAMES[activeFamily] || activeFamily) + ' credentials & usage…', 'muted'));
    try {
      const detail = await fetchDetail(activeFamily);
      renderDetail(detail);
      return detail;
    } catch (err) {
      if (root) renderErrorState(root, activeFamily, err);
      return null;
    }
  }

  window.AnchorProviderDetail = { open, refresh: () => open(activeFamily, switchSectionFn), backToStage2 };
  const initParams = new URLSearchParams(location.search);
  if (initParams.get('section') === 'provider-detail') {
    open(initParams.get('family') || 'claude');
  }
})();
