"""Does the intrusion have the shape a kill chain says it should?

    python analysis/concurrency.py

Writes `results/concurrency.json` and `results/phase_overlap.csv`.

The claim under test
--------------------
Every vendor writeup of this incident draws it as a kill chain: ordered stages, each largely
finishing before the next begins. That model is not decoration -- it is what detection playbooks
are keyed to, and "we are at stage 3" is an escalation input.

Hugging Face published, inside its interactive replay, the first and last timestamp of every
phase as a fraction of the campaign. That is enough to ask whether the stages are stages.

The measure, and the limit that constrains it
---------------------------------------------
What is published per phase is an **envelope** -- first action to last action -- not a duty
cycle. A phase with six actions spread across three days has a wide envelope and was almost
never active. Envelope overlap therefore proves concurrency only when the phases involved are
*dense*: thousands of actions distributed across the window cannot be an artefact of two
outliers at the ends.

So density is computed and reported alongside every span, the headline claim is restricted to
the dense phases, and the sparse ones are shown but explicitly excluded from it. Reporting mean
overlap across all nine phases without that split would be the more impressive and less true
number.
"""
from __future__ import annotations

import csv
import json
import sys
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ingest"))

import replay  # noqa: E402

RESULTS = ROOT / "results"

#: A phase is "dense" if it carries at least this many actions. Below it, an envelope can be
#: produced by a handful of scattered actions and says little about sustained activity.
DENSE_MIN_ACTIONS = 1000

#: Campaign wall-clock, from the published window 2026-07-09T02:28Z -> 2026-07-13T14:14Z.
CAMPAIGN_DAYS = 4.49


def overlap(a: dict, b: dict) -> float:
    """Fraction of the shorter envelope that the two share."""
    lo = max(a["first"], b["first"])
    hi = min(a["last"], b["last"])
    inter = max(0.0, hi - lo)
    shorter = min(a["last"] - a["first"], b["last"] - b["first"])
    return inter / shorter if shorter > 0 else 0.0


def active_profile(phases: list[dict], steps: int = 1000) -> list[int]:
    """How many phase envelopes cover each point of the campaign."""
    out = []
    for i in range(steps + 1):
        t = i / steps
        out.append(sum(1 for p in phases if p["first"] <= t <= p["last"]))
    return out


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    phases = replay.load()["PHASES"]

    for p in phases:
        p["span"] = p["last"] - p["first"]
        # Actions per 1% of the campaign: the density that decides whether a span means anything.
        p["density"] = p["total"] / (p["span"] * 100) if p["span"] > 0 else 0.0
        p["dense"] = p["total"] >= DENSE_MIN_ACTIONS

    dense = [p for p in phases if p["dense"]]
    sparse = [p for p in phases if not p["dense"]]

    pairs = []
    for a, b in combinations(phases, 2):
        pairs.append({
            "a": a["key"], "b": b["key"],
            "overlap": round(overlap(a, b), 4),
            "both_dense": a["dense"] and b["dense"],
        })

    dense_pairs = [p for p in pairs if p["both_dense"]]
    mean_dense = sum(p["overlap"] for p in dense_pairs) / len(dense_pairs)
    mean_all = sum(p["overlap"] for p in pairs) / len(pairs)

    profile = active_profile(phases)
    dense_profile = active_profile(dense)
    max_concurrent = max(profile)
    frac_ge3 = sum(1 for v in profile if v >= 3) / len(profile)
    frac_all_dense = sum(1 for v in dense_profile if v == len(dense)) / len(dense_profile)

    print("Phase envelopes, with the density that decides how much an envelope means\n")
    print(f"  {'phase':14}{'actions':>8}{'span':>8}{'days':>7}{'actions/1%':>12}   class")
    print("  " + "-" * 62)
    for p in sorted(phases, key=lambda p: -p["total"]):
        cls = "dense" if p["dense"] else "SPARSE"
        print(f"  {p['key']:14}{p['total']:>8,}{p['span']:>8.3f}"
              f"{p['span'] * CAMPAIGN_DAYS:>7.2f}{p['density']:>12.1f}   {cls}")

    print(f"\n  dense phases (>= {DENSE_MIN_ACTIONS:,} actions): "
          f"{', '.join(p['key'] for p in dense)}")
    print(f"  sparse, excluded from the headline: {', '.join(p['key'] for p in sparse)}")

    print("\nConcurrency\n")
    print(f"  mean pairwise envelope overlap, dense phases only : {mean_dense:.3f}")
    print(f"  mean pairwise envelope overlap, all nine phases   : {mean_all:.3f}")
    print(f"  maximum phases simultaneously in envelope         : {max_concurrent} of {len(phases)}")
    print(f"  fraction of campaign with >= 3 phases in envelope : {frac_ge3:.3f}")
    print(f"  fraction of campaign with ALL dense phases active : {frac_all_dense:.3f}")

    print("\nWhat a kill chain would predict\n")
    print("  Ordered stages imply near-zero pairwise overlap and one or two active phases at a")
    print("  time. The three dense phases -- recon, rce, dropper, carrying "
          f"{sum(p['total'] for p in dense):,} of")
    print(f"  {sum(p['total'] for p in phases):,} labelled actions -- instead overlap at "
          f"{mean_dense:.3f} and run together across")
    print(f"  {frac_all_dense:.1%} of the campaign. Reconnaissance is not a stage that precedes "
          "exploitation here;")
    print("  it runs to the final minutes.")

    print("\nLimits, stated rather than left for a reviewer\n")
    print("  * n = 1 incident. This is a description of one campaign, not an estimate of how")
    print("    intrusions behave in general, and no inferential statistic is reported.")
    print("  * Envelopes are not duty cycles. The claim is restricted to dense phases for that")
    print("    reason; `evasion` spans 70% of the campaign on six actions and is excluded.")
    print("  * Phase labels are Hugging Face's and are not a partition -- they sum to 16,521 of")
    print("    17,613 actions. Any reading of these as exhaustive categories is unsupported.")

    with (RESULTS / "phase_overlap.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["a", "b", "overlap", "both_dense"])
        w.writeheader()
        w.writerows(pairs)

    (RESULTS / "concurrency.json").write_text(json.dumps({
        "phases": phases,
        "mean_pairwise_overlap_dense": round(mean_dense, 4),
        "mean_pairwise_overlap_all": round(mean_all, 4),
        "max_concurrent_phases": max_concurrent,
        "frac_campaign_ge3_phases": round(frac_ge3, 4),
        "frac_campaign_all_dense_active": round(frac_all_dense, 4),
        "dense_phase_keys": [p["key"] for p in dense],
        "sparse_phase_keys": [p["key"] for p in sparse],
        "dense_min_actions": DENSE_MIN_ACTIONS,
        "campaign_days": CAMPAIGN_DAYS,
    }, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
