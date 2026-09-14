"""Tests for the Track 2 ingest layer.

All of these run from the byte cache, so the suite is offline and deterministic. If the cache is
missing, `sources.fetch` will reach the network once and populate it.

The parser tests are deliberately regression-shaped. Both bugs they cover were bugs I actually
wrote, and both belong to the class this project keeps being bitten by: a parser that produces
plausible wrong data rather than failing. A test that only checks "it parses" would have passed
against both.
"""
from __future__ import annotations

import json

import pytest

import hfblog
import metr
import replay
import sources
import timeline


# --------------------------------------------------------------------------- sources

def test_every_source_is_class_labelled():
    for key, s in sources.SOURCES.items():
        assert s.source_class in {"PRIMARY", "INDEPENDENT", "SECONDARY"}, key
        assert s.author and s.title, key


def test_manifest_records_a_digest_for_each_cached_source():
    man = json.loads(sources.MANIFEST.read_text(encoding="utf-8"))
    for key in sources.SOURCES:
        if sources.SOURCES[key].path.exists():
            assert len(man[key]["sha256"]) == 64
            assert man[key]["bytes"] > 0


def test_text_refuses_to_decode_a_pdf():
    # A PDF read as text silently yields mojibake rather than an error, and every page number
    # computed from it would be meaningless.
    with pytest.raises(ValueError):
        sources.text("metr_report")


# --------------------------------------------------------------------------- replay parser

def test_js_scanner_keeps_a_url_containing_a_double_slash():
    """The first parser stripped `//` as a comment and ate the rest of the command."""
    src = """[{cmd:'curl -s http://host/path', out:'staged'}]"""
    got = replay.js_to_json(src)
    assert got[0]["cmd"] == "curl -s http://host/path"
    assert got[0]["out"] == "staged"


def test_js_scanner_keeps_single_quotes_inside_a_double_quoted_string():
    """The second parser rewrote `'...'` pairs and corrupted this real record."""
    src = """[{cmd:"curl -sw '%{http_code}' https://x/key", phase:'tailscale'}]"""
    got = replay.js_to_json(src)
    assert got[0]["cmd"] == "curl -sw '%{http_code}' https://x/key"
    assert got[0]["phase"] == "tailscale"


def test_js_scanner_handles_trailing_commas_and_nested_arrays():
    assert replay.js_to_json("[[0,0],[1,2],]") == [[0, 0], [1, 2]]


def test_js_scanner_does_not_quote_a_word_that_is_not_a_key():
    got = replay.js_to_json("""[{desc:'gzip / base64 packing, AV probing'}]""")
    assert got[0]["desc"] == "gzip / base64 packing, AV probing"


def test_replay_arrays_all_present_and_shaped():
    d = replay.load()
    for name in replay.ARRAYS:
        assert d[name], name
    assert len(d["PHASES"]) == 9
    assert len(d["DAYS"]) == 5
    assert len(d["EVENTS"]) == 21


def test_replay_days_reconcile_with_cumulative_curve_and_reported_total():
    d = replay.load()
    assert sum(x["actions"] for x in d["DAYS"]) == replay.REPORTED_TOTAL
    assert d["CUM"][-1][1] == replay.REPORTED_TOTAL


def test_phase_totals_sit_below_the_action_total():
    """Guards the correction, not just the number.

    The project's incident record says "Totals exceed 17,600 because HF's clustering allows one
    cluster to carry multiple tags." Multi-tagging implies a sum ABOVE the total. The published
    figures sum below it, so that explanation cannot be right and phases are not a partition.
    """
    d = replay.load()
    phase_sum = sum(x["total"] for x in d["PHASES"])
    assert phase_sum < replay.REPORTED_TOTAL
    assert replay.REPORTED_TOTAL - phase_sum == 1092


def test_phases_run_concurrently_rather_than_in_sequence():
    """The kill-chain observation, as an assertion rather than a remark."""
    d = replay.load()
    spans = {p["key"]: p["last"] - p["first"] for p in d["PHASES"]}
    assert spans["recon"] > 0.98
    assert spans["rce"] > 0.97
    assert spans["dropper"] > 0.96
    # If any of these ever drops below half, the "phases are not stages" claim needs rewriting.
    assert sum(1 for v in spans.values() if v > 0.5) >= 6


# --------------------------------------------------------------------------- METR parser

def test_metr_has_the_expected_page_count():
    assert len(metr.pages()) == metr.EXPECTED_PAGES


def test_metr_quotes_carry_page_numbers_within_range():
    pgs = metr.pages()
    quotes = metr.agent_quotes(pgs)
    assert len(quotes) >= 40
    for q in quotes:
        assert 1 <= q["page"] <= metr.EXPECTED_PAGES
        assert len(q["quote"]) >= metr.MIN_QUOTE_CHARS


def test_metr_separates_agent_reasoning_from_prose_quotation():
    pgs = metr.pages()
    braces = {q["quote"] for q in metr.agent_quotes(pgs)}
    quoted = {p["passage"] for p in metr.passages(pgs)}
    # Different evidence classes; merging them would attribute METR's prose to an agent.
    assert not (braces & quoted)


def test_metr_names_the_founding_agent():
    ids = metr.agent_ids(metr.pages())
    assert "PHASEONE10841" in ids
    assert ids["PHASEONE10841"] >= 10


# --------------------------------------------------------------------------- HF blog parser

def test_hfblog_locates_every_quote_anchor():
    qs = hfblog.quotes(sources.text("hf_blog_timeline"))
    assert set(qs) == set(hfblog.QUOTE_ANCHORS)


def test_hfblog_detection_quote_is_about_criticality_not_coverage():
    """The load-bearing quote for the escalation argument."""
    qs = hfblog.quotes(sources.text("hf_blog_timeline"))
    t = qs["detection_criticality"]["text"]
    assert "criticality" in t and "on-call" in t


def test_defenders_dilemma_quote_is_in_the_disclosure_not_the_technical_timeline():
    """Pins the corrected attribution.

    This test previously asserted the sentence appeared in NO source, and failed -- correctly.
    The quotation is genuine; the project's incident record simply attributes it to the wrong
    Hugging Face post. Both posts carry a section on "the asymmetry problem", which is the
    likeliest origin of the mix-up, so the two are pinned apart here deliberately.
    """
    assert "behind commercial APIs" in sources.text("hf_disclosure")
    assert "behind commercial APIs" not in sources.text("hf_blog_timeline")
    for key in ("openai_road_ahead", "openai_disclosure"):
        assert "behind commercial APIs" not in sources.text(key), key


def test_disclosure_quote_extraction_returns_the_full_sentence():
    qs = hfblog.disclosure_quotes(sources.text("hf_disclosure"))
    t = qs["defenders_dilemma"]["text"]
    assert "frontier models behind commercial APIs" in t
    assert qs["defenders_dilemma"]["source"] == "hf_disclosure"


def test_hfblog_code_fences_do_not_become_headings():
    md = sources.text("hf_blog_timeline")
    titles = [s["title"] for s in hfblog.sections(md)]
    # Captured commands contain lines like `# probe in-cluster API`; those are shell comments.
    assert not any(t.startswith("probe in-cluster") for t in titles)
    assert "TL;DR" in titles


# --------------------------------------------------------------------------- timeline

def test_timeline_marks_secondary_dates_as_unverified():
    events = timeline.verify(list(timeline.EVENTS))
    by = {e.label: e.status for e in events}
    assert by["OpenAI connects its evaluation to the intrusion"] == "UNVERIFIED-SECONDARY"
    assert sum(1 for e in events if e.status == "VERIFIED") >= 5


def test_no_timeline_anchor_is_missing():
    events = timeline.verify(list(timeline.EVENTS))
    assert [e.label for e in events if e.status == "ANCHOR-NOT-FOUND"] == []


def test_intrusion_duration_matches_the_published_window():
    rows = timeline.lags(timeline.verify(list(timeline.EVENTS)))
    dur = next(r for r in rows if "First recorded" in r["from"] and "Last recorded" in r["to"])
    assert dur["days"] == pytest.approx(4.49, abs=0.02)


def test_lag_rows_inherit_the_weakest_source_status():
    rows = timeline.lags(timeline.verify(list(timeline.EVENTS)))
    r = next(r for r in rows if "OpenAI connects" in r["to"])
    assert "UNVERIFIED" in r["weakest_status"]
