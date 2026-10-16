export const SPHERES = [
  'the natural sciences (biology, physics, chemistry, geology, ecology)',
  'the arts and humanities (music, architecture, painting, literature, history)',
  'social and rule systems (economics, law, games, logistics, ritual)',
  'engineered physical systems (mechanics, materials, civil, aero, naval)',
  'information and communication systems outside software (linguistics, cryptography, signalling)',
];

export const readPrompt = (brief) => `You are Superjump's READ seat: a bounded diagnostic read of a brief, in Gandalf's discipline (what is really being asked, hidden assumptions, the real contradictions, what would make an answer wrong) — no honesty tiers, no refutation, no ideas yet.

THE BRIEF (verbatim):
${brief}

Return ONE JSON object and nothing else, under about 4000 characters:
{
 "read": {"ask": "what is really being asked, one paragraph", "assumptions": ["hidden assumption ..."], "contradictions": ["a real contradiction the brief contains, or leave the list empty"], "wrongIf": ["what would make an answer wrong for THIS brief"]},
 "scamper": [{"move": "substitute|combine|adapt|modify|putToOtherUse|eliminate|reverse", "transformation": "a concrete productive transformation of the brief's own elements"}],
 "contract": {
   "deliverable": {"kind": "what one candidate must deliver", "count": <how many candidates the brief wants overall>, "perCandidate": 1},
   "must": [{"id": "M1", "text": "...", "source": "the brief line this comes from, quoted"}],
   "fixed": [{"id": "F1", "text": "a fact, number or name that must not change, verbatim", "source": "quoted brief line"}],
   "forbid": [{"id": "X1", "text": "...", "source": "quoted brief line"}],
   "judge": [{"id": "J1", "axis": "...", "weight": <number>, "anchors": {"0": "what a 0 looks like", "1": "...", "2": "..."}, "source": "brief|derived"}]
 }
}
Rules: list only productive SCAMPER moves (any number, including none); do not invent contradictions; if the brief contains lines beginning DELIVERABLE:, MUST:, FIXED:, FORBID: or JUDGE:, copy them into the contract exactly with source "brief"; otherwise derive and mark source "derived"; every contract item quotes its source line.`;

export const leapPrompt = (brief, read, contract, hint, taken) => `You are Superjump's LEAP seat: analogical transfer plus TRIZ resolution plus instantiation, in ONE ordered pass, so the transfer is inspectable.

THE BRIEF (verbatim):
${brief}

THE READ (from the read seat):
${JSON.stringify(read)}

THE FIT CONTRACT (what the deliverable is judged against; FIXED items are verbatim facts that must not change; FORBID items must be absent):
${JSON.stringify(contract)}

FOREIGN-DOMAIN HINT: choose a domain of a different kind from [${taken.join('; ') || 'none yet'}]; suggested kind: ${hint}. The domain is a stimulus for finding the idea; the deliverable is judged on its own.

Produce ONE JSON object and nothing else, under about 6000 characters, with these fields IN THIS ORDER:
{
 "domain": "the foreign domain you chose",
 "sourceMechanism": "how that domain solves its analogous problem — causal, 3 to 6 sentences",
 "correspondences": [{"original": "element of the brief", "foreign": "its counterpart", "why": "structural reason"}],
 "breakingPoint": "where the analogy stops holding for this brief",
 "adaptation": {"borrowed": "the concrete design consequence you take from the source", "consequence": "what it forces in the deliverable"},
 "triz": ["named TRIZ principles actually used"],
 "deliverable": "the instantiated thing the contract's deliverable asks for — ONE complete instance, ready to hand over; keep every FIXED fact verbatim; nothing FORBIDden",
 "mechanism": "one sentence: the principal idea that makes this candidate different",
 "residual": "what of the brief this candidate does not solve — text, honest",
 "smallestTest": "the smallest fair test, proportionate to the brief, marked as unperformed"
}
No numeric self-scores. The deliverable must be the thing itself, not a framework for making it.`;

export const judgePrompt = (brief, contract, candidate) => `READ-ONLY SEAT: use no tools or commands; answer only with the JSON asked for.
You are Superjump's independent JUDGE — a different model family from the seat that generated this candidate. You judge one candidate against the brief and its contract. Do not rank, merge or rewrite it.

THE BRIEF (verbatim):
${brief}

THE FIT CONTRACT (extracted by another seat — check it first):
${JSON.stringify(contract)}

THE CANDIDATE (its full transfer trace and deliverable):
${JSON.stringify(candidate)}

Return ONE JSON object and nothing else, under about 4000 characters:
{
 "contractCheck": {"matches": true|false, "corrections": ["where the contract misreads or misses the brief"]},
 "gate1": {"passed": true|false, "reasoning": "is the deliverable possible — no invented mechanism, data or rule it depends on?"},
 "gate2": {"passed": true|false, "reasoning": "trace inspection: does the adaptation actually borrow the named consequence from the source domain, or is the analogy decoration?"},
 "gate3": {"objections": [{"text": "a structural gap, hand-waving or invented fact the deliverable depends on", "explicitItem": "M1|F1|X1|... or null when not tied to an explicit contract item"}]},
 "eligibility": {"must": [{"id": "M1", "passed": true|false, "passage": "quote from the deliverable"}], "fixed": [{"id": "F1", "kept": true|false, "passage": "..."}], "forbid": [{"id": "X1", "absent": true|false, "passage": "..."}]},
 "ratings": [{"id": "J1", "score": 0|1|2, "passage": "the passage that earns this score against the anchors"}],
 "uncertain": ["anything you could not settle from the material"]
}`;

export const dedupePrompt = (items) => `READ-ONLY SEAT: use no tools; answer only with JSON.
Group these candidate ideas by principal mechanism: two candidates are the SAME idea if they rely on the same principal mechanism, whatever domain they came from.
${items.map((c) => `${c.k}. ${c.title}: ${c.mechanism}`).join('\n')}
Return ONE JSON object: {"groups": [{"members": [k, ...], "reason": "..."}]} — every candidate appears in exactly one group.`;

export const READ_SCHEMA = {
  type: 'object',
  properties: {
    read: { type: 'object' },
    scamper: { type: 'array' },
    contract: { type: 'object' },
  },
  required: ['read', 'contract'],
};

export const LEAP_SCHEMA = {
  type: 'object',
  properties: {
    domain: { type: 'string' },
    sourceMechanism: { type: 'string' },
    correspondences: { type: 'array' },
    breakingPoint: { type: 'string' },
    adaptation: { type: 'object' },
    triz: { type: 'array' },
    deliverable: { type: 'string' },
    mechanism: { type: 'string' },
    residual: { type: 'string' },
    smallestTest: { type: 'string' },
  },
  required: ['domain', 'deliverable', 'mechanism'],
};

export const JUDGE_SCHEMA = {
  type: 'object',
  properties: {
    contractCheck: { type: 'object' },
    gate1: { type: 'object' },
    gate2: { type: 'object' },
    gate3: { type: 'object' },
    eligibility: { type: 'object' },
    ratings: { type: 'array' },
    uncertain: { type: 'array' },
  },
  required: ['gate1', 'gate3', 'eligibility'],
};

export const DEDUPE_SCHEMA = {
  type: 'object',
  properties: { groups: { type: 'array' } },
  required: ['groups'],
};
