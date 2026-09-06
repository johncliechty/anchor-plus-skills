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
    { name: "Ramanujan",        icon: "ramanujan-icon.jpg",       aliases: ["ramanujan"] },
    { name: "legal-beagle",     icon: "legal-beagle-icon.jpg",    aliases: ["legal beagle", "legal-beagle"] },
    { name: "financial-analyst", icon: "financial-analyst-icon.jpg", aliases: ["financial analyst", "financial-analyst"] },
    { name: "literature-review", icon: "literature-review-icon.jpg", aliases: ["literature review", "literature-review", "lit review"] },
    { name: "tidy-idy",         icon: "tidy-idy-icon.jpg",        aliases: ["tidy idy", "tidy-idy"] },
    { name: "zombie-hunter",    icon: "zombie-hunter-radar.jpg",  aliases: ["zombie hunter", "zombie-hunter"] },
    { name: "Ecgberht",         icon: "ecgberht-project-seal.jpg", aliases: ["ecgberht", "steward"] },
    { name: "Skill Foundry",    icon: "skill-foundry-icon.jpg",   aliases: ["skill foundry"] }
  ];
  var BASE = (function () {
    // the cockpit pages sit under /steward/ where the shim rewrites /brand/ → /vendor/brand/;
    // every other page reaches the assets directly
    return (location.pathname.indexOf("/steward/") === 0) ? "/brand/" : "/vendor/brand/";
  })();
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
    im.onerror = function () { im.style.display = "none"; };
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
  /* Which skill produced a document, from its path (gandalf/run-…/report.md → Gandalf; a lane dir → its skill). */
  function fromPath(path) {
    var p = String(path || "").toLowerCase();
    if (/(^|\/)gandalf(\/|$)/.test(p)) return "Gandalf";
    if (/(^|\/)jumper(\/|$)/.test(p)) return "Jumper";
    if (/(^|\/)(research|researchprime)(\/|$)/.test(p)) return "researchPrime";
    if (/(^|\/)(plan|planning|crucible)(\/|$)/.test(p)) return "Crucible";
    if (/(^|\/)(build|foreman)(\/|$)/.test(p)) return "Foreman";
    var e = entryFor(p);
    return e ? e.name : null;
  }
  window.SkillIcons = { MAP: MAP, entryFor: entryFor, iconFor: iconFor, img: img, decorate: decorate, fromPath: fromPath };
})();
