"""Parse OpenAI's 38-page incident technical report into a timestamped escalation record.

    python ingest/openai_tr.py

Writes `data/openai_tr_timeline.csv` and `data/openai_tr_escalation.json`.

Why this source was added in revision
-------------------------------------
The first version of this paper supported its perpetrator-side claim with a sentence -- "at the
perpetrator, the evidence was internal from the outset" -- that no source states, and with a
press-reported four-day interval between the victim's disclosure and OpenAI's self-identification.
That interval is an *attribution* latency. It is not an escalation failure, and OpenAI's own
report says so explicitly: of the 19 July alert, "At the time, there was no indication of a
relationship between that July 19 activity and the Hugging Face incident."

The escalation failure at the perpetrator is nevertheless in the public record, in this document
and nowhere else: a true-positive alert at 12:03 UTC on 19 July, and responders beginning to stop
the runs at 17:37 UTC the same day. The appendix also timestamps what happened in between, which
is what makes the interval consequential rather than merely long.

Two extraction properties, both checked rather than assumed
-----------------------------------------------------------
* Unlike the METR report, this PDF extracts in reading order, and the appendix renders as
  `2026-07-19 \\n 12:03 UTC \\n <description>`. That is parsed directly; no reflow is needed.
  `EXPECTED_PAGES` guards against the cached bytes changing under a later run.
* Each of the two escalation entries is located by an anchor substring, not by row index, so a
  reordered or extended appendix fails loudly instead of silently selecting the wrong row.
"""
from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timedelta

import pypdf

from sources import ROOT, SOURCES, fetch

DATA = ROOT / "data"

#: The report as published. A different count means the cached bytes changed and every
#: timestamp recorded by an earlier run is suspect.
EXPECTED_PAGES = 38

#: `2026-07-19` / `12:03 UTC` / description, in that order, as the appendix renders.
ENTRY_RE = re.compile(
    r"(?P<date>20\d{2}-\d{2}-\d{2})\s*\n\s*(?P<time>\d{2}:\d{2})\s*UTC\s*\n"
    r"(?P<desc>.*?)(?=\n20\d{2}-\d{2}-\d{2}\s*\n\s*\d{2}:\d{2}\s*UTC|\Z)",
    re.S,
)

#: The two rows the escalation interval is measured between. Anchors, not indices: if OpenAI
#: revises the appendix these raise rather than quietly matching a neighbouring row.
ALERT_ANCHOR = "Cybersecurity monitoring tool triggers an alert"
RESPONSE_ANCHOR = "incident responders began stopping the active ExploitGym runs"

#: The day the alert fired. Both endpoints must fall on it; a cross-midnight pair would mean
#: the anchors matched the wrong rows.
ESCALATION_DATE = "2026-07-19"


def pages(refresh: bool = False) -> list[str]:
    """Text of every page, index 0 == page 1."""
    fetch("openai_tech_report", refresh)
    reader = pypdf.PdfReader(str(SOURCES["openai_tech_report"].path))
    if len(reader.pages) != EXPECTED_PAGES:
        raise ValueError(
            f"openai_tech_report: expected {EXPECTED_PAGES} pages, got {len(reader.pages)} -- "
            "the cached bytes changed; re-verify every timestamp before trusting them"
        )
    return [p.extract_text() or "" for p in reader.pages]


def _clean(desc: str) -> str:
    return re.sub(r"\s+", " ", desc).strip()


def timeline(pgs: list[str] | None = None) -> list[dict]:
    """Every timestamped appendix entry, with the page it was read from."""
    pgs = pages() if pgs is None else pgs
    out: list[dict] = []
    for i, text in enumerate(pgs, start=1):
        for m in ENTRY_RE.finditer(text):
            out.append({
                "date": m.group("date"),
                "time": m.group("time"),
                "page": i,
                "desc": _clean(m.group("desc")),
            })
    return out


def _row(rows: list[dict], anchor: str) -> dict:
    hits = [r for r in rows if anchor in r["desc"]]
    if len(hits) != 1:
        raise ValueError(
            f"openai_tech_report: anchor {anchor!r} matched {len(hits)} appendix rows, "
            "expected exactly 1 -- the appendix changed shape"
        )
    return hits[0]


def escalation(rows: list[dict] | None = None) -> dict:
    """The 19 July alert-to-response interval, and what the appendix records inside it."""
    rows = timeline() if rows is None else rows
    alert = _row(rows, ALERT_ANCHOR)
    response = _row(rows, RESPONSE_ANCHOR)

    for label, r in (("alert", alert), ("response", response)):
        if r["date"] != ESCALATION_DATE:
            raise ValueError(
                f"openai_tech_report: {label} row is dated {r['date']}, expected "
                f"{ESCALATION_DATE} -- the anchors matched the wrong rows"
            )

    fmt = "%Y-%m-%d %H:%M"
    t0 = datetime.strptime(f"{alert['date']} {alert['time']}", fmt)
    t1 = datetime.strptime(f"{response['date']} {response['time']}", fmt)
    gap: timedelta = t1 - t0
    if gap.total_seconds() <= 0:
        raise ValueError("openai_tech_report: response precedes alert -- anchors misaligned")

    between = [r for r in rows
               if r["date"] == ESCALATION_DATE and alert["time"] < r["time"] < response["time"]]

    return {
        "alert": alert,
        "response": response,
        "gap_minutes": int(gap.total_seconds() // 60),
        "gap_hours": gap.total_seconds() / 3600.0,
        "between": between,
    }


def write(refresh: bool = False) -> dict:
    DATA.mkdir(parents=True, exist_ok=True)
    rows = timeline(pages(refresh))
    esc = escalation(rows)

    with (DATA / "openai_tr_timeline.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["date", "time", "page", "desc"])
        w.writeheader()
        w.writerows(rows)

    (DATA / "openai_tr_escalation.json").write_text(
        json.dumps(esc, indent=2), encoding="utf-8")
    return esc


if __name__ == "__main__":
    e = write()
    h, m = divmod(e["gap_minutes"], 60)
    print(f"appendix entries : {len(timeline())}")
    print(f"alert            : {e['alert']['date']} {e['alert']['time']} UTC "
          f"(p.{e['alert']['page']})")
    print(f"response         : {e['response']['date']} {e['response']['time']} UTC "
          f"(p.{e['response']['page']})")
    print(f"gap              : {h}h {m:02d}m")
    print(f"entries inside   : {len(e['between'])}")
    for r in e["between"]:
        print(f"  {r['time']} UTC  {r['desc'][:88]}")
