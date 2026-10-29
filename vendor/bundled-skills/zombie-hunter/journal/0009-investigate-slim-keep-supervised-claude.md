---
id: 0009-investigate-slim-keep-supervised-claude
skill: zombie-hunter@w10-2026-09-15
situation: investigate-slim-seed-no-candidate
context: grok-build investigate W8/SC5 2026-09-15 16:50Z; live radar :48484; session da24c8d3
observation: Slim seed had pid/class unknown and no reason codes. Fresh sweep 16:49:16Z was shadow, NO_WOULD_BE_RED, 0 zombies, 0 observe RED, freeze/kill forbidden (no canary, SC1 unclaimed, DESTRUCTIVE_ELIGIBLE unset). Host freezeCapability true; seed said false. Measured burn ~$0.10/min is supervised claude.exe 44880 (session 1, powershell parent, ~5.5h, SPEND_NEGATIVE port-443-alone, QUAD_KEEP). Why/deep-brief recommendedNext KEEP. This hunt is grok.exe 27084 under nssm→anchor_gui.py session 0 (UNSUPERVISED + SPEND_NEGATIVE + QUAD_KEEP). Yesterday leftover Investigate grok.exe 32112/75588/58916/80804/80980 and VS Code grok 28168 / claude 50812 are dead. Idle claude.exe 28584 (session 1) not treated. Correct treat is KEEP the one radar burner, not freeze/kill, not invent a zombie.
outcome: worked
provenance: genuine-execution
---

Empty Investigate seed + 0 radar zombies. Treated the only live burner (claude.exe 44880) as KEEP. Freeze/kill refused under shadow.
