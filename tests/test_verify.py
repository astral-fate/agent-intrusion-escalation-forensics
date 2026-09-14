"""Tests for the claim harness.

The point of `verify.py` is that the manuscript cannot disagree with its artifacts. These tests
check that guarantee actually holds, rather than that the script runs.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import verify  # noqa: E402


@pytest.fixture(scope="module")
def values():
    return verify.compute()


def test_every_claim_computes(values):
    bad = [k for k, v in values.items() if v.startswith("<<UNCOMPUTABLE")]
    assert bad == []


def test_claim_keys_are_unique():
    keys = [c.key for c in verify.CLAIMS]
    assert len(keys) == len(set(keys))


def test_every_claim_has_a_description():
    for c in verify.CLAIMS:
        assert c.describe.strip()


def test_template_references_no_unknown_placeholder(values):
    tmpl = (ROOT / "paper" / "main.tex.tmpl").read_text(encoding="utf-8")
    used = set(re.findall(r"\{\{([A-Z_]+)\}\}", tmpl))
    assert used - set(values) == set()


@pytest.mark.parametrize("name", ["main.tex"])
def test_rendered_paper_has_no_unsubstituted_placeholders(name):
    text = (ROOT / "paper" / name).read_text(encoding="utf-8")
    assert "{{" not in text
    assert "<<UNCOMPUTABLE" not in text


def test_latex_escaping_protects_specials_but_not_raw_table_claims():
    assert verify.tex_escape("97.3% & up") == r"97.3\% \& up"
    # Table and figure bodies are inserted verbatim; escaping them would destroy the column
    # separators and the TikZ coordinates respectively. The set is pinned because `raw` is a
    # hole in the escaping guarantee: adding to it should require editing this assertion.
    raw = {c.key for c in verify.CLAIMS if c.raw}
    assert raw == {"PHASE_TABLE_TEX", "LAG_TABLE_TEX", "PHASE_FIGURE_TEX"}


def test_repo_url_is_escaped_not_raw():
    """A URL carries underscores and percent-encoding; it must go through the escaper.

    It is also the one claim whose *absence* has to be visible in the rendered PDF rather
    than silent, so the unset marker is plain text that survives escaping legibly.
    """
    assert "REPO_URL" not in {c.key for c in verify.CLAIMS if c.raw}
    assert "\\" not in verify.REPO_URL_UNSET


def test_generated_tex_tables_have_one_row_per_record(values):
    import replay
    assert values["PHASE_TABLE_TEX"].count(r"\\") == len(replay.load()["PHASES"])
    assert values["LAG_TABLE_TEX"].count(r"\\") == len(verify.timeline.LAGS)


def test_abstract_word_count_reads_both_template_languages():
    tex = r"\begin{abstract}\noindent One two three.\end{abstract}"
    assert verify.abstract_words(tex) == 3
    assert verify.abstract_words("## Abstract\nOne two three four.\n---") == 4
    assert verify.abstract_words("no abstract here") is None


def test_the_tex_manuscript_carries_no_stray_percent_signs_in_values(values):
    """A bare `%` from a substituted value would comment out the rest of the line."""
    tex = (ROOT / "paper" / "main.tex").read_text(encoding="utf-8")
    for line in tex.split("\n"):
        # Every literal percent in the body must be escaped; `%` only starts a comment when
        # it is unescaped, and a silently truncated line is invisible in the PDF.
        stripped = line.lstrip()
        if stripped.startswith("%"):
            continue
        assert not re.search(r"(?<!\\)%", line), line


def test_abstract_is_within_the_submission_limit():
    """A listed submission requirement, and the cheapest way to be rejected unread."""
    tex = (ROOT / "paper" / "main.tex").read_text(encoding="utf-8")
    n = verify.abstract_words(tex)
    assert n is not None, "no abstract environment"
    assert n <= verify.ABSTRACT_WORD_LIMIT, f"abstract is {n} words"


def test_paper_carries_the_mandatory_limitations_appendix():
    tex = (ROOT / "paper" / "main.tex").read_text(encoding="utf-8")
    assert "Limitations and Dual-Use Considerations" in tex


def test_paper_has_the_expected_academic_section_structure():
    """Methodology, Results, Error analysis and Discussion must all be present and distinct."""
    tex = (ROOT / "paper" / "main.tex").read_text(encoding="utf-8")
    for heading in ("Introduction", "Background and related work", "Data",
                    "Methodology", "Results", "Error analysis", "Discussion",
                    "Conclusion"):
        assert f"section{{{heading}}}" in tex, heading


def test_paper_does_not_narrate_its_own_development():
    """A manuscript is a contribution, not a record of the session that produced it."""
    tex = (ROOT / "paper" / "main.tex").read_text(encoding="utf-8")
    for phrase in ("errors we made", "we concluded the sentence appeared",
                   "grep classified", "rewritten three times", "at first"):
        assert phrase.lower() not in tex.lower(), phrase


def test_headline_numbers_in_the_paper_match_the_artifacts(values):
    """The whole design in one assertion: the rendered text carries the computed values."""
    tex = (ROOT / "paper" / "main.tex").read_text(encoding="utf-8")
    for key in ("DENSE_SHARE", "CONCURRENT_PCT", "MEAN_OVERLAP_DENSE",
                "LAG_DISCLOSE_TO_CONNECT", "PHASE_GAP"):
        assert values[key] in tex, key


def test_the_larger_less_true_number_is_present_but_not_the_headline(values):
    """Mean overlap across all nine phases is reported, and reported as the weaker measure."""
    tex = (ROOT / "paper" / "main.tex").read_text(encoding="utf-8")
    assert values["MEAN_OVERLAP_ALL"] in tex
    i_all = tex.find(values["MEAN_OVERLAP_ALL"])
    i_abstract_end = tex.find(r"\end{abstract}")
    # It must not appear in the abstract, where the headline lives.
    assert i_all > i_abstract_end
