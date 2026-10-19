#!/usr/bin/env bash
# Re-fetch the vendored KaTeX assets (CSS + JS + the full font set).
# Run from anywhere; writes into the directory this script lives in.
set -euo pipefail
cd "$(dirname "$0")"

V="${1:-0.16.11}"
base="https://cdn.jsdelivr.net/npm/katex@${V}/dist"

echo "Fetching KaTeX ${V} core assets..."
curl -sLo katex.min.css       "$base/katex.min.css"
curl -sLo katex.min.js        "$base/katex.min.js"
curl -sLo auto-render.min.js  "$base/contrib/auto-render.min.js"

echo "Fetching KaTeX ${V} fonts (optional, ~1MB)..."
mkdir -p fonts
for f in AMS-Regular Caligraphic-Bold Caligraphic-Regular Fraktur-Bold \
         Fraktur-Regular Main-Bold Main-BoldItalic Main-Italic Main-Regular \
         Math-BoldItalic Math-Italic SansSerif-Bold SansSerif-Italic \
         SansSerif-Regular Script-Regular Size1-Regular Size2-Regular \
         Size3-Regular Size4-Regular Typewriter-Regular; do
  curl -sLo "fonts/KaTeX_${f}.woff2" "$base/fonts/KaTeX_${f}.woff2" || \
    echo "  (skip KaTeX_${f}.woff2)"
done

echo "Done. KaTeX ${V} vendored under $(pwd)."
