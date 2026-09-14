"""Recompute every number the paper asserts, from `data/`, and render the paper from the results.

    python verify.py            # recompute, check, render paper/main.tex
    python verify.py --list     # print the claim table and stop

How this differs from checking the paper afterwards
---------------------------------------------------
Version 1 of this project shipped a cost table that contradicted its own artifact -- a false
caption, an unsourced standard deviation, four wrong cells. It survived because verification ran
*over the prose*: a consistency checker recomputed what the paper said and confirmed the paper
said it consistently.

So the numbers are not written into the manuscript at all. `paper/main.tex.tmpl` contains
placeholders like `{{DENSE_SHARE}}`, and this script substitutes the computed value. A number in
the paper cannot disagree with the artifact, because the paper has no numbers of its own. An
unknown placeholder is a hard failure, and a claim nothing references is reported too -- an
orphan usually means a finding was cut from the text and its number left behind.

What this does NOT establish
----------------------------
That the claims are *correct* -- only that the manuscript matches the artifacts. Consistency
checking cannot detect an inappropriate measure or a mis-specified source; that is the structural
limit that let v1's headline through, and it is stated here rather than assumed away.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "ingest"))
sys.path.insert(0, str(ROOT / "analysis"))

import concurrency  # noqa: E402
import escalation  # noqa: E402
import hfblog  # noqa: E402
import metr  # noqa: E402
import openai_tr  # noqa: E402
import replay  # noqa: E402
import sources  # noqa: E402
import timeline  # noqa: E402

PAPER = ROOT / "paper"
RESULTS = ROOT / "results"

#: Stated in the sprint's submission requirements as a hard cap, alongside the mandatory
#: Limitations appendix. Enforced at render time.
ABSTRACT_WORD_LIMIT = 150


@dataclass
class Claim:
    key: str
    describe: str
    fn: Callable[[], str]
    #: Raw claims are inserted verbatim into LaTeX. Only generated table bodies set this --
    #: they legitimately contain `&` and `\\`, which the escaper would otherwise destroy.
    raw: bool = False


#: LaTeX specials that must be escaped in substituted values. `\` is deliberately absent: no
#: computed value contains one, and escaping it would corrupt the raw table claims if the flag
#: above were ever set wrongly.
TEX_ESCAPES = {"&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
               "_": r"\_", "{": r"\{", "}": r"\}"}


def tex_escape(s: str) -> str:
    return "".join(TEX_ESCAPES.get(ch, ch) for ch in s)


def _phases():
    ps = replay.load()["PHASES"]
    for p in ps:
        p["span"] = p["last"] - p["first"]
        p["dense"] = p["total"] >= concurrency.DENSE_MIN_ACTIONS
    return ps


def _lag(from_frag: str, to_frag: str) -> float:
    rows = timeline.lags(timeline.verify(list(timeline.EVENTS)))
    return next(r for r in rows
                if from_frag in r["from"] and to_frag in r["to"])["days"]


def _dense_overlap_min() -> float:
    ps = [p for p in _phases() if p["dense"]]
    return min(concurrency.overlap(a, b) for a, b in combinations(ps, 2))


def _concurrent_fraction() -> float:
    dense = [p for p in _phases() if p["dense"]]
    prof = concurrency.active_profile(dense)
    return sum(1 for v in prof if v == len(dense)) / len(prof)


def _mean_overlap(dense_only: bool) -> float:
    ps = [p for p in _phases() if p["dense"]] if dense_only else _phases()
    pairs = [concurrency.overlap(a, b) for a, b in combinations(ps, 2)]
    return sum(pairs) / len(pairs)


# --------------------------------------------------------------------------------------
# Feasible bounds on the concurrency statistics.
#
# These exist because of a defect found in review. Two intervals inside a normalised
# campaign with spans s_a and s_b must overlap on at least max(0, s_a + s_b - 1); once the
# spans in Table 1 are known, the overlap statistic and the coextensivity fraction are
# confined to a band a couple of percentage points wide and cannot report anything other
# than "close to 1". They therefore carry no information beyond the span column, and the
# paper reports these bounds instead of the point values it used to headline.
#
# The bounds are computed here rather than asserted in prose so that the retirement is
# itself reproducible: if the spans ever change, the band changes with them.
# --------------------------------------------------------------------------------------
def _overlap_floor_mean() -> float:
    """Smallest mean pairwise overlap consistent with the dense spans alone."""
    ps = [p for p in _phases() if p["dense"]]
    fl = [max(0.0, a["span"] + b["span"] - 1.0) / min(a["span"], b["span"])
          for a, b in combinations(ps, 2)]
    return sum(fl) / len(fl)


def _phi_floor() -> float:
    """Smallest coextensivity fraction consistent with the dense spans alone."""
    ps = [p for p in _phases() if p["dense"]]
    return 1.0 - sum(1.0 - p["span"] for p in ps)


def _phi_ceil() -> float:
    """Largest possible coextensivity fraction: no phase can be active beyond its own span."""
    return min(p["span"] for p in _phases() if p["dense"])


def _dense_onset_spread() -> float:
    """Campaign fraction between the first and last dense-phase onset."""
    ps = [p for p in _phases() if p["dense"]]
    return max(p["first"] for p in ps) - min(p["first"] for p in ps)


def _last_onset() -> float:
    """Onset of the last phase to begin at all.

    Onsets are the part of the record that *is* ordered, and ordering is what a staged model
    actually predicts. Against a dense-onset spread of under two percentage points, the last
    phase not starting until well into the campaign is what distinguishes "these three ran
    together throughout" from "nothing here is sequenced".
    """
    return max(p["first"] for p in _phases())


def _oai_esc() -> dict:
    return openai_tr.escalation()


#: Where the released repository lives. Kept in a file rather than in the manuscript so that
#: an unset value is a visible, greppable failure in the rendered PDF instead of an omission
#: nobody notices -- review of v1 found the artifact unreachable precisely because the paper
#: described a release it never located.
#: Plain text, not LaTeX: this value is escaped like every other computed value, so it must
#: not smuggle markup through. Keeping it out of the raw set is deliberate -- a URL is exactly
#: the kind of string (underscores, percent-encoding) that needs escaping.
REPO_URL_FILE = PAPER / "REPO_URL.txt"
REPO_URL_UNSET = "[REPOSITORY URL NOT SET - see paper/REPO_URL.txt]"


def _repo_url() -> str:
    if REPO_URL_FILE.exists():
        url = REPO_URL_FILE.read_text(encoding="utf-8").strip()
        if url:
            return url
    print(f"  !! REPO_URL: unset -- create {REPO_URL_FILE} before submission")
    return REPO_URL_UNSET


CLAIMS: list[Claim] = [
    Claim("TOTAL_ACTIONS", "Actions in the published replay",
          lambda: f"{sum(d['actions'] for d in replay.load()['DAYS']):,}"),
    Claim("CAMPAIGN_DAYS", "Intrusion duration, days",
          lambda: f"{_lag('First recorded', 'Last recorded'):.2f}"),
    Claim("PHASE_COUNT", "Phases HF labels", lambda: str(len(_phases()))),
    Claim("PHASE_SUM", "Sum of per-phase action totals",
          lambda: f"{sum(p['total'] for p in _phases()):,}"),
    Claim("PHASE_GAP", "Actions not covered by phase totals",
          lambda: f"{sum(d['actions'] for d in replay.load()['DAYS']) - sum(p['total'] for p in _phases()):,}"),
    Claim("PHASE_GAP_PCT", "That gap as a percentage",
          lambda: f"{100 * (sum(d['actions'] for d in replay.load()['DAYS']) - sum(p['total'] for p in _phases())) / sum(d['actions'] for d in replay.load()['DAYS']):.1f}"),

    Claim("DENSE_COUNT", "Phases above the density floor",
          lambda: str(sum(1 for p in _phases() if p["dense"]))),
    Claim("DENSE_MIN_ACTIONS", "Density floor",
          lambda: f"{concurrency.DENSE_MIN_ACTIONS:,}"),
    Claim("DENSE_ACTIONS", "Actions in dense phases",
          lambda: f"{sum(p['total'] for p in _phases() if p['dense']):,}"),
    Claim("DENSE_SHARE", "Dense phases' share of labelled actions, %",
          lambda: f"{100 * sum(p['total'] for p in _phases() if p['dense']) / sum(p['total'] for p in _phases()):.1f}"),
    Claim("DENSE_OVERLAP", "Minimum pairwise overlap among dense phases",
          lambda: f"{_dense_overlap_min():.3f}"),
    Claim("MEAN_OVERLAP_DENSE", "Mean pairwise overlap, dense phases",
          lambda: f"{_mean_overlap(True):.3f}"),
    Claim("MEAN_OVERLAP_ALL", "Mean pairwise overlap, all phases",
          lambda: f"{_mean_overlap(False):.3f}"),
    Claim("CONCURRENT_PCT", "Campaign fraction with all dense phases active, %",
          lambda: f"{100 * _concurrent_fraction():.1f}"),

    # The bands the two statistics above were confined to before either was computed.
    Claim("OVERLAP_FLOOR", "Arithmetic floor on mean pairwise overlap, given the spans",
          lambda: f"{_overlap_floor_mean():.3f}"),
    Claim("OVERLAP_BAND", "Width of the feasible interval for mean pairwise overlap",
          lambda: f"{1.0 - _overlap_floor_mean():.3f}"),
    Claim("PHI_FLOOR", "Arithmetic floor on the coextensivity fraction, %",
          lambda: f"{100 * _phi_floor():.1f}"),
    Claim("PHI_CEIL", "Arithmetic ceiling on the coextensivity fraction, %",
          lambda: f"{100 * _phi_ceil():.1f}"),
    Claim("PHI_BAND", "Width of the feasible interval for the coextensivity fraction, pp",
          lambda: f"{100 * (_phi_ceil() - _phi_floor()):.1f}"),

    # Onsets: the ordering claim a staged model actually makes, which extent cannot address.
    Claim("DENSE_ONSET_SPREAD", "Campaign fraction between first and last dense onset, %",
          lambda: f"{100 * _dense_onset_spread():.1f}"),
    Claim("ONSET_LAST", "Onset of the last phase to begin, % of campaign",
          lambda: f"{100 * _last_onset():.1f}"),
    Claim("RECON_SPAN", "Recon envelope span, %",
          lambda: f"{100 * next(p['span'] for p in _phases() if p['key'] == 'recon'):.1f}"),
    Claim("EVASION_ACTIONS", "Actions labelled evasion",
          lambda: str(next(p["total"] for p in _phases() if p["key"] == "evasion"))),
    Claim("EVASION_SPAN", "Evasion envelope span, %",
          lambda: f"{100 * next(p['span'] for p in _phases() if p['key'] == 'evasion'):.0f}"),

    Claim("BUSIEST_DAY", "Busiest day",
          lambda: max(replay.load()["DAYS"], key=lambda d: d["actions"])["label"]),
    Claim("BUSIEST_SHARE", "Busiest day's share of actions, %",
          lambda: f"{100 * max(d['actions'] for d in replay.load()['DAYS']) / sum(d['actions'] for d in replay.load()['DAYS']):.1f}"),

    Claim("LAG_DISCLOSE_TO_CONNECT", "HF disclosure to OpenAI self-identification, days",
          lambda: f"{_lag('Hugging Face discloses', 'OpenAI connects'):.2f}"),
    Claim("LAG_START_TO_ACK", "Attack start to OpenAI acknowledgement, days",
          lambda: f"{_lag('First recorded', 'OpenAI acknowledges'):.2f}"),
    Claim("LAG_END_TO_METR", "Last action to independent investigation, days",
          lambda: f"{_lag('Last recorded', 'METR/Redwood'):.2f}"),
    Claim("LAG_END_TO_DISCLOSE", "Last action to HF disclosure, days",
          lambda: f"{_lag('Last recorded', 'Hugging Face discloses'):.2f}"),

    # Perpetrator-side escalation, from OpenAI's own appendix. Replaces the press-sourced
    # attribution interval the paper previously leaned on for this claim.
    Claim("OAI_ALERT_UTC", "OpenAI monitoring alert, 19 July, UTC",
          lambda: _oai_esc()["alert"]["time"]),
    Claim("OAI_RESPONSE_UTC", "OpenAI responders begin stopping runs, 19 July, UTC",
          lambda: _oai_esc()["response"]["time"]),
    Claim("OAI_GAP_H", "Whole hours from alert to response",
          lambda: str(_oai_esc()["gap_minutes"] // 60)),
    Claim("OAI_GAP_M", "Remaining minutes from alert to response",
          lambda: f"{_oai_esc()['gap_minutes'] % 60:02d}"),
    Claim("OAI_GAP_HOURS", "Alert-to-response interval, decimal hours",
          lambda: f"{_oai_esc()['gap_hours']:.2f}"),
    Claim("OAI_GAP_EVENTS", "Timestamped appendix entries inside the interval",
          lambda: str(len(_oai_esc()["between"]))),
    Claim("OAI_ALERT_PAGE", "Appendix page carrying the alert entry",
          lambda: str(_oai_esc()["alert"]["page"])),
    Claim("OAI_RESPONSE_PAGE", "Appendix page carrying the response entry",
          lambda: str(_oai_esc()["response"]["page"])),
    Claim("OAI_TR_PAGES", "Pages in OpenAI's technical report",
          lambda: str(openai_tr.EXPECTED_PAGES)),
    Claim("OAI_TR_ENTRIES", "Timestamped entries in OpenAI's appendix timeline",
          lambda: str(len(openai_tr.timeline()))),

    Claim("REPO_URL", "Released repository", _repo_url),
    Claim("PYTHON_VERSION", "Python the results were produced under",
          lambda: ".".join(str(v) for v in sys.version_info[:3])),
    Claim("PYPDF_VERSION", "Pinned pypdf version",
          lambda: (ROOT / "requirements.txt").read_text(encoding="utf-8").strip().split("==")[1]),

    Claim("N_SOURCES", "Primary sources cached", lambda: str(len(sources.SOURCES))),
    Claim("N_EVENTS_VERIFIED", "Timeline events anchored in a primary source",
          lambda: str(sum(1 for e in timeline.verify(list(timeline.EVENTS))
                          if e.status == "VERIFIED"))),
    Claim("N_EVENTS_TOTAL", "Timeline events", lambda: str(len(timeline.EVENTS))),
    Claim("METR_PAGES", "Pages in the METR/Redwood report", lambda: str(metr.EXPECTED_PAGES)),
    Claim("METR_QUOTES", "Page-numbered agent-reasoning quotes extracted",
          lambda: str(len(metr.agent_quotes(metr.pages())))),
    Claim("HF_COMMAND_BLOCKS", "Captured command blocks in the technical timeline",
          lambda: str(len(hfblog.code_blocks(sources.text("hf_blog_timeline"))))),

    Claim("ALARM_LOW", "EEMUA/ISA low-priority target, %",
          lambda: f"{100 * escalation.ALARM_PRIORITY_TARGET['low']:.0f}"),
    Claim("ALARM_MED", "EEMUA/ISA medium-priority target, %",
          lambda: f"{100 * escalation.ALARM_PRIORITY_TARGET['medium']:.0f}"),
    Claim("ALARM_HIGH", "EEMUA/ISA high-priority target, %",
          lambda: f"{100 * escalation.ALARM_PRIORITY_TARGET['high']:.0f}"),

    Claim("HF_DETECTION_QUOTE", "HF's escalation admission, verbatim",
          lambda: hfblog.quotes(sources.text("hf_blog_timeline"))[
              "detection_criticality"]["text"].split(". ")[0] + "."),

    Claim("SPARSE_COUNT", "Phases below the density floor",
          lambda: str(sum(1 for p in _phases() if not p["dense"]))),
    Claim("METR_PASSAGES", "Quoted passages extracted from the METR report",
          lambda: str(len(metr.passages(metr.pages())))),
    Claim("N_AGENT_IDS", "Distinct agent pseudonyms in the METR report",
          lambda: str(len(metr.agent_ids(metr.pages())))),
    Claim("N_TESTS", "Automated tests in the released harness",
          lambda: str(sum(len(re.findall(r"^def test_", p.read_text(encoding='utf-8'),
                                         re.M))
                          for p in sorted((ROOT / "tests").glob("test_*.py"))))),
    Claim("N_DATA_FILES", "Derived data files produced by ingestion",
          lambda: str(len(list((ROOT / "data").glob("*"))))),

    Claim("PHASE_TABLE_TEX", "Per-phase table body (generated)",
          lambda: _phase_table_tex(), raw=True),
    Claim("PHASE_FIGURE_TEX", "Per-phase interval strip (generated)",
          lambda: _phase_figure_tex(), raw=True),
    Claim("LAG_TABLE_TEX", "Escalation-lag table body (generated)",
          lambda: _lag_table_tex(), raw=True),
]


def _phase_table_tex() -> str:
    """The phase table, emitted from the data rather than transcribed into the manuscript.

    v1 of this project shipped a table with four wrong cells because it was typed by hand next
    to an artifact that said something else. Generating the rows removes that failure entirely.

    Ordered by onset rather than by volume, so that the one thing a staged model does
    predict -- an ordering of phase *starts* -- is legible in the table instead of absent
    from the paper. The dense phases sort first regardless, because they all begin in the
    campaign's opening minutes.
    """
    rows = []
    for p in sorted(_phases(), key=lambda p: p["first"]):
        density = p["total"] / (p["span"] * 100) if p["span"] > 0 else 0.0
        cls = r"\textbf{dense}" if p["dense"] else "sparse"
        rows.append(f"{p['key'].replace('-', '--')} & {p['total']:,} & {p['first']:.3f} & "
                    f"{p['span']:.3f} & {density:.1f} & {cls} \\\\")
    return "\n".join(rows)


def _phase_figure_tex() -> str:
    """A per-phase interval strip over normalised campaign time, drawn from the data.

    The paper had no figure, and this is the one result that is fundamentally about
    intervals on a line: three bars spanning nearly the whole axis and six starting
    progressively later is the entire concurrency-versus-onset finding in one glance. It is
    generated for the same reason the tables are -- so it cannot drift from the artifact.
    """
    ps = sorted(_phases(), key=lambda p: p["first"])
    rows = [
        r"\begin{tikzpicture}[x=10cm,y=0.42cm]",
        r"  \draw[gray!45] (0,0.55) -- (1,0.55);",
        r"  \foreach \x/\l in {0/0, 0.25/25, 0.5/50, 0.75/75, 1/100} {",
        r"    \draw[gray!45] (\x,0.55) -- (\x,0.75)"
        r" node[above,font=\tiny,gray!70,inner sep=1pt] {\l\%};}",
    ]
    for i, p in enumerate(ps):
        y = -i
        fill = "black!62" if p["dense"] else "black!22"
        label = p["key"].replace("-", "--")
        weight = r"\bfseries" if p["dense"] else ""
        rows.append(
            f"  \\fill[{fill}] ({p['first']:.4f},{y - 0.30:.2f}) rectangle "
            f"({p['last']:.4f},{y + 0.30:.2f});"
        )
        rows.append(
            f"  \\node[left,font=\\tiny{weight},inner sep=2pt] at (0,{y:.2f}) "
            f"{{{label}}};"
        )
        rows.append(
            f"  \\node[right,font=\\tiny,gray!70,inner sep=2pt] at (1,{y:.2f}) "
            f"{{{p['total']:,}}};"
        )
    rows.append(r"\end{tikzpicture}")
    return "\n".join(rows)


def _lag_table_tex() -> str:
    rows = []
    for r in timeline.lags(timeline.verify(list(timeline.EVENTS))):
        src = "secondary" if "UNVERIFIED" in r["weakest_status"] else "primary"
        frm = r["from"].replace("&", r"\&")
        to = r["to"].replace("&", r"\&")
        rows.append(f"{frm} $\\rightarrow$ {to} & {r['days']:.2f} & {src} \\\\")
    return "\n".join(rows)


def compute() -> dict[str, str]:
    out: dict[str, str] = {}
    for c in CLAIMS:
        try:
            out[c.key] = c.fn()
        except Exception as e:                                   # noqa: BLE001
            # A claim that cannot be computed must never render as blank or stale.
            print(f"  !! {c.key}: FAILED to compute -- {e}")
            out[c.key] = f"<<UNCOMPUTABLE:{c.key}>>"
    return out


def abstract_words(text: str) -> int | None:
    """Word count of the abstract, for either template language.

    Returns None if no abstract is present -- which is a failure, not a zero, because a missing
    required section and an empty one need different messages.
    """
    m = re.search(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", text, re.S)
    if not m:
        m = re.search(r"## Abstract\n(.*?)\n---", text, re.S)
    if not m:
        return None
    body = re.sub(r"\\[a-zA-Z]+\{?|\}|\\noindent", " ", m.group(1))
    return len(re.sub(r"\s+", " ", body).split())


def render_one(tmpl_path: Path, values: dict[str, str], raw_keys: set[str]) -> int:
    out_path = tmpl_path.with_suffix("")            # main.tex.tmpl -> main.tex
    is_tex = out_path.suffix == ".tex"
    tmpl = tmpl_path.read_text(encoding="utf-8")

    used = set(re.findall(r"\{\{([A-Z_]+)\}\}", tmpl))
    unknown = sorted(used - set(values))
    if unknown:
        print(f"\nFAIL: {tmpl_path.name} references unknown placeholder(s): "
              f"{', '.join(unknown)}")
        return 1

    def sub(m: re.Match) -> str:
        key = m.group(1)
        v = values[key]
        return v if (not is_tex or key in raw_keys) else tex_escape(v)

    out = re.sub(r"\{\{([A-Z_]+)\}\}", sub, tmpl)
    if "<<UNCOMPUTABLE" in out:
        print(f"\nFAIL: an uncomputable claim reached {out_path.name}")
        return 1

    # The 150-word abstract is a listed submission requirement, not a style preference. A
    # companion project in this repo carried a 334-word abstract to review before anyone
    # noticed, so it is a gate here rather than a note.
    n_words = abstract_words(out)
    if n_words is None:
        print(f"\nFAIL: {out_path.name} has no abstract -- a required submission item")
        return 1

    out_path.write_text(out, encoding="utf-8")
    status = "ok" if n_words <= ABSTRACT_WORD_LIMIT else "OVER LIMIT"
    print(f"  {out_path.name:12} {len(out):>7,} chars  {len(used):>2} claims  "
          f"abstract {n_words}/{ABSTRACT_WORD_LIMIT} [{status}]")
    return 0 if n_words <= ABSTRACT_WORD_LIMIT else 1


def render(values: dict[str, str]) -> int:
    templates = sorted(PAPER.glob("*.tmpl"))
    if not templates:
        print(f"\nno templates in {PAPER} -- nothing to render")
        return 0

    raw_keys = {c.key for c in CLAIMS if c.raw}
    print(f"\nRendering {len(templates)} template(s)\n")

    rc = 0
    all_used: set[str] = set()
    for t in templates:
        all_used |= set(re.findall(r"\{\{([A-Z_]+)\}\}", t.read_text(encoding="utf-8")))
        rc |= render_one(t, values, raw_keys)

    orphan = sorted(set(values) - all_used)
    if rc:
        return rc
    if orphan:
        print(f"\n  {len(orphan)} computed claim(s) the manuscript does not use:")
        print("  " + ", ".join(orphan))
        print("  Usually a finding was cut and its number left behind. Not fatal; check.")
    return 0


def main(argv: list[str]) -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    PAPER.mkdir(parents=True, exist_ok=True)

    print("Recomputing every claim from data/\n")
    values = compute()

    width = max(len(c.key) for c in CLAIMS)
    for c in CLAIMS:
        v = values[c.key]
        shown = v if len(v) <= 46 else v[:43] + "..."
        print(f"  {c.key:<{width}}  {shown:<48}  {c.describe}")

    (RESULTS / "claims.json").write_text(json.dumps(values, indent=2), encoding="utf-8")
    print(f"\n{len(values)} claims -> {RESULTS / 'claims.json'}")

    bad = [k for k, v in values.items() if v.startswith("<<UNCOMPUTABLE")]
    if bad:
        print(f"\nFAIL: {len(bad)} claim(s) could not be computed: {', '.join(bad)}")
        return 1

    if "--list" in argv:
        return 0
    return render(values)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
