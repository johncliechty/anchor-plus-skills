/**
 * Projects tree collapse — W19 real JS path (not a cosmetic CSS override).
 *
 * Owns:
 *   - collapsed-by-default first paint (class "collapsed" + data-collapsed="true")
 *   - toggle expand/collapse on folder headers
 *   - per-profile preference persistence (version-stamped key)
 *
 * Preference key is version-stamped so a default-state change ignores stale
 * stored values (plan: ship key with the fix, not after John reports breakage).
 *
 * Surface: projects_collapse · Wave: W19
 */
(function (global) {
  "use strict";

  var PREF_KEY = "projects.collapse.v1";
  var FOLDER_SELECTOR = ".project-folder";
  var COLLAPSED_CLASS = "collapsed";
  var SURFACE = "projects_collapse";

  function _asBool(v) {
    if (v === true || v === "true" || v === "1") {
      return true;
    }
    if (v === false || v === "false" || v === "0") {
      return false;
    }
    return null;
  }

  function isCollapsed(el) {
    if (!el) {
      return true;
    }
    if (el.classList && el.classList.contains(COLLAPSED_CLASS)) {
      return true;
    }
    var attr = el.getAttribute ? el.getAttribute("data-collapsed") : null;
    var b = _asBool(attr);
    if (b === null) {
      return true;
    }
    return b;
  }

  function setCollapsed(el, collapsed) {
    if (!el) {
      return;
    }
    var flag = !!collapsed;
    if (el.classList) {
      if (flag) {
        el.classList.add(COLLAPSED_CLASS);
      } else {
        el.classList.remove(COLLAPSED_CLASS);
      }
    }
    if (el.setAttribute) {
      el.setAttribute("data-collapsed", flag ? "true" : "false");
    }
    if (el.setAttribute) {
      el.setAttribute("aria-expanded", flag ? "false" : "true");
    }
  }

  function collectExpandedIds(root) {
    var out = [];
    if (!root || !root.querySelectorAll) {
      return out;
    }
    var folders = root.querySelectorAll(FOLDER_SELECTOR);
    for (var i = 0; i < folders.length; i++) {
      var el = folders[i];
      if (!isCollapsed(el)) {
        var id = el.getAttribute("data-folder-id") || "";
        if (id) {
          out.push(id);
        }
      }
    }
    return out;
  }

  function applyExpandedSet(root, expandedIds) {
    var want = Object.create(null);
    var list = expandedIds || [];
    for (var i = 0; i < list.length; i++) {
      want[String(list[i])] = true;
    }
    var folders = root.querySelectorAll(FOLDER_SELECTOR);
    for (var j = 0; j < folders.length; j++) {
      var el = folders[j];
      var id = el.getAttribute("data-folder-id") || "";
      // Default collapsed; only expand when preference names this folder.
      setCollapsed(el, !want[id]);
    }
  }

  function collapseAll(root) {
    if (!root || !root.querySelectorAll) {
      return;
    }
    var folders = root.querySelectorAll(FOLDER_SELECTOR);
    for (var i = 0; i < folders.length; i++) {
      setCollapsed(folders[i], true);
    }
  }

  function readStoredPreference(profileId) {
    var store = global.__anchorProjectsCollapseStore;
    if (store && typeof store.load === "function") {
      return store.load(profileId);
    }
    try {
      if (global.localStorage && typeof global.localStorage.getItem === "function") {
        var raw = global.localStorage.getItem(PREF_KEY + ":" + profileId);
        if (raw == null || raw === "") {
          return { expanded: [], ok: true };
        }
        var parsed = JSON.parse(raw);
        if (!parsed || typeof parsed !== "object") {
          return { expanded: [], ok: false };
        }
        if (parsed.key && parsed.key !== PREF_KEY) {
          // Stale key version — ignore stored expand set.
          return { expanded: [], ok: true, stale_key: true };
        }
        var exp = parsed.expanded;
        if (!exp || !exp.length) {
          return { expanded: [], ok: true };
        }
        var ids = [];
        for (var i = 0; i < exp.length; i++) {
          ids.push(String(exp[i]));
        }
        return { expanded: ids, ok: true };
      }
    } catch (err) {
      return { expanded: [], ok: false, error: String(err && err.message ? err.message : err) };
    }
    return { expanded: [], ok: true };
  }

  function writeStoredPreference(profileId, expandedIds) {
    var payload = {
      key: PREF_KEY,
      expanded: expandedIds || [],
      profile_id: profileId || ""
    };
    var store = global.__anchorProjectsCollapseStore;
    if (store && typeof store.save === "function") {
      store.save(profileId, payload.expanded);
      return true;
    }
    try {
      if (global.localStorage && typeof global.localStorage.setItem === "function") {
        global.localStorage.setItem(
          PREF_KEY + ":" + profileId,
          JSON.stringify(payload)
        );
        return true;
      }
    } catch (err) {
      if (typeof global.__anchorProjectsCollapseOnError === "function") {
        global.__anchorProjectsCollapseOnError(err);
      }
      return false;
    }
    return false;
  }

  function bindToggles(root, profileId) {
    if (!root || !root.querySelectorAll) {
      return;
    }
    var toggles = root.querySelectorAll("[data-folder-toggle]");
    for (var i = 0; i < toggles.length; i++) {
      (function (btn) {
        btn.addEventListener("click", function (ev) {
          if (ev && typeof ev.preventDefault === "function") {
            ev.preventDefault();
          }
          var folder = btn.closest
            ? btn.closest(FOLDER_SELECTOR)
            : btn.parentNode;
          if (!folder) {
            return;
          }
          setCollapsed(folder, !isCollapsed(folder));
          var expanded = collectExpandedIds(root);
          writeStoredPreference(profileId, expanded);
          if (typeof global.__anchorProjectsCollapseChanged === "function") {
            global.__anchorProjectsCollapseChanged(profileId, expanded);
          }
        });
      })(toggles[i]);
    }
  }

  /**
   * Initialize the projects tree surface.
   *
   * options:
   *   root        — element or selector (default [data-surface="projects_collapse"])
   *   profileId   — per-user profile key (profile_A / profile_B)
   *   preferenceOk — when false, force collapsed and do not treat store as user choice
   *   expanded    — optional server-provided expanded id list (skips client re-read)
   *   applyDefault — when true (default), ensure every folder has collapsed default
   */
  function initProjectsTree(options) {
    var opts = options || {};
    var root = opts.root;
    if (typeof root === "string") {
      root = global.document ? global.document.querySelector(root) : null;
    }
    if (!root && global.document) {
      root = global.document.querySelector(
        '[data-surface="' + SURFACE + '"]'
      );
    }
    if (!root) {
      return { ok: false, reason: "no_root" };
    }

    var profileId =
      opts.profileId ||
      root.getAttribute("data-profile") ||
      "profile_A";

    var preferenceOk = opts.preferenceOk;
    if (preferenceOk === undefined || preferenceOk === null) {
      var prefAttr = root.getAttribute("data-preference-ok");
      var pb = _asBool(prefAttr);
      preferenceOk = pb === null ? true : pb;
    }

    // Real default path: every folder starts collapsed unless preference expands it.
    if (opts.applyDefault !== false) {
      collapseAll(root);
    }

    var expanded = opts.expanded;
    if (!preferenceOk) {
      // Unreadable preference store → collapsed fallback; never silent user choice.
      collapseAll(root);
      root.setAttribute("data-preference-state", "unknown");
    } else {
      if (!expanded) {
        var stored = readStoredPreference(profileId);
        if (!stored.ok) {
          collapseAll(root);
          root.setAttribute("data-preference-state", "unknown");
          preferenceOk = false;
        } else {
          expanded = stored.expanded || [];
          applyExpandedSet(root, expanded);
          root.setAttribute("data-preference-state", "ok");
        }
      } else {
        applyExpandedSet(root, expanded);
        root.setAttribute("data-preference-state", "ok");
      }
    }

    bindToggles(root, profileId);
    root.setAttribute("data-tree-ready", "true");
    root.setAttribute("data-profile", profileId);

    return {
      ok: true,
      profileId: profileId,
      preferenceOk: !!preferenceOk,
      expanded: collectExpandedIds(root),
      prefKey: PREF_KEY
    };
  }

  // Auto-init when DOM is ready and a surface root exists.
  function autoInit() {
    if (!global.document) {
      return;
    }
    var root = global.document.querySelector(
      '[data-surface="' + SURFACE + '"]'
    );
    if (!root) {
      return;
    }
    if (root.getAttribute("data-tree-ready") === "true") {
      return;
    }
    initProjectsTree({ root: root });
  }

  if (global.document) {
    if (global.document.readyState === "loading") {
      global.document.addEventListener("DOMContentLoaded", autoInit);
    } else {
      autoInit();
    }
  }

  var api = {
    PREF_KEY: PREF_KEY,
    COLLAPSED_CLASS: COLLAPSED_CLASS,
    SURFACE: SURFACE,
    isCollapsed: isCollapsed,
    setCollapsed: setCollapsed,
    collapseAll: collapseAll,
    collectExpandedIds: collectExpandedIds,
    applyExpandedSet: applyExpandedSet,
    initProjectsTree: initProjectsTree,
    readStoredPreference: readStoredPreference,
    writeStoredPreference: writeStoredPreference
  };

  global.AnchorProjectsTree = api;
  global.initProjectsTree = initProjectsTree;
})(typeof window !== "undefined" ? window : globalThis);
