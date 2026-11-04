import re
import shutil
import threading

import numpy as np
import pytest

from teddyclip import editing, media, session, ui
from teddyclip.moments import Moment
from teddyclip.transcribe import Segment

NAME = "2026-11-04 Lego"


@pytest.fixture
def saved(cfg, tiny_video):
    """A found session whose recording is the 10 s test video."""
    cfg.paths.ensure()
    recording = cfg.paths.done / f"{NAME}.mp4"
    shutil.copy2(tiny_video, recording)
    (cfg.paths.clips / NAME).mkdir(parents=True, exist_ok=True)
    data = session.build(NAME, recording, None, 10.0, [Segment(1.0, 3.0, "is it a game over", [])],
                         np.zeros(10), np.zeros(10), [Moment(1.0, 4.0, 9, "laughter", title="Game over", keep=True)])
    session.save(cfg, data)
    return recording


def test_a_cut_makes_the_clip_and_records_it(cfg, saved):
    clip = editing.cut_clip(cfg, NAME, 1.0, 4.0, "Game over", suggestion=1)
    assert clip == cfg.paths.clips / NAME / "0h00m01s - Game over.mp4"
    assert abs(media.probe(clip).duration - 3.0) < 0.2
    assert session.load(cfg, NAME)["made"] == [
        {"file": clip.name, "start": 1.0, "end": 4.0, "title": "Game over", "suggestion": 1}]


@pytest.mark.parametrize("start, end, words", [
    (4.0, 4.0, "at least 1 second"), (5.0, 2.0, "at least 1 second"), (0.0, 0.5, "at least 1 second"),
    ("a", 3.0, "start and end"), (float("nan"), 3.0, "start and end"), (True, 3.0, "start and end"),
])
def test_bad_ranges_are_refused_plainly(cfg, saved, start, end, words):
    with pytest.raises(editing.CutError, match=words):
        editing.cut_clip(cfg, NAME, start, end, "x")
    assert not list((cfg.paths.clips / NAME).iterdir())


def test_a_range_past_the_ends_is_clamped(cfg, saved):
    clip = editing.cut_clip(cfg, NAME, -5.0, 99.0, "Whole thing")
    assert clip.name.startswith("0h00m00s") and abs(media.probe(clip).duration - 10.0) < 0.3


def test_a_clip_over_ten_minutes_is_refused(cfg, saved, monkeypatch):
    data = session.load(cfg, NAME)
    session.save(cfg, {**data, "duration": 4000.0})
    with pytest.raises(editing.CutError, match="10 minutes"):
        editing.cut_clip(cfg, NAME, 0.0, 601.0, "x")


def test_an_unknown_session_or_missing_recording_is_a_plain_error(cfg, saved):
    with pytest.raises(editing.CutError, match="session"):
        editing.cut_clip(cfg, "nope", 1.0, 3.0, "x")
    saved.unlink()
    with pytest.raises(editing.CutError, match="recording"):
        editing.cut_clip(cfg, NAME, 1.0, 3.0, "x")


def test_the_same_title_twice_never_overwrites(cfg, saved):
    a = editing.cut_clip(cfg, NAME, 1.0, 4.0, "Game over")
    b = editing.cut_clip(cfg, NAME, 1.0, 4.0, "Game over")
    assert a.name == "0h00m01s - Game over.mp4" and b.name == "0h00m01s - Game over (2).mp4"
    assert a.exists() and b.exists()


def test_replace_swaps_out_only_that_clip(cfg, saved):
    old = editing.cut_clip(cfg, NAME, 1.0, 4.0, "Game over", suggestion=1)
    other = editing.cut_clip(cfg, NAME, 5.0, 8.0, "Other")
    new = editing.cut_clip(cfg, NAME, 2.0, 6.0, "Game over, longer", replace=old.name, suggestion=1)
    assert not old.exists() and new.exists() and other.exists()
    assert sorted(m["file"] for m in session.load(cfg, NAME)["made"]) == sorted([other.name, new.name])
    same = editing.cut_clip(cfg, NAME, 2.0, 7.0, "Game over, longer", replace=new.name)
    assert same.name == new.name and abs(media.probe(same).duration - 5.0) < 0.2


def test_replace_must_be_a_clip_of_this_session(cfg, saved):
    for bad in ["../x.mp4", "missing.mp4", "notes.txt"]:
        with pytest.raises(editing.CutError, match="clip to replace"):
            editing.cut_clip(cfg, NAME, 1.0, 3.0, "x", replace=bad)


@pytest.mark.parametrize("title, fallback, expected", [
    ('a:b?"c/d\\e*f<g>h|i', "x", "abcdefghi"),
    ("   ", "is it a game over", "is it a game over"),
    ("...", "", "clip"),
    ("Worst ending ever 😂", "x", "Worst ending ever 😂"),
])
def test_titles_become_safe_windows_names(title, fallback, expected):
    out = editing.safe_title(title, fallback)
    assert out == expected and not re.search(r'[<>:"/\\|?*]', out) and not out.endswith((".", " "))


def test_an_empty_title_falls_back_to_what_was_said(cfg, saved):
    assert editing.cut_clip(cfg, NAME, 1.0, 4.0, "  ").name == "0h00m01s - is it a game over.mp4"


def test_cutting_works_while_clips_are_being_found(cfg, saved):
    job, gate = ui.Job(), threading.Event()
    assert job.start("Finding clips", lambda: gate.wait(10))
    try:
        assert editing.cut_clip(cfg, NAME, 1.0, 3.0, "During a run").exists()
    finally:
        gate.set()


def test_a_replaced_clip_goes_to_the_recycle_bin(cfg, saved, monkeypatch):
    binned = []
    monkeypatch.setattr(ui, "to_recycle_bin", lambda p: (binned.append(p.name), p.unlink()))
    old = editing.cut_clip(cfg, NAME, 1.0, 4.0, "Game over")
    new = editing.cut_clip(cfg, NAME, 2.0, 5.0, "Game over", replace=old.name)
    assert binned == [old.name] and new.exists() and not old.exists()
