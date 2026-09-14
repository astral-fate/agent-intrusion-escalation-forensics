---
license: cc-by-4.0
pretty_name: "July 2026 Autonomous Agent Intrusion — Forensic Corpus"
language:
  - en
tags:
  - ai-safety
  - ai-incident-response
  - autonomous-agents
  - digital-forensics
  - alert-triage
  - alarm-management
size_categories:
  - n<1K
configs:
  - config_name: phases
    data_files: data/replay_phases.csv
  - config_name: days
    data_files: data/replay_days.csv
  - config_name: cumulative
    data_files: data/replay_cumulative.csv
  - config_name: attack_graph
    data_files: data/replay_events.csv
  - config_name: timeline
    data_files: data/timeline.csv
  - config_name: timeline_lags
    data_files: data/timeline_lags.csv
  - config_name: openai_appendix_timeline
    data_files: data/openai_tr_timeline.csv
  - config_name: metr_passages
    data_files: data/metr_passages.csv
  - config_name: metr_agent_quotes
    data_files: data/metr_agent_quotes.csv
  - config_name: hfblog_sections
    data_files: data/hfblog_sections.csv
  - config_name: hfblog_commands
    data_files: data/hfblog_commands.csv
---

# Both Sides Detected It, Neither Escalated: Concurrency and Escalation Failure in the July 2026 Autonomous Agent Intrusion

This repository contains the corpus, ingestion pipeline and report for a forensic reconstruction
of the **July 2026 autonomous agent intrusion**, submitted to the **[Apart Research & CeSIA AI
Incident Response Sprint](https://www.apartresearch.com/)**, Track 2 (Forensics and Forecasting).

#### By: [Fatimah Mohamed Emad Elden](https://scholar.google.com/citations?user=CfX6eA8AAAAJ&hl=ar)

#### *Trouve Labs*

[![Paper](https://img.shields.io/badge/Paper-PDF-b31b1b.svg)](docs/both-sides-detected-it-neither-escalated.pdf)
[![Slides](https://img.shields.io/badge/Slides-Live%20deck-2ea44f)](https://astral-fate.github.io/agent-intrusion-escalation-forensics/)
[![Slides PDF](https://img.shields.io/badge/Slides-PDF-8b5cf6)](docs/slides.pdf)
[![Code](https://img.shields.io/badge/GitHub-Code-blue)](https://github.com/astral-fate/agent-intrusion-escalation-forensics)
[![HuggingFace](https://img.shields.io/badge/HuggingFace-Dataset-F9D371)](https://huggingface.co/datasets/FatimahEmadEldin/agent-intrusion-escalation-forensics)
[![License](https://img.shields.io/badge/License-MIT-lightgrey)](LICENSE)

---

**Detection was not the binding constraint at either organisation — escalation was.** Built from
seven public primary sources with a pipeline in which every number in the report is recomputed
from the data at build time.

Report: [`docs/both-sides-detected-it-neither-escalated.pdf`](docs/both-sides-detected-it-neither-escalated.pdf) (built from `paper/`) — 8-page main text plus Appendices A–D.

---

## The problem

In July 2026, autonomous agents under evaluation by OpenAI escaped their sandbox and ran a 4.49-day
campaign against Hugging Face's production infrastructure, producing 17,613 recovered attacker
actions. Both the victim and the perpetrator published accounts, and METR and Redwood Research
published an independent investigation. It is the first intrusion of its kind with a public,
log-level forensic record.

Those accounts converge on a diagnosis: the response failure was a **detection** failure — the
campaign was not seen soon enough. That diagnosis decides what work follows. If detection was the
constraint, the remedy is more sensors and better classifiers. If escalation was the constraint,
the sensors were already sufficient and the remedy lies in how a correct verdict is ranked and
routed.

This project tests the diagnosis against the quantitative record. It does not hold.

## What the record shows

### 1. Both organisations detected the campaign and neither escalated it

At the victim, the signals fired *and were correlated into a coherent attack signal*. Hugging Face
states the consequence directly:

> However, it failed to correctly raise the alert's criticality and trigger the on-call team,
> costing precious time in the response.

At the perpetrator, the same step failed, and OpenAI's own 38-page technical report timestamps it.
A cybersecurity monitoring alert fired at **12:03 UTC on 19 July** on unusual identity-related API
activity — recorded in the appendix as "later correlated to ExploitGym evaluations", so a true
positive. Responders began stopping the runs at **17:37 UTC**, **5 h 34 min** later, with **8
further compromise events timestamped inside that interval** (host root at 15:59, an Artifactory
administrator account created at 16:48).

Both endpoints are read from OpenAI's appendix by `ingest/openai_tr.py`, located by anchor
substring rather than row index, on pages 37–38 of 38. Neither half of this finding depends on
press reporting.

**What it is not.** This is a detection-to-response interval inside one organisation, not an
attribution interval. OpenAI states that at the time of the alert "there was no indication of a
relationship between that July 19 activity and the Hugging Face incident." The 4.00-day
disclosure-to-attribution figure is press-sourced, is labelled secondary in the data, and carries
no part of the argument.

### 2. The failure mode is invisible to the field that studies alerts

A correctly classified alert that is ranked below the threshold at which anyone is woken scores as
a *success* on every quantity the field's formalisation defines. The 2026 survey of alert screening
defines the task over a binary label space `{malicious, benign}` with three failure quantities —
false-positive rate, uninvestigated rate, decision-quality degradation — each satisfied by `ŷ = y`.

The narrow, checkable claim: security publishes **no target priority distribution** and **no
population study of deviation from one**. Process safety publishes both — EEMUA 191 and ANSI/ISA-18.2
specify roughly 80 % low / 15 % medium / 5 % high, and the ASM Consortium measured 37 real operator
consoles against it. Priority *is* studied in security; a standard against which a priority can be
called *wrong* is not published.

The paper proposes the metric that would close the gap (an escalation-miss rate conditioned on a
locally-defined escalation threshold, reported alongside its dual) and an annotation scheme that
transfers between deployments. **No value of it is claimed for this incident** — Hugging Face's
escalation policy is unpublished.

### 3. A negative result: the concurrency statistics this project first headlined are uninformative

Three phases carry 16,074 of 16,521 labelled actions (97.3 %) and each spans nearly the whole
campaign; reconnaissance runs to the campaign's final minutes rather than preceding exploitation.

| phase | actions | onset | span | actions per 1 % | |
|---|---:|---:|---:|---:|---|
| recon | 6,191 | 0.014 | 0.986 | 62.8 | dense |
| rce | 2,911 | 0.014 | 0.981 | 29.7 | dense |
| dropper | 6,972 | 0.032 | 0.968 | 72.0 | dense |
| exfil | 56 | 0.109 | 0.878 | 0.6 | sparse |
| c2 | 114 | 0.122 | 0.851 | 1.3 | sparse |
| evasion | 6 | 0.158 | 0.697 | 0.1 | sparse |
| k8s | 87 | 0.517 | 0.254 | 3.4 | sparse |
| supply-chain | 69 | 0.570 | 0.424 | 1.6 | sparse |
| tailscale | 115 | 0.621 | 0.373 | 3.1 | sparse |

Mean pairwise overlap of 0.998 and a coextensivity fraction of 96.3 % were originally presented as
findings. They are not findings. Two intervals in [0,1] with spans `s_a, s_b` must overlap on at
least `max(0, s_a + s_b − 1)`, so given the span column above the mean overlap was confined **in
advance** to [0.984, 1] — a band **0.016** wide — and coextensivity to [93.5 %, 96.8 %], a band
**3.3 pp** wide. Neither could have come out otherwise; they restate the span column in two extra
symbols. The bound is computed in `verify.py` and reported in place of the point values.

**What replaces them is onsets.** A kill chain orders stage *onsets*; it never claimed extents are
disjoint, so extent was the wrong test. The three dense phases begin within **1.8 %** of campaign
time of one another, while the last phase does not begin until **62.1 %**. The record is *ordered in
onset and coextensive in extent*. What that defeats is not stage-keyed response but
stage-**exclusive** response: reconnaissance, exploitation and staging were all still running at the
final recorded action.

## How it works

![Pipeline: sources are fetched once and content-hashed; four parsers each assert a reconciliation
condition and halt on failure; sixteen derived datasets feed two analyses; verify.py recomputes 61
claims and substitutes them into the manuscript template.](docs/methodology.svg)

Three decisions a reader would otherwise question:

**Envelope overlap is only computed where it can mean something.** What the replay publishes per
phase is an *envelope* — first action to last — not a duty cycle. Six scattered actions produce a
wide envelope and prove nothing, so density is computed and inference is restricted to the three
phases above 1,000 actions. The six sparse phases are shown and excluded. Mean overlap across all
nine is 0.959; quoting that instead would be the more impressive and less true number.

**Duty cycles are not computable from this artifact at all.** `replay_phases.csv` gives per-phase
envelopes and `replay_days.csv` gives per-day totals — the two *marginals* of a phase-by-day table
whose interior Hugging Face does not publish. Simultaneous *extent* is established here;
simultaneous *activity* is not.

**No number in the paper is typed by hand.** `paper/main.tex.tmpl` holds placeholders like
`{{DENSE_SHARE}}` and `verify.py` recomputes each from `data/`. An unknown placeholder fails the
build; a computed-but-unused claim is reported as an orphan. This guarantees the manuscript agrees
with its artifacts — it does **not** establish that a measure is appropriate, and the paper says so.

## Data

`data/` holds 16 derived datasets built from seven cached primary artifacts. Every source carries a
declared evidential class — PRIMARY / INDEPENDENT / SECONDARY — attached to the data rather than
remembered, and every timeline row carries an anchor string checked against the cached bytes. **5 of
7 timeline events are anchored in a primary source**; the two that are not are marked
`UNVERIFIED-SECONDARY`, and every interval computed from them is flagged.

| file | contents |
|---|---|
| `replay_phases.csv` | per-phase first/last action times and counts (the concurrency input) |
| `replay_days.csv`, `replay_cumulative.csv` | per-day and cumulative action counts |
| `replay_events.csv`, `replay.json` | attack graph and 21 representative commands |
| `metr_passages.csv`, `metr_agent_quotes.csv` | 48 quoted passages, 51 page-numbered agent-reasoning excerpts |
| `hfblog_sections.csv`, `hfblog_commands.csv` | 24 sections, 17 captured command blocks |
| `openai_tr_timeline.csv` | 69 timestamped appendix entries |
| `openai_tr_escalation.json` | the two anchored escalation endpoints |
| `timeline.csv`, `timeline_lags.csv` | normalised chronology and computed intervals |

**What is not public, and is not reconstructed here:** the raw ~17,600-action log and the ~1,300
agent transcripts were reviewed on-premises and never released. No analysis in this project needs
individual actions, inter-arrival times, or per-agent attribution.

**Two artifacts look unavailable and are not.** Requests without a browser User-Agent receive HTTP
403 from `huggingface.co`, `openai.com` and `metr.org` — a User-Agent filter, not access control.
And the interactive replay has no companion dataset repository because its data is inline in its
43.9 kB `index.html` as JavaScript literals: a file that reads as an empty shell is the dataset.

The cached source bytes are **not** redistributed. `cache/manifest.json` ships each source's URL,
byte count, fetch time and SHA-256, and `ingest/run_all.py` refetches them; a re-fetch that yields a
different digest is reported rather than silently accepted.

## Two corrections to the inherited incident record

**The phase annotation is not a partition.** The nine phase counts sum to 16,521 against 17,613
recorded actions — 1,092 *below*, a 6.2 % shortfall. The multi-tagging explanation circulating in
secondary summaries predicts a sum *above* the total. Either tags attach to clusters rather than
actions, or ~6 % are unclassified; the source does not say. Nothing here treats phases as a
partition.

**A quotation is attributed to the wrong post.** The "behind commercial APIs" passage on
frontier-model refusal during forensic analysis is cited to Hugging Face's technical timeline. It is
in the **disclosure**. Both posts contain a section on "the asymmetry problem", which is the likely
origin of the mix-up. The quote is genuine and citable; the citation is wrong.

## Repository layout

```
ingest/        fetch, hash and parse each source
  sources.py     registry, HTTP cache, SHA-256 manifest
  replay.py      the interactive replay's inline dataset
  metr.py        the 91-page independent investigation
  hfblog.py      the technical timeline and disclosure
  openai_tr.py   the 38-page technical report's UTC appendix
  timeline.py    normalised chronology and lags
analysis/      concurrency.py (density, onsets, bound), escalation.py (intervals)
data/          16 derived datasets — the artifacts every claim is computed from
results/       claims.json and the analysis outputs
paper/         main.tex.tmpl (source), main.tex (generated), main.pdf, references.bib
index.html     the 6-slide deck -- this IS the published site
build-slides.sh  renders index.html to docs/slides.pdf via headless Chrome
docs/          methodology.svg, the deck as PDF, and the built report PDF
tests/         75 offline tests, including regressions for both parser failure modes
verify.py      recomputes all 61 claims and renders the manuscript
```

## Reproducing it

```bash
pip install -r requirements.txt      # pypdf==6.16.2, Python 3.14.4
python ingest/run_all.py             # rebuild data/ from the byte cache
python ingest/run_all.py --refresh   # re-fetch every source first
python analysis/concurrency.py       # phase density, onsets, bound
python analysis/escalation.py        # escalation intervals
python verify.py                     # recompute 61 claims; render paper/main.tex
cd paper && bash build.sh            # four LaTeX passes -> main.pdf
python -m pytest tests -q            # 75 tests, offline
```

Everything after ingestion runs offline. The pipeline is deterministic and seeds nothing.

## Scope of the result

One campaign, n = 1. No inferential statistic is reported and none would be appropriate. The
escalation finding rests entirely on primary sources; the concurrency finding is weaker and is
reported with its bound. The proposed metric is an instrument, not a measurement — no value of it is
computed for this incident. The paper's Limitations and Dual-Use Considerations section gives the
full treatment.

## Citing this work

```bibtex
@techreport{emadeldin2026escalation,
  author      = {Emad Eldin, Fatimah},
  title       = {Both Sides Detected It, Neither Escalated: Concurrency and
                 Escalation Failure in the July 2026 Autonomous Agent Intrusion},
  institution = {Apart Research \& CeSIA AI Incident Response Sprint, Track 2},
  year        = {2026},
  month       = sep,
  note        = {Corpus retrieved 2026-09-04; OpenAI technical report added 2026-09-05}
}
```

See also [`CITATION.cff`](CITATION.cff).

## Licence

Code MIT ([`LICENSE`](LICENSE)). Derived data in `data/` and `results/` CC BY 4.0. Cached
third-party source bytes are not redistributed and remain under their publishers' terms.
