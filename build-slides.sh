#!/usr/bin/env bash
# Render the deck at index.html to docs/slides.pdf, one page per slide.
#
#   ./build-slides.sh
#
# index.html IS the deck: it is what GitHub Pages serves at the project URL and what this
# script exports. There is deliberately no second copy of the slides anywhere -- a landing
# page that duplicated the deck's content would be the thing that goes stale.
#
# The deck is authored as HTML because it carries live layout -- CSS grid columns, gradient
# tiles, an inline SVG of the pipeline -- that a slide tool would flatten. `.slide` sets
# `page-break-after: always` and the print block pins each slide to one `100vh` page, so a
# browser's print path is the renderer: headless Chrome honours the page breaks, the
# `@page { size: A4 landscape }` rule and the dark backgrounds, where a generic html-to-pdf
# converter drops all three.
#
# --virtual-time-budget matters: without it Chrome can snapshot before fonts and layout settle,
# which shows up as a deck with the right text at the wrong sizes.
set -u
cd "$(dirname "$0")"

SRC="$(pwd)/index.html"
OUT="$(pwd)/docs/slides.pdf"

CHROME=""
for c in \
  "/c/Program Files/Google/Chrome/Application/chrome.exe" \
  "/c/Program Files (x86)/Google/Chrome/Application/chrome.exe" \
  "/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" \
  "/c/Program Files/Microsoft/Edge/Application/msedge.exe" \
  "$(command -v google-chrome || true)" \
  "$(command -v chromium || true)"
do
  [ -n "$c" ] && [ -x "$c" ] && CHROME="$c" && break
done

if [ -z "$CHROME" ]; then
    echo "no Chrome or Edge found -- open index.html and print to PDF instead" >&2
    exit 1
fi

# Convert the path to a file:// URL Chrome accepts on Windows.
URL="file:///$(echo "$SRC" | sed 's|^/\([a-z]\)/|\1:/|' | sed 's| |%20|g')"

mkdir -p docs
rm -f "$OUT"
"$CHROME" --headless --disable-gpu --no-pdf-header-footer --no-margins \
          --virtual-time-budget=15000 --print-to-pdf="$OUT" "$URL" >/dev/null 2>&1

if [ ! -f "$OUT" ]; then
    echo "BUILD FAILED -- no PDF produced" >&2
    exit 1
fi

# Count pages from the PDF and slides from the numbering stamp, which every slide carries.
# pypdf rather than a byte scan for /Type/Page: the scan needs the path interpolated into the
# -c string, which breaks on a directory containing a space and then reports "?" forever --
# a guard that silently stops guarding is worse than no guard.
pages=$(python -c "import sys,pypdf;print(len(pypdf.PdfReader(sys.argv[1]).pages))" "$OUT" 2>/dev/null || echo "?")
slides=$(grep -c 'class="slide-num"' "$SRC")

echo "built docs/slides.pdf -- $pages pages from $slides slides, $(stat -c%s "$OUT") bytes"

# A mismatch means a slide overflowed onto a second page, which is invisible in the HTML and
# obvious in the PDF only if you count. Worth failing on rather than shipping a deck whose
# numbering no longer matches its pages.
if [ "$pages" != "?" ] && [ "$pages" -ne "$slides" ]; then
    echo "WARNING: $pages pages from $slides slides -- a slide is overflowing" >&2
    exit 1
fi
