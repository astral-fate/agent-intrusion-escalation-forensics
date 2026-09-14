"""Tests for the Track 2 analysis layer.

The overlap measure gets unit tests against hand-computed intervals before it is trusted on the
real data. A concurrency statistic that is subtly wrong would still produce a confident-looking
number, and the whole kill-chain claim rests on it.
"""
from __future__ import annotations

import pytest

import concurrency
import escalation
import replay


# --------------------------------------------------------------------------- the measure

def _p(first, last, total=5000):
    return {"first": first, "last": last, "total": total}


def test_disjoint_envelopes_do_not_overlap():
    assert concurrency.overlap(_p(0.0, 0.2), _p(0.5, 0.9)) == 0.0


def test_touching_envelopes_do_not_overlap():
    assert concurrency.overlap(_p(0.0, 0.5), _p(0.5, 1.0)) == 0.0


def test_identical_envelopes_overlap_completely():
    assert concurrency.overlap(_p(0.1, 0.9), _p(0.1, 0.9)) == pytest.approx(1.0)


def test_overlap_is_normalised_by_the_shorter_envelope():
    """A short phase entirely inside a long one is fully concurrent with it.

    Normalising by the longer envelope instead would report 0.1 here and make a wholly
    contained phase look almost sequential.
    """
    assert concurrency.overlap(_p(0.0, 1.0), _p(0.4, 0.5)) == pytest.approx(1.0)


def test_partial_overlap_is_the_shared_fraction():
    # shared 0.4-0.6 = 0.2; shorter envelope is 0.4-1.0 = 0.6
    assert concurrency.overlap(_p(0.0, 0.6), _p(0.4, 1.0)) == pytest.approx(0.2 / 0.6)


def test_zero_length_envelope_does_not_divide_by_zero():
    assert concurrency.overlap(_p(0.3, 0.3), _p(0.0, 1.0)) == 0.0


def test_active_profile_counts_simultaneous_envelopes():
    phases = [_p(0.0, 0.5), _p(0.25, 0.75), _p(0.9, 1.0)]
    prof = concurrency.active_profile(phases, steps=100)
    assert prof[0] == 1          # only the first
    assert prof[30] == 2         # first and second
    assert prof[80] == 0         # gap between second and third
    assert prof[95] == 1         # third only
    assert max(prof) == 2


# --------------------------------------------------------------------------- real data

def _phases():
    ps = replay.load()["PHASES"]
    for p in ps:
        p["span"] = p["last"] - p["first"]
        p["dense"] = p["total"] >= concurrency.DENSE_MIN_ACTIONS
    return ps


def test_exactly_three_phases_are_dense():
    dense = {p["key"] for p in _phases() if p["dense"]}
    assert dense == {"dropper", "recon", "rce"}


def test_dense_phases_carry_the_overwhelming_majority_of_labelled_actions():
    ps = _phases()
    dense_actions = sum(p["total"] for p in ps if p["dense"])
    assert dense_actions / sum(p["total"] for p in ps) > 0.97


def test_dense_phases_are_essentially_coextensive():
    """The kill-chain claim, pinned. Ordered stages would put this near zero."""
    ps = [p for p in _phases() if p["dense"]]
    pairs = [concurrency.overlap(a, b)
             for i, a in enumerate(ps) for b in ps[i + 1:]]
    assert min(pairs) > 0.99


def test_sparse_phases_are_excluded_from_the_headline():
    """`evasion` spans 70% of the campaign on six actions -- an envelope, not activity."""
    ev = next(p for p in _phases() if p["key"] == "evasion")
    assert ev["total"] == 6
    assert ev["span"] > 0.6
    assert not ev["dense"]


# --------------------------------------------------------------------------- escalation

def test_alarm_priority_target_is_a_distribution_and_is_status_labelled():
    assert sum(escalation.ALARM_PRIORITY_TARGET.values()) == pytest.approx(1.0)
    # The standards are paywalled; the label must say so wherever the figure travels.
    assert "SECONDARY" in escalation.ALARM_TARGET_STATUS


def test_openai_connected_the_incident_after_the_victim_disclosed():
    """The direction of this interval is the claim; a sign error would invert it."""
    import timeline
    rows = timeline.lags(timeline.verify(list(timeline.EVENTS)))
    r = next(r for r in rows
             if "Hugging Face discloses" in r["from"] and "OpenAI connects" in r["to"])
    assert r["days"] > 0
    assert r["days"] == pytest.approx(4.0, abs=0.01)


def test_the_busiest_day_carries_over_forty_percent_of_all_actions():
    days = replay.load()["DAYS"]
    total = sum(d["actions"] for d in days)
    busiest = max(days, key=lambda d: d["actions"])
    assert busiest["label"] == "07-11"
    assert busiest["actions"] / total > 0.40
