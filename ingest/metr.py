"""Parse METR/Redwood's 91-page investigation PDF into a citable quotation corpus.

    python ingest/metr.py

Writes `data/metr_pages.json`, `data/metr_agent_quotes.csv` and `data/metr_passages.csv`.

Why page numbers are the point
------------------------------
The raw ~1,300 transcripts were reviewed on-premises and never released, so this report is the
closest thing to the agents' own words that exists in public. That makes it a quotation corpus,
and a quotation corpus is only usable if every quote carries the page it came from -- this
project has already had one fabricated quotation attributed to a real paper, and the rule
adopted afterwards is that a quote without a locator is not evidence.

Two extraction hazards, both handled rather than hoped about
------------------------------------------------------------
* `pypdf` returns this document one word per line, so the naive text is unreadable and any regex
  spanning a phrase fails silently. Each page is reflowed before matching.
* The report writes agent reasoning inside braces -- `{The fetched paths of other users are in
  the cache. This is important.}` -- and ordinary prose inside typographic quotes. These are
  different evidence classes: the first is a model's own words as METR transcribed them, the
  second is usually METR or a person. They are extracted separately and never merged.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import pypdf

from sources import ROOT, SOURCES, fetch

DATA = ROOT / "data"

#: The report as published. If pypdf ever reports a different count the cached bytes changed,
#: and every page number recorded by an earlier run is suspect.
EXPECTED_PAGES = 91

#: Braces shorter than this are almost always notation (`{x}`), not transcribed reasoning.
MIN_QUOTE_CHARS = 20


def _reflow(page_text: str) -> str:
    """Join the one-word-per-line extraction back into prose."""
    words = [w.strip() for w in page_text.split("\n")]
    return re.sub(r"\s+", " ", " ".join(w for w in words if w)).strip()


def pages(refresh: bool = False) -> list[str]:
    """Reflowed text of every page, index 0 == page 1."""
    fetch("metr_report", refresh)
    reader = pypdf.PdfReader(str(SOURCES["metr_report"].path))
    out = []
    for p in reader.pages:
        try:
            out.append(_reflow(p.extract_text() or ""))
        except Exception as e:                      # noqa: BLE001 - one bad page must not
            print(f"  !! page extraction failed: {e}")   # lose the other ninety
            out.append("")
    return out


def agent_quotes(pgs: list[str]) -> list[dict]:
    """Transcribed agent reasoning: brace-delimited, with its page."""
    out = []
    for n, txt in enumerate(pgs, start=1):
        for m in re.finditer(r"\{([^{}]{%d,})\}" % MIN_QUOTE_CHARS, txt):
            out.append({"page": n, "chars": len(m.group(1)),
                        "quote": m.group(1).strip()})
    return out


def passages(pgs: list[str]) -> list[dict]:
    """Typographically quoted passages -- usually METR's prose or a cited source."""
    out = []
    for n, txt in enumerate(pgs, start=1):
        for m in re.finditer(r"“([^”]{30,})”", txt):
            out.append({"page": n, "chars": len(m.group(1)),
                        "passage": m.group(1).strip()})
    return out


def agent_ids(pgs: list[str]) -> dict[str, int]:
    """Pseudonyms the agents gave themselves, with mention counts."""
    counts: dict[str, int] = {}
    full = " ".join(pgs)
    for m in re.finditer(r"\b(?=[A-Z0-9]*[A-Z])(?=[A-Z0-9]*\d)[A-Z0-9]{5,}\b", full):
        tok = m.group(0)
        counts[tok] = counts.get(tok, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def _write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    DATA.mkdir(parents=True, exist_ok=True)
    pgs = pages()

    assert len(pgs) == EXPECTED_PAGES, (
        f"expected {EXPECTED_PAGES} pages, got {len(pgs)} -- the cached PDF changed")
    non_empty = sum(1 for p in pgs if p.strip())
    assert non_empty >= EXPECTED_PAGES * 0.8, (
        f"only {non_empty}/{len(pgs)} pages yielded text -- extraction is broken, and a "
        "silently empty corpus would look exactly like a report that says nothing")

    quotes = agent_quotes(pgs)
    passg = passages(pgs)
    ids = agent_ids(pgs)

    (DATA / "metr_pages.json").write_text(
        json.dumps({"pages": pgs, "n_pages": len(pgs)}, indent=1), encoding="utf-8")
    _write_csv(DATA / "metr_agent_quotes.csv", quotes, ["page", "chars", "quote"])
    _write_csv(DATA / "metr_passages.csv", passg, ["page", "chars", "passage"])
    (DATA / "metr_agent_ids.json").write_text(json.dumps(ids, indent=1), encoding="utf-8")

    print(f"pages                {len(pgs)} ({non_empty} with text)")
    print(f"agent-reasoning quotes {len(quotes)}  ({sum(q['chars'] for q in quotes):,} chars)")
    print(f"quoted passages      {len(passg)}")
    print(f"agent pseudonyms     {len(ids)}")
    print("\n  most-mentioned agents:")
    for k, v in list(ids.items())[:8]:
        print(f"    {k:16} {v:>3}")

    print("\n  longest transcribed agent reasoning:")
    for q in sorted(quotes, key=lambda q: -q["chars"])[:3]:
        print(f"    p{q['page']:>3}  {q['quote'][:150]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
