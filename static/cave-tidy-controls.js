/* Cave of Wonders Tidy Controls (2026-11-24):
   1. Light vs. Dark theme toggle (upper right next to Steward identifier, matching Skill Foundry palette).
   2. AI Cockpits summary tile (Active · On Deck · In Reserve, closed by default; opens shelves + expandable Reserve bar).
   3. Email & Calendar Services expandable status bar inside #calBody. */
(function () {
  'use strict';

  var THEME_KEY = 'anchor_cave_theme';

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function currentTheme() {
    try {
      return localStorage.getItem(THEME_KEY) === 'light' ? 'light' : 'dark';
    } catch (_) {
      return document.documentElement.getAttribute('data-cave-theme') === 'light' ? 'light' : 'dark';
    }
  }

  function syncEmbeddedFrames(theme) {
    var frames = document.querySelectorAll('iframe.cview-frame, .tile iframe');
    frames.forEach(function (fr) {
      try {
        if (fr.contentDocument && fr.contentDocument.documentElement) {
          if (theme === 'light') {
            fr.contentDocument.documentElement.setAttribute('data-cave-theme', 'light');
          } else {
            fr.contentDocument.documentElement.removeAttribute('data-cave-theme');
          }
        }
        if (fr.contentWindow) {
          fr.contentWindow.postMessage({ type: 'anchor-cave-theme', theme: theme }, location.origin);
        }
      } catch (_) {}
    });
  }

  function applyTheme(theme, persist) {
    var isLight = theme === 'light';
    if (isLight) {
      document.documentElement.setAttribute('data-cave-theme', 'light');
    } else {
      document.documentElement.removeAttribute('data-cave-theme');
    }
    if (persist) {
      try { localStorage.setItem(THEME_KEY, isLight ? 'light' : 'dark'); } catch (_) {}
    }
    var btn = document.getElementById('caveThemeToggle');
    var ico = document.getElementById('caveThemeIcon');
    var lbl = document.getElementById('caveThemeLabel');
    if (btn) {
      btn.setAttribute('aria-pressed', isLight ? 'true' : 'false');
      btn.classList.toggle('is-light', isLight);
    }
    if (ico) ico.innerHTML = isLight ? '&#127769;' : '&#9728;';
    if (lbl) lbl.textContent = isLight ? 'Dark' : 'Light';
    syncEmbeddedFrames(isLight ? 'light' : 'dark');
  }

  function setCockpitsHubOpen(open) {
    var hub = document.getElementById('caveCockpitsTile');
    var btn = document.getElementById('caveCockpitsToggle');
    var body = document.getElementById('caveCockpitsBody');
    var tog = document.getElementById('caveCockpitsTog');
    if (!hub || !body) return;
    var isOpen = Boolean(open);
    hub.classList.toggle('open', isOpen);
    body.hidden = !isOpen;
    if (btn) btn.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    if (tog) tog.textContent = isOpen ? 'Collapse' : 'Expand';
    if (isOpen && typeof window._caveWarmActiveIfVisible === 'function') {
      window._caveWarmActiveIfVisible();
    }
  }

  function syncReserveTogLabel() {
    var det = document.getElementById('candsTile');
    var lbl = det && det.querySelector('.cands-tog-lbl');
    if (det && lbl) lbl.textContent = det.open ? 'Collapse' : 'Expand';
  }

  function syncAfterMorph(doc) {
    if (!doc) return;
    ['ckCntActive', 'ckCntDeck', 'ckCntReserve'].forEach(function (id) {
      var a = document.getElementById(id), b = doc.getElementById(id);
      if (a && b) a.textContent = b.textContent;
    });
    var shActiveCnt = document.querySelector('#shActive > .shelf-h .c');
    var freshActiveCnt = doc.querySelector('#shActive > .shelf-h .c');
    if (shActiveCnt && freshActiveCnt) shActiveCnt.textContent = freshActiveCnt.textContent;
    var shDeckCnt = document.querySelector('#shDeck > .shelf-h .c');
    var freshDeckCnt = doc.querySelector('#shDeck > .shelf-h .c');
    if (shDeckCnt && freshDeckCnt) shDeckCnt.textContent = freshDeckCnt.textContent;
    syncReserveTogLabel();
    syncEmbeddedFrames(currentTheme());
  }

  function renderCommsServicesBar(d) {
    if (!d || !Array.isArray(d.accounts)) return;
    var bar = document.getElementById('caveCommsServicesBar');
    var dot = document.getElementById('caveCommsServicesDot');
    var pill = document.getElementById('caveCommsServicesStatusPill');
    var namesEl = document.getElementById('caveCommsServicesNames');
    var rowsHost = document.getElementById('caveConnectedAccountsBar');
    if (!rowsHost) return;

    var rowsHtml = [];
    var names = [];
    var okN = 0;
    var totalN = 0;

    d.accounts.forEach(function (a) {
      if (!a || !a.id) return;
      totalN += 1;
      var aid = esc(a.id);
      var albl = esc(a.label || a.family || 'Service');
      names.push(albl);
      var aem = esc(a.email || 'Calendar ICS');
      var astat = String(a.status || 'configured').toLowerCase();
      var famL = String(a.family || 'gmail').toLowerCase();
      var amode = String(a.auth_mode || '').toLowerCase();
      var hasIcs = Boolean(String(a.ics_url || '').trim()) || famL === 'outlook';
      var noteTip = esc(String(a.last_imap_note || a.last_ics_note || '').slice(0, 180));
      var mailSyncErr = String(a.mail_sync_state || '').toLowerCase() === 'sync_error'
        || Boolean(d.provider_states && d.provider_states[a.id] && d.provider_states[a.id].mail === 'unknown');
      var isDegraded = astat === 'paused_safety' || astat === 'auth_error' || astat === 'error' || astat === 'disconnected' || mailSyncErr;
      if (!isDegraded) okN += 1;
      var tone = (astat === 'auth_error' || astat === 'error' || astat === 'disconnected') ? 'red' : (isDegraded ? 'amber' : 'emerald');

      var mailPill = amode === 'ics_only'
        ? '<span class="comms-pill sky">Email: ICS Only</span>'
        : (astat === 'paused_safety'
            ? '<span class="comms-pill amber">Email: Paused</span>'
            : (mailSyncErr
                ? '<span class="comms-pill amber" title="' + esc(String(a.last_sync_error || a.last_imap_note || 'IMAP sync delayed')) + '">Email: Sync Delayed (Retrying)</span>'
                : (isDegraded
                    ? '<span class="comms-pill red">Email: Needs Sign-In</span>'
                    : '<span class="comms-pill emerald">Email: Connected</span>')));
      var calPill = astat === 'paused_safety'
        ? '<span class="comms-pill amber">Calendar: Paused</span>'
        : ((tone === 'red' && !hasIcs)
            ? '<span class="comms-pill red">Calendar: Needs Auth</span>'
            : ((hasIcs || !isDegraded)
                ? '<span class="comms-pill emerald">Calendar: Synced</span>'
                : '<span class="comms-pill sky">Calendar: Optional</span>'));

      var fixBtn = '';
      if (astat === 'paused_safety') {
        fixBtn = '<button type="button" class="mini" data-comms-ms-device-auth="' + aid + '" data-comms-ms-email="' + aem + '" data-comms-ms-label="' + albl + '" title="Sign in safely with Microsoft 365 + 2FA">&#128273; Microsoft 365 2FA</button>'
          + '<button type="button" class="mini" data-comms-auto-outlook="1" title="Read from Windows Desktop Outlook">&#128187; Local Outlook</button>';
      } else if (astat === 'auth_error') {
        fixBtn = famL === 'outlook'
          ? '<button type="button" class="mini" data-comms-ms-device-auth="' + aid + '" data-comms-ms-email="' + aem + '" data-comms-ms-label="' + albl + '" title="Sign in with Microsoft 365 + 2FA">&#128273; Sign In (2FA)</button>'
          : '<button type="button" class="mini" data-comms-gmail-2fa="' + aid + '" data-comms-edit-account="' + aid + '" data-comms-edit-email="' + aem + '" data-comms-edit-label="' + albl + '" data-comms-edit-family="' + esc(famL) + '" title="Trigger Google 2FA prompt on your phone">&#128273; Authenticate 2FA</button>';
      }
      var editBtn = '<button type="button" class="mini" data-comms-edit-account="' + aid + '" data-comms-edit-email="' + aem + '" data-comms-edit-label="' + albl + '" data-comms-edit-family="' + esc(famL) + '" title="Update credentials for ' + aem + '">&#9998; Credentials</button>';
      var rmBtn = '<button type="button" class="mini" data-comms-remove-id="' + aid + '" title="Disconnect ' + albl + '">&times;</button>';

      rowsHtml.push(
        '<div class="cave-svc-row is-' + tone + '" data-svc-account-id="' + aid + '" title="' + noteTip + '">'
        + '<span class="cave-svc-dot ' + tone + '"></span>'
        + '<div class="cave-svc-ident"><b>' + albl + '</b><span>' + aem + '</span></div>'
        + '<div class="cave-svc-pills">' + mailPill + calPill + '</div>'
        + '<div class="cave-svc-acts">' + fixBtn + editBtn + rmBtn + '</div>'
        + '</div>'
      );
    });

    rowsHost.innerHTML = rowsHtml.length
      ? rowsHtml.join('')
      : '<div class="tw-empty">No connected accounts yet &mdash; use + Connect Account below.</div>';

    var badN = Math.max(0, totalN - okN);
    var barTone = (totalN === 0 || okN === 0) ? 'red' : (badN > 0 ? 'amber' : 'emerald');
    var badgeTxt = totalN === 0
      ? '0 Connected'
      : (okN === 0
          ? ('0/' + totalN + ' Healthy \u00b7 Needs Sign-In')
          : (badN > 0 ? (okN + '/' + totalN + ' Connected \u00b7 ' + badN + ' Attention') : (okN + '/' + totalN + ' Connected')));

    if (bar) {
      bar.classList.remove('is-emerald', 'is-amber', 'is-red');
      bar.classList.add('is-' + barTone);
    }
    if (dot) dot.className = 'cave-svc-dot ' + barTone;
    if (pill) {
      pill.className = 'comms-pill ' + barTone;
      pill.textContent = badgeTxt;
    }
    if (namesEl) {
      namesEl.innerHTML = totalN > 0
        ? names.slice(0, 4).join(' &middot; ')
        : 'No external Email or Calendar service connected yet &mdash; click to connect';
    }
    if (totalN > 0 && badN === 0) {
      var devBox = document.getElementById('caveCommsDeviceFlowBox');
      if (devBox) devBox.hidden = true;
    }
  }

  document.addEventListener('click', function (e) {
    var themeBtn = e.target.closest && e.target.closest('[data-cave-theme-toggle]');
    if (themeBtn) {
      e.preventDefault();
      applyTheme(currentTheme() === 'light' ? 'dark' : 'light', true);
      return;
    }
    var ckBtn = e.target.closest && e.target.closest('[data-cockpits-toggle]');
    if (ckBtn) {
      e.preventDefault();
      var hub = document.getElementById('caveCockpitsTile');
      setCockpitsHubOpen(!(hub && hub.classList.contains('open')));
      return;
    }
    var railBtn = e.target.closest && e.target.closest('#railNav button[data-rail]');
    if (railBtn) {
      var rk = railBtn.getAttribute('data-rail');
      if (rk === 'active' || rk === 'deck') {
        setCockpitsHubOpen(true);
      }
    }
  }, true);

  document.addEventListener('toggle', function (e) {
    if (e.target && e.target.id === 'candsTile') {
      syncReserveTogLabel();
    } else if (e.target && e.target.id === 'caveCommsServicesBar') {
      var st = e.target.querySelector('.cave-services-tog');
      if (st) st.innerHTML = e.target.open ? 'Collapse &#9652;' : 'Expand &#9662;';
    }
  }, true);

  document.querySelectorAll('iframe.cview-frame').forEach(function (fr) {
    fr.addEventListener('load', function () {
      syncEmbeddedFrames(currentTheme());
    });
  });

  applyTheme(currentTheme(), false);
  syncReserveTogLabel();

  /* ── 4. Cave Projects Tile (#ptile) Collapsible Folders, Drag-to-Folder & Guided Walkthrough GUI ── */
  var FOLDER_OPEN_LS = 'anchor_rnd_folder_open';
  var PENDING_FOLDERS_LS = 'anchor_rnd_pending_folders';
  var _draggedProject = null;
  var _wizardState = { tab: 'folder', projMode: 'new_folder', selectedDir: '', parentDir: '', roots: [] };

  function authHdrs(jsonBody) {
    var h = jsonBody ? { 'Content-Type': 'application/json' } : {};
    try {
      var t = localStorage.getItem('anchor_token') || '';
      if (t) { h['X-Anchor-Token'] = t; h['Authorization'] = 'Bearer ' + t; }
    } catch (_) {}
    if (window.ANCHOR_BOOT && window.ANCHOR_BOOT.build_id) {
      h['X-Anchor-Build'] = String(window.ANCHOR_BOOT.build_id);
    }
    return (window.StewardDialogue && typeof window.StewardDialogue.authHeaders === 'function')
      ? window.StewardDialogue.authHeaders(h)
      : h;
  }

  function readLsList(key) {
    try {
      var arr = JSON.parse(localStorage.getItem(key) || '[]');
      return Array.isArray(arr) ? arr.filter(Boolean) : [];
    } catch (_) { return []; }
  }

  function writeLsList(key, arr) {
    try { localStorage.setItem(key, JSON.stringify(arr || [])); } catch (_) {}
  }

  function showCaveToast(msg, isBad) {
    var toast = document.getElementById('caveToast');
    if (toast) {
      var tt = toast.querySelector('#caveToastText');
      var tm = toast.querySelector('.ct-mark');
      if (tt) tt.textContent = msg;
      if (tm) tm.textContent = isBad ? '\u26a0' : '\u2713';
      toast.classList.toggle('bad', Boolean(isBad));
      toast.hidden = false;
      setTimeout(function () { toast.hidden = true; }, 4500);
    }
  }

  function rememberFolderOpen(name, isOpen) {
    var g = String(name || '').trim();
    if (!g) return;
    var cur = readLsList(FOLDER_OPEN_LS);
    var idx = cur.indexOf(g);
    if (isOpen && idx < 0) cur.push(g);
    else if (!isOpen && idx >= 0) cur.splice(idx, 1);
    writeLsList(FOLDER_OPEN_LS, cur);
  }

  window.rndToggleFolder = function (headEl) {
    var folder = headEl && headEl.closest ? headEl.closest('.rnd-folder') : null;
    if (!folder) return;
    var collapsed = folder.classList.toggle('rnd-collapsed');
    var tw = folder.querySelector('.rnd-tw');
    if (tw) tw.textContent = collapsed ? '\u25B8' : '\u25BE';
    rememberFolderOpen(folder.getAttribute('data-group') || '', !collapsed);
  };

  function ensureFolderNode(listEl, groupName, startOpen) {
    if (!listEl || !groupName) return null;
    var existing = null;
    listEl.querySelectorAll('.rnd-folder').forEach(function (el) {
      if ((el.getAttribute('data-group') || '') === groupName) existing = el;
    });
    if (existing) {
      if (startOpen) {
        existing.classList.remove('rnd-collapsed');
        var tw0 = existing.querySelector('.rnd-tw');
        if (tw0) tw0.textContent = '\u25BE';
      }
      return existing;
    }
    var folder = document.createElement('div');
    folder.className = startOpen ? 'rnd-folder' : 'rnd-folder rnd-collapsed';
    folder.setAttribute('data-group', groupName);
    folder.setAttribute('data-ungrouped', '0');
    folder.innerHTML =
      '<div class="rnd-folder-head" role="button" tabindex="0" title="Collapse / expand folder">'
      + '<span class="rnd-tw" aria-hidden="true">' + (startOpen ? '\u25BE' : '\u25B8') + '</span>'
      + '<span class="rnd-fname">' + esc(groupName) + '</span>'
      + '<span class="rnd-fcount">(0)</span>'
      + '<span class="rnd-fsp"></span>'
      + '<span class="rnd-fdrop-hint">empty folder &mdash; drag a project here or click + Add Project to Folder</span>'
      + '</div>'
      + '<div class="rnd-folder-body"><div class="cave-empty-folder-note">No projects in <b>' + esc(groupName) + '</b> yet &mdash; drag any project row onto this header or click <button type="button" class="mini" data-open-folder-wizard="project" data-target-group="' + esc(groupName) + '">&#65291; Add Project Here</button>.</div></div>';
    var head = folder.querySelector('.rnd-folder-head');
    head.addEventListener('click', function (ev) {
      if (ev.target && ev.target.closest && ev.target.closest('button')) return;
      window.rndToggleFolder(head);
    });
    var ung = listEl.querySelector('.rnd-folder[data-ungrouped="1"]');
    if (ung) listEl.insertBefore(folder, ung);
    else listEl.appendChild(folder);
    return folder;
  }

  function syncFolderDom(forceOpenGroup) {
    var host = document.getElementById('folders');
    var listEl = host && host.querySelector('.rnd-folder-list');
    if (!listEl) return;

    var serverGroups = [];
    listEl.querySelectorAll('.rnd-folder').forEach(function (f) {
      var g = f.getAttribute('data-group') || '';
      if (g) serverGroups.push(g);
    });

    var pend = readLsList(PENDING_FOLDERS_LS);
    var stillPending = [];
    pend.forEach(function (g) {
      if (serverGroups.indexOf(g) >= 0) return;
      stillPending.push(g);
      ensureFolderNode(listEl, g, false);
    });
    if (stillPending.length !== pend.length) writeLsList(PENDING_FOLDERS_LS, stillPending);

    if (forceOpenGroup) rememberFolderOpen(forceOpenGroup, true);
    var openSet = readLsList(FOLDER_OPEN_LS);
    listEl.querySelectorAll('.rnd-folder').forEach(function (f) {
      var g = f.getAttribute('data-group') || '';
      var shouldOpen = openSet.indexOf(g) >= 0;
      f.classList.toggle('rnd-collapsed', !shouldOpen);
      var tw = f.querySelector('.rnd-tw');
      if (tw) tw.textContent = shouldOpen ? '\u25BE' : '\u25B8';
    });

    var allFolders = listEl.querySelectorAll('.rnd-folder');
    var allRows = listEl.querySelectorAll('.rnd-row[data-project-id]');
    var cntEl = document.getElementById('ptileCount');
    if (cntEl) {
      cntEl.innerHTML = '&middot; ' + allRows.length + ' project' + (allRows.length === 1 ? '' : 's')
        + ' in ' + allFolders.length + ' folder' + (allFolders.length === 1 ? '' : 's');
    }
    var grpSel = document.getElementById('apGroups');
    if (grpSel) {
      var opts = [];
      allFolders.forEach(function (f) {
        if (f.getAttribute('data-ungrouped') === '1') return;
        var g = f.getAttribute('data-group') || '';
        if (g) opts.push('<option value="' + esc(g) + '">' + esc(g) + '</option>');
      });
      opts.push('<option value="" selected>Ungrouped</option>');
      grpSel.innerHTML = opts.join('');
    }
  }

  function refreshCaveFolders(expandGroup) {
    var ptile = document.getElementById('ptile');
    var ptileTog = document.getElementById('ptileTog');
    if (ptile && !ptile.classList.contains('open')) {
      ptile.classList.add('open');
      if (ptileTog) ptileTog.textContent = 'Hide';
    }
    return fetch('/api/high-seat/projects', { headers: authHdrs(false) })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        var host = document.getElementById('folders');
        if (host && j && j.html) {
          host.innerHTML = j.html;
          syncFolderDom(expandGroup || '');
        }
        return j;
      })
      .catch(function () { return null; });
  }

  function collectKnownGroupsAndProjects() {
    var groups = [];
    var projects = [];
    var seenG = {};
    var grpSel = document.getElementById('apGroups');
    if (grpSel) {
      Array.prototype.forEach.call(grpSel.options, function (o) {
        var v = (o.value || '').trim();
        if (v && !seenG[v]) { seenG[v] = true; groups.push(v); }
      });
    }
    readLsList(PENDING_FOLDERS_LS).forEach(function (g) {
      if (g && !seenG[g]) { seenG[g] = true; groups.push(g); }
    });
    document.querySelectorAll('#folders .rnd-folder').forEach(function (f) {
      if (f.getAttribute('data-ungrouped') === '1') return;
      var g = (f.getAttribute('data-group') || '').trim();
      if (g && !seenG[g]) { seenG[g] = true; groups.push(g); }
    });
    var seenP = {};
    document.querySelectorAll('#folders .rnd-folder-list .rnd-row[data-project-id]').forEach(function (r) {
      var pid = r.getAttribute('data-project-id') || '';
      if (!pid || seenP[pid]) return;
      seenP[pid] = true;
      var nmEl = r.querySelector('.rnd-name');
      projects.push({
        id: pid,
        name: (nmEl && nmEl.textContent.trim()) || pid,
        group: r.getAttribute('data-group') || ''
      });
    });
    return { groups: groups, projects: projects };
  }

  function slugifyName(s) {
    return String(s || '').trim().replace(/[<>:"/\\|?*]+/g, '-').replace(/\s+/g, '-') || 'new-project';
  }

  function ensureWizardModal() {
    var m = document.getElementById('caveFolderWizardModal');
    if (m) return m;
    m = document.createElement('div');
    m.id = 'caveFolderWizardModal';
    m.className = 'cave-fw-backdrop';
    m.hidden = true;
    m.innerHTML =
      '<div class="cave-fw-dialog" role="dialog" aria-modal="true" aria-labelledby="caveFwTitle">'
      + '<div class="cave-fw-head">'
      + '  <div>'
      + '    <div class="cave-fw-eyebrow">CAVE OF WONDERS &middot; PROJECT &amp; FOLDER WALKTHROUGH</div>'
      + '    <h3 id="caveFwTitle">Organize Project Folders</h3>'
      + '  </div>'
      + '  <button type="button" class="cave-fw-close" data-fw-close aria-label="Close">&times;</button>'
      + '</div>'
      + '<div class="cave-fw-tabs" role="tablist">'
      + '  <button type="button" class="cave-fw-tab on" data-fw-tab="folder">&#128193; 1. Add a Folder</button>'
      + '  <button type="button" class="cave-fw-tab" data-fw-tab="project">&#128640; 2. Add a Project to a Folder</button>'
      + '</div>'
      + '<div class="cave-fw-pane" id="caveFwFolderPane">'
      + '  <div class="cave-fw-step">'
      + '    <div class="cave-fw-step-lbl"><span class="cave-fw-num">1</span> Name your folder</div>'
      + '    <input type="text" class="cave-fw-input" id="caveFwFolderName" placeholder="e.g., Teaching, Research, Commercial, Writing..." autocomplete="off">'
      + '    <div class="cave-fw-chips" id="caveFwQuickChips">'
      + '      <span class="cave-fw-chip-hint">Quick suggestions:</span>'
      + '      <button type="button" class="cave-fw-chip" data-fw-suggest="Teaching">Teaching</button>'
      + '      <button type="button" class="cave-fw-chip" data-fw-suggest="Research">Research</button>'
      + '      <button type="button" class="cave-fw-chip" data-fw-suggest="Commercial">Commercial</button>'
      + '      <button type="button" class="cave-fw-chip" data-fw-suggest="Writing">Writing</button>'
      + '      <button type="button" class="cave-fw-chip" data-fw-suggest="Foundational">Foundational</button>'
      + '    </div>'
      + '  </div>'
      + '  <div class="cave-fw-step">'
      + '    <div class="cave-fw-step-lbl"><span class="cave-fw-num">2</span> Select existing projects to place inside now <span class="cave-fw-opt">(optional &mdash; or drag in later)</span></div>'
      + '    <div class="cave-fw-checklist" id="caveFwProjChecklist"><div class="cave-fw-muted">Loading projects&hellip;</div></div>'
      + '  </div>'
      + '  <div class="cave-fw-step">'
      + '    <div class="cave-fw-step-lbl"><span class="cave-fw-num">3</span> How should selected projects be organized?</div>'
      + '    <label class="cave-fw-radio"><input type="radio" name="caveFwOrgMode" value="group" checked> <span><b>Group in folder on dashboard (Recommended)</b> &mdash; keeps existing on-disk paths untouched</span></label>'
      + '    <label class="cave-fw-radio"><input type="radio" name="caveFwOrgMode" value="disk"> <span><b>Also move project directory on disk</b> &mdash; guarded atomic move into matching subfolder</span></label>'
      + '  </div>'
      + '  <div class="cave-fw-status" id="caveFwFolderStatus" hidden></div>'
      + '  <div class="cave-fw-foot">'
      + '    <button type="button" class="cave-fw-btn ghost" data-fw-close>Cancel</button>'
      + '    <button type="button" class="cave-fw-btn primary" id="caveFwCreateFolderBtn">&#128193; Create Folder &rarr;</button>'
      + '  </div>'
      + '</div>'
      + '<div class="cave-fw-pane" id="caveFwProjectPane" hidden>'
      + '  <div class="cave-fw-step">'
      + '    <div class="cave-fw-step-lbl"><span class="cave-fw-num">1</span> Choose where the project lives on disk</div>'
      + '    <div class="cave-fw-mode-row">'
      + '      <button type="button" class="cave-fw-mode on" data-fw-pmode="new_folder">&#10024; Create New Folder on Disk</button>'
      + '      <button type="button" class="cave-fw-mode" data-fw-pmode="existing">&#128194; Select Existing Folder on Disk</button>'
      + '    </div>'
      + '    <div id="caveFwNewDiskBox" class="cave-fw-subbox">'
      + '      <label class="cave-fw-field-lbl">Parent directory on disk</label>'
      + '      <div class="cave-fw-inline">'
      + '        <input type="text" class="cave-fw-input" id="caveFwParentPath" placeholder="Workspace parent directory">'
      + '        <button type="button" class="cave-fw-btn" id="caveFwBrowseParentBtn">Browse&hellip;</button>'
      + '      </div>'
      + '      <div class="cave-fw-preview" id="caveFwPathPreview">Will create: <code>&hellip;</code></div>'
      + '      <label class="cave-fw-check"><input type="checkbox" id="caveFwGitInit" checked> Initialize git repository automatically</label>'
      + '    </div>'
      + '    <div id="caveFwExistingDiskBox" class="cave-fw-subbox" hidden>'
      + '      <label class="cave-fw-field-lbl">Selected existing folder on disk</label>'
      + '      <input type="text" class="cave-fw-input" id="caveFwExistingPath" placeholder="Click a folder below or paste full path">'
      + '    </div>'
      + '    <div class="cave-fw-browser" id="caveFwDirBrowser" hidden>'
      + '      <div class="cave-fw-browser-bar" id="caveFwDirRoots"></div>'
      + '      <div class="cave-fw-browser-cur" id="caveFwDirCurrent"></div>'
      + '      <div class="cave-fw-browser-list" id="caveFwDirList"></div>'
      + '    </div>'
      + '  </div>'
      + '  <div class="cave-fw-step cave-fw-two-col">'
      + '    <div>'
      + '      <div class="cave-fw-step-lbl"><span class="cave-fw-num">2</span> Project Name &amp; Priority</div>'
      + '      <div class="cave-fw-inline">'
      + '        <input type="text" class="cave-fw-input" id="caveFwProjName" placeholder="e.g., Quantum Portfolio Lab">'
      + '        <select class="cave-fw-select" id="caveFwProjPrio" style="max-width:125px">'
      + '          <option value="1">P1 &middot; High</option>'
      + '          <option value="2" selected>P2 &middot; Normal</option>'
      + '          <option value="3">P3 &middot; Later</option>'
      + '        </select>'
      + '      </div>'
      + '    </div>'
      + '    <div>'
      + '      <div class="cave-fw-step-lbl"><span class="cave-fw-num">3</span> Place in Dashboard Folder</div>'
      + '      <select class="cave-fw-select" id="caveFwProjGroup"></select>'
      + '      <input type="text" class="cave-fw-input" id="caveFwProjNewGroup" placeholder="New dashboard folder name..." style="margin-top:6px" hidden>'
      + '    </div>'
      + '  </div>'
      + '  <div class="cave-fw-status" id="caveFwProjStatus" hidden></div>'
      + '  <div class="cave-fw-foot">'
      + '    <button type="button" class="cave-fw-btn ghost" data-fw-close>Cancel</button>'
      + '    <button type="button" class="cave-fw-btn primary" id="caveFwCreateProjBtn">&#128640; Create Project &rarr;</button>'
      + '  </div>'
      + '</div>'
      + '<div class="cave-fw-pane" id="caveFwMovePane" hidden>'
      + '  <div class="cave-fw-step">'
      + '    <div class="cave-fw-step-lbl" id="caveFwMoveHeading">Move project into folder</div>'
      + '    <p class="cave-fw-muted" id="caveFwMoveDesc" style="margin-top:4px"></p>'
      + '  </div>'
      + '  <div class="cave-fw-foot">'
      + '    <button type="button" class="cave-fw-btn ghost" data-fw-close>Cancel</button>'
      + '    <button type="button" class="cave-fw-btn" id="caveFwMoveDiskBtn">&#128666; Move on Disk + Group</button>'
      + '    <button type="button" class="cave-fw-btn primary" id="caveFwMoveGroupOnlyBtn">&#128193; Group in Folder (Recommended)</button>'
      + '  </div>'
      + '</div>'
      + '</div>';
    document.body.appendChild(m);

    function updatePathPreview() {
      var par = (document.getElementById('caveFwParentPath').value || '').trim().replace(/[\\/]+$/, '');
      var nm = (document.getElementById('caveFwProjName').value || '').trim();
      var prev = document.getElementById('caveFwPathPreview');
      if (prev) {
        var sep = par.indexOf('/') >= 0 && par.indexOf('\\') < 0 ? '/' : '\\';
        prev.innerHTML = 'On-disk location: <code>' + esc((par || '<workspace>') + sep + slugifyName(nm)) + '</code>';
      }
    }

    document.getElementById('caveFwParentPath').addEventListener('input', updatePathPreview);
    document.getElementById('caveFwProjName').addEventListener('input', updatePathPreview);
    document.getElementById('caveFwProjGroup').addEventListener('change', function (ev) {
      var ng = document.getElementById('caveFwProjNewGroup');
      if (ng) ng.hidden = ev.target.value !== '__new__';
    });
    document.getElementById('caveFwBrowseParentBtn').addEventListener('click', function () {
      var br = document.getElementById('caveFwDirBrowser');
      if (br) {
        br.hidden = !br.hidden;
        if (!br.hidden) loadDirBrowser(document.getElementById('caveFwParentPath').value || '');
      }
    });

    m.addEventListener('click', function (ev) {
      if (ev.target === m || (ev.target.closest && ev.target.closest('[data-fw-close]'))) {
        m.hidden = true;
        return;
      }
      var tabBtn = ev.target.closest && ev.target.closest('[data-fw-tab]');
      if (tabBtn) {
        switchWizardTab(tabBtn.getAttribute('data-fw-tab') || 'folder');
        return;
      }
      var chip = ev.target.closest && ev.target.closest('[data-fw-suggest]');
      if (chip) {
        var inp = document.getElementById('caveFwFolderName');
        if (inp) { inp.value = chip.getAttribute('data-fw-suggest') || ''; inp.focus(); }
        return;
      }
      var pmBtn = ev.target.closest && ev.target.closest('[data-fw-pmode]');
      if (pmBtn) {
        var mode = pmBtn.getAttribute('data-fw-pmode') || 'new_folder';
        _wizardState.projMode = mode;
        m.querySelectorAll('[data-fw-pmode]').forEach(function (b) { b.classList.toggle('on', b === pmBtn); });
        document.getElementById('caveFwNewDiskBox').hidden = mode !== 'new_folder';
        document.getElementById('caveFwExistingDiskBox').hidden = mode !== 'existing';
        var br = document.getElementById('caveFwDirBrowser');
        if (mode === 'existing') {
          br.hidden = false;
          loadDirBrowser(document.getElementById('caveFwExistingPath').value || _wizardState.parentDir || '');
        }
        return;
      }
      var dirBtn = ev.target.closest && ev.target.closest('[data-fw-dir-nav]');
      if (dirBtn) {
        var p = dirBtn.getAttribute('data-fw-dir-nav') || '';
        loadDirBrowser(p);
        return;
      }
      var pickBtn = ev.target.closest && ev.target.closest('[data-fw-dir-pick]');
      if (pickBtn) {
        var picked = pickBtn.getAttribute('data-fw-dir-pick') || '';
        if (_wizardState.projMode === 'existing') {
          document.getElementById('caveFwExistingPath').value = picked;
          var nmIn = document.getElementById('caveFwProjName');
          if (nmIn && !nmIn.value.trim()) {
            nmIn.value = picked.replace(/[\\/]+$/, '').split(/[\\/]/).pop() || '';
          }
        } else {
          document.getElementById('caveFwParentPath').value = picked;
          updatePathPreview();
        }
        return;
      }
    });

    document.getElementById('caveFwCreateFolderBtn').addEventListener('click', submitCreateFolder);
    document.getElementById('caveFwCreateProjBtn').addEventListener('click', submitCreateProject);
    return m;
  }

  function loadDirBrowser(targetPath) {
    var url = '/api/rnd/dir_browse' + (targetPath ? ('?path=' + encodeURIComponent(targetPath)) : '');
    fetch(url, { headers: authHdrs(false) })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var res = (d && d.result) || d || {};
        var roots = Array.isArray(res.roots) ? res.roots : [];
        var dirs = Array.isArray(res.dirs) ? res.dirs : [];
        var curPath = String(res.path || res.current || targetPath || (roots[0] && (roots[0].path || roots[0])) || '');
        if (!_wizardState.parentDir && curPath) {
          _wizardState.parentDir = curPath;
          var parIn = document.getElementById('caveFwParentPath');
          if (parIn && !parIn.value.trim()) {
            parIn.value = curPath;
            parIn.dispatchEvent(new Event('input'));
          }
        }
        var rootsEl = document.getElementById('caveFwDirRoots');
        if (rootsEl) {
          var rHtml = roots.map(function (rt) {
            var rp = typeof rt === 'string' ? rt : (rt.path || '');
            var rl = typeof rt === 'string' ? rt : (rt.label || rt.name || rp);
            return '<button type="button" class="cave-fw-chip" data-fw-dir-nav="' + esc(rp) + '">&#128193; ' + esc(rl) + '</button>';
          });
          if (res.parent) {
            rHtml.unshift('<button type="button" class="cave-fw-chip" data-fw-dir-nav="' + esc(res.parent) + '">&uarr; Up</button>');
          }
          rootsEl.innerHTML = rHtml.join('');
        }
        var curEl = document.getElementById('caveFwDirCurrent');
        if (curEl) {
          curEl.innerHTML = curPath
            ? ('<span>Browsing: <code>' + esc(curPath) + '</code></span>'
               + '<button type="button" class="mini" data-fw-dir-pick="' + esc(curPath) + '">&#10003; Use This Folder</button>')
            : '';
        }
        var listEl = document.getElementById('caveFwDirList');
        if (listEl) {
          if (!dirs.length) {
            listEl.innerHTML = '<div class="cave-fw-muted">No subfolders inside this folder.</div>';
          } else {
            listEl.innerHTML = dirs.slice(0, 80).map(function (dr) {
              var dp = typeof dr === 'string' ? dr : (dr.path || '');
              var dn = typeof dr === 'string' ? dp.split(/[\\/]/).pop() : (dr.name || dp);
              return '<div class="cave-fw-dir-row">'
                + '<button type="button" class="cave-fw-dir-open" data-fw-dir-nav="' + esc(dp) + '">&#128193; ' + esc(dn) + '</button>'
                + '<button type="button" class="mini" data-fw-dir-pick="' + esc(dp) + '">Select</button>'
                + '</div>';
            }).join('');
          }
        }
      })
      .catch(function () {});
  }

  function switchWizardTab(tab, targetGroup) {
    var m = ensureWizardModal();
    _wizardState.tab = tab;
    m.querySelector('.cave-fw-tabs').hidden = (tab === 'move');
    m.querySelectorAll('[data-fw-tab]').forEach(function (b) {
      b.classList.toggle('on', b.getAttribute('data-fw-tab') === tab);
    });
    document.getElementById('caveFwFolderPane').hidden = tab !== 'folder';
    document.getElementById('caveFwProjectPane').hidden = tab !== 'project';
    document.getElementById('caveFwMovePane').hidden = tab !== 'move';
    var titleEl = document.getElementById('caveFwTitle');
    if (titleEl) {
      titleEl.textContent = tab === 'folder'
        ? 'Add a Project Folder'
        : (tab === 'project' ? 'Add a Project into a Folder' : 'Move Project into Folder');
    }

    var info = collectKnownGroupsAndProjects();
    if (tab === 'folder') {
      var cl = document.getElementById('caveFwProjChecklist');
      if (cl) {
        if (!info.projects.length) {
          cl.innerHTML = '<div class="cave-fw-muted">No active projects loaded yet &mdash; you can create the empty folder now and drag or add projects into it anytime.</div>';
        } else {
          var sorted = info.projects.slice().sort(function (a, b) {
            var au = a.group ? 1 : 0, bu = b.group ? 1 : 0;
            return au !== bu ? (au - bu) : a.name.localeCompare(b.name);
          });
          cl.innerHTML = sorted.map(function (p) {
            var badge = p.group ? ('in ' + p.group) : 'Ungrouped';
            return '<label class="cave-fw-proj-item">'
              + '<input type="checkbox" value="' + esc(p.id) + '" data-fw-proj-check>'
              + '<span class="cave-fw-proj-nm">' + esc(p.name) + '</span>'
              + '<span class="cave-fw-proj-grp">' + esc(badge) + '</span>'
              + '</label>';
          }).join('');
        }
      }
    } else if (tab === 'project') {
      var sel = document.getElementById('caveFwProjGroup');
      if (sel) {
        var opts = ['<option value="">Ungrouped (no folder)</option>'];
        info.groups.forEach(function (g) {
          var isSel = targetGroup && targetGroup === g ? ' selected' : '';
          opts.push('<option value="' + esc(g) + '"' + isSel + '>&#128193; ' + esc(g) + '</option>');
        });
        opts.push('<option value="__new__">+ Create a new folder&hellip;</option>');
        sel.innerHTML = opts.join('');
        if (targetGroup && info.groups.indexOf(targetGroup) >= 0) sel.value = targetGroup;
        document.getElementById('caveFwProjNewGroup').hidden = sel.value !== '__new__';
      }
      if (!_wizardState.parentDir) loadDirBrowser('');
    }
  }

  function openCaveFolderWizard(mode, targetGroup) {
    var m = ensureWizardModal();
    var st1 = document.getElementById('caveFwFolderStatus');
    var st2 = document.getElementById('caveFwProjStatus');
    if (st1) st1.hidden = true;
    if (st2) st2.hidden = true;
    m.hidden = false;
    var host = document.getElementById('folders');
    var hasList = Boolean(host && host.querySelector('.rnd-folder-list'));
    var ready = hasList ? Promise.resolve() : refreshCaveFolders('');
    ready.then(function () {
      switchWizardTab(mode === 'project' ? 'project' : 'folder', targetGroup || '');
      var focusEl = document.getElementById(mode === 'project' ? 'caveFwProjName' : 'caveFwFolderName');
      if (focusEl) setTimeout(function () { focusEl.focus(); }, 40);
    });
  }

  function applyProjectGroup(pid, groupName, moveOnDisk) {
    if (!moveOnDisk) {
      return fetch('/api/rnd/set_group', {
        method: 'POST',
        headers: authHdrs(true),
        body: JSON.stringify({ project_id: pid, group: groupName })
      }).then(function (r) { return r.json(); });
    }
    return fetch('/api/rnd/move_project', {
      method: 'POST',
      headers: authHdrs(true),
      body: JSON.stringify({ project_id: pid, group: groupName, confirm: true })
    }).then(function (r) { return r.json(); }).then(function (res) {
      if (res && res.ok) return res;
      return fetch('/api/rnd/set_group', {
        method: 'POST',
        headers: authHdrs(true),
        body: JSON.stringify({ project_id: pid, group: groupName })
      }).then(function (r2) { return r2.json(); });
    });
  }

  function submitCreateFolder() {
    var inp = document.getElementById('caveFwFolderName');
    var st = document.getElementById('caveFwFolderStatus');
    var btn = document.getElementById('caveFwCreateFolderBtn');
    var name = (inp && inp.value || '').trim();
    if (!name) {
      if (st) { st.textContent = 'Please enter a folder name first.'; st.hidden = false; }
      if (inp) inp.focus();
      return;
    }
    var checked = [];
    document.querySelectorAll('#caveFwProjChecklist input[data-fw-proj-check]:checked').forEach(function (cb) {
      if (cb.value) checked.push(cb.value);
    });
    var modeEl = document.querySelector('input[name="caveFwOrgMode"]:checked');
    var onDisk = Boolean(modeEl && modeEl.value === 'disk');

    var pend = readLsList(PENDING_FOLDERS_LS);
    if (pend.indexOf(name) < 0) { pend.push(name); writeLsList(PENDING_FOLDERS_LS, pend); }
    rememberFolderOpen(name, true);

    if (btn) { btn.disabled = true; btn.textContent = 'Creating\u2026'; }
    Promise.all(checked.map(function (pid) { return applyProjectGroup(pid, name, onDisk); }))
      .then(function () { return refreshCaveFolders(name); })
      .then(function () {
        if (btn) { btn.disabled = false; btn.innerHTML = '&#128193; Create Folder &rarr;'; }
        if (inp) inp.value = '';
        var m = document.getElementById('caveFolderWizardModal');
        if (m) m.hidden = true;
        showCaveToast('Folder "' + name + '" ready' + (checked.length ? (' with ' + checked.length + ' project(s).') : ' — drag or add projects anytime.'), false);
      })
      .catch(function () {
        if (btn) { btn.disabled = false; btn.innerHTML = '&#128193; Create Folder &rarr;'; }
        if (st) { st.textContent = 'Could not save folder changes — please try again.'; st.hidden = false; }
      });
  }

  function submitCreateProject() {
    var name = (document.getElementById('caveFwProjName').value || '').trim();
    var prio = parseInt(document.getElementById('caveFwProjPrio').value || '2', 10) || 2;
    var grpSel = document.getElementById('caveFwProjGroup').value || '';
    var newGrp = (document.getElementById('caveFwProjNewGroup').value || '').trim();
    var group = grpSel === '__new__' ? newGrp : grpSel;
    var st = document.getElementById('caveFwProjStatus');
    var btn = document.getElementById('caveFwCreateProjBtn');

    if (!name) {
      if (st) { st.textContent = 'Please enter a project name.'; st.hidden = false; }
      return;
    }
    var payload = { name: name, priority: prio, group: group };
    if (_wizardState.projMode === 'existing') {
      var fp = (document.getElementById('caveFwExistingPath').value || '').trim();
      if (!fp) {
        if (st) { st.textContent = 'Please select or paste an existing folder path on disk.'; st.hidden = false; }
        return;
      }
      payload.mode = 'existing';
      payload.folder_path = fp;
    } else {
      var pp = (document.getElementById('caveFwParentPath').value || '').trim();
      if (!pp) {
        if (st) { st.textContent = 'Please choose a parent directory on disk.'; st.hidden = false; }
        return;
      }
      payload.mode = 'new_folder';
      payload.parent_path = pp;
      payload.git_init = Boolean(document.getElementById('caveFwGitInit').checked);
    }

    if (btn) { btn.disabled = true; btn.textContent = 'Creating\u2026'; }
    fetch('/api/rnd/new_project', {
      method: 'POST',
      headers: authHdrs(true),
      body: JSON.stringify(payload)
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (btn) { btn.disabled = false; btn.innerHTML = '&#128640; Create Project &rarr;'; }
        if (!d || !d.ok) {
          if (st) { st.textContent = (d && (d.error || d.message)) || 'Could not create project.'; st.hidden = false; }
          return;
        }
        if (group) rememberFolderOpen(group, true);
        var m = document.getElementById('caveFolderWizardModal');
        if (m) m.hidden = true;
        refreshCaveFolders(group || 'Ungrouped');
        showCaveToast(d.message || ('Created project "' + name + '"' + (group ? (' in folder "' + group + '".') : '.')), false);
      })
      .catch(function () {
        if (btn) { btn.disabled = false; btn.innerHTML = '&#128640; Create Project &rarr;'; }
        if (st) { st.textContent = 'Network error while creating project.'; st.hidden = false; }
      });
  }

  function openDropMovePrompt(pid, projName, targetGroup) {
    var m = ensureWizardModal();
    switchWizardTab('move');
    m.hidden = false;
    var h = document.getElementById('caveFwMoveHeading');
    var d = document.getElementById('caveFwMoveDesc');
    if (h) h.textContent = 'Place "' + (projName || pid) + '" into folder "' + targetGroup + '"?';
    if (d) d.textContent = 'Choose whether to group it in "' + targetGroup + '" on the dashboard (leaving its on-disk path untouched) or also move its directory on disk.';
    var gBtn = document.getElementById('caveFwMoveGroupOnlyBtn');
    var dBtn = document.getElementById('caveFwMoveDiskBtn');
    gBtn.onclick = function () {
      m.hidden = true;
      rememberFolderOpen(targetGroup, true);
      applyProjectGroup(pid, targetGroup, false).then(function () {
        refreshCaveFolders(targetGroup);
        showCaveToast('Grouped "' + (projName || pid) + '" into "' + targetGroup + '".', false);
      });
    };
    dBtn.onclick = function () {
      m.hidden = true;
      rememberFolderOpen(targetGroup, true);
      applyProjectGroup(pid, targetGroup, true).then(function (res) {
        refreshCaveFolders(targetGroup);
        showCaveToast((res && res.reason) ? ('Disk move refused (' + res.reason + ') — grouped in "' + targetGroup + '" instead.') : ('Moved "' + (projName || pid) + '" into "' + targetGroup + '".'), false);
      });
    };
  }

  window.rndNewFolder = function () { openCaveFolderWizard('folder'); };

  document.addEventListener('click', function (e) {
    var wizBtn = e.target.closest && e.target.closest('[data-open-folder-wizard], #apNew, #apAddFolder');
    if (wizBtn) {
      e.preventDefault();
      e.stopPropagation();
      var mode = wizBtn.getAttribute('data-open-folder-wizard') || (wizBtn.id === 'apNew' ? 'project' : 'folder');
      var tGrp = wizBtn.getAttribute('data-target-group') || '';
      openCaveFolderWizard(mode, tGrp);
    }
  }, true);

  document.addEventListener('dragstart', function (e) {
    var row = e.target.closest && e.target.closest('#folders .rnd-row[data-project-id]');
    if (!row) return;
    var pid = row.getAttribute('data-project-id') || '';
    if (!pid) return;
    var nm = row.querySelector('.rnd-name');
    _draggedProject = { id: pid, name: (nm && nm.textContent.trim()) || pid, group: row.getAttribute('data-group') || '' };
    row.classList.add('rnd-dragging');
    try { e.dataTransfer.setData('text/plain', pid); e.dataTransfer.effectAllowed = 'move'; } catch (_) {}
  });

  document.addEventListener('dragend', function () {
    _draggedProject = null;
    document.querySelectorAll('#folders .rnd-dragging, #folders .rnd-droptarget').forEach(function (el) {
      el.classList.remove('rnd-dragging', 'rnd-droptarget');
    });
  });

  document.addEventListener('dragover', function (e) {
    if (!_draggedProject) return;
    var head = e.target.closest && e.target.closest('#folders .rnd-folder-head');
    if (!head) return;
    e.preventDefault();
    try { e.dataTransfer.dropEffect = 'move'; } catch (_) {}
    var folder = head.closest('.rnd-folder');
    if (folder) folder.classList.add('rnd-droptarget');
  });

  document.addEventListener('dragleave', function (e) {
    var head = e.target.closest && e.target.closest('#folders .rnd-folder-head');
    var folder = head && head.closest('.rnd-folder');
    if (folder && !folder.contains(e.relatedTarget)) folder.classList.remove('rnd-droptarget');
  });

  document.addEventListener('drop', function (e) {
    if (!_draggedProject) return;
    var head = e.target.closest && e.target.closest('#folders .rnd-folder-head');
    if (!head) return;
    e.preventDefault();
    e.stopPropagation();
    var folder = head.closest('.rnd-folder');
    if (!folder) return;
    folder.classList.remove('rnd-droptarget');
    var isUng = folder.getAttribute('data-ungrouped') === '1';
    var targetGroup = isUng ? '' : (folder.getAttribute('data-group') || '');
    var dragged = _draggedProject;
    _draggedProject = null;
    if (isUng) {
      applyProjectGroup(dragged.id, '', false).then(function () {
        refreshCaveFolders('Ungrouped');
        showCaveToast('Moved "' + dragged.name + '" to Ungrouped.', false);
      });
    } else if (targetGroup) {
      openDropMovePrompt(dragged.id, dragged.name, targetGroup);
    }
  });

  var foldersHost = document.getElementById('folders');
  if (foldersHost && typeof MutationObserver !== 'undefined') {
    var _syncingFolders = false;
    var mo = new MutationObserver(function () {
      if (_syncingFolders) return;
      _syncingFolders = true;
      try { syncFolderDom(''); } finally { _syncingFolders = false; }
    });
    mo.observe(foldersHost, { childList: true });
    syncFolderDom('');
  }

  window.CaveTidyControls = {
    applyTheme: applyTheme,
    currentTheme: currentTheme,
    setCockpitsHubOpen: setCockpitsHubOpen,
    syncAfterMorph: syncAfterMorph,
    renderCommsServicesBar: renderCommsServicesBar,
    openCaveFolderWizard: openCaveFolderWizard,
    refreshCaveFolders: refreshCaveFolders
  };
})();
