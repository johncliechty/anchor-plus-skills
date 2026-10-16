#!/usr/bin/env bash
# w0-runs.sh — Superjump Wave 0: five prototype runs, sequential, timings kept clean.
# Controls (lean mode on both briefs) are yesterday's runs under jumper/planning/review-2026-09-13/comparison.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SJ="$(cd "$HERE/.." && pwd)"
CMP="$SJ/../jumper/planning/review-2026-09-13/comparison/briefs"
OUT="$SJ/planning/crucible-2026-09-14/proto"
LOG="$OUT/runs.jsonl"
mkdir -p "$OUT"
stamp() { date -u +%Y-%m-%dT%H:%M:%SZ; }
one() {  # label brief coding-effort review-effort
  local label="$1" brief="$2" ce="$3" re="$4" t0 t1 rc
  t0="$(stamp)"
  node "$SJ/tools/prototype.mjs" --brief "$brief" --coding-effort "$ce" --review-effort "$re" --candidates 3 --out "$OUT/$label" --label "$label" 2>> "$OUT/$label.stderr.log"; rc=$?
  t1="$(stamp)"
  printf '{"label":"%s","coding_effort":"%s","review_effort":"%s","started":"%s","ended":"%s","exit":%s}\n' "$label" "$ce" "$re" "$t0" "$t1" "$rc" >> "$LOG"
}
one teaching-ultra-highest  "$CMP/teaching-einstein-cover.txt"   ultra highest
one teaching-max-highest    "$CMP/teaching-einstein-cover.txt"   max   highest
one artifact-ultra-highest  "$CMP/artifact-book1-victories.md"   ultra highest
one artifact-max-highest    "$CMP/artifact-book1-victories.md"   max   highest
one teaching-ultra-next     "$CMP/teaching-einstein-cover.txt"   ultra next
echo "w0 complete $(stamp)" >> "$LOG"
