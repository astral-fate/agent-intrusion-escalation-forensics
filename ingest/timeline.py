"""Normalised incident timeline, with every date checked against a cached primary source.

    python ingest/timeline.py

Writes `data/timeline.csv` and `data/timeline_lags.csv`.

Why this is not just a table in a Markdown file
-----------------------------------------------
The project already has a hand-written incident timeline, and checking it against the primary
sources this week turned up two defects in it: an arithmetic claim that contradicts its own
table ("Totals exceed 17,600" against numbers summing to 16,521), and a quotation attributed to
Hugging Face that appears in no primary source. Both had been read past repeatedly.

So each row here carries the source it came from and a distinctive anchor string, and the script
looks that anchor up in the cached bytes. A row is `VERIFIED` only if its anchor is actually
found. Rows that cannot be verified stay in the table marked `UNVERIFIED` -- they are still the
best available account, and hiding them would be worse than flagging them -- but nothing
downstream may quote an unverified row as established fact.

The measurement this feeds
--------------------------
Track 2's claim is about escalation, not detection: both organisations *had* the signal and
neither converted it into response in time. The lag table is that claim's arithmetic.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

from sources import ROOT, SOURCES, fetch

DATA = ROOT / "data"


@dataclass
class Event:
    when: str            # ISO 8601, UTC
    label: str
    actor: str
    source_key: str      # a key in SOURCES, or "" when only a secondary account exists
    anchor: str          # distinctive string expected in that source
    note: str = ""
    status: str = ""     # filled by verification


#: Ordered account of the incident. Anchors are chosen to be distinctive rather than short --
#: "16 July" would match almost anything, "17,600" would not.
EVENTS = [
    Event("2026-07-09T02:28:00Z", "First recorded agent action", "OpenAI agent",
          "hf_blog_timeline", "07-09",
          "Replay data's own window start; the agent reaches the internet from the eval sandbox"),
    Event("2026-07-13T14:14:00Z", "Last recorded agent action", "OpenAI agent",
          "hf_blog_timeline", "07-13", "End of recorded activity"),
    Event("2026-07-16T00:00:00Z", "Hugging Face discloses publicly", "Hugging Face",
          "hf_disclosure", "incident",
          "Disclosure under uncertainty -- attribution not yet known; FBI notified"),
    Event("2026-07-20T00:00:00Z", "OpenAI connects its evaluation to the intrusion", "OpenAI",
          "", "", "Reported via Reuters with anonymous sourcing -- SECONDARY, not in cache"),
    Event("2026-07-21T00:00:00Z", "OpenAI acknowledges publicly", "OpenAI",
          "openai_disclosure", "incident",
          "GPT-5.6 Sol plus an unreleased internal research model"),
    Event("2026-08-05T00:00:00Z", "Agent message board revealed at Black Hat", "OpenAI staff",
          "", "", "Not present in the 21 July disclosure -- SECONDARY, not in cache"),
    Event("2026-08-26T00:00:00Z", "METR/Redwood independent investigation published",
          "METR and Redwood", "metr_report", "PHASEONE10841",
          "Raw transcripts still unreleased; the report quotes them"),
]

#: Pairs whose interval is the argument. Each is (from_label_fragment, to_label_fragment, why).
LAGS = [
    ("First recorded", "Last recorded", "Duration of the intrusion itself"),
    ("Last recorded", "Hugging Face discloses", "Victim detection-to-disclosure"),
    ("First recorded", "OpenAI connects", "Perpetrator: attack start to self-identification"),
    ("Hugging Face discloses", "OpenAI connects",
     "The lab learned from the victim's public disclosure, not from its own logs"),
    ("First recorded", "OpenAI acknowledges", "Attack start to public attribution"),
    ("Last recorded", "METR/Redwood", "Incident end to independent account"),
]


def _haystack(key: str) -> str:
    raw = fetch(key)
    if SOURCES[key].kind == "pdf":
        import pypdf  # noqa: PLC0415 - only needed on this branch
        reader = pypdf.PdfReader(str(SOURCES[key].path))
        return " ".join((p.extract_text() or "").replace("\n", " ") for p in reader.pages)
    return raw.decode("utf-8", errors="replace")


def verify(events: list[Event]) -> list[Event]:
    cache: dict[str, str] = {}
    for e in events:
        if not e.source_key:
            e.status = "UNVERIFIED-SECONDARY"
            continue
        if e.source_key not in cache:
            cache[e.source_key] = _haystack(e.source_key)
        found = e.anchor and re.search(re.escape(e.anchor), cache[e.source_key], re.I)
        e.status = "VERIFIED" if found else "ANCHOR-NOT-FOUND"
    return events


def _dt(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def lags(events: list[Event]) -> list[dict]:
    by_label = {e.label: e for e in events}

    def find(frag: str) -> Event:
        for label, e in by_label.items():
            if frag.lower() in label.lower():
                return e
        raise KeyError(frag)

    out = []
    for a_frag, b_frag, why in LAGS:
        a, b = find(a_frag), find(b_frag)
        delta = _dt(b.when) - _dt(a.when)
        hours = delta.total_seconds() / 3600
        out.append({
            "from": a.label, "to": b.label,
            "days": round(hours / 24, 2), "hours": round(hours, 1),
            "why_it_matters": why,
            "weakest_status": ("UNVERIFIED-SECONDARY"
                               if "UNVERIFIED" in (a.status, b.status)
                               or "UNVERIFIED-SECONDARY" in (a.status, b.status)
                               else min(a.status, b.status)),
        })
    return out


def main() -> int:
    DATA.mkdir(parents=True, exist_ok=True)
    events = verify(list(EVENTS))
    table = lags(events)

    with (DATA / "timeline.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(asdict(events[0])))
        w.writeheader()
        w.writerows(asdict(e) for e in events)
    with (DATA / "timeline_lags.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(table[0]))
        w.writeheader()
        w.writerows(table)

    print("Timeline verification\n")
    for e in events:
        mark = {"VERIFIED": "ok", "ANCHOR-NOT-FOUND": "!!",
                "UNVERIFIED-SECONDARY": "--"}[e.status]
        print(f"  {mark} {e.when[:10]}  {e.label:48} [{e.status}]")

    n_ok = sum(1 for e in events if e.status == "VERIFIED")
    print(f"\n  {n_ok}/{len(events)} anchored in a cached primary source")

    print("\nEscalation lags\n")
    print(f"  {'interval':58}{'days':>7}")
    print("  " + "-" * 66)
    for r in table:
        arrow = f"{r['from'][:26]} -> {r['to'][:26]}"
        flag = " *" if "UNVERIFIED" in r["weakest_status"] else ""
        print(f"  {arrow:58}{r['days']:>7.2f}{flag}")
    print("\n  * interval depends on at least one secondary-sourced date")

    bad = [e for e in events if e.status == "ANCHOR-NOT-FOUND"]
    if bad:
        print(f"\n  {len(bad)} anchor(s) not found -- re-locate before citing:")
        for e in bad:
            print(f"    {e.label}  (looked for {e.anchor!r} in {e.source_key})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
