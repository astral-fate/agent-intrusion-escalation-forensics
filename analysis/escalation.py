"""Detection was not the failure. Escalation was.

    python analysis/escalation.py

Writes `results/escalation.json`.

The argument
------------
Both organisations held the signal and neither converted it into response in time.

* **Hugging Face** -- a detection fired. In their own words it "failed to correctly raise the
  alert's criticality and trigger the on-call team, costing precious time in the response."
  Coverage worked; prioritisation did not.
* **OpenAI** -- the evidence was in its own logs, and it connected the intrusion to its own
  evaluation four days *after* the victim disclosed publicly.

Why that is a research finding and not just a bad week
------------------------------------------------------
Process-safety engineering has treated alarm priority as a first-class, measurable property for
twenty-five years. EEMUA 191 and ISA-18.2 both publish a target distribution -- roughly 80% low,
15% medium, 5% high -- precisely so that a genuine emergency is distinguishable from background.
Mis-prioritisation is a named, measured failure there.

Security alert-screening research has no such object. This project's `BASERATE-F` prior-art pass
found that the field's 2026 state-of-the-art formalisation uses a **binary {malicious, benign}
label space** admitting exactly three failure quantities -- false-positive rate, unhandled-incident
rate, and a degradation term. "Correctly labelled malicious, wrongly prioritised" has no place in
it. The failure mode that decided this incident is formally unrepresentable in the literature
meant to study it.

What is NOT claimed
-------------------
That Hugging Face's alarm distribution violates 80/15/5. Their alert configuration was never
published and cannot be computed from anything here. The distribution is cited as evidence that
one engineering discipline treats priority as measurable and the other does not -- a claim about
the two literatures, not a measurement of HF's alerting.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ingest"))

import hfblog  # noqa: E402
import replay  # noqa: E402
import sources  # noqa: E402
import timeline  # noqa: E402

RESULTS = ROOT / "results"

#: Recommended alarm-priority distribution, low/medium/high. Stated by both EEMUA 191 and
#: ISA-18.2 and reported consistently by independent industry sources (exida, Emerson, ABB).
#: The standards themselves are paywalled; this is therefore SECONDARY-CORROBORATED and is
#: labelled as such wherever it is used. It is a target distribution for alarm configuration,
#: not a benchmark any figure in this incident is compared against.
ALARM_PRIORITY_TARGET = {"low": 0.80, "medium": 0.15, "high": 0.05}
ALARM_TARGET_STATUS = "SECONDARY-CORROBORATED (primary standards paywalled)"


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)

    events = timeline.verify(list(timeline.EVENTS))
    lags = timeline.lags(events)
    days = replay.load()["DAYS"]
    total = sum(d["actions"] for d in days)
    quotes = hfblog.quotes(sources.text("hf_blog_timeline"))
    quotes.update(hfblog.disclosure_quotes(sources.text("hf_disclosure")))

    busiest = max(days, key=lambda d: d["actions"])

    print("Escalation intervals\n")
    print(f"  {'interval':56}{'days':>7}  source")
    print("  " + "-" * 74)
    for r in lags:
        flag = "secondary" if "UNVERIFIED" in r["weakest_status"] else "primary"
        print(f"  {r['from'][:26] + ' -> ' + r['to'][:26]:56}{r['days']:>7.2f}  {flag}")

    print("\nThe two escalation failures\n")
    print("  Hugging Face -- detection fired, criticality did not. Verbatim, from the technical")
    print("  timeline:")
    print(f"    \"{quotes['detection_criticality']['text'][:200]}\"")
    print()
    hf_disc = next(r for r in lags if "Hugging Face discloses" in r["from"])
    print(f"  OpenAI -- held the evidence in its own logs and connected it {hf_disc['days']:.2f} "
          "days AFTER the")
    print("  victim's public disclosure. The perpetrator learned from the victim.")
    print("  (This interval rests on a secondary, anonymously-sourced date and is flagged")
    print("   everywhere it appears.)")

    print("\nActivity was bursty, which is what makes prioritisation load-bearing\n")
    for d in days:
        bar = "#" * round(40 * d["actions"] / busiest["actions"])
        print(f"  {d['label']}  {d['actions']:>6,}  {100 * d['actions'] / total:>5.1f}%  {bar}")
    print(f"\n  {busiest['label']} alone carries {busiest['actions']:,} of {total:,} actions "
          f"({100 * busiest['actions'] / total:.1f}%).")
    print("  A queue that does not rank cannot survive a day like that -- which is the")
    print("  practical reason priority, not coverage, is the binding constraint.")

    print("\nThe baseline, and exactly what it does and does not license\n")
    t = ALARM_PRIORITY_TARGET
    print(f"  EEMUA 191 / ISA-18.2 target distribution: {t['low']:.0%} low, "
          f"{t['medium']:.0%} medium, {t['high']:.0%} high.")
    print(f"  Status: {ALARM_TARGET_STATUS}.")
    print("  USED FOR: evidence that process-safety engineering treats alarm priority as a")
    print("            first-class measurable property, and has for twenty-five years.")
    print("  NOT USED FOR: any claim about Hugging Face's alarm distribution. Their alert")
    print("            configuration is unpublished and cannot be computed from these sources.")
    print()
    print("  The contrast is the finding: security alert-screening research uses a binary")
    print("  {malicious, benign} label space (BASERATE-F). Severity is not in it, so")
    print("  'correctly labelled malicious, wrongly prioritised' -- the failure that decided")
    print("  this incident -- is formally unrepresentable in the field that studies alerts.")

    (RESULTS / "escalation.json").write_text(json.dumps({
        "lags": lags,
        "events": [e.__dict__ for e in events],
        "daily_actions": days,
        "busiest_day": busiest["label"],
        "busiest_day_share": round(busiest["actions"] / total, 4),
        "alarm_priority_target": ALARM_PRIORITY_TARGET,
        "alarm_priority_target_status": ALARM_TARGET_STATUS,
        "hf_detection_quote": quotes["detection_criticality"]["text"],
        "hf_defenders_dilemma_quote": quotes["defenders_dilemma"]["text"],
    }, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
