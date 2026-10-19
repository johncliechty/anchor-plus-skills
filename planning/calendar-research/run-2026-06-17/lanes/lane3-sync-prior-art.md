# Lane 3 — Best-in-Class Prior Art for the Reconcile Engine

**Study:** Anchor bidirectional calendar sync (local store ↔ Google Calendar API v3 + Microsoft Graph)
**Lane scope:** Find prior art to REUSE or LEARN FROM so Anchor does not reinvent a subtly-wrong reconcile engine.
**Reconcile design already locked:** iCalUID-keyed mapping table + last-synced-baseline three-way merge (Unison/vdirsyncer model) + ETag/self-marker echo suppression + tombstones + recurring master+exception handling.
**Date:** 2026-06-17
**Evidence ladder:** OBSERVED (primary doc/source read) > CORROBORATED (≥2 independent) > CLAIMED (single secondary) > UNVERIFIED.

---

## 0. Headline findings (the things that change the verdict)

1. **vdirsyncer does NOT do a three-way merge.** Its core is a **two-way, state-based reconcile**: it stores a *status* mapping `item_id → (etag_A, etag_B)` from the previous sync, and uses ETag change-detection to decide add/delete/change/conflict. A *three-way content merge* is mentioned by the author only as an **optional** `conflict_resolution` strategy ("perhaps you saved the old version and can perform a three-way merge"), **not** the default engine. — OBSERVED (author's own algorithm post). This is a meaningful divergence from Anchor's spec, which says "last-synced-baseline three-way merge." Anchor's design is closer to **Unison** (which keeps the *last-synced content archive*, enabling a true 3-way) than to vdirsyncer (which keeps only *etags*, not content, so it can only do a 3-way if it separately cached old content).

2. **No turnkey Google↔Graph two-way Python library exists.** The closest maintained two-way tool is **OutlookGoogleCalendarSync** — but it is **C#/.NET, a standalone desktop app, MPL-2.0**, not an importable Python component. Python options (`pyO2g`, `gboeing/outlook-to-google-calendar`) are **one-way** Outlook→Google. — CORROBORATED. Hand-rolling per the spec is the realistic path.

3. **vdirsyncer cannot talk to Microsoft Graph at all.** It is CalDAV-native + has a first-class `google_calendar` storage, but Microsoft requires the **DavMail** CalDAV-proxy bridge, which the vdirsyncer docs themselves warn can cause **data loss**. — OBSERVED (vdirsyncer DavMail tutorial). So even as a library it only covers half of Anchor's targets.

4. **The authoritative algorithm reference is Balasubramaniam & Pierce, "What is a File Synchronizer?" (MobiCom '98)**, formalized in **Pierce & Vouillon, "What's in Unison?" (UPenn Tech Report MS-CIS-03-36, 2004)**. The baseline-comparison "dirty on both sides ⇒ conflict; dirty on one side ⇒ propagate" rule is *their* model and is exactly Anchor's locked design. — OBSERVED (Pierce's own publications page).

---

## 1. vdirsyncer — deep dive (the most directly relevant prior art)

| Question | Finding | Evidence |
|---|---|---|
| True three-way merge against a stored baseline? | **No.** Core is two-way state-based. Status = `id → (etag_A, etag_B)` from last sync. 3-way is only an *optional* conflict-resolution add-on, and the engine does not retain old *content* by default. | OBSERVED — author's "A simple synchronization algorithm" post |
| How detects add vs delete? | An id present on one side + absent from both the other side **and** the stored status ⇒ **add**. An id in status + one side but gone from the other ⇒ **delete**. | OBSERVED — same post |
| How detects both-changed conflict? | ETag comparison: "If the etag has changed on both A and B, invoke `conflict_resolution`." Also: id on both sides with no status entry ⇒ conflict. | OBSERVED — same post |
| `conflict_resolution` policy options | `"a wins"` / `"b wins"`; user prompt; or `["command", "vimdiff", ...]` external merge on two temp files. App-specific; verifies content actually differs before acting. | OBSERVED — config manual + algorithm post |
| Importable Python library, or CLI-only? | CLI-first. Internal sync engine exists (`vdirsyncer.sync` with `sync()`, `StorageEmpty`, `SyncConflict`, `prepare_new_status`, `Storage` base) but it is an **internal/unstable API**, not a documented public library surface. | CORROBORATED — programtalk example + issue tracker; CLAIMED that it's "supported public API" (it is not advertised as one) |
| License | **3-clause BSD** | CORROBORATED — GitHub + PyPI |
| Maintenance state (2026) | **Actively maintained.** Latest **0.20.0, 2025-08-28** (PyPI). Snyk: "Sustainable." Maintainers geier/untitaker/WhyNotHugo. BUT the lead author has redirected active development to a **Rust rewrite (pimsync / vstorage)** — see below. | OBSERVED — PyPI; CORROBORATED — Snyk |
| Targets Google + Graph? | **Google: yes** (`google_calendar` storage, OAuth token+client id/secret). **Graph: no** — only via DavMail CalDAV proxy, which docs flag as data-loss-prone. | OBSERVED — vdirsyncer config + DavMail tutorial |
| Successor | **pimsync** (Rust) is the announced successor; the sync algorithm now lives in the reusable **vstorage** Rust library; pimsync is a thin CLI over it. Python vdirsyncer is "not yet deprecated" but feature-frozen-ish. | OBSERVED — pimutils.org "pimsync: a successor to vdirsyncer" (2025-01-08) |

**Takeaway:** vdirsyncer's *status-model and add/delete/conflict detection logic* is gold-standard prior art to STUDY (BSD, so even copyable), but (a) its engine is two-way/etag-state, not the content-baseline 3-way Anchor specced; (b) it has no Graph path; (c) its Python sync core is an internal API, not a stable importable library; (d) the author himself has moved the "well-designed-from-the-start" version to Rust (vstorage). So: **reference, not reuse.**

---

## 2. Other open-source sync engines (reference vs reuse)

| Engine | What it is | Reuse or reference? | License | Google+Graph? | Notes / evidence |
|---|---|---|---|---|---|
| **Unison** (bcpierce00/unison) | The canonical bidirectional *file* synchronizer; origin of the baseline-archive algorithm | **Reference (algorithm origin)** — OCaml, file-not-calendar | GPL | No (files) | Keeps a per-replica *archive* of last-synced state; dirty-on-both ⇒ conflict, dirty-on-one ⇒ propagate; detects false conflicts (both changed to identical value). This IS Anchor's model. — OBSERVED (Wikipedia + manual + Pierce papers) |
| **pimsync / vstorage** (sr.ht ~whynothugo) | vdirsyncer's Rust successor; sync logic in the reusable `vstorage` crate | **Reference** (Rust, can't import into Python) | (open; sr.ht) | Google via CalDAV; Graph no | Best-designed modern incarnation of the vdirsyncer algorithm. Worth reading the vstorage source for the cleaned-up state machine. — OBSERVED (pimutils blog, docs.rs/vstorage) |
| **python-caldav** (python-caldav/caldav) | CalDAV *client* library (DAVClient → Principal → Calendar → Event) | **Possible REUSE for the CalDAV transport ONLY** — it is NOT a sync engine | **Apache-2.0 OR GPLv3** (dual) | CalDAV servers incl. Google's CalDAV endpoint; no Graph | Has a server-quirk compatibility layer. Gives you fetch/create/update/delete + date search, but you write the reconcile yourself. — OBSERVED (PyPI/readthedocs) |
| **Radicale** (Kozea) | CalDAV/CardDAV *server* in Python | **Reference only** (it's a server, not a sync engine) | **GPLv3** | No | Useful as a local test CalDAV target, not for reconcile logic. — CORROBORATED |
| **khal / khard** | CLI calendar/contacts frontends over a vdir | **Reference** | (open) | Via vdirsyncer | They consume vdir; they don't sync. — CLAIMED (secondary) |
| **GNOME Evolution-data-server (EDS)** | Linux PIM backend with calendar sync backends incl. Google & a Graph/EWS connector | **Reference** (C/GObject, Linux-bound, heavy) | LGPL | Google + (EWS/Graph via evolution-ews) | Mature multi-backend sync, but not embeddable in a single-user Python app. — CLAIMED (not deep-verified this run; flag as secondary) |
| **Thunderbird / Mozilla Sync** | Thunderbird syncs via CalDAV/ICS providers; "Mozilla Sync" is browser-data sync, NOT calendar reconcile | **Not relevant** | MPL | n/a | Mozilla Sync ≠ calendar sync; do not conflate. — CLAIMED |
| **syncthing-style / CRDT models** | Block/version-vector file sync; CRDTs for conflict-free merge | **Reference (alternative paradigm)** | MPL (syncthing) | No | An alternative to baseline-3-way: version vectors avoid a stored baseline but add per-field merge complexity. Considered as the counter-argument (§5). — CLAIMED |
| **OutlookGoogleCalendarSync** (phw198) | The one maintained **two-way Outlook↔Google** tool | **Reference** (C#/.NET, standalone app) | **MPL-2.0** | Yes (Outlook + Google) | Two-way, "differential comparison updates only changed attributes," active (v2.12.0 beta 2026-01-18, v3 alpha). Not a library. Worth studying its *attribute-level diff + event matching* approach. — OBSERVED (GitHub) |
| **pyO2g**, **gboeing/outlook-to-google-calendar** | Python Outlook→Google | **Reference** (one-way) | (open) | One-way O→G | Shows the Graph+Google API plumbing in Python, but no bidirectional reconcile. — CORROBORATED |
| **O365/python-o365** | Microsoft Graph client library (Python) | **Possible REUSE for the Graph transport** | (open, BSD-ish) | Graph only | Pairs with google-api-python-client. Transport, not reconcile. — CORROBORATED |

---

## 3. Is there a maintained turnkey Google↔Graph two-way sync? — HONEST ANSWER: No (not as a Python component)

- **Two-way + Google + Microsoft, maintained:** only **OutlookGoogleCalendarSync** — but **C#/.NET, MPL-2.0, a standalone GUI app**, not importable into a Python single-user app. — OBSERVED.
- **Python, two-way, Google↔Graph:** **none found** on PyPI/GitHub. Python tools are one-way (Outlook→Google). — CORROBORATED (negative result; searched PyPI + GitHub topics `outlook`, `google-calendar`, `outlook-calendar`).
- **vdirsyncer** would require DavMail to reach Microsoft (data-loss-flagged) and exposes no stable Python sync API.

**Conclusion:** There is no drop-in turnkey. **Hand-rolling the reconcile engine per the locked spec is the realistic path.** The reusable pieces are the **transports** (`google-api-python-client` for GCal v3; `O365/python-o365` or raw Graph REST for Microsoft; optionally `python-caldav` if a CalDAV path is ever wanted), plus the **algorithm** borrowed from Unison/vdirsyncer.

---

## 4. Canonical algorithm references (authoritative, primary)

1. **Balasubramaniam, S. & Pierce, B. C. — "What is a File Synchronizer?"** — *MobiCom '98* (4th ACM/IEEE Intl. Conf. on Mobile Computing and Networking), Oct 1998. Full version: Indiana Univ. CSCI Tech Report #507, Apr 1998. *The* formal definition of a synchronizer's correctness (propagate non-conflicting, flag conflicting). — OBSERVED (Pierce's UPenn publications page).
2. **Pierce, B. C. & Vouillon, J. — "What's in Unison? A Formal Specification and Reference Implementation of a File Synchronizer"** — UPenn Tech Report **MS-CIS-03-36**, 2004. The reference algorithm: per-path *dirty* predicate vs the last-sync archive; `dirty(A) ∧ dirty(B) ∧ A≠B ⇒ conflict`; one-sided dirty ⇒ propagate; both dirty to equal value ⇒ silently reconciled (false conflict). **This is precisely Anchor's last-synced-baseline rule.** — OBSERVED (PDF binary saved; algorithm corroborated via Unison manual + Wikipedia).
3. **Author's practitioner write-up:** Markus Unterwaditzer, *"A simple synchronization algorithm"* (unterwaditzer.net, 2016) — the vdirsyncer status-mapping/etag adaptation of the above for calendars/contacts. The single best plain-language source for the *calendar* specialization (ETags as the "dirty" signal). — OBSERVED.
4. Supplementary (alternative paradigm): *"Algebra of Data Reconciliation"* (arXiv 2110.06313) and *"Algebraic File Synchronization: Adequacy and Completeness"* (arXiv 1601.01736) — formal treatments if a CRDT/algebraic alternative is ever evaluated. — CLAIMED (not deep-read).

---

## 5. VERDICT

**Reuse directly:** Nothing as a *reconcile engine*. Reuse only the **transport clients** — `google-api-python-client` (GCal v3) + a Graph client (`O365/python-o365` or raw REST). vdirsyncer's Python sync core is an internal/unstable API, BSD but not a stable library surface, and covers Google-only.

**Study as the algorithm reference (in priority order):**
1. **vdirsyncer's status-model** (Unterwaditzer's post + the BSD source `vdirsyncer/sync.py`) — the *single most worth studying* artifact: it is the proven calendar-specific specialization (ETag-as-dirty-signal, add/delete/conflict detection, `SyncConflict`/`StorageEmpty` safety guards like the "storage emptied ⇒ abort" data-loss tripwire Anchor should copy).
2. **Unison** (Pierce papers §4) — the formal correctness model that justifies the baseline-3-way and the false-conflict optimization.
3. **pimsync/vstorage** (Rust) and **OutlookGoogleCalendarSync** (C#) — read for the modern cleaned-up state machine and for attribute-level diffing + cross-provider event matching, respectively.

**Confirm "hand-roll per the spec" as the realistic recommendation: YES — CONFIRMED.** No turnkey Python Google↔Graph two-way engine exists; vdirsyncer can't reach Graph without the data-loss-prone DavMail bridge and exposes no stable sync API; the spec's iCalUID-mapping + last-synced-baseline 3-way IS the canonical Unison model. Hand-rolling the ~few-hundred-line reconcile core against two transport SDKs is the standard, correct path.

**Strongest counter-argument (considered):** *"Don't hand-roll a baseline; adopt a CRDT / version-vector model (syncthing-style) and avoid the whole class of stale-baseline and missed-conflict bugs."* — Rejected for Anchor because: (a) Google and Graph give us **server-authoritative ETags + sync tokens** already, so the "dirty" signal is free and reliable — the baseline-3-way is a natural fit, not extra machinery; (b) CRDTs require per-field merge semantics for calendar events (title/time/attendees/recurrence) that neither API exposes cleanly, pushing complexity UP, not down; (c) the spec's recurring master+exception handling maps onto per-iCalUID baseline entries far more directly than onto a CRDT document; (d) two endpoints + a local store is the simplest possible topology, where the Unison 2-replica-with-archive model is exactly sized. The one CRDT lesson worth keeping: prefer **field-level (attribute) diffing on conflict** (à la OutlookGoogleCalendarSync) over whole-event last-writer-wins, to minimize destructive overwrites.

---

## 6. Sources (with evidence quality)

- vdirsyncer algorithm (OBSERVED): https://unterwaditzer.net/2016/sync-algorithm.html
- vdirsyncer config / conflict_resolution (OBSERVED): https://vdirsyncer.pimutils.org/en/stable/config.html
- vdirsyncer DavMail/Outlook caveat (OBSERVED): https://vdirsyncer.pimutils.org/en/stable/tutorials/davmail.html
- vdirsyncer GitHub / BSD license (CORROBORATED): https://github.com/pimutils/vdirsyncer
- vdirsyncer PyPI 0.20.0 / 2025-08-28 / google extra (OBSERVED): https://pypi.org/project/vdirsyncer/
- vdirsyncer maintenance "Sustainable" (CORROBORATED): https://snyk.io/advisor/python/vdirsyncer
- vdirsyncer Mar-2024 status / library-goal (OBSERVED): https://whynothugo.nl/journal/2024/03/29/vdirsyncer-status-update-march-2024/
- pimsync successor / vstorage Rust library (OBSERVED): https://pimutils.org/blog/2025-01-08-pimsync-a-successor-to-vdirsyncer/  ·  https://docs.rs/vstorage/  ·  https://sr.ht/~whynothugo/pimsync/
- vdirsyncer internal sync API symbols (CORROBORATED): https://programtalk.com/python-examples/vdirsyncer.sync.sync/
- Pierce publications (titles/venues/years) (OBSERVED): https://www.cis.upenn.edu/~bcpierce/papers/index.shtml
- "What's in Unison?" spec PDF (OBSERVED, binary): https://www.cis.upenn.edu/~bcpierce/papers/unisonspec.pdf
- Unison algorithm (archive/dirty/false-conflict) (CORROBORATED): https://en.wikipedia.org/wiki/Unison_(software)  ·  https://man.archlinux.org/man/extra/unison/unison.1.en
- python-caldav lib, dual Apache/GPL (OBSERVED): https://pypi.org/project/caldav/  ·  https://caldav.readthedocs.io/stable/about.html
- Radicale GPLv3 server (CORROBORATED): https://github.com/Kozea/Radicale  ·  https://pypi.org/project/Radicale/
- OutlookGoogleCalendarSync (two-way, C#, MPL-2.0, active) (OBSERVED): https://github.com/phw198/OutlookGoogleCalendarSync
- Python one-way O→G tools (CORROBORATED): https://github.com/darknao/pyO2g  ·  https://github.com/gboeing/outlook-to-google-calendar
- O365/python-o365 Graph client (CORROBORATED): https://github.com/O365/python-o365
- Alternative-paradigm formal papers (CLAIMED): https://arxiv.org/pdf/2110.06313  ·  https://arxiv.org/pdf/1601.01736
