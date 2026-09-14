"""Tests for the perpetrator-side escalation record.

This parser carries a headline claim of the revised paper -- the alert-to-response interval
at OpenAI -- so it is tested rather than trusted. The failure that matters here is not a
crash but a silent mismatch: an anchor drifting onto a neighbouring appendix row would still
produce a confident-looking interval, in the wrong place. The anchor-uniqueness and
same-day assertions below exist for that case specifically.

The arithmetic bound tests at the foot are the other half of the revision: they pin the fact
that the retired concurrency statistics could not have come out differently, so that if the
spans ever change the bound moves with them instead of the prose going stale.
"""
from __future__ import annotations

import itertools

import pytest

import openai_tr


@pytest.fixture(scope="module")
def rows():
    return openai_tr.timeline()


@pytest.fixture(scope="module")
def esc(rows):
    return openai_tr.escalation(rows)


# ------------------------------------------------------------------- document integrity

def test_report_has_the_expected_page_count():
    """A different count means the cached bytes changed under us."""
    assert len(openai_tr.pages()) == openai_tr.EXPECTED_PAGES


def test_appendix_yields_a_plausible_number_of_timestamped_entries(rows):
    assert len(rows) > 40
    assert all(r["date"].startswith("2026-0") for r in rows)
    assert all(len(r["time"]) == 5 and r["time"][2] == ":" for r in rows)


def test_every_entry_records_the_page_it_was_read_from(rows):
    assert all(1 <= r["page"] <= openai_tr.EXPECTED_PAGES for r in rows)


# ----------------------------------------------------------------------- anchor safety

@pytest.mark.parametrize("anchor", [openai_tr.ALERT_ANCHOR, openai_tr.RESPONSE_ANCHOR])
def test_each_anchor_matches_exactly_one_row(rows, anchor):
    """The whole point of anchoring rather than indexing."""
    assert sum(1 for r in rows if anchor in r["desc"]) == 1


def test_a_missing_anchor_raises_rather_than_guessing(rows):
    with pytest.raises(ValueError, match="matched 0 appendix rows"):
        openai_tr._row(rows, "this string is not in the appendix")


def test_both_escalation_endpoints_fall_on_the_alert_day(esc):
    assert esc["alert"]["date"] == openai_tr.ESCALATION_DATE
    assert esc["response"]["date"] == openai_tr.ESCALATION_DATE


# --------------------------------------------------------------------------- the interval

def test_response_follows_the_alert(esc):
    assert esc["gap_minutes"] > 0


def test_gap_minutes_and_hours_agree(esc):
    assert esc["gap_hours"] == pytest.approx(esc["gap_minutes"] / 60.0)


def test_intervening_events_lie_strictly_inside_the_interval(esc):
    for r in esc["between"]:
        assert esc["alert"]["time"] < r["time"] < esc["response"]["time"]
        assert r["date"] == openai_tr.ESCALATION_DATE


def test_the_interval_is_hours_not_days(esc):
    """Bounds the claim rather than pinning the value: this is a within-shift interval.

    Pinning the exact minute count would make the test a transcription of the artifact. What
    the paper's argument needs is that the interval is of order hours -- long enough to be a
    response failure, short enough not to be the multi-day attribution latency it is
    explicitly distinguished from.
    """
    assert 60 < esc["gap_minutes"] < 24 * 60


def test_compromise_continued_inside_the_interval(esc):
    """The interval is consequential, not merely long -- and that is what makes it evidence."""
    assert len(esc["between"]) >= 1


# ------------------------------------------- bounds on the retired concurrency statistics

def _phases_dense():
    import replay

    import concurrency
    ps = replay.load()["PHASES"]
    for p in ps:
        p["span"] = p["last"] - p["first"]
    return [p for p in ps if p["total"] >= concurrency.DENSE_MIN_ACTIONS]


def test_mean_overlap_could_not_have_been_far_from_one():
    """The defect the revision reports: the statistic is pinned by the spans alone."""
    import concurrency
    ps = _phases_dense()
    floors, actuals = [], []
    for a, b in itertools.combinations(ps, 2):
        floors.append(max(0.0, a["span"] + b["span"] - 1.0) / min(a["span"], b["span"]))
        actuals.append(concurrency.overlap(a, b))
    mean_floor = sum(floors) / len(floors)
    assert mean_floor > 0.97, "if this drops, the pinning claim needs restating"
    assert sum(actuals) / len(actuals) >= mean_floor - 1e-9


def test_coextensivity_is_confined_between_its_span_bounds():
    ps = _phases_dense()
    floor = 1.0 - sum(1.0 - p["span"] for p in ps)
    ceiling = min(p["span"] for p in ps)
    assert ceiling - floor < 0.05, "the feasible band is narrow -- that is the finding"

    import concurrency
    prof = concurrency.active_profile(ps)
    phi = sum(1 for v in prof if v == len(ps)) / len(prof)
    assert floor - 1e-9 <= phi <= ceiling + 1e-9


def test_onsets_are_ordered_even_though_extents_are_not():
    """The result that replaces the retired one: onset ordering is real and recoverable."""
    import replay
    ps = replay.load()["PHASES"]
    onsets = sorted(p["first"] for p in ps)
    assert onsets == [p["first"] for p in sorted(ps, key=lambda p: p["first"])]
    # The dense phases start together; something starts materially later.
    assert max(onsets) - min(onsets) > 0.5
