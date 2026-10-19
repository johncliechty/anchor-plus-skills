/* skill-icons.js — ONE client-side map from a skill's name to its brand mark (John, 2026-09-05:
   "the icons are cool and I want to get them available" — in the project list, the plan, the top of
   every report a skill creates, and the workbench skill rail). The assets live in /vendor/brand/;
   the cockpit pages reach them as /brand/<file> (rewritten by the page shim). Pure DOM, no fetch. */
(function () {
  "use strict";
  var MAP = [
    { name: "researchPrime",    icon: "research-prime-icon.jpg",  aliases: ["research prime", "researchprime"] },
    { name: "Crucible",         icon: "crucible-icon.svg",        aliases: ["crucible"] },
    { name: "Foreman",          icon: "foreman-icon.svg",         aliases: ["foreman"] },
    { name: "Gandalf",          icon: "gandalf-icon.jpg",         aliases: ["gandalf"] },
    { name: "Jumper",           icon: "jumper-icon.jpg",          aliases: ["jumper"] },
    { name: "Superjump",        icon: "superjump-icon.jpg",       aliases: ["superjump", "super jump"] },
    { name: "Anvil",            icon: "anvil-icon.jpg",           aliases: ["anvil"] },
    { name: "Aegis",            icon: "aegis-icon.svg",           aliases: ["aegis", "sentinel"] },
    { name: "Ramanujan",        icon: "ramanujan-icon.jpg",       aliases: ["ramanujan"] },
    { name: "legal-beagle",     icon: "legal-beagle-icon.jpg",    aliases: ["legal beagle", "legal-beagle"] },
    { name: "financial-analyst", icon: "financial-analyst-icon.jpg", aliases: ["financial analyst", "financial-analyst"] },
    { name: "literature-review", icon: "literature-review-icon.jpg", aliases: ["literature review", "literature-review", "lit review"] },
    { name: "tidy-idy",         icon: "tidy-idy-icon.jpg",        aliases: ["tidy idy", "tidy-idy"] },
    { name: "zombie-hunter",    icon: "zombie-hunter-radar.jpg",  aliases: ["zombie hunter", "zombie-hunter"] },
    { name: "Ecgberht",         icon: "ecgberht-project-seal.jpg", aliases: ["ecgberht", "steward"] },
    { name: "chekhov",          icon: "chekhov-icon.svg",         aliases: ["chekhov", "writing skill"] },
    { name: "Skill Foundry",    icon: "skill-foundry-icon.jpg",   aliases: ["skill foundry"] }
  ];
  // 2026-10-07: always /vendor/brand/. The page shim rewrites /brand/ only inside HTML, never inside this separately
  // served script, so cockpit pages asked /brand/ (served from foundry-gui/dist/brand, which lacks several marks) and
  // got 404s — the image appeared, failed and vanished on every 1 s repaint, jittering the row ("nervous cat").
  var BASE = "/vendor/brand/";
  function entryFor(text) {
    var t = String(text || "").toLowerCase();
    if (!t) return null;
    for (var i = 0; i < MAP.length; i++) {
      var m = MAP[i];
      if (t === m.name.toLowerCase()) return m;
      for (var j = 0; j < m.aliases.length; j++) {
        if (t.indexOf(m.aliases[j]) >= 0) return m;
      }
    }
    return null;
  }
  function iconFor(text) { var e = entryFor(text); return e ? BASE + e.icon : null; }
  function img(text, size) {
    var e = entryFor(text);
    if (!e) return null;
    var im = document.createElement("img");
    im.className = "skico";
    im.src = BASE + e.icon;
    im.alt = e.name; im.title = e.name;
    im.width = size || 18; im.height = size || 18;
    im.style.cssText = "width:" + (size || 18) + "px;height:" + (size || 18) + "px;border-radius:4px;object-fit:cover;vertical-align:-4px;margin-right:5px";
    // a failed mark keeps its slot (hidden, not removed) so the text beside it never shifts
    im.onerror = function () { im.style.visibility = "hidden"; };
    return im;
  }
  /* Prepend a mark before the FIRST mention of a skill inside each matching element (idempotent). */
  function decorate(root, selector) {
    var nodes = (root || document).querySelectorAll(selector || "[data-skill-mentions]");
    for (var i = 0; i < nodes.length; i++) {
      var n = nodes[i];
      if (n.getAttribute("data-skico") === "1") continue;
      var e = entryFor(n.textContent);
      if (!e) continue;
      var im = img(e.name);
      if (im) { n.insertBefore(im, n.firstChild); n.setAttribute("data-skico", "1"); }
    }
  }
  function exact(text) {
    var t = String(text || "").toLowerCase();
    if (!t) return null;
    for (var i = 0; i < MAP.length; i++) {
      if (t === MAP[i].name.toLowerCase() || MAP[i].aliases.indexOf(t) >= 0) return MAP[i];
    }
    return null;
  }
  /* Which skill produced a document: a directory on its path that IS a skill's name (gandalf/run-…/report.md →
     Gandalf); a lane folder (planning/, build/, research/) says nothing about who made the file. */
  function fromPath(path) {
    var segs = String(path || "").replace(/\\/g, "/").split("/");
    for (var i = 0; i < segs.length - 1; i++) {
      var e = exact(segs[i]);
      if (e) return e.name;
    }
    return null;
  }
  /* A skill named as a whole word in a row's title ("Gandalf read …", "researchPrime run — …"); names only, never aliases. */
  function wordSkill(text) {
    var words = String(text || "").split(/[^A-Za-z0-9\-]+/);
    for (var i = 0; i < words.length; i++) {
      var e = exact(words[i]);
      if (e && e.name.toLowerCase() === words[i].toLowerCase()) return e;
    }
    return null;
  }
  /* The skill that made a register item: its owning step's commission, else the skill its title names, else its folder. */
  function forItem(it, owner) {
    if (!it) return null;
    var e = owner && owner.commissioned_as ? exact(String(owner.commissioned_as).split(":")[0]) : null;
    if (!e) e = wordSkill(it.what);
    return e ? e.name : fromPath(it.path || it.route || "");
  }
  window.SkillIcons = { MAP: MAP, entryFor: entryFor, exact: exact, iconFor: iconFor, img: img, decorate: decorate, fromPath: fromPath, forItem: forItem };
})();
