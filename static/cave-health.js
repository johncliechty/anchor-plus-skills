(function () {
  'use strict';

  if (window.AnchorCaveHealth) return;

  var started = false;
  var pending = null;
  var options = {};
  var lastReport = '';
  var lastSignature = '';
  var timer = null;

  function surface() {
    return document.querySelector('.main > .masthead');
  }

  function banner() {
    var masthead = surface();
    if (!masthead) return null;
    var sibling = masthead.nextElementSibling;
    return sibling && sibling.classList.contains('healthbar') ? sibling : null;
  }

  function report(value) {
    if (!value || typeof value !== 'object' || value.ok !== true) return null;
    if (!['red', 'yellow', 'green', 'unknown', 'none'].includes(value.status)) return null;
    if (typeof value.last_run !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(value.last_run)) return null;
    if (!Array.isArray(value.issues) || !Array.isArray(value.warnings)) return null;
    if (!value.issues.every(function (issue) {
      return issue && typeof issue === 'object' && typeof issue.component === 'string' &&
        typeof issue.detail === 'string';
    })) return null;
    if (!value.warnings.every(function (warning) { return typeof warning === 'string'; })) return null;
    if (value.status === 'unknown' || value.status === 'none') return null;
    if (value.status !== 'red' && value.issues.length) return null;
    if (lastReport && value.last_run < lastReport) return null;
    return value;
  }

  function openTool(kind) {
    if (typeof options.openTool === 'function') {
      options.openTool(kind);
      return;
    }
    window.open(kind === 'zombie' ? '/api/rnd/zombie_hunter_report' : '/doctor', '_blank', 'noopener');
  }

  function button(kind, label, className) {
    var node = document.createElement('button');
    node.type = 'button';
    node.className = className;
    node.dataset.tool = kind;
    if (kind === 'zombie') {
      var icon = document.createElement('img');
      icon.className = 'tool-icon';
      icon.src = '/vendor/brand/zombie-hunter-radar.jpg';
      icon.alt = '';
      node.appendChild(icon);
      node.appendChild(document.createTextNode(' ' + label));
    } else {
      node.textContent = label;
    }
    node.addEventListener('click', function () { openTool(kind); });
    return node;
  }

  function getAuthHeaders(extra) {
    var headers;
    if (typeof options.headers === 'function') {
      headers = Object.assign({}, options.headers());
    } else if (window.StewardDialogue && typeof window.StewardDialogue.authHeaders === 'function') {
      headers = window.StewardDialogue.authHeaders({});
    } else {
      headers = {};
      try {
        var token = window.localStorage.getItem('anchor_token');
        if (token) {
          headers['X-Anchor-Token'] = token;
          headers.Authorization = 'Bearer ' + token;
        }
      } catch (_) {}
    }
    if (extra) Object.assign(headers, extra);
    return headers;
  }

  function plainIssueLabel(issue) {
    var comp = (issue && issue.component) ? String(issue.component).trim() : 'check';
    var detail = (issue && issue.detail) ? String(issue.detail).trim() : '';
    if (/unreachable|timed?\s*out|ConnectionRefused|WinError/i.test(detail)) {
      return comp + ': live server self-probe timed out during check';
    }
    if (/401|403|unauthorized/i.test(detail)) {
      return comp + ': authentication check rejected tokenless request';
    }
    var clean = detail.replace(/\s+/g, ' ');
    if (clean.length > 76) clean = clean.slice(0, 73) + '…';
    return comp + (clean ? ': ' + clean : '');
  }

  function runOneClickFix(btn) {
    if (!btn || btn.disabled) return;
    var origText = btn.textContent;
    btn.disabled = true;
    btn.textContent = '⏳ Verifying…';
    fetch('/api/doctor/resolve_all', {
      method: 'POST',
      credentials: 'same-origin',
      headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({})
    }).then(function (r) {
      return r.json();
    }).then(function (p) {
      if (!p || !p.ok) {
        btn.disabled = false;
        btn.textContent = origText;
        openTool('doctor');
        return;
      }
      if (p.decision === 'session') {
        btn.disabled = false;
        btn.textContent = origText;
        openTool('doctor');
        return;
      }
      btn.textContent = '🔄 Re-checking…';
      var polls = 0;
      var pollTimer = window.setInterval(function () {
        polls += 1;
        refresh();
        if (!banner() || polls >= 20) {
          window.clearInterval(pollTimer);
          if (btn.isConnected) {
            btn.disabled = false;
            btn.textContent = origText;
          }
        }
      }, 2000);
    }).catch(function () {
      btn.disabled = false;
      btn.textContent = origText;
    });
  }

  function wireBannerActions(bar) {
    if (!bar || bar._hbWired) return;
    bar._hbWired = true;
    bar.addEventListener('click', function (ev) {
      var fixBtn = ev.target.closest('[data-hb-act="resolve-all"]');
      if (fixBtn) {
        ev.preventDefault();
        runOneClickFix(fixBtn);
        return;
      }
      var dismissBtn = ev.target.closest('[data-hb-act="dismiss"]');
      if (dismissBtn) {
        ev.preventDefault();
        bar.remove();
        lastSignature = '';
      }
    });
  }

  function render(value) {
    var masthead = surface();
    if (!masthead) return;
    var current = banner();
    if (value.status !== 'red') {
      if (current) current.remove();
      lastReport = value.last_run;
      lastSignature = '';
      return;
    }

    var details = value.issues.map(function (issue) {
      return issue.component + ': ' + issue.detail;
    }).join('\n') || 'Doctor can diagnose it';
    var signature = JSON.stringify([value.status, value.last_run, value.issues]);
    if (current && signature === lastSignature) {
      wireBannerActions(current);
      lastReport = value.last_run;
      return;
    }
    if (!current) {
      current = document.createElement('div');
      current.className = 'healthbar';
      current.setAttribute('role', 'alert');
      var mark = document.createElement('span');
      mark.className = 'hb-mark';
      mark.textContent = '⚠';
      current.appendChild(mark);
      var text = document.createElement('span');
      text.className = 'hb-t';
      current.appendChild(text);
      var fixBtn = document.createElement('button');
      fixBtn.type = 'button';
      fixBtn.className = 'tool hb-fix';
      fixBtn.setAttribute('data-hb-act', 'resolve-all');
      fixBtn.title = 'Probe live endpoints now and auto-verify/clear if passing';
      fixBtn.textContent = '⚡ One-Click Fix & Verify';
      current.appendChild(fixBtn);
      var diagnose = document.createElement('a');
      diagnose.className = 'tool';
      diagnose.href = '/doctor?issueId=ZH_HEALTH_CHECK_ISSUES&diagnose=1';
      diagnose.target = '_blank';
      diagnose.rel = 'noopener';
      diagnose.textContent = 'Diagnose';
      current.appendChild(diagnose);
      current.appendChild(button('doctor', '✚ Anchor Doctor', 'tool doctor'));
      current.appendChild(button('zombie', 'Zombie Hunter', 'tool'));
      var dismissBtn = document.createElement('button');
      dismissBtn.type = 'button';
      dismissBtn.className = 'tool hb-dismiss';
      dismissBtn.setAttribute('data-hb-act', 'dismiss');
      dismissBtn.title = 'Dismiss banner for this report';
      dismissBtn.setAttribute('aria-label', 'Dismiss health banner');
      dismissBtn.textContent = '✕';
      current.appendChild(dismissBtn);
      masthead.insertAdjacentElement('afterend', current);
    }
    wireBannerActions(current);
    var content = current.querySelector('.hb-t');
    if (content) {
      var heading = document.createElement('b');
      heading.textContent = 'Health check found issues';
      var children = [
        heading,
        document.createTextNode(' · ' + value.last_run + ' · Doctor can diagnose it')
      ];
      if (value.issues && value.issues.length) {
        var pills = document.createElement('span');
        pills.className = 'hb-pills';
        value.issues.slice(0, 3).forEach(function (iss) {
          var pill = document.createElement('span');
          pill.className = 'hb-pill';
          pill.textContent = plainIssueLabel(iss);
          pills.appendChild(pill);
        });
        children.push(pills);
      }
      content.replaceChildren.apply(content, children);
      content.title = details;
    }
    current.title = details;
    lastReport = value.last_run;
    lastSignature = signature;
  }

  function refresh() {
    if (document.hidden || !surface()) return Promise.resolve();
    if (pending) return pending;
    var controller = new AbortController();
    var timeout = window.setTimeout(function () { controller.abort(); }, 12000);
    pending = Promise.resolve().then(function () {
      var headers = getAuthHeaders();
      return fetch('/api/doctor/status', {
        credentials: 'same-origin',
        cache: 'no-store',
        headers: headers,
        signal: controller.signal
      });
    }).then(function (response) {
      if (!response.ok) throw new Error('Health status unavailable');
      return response.json();
    }).then(function (value) {
      var valid = report(value);
      if (valid) render(valid);
    }).catch(function () {
      // A failed read retains the last visible health indication.
    }).finally(function () {
      window.clearTimeout(timeout);
      pending = null;
    });
    return pending;
  }

  function start(settings) {
    if (settings && typeof settings === 'object') options = settings;
    var cur = banner();
    if (cur) wireBannerActions(cur);
    if (!started) {
      started = true;
      timer = window.setInterval(refresh, 15000);
      document.addEventListener('visibilitychange', function () {
        if (!document.hidden) refresh();
      });
      window.addEventListener('focus', refresh);
    }
    return refresh();
  }

  window.AnchorCaveHealth = { start: start, refresh: refresh, runOneClickFix: runOneClickFix };
})();
