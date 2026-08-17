#!/usr/bin/env bash
# Assemble the static GitHub Pages demo site from frontend/.
#
# The frontend is written to be served by the FastAPI backend (assets under
# /static/, cross-links at /finance and /). GitHub Pages serves plain files
# from a subpath, so this script produces a self-contained _site/ with:
#   - assets moved under static/ so the existing static/... URLs resolve
#   - cross-page links rewritten to real .html files
#   - the demo mock (frontend/mock-api.js + frontend/mock/*.json) wired in
#
# frontend/ itself is never modified, so the real backend is unaffected.
#
# Usage: scripts/build_pages.sh [out_dir]   (default: _site)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$ROOT/_site}"
FE="$ROOT/frontend"

rm -rf "$OUT"
mkdir -p "$OUT/static" "$OUT/mock"

# Assets referenced as static/<file> by the HTML.
cp "$FE/styles.css" "$FE/app.js" "$FE/finance.js" "$OUT/static/"
# The mock lives at the site root (referenced by the injected script tag).
cp "$FE/mock-api.js" "$OUT/mock-api.js"
# Precomputed fixtures.
cp "$FE/mock/"*.json "$OUT/mock/"

# index.html: fix the /finance cross-link, inject the mock before app.js.
sed -e 's#href="/finance"#href="finance.html"#' \
    -e 's#<script src="static/app.js#<script src="mock-api.js"></script>\n<script src="static/app.js#' \
    "$FE/index.html" > "$OUT/index.html"

# finance.html: fix the / cross-link, inject the mock before finance.js.
sed -e 's#href="/"#href="index.html"#' \
    -e 's#<script src="static/finance.js#<script src="mock-api.js"></script>\n<script src="static/finance.js#' \
    "$FE/finance.html" > "$OUT/finance.html"

# Pages must not run Jekyll over our files.
touch "$OUT/.nojekyll"

echo "Built Pages site → $OUT"
ls -la "$OUT"
