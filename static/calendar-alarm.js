/* Anchor Calendar Event Alarm Coordinator (static/calendar-alarm.js)
 *
 * Provides multi-surface calendar event alarms across Anchor (static/app.html + Cave of Wonders):
 *   1. Visual flash in Anchor's persistent top bar (#bar / #anchorCalAlarmPill), Cave of Wonders
 *      banner (#anchorCaveTopAlarmBanner) + left rail Calendar button, and centered Alarm Window modal.
 *   2. Harmonic bell chime (Web Audio API + WAV fallback, unlocked on first user gesture).
 *   3. OS system notification (Web Notification API; auto-allowed in Anchor.exe WebView2) +
 *      dedicated popup window (/static/calendar-alarm.html?alarm_window=1) + taskbar flash in Anchor.exe.
 *   4. Synchronized "Go to" (jumps straight to Cave Calendar & opens the event dialogue) and "Exit"
 *      (dismisses & acknowledges across all tabs/popups and persists to .anchor/calendar-alarms.json).
 */
(function () {
  "use strict";

  // Child frames inside app.html delegate to the top-shell singleton coordinator.
  try {
    if (window.top && window.top !== window && window.top.AnchorCalendarAlarm) {
      window.top.AnchorCalendarAlarm.registerFrameWindow(window);
      window.AnchorCalendarAlarm = window.top.AnchorCalendarAlarm;
      return;
    }
  } catch (_crossOriginErr) {}

  if (window.AnchorCalendarAlarm && window.AnchorCalendarAlarm.__initialized) {
    return;
  }

  var LS_ACK_KEY = "anchor_cal_alarm_ack_v1";
  var LS_PREFS_KEY = "anchor_cal_alarm_prefs_v1";
  var BC_NAME = "anchor_calendar_alarm_v1";

  var state = {
    prefs: {
      enabled: true,
      lead_minutes: 5,
      sound_enabled: true,
      popup_enabled: true
    },
    acknowledged: {},
    events: [],
    activeAlarm: null,       // { key, event, timeRange, minsUntil, joinUrl, isTest }
    popupWin: null,
    chimeTimer: null,
    chimeCount: 0,
    frameWindows: [],
    audioCtx: null,
    fallbackWavUri: "",
    pollBusy: false
  };

  var bc = null;
  try {
    if (typeof BroadcastChannel === "function") {
      bc = new BroadcastChannel(BC_NAME);
    }
  } catch (_bcErr) {
    bc = null;
  }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function getAuthToken() {
    try {
      var t = localStorage.getItem("anchor_token") || "";
      if (t) return t.trim();
    } catch (_e) {}
    return "";
  }

  function authHeaders() {
    var h = { "Content-Type": "application/json" };
    var t = getAuthToken();
    if (t) {
      h["X-Anchor-Token"] = t;
      h["Authorization"] = "Bearer " + t;
    }
    return h;
  }

  function loadLocalState() {
    try {
      var rawAck = localStorage.getItem(LS_ACK_KEY);
      if (rawAck) {
        var parsedAck = JSON.parse(rawAck);
        if (parsedAck && typeof parsedAck === "object") {
          state.acknowledged = parsedAck;
        }
      }
    } catch (_e1) {}
    try {
      var rawPrefs = localStorage.getItem(LS_PREFS_KEY);
      if (rawPrefs) {
        var parsedPrefs = JSON.parse(rawPrefs);
        if (parsedPrefs && typeof parsedPrefs === "object") {
          mergePrefs(parsedPrefs);
        }
      }
    } catch (_e2) {}
  }

  function saveLocalAck() {
    try {
      var keys = Object.keys(state.acknowledged);
      if (keys.length > 300) {
        var trimmed = {};
        keys.slice(keys.length - 300).forEach(function (k) {
          trimmed[k] = state.acknowledged[k];
        });
        state.acknowledged = trimmed;
      }
      localStorage.setItem(LS_ACK_KEY, JSON.stringify(state.acknowledged));
    } catch (_e) {}
  }

  function mergePrefs(p) {
    if (!p || typeof p !== "object") return;
    if (typeof p.enabled === "boolean") state.prefs.enabled = p.enabled;
    if (p.lead_minutes !== undefined && p.lead_minutes !== null && !isNaN(Number(p.lead_minutes))) {
      state.prefs.lead_minutes = Math.max(0, Math.min(60, Math.round(Number(p.lead_minutes))));
    }
    if (typeof p.sound_enabled === "boolean") state.prefs.sound_enabled = p.sound_enabled;
    if (typeof p.popup_enabled === "boolean") state.prefs.popup_enabled = p.popup_enabled;
    try {
      localStorage.setItem(LS_PREFS_KEY, JSON.stringify(state.prefs));
    } catch (_e) {}
    syncCaveHeaderButton();
  }

  function syncCaveHeaderButton() {
    var wins = [window].concat(state.frameWindows || []);
    wins.forEach(function (w) {
      try {
        if (w && !w.closed && typeof w._syncCaveAlarmHeaderBtn === "function") {
          w._syncCaveAlarmHeaderBtn(state.prefs);
        }
      } catch (_e) {}
    });
  }

  function localNow() {
    var testNow = null;
    try {
      testNow = window.__ANCHOR_TEST_NOW;
      if (!testNow && state.frameWindows.length) {
        for (var i = 0; i < state.frameWindows.length; i++) {
          if (state.frameWindows[i] && !state.frameWindows[i].closed && state.frameWindows[i].__ANCHOR_TEST_NOW) {
            testNow = state.frameWindows[i].__ANCHOR_TEST_NOW;
            break;
          }
        }
      }
    } catch (_e) {}
    var dt = testNow instanceof Date ? testNow : (typeof testNow === "string" && testNow ? new Date(testNow) : new Date());
    if (isNaN(dt.getTime())) dt = new Date();
    var yr = dt.getFullYear();
    var mo = String(dt.getMonth() + 1).padStart(2, "0");
    var dy = String(dt.getDate()).padStart(2, "0");
    var mins = dt.getHours() * 60 + dt.getMinutes();
    return {
      date: dt,
      dateIso: yr + "-" + mo + "-" + dy,
      minsOfDay: mins
    };
  }

  function parseHm(str) {
    var m = String(str || "").trim().match(/^(\d{1,2}):(\d{2})/);
    if (!m) return null;
    var hh = parseInt(m[1], 10);
    var mm = parseInt(m[2], 10);
    if (hh < 0 || hh > 23 || mm < 0 || mm > 59) return null;
    return hh * 60 + mm;
  }

  function fmt12h(mins) {
    var total = ((mins % 1440) + 1440) % 1440;
    var hh24 = Math.floor(total / 60);
    var mm = String(total % 60).padStart(2, "0");
    var ampm = hh24 >= 12 ? "PM" : "AM";
    var hh12 = hh24 % 12 || 12;
    return hh12 + ":" + mm + " " + ampm;
  }

  function extractJoinUrl(ev) {
    if (!ev || typeof ev !== "object") return "";
    if (ev.join_url && /^https?:\/\//i.test(String(ev.join_url))) return String(ev.join_url);
    if (Array.isArray(ev.links)) {
      for (var i = 0; i < ev.links.length; i++) {
        var lk = ev.links[i];
        var u = lk && typeof lk === "object" ? lk.url : lk;
        if (u && /^https?:\/\//i.test(String(u))) return String(u);
      }
    }
    var blob = [ev.location, ev.description, ev.title].join("\n");
    var m = blob.match(/https?:\/\/[^\s<>"')]+/i);
    return m ? m[0].replace(/[.,;:!?)>\]]+$/, "") : "";
  }

  function normalizeEventTiming(ev) {
    if (!ev || typeof ev !== "object") return null;
    var title = String(ev.title || "").trim();
    if (!title) return null;
    var tLow = title.toLowerCase();
    if (tLow.indexOf("canceled:") === 0 || tLow.indexOf("cancelled:") === 0) return null;
    if (ev.is_followup_marker || ev.is_marker) return null;
    var rsvp = String(ev.rsvp_status || "").toLowerCase();
    if (rsvp === "declined") return null;
    var evDate = String(ev.date || "").slice(0, 10);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(evDate)) return null;

    var stRaw = String(ev.start_time || "").trim();
    var enRaw = String(ev.end_time || "").trim();
    var tLbl = String(ev.time_label || "").trim();
    if (stRaw.toLowerCase() === "marker" || stRaw.toLowerCase().indexOf("all") === 0) {
      if (tLbl.indexOf(":") >= 0 && stRaw.toLowerCase() !== "marker") {
        var found = tLbl.match(/(\d{1,2}:\d{2})/g);
        if (found && found.length) {
          stRaw = found[0];
          if (found.length >= 2 && !enRaw) enRaw = found[1];
        } else {
          return null;
        }
      } else {
        return null;
      }
    }
    var startMins = parseHm(stRaw);
    if (startMins === null) return null;
    var endMins = parseHm(enRaw);
    if (endMins === null || endMins <= startMins) {
      var dur = parseInt(ev.duration_mins, 10);
      endMins = startMins + (dur > 0 ? dur : 60);
    }
    var stHm = String(Math.floor(startMins / 60)).padStart(2, "0") + ":" + String(startMins % 60).padStart(2, "0");
    var enHm = String(Math.floor((endMins % 1440) / 60)).padStart(2, "0") + ":" + String(endMins % 60).padStart(2, "0");
    var baseId = String(ev.uid || ev.id || title.toLowerCase()).trim();
    var key = baseId + "@" + evDate + "T" + stHm;
    return {
      key: key,
      uid: String(ev.uid || ev.id || ""),
      title: title,
      date: evDate,
      startHm: stHm,
      endHm: enHm,
      startMins: startMins,
      endMins: endMins,
      timeRange: fmt12h(startMins) + " \u2013 " + fmt12h(endMins),
      location: String(ev.location || "").trim(),
      source: String((ev.calendars && ev.calendars.length ? ev.calendars.join(" + ") : (ev.calendar_badge || ev.project_name || "Calendar"))).trim(),
      joinUrl: extractJoinUrl(ev),
      raw: ev
    };
  }

  // ── Audio Chime (Web Audio API + inline WAV fallback) ─────────────────────
  function unlockAudio() {
    try {
      var AC = window.AudioContext || window.webkitAudioContext;
      if (AC && !state.audioCtx) {
        state.audioCtx = new AC();
      }
      if (state.audioCtx && state.audioCtx.state === "suspended") {
        state.audioCtx.resume().catch(function () {});
      }
    } catch (_e) {}
    try {
      if (typeof Notification !== "undefined" && Notification.permission === "default") {
        Notification.requestPermission().catch(function () {});
      }
    } catch (_nErr) {}
  }

  function buildFallbackWavDataUri() {
    if (state.fallbackWavUri) return state.fallbackWavUri;
    try {
      var sampleRate = 8000;
      var durationSec = 0.65;
      var numSamples = Math.floor(sampleRate * durationSec);
      var bytes = new Uint8Array(44 + numSamples * 2);
      var view = new DataView(bytes.buffer);
      function writeStr(off, s) {
        for (var i = 0; i < s.length; i++) bytes[off + i] = s.charCodeAt(i);
      }
      writeStr(0, "RIFF");
      view.setUint32(4, 36 + numSamples * 2, true);
      writeStr(8, "WAVE");
      writeStr(12, "fmt ");
      view.setUint32(16, 16, true);
      view.setUint16(20, 1, true);
      view.setUint16(22, 1, true);
      view.setUint32(24, sampleRate, true);
      view.setUint32(28, sampleRate * 2, true);
      view.setUint16(32, 2, true);
      view.setUint16(34, 16, true);
      writeStr(36, "data");
      view.setUint32(40, numSamples * 2, true);
      for (var n = 0; n < numSamples; n++) {
        var t = n / sampleRate;
        var freq = t < 0.22 ? 659.25 : (t < 0.42 ? 783.99 : 1046.5);
        var env = Math.exp(-3.8 * (t % 0.22));
        var sample = Math.sin(2 * Math.PI * freq * t) * 0.38 * env;
        view.setInt16(44 + n * 2, Math.max(-32767, Math.min(32767, Math.floor(sample * 32767))), true);
      }
      var bin = "";
      for (var j = 0; j < bytes.length; j++) bin += String.fromCharCode(bytes[j]);
      state.fallbackWavUri = "data:audio/wav;base64," + btoa(bin);
    } catch (_e) {
      state.fallbackWavUri = "";
    }
    return state.fallbackWavUri;
  }

  function playChime() {
    if (state.prefs.sound_enabled === false) return false;
    var playedWebAudio = false;
    try {
      var AC = window.AudioContext || window.webkitAudioContext;
      if (AC) {
        if (!state.audioCtx) state.audioCtx = new AC();
        var ctx = state.audioCtx;
        if (ctx.state === "suspended") {
          ctx.resume().catch(function () {});
        }
        if (ctx.state === "running") {
          var now = ctx.currentTime;
          var notes = [
            { f: 523.25, t: 0.0, d: 0.34, g: 0.16 },
            { f: 659.25, t: 0.14, d: 0.36, g: 0.16 },
            { f: 783.99, t: 0.28, d: 0.42, g: 0.17 },
            { f: 1046.5, t: 0.44, d: 0.65, g: 0.19 },
            { f: 783.99, t: 0.92, d: 0.28, g: 0.11 },
            { f: 1046.5, t: 1.08, d: 0.68, g: 0.16 }
          ];
          notes.forEach(function (n) {
            var osc = ctx.createOscillator();
            var gain = ctx.createGain();
            osc.type = "triangle";
            osc.frequency.setValueAtTime(n.f, now + n.t);
            gain.gain.setValueAtTime(0.0001, now + n.t);
            gain.gain.exponentialRampToValueAtTime(n.g, now + n.t + 0.025);
            gain.gain.exponentialRampToValueAtTime(0.0001, now + n.t + n.d);
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.start(now + n.t);
            osc.stop(now + n.t + n.d + 0.03);
          });
          playedWebAudio = true;
        }
      }
    } catch (_waErr) {}

    if (!playedWebAudio) {
      try {
        var uri = buildFallbackWavDataUri();
        if (uri && typeof Audio === "function") {
          var a = new Audio(uri);
          a.volume = 0.7;
          var p = a.play();
          if (p && typeof p.catch === "function") p.catch(function () {});
          playedWebAudio = true;
        }
      } catch (_auErr) {}
    }
    return playedWebAudio;
  }

  function stopChimeLoop() {
    if (state.chimeTimer) {
      clearInterval(state.chimeTimer);
      state.chimeTimer = null;
    }
    state.chimeCount = 0;
  }

  // ── UI Rendering (Styles + Top Shell Pill + Cave Banner + Modal Window) ───
  function ensureStylesInjected(doc) {
    if (!doc || !doc.head || doc.getElementById("anchorCalAlarmStyles")) return;
    var st = doc.createElement("style");
    st.id = "anchorCalAlarmStyles";
    st.textContent =
      "@keyframes anchorAlarmFlashEdge{0%,100%{border-color:#fbbf24;box-shadow:0 0 0 1px rgba(251,191,36,.45),0 8px 28px rgba(0,0,0,.55)}50%{border-color:#ef4444;box-shadow:0 0 0 2px rgba(239,68,68,.55),0 8px 28px rgba(0,0,0,.55)}}" +
      "@keyframes anchorAlarmPillPulse{0%,100%{background:rgba(245,158,11,.24);border-color:#fbbf24;color:#fef3c7}50%{background:rgba(239,68,68,.30);border-color:#f87171;color:#ffffff}}" +
      "#bar.cal-alarm-flashing{border-bottom-color:#fbbf24 !important;box-shadow:inset 0 -2px 0 #f59e0b}" +
      "#anchorCalAlarmPill{flex:none;display:inline-flex;align-items:center;gap:6px;margin:7px 6px 0 0;padding:3px 9px;border:1px solid #fbbf24;border-radius:999px;font:700 11.5px 'Segoe UI',system-ui,sans-serif;animation:anchorAlarmPillPulse 1.05s ease-in-out infinite;-webkit-app-region:no-drag;app-region:no-drag}" +
      "#anchorCalAlarmPill[hidden]{display:none !important}" +
      "#anchorCalAlarmPill .ca-title{max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}" +
      ".ca-act-btn{border:1px solid rgba(255,255,255,.32);border-radius:6px;padding:2px 8px;font:700 11px 'Segoe UI',system-ui,sans-serif;cursor:pointer;color:#0f172a;background:#fbbf24}" +
      ".ca-act-btn:hover{background:#fde68a}" +
      ".ca-act-btn.exit{background:rgba(15,23,42,.75);color:#fca5a5;border-color:rgba(248,113,113,.55)}" +
      ".ca-act-btn.exit:hover{background:rgba(127,29,29,.65);color:#fff}" +
      ".ca-act-btn.join{background:rgba(56,189,248,.22);color:#e0f2fe;border-color:rgba(56,189,248,.7);text-decoration:none}" +
      "#anchorCalAlarmModal,#anchorCalAlarmPrefsModal{position:fixed;inset:0;z-index:2147483000;display:flex;align-items:center;justify-content:center;background:rgba(6,10,18,.68);backdrop-filter:blur(3px);padding:16px}" +
      "#anchorCalAlarmModal[hidden],#anchorCalAlarmPrefsModal[hidden]{display:none !important}" +
      ".ca-modal-card{width:min(460px,100%);background:#131924;color:#e6ebf2;border:2px solid #fbbf24;border-radius:14px;padding:18px 20px;font:13px/1.45 'Segoe UI',system-ui,sans-serif;animation:anchorAlarmFlashEdge 1.15s ease-in-out infinite}" +
      ".ca-prefs-card{width:min(410px,100%);background:#131924;color:#e6ebf2;border:1px solid #38465e;border-radius:13px;padding:16px 18px;font:13px/1.45 'Segoe UI',system-ui,sans-serif;box-shadow:0 14px 36px rgba(0,0,0,.6)}" +
      "@media(prefers-reduced-motion:reduce){#anchorCalAlarmPill,.ca-modal-card{animation:none !important}}";
    doc.head.appendChild(st);
  }

  function countdownBadgeText(alarm) {
    if (!alarm) return "Starting soon";
    var m = alarm.minsUntil;
    if (m > 1) return "Starts in " + m + " min";
    if (m === 1) return "Starts in 1 min";
    if (m === 0) return "Starting now";
    return "In progress (" + Math.abs(m) + "m in)";
  }

  function renderTopBarAndModal() {
    ensureStylesInjected(document);
    var alarm = state.activeAlarm;
    var bar = document.getElementById("bar");
    if (bar) {
      bar.classList.toggle("cal-alarm-flashing", !!alarm);
      var pill = document.getElementById("anchorCalAlarmPill");
      if (!pill) {
        pill = document.createElement("div");
        pill.id = "anchorCalAlarmPill";
        pill.hidden = true;
        var anchorRef = document.getElementById("bar-version-pill") || bar.querySelector(".panes") || bar.lastElementChild;
        if (anchorRef) bar.insertBefore(pill, anchorRef);
        else bar.appendChild(pill);
      }
      if (!alarm) {
        pill.hidden = true;
        pill.innerHTML = "";
      } else {
        pill.hidden = false;
        pill.innerHTML =
          "<span>\ud83d\udd14 " + esc(countdownBadgeText(alarm)) + ":</span>" +
          "<span class=\"ca-title\" title=\"" + esc(alarm.title + " (" + alarm.timeRange + ")") + "\">" + esc(alarm.title) + "</span>" +
          "<button type=\"button\" class=\"ca-act-btn\" data-cal-alarm-act=\"goto\" title=\"Go to Calendar Event in Cave of Wonders\">Go to</button>" +
          "<button type=\"button\" class=\"ca-act-btn exit\" data-cal-alarm-act=\"exit\" title=\"Dismiss alarm\">Exit</button>";
      }
    }

    var modal = document.getElementById("anchorCalAlarmModal");
    if (!modal) {
      modal = document.createElement("div");
      modal.id = "anchorCalAlarmModal";
      modal.setAttribute("role", "alertdialog");
      modal.setAttribute("aria-modal", "true");
      modal.hidden = true;
      document.body.appendChild(modal);
    }
    if (!alarm) {
      modal.hidden = true;
      modal.innerHTML = "";
    } else {
      var joinBtn = alarm.joinUrl
        ? "<a class=\"ca-act-btn join\" href=\"" + esc(alarm.joinUrl) + "\" target=\"_blank\" rel=\"noopener noreferrer\">\ud83d\udd17 Join Meeting \u2197</a>"
        : "";
      var locRow = alarm.location
        ? "<div style=\"margin-top:6px;font-size:12px;color:#cbd5e1\">\ud83d\udccd " + esc(alarm.location) + "</div>"
        : "";
      modal.hidden = false;
      modal.innerHTML =
        "<div class=\"ca-modal-card\">" +
          "<div style=\"display:flex;align-items:center;justify-content:space-between;gap:8px\">" +
            "<span style=\"font-size:11px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:#fbbf24\">\ud83d\udd14 Anchor Calendar Alarm &middot; " + esc(countdownBadgeText(alarm)) + "</span>" +
            "<span style=\"font-size:11px;color:#94a3b8;border:1px solid #2d384c;border-radius:999px;padding:1px 8px\">" + esc(alarm.source || "Calendar") + "</span>" +
          "</div>" +
          "<div style=\"margin-top:9px;font-size:17px;font-weight:750;color:#f8fafc;line-height:1.3\">" + esc(alarm.title) + "</div>" +
          "<div style=\"margin-top:5px;font-size:13px;font-weight:650;color:#fde68a\">\u23f0 " + esc(alarm.timeRange) + " &middot; " + esc(alarm.date) + "</div>" +
          locRow +
          "<div style=\"display:flex;align-items:center;justify-content:flex-end;gap:8px;flex-wrap:wrap;margin-top:16px;padding-top:12px;border-top:1px solid #263144\">" +
            joinBtn +
            "<button type=\"button\" class=\"ca-act-btn\" data-cal-alarm-act=\"goto\" style=\"padding:6px 14px;font-size:12.5px\">\ud83d\udcc5 Go to</button>" +
            "<button type=\"button\" class=\"ca-act-btn exit\" data-cal-alarm-act=\"exit\" style=\"padding:6px 14px;font-size:12.5px\">\u2715 Exit</button>" +
          "</div>" +
        "</div>";
    }

    renderCaveFrames();
  }

  function renderCaveFrames() {
    var alarm = state.activeAlarm;
    var wins = [window].concat(state.frameWindows || []);
    wins.forEach(function (w) {
      try {
        if (!w || w.closed || !w.document) return;
        ensureStylesInjected(w.document);
        var railCalBtn = w.document.querySelector('#railNav button[data-rail="calendar"]');
        if (railCalBtn) {
          railCalBtn.classList.toggle("cal-alarm-rail-flash", !!alarm);
        }
        var banner = w.document.getElementById("anchorCaveTopAlarmBanner");
        if (!banner) return;
        if (!alarm) {
          banner.hidden = true;
          banner.innerHTML = "";
        } else {
          var joinHtml = alarm.joinUrl
            ? "<a class=\"ca-act-btn join\" href=\"" + esc(alarm.joinUrl) + "\" target=\"_blank\" rel=\"noopener noreferrer\">\ud83d\udd17 Join \u2197</a>"
            : "";
          banner.hidden = false;
          banner.innerHTML =
            "<div style=\"display:flex;align-items:center;gap:10px;flex-wrap:wrap;min-width:0\">" +
              "<span style=\"font-weight:800;color:#fde68a\">\ud83d\udd14 " + esc(countdownBadgeText(alarm)) + "</span>" +
              "<b style=\"font-size:13.5px;color:#fff\">" + esc(alarm.title) + "</b>" +
              "<span style=\"font-size:12px;color:#cbd5e1\">(" + esc(alarm.timeRange) + (alarm.location ? " &middot; " + esc(alarm.location).slice(0, 60) : "") + ")</span>" +
            "</div>" +
            "<div style=\"display:inline-flex;align-items:center;gap:7px;flex-wrap:wrap\">" +
              joinHtml +
              "<button type=\"button\" class=\"ca-act-btn\" data-cal-alarm-act=\"goto\">\ud83d\udcc5 Go to</button>" +
              "<button type=\"button\" class=\"ca-act-btn exit\" data-cal-alarm-act=\"exit\">\u2715 Exit</button>" +
            "</div>";
        }
      } catch (_e) {}
    });
  }

  function buildPopupUrl(alarm, chimePlayed) {
    var p = new URLSearchParams();
    p.set("alarm_window", "1");
    p.set("key", alarm.key || "");
    p.set("uid", alarm.uid || "");
    p.set("title", alarm.title || "");
    p.set("date", alarm.date || "");
    p.set("start", alarm.startHm || "");
    p.set("end", alarm.endHm || "");
    p.set("range", alarm.timeRange || "");
    p.set("countdown", countdownBadgeText(alarm));
    p.set("loc", alarm.location || "");
    p.set("source", alarm.source || "Calendar");
    p.set("join", alarm.joinUrl || "");
    p.set("sound", state.prefs.sound_enabled === false ? "0" : "1");
    p.set("chime_played", chimePlayed ? "1" : "0");
    return "/static/calendar-alarm.html?" + p.toString();
  }

  function fireSystemNotifications(alarm, chimePlayed) {
    var popupUrl = buildPopupUrl(alarm, chimePlayed);
    // 1. OS Toast Notification (Web Notification API — auto-allowed in Anchor.exe WebView2)
    try {
      if (typeof Notification !== "undefined" && Notification.permission === "granted") {
        var bodyLines = [alarm.timeRange + " (" + countdownBadgeText(alarm) + ")"];
        if (alarm.location) bodyLines.push("\ud83d\udccd " + alarm.location);
        var notif = new Notification("\ud83d\udd14 " + alarm.title, {
          body: bodyLines.join("\n"),
          icon: "/vendor/brand/anchor-tab-48.png",
          tag: "anchor-cal-" + alarm.key,
          requireInteraction: true
        });
        notif.onclick = function () {
          try { window.focus(); } catch (_fErr) {}
          try { notif.close(); } catch (_cErr) {}
          goToActiveAlarm(alarm.key);
        };
      }
    } catch (_nErr) {}

    // 2. Desktop Host Taskbar Flash / Attention (Anchor.exe pywebview bridge)
    try {
      if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.alarm_notify === "function") {
        window.pywebview.api.alarm_notify({
          key: alarm.key,
          title: alarm.title,
          time_range: alarm.timeRange,
          url: popupUrl
        });
      }
    } catch (_pwErr) {}

    // 3. Dedicated System Popup Window (with Exit & Go to)
    if (state.prefs.popup_enabled !== false) {
      try {
        var w = window.open(
          popupUrl,
          "AnchorCalendarAlarmPopup",
          "popup=yes,width=460,height=340,menubar=no,toolbar=no,location=no,status=no,resizable=yes"
        );
        if (w && w !== window) {
          state.popupWin = w;
          try { w.focus(); } catch (_wfErr) {}
        }
      } catch (_popErr) {}
    }
  }

  function activateAlarm(alarmObj) {
    if (!alarmObj || !alarmObj.key) return;
    if (state.activeAlarm && state.activeAlarm.key === alarmObj.key) {
      state.activeAlarm.minsUntil = alarmObj.minsUntil;
      renderTopBarAndModal();
      return;
    }
    state.activeAlarm = alarmObj;
    stopChimeLoop();
    var chimePlayed = playChime();
    state.chimeCount = 1;
    if (state.prefs.sound_enabled !== false) {
      state.chimeTimer = setInterval(function () {
        if (!state.activeAlarm || state.chimeCount >= 3) {
          stopChimeLoop();
          return;
        }
        state.chimeCount += 1;
        playChime();
      }, 25000);
    }
    renderTopBarAndModal();
    fireSystemNotifications(alarmObj, chimePlayed);
  }

  function closePopupIfOpen() {
    if (state.popupWin) {
      try {
        if (!state.popupWin.closed) state.popupWin.close();
      } catch (_e) {}
      state.popupWin = null;
    }
  }

  function persistAckToServer(alarm, via) {
    if (!alarm || alarm.isTest) return;
    fetch("/api/steward/comms", {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({
        action: "calendar_alarm_ack",
        sub_action: via === "goto" ? "goto" : "ack",
        via: via || "dismiss",
        alarm_key: alarm.key,
        uid: alarm.uid || "",
        title: alarm.title || "",
        date: alarm.date || "",
        start_time: alarm.startHm || ""
      })
    }).catch(function () {});
  }

  function broadcastAction(type, key, evPayload) {
    if (!bc) return;
    try {
      bc.postMessage({ type: type, key: key, event: evPayload || null, ts: Date.now() });
    } catch (_e) {}
  }

  function dismissActiveAlarm(targetKey, via, skipBroadcast) {
    var cur = state.activeAlarm;
    var k = targetKey || (cur && cur.key) || "";
    if (k && (!cur || !cur.isTest)) {
      state.acknowledged[k] = {
        at: new Date().toISOString(),
        via: via || "exit"
      };
      saveLocalAck();
    }
    if (cur && (!k || cur.key === k)) {
      persistAckToServer(cur, via || "exit");
      state.activeAlarm = null;
    }
    stopChimeLoop();
    closePopupIfOpen();
    renderTopBarAndModal();
    if (!skipBroadcast && k) {
      broadcastAction("alarm_dismissed", k, null);
    }
  }

  function routeToCalendarEvent(evData) {
    var ev = evData || {};
    try { window.focus(); } catch (_e) {}
    if (window.ANCHOR_APP && typeof window.ANCHOR_APP.goToCalendarEvent === "function") {
      window.ANCHOR_APP.goToCalendarEvent(ev);
      return;
    }
    if (typeof window._focusCaveCalendarEvent === "function") {
      window._focusCaveCalendarEvent(ev);
      return;
    }
    for (var i = 0; i < state.frameWindows.length; i++) {
      var fw = state.frameWindows[i];
      try {
        if (fw && !fw.closed && typeof fw._focusCaveCalendarEvent === "function") {
          fw._focusCaveCalendarEvent(ev);
          return;
        }
      } catch (_fe) {}
    }
    var p = new URLSearchParams();
    if (ev.uid) p.set("cal_goto_uid", ev.uid);
    if (ev.title) p.set("cal_goto_title", ev.title);
    if (ev.date) p.set("cal_goto_date", ev.date);
    if (ev.start_time || ev.startHm) p.set("cal_goto_start", ev.start_time || ev.startHm);
    location.href = "/?" + p.toString();
  }

  function goToActiveAlarm(targetKey, explicitEv, skipBroadcast) {
    var cur = state.activeAlarm;
    var evObj = explicitEv || (cur && (cur.raw || {
      uid: cur.uid,
      title: cur.title,
      date: cur.date,
      start_time: cur.startHm,
      end_time: cur.endHm,
      location: cur.location,
      calendar_badge: cur.source
    })) || null;
    var k = targetKey || (cur && cur.key) || "";
    dismissActiveAlarm(k, "goto", true);
    if (!skipBroadcast && k) {
      broadcastAction("alarm_goto", k, evObj);
    }
    if (evObj) {
      routeToCalendarEvent(evObj);
    }
  }

  function evaluateEvents() {
    if (state.prefs.enabled === false) {
      if (state.activeAlarm && !state.activeAlarm.isTest) {
        state.activeAlarm = null;
        stopChimeLoop();
        closePopupIfOpen();
        renderTopBarAndModal();
      }
      return;
    }
    var clk = localNow();
    var lead = state.prefs.lead_minutes;
    var dueCandidate = null;

    for (var i = 0; i < state.events.length; i++) {
      var info = normalizeEventTiming(state.events[i]);
      if (!info || info.date !== clk.dateIso) continue;
      if (state.acknowledged[info.key]) continue;
      var minsUntil = info.startMins - clk.minsOfDay;
      var latestFireMins = Math.min(info.endMins, info.startMins + 15);
      if (minsUntil <= lead && clk.minsOfDay <= latestFireMins) {
        info.minsUntil = minsUntil;
        if (!dueCandidate || info.startMins < dueCandidate.startMins) {
          dueCandidate = info;
        }
      }
    }

    if (dueCandidate) {
      activateAlarm(dueCandidate);
    } else if (state.activeAlarm && !state.activeAlarm.isTest) {
      // Auto-clear if event window passed or was acknowledged on another surface
      if (state.acknowledged[state.activeAlarm.key] || clk.minsOfDay > Math.min(state.activeAlarm.endMins, state.activeAlarm.startMins + 20)) {
        state.activeAlarm = null;
        stopChimeLoop();
        closePopupIfOpen();
        renderTopBarAndModal();
      }
    }
  }

  function ingestServerPayload(d) {
    if (!d || typeof d !== "object") return;
    if (d.calendar_alarms && typeof d.calendar_alarms === "object") {
      var ca = d.calendar_alarms;
      mergePrefs(ca);
      if (ca.acknowledged && typeof ca.acknowledged === "object") {
        Object.keys(ca.acknowledged).forEach(function (k) {
          state.acknowledged[k] = ca.acknowledged[k];
        });
        saveLocalAck();
      }
    }
    var evs = Array.isArray(d.calendar_events_all)
      ? d.calendar_events_all
      : (Array.isArray(d.calendar_events) ? d.calendar_events : null);
    if (evs) {
      state.events = evs;
    }
    evaluateEvents();
  }

  function pollServerAlarms() {
    if (state.pollBusy) return;
    state.pollBusy = true;
    fetch("/api/steward/comms?view=calendar_alarms", {
      headers: authHeaders(),
      cache: "no-store",
      credentials: "same-origin"
    })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (d && d.ok) ingestServerPayload(d);
      })
      .catch(function () {})
      .finally(function () {
        state.pollBusy = false;
      });
  }

  // ── Settings Modal ────────────────────────────────────────────────────────
  function openSettingsModal() {
    unlockAudio();
    ensureStylesInjected(document);
    var modal = document.getElementById("anchorCalAlarmPrefsModal");
    if (!modal) {
      modal = document.createElement("div");
      modal.id = "anchorCalAlarmPrefsModal";
      document.body.appendChild(modal);
    }
    var leadOpts = [0, 2, 5, 10, 15].map(function (m) {
      var sel = state.prefs.lead_minutes === m ? " selected" : "";
      var lbl = m === 0 ? "At event start (0 min)" : (m + " minutes before start");
      return "<option value=\"" + m + "\"" + sel + ">" + lbl + "</option>";
    }).join("");
    modal.hidden = false;
    modal.innerHTML =
      "<div class=\"ca-prefs-card\">" +
        "<div style=\"display:flex;align-items:center;justify-content:space-between;margin-bottom:10px\">" +
          "<b style=\"font-size:14px;color:#fde68a\">\ud83d\udd14 Calendar Event Alarm Settings</b>" +
          "<button type=\"button\" class=\"ca-act-btn exit\" data-cal-alarm-prefs-close=\"1\">\u2715</button>" +
        "</div>" +
        "<label style=\"display:flex;align-items:center;gap:8px;margin:8px 0;cursor:pointer\">" +
          "<input type=\"checkbox\" id=\"caPrefEnabled\"" + (state.prefs.enabled !== false ? " checked" : "") + ">" +
          "<span>Enable Calendar Event Alarms (flash in Anchor)</span>" +
        "</label>" +
        "<label style=\"display:flex;align-items:center;gap:8px;margin:8px 0;cursor:pointer\">" +
          "<input type=\"checkbox\" id=\"caPrefSound\"" + (state.prefs.sound_enabled !== false ? " checked" : "") + ">" +
          "<span>Play audible harmonic chime</span>" +
        "</label>" +
        "<label style=\"display:flex;align-items:center;gap:8px;margin:8px 0;cursor:pointer\">" +
          "<input type=\"checkbox\" id=\"caPrefPopup\"" + (state.prefs.popup_enabled !== false ? " checked" : "") + ">" +
          "<span>Open system notification &amp; popup alarm window</span>" +
        "</label>" +
        "<div style=\"margin:10px 0\">" +
          "<label for=\"caPrefLead\" style=\"display:block;font-size:11.5px;color:#94a3b8;margin-bottom:4px\">Lead time before scheduled start:</label>" +
          "<select id=\"caPrefLead\" style=\"width:100%;padding:6px 8px;border-radius:7px;background:#0c111a;color:#f8fafc;border:1px solid #334155\">" +
            leadOpts +
          "</select>" +
        "</div>" +
        "<div style=\"display:flex;align-items:center;justify-content:space-between;gap:8px;margin-top:14px;padding-top:10px;border-top:1px solid #263144\">" +
          "<button type=\"button\" class=\"ca-act-btn join\" data-cal-alarm-prefs-test=\"1\">\ud83d\udd14 Test Alarm</button>" +
          "<button type=\"button\" class=\"ca-act-btn\" data-cal-alarm-prefs-save=\"1\">Save Settings</button>" +
        "</div>" +
      "</div>";
  }

  function saveSettingsFromModal() {
    var modal = document.getElementById("anchorCalAlarmPrefsModal");
    if (!modal) return;
    var enEl = document.getElementById("caPrefEnabled");
    var sdEl = document.getElementById("caPrefSound");
    var ppEl = document.getElementById("caPrefPopup");
    var ldEl = document.getElementById("caPrefLead");
    var nextPrefs = {
      enabled: enEl ? !!enEl.checked : true,
      sound_enabled: sdEl ? !!sdEl.checked : true,
      popup_enabled: ppEl ? !!ppEl.checked : true,
      lead_minutes: ldEl ? parseInt(ldEl.value, 10) : 5
    };
    mergePrefs(nextPrefs);
    modal.hidden = true;
    fetch("/api/steward/comms", {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({
        action: "calendar_alarm_prefs",
        sub_action: "prefs",
        enabled: state.prefs.enabled,
        sound_enabled: state.prefs.sound_enabled,
        popup_enabled: state.prefs.popup_enabled,
        lead_minutes: state.prefs.lead_minutes
      })
    }).catch(function () {});
    evaluateEvents();
  }

  function triggerTestAlarm(optionalCommsData) {
    unlockAudio();
    if (optionalCommsData) ingestServerPayload(optionalCommsData);
    var clk = localNow();
    var pick = null;
    for (var i = 0; i < state.events.length; i++) {
      var cand = normalizeEventTiming(state.events[i]);
      if (cand && cand.date >= clk.dateIso) {
        pick = cand;
        break;
      }
    }
    if (!pick) {
      var stM = clk.minsOfDay + 5;
      var enM = stM + 30;
      pick = {
        key: "test-alarm@" + Date.now(),
        uid: "",
        title: "Upcoming Calendar Appointment (Test Alarm)",
        date: clk.dateIso,
        startHm: String(Math.floor((stM % 1440) / 60)).padStart(2, "0") + ":" + String(stM % 60).padStart(2, "0"),
        endHm: String(Math.floor((enM % 1440) / 60)).padStart(2, "0") + ":" + String(enM % 60).padStart(2, "0"),
        startMins: stM,
        endMins: enM,
        timeRange: fmt12h(stM) + " \u2013 " + fmt12h(enM),
        location: "Anchor Calendar",
        source: "Anchor Alarm Test",
        joinUrl: "",
        raw: {
          uid: "",
          title: "Upcoming Calendar Appointment (Test Alarm)",
          date: clk.dateIso,
          start_time: String(Math.floor((stM % 1440) / 60)).padStart(2, "0") + ":" + String(stM % 60).padStart(2, "0")
        }
      };
    } else {
      pick = Object.assign({}, pick, { key: "test-alarm@" + Date.now() });
    }
    pick.isTest = true;
    pick.minsUntil = typeof pick.minsUntil === "number" ? pick.minsUntil : state.prefs.lead_minutes;
    activateAlarm(pick);
  }

  function showModalFromUrl(rawUrl) {
    try {
      var u = new URL(rawUrl, location.origin);
      var q = u.searchParams;
      var alarmObj = {
        key: q.get("key") || ("popup@" + Date.now()),
        uid: q.get("uid") || "",
        title: q.get("title") || "Calendar Event",
        date: q.get("date") || localNow().dateIso,
        startHm: q.get("start") || "",
        endHm: q.get("end") || "",
        timeRange: q.get("range") || q.get("start") || "Scheduled",
        location: q.get("loc") || "",
        source: q.get("source") || "Calendar",
        joinUrl: q.get("join") || "",
        minsUntil: 0,
        isTest: String(q.get("key") || "").indexOf("test-alarm@") === 0
      };
      if (!state.activeAlarm) {
        state.activeAlarm = alarmObj;
      }
      renderTopBarAndModal();
    } catch (_e) {}
  }

  function wireDocumentEvents(doc) {
    if (!doc || doc.__anchorCalAlarmWired) return;
    doc.__anchorCalAlarmWired = true;
    doc.addEventListener("pointerdown", unlockAudio, { passive: true });
    doc.addEventListener("keydown", unlockAudio, { passive: true });
    doc.addEventListener("click", function (ev) {
      var actBtn = ev.target && ev.target.closest ? ev.target.closest("[data-cal-alarm-act]") : null;
      if (actBtn) {
        ev.preventDefault();
        ev.stopPropagation();
        var act = actBtn.getAttribute("data-cal-alarm-act");
        if (act === "goto") {
          goToActiveAlarm();
        } else {
          dismissActiveAlarm(null, "exit");
        }
        return;
      }
      if (ev.target && ev.target.closest && ev.target.closest("[data-cal-alarm-prefs-close]")) {
        ev.preventDefault();
        var pm = document.getElementById("anchorCalAlarmPrefsModal");
        if (pm) pm.hidden = true;
        return;
      }
      if (ev.target && ev.target.closest && ev.target.closest("[data-cal-alarm-prefs-save]")) {
        ev.preventDefault();
        saveSettingsFromModal();
        return;
      }
      if (ev.target && ev.target.closest && ev.target.closest("[data-cal-alarm-prefs-test]")) {
        ev.preventDefault();
        saveSettingsFromModal();
        triggerTestAlarm();
      }
    });
  }

  function registerFrameWindow(fw) {
    if (!fw || fw === window) return;
    state.frameWindows = state.frameWindows.filter(function (w) { return w && !w.closed && w !== fw; });
    state.frameWindows.push(fw);
    try {
      if (fw.document) wireDocumentEvents(fw.document);
      if (fw.ANCHOR_CAVE_COMMS_BOOT) ingestServerPayload(fw.ANCHOR_CAVE_COMMS_BOOT);
    } catch (_e) {}
    syncCaveHeaderButton();
    renderCaveFrames();
  }

  if (bc) {
    bc.onmessage = function (ev) {
      var msg = ev && ev.data;
      if (!msg || typeof msg !== "object") return;
      if (msg.type === "alarm_dismissed") {
        dismissActiveAlarm(msg.key || "", "exit", true);
      } else if (msg.type === "alarm_goto") {
        goToActiveAlarm(msg.key || "", msg.event || null, true);
      }
    };
  }

  window.addEventListener("message", function (ev) {
    if (ev.origin !== location.origin || !ev.data || typeof ev.data !== "object") return;
    if (ev.data.proto !== "anchor-calendar-alarm") return;
    if (ev.data.action === "exit") {
      dismissActiveAlarm(ev.data.key || "", "exit");
    } else if (ev.data.action === "goto") {
      goToActiveAlarm(ev.data.key || "", ev.data.event || null);
    }
  });

  loadLocalState();
  wireDocumentEvents(document);
  if (window.ANCHOR_CAVE_COMMS_BOOT) {
    ingestServerPayload(window.ANCHOR_CAVE_COMMS_BOOT);
  }

  setTimeout(pollServerAlarms, 900);
  setInterval(pollServerAlarms, 20000);
  setInterval(evaluateEvents, 5000);

  window.AnchorCalendarAlarm = {
    __initialized: true,
    registerFrameWindow: registerFrameWindow,
    ingestCommsData: ingestServerPayload,
    evaluateNow: evaluateEvents,
    triggerTestAlarm: triggerTestAlarm,
    openSettingsModal: openSettingsModal,
    dismiss: function (key) { dismissActiveAlarm(key || "", "exit"); },
    goTo: function (key, ev) { goToActiveAlarm(key || "", ev || null); },
    showModalFromUrl: showModalFromUrl,
    getState: function () { return state; }
  };
})();
