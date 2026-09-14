"""The README is the one document the build does not generate, which is why it drifts.

Every headline figure quoted on the front page is recomputed in results/claims.json. These tests
fail the build when the two disagree, so a re-run of the pipeline cannot silently leave the README
asserting last week's numbers.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"


@pytest.fixture(scope="module")
def readme() -> str:
    return README.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def claims() -> dict[str, str]:
    path = ROOT / "results" / "claims.json"
    if not path.exists():
        pytest.skip("results/claims.json absent -- run verify.py first")
    return json.loads(path.read_text(encoding="utf-8"))


# Claim key -> the literal string the README must carry for it. Where the README words a figure
# differently from the manuscript (5 h 34 min rather than 5h34m), the expected string is given
# explicitly and checked against the claim separately.
QUOTED_VERBATIM = [
    "TOTAL_ACTIONS", "CAMPAIGN_DAYS", "OAI_ALERT_UTC", "OAI_RESPONSE_UTC",
    "OAI_GAP_EVENTS", "OAI_TR_PAGES", "METR_PAGES", "DENSE_ACTIONS", "PHASE_SUM",
    "DENSE_SHARE", "MEAN_OVERLAP_DENSE", "MEAN_OVERLAP_ALL", "CONCURRENT_PCT",
    "OVERLAP_FLOOR", "OVERLAP_BAND", "PHI_FLOOR", "PHI_CEIL", "PHI_BAND",
    "DENSE_ONSET_SPREAD", "ONSET_LAST", "PHASE_GAP", "PHASE_GAP_PCT",
    "N_DATA_FILES", "N_TESTS", "N_EVENTS_VERIFIED", "N_EVENTS_TOTAL", "N_SOURCES",
    "ALARM_LOW", "ALARM_MED", "ALARM_HIGH", "DENSE_MIN_ACTIONS",
    "LAG_DISCLOSE_TO_CONNECT", "PYTHON_VERSION", "PYPDF_VERSION",
]


@pytest.mark.parametrize("key", QUOTED_VERBATIM)
def test_readme_headline_figure_matches_the_artifact(readme, claims, key):
    assert claims[key] in readme, (
        f"README does not carry the computed value of {key} ({claims[key]!r}); "
        "it was probably edited by hand or the pipeline was re-run"
    )


def test_readme_escalation_interval_matches_the_artifact(readme, claims):
    """The paper's headline interval, worded for prose rather than substituted."""
    expected = f"{claims['OAI_GAP_H']} h {claims['OAI_GAP_M']} min"
    assert expected in readme, f"README should state the interval as {expected!r}"


def test_readme_phase_table_matches_the_generated_paper_table(readme, claims):
    """The README's phase table is checked against the table body the paper renders.

    Both must come from the same computation; a README table edited by hand is exactly the
    drift this file exists to catch.
    """
    body = claims["PHASE_TABLE_TEX"]
    assert body.strip(), "PHASE_TABLE_TEX is empty"

    for line in body.strip().splitlines():
        cells = [c.strip() for c in line.replace(r"\\", "").split("&")]
        if len(cells) < 5:
            continue
        phase, actions, onset, span, density = cells[:5]
        # undo the TeX escaping the table body carries: \texttt{} wrappers and the
        # hyphen doubling that keeps "supply-chain" from being set as an en dash
        phase = re.sub(r"\\texttt\{|\}", "", phase).replace("--", "-")

        m = re.search(rf"^\|\s*{re.escape(phase)}\s*\|(.+)$", readme, re.M)
        assert m, f"README phase table has no row for {phase!r}"
        got = [c.strip() for c in m.group(1).split("|")]
        for i, (label, want) in enumerate(
            (("actions", actions), ("onset", onset), ("span", span), ("density", density))
        ):
            assert got[i] == want, (
                f"{phase}: README {label} is {got[i]!r}, the computed table says {want!r}"
            )


def test_readme_quotes_the_detection_admission_verbatim(readme, claims):
    """The load-bearing quotation must be the one retrieved from the source, not a paraphrase."""
    quote = claims["HF_DETECTION_QUOTE"]
    normalised = " ".join(readme.replace(">", " ").split())
    assert " ".join(quote.split()) in normalised


def test_readme_points_at_files_that_exist(readme):
    """A front page whose paths have rotted is worse than one with no paths."""
    for target in re.findall(r"\]\((?!https?:)([^)#]+)\)", readme):
        assert (ROOT / target).exists(), f"README links to missing path: {target}"


def test_readme_does_not_claim_a_value_for_the_proposed_metric(readme):
    """EMR is not computable from the public record; the paper withdrew that claim."""
    assert "EMR took" not in readme
    assert re.search(r"no value of it is\s+claimed", readme, re.I | re.S), (
        "README must state that no EMR value is claimed for this incident"
    )
