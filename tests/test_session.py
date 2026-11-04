import json
import math

import numpy as np

from teddyclip import session
from teddyclip.moments import Moment
from teddyclip.transcribe import Segment

SEGS = [Segment(0.0, 4.0, " Now for the game to end ", []), Segment(5.0, 9.5, "I have to kill you.", [])]


def _build(duration=10.4, moments=None):
    laughter = np.array([0, 0, 0.6789, 0, 1.0], dtype=np.float32)
    yelling = np.linspace(0, 1, 30).astype(np.float32)  # longer than the video: trimmed
    moments = moments if moments is not None else [
        Moment(6.0, 9.0, 8.04, "laughter", title="Worst ending", why="big laugh", keep=True),
        Moment(1.04, 4.0, 10.0, "trigger", keep=True),
        Moment(3.0, 5.0, 2.0, "loud"),  # not kept: not a suggestion
    ]
    return session.build("2026-11-04 Lego", "C:/x/rec.mp4", None, duration, SEGS, laughter, yelling, moments)


def test_build_keeps_the_kept_moments_in_time_order():
    data = _build()
    assert data["version"] == 1 and data["name"] == "2026-11-04 Lego" and data["made"] == []
    assert data["recording"] == "C:/x/rec.mp4" and data["preview"] is None and data["duration"] == 10.4
    assert [(s["id"], s["start"], s["end"], s["kind"]) for s in data["suggestions"]] == \
        [(1, 1.0, 4.0, "trigger"), (2, 6.0, 9.0, "laughter")]
    assert data["suggestions"][1]["title"] == "Worst ending" and data["suggestions"][1]["score"] == 8.0
    assert data["segments"] == [{"start": 0.0, "end": 4.0, "text": "Now for the game to end"},
                                {"start": 5.0, "end": 9.5, "text": "I have to kill you."}]


def test_an_untitled_suggestion_is_named_after_what_was_said():
    assert _build()["suggestions"][0]["title"] == "Now for the game to end"


def test_cues_have_one_rounded_value_per_second():
    cues = _build()["cues"]
    assert len(cues["laughter"]) == len(cues["yelling"]) == math.ceil(10.4)
    assert cues["laughter"][:5] == [0, 0, 0.68, 0, 1.0] and cues["laughter"][5:] == [0] * 6
    assert cues["yelling"][-1] == round(10 / 29, 2)


def test_a_moment_past_the_end_is_clamped():
    data = _build(duration=8.0, moments=[Moment(6.0, 12.0, 5, "loud", keep=True)])
    assert (data["suggestions"][0]["start"], data["suggestions"][0]["end"]) == (6.0, 8.0)


def test_save_and_load_round_trip(cfg):
    data = _build()
    path = session.save(cfg, data)
    assert path == session.session_dir(cfg, data["name"]) / "session.json"
    assert session.load(cfg, data["name"]) == json.loads(json.dumps(data))
    assert sorted(p.name for p in path.parent.iterdir()) == ["session.json"]  # no .tmp left


def test_load_is_none_when_missing_or_unreadable(cfg):
    assert session.load(cfg, "nope") is None
    folder = session.session_dir(cfg, "broken")
    folder.mkdir(parents=True)
    (folder / "session.json").write_text("{not json", encoding="utf-8")
    assert session.load(cfg, "broken") is None


def test_record_made_adds_and_replaces(cfg):
    session.save(cfg, _build())
    name = "2026-11-04 Lego"
    a = {"file": "a.mp4", "start": 1.0, "end": 4.0, "title": "A", "suggestion": 1}
    b = {"file": "b.mp4", "start": 6.0, "end": 9.0, "title": "B", "suggestion": 2}
    session.record_made(cfg, name, a)
    session.record_made(cfg, name, b)
    a2 = {**a, "file": "a2.mp4", "end": 5.0}
    data = session.record_made(cfg, name, a2, replace="a.mp4")
    assert [m["file"] for m in data["made"]] == ["b.mp4", "a2.mp4"]
    assert session.load(cfg, name)["made"] == data["made"]
    again = session.record_made(cfg, name, {**b, "end": 9.5})  # same file: one entry
    assert [m["file"] for m in again["made"]] == ["a2.mp4", "b.mp4"] and again["made"][-1]["end"] == 9.5
