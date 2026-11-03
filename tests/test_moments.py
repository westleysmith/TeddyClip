import math

import numpy as np
import pytest

from teddyclip.moments import (
    KINDS,
    Moment,
    forced_windows,
    label,
    load_prompt,
    merge,
    rerank,
    select,
    signal_windows,
    snap,
    sweep,
)
from teddyclip.transcribe import Segment


class FakeLLM:
    def __init__(self, answers, enabled=True):
        self.answers = list(answers)
        self.enabled = enabled
        self.prompts = []

    def ask(self, prompt, schema):
        self.prompts.append(prompt)
        return self.answers.pop(0) if self.answers else None


# forced windows and merge

def test_trigger_near_start_clamps():
    m = forced_windows([20.0], "trigger")[0]
    assert m.start == 0 and m.end == pytest.approx(19.7) and m.kind == "trigger"


def test_forced_window_shape_and_score():
    m = forced_windows([100.0], "marker")[0]
    assert (m.start, m.end, m.score, m.kind) == (55.0, pytest.approx(99.7), 10, "marker")
    assert m.duration == pytest.approx(44.7)


def test_close_triggers_merge_but_stay_triggers():
    ms = merge(forced_windows([100.0, 110.0], "trigger"), segments=[])
    assert len(ms) == 1 and ms[0].kind == "trigger" and ms[0].end == pytest.approx(109.7)
    assert ms[0].start == 55.0


def test_merge_prefers_higher_priority_kind():
    a = Moment(10, 40, 6, "loud")
    b = Moment(15, 45, 4, "laughter")
    out = merge([a, b], [])
    assert len(out) == 1 and out[0].kind == "laughter"
    assert out[0].score == 6 and (out[0].start, out[0].end) == (10, 45)


def test_merge_forced_with_other_keeps_forced_kind_and_end():
    t = Moment(100, 144.7, 10, "trigger")
    o = Moment(120, 170, 8, "laughter", events=["YOU DIED"])
    out = merge([o, t], [])
    assert len(out) == 1
    assert out[0].kind == "trigger" and (out[0].start, out[0].end) == (100, 144.7)
    assert out[0].events == ["YOU DIED"]


def test_merge_never_runs_past_the_trigger_phrase():
    # [90, 130] overlaps only 24 percent of the shorter window, so [75, 130] is used to make them merge.
    t = forced_windows([100.0], "trigger")[0]
    out = merge([t, Moment(75, 130, 9, "loud")], [])
    assert len(out) == 1 and out[0].kind == "trigger"
    assert (out[0].start, out[0].end) == (55, pytest.approx(99.7))


def test_merge_forced_takes_earlier_start_from_other():
    t = Moment(60, 104.7, 10, "marker")
    out = merge([Moment(50, 90, 9, "laughter"), t], [])
    assert len(out) == 1 and out[0].kind == "marker" and (out[0].start, out[0].end) == (50, 104.7)


def test_two_triggers_merged_with_loud_end_at_the_later_trigger():
    out = merge(forced_windows([100.0, 110.0], "trigger") + [Moment(80, 140, 9, "loud")], [])
    assert len(out) == 1 and out[0].kind == "trigger"
    assert (out[0].start, out[0].end) == (55, pytest.approx(109.7))


def test_merge_unions_events_without_duplicates():
    a = Moment(10, 40, 6, "loud", events=["a", "b"])
    b = Moment(12, 42, 4, "joke", events=["b", "c"])
    assert merge([a, b], [])[0].events == ["a", "b", "c"]


def test_merge_keeps_distant_moments_apart_and_sorted():
    out = merge([Moment(500, 530, 5, "loud"), Moment(10, 40, 5, "loud")], [])
    assert [m.start for m in out] == [10, 500]


def test_merge_small_overlap_stays_apart():
    # 5 s overlap of 30 s is under 40 percent
    out = merge([Moment(0, 30, 5, "loud"), Moment(25, 55, 5, "loud")], [])
    assert len(out) == 2


def test_merge_on_text_similarity():
    segs = [Segment(0, 30, "he walked right off the cliff again", []),
            Segment(100, 130, "he walked right off the cliff again", [])]
    a, b = Moment(0, 30, 5, "loud"), Moment(100, 130, 4, "joke")
    assert len(merge([a, b], [])) == 2  # no transcript, no text rule
    out = merge([a, b], segs)
    # far apart: the better one is kept as it is, the span is not stretched over both
    assert len(out) == 1
    assert (out[0].kind, out[0].start, out[0].end, out[0].score) == ("joke", 100, 130, 4)


def test_text_match_far_apart_keeps_trigger_not_the_span():
    segs = [Segment(0, 30, "he walked right off the cliff again", []),
            Segment(5000, 5030, "he walked right off the cliff again", [])]
    out = merge([Moment(0, 30, 9, "loud"), Moment(5000, 5030, 3, "trigger")], segs)
    assert len(out) == 1
    assert (out[0].kind, out[0].start, out[0].end) == ("trigger", 5000, 5030)


def test_text_match_same_kind_keeps_higher_score():
    segs = [Segment(0, 30, "he walked right off the cliff again", []),
            Segment(500, 530, "he walked right off the cliff again", [])]
    out = merge([Moment(0, 30, 4, "loud"), Moment(500, 530, 7, "loud")], segs)
    assert [(m.start, m.score) for m in out] == [(500, 7)]


def test_text_match_between_two_forced_keeps_both():
    segs = [Segment(0, 30, "clip that he walked off", []), Segment(500, 530, "clip that he walked off", [])]
    out = merge([Moment(0, 30, 10, "trigger"), Moment(500, 530, 10, "marker")], segs)
    assert [(m.start, m.end) for m in out] == [(0, 30), (500, 530)]


def test_merge_different_text_does_not_merge():
    segs = [Segment(0, 30, "aaaa bbbb cccc dddd", []), Segment(100, 130, "zzzz yyyy xxxx wwww", [])]
    assert len(merge([Moment(0, 30, 5, "loud"), Moment(100, 130, 5, "loud")], segs)) == 2


# signal windows

def test_signal_windows_kind_is_strongest_signal():
    n = 100
    laugh = np.zeros(n)
    joke = np.zeros(n)
    loud = np.zeros(n)
    loud[50] = 0.9
    laugh[52] = 0.4
    out = signal_windows([(30.0, 65.0, 0.8)], {"laughter": laugh, "joke": joke, "loud": loud})
    assert len(out) == 1
    m = out[0]
    assert m.kind == "loud" and m.score == pytest.approx(8.0) and (m.start, m.end) == (30.0, 65.0)
    laugh[40] = 0.95
    assert signal_windows([(30.0, 65.0, 0.8)], {"laughter": laugh, "loud": loud})[0].kind == "laughter"


def test_signal_windows_tie_goes_to_priority_and_missing_signals_default_to_loud():
    a = np.zeros(100)
    b = np.zeros(100)
    a[40] = b[40] = 0.5
    assert signal_windows([(30.0, 65.0, 0.5)], {"joke": a, "laughter": b})[0].kind == "laughter"
    assert signal_windows([(30.0, 65.0, 0.5)], {})[0].kind == "loud"


# snap

SEGS = [Segment(0, 10, "a", []), Segment(10, 25, "b", []), Segment(25, 40, "c", []),
        Segment(40, 100, "d", [])]


def test_snap_expands_to_segment_boundaries():
    m = snap(Moment(12, 38, 5, "laughter"), SEGS, 20, 120)
    assert (m.start, m.end) == (10, 40)


def test_snap_clamps_long_moments_to_max():
    m = snap(Moment(5, 95, 5, "laughter"), SEGS, 20, 60)
    assert m.duration == pytest.approx(60) and m.start >= 0 and m.end <= 100


def test_snap_extends_short_moments_to_min():
    m = snap(Moment(26, 30, 5, "loud"), SEGS, 20, 120)
    assert m.duration >= 20 - 1e-9


def test_snap_forced_keeps_end_never_grows_and_caps_length():
    m = snap(Moment(-5, 12.5, 10, "trigger"), SEGS, 20, 120)
    assert (m.start, m.end) == (0, 12.5)
    m = snap(Moment(0, 300, 10, "marker"), SEGS, 20, 120)
    assert (m.start, m.end) == (180, 300)
    m = snap(Moment(55, 99.7, 10, "trigger"), SEGS, 20, 120)
    assert (m.start, m.end) == (55, 99.7)


def test_merged_close_triggers_then_snapped_stay_within_max():
    merged = merge(forced_windows([100.0, 125.0, 150.0, 175.0, 200.0], "trigger"), segments=[])
    assert len(merged) == 1 and merged[0].duration > 120
    snapped = snap(merged[0], [], 20, 120)
    assert snapped.duration == pytest.approx(120) and snapped.end == pytest.approx(199.7)
    assert snapped.kind == "trigger"


def test_snap_does_not_mutate_input():
    src = Moment(12, 38, 5, "laughter")
    snap(src, SEGS, 20, 120)
    assert (src.start, src.end) == (12, 38)


# sweep

def test_sweep_disabled_is_zero():
    assert sweep([Segment(0, 300, "hi", [])], FakeLLM([], enabled=False), "{transcript}").max() == 0


def test_sweep_spreads_scores_and_takes_max_on_overlap():
    segs = [Segment(float(t), t + 5.0, f"line {t}", []) for t in range(0, 300, 5)]
    llm = FakeLLM([{"score": 8, "quote": "x"}, {"score": 3, "quote": "y"}, {"score": 5, "quote": "z"}])
    out = sweep(segs, llm, "{transcript}", slice_s=120, overlap_s=30)
    assert len(out) == 300
    assert out[10] == pytest.approx(0.8)
    assert out[100] == pytest.approx(0.8)    # overlap of slice 0 (0-120) and 1 (90-210): max
    assert out[150] == pytest.approx(0.3)
    assert out[250] == pytest.approx(0.5)
    assert len(llm.prompts) == 3
    assert "line 0" in llm.prompts[0] and "line 95" in llm.prompts[1]


def test_sweep_failed_answer_leaves_zero_and_empty_segments_ok():
    segs = [Segment(0, 100, "hello there", [])]
    assert sweep(segs, FakeLLM([None]), "{transcript}").max() == 0
    assert len(sweep([], FakeLLM([]), "{transcript}")) == 0


def test_sweep_clamps_wild_scores():
    segs = [Segment(0, 100, "hello there", [])]
    out = sweep(segs, FakeLLM([{"score": 99, "quote": ""}]), "{transcript}")
    assert out.max() == pytest.approx(1.0)


# label

def test_label_falls_back_when_llm_fails():
    segs = [Segment(0, 30, "no way he just walked off the cliff again buddy", [])]
    out = label([Moment(0, 30, 5, "laughter")], segs, FakeLLM([None]), "{transcript}", ["Teddy"])
    assert out[0].title == "no way he just walked off the cliff" and out[0].why == "laughter"


def test_label_never_trims_triggers():
    llm = FakeLLM([{"score": 8, "title": "T", "why": "w", "trim_start": 10, "trim_end": 20}])
    out = label([Moment(0, 44.7, 10, "trigger")], [], llm, "{transcript}", [])
    assert (out[0].start, out[0].end) == (0, 44.7) and out[0].title == "T"


def test_label_applies_trims_and_fills_prompt():
    llm = FakeLLM([{"score": 9, "title": "Teddy falls", "why": "classic", "trim_start": 5, "trim_end": 8}])
    m = Moment(100, 160, 4, "laughter", events=["YOU DIED"])
    segs = [Segment(100, 160, "Teddy fell off the bridge", [])]
    out = label([m], segs, llm, "T:{transcript}|E:{events}|P:{people}", ["Teddy", "Sam"])
    assert (out[0].start, out[0].end) == (105, 152)
    assert out[0].title == "Teddy falls" and out[0].why == "classic"
    assert out[0].score == pytest.approx(6.5)
    p = llm.prompts[0]
    assert "Teddy fell off the bridge" in p and "YOU DIED" in p and "Teddy, Sam" in p


def test_label_ignores_absurd_trims_and_bad_fields():
    llm = FakeLLM([{"score": "x", "title": 7, "why": None, "trim_start": 40, "trim_end": 40}])
    segs = [Segment(0, 60, "one two three", [])]
    out = label([Moment(0, 60, 5, "loud")], segs, llm, "{transcript}", [])
    assert (out[0].start, out[0].end) == (0, 60) and out[0].score == 5
    assert out[0].title == "one two three" and out[0].why == "loud"


def test_label_title_capped_at_60_and_negative_trims_ignored():
    llm = FakeLLM([{"score": 5, "title": "x" * 90, "why": "w", "trim_start": -3, "trim_end": 0}])
    out = label([Moment(0, 60, 5, "loud")], [], llm, "{transcript}", [])
    assert len(out[0].title) <= 60 and (out[0].start, out[0].end) == (0, 60)


def test_label_skips_model_when_disabled():
    llm = FakeLLM([{"score": 9, "title": "T", "why": "w"}], enabled=False)
    out = label([Moment(0, 30, 5, "loud")], [Segment(0, 30, "hi there", [])], llm, "{transcript}", [])
    assert llm.prompts == [] and out[0].title == "hi there"


# rerank

def test_rerank_repairs_partial_order():
    ms = [Moment(i, i + 30, 5, "loud") for i in range(3)]
    out = rerank(ms, FakeLLM([{"order": [2]}]), "{transcript}")
    assert out[2].score > out[0].score > out[1].score >= 5


def test_rerank_bonus_formula_and_original_order_kept():
    ms = [Moment(i, i + 30, 5, "loud", title=f"t{i}") for i in range(4)]
    out = rerank(ms, FakeLLM([{"order": [3, 1, 0, 2]}]), "{candidates}")
    assert [m.title for m in out] == ["t0", "t1", "t2", "t3"]
    assert [m.score for m in out] == pytest.approx([5 + 6 * 0.5, 5 + 6 * 0.75, 5 + 6 * 0.25, 5 + 6])


def test_rerank_sends_only_top_scoring_moments():
    ms = [Moment(i, i + 30, float(i), "loud") for i in range(6)]
    llm = FakeLLM([{"order": [0, 1]}])
    out = rerank(ms, llm, "{count}", top=2)
    assert llm.prompts == ["2"]
    assert [m.score for m in out[:4]] == [0, 1, 2, 3]       # not sent, unchanged
    assert out[5].score == pytest.approx(5 + 6) and out[4].score == pytest.approx(4 + 3)


def test_rerank_unusable_answer_changes_nothing():
    ms = [Moment(i, i + 30, 5, "loud") for i in range(3)]
    for answer in (None, {"order": "nope"}, {"order": [9, 9]}, {"x": 1}):
        out = rerank(ms, FakeLLM([answer]), "{transcript}")
        assert [m.score for m in out] == [5, 5, 5]
    assert [m.score for m in rerank(ms, FakeLLM([], enabled=False), "{transcript}")] == [5, 5, 5]


def test_rerank_single_moment_makes_no_call():
    llm = FakeLLM([{"order": [0]}])
    assert rerank([Moment(0, 30, 5, "loud")], llm, "{transcript}")[0].score == 5
    assert llm.prompts == []


# select

def test_select_keeps_all_triggers_and_caps_sections():
    ms = [Moment(t, t + 30, 9, "loud") for t in range(0, 600, 31)] + forced_windows([5000], "trigger")
    kept = [m for m in select(ms, duration=8000, max_clips=10) if m.keep]
    assert any(m.kind == "trigger" for m in kept)
    assert sum(1 for m in kept if m.start < 1000) <= 3  # ceil(0.22 * 10)


def test_select_returns_everything_sorted_and_respects_max_clips():
    ms = [Moment(t * 100.0, t * 100.0 + 30, float(t), "loud") for t in range(20)]
    out = select(ms, duration=2000, max_clips=5)
    assert len(out) == 20 and [m.start for m in out] == sorted(m.start for m in out)
    kept = [m for m in out if m.keep]
    assert len(kept) <= 5
    assert min(m.score for m in kept) >= 14      # best ones win subject to section caps


def test_select_forced_exceed_max_clips():
    ms = forced_windows([100.0 + 1000 * i for i in range(5)], "trigger") + [Moment(0, 30, 9, "loud")]
    out = select(ms, duration=6000, max_clips=3)
    kept = [m for m in out if m.keep]
    assert sum(m.kind == "trigger" for m in kept) == 5 and len(kept) == 5


def test_select_marks_markers_and_leaves_input_untouched():
    ms = forced_windows([500.0], "marker") + [Moment(0, 30, 1, "loud")]
    out = select(ms, duration=1000, max_clips=40)
    assert all(m.keep for m in out)
    assert not any(m.keep for m in ms)


def test_select_handles_empty_and_zero_duration():
    assert select([], 100, 10) == []
    assert len(select([Moment(0, 30, 5, "loud")], 0, 10)) == 1


# prompts

@pytest.mark.parametrize("name,fields", [
    ("sweep", {"transcript": "[0 - 5] hi"}),
    ("label", {"transcript": "[0s - 5s] hi", "events": "none", "people": "Teddy, Sam"}),
    ("rerank", {"count": 3, "candidates": "0: x"}),
])
def test_prompts_load_format_and_have_no_dashes(name, fields):
    text = load_prompt(name)
    filled = text.format(**fields)
    for value in fields.values():
        assert str(value) in filled
    assert not any(bad in text for bad in (chr(0x2014), chr(0x2013), "-" * 2))


def test_kinds_order():
    assert KINDS == ("trigger", "marker", "laughter", "joke", "loud", "game")
    assert math.isclose(Moment(1, 4, 0, "loud").duration, 3)
