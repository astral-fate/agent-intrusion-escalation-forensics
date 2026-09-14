#!/usr/bin/env bash
# Build main.pdf from the rendered main.tex.
#
#   ./build.sh
#
# Run `python ../verify.py` first: main.tex is generated from main.tex.tmpl and every number in
# it is substituted from ../data. Editing main.tex directly will be overwritten.
#
# Four passes, because bibtex needs an .aux and hyperref needs a settled .out. The last pass is
# the one whose exit status matters -- an earlier pass can write a PDF and a later one still
# fail, which is how a deterministic font error first looked intermittent here.
set -u

cd "$(dirname "$0")"

if [ ! -f main.tex ]; then
    echo "main.tex missing -- run: python ../verify.py" >&2
    exit 1
fi

rm -f main.pdf

pdflatex -interaction=nonstopmode main.tex > build1.log 2>&1
bibtex main                                > build_bib.log 2>&1
pdflatex -interaction=nonstopmode main.tex > build2.log 2>&1
pdflatex -interaction=nonstopmode main.tex > build3.log 2>&1

if [ ! -f main.pdf ]; then
    echo "BUILD FAILED -- no PDF produced. Errors:" >&2
    grep -E "^(!|! LaTeX Error|! pdfTeX error)" build3.log | head -20 >&2
    exit 1
fi

# Unresolved references render as "??" in the PDF and are easy to miss on a visual skim.
undef=$(grep -c -E "LaTeX Warning: (Citation|Reference) .* undefined" build3.log || true)
pages=$(grep -o "Output written on main.pdf ([0-9]* pages" build3.log | grep -o "[0-9]*" | head -1)

echo "built main.pdf -- ${pages:-?} pages, $(stat -c%s main.pdf) bytes"
if [ "$undef" -gt 0 ]; then
    echo "WARNING: $undef undefined citation/reference(s):"
    grep -E "LaTeX Warning: (Citation|Reference) .* undefined" build3.log | sort -u | head
    exit 1
fi
echo "all citations and references resolved"
