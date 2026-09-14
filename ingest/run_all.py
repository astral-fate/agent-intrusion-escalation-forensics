"""Run the whole Track 2 ingest, in dependency order.

    python ingest/run_all.py           # from cache
    python ingest/run_all.py --refresh # re-fetch every source first

Everything downstream (analysis, paper, verify) reads `data/`, never the network.
"""
from __future__ import annotations

import sys

import hfblog
import metr
import replay
import sources
import timeline

STEPS = [
    ("sources  — fetch and hash primary artifacts", None),
    ("replay   — HF interactive replay dataset", replay.main),
    ("metr     — 91-page investigation to a citable corpus", metr.main),
    ("hfblog   — technical timeline + disclosure quotes", hfblog.main),
    ("timeline — normalised events and escalation lags", timeline.main),
]


def main(argv: list[str]) -> int:
    refresh = "--refresh" in argv

    print("=" * 74)
    print(f"  {STEPS[0][0]}")
    print("=" * 74)
    got = sources.fetch_all(refresh)
    missing = [k for k, v in got.items() if not v]
    if missing:
        # A partial corpus produces numbers that look fine and are computed from less than the
        # paper claims. Stop instead.
        print(f"\nABORT: {len(missing)} source(s) unavailable: {', '.join(missing)}")
        return 1

    for label, fn in STEPS[1:]:
        print()
        print("=" * 74)
        print(f"  {label}")
        print("=" * 74)
        rc = fn()
        if rc != 0:
            print(f"\nABORT: step failed -- {label}")
            return rc

    print()
    print("=" * 74)
    print("  ingest complete")
    print("=" * 74)
    for p in sorted((sources.ROOT / "data").glob("*")):
        print(f"  {p.name:28} {p.stat().st_size:>9,} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
