/* One set of notebook actions for Deliverables, producing Plan steps and Files. */
(function () {
  "use strict";
  function url(verb, dir, path) {
    const query = new URLSearchParams({pid: window.STEWARD_PID || "", dir: dir || "", path});
    if (window.STEWARD_TOKEN) query.set("token", window.STEWARD_TOKEN);
    return "/api/steward/" + verb + "?" + query.toString();
  }
  function link(text, href) {
    const node = document.createElement("a");
    node.textContent = text; node.href = href; node.target = "_blank";
    node.rel = "noopener noreferrer"; return node;
  }
  function render(item, dir) {
    const info = item.notebook_product;
    if (!info) return null;
    const root = document.createElement("span"); root.className = "notebook-product";
    const title = item.what || item.name || item.path || "Notebook";
    const target = info.source || info.notebook || item.path;
    const name = info.can_open ? link(title + " · Open notebook", url("notebook-open", dir, target))
                              : document.createElement("span");
    if (!info.can_open) name.textContent = title;
    name.title = info.message || ""; root.appendChild(name);
    if (info.source) {
      root.appendChild(document.createTextNode(" · "));
      root.appendChild(link("Source", url("deliverable-file", dir, info.source) + "&download=1"));
    }
    if (info.can_convert || ["source_changed", "notebook_edited"].includes(info.status)) {
      const regenerate = !info.can_convert;
      const button = document.createElement("button"); button.type = "button";
      button.textContent = regenerate ? "New notebook revision" : "Create notebook";
      button.title = "Create and register a notebook on the Anchor host; no code is executed.";
      button.onclick = async () => {
        button.disabled = true;
        try {
          const headers = {"Content-Type": "application/json"};
          if (window.STEWARD_TOKEN) headers.Authorization = "Bearer " + window.STEWARD_TOKEN;
          const response = await fetch("/api/steward/notebook-register?pid=" + encodeURIComponent(window.STEWARD_PID || ""), {
            method: "POST", headers, body: JSON.stringify({dir: dir || "", source: info.source,
              what: title, step: item.step || "", regenerate})});
          const result = await response.json();
          if (!response.ok || !result.ok) throw new Error(result.error || result.reason || "Notebook registration failed");
          root.replaceWith(render({...item, notebook_product: result.notebook_product}, dir));
          window.dispatchEvent(new Event("anchor-notebooks-changed"));
        } catch (error) { button.disabled = false; note.textContent = " · " + error.message; }
      };
      root.appendChild(document.createTextNode(" · ")); root.appendChild(button);
    }
    const note = document.createElement("small");
    note.textContent = info.setup_required ? " · Jupyter setup required on the Anchor host"
      : info.status === "notebook_edited" ? " · edited notebook preserved"
      : info.status === "source_changed" ? " · source changed; notebook preserved"
      : !info.can_open && info.message ? " · " + info.message : "";
    root.appendChild(note); return root;
  }
  window.AnchorNotebooks = {render};
})();
