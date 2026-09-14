"""Extract Hugging Face's published intrusion-replay dataset from its static Space.

    python ingest/replay.py

Writes `data/replay.json` plus per-array CSVs.

What this is, precisely
-----------------------
NOT the raw ~17,600-action log; that was reviewed on-premises and never released. This is the
published *derived* forensic summary that Hugging Face shipped inside the interactive replay:
per-phase totals with first/last timestamps, per-day action counts, a cumulative curve, 21
representative timestamped commands, and the attack graph.

The project scorecard recorded this as DEAD on two observations -- HTTP 403, and no companion
dataset repo. Both observations were real; the conclusion was wrong. The 403 was a User-Agent
block (see `sources.BROWSER_UA`), and there is no companion repo because the data is inline in
the 43.9 kB `index.html` as JavaScript literals.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from sources import ROOT, text

DATA = ROOT / "data"

ARRAYS = ("PHASES", "DAYS", "CUM", "EVENTS", "NODES", "ZONES", "EDGES")

#: Hugging Face's reported action total. Used to check the extraction, not to trust it.
REPORTED_TOTAL = 17613


def _array_source(html: str, name: str) -> str:
    """Bracket-matched source of `const <name> = [...]`.

    Depth counting rather than a lazy regex: several arrays nest object and array literals, and
    `\\[.*?\\]` stops at the first inner `]`.
    """
    m = re.search(r"const\s+%s\s*=\s*\[" % re.escape(name), html)
    if not m:
        raise LookupError(f"{name} not found -- the Space's structure changed")
    start = m.end() - 1
    depth = 0
    for j in range(start, len(html)):
        if html[j] == "[":
            depth += 1
        elif html[j] == "]":
            depth -= 1
            if depth == 0:
                return html[start:j + 1]
    raise LookupError(f"{name} is unterminated")


def js_to_json(src: str) -> list:
    """Convert a JS object-literal array to JSON by scanning, not by regex.

    This was a regex three times and wrong three times, each a variant of one mistake: a regex
    cannot tell whether it is inside a string.

    * `//[^\\n]*` ate `curl -s http://...` from the `//` on, taking the closing quote with it.
    * Anchoring comments to line starts exposed the next case: one captured command is a
      DOUBLE-quoted JS string containing single quotes (``cmd:"curl -sw '%{http_code}' ..."``),
      so rewriting `'...'` pairs corrupted it.
    * The bare-key rewrite would equally have mangled any `word:` inside a command string.

    A scanner tracks quote state and all three vanish. Worth the extra lines: these failures
    were loud, but the same confusion against a URL inside a `desc` field would have silently
    truncated a record and produced a plausible, wrong dataset.
    """
    out: list[str] = []
    i, n = 0, len(src)
    while i < n:
        ch = src[i]

        if ch in "\"'":
            quote = ch
            i += 1
            buf: list[str] = []
            while i < n and src[i] != quote:
                if src[i] == "\\" and i + 1 < n:
                    buf.append(src[i:i + 2])
                    i += 2
                    continue
                buf.append(src[i])
                i += 1
            i += 1
            out.append(json.dumps("".join(buf).replace('\\"', '"').replace("\\'", "'")))
            continue

        if ch == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                i += 1
            continue

        m = re.match(r"[A-Za-z_][A-Za-z0-9_]*", src[i:])
        if m:
            word = m.group(0)
            j = i + len(word)
            k = j
            while k < n and src[k] in " \t":
                k += 1
            if k < n and src[k] == ":":
                out.append(json.dumps(word))
                i = j
                continue
            out.append(word)
            i = j
            continue

        out.append(ch)
        i += 1

    return json.loads(re.sub(r",(\s*[}\]])", r"\1", "".join(out)))


def load(refresh: bool = False) -> dict[str, list]:
    html = text("hf_replay_space", refresh)
    return {name: js_to_json(_array_source(html, name)) for name in ARRAYS}


def _write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    DATA.mkdir(parents=True, exist_ok=True)
    d = load()

    (DATA / "replay.json").write_text(json.dumps(d, indent=2), encoding="utf-8")
    _write_csv(DATA / "replay_phases.csv", d["PHASES"], ["key", "total", "first", "last", "desc"])
    _write_csv(DATA / "replay_days.csv", d["DAYS"], ["label", "actions", "start", "end", "char"])
    _write_csv(DATA / "replay_events.csv", d["EVENTS"], ["frac", "t", "phase", "cmd", "out"])
    with (DATA / "replay_cumulative.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["frac", "cumulative_actions"])
        w.writerows(d["CUM"])

    day_sum = sum(x["actions"] for x in d["DAYS"])
    phase_sum = sum(x["total"] for x in d["PHASES"])
    cum_final = d["CUM"][-1][1]

    assert day_sum == cum_final == REPORTED_TOTAL, (
        f"reconciliation failed: days={day_sum} cum={cum_final} expected={REPORTED_TOTAL}")

    print(f"phases {len(d['PHASES'])} | days {len(d['DAYS'])} | events {len(d['EVENTS'])} | "
          f"nodes {len(d['NODES'])} | edges {len(d['EDGES'])}")
    print(f"days and cumulative curve both reconcile to {REPORTED_TOTAL:,}")

    gap = day_sum - phase_sum
    print(f"\nphase totals sum to {phase_sum:,}, which is {gap:,} BELOW the action total "
          f"({100 * gap / day_sum:.1f}%).")
    print("  This contradicts the project's own incident timeline, which states 'Totals exceed")
    print("  17,600 because HF's clustering allows one cluster to carry multiple tags.' Multi-")
    print("  tagging would push the sum ABOVE the total; the published numbers sit below it.")
    print("  Either tags attach to clusters rather than actions, or ~6% of actions are")
    print("  untagged. The source does not say, so phases must not be treated as a partition.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
