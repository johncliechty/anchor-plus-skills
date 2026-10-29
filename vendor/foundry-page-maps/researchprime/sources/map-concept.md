# Poincaré knowledge maps for Foundry skills (concept, corrected 2026-10-03)

**Correction (John, 2026-10-03):** the "Piaget hierarchy" he remembered is the **Poincaré** (hyperbolic) geometry of
Nickel & Kiela 2017 ("Poincaré Embeddings for Learning Hierarchical Representations": 2–5 hyperbolic dimensions
matched or beat 200 Euclidean dimensions on hierarchical data); the **Lorentz** model is their 2018 follow-up for
stable training on deeper hierarchies. Piaget keeps a role later: the sleep loop's assimilate / accommodate cycle.
Everything this effort called the "Piaget sphere" is renamed the **Poincaré knowledge map**.

## What it is
- **One map per skill** (later, per cognitive cell), of the knowledge, methods, tools, skills it commissions and
  places to look that the skill actually uses when it executes tasks.
- **Derived, not drawn:** built up and calibrated from real data: the skill's run records (which steps ran, which
  sources and files were read, which prompts and references were used), its journal and its outcomes. It grows
  with use; it is not authored by John.
- **Geometry:** each node is a point in hyperbolic space. Distance from the origin = generality (general,
  heavily-used, highly-connected knowledge near the center; specific material toward the rim); siblings sit close;
  distant branches sit far apart. Trees embed in hyperbolic space with low distortion in very few dimensions, which
  is why it is efficient. Train and store in the **Lorentz** model (numerically stable); project to the **Poincaré
  disk/ball** for display.
- **What it is for: context management.** When the skill takes a task, a router (mixture-of-experts style) picks
  the relevant branches and pulls only that part of the knowledge base into the context window, leaving the rest
  untouched. A more general node brings a summary; descending a branch brings specifics. Over time the map makes
  the skill cheaper and more accurate because it loads less and loads the right things.
- **How it learns (Piaget's later role):** each run is assimilated (usage counts, co-use edges, outcome credit on the
  nodes used); the sleep cycle accommodates (re-embeds, splits an overloaded node, merges duplicates, moves a node
  that keeps being used with another branch), proposing structural changes for John's approval.

## Relation to John's existing work
- BASE-BRAIN-SPEC v2.0.2: per-cell knowledge store; "Knowledge-Linear vs Knowledge-Lorentz"; apex = general.
- Geometric Memory report (Report 4): hyperbolic ontology + product-space facets + analogy graph; Symbolic-MoE
  routing with skill cards and a routing ledger; GEO worker re-embeds after consolidation.
- PLAN-Alpha-Agent-Brain-v2 §P13: Tournament 1, Linear cell vs Poincaré cell at matched compute (the empirical test).
- T2R design D3: start flat; defer Lorentz until the ontology is deeper than 3 levels.
- His Variable Selection work (not on this machine): Poincaré-ball covariance with a calibrated link; the Bell-number
  limit of a fixed-curvature ball and the product-simplex / variable-curvature fix.

## What the Foundry page shows (replaces the hand-drawn "sphere")
- The map drawn in the Poincaré disk: center = the skill's most general, most-used knowledge; zoom by moving the
  focus (the hyperbolic "fisheye": the region you look at expands, the rest compresses to the rim), click a node for
  its source card (what it is, which files/prompts/sources it stands for, how often it is used, by which steps).
- Lenses: usage, recency, outcome credit, source type; and what the router loaded on the last run.
- Until enough run data exists, the map is seeded from the traced process map and the skill's files, and labelled
  "seeded, not yet calibrated".
