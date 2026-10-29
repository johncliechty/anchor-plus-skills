# Piaget sphere: sources found (2026-10-02 search, read-only agent)

John's description (2026-10-02): a hierarchical map of the types of knowledge, skills, tools, methods and places to
look that each Foundry skill uses; circular hierarchy, most important topics/knowledge/questions at the CENTER,
branching outward as refined; like a Mixture-of-Experts collection; multi-dimensional, a SPHERE not a circle.

No single note names a "Piaget map" or "knowledge sphere". The parts live here:

## Ghost World Labs agentic memory (C:\dev\Agentic-Home)
- `Geometric Memory — Hyperbolic, Mixture-of-Experts, and Transformer Knowledge for the Agentic Sandbox.md` (Report 4,
  2026-04-24): hierarchical knowledge needs a geometric embedding; MoE routes between "knowledge states and skill
  sets"; attention bridges domains. "Near-origin entities are high-abstraction ... near-boundary entities are
  specific." Product manifold of facets: "time, authorship, domain, certainty, audience, cost"; "authorship is
  spherical". "The breakthrough is less one geometry and more the disciplined coexistence of several, with routing
  as the integrating act." Geometric Memory Layer + Symbolic-MoE routing + cross-branch analogy edges; 10-D ball.
- `ARCHITECTURE-Alpha-Agent-Brain-v2.md` (2026-04-30): each region a "cognitive cell": "Mixture of Experts gating
  function driven by an embedding, then local skill files with rules + questions, then local memory / context /
  experiences, then outward to nearby skill-files and memories." §6 "The sleep / dream / replay loop (Piaget, made
  concrete)": assimilation vs accommodation; sleep changes skill files, MoE gate residuals and ontology nodes
  ("worldview hierarchy"; Consolidator proposes, human approves).
- `TERMINOLOGY.md` l.131; `whitepaper-archive/BASE-BRAIN-SPEC-2026-05-04-v2.md` l.256: "distance from the disk origin
  maps to abstraction level (center = general; edge = specific)"; GEO worker: geo.lookup, analogy walks,
  geo.worldview, geo.commit.
- `docs/plans/PLAN-Update-Planning-Cognition.md` (2026-05-01): "Linear vs. Poincaré" embedding spaces for difficulty
  routing; "a Piagetan Dream Loop for structural accommodation"; Strategy Shards retrieved by Poincaré embedding.
- `docs/plans/PLAN-Alpha-Agent-Brain-v2.md` (P11 Dream / replay loop, Piaget accommodation); `PVB+P Kit/`
  (03-memory-schema, 04-geo-worker-spec): not yet read.

## Skill Foundry / Anchor
- `Anchor/foundry-gui/src/components/KnowledgeGraphTile.jsx`: live Poincaré-disk layout of the SKILL dependency
  graph (foundational skills near the center, r = tanh(depth·SPREAD)·R). Nodes are skills, not knowledge.
- `Skill Foundry/planning/portfolio-program/_archive/sleep-engine-gui-archived-2026-07-02/planning/crucible/MASTER-PLAN.md`:
  "Poincaré Map (Hyperbolic Tree Graph) mimicking a starry constellation ... 'breaking open' into a Deep Expander".
- `Skill Foundry/notes/skills-and-agent-tips/NIGHTLY_SWEEP_PLAN.md` (Aurora v1–v4.3, May 2026): a deep-think critique:
  a hashed-angle Poincaré disk "is a sunburst dressed in geometry words"; ship a sunburst first; the learned
  Poincaré version waits for ≥500 artifacts; "domain → radius (depth), complexity → angular band"; new taxonomy
  nodes proposed to John for approval.

## Reviews
None by researchPrime or Gandalf on a Piaget map / knowledge sphere. The only critique is the NIGHTLY_SWEEP deep-think
pass ("the hierarchical idea is fine; the v1 implementation is decorative").

## Search limits
C:\dev top-level, OneDrive and a C:\dev-wide grep timed out; folders outside Agentic-Home named Ghost/Jarvis/Cortex/
Brain/Mind and OneDrive are unverified.

## Second search (2026-10-02 evening, on John's word that the original Piaget-map work is local)
Scanned every .md/.txt/.json/.html/.docx/.pptx/.pdf (text extracted) under C:\dev\Ghost World Labs (holds only a
.researchprime folder), C:\dev\Agentic-Home, C:\Users\example\gbrain, OneDrive, Documents, Desktop, Downloads,
C:\dev\plans, Teaching, AI Club, _sf-sandbox, and the Claude session logs. Hits (PIAGET-HITS.json): no file is named or
titled a "Piaget map". Piaget appears in:
- `Agentic-Home/Cognition-Inspired Architectures for the Agentic Sandbox.docx/.pdf` §4 "World models that update
  (Piaget; predictive processing)" (schemas, assimilation, accommodation, equilibration; "schemas only need to be as
  good as they need to be"; GBrain is "a persistent external schema") and §P5 "Predict → act → compare → accommodate
  loop" (every worker predicts time, cost, artifact and quality; small gaps = assimilation, large/systematic gaps =
  accommodation proposal, approved before it takes effect; ~/gbrain/predictions/*.jsonl; weekly accommodation brief).
  Text extracted to `cognition-inspired.txt`.
- ARCHITECTURE-Alpha-Agent-Brain-v2 §6; docs/plans/PLAN-Alpha-Agent-Brain-v2 P11; Master Rollout Plan v2; 
  docs/plans/PLAN-Update-Planning-Cognition (all: the dream/replay loop as Piaget accommodation).
The circular, center-to-rim, MoE-routed structure itself is in the Geometric Memory report (Report 4), not tied to
the word Piaget. If John's original is elsewhere (another machine, a claude.ai chat, a OneDrive file not synced
here), it was not found on this machine.

## Third search: the Taste-to-Reason (T2R) brain material (John: "each unit of that cognition includes a knowledge map")
No file uses "knowledge map", concentric/sphere layout or "core questions at the center". The design he means is:
- `Agentic-Home/BASE-BRAIN-SPEC.md` (v2.0.2, 2026-05-05, AUTHORITATIVE) §1.2 surface 3: "Per-cell knowledge store. The
  cell's local copy of the knowledge structure relevant to its function. Geometry-uniform with the brain... Grows as new
  concepts are encountered; consolidated nightly." §2.3: "Knowledge stores are hierarchical: distance from the
  hyperboloid apex maps to abstraction level (apex = general; further = specific)." §3.3: the per-cell store is the
  Librarian's "personal map" of how to navigate the Atlas. §1.3 gate: score = similarity(q, skill) * temperature +
  gate_residual. §7.4: sleep tiers: small additions / nudge edges / refactor neighborhoods if drift > threshold.
- `ARCHITECTURE-Alpha-Agent-Brain-v2.md` §0(a) John's words: "Mixture of Experts gating function driven by an embedding,
  then local skill files with rules + questions, then local memory / context / experiences, then outward to nearby
  skill-files and memories." §1.3 the four resources "working from inside out". §2.1 ontology node = "Category in the
  worldview hierarchy... Consolidator (proposes), human (approves)... refactored on schema-stress". §6 Piaget.
- `PVB+P Kit/03-memory-schema.md`, `01-WHAT-IS-PLUS-P.md`: concept frontmatter `id, name, tags, created, last_touched,
  parent_ids, sibling_ids, position`; `graph.json` `root_clusters[{name, concept_ids, centroid, children[...]}]`;
  `worldview.md` = the top-level partition with percentages; analogy walks toward the root and laterally.
- `archive/alpha-brain-v1` §4.1 `procedural/ontology.md` seed tree (agentic-sandbox / self / world); §5.4 per-region
  `questions.md` (canonical question shapes).
- `sandbox-lab-gui/brain/knowledge-store.mjs` (code): per-cell stores are "projections of Atlas neighborhoods"; entry
  `{id, embedding[], summary, tags[], source_concept_id, access_count, created_at, last_accessed_at}`; flat today.
  `regions/atlas/experts/worldview-summary`, `regions/consolidator/experts/ontology-refactor` (merge / split).
- `TERMINOLOGY.md` §G: flat semantic shards / ontology (taxonomic tree) / Poincaré geometric memory; WHITEPAPER v0.14
  §4.2 and figure-05 "center = general · edge = specific".
- `ARCHITECTURE-Reasoning-Agent-v3.md` §3.6: distance to origin = abstraction / difficulty / how fundamental;
  "mastered centre vs unfamiliar outer ring".
- `docs/plans/DESIGN-t2r-brain-and-gwl-harness-2026-06-08.md`: D1 the cognitive-cell knowledge store; D3 v0 flat,
  "defer Knowledge-Lorentz until ontology depth > 3"; D8 each T2R stage (Taste, Reason, Summary) is its own ~11-cell
  brain with its own knowledge stores.
`gwl-t2r-brain/` holds code only (no docs). Not written anywhere: "most important questions at the center"; the
documents define the center by generality.

## Fourth search (2026-10-03): the paper John remembers ("calibrating deep networks with hierarchical systems;
## Piaget hierarchies empirically more efficient than linear; a Lorentz hierarchy suggested later")
No local paper pairs "Piaget" with a hierarchy geometry. The description matches POINCARÉ (hyperbolic) embeddings:
- Nickel & Kiela, "Poincaré Embeddings for Learning Hierarchical Representations", NeurIPS 2017 (arXiv 1705.08039;
  no local PDF). Summarised in Agentic-Home Geometric Memory report §6 l.219: "in as few as 2–5 dimensions, Poincaré
  embeddings match or beat 200-dimensional Euclidean embeddings on reconstruction and link prediction over WordNet."
  Follow-up Nickel & Kiela ICML 2018 switched to the LORENTZ model ("more stable optimization for deeper
  hierarchies", l.221). Sala et al. ICML 2018: MAP 0.989 in 2 dimensions (l.594). HyperbolicRAG Recall@5 79.0% vs
  73.4% Euclidean.
- His own work cited there (files not on this machine): Variable Selection folder, `hyperbolic_cov_report.docx`
  (Poincaré-ball covariance with a calibrated link g(d) = 2/(1+e^(αd)) − 1 — likely the "calibrating" memory),
  `Bayesian Partition Inference — LE, Pruning, Manifolds.pdf` (Bell numbers outgrow the Poincaré ball → variable
  curvature / product simplex), `Bayesian Partition Search on the Liechty-Ebbes Trie — Survey`.
- Lorentz: first in the Geometric Memory report (l.264, l.920 "train in Lorentz, project to Poincaré for display",
  l.1365); recommended explicitly in `BRAIN-ARCHITECTURE-REVIEW.md` l.81 (likely Gemini); adopted 2026-05-05 as
  BASE-BRAIN-SPEC v2.0.2 "Knowledge-Linear vs Knowledge-Lorentz".
- `docs/plans/PLAN-Update-Planning-Cognition.md` l.8 puts "Linear vs. Poincaré" and "a Piagetan Dream Loop" side by
  side — the likely origin of the merged name.
- The planned empirical test is his own: PLAN-Alpha-Agent-Brain-v2 §P13 "Tournament 1: Alpha-Linear-Cell vs
  Alpha-Poincaré-Cell" (plan, not a result).
Reading: the structure is Poincaré/Lorentz (hyperbolic) geometry; the learning is Piaget (assimilation and
accommodation in the sleep loop). "Piaget map" = a hyperbolic knowledge map that a Piagetian sleep loop calibrates.
