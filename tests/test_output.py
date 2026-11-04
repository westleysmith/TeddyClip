import csv
import subprocess
import tempfile
from pathlib import Path

import pytest

from teddyclip import media
from teddyclip.media import Probe
from teddyclip.moments import Moment
from teddyclip.output import (
    build_highlight,
    clip_name,
    file_original,
    write_clips,
    write_moments_csv,
    write_resolve_edl,
    youtube_chapters,
)


def write_and_read_edl(moments, fps=59.94, timeline_start="01:00:00:00", title="Test") -> str:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "markers.edl"
        write_resolve_edl(moments, path, fps, timeline_start, title)
        return path.read_bytes().decode("ascii")


# clip names


def test_clip_name_sanitizes():
    m = Moment(3760, 3800, 9, "trigger", title='Teddy\'s "best" run?: part/2')
    assert clip_name(m) == "1h02m40s - Clip that - Teddy's best run part2.mp4"


def test_clip_name_marker_has_no_prefix():
    assert clip_name(Moment(65, 95, 9, "marker", title="Hotkey")) == "0h01m05s - Hotkey.mp4"


def test_clip_name_other_kinds_have_no_prefix():
    assert clip_name(Moment(5, 40, 7, "joke", title="Funny")) == "0h00m05s - Funny.mp4"


def test_clip_name_empty_title_becomes_moment():
    assert clip_name(Moment(0, 30, 5, "loud", title="")) == "0h00m00s - moment.mp4"
    assert clip_name(Moment(0, 30, 5, "loud", title='?:"')) == "0h00m00s - moment.mp4"


def test_clip_name_caps_title_at_80_and_trims_dots_and_spaces():
    name = clip_name(Moment(0, 30, 5, "loud", title="x" * 200))
    assert name == "0h00m00s - " + "x" * 80 + ".mp4"
    assert clip_name(Moment(0, 30, 5, "loud", title="Wait for it...  ")) == "0h00m00s - Wait for it.mp4"
    assert clip_name(Moment(0, 30, 5, "loud", title="a   b \t c")) == "0h00m00s - a b c.mp4"


# YouTube chapters


def test_youtube_chapter_rules():
    assert youtube_chapters([(0, 20, "a"), (20, 40, "b")]) == []
    assert youtube_chapters([(0, 20, "a"), (20, 25, "b"), (25, 60, "c")]) == []
    assert youtube_chapters([(0, 20, "a"), (20, 40, "b"), (40, 3700, "c")]) == ["0:00 a", "0:20 b", "0:40 c"]


def test_youtube_chapters_must_start_at_zero_and_ascend():
    assert youtube_chapters([(5, 25, "a"), (25, 45, "b"), (45, 65, "c")]) == []
    assert youtube_chapters([(0, 20, "a"), (40, 60, "b"), (20, 40, "c")]) == []
    assert youtube_chapters([]) == []


def test_youtube_chapters_hour_timestamps_floor_seconds():
    entries = [(0, 20, "a"), (20.9, 3750.5, "b"), (3750.9, 3800, "c")]
    assert youtube_chapters(entries) == ["0:00 a", "0:20 b", "1:02:30 c"]


# Resolve EDL


def test_edl_lines():
    ms = [Moment(12.5, 42.5, 9, "trigger", title="Malenia", keep=True)]
    text = write_and_read_edl(ms, fps=59.94, timeline_start="01:00:00:00")
    assert "01:00:12:29 01:00:12:30" in text and "|C:ResolveColorRed |M:Malenia |D:1798" in text


def test_edl_header_and_event_layout():
    ms = [Moment(12.5, 42.5, 9, "trigger", title="Malenia", keep=True)]
    lines = write_and_read_edl(ms, title="Elden Ring").splitlines()
    assert lines[0] == "TITLE: Elden Ring"
    assert lines[1] == "FCM: NON-DROP FRAME"
    event = "001  001      V     C        01:00:12:29 01:00:12:30 01:00:12:29 01:00:12:30"
    assert event in lines
    assert lines[lines.index(event) + 1] == " |C:ResolveColorRed |M:Malenia |D:1798"


def test_edl_uses_crlf_only():
    ms = [Moment(0, 30, 9, "marker", title="One", keep=True)]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "m.edl"
        write_resolve_edl(ms, path, 30.0, "01:00:00:00", "T")
        raw = path.read_bytes()
    assert b"\r\n" in raw
    assert raw.replace(b"\r\n", b"").count(b"\n") == 0


def test_edl_marker_names_are_ascii_safe_and_keep_apostrophes():
    ms = [Moment(0, 30, 9, "joke", title="Teddy's | caf\u00e9 \u2014 \U0001F602 run", keep=True)]
    text = write_and_read_edl(ms)  # decoding as ascii proves nothing else slipped through
    assert "|M:Teddy's cafe run |D:" in text


def test_edl_colors_by_kind():
    colors = {
        "trigger": "ResolveColorRed",
        "marker": "ResolveColorRed",
        "laughter": "ResolveColorYellow",
        "joke": "ResolveColorBlue",
        "game": "ResolveColorPurple",
        "loud": "ResolveColorGreen",
    }
    for kind, color in colors.items():
        text = write_and_read_edl([Moment(0, 10, 5, kind, title="T", keep=True)])
        assert f"|C:{color} |M:T |D:" in text, kind


def test_edl_only_kept_moments_numbered_in_order_with_timeline_start():
    ms = [
        Moment(100, 130, 5, "joke", title="Later", keep=True),
        Moment(50, 60, 5, "loud", title="Dropped", keep=False),
        Moment(10, 40, 5, "game", title="Earlier", keep=True),
    ]
    text = write_and_read_edl(ms, fps=30.0, timeline_start="10:00:00:00")
    assert "Dropped" not in text
    assert text.index("|M:Earlier") < text.index("|M:Later")
    assert "001  001      V     C        10:00:10:00 10:00:10:01" in text
    assert "002  001      V     C        10:01:40:00 10:01:40:01" in text
    assert "|D:900" in text


def test_edl_with_nothing_kept_is_header_only():
    for ms in ([], [Moment(0, 30, 5, "loud", title="x")]):
        text = write_and_read_edl(ms, title="Empty")
        assert text.strip().splitlines() == ["TITLE: Empty", "FCM: NON-DROP FRAME"]


# moments.csv


def test_csv_has_all_moments(tmp_path):
    p = tmp_path / "m.csv"
    write_moments_csv([Moment(0, 30, 5, "loud"), Moment(60, 90, 9, "joke", keep=True)], p)
    rows = list(csv.DictReader(p.open(encoding="utf-8-sig")))
    assert len(rows) == 2 and rows[1]["start"] == "0:01:00"


def test_csv_columns_bom_and_values(tmp_path):
    p = tmp_path / "m.csv"
    m = Moment(3760, 3800, 8.5, "trigger", title="Caf\u00e9, \"quoted\"", why="because", events=["boss", "death"], keep=True)
    write_moments_csv([m, Moment(0, 30, 5, "loud")], p)
    assert p.read_bytes().startswith(b"\xef\xbb\xbf")
    reader = csv.DictReader(p.open(encoding="utf-8-sig", newline=""))
    assert reader.fieldnames == ["keep", "start", "end", "score", "kind", "title", "why", "events", "file"]
    kept, dropped = list(reader)
    assert kept["keep"] == "yes" and kept["start"] == "1:02:40" and kept["end"] == "1:03:20"
    assert kept["score"] == "8.5" and kept["kind"] == "trigger"
    assert kept["title"] == "Caf\u00e9, \"quoted\"" and kept["why"] == "because"
    assert kept["events"] == "boss; death"
    assert kept["file"] == clip_name(m)
    assert dropped["keep"] == "no" and dropped["file"] == ""


def test_csv_with_no_moments_is_header_only(tmp_path):
    p = tmp_path / "m.csv"
    write_moments_csv([], p)
    lines = p.read_text(encoding="utf-8-sig").splitlines()
    assert lines == ["keep,start,end,score,kind,title,why,events,file"]


# clips


def test_write_clips_cuts_only_kept_and_names_them(tiny_video, tmp_path):
    ms = [
        Moment(1, 4, 9, "trigger", title="Boss", keep=True),
        Moment(5, 8, 8, "marker", title="Hotkey", keep=True),
        Moment(6, 9, 3, "loud", title="Skipped"),
    ]
    out = tmp_path / "2 Clips" / "rec"
    paths = write_clips(tiny_video, ms, out)
    assert [p.name for p in paths] == ["0h00m01s - Clip that - Boss.mp4", "0h00m05s - Hotkey.mp4"]
    assert sorted(p.name for p in out.iterdir()) == sorted(p.name for p in paths)
    assert abs(media.probe(paths[0]).duration - 3) < 0.5


def test_write_clips_numbers_colliding_names(tiny_video, tmp_path):
    ms = [
        Moment(1, 3, 9, "marker", title="Same", keep=True),
        Moment(1.4, 3, 9, "marker", title="Same", keep=True),
        Moment(1.9, 3.5, 9, "marker", title="Same", keep=True),
    ]
    paths = write_clips(tiny_video, ms, tmp_path / "c")
    assert [p.name for p in paths] == [
        "0h00m01s - Same.mp4",
        "0h00m01s - Same (2).mp4",
        "0h00m01s - Same (3).mp4",
    ]
    assert all(p.is_file() for p in paths)


def test_write_clips_with_nothing_kept_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "cut", lambda *a: (_ for _ in ()).throw(AssertionError("cut called")))
    src = tmp_path / "src.mp4"
    assert write_clips(src, [], tmp_path / "c") == []
    assert write_clips(src, [Moment(0, 30, 5, "loud", title="x")], tmp_path / "c") == []


# highlight


def test_highlight_handles_quotes_in_names(tiny_video, tmp_path):
    d = tmp_path / "clips"; d.mkdir()
    for i, t in enumerate(["Teddy's fall", "Big 'oops'", "Third"]):
        media.cut(tiny_video, i * 3, i * 3 + 3, d / f"0h00m0{i}s - {t}.mp4")
    out = build_highlight(d, tmp_path / "h.mp4", tmp_path / "h.txt")
    assert abs(media.probe(out).duration - 9) < 0.5
    assert "no chapters" in (tmp_path / "h.txt").read_text(encoding="utf-8").lower()


def _fake_media(monkeypatch, durations):
    """Stand in for ffmpeg: probe reads a duration per file name, concat records its input."""
    joined = []
    monkeypatch.setattr(media, "probe", lambda p: Probe(durations[Path(p).name], 30.0, 1920, 1080, 1))

    def fake_concat(files, dst):
        joined.extend(Path(f).name for f in files)
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        Path(dst).write_bytes(b"video")
        return Path(dst)

    monkeypatch.setattr(media, "concat", fake_concat)
    return joined


def test_highlight_chapters_follow_clip_order_and_durations(tmp_path, monkeypatch):
    d = tmp_path / "clips"; d.mkdir()
    names = {
        "0h20m00s - Clip that - Third.mp4": 15.0,
        "0h02m00s - Clip that - First.mp4": 30.0,
        "0h10m00s - Second.mp4": 12.5,
    }
    for n in names:
        (d / n).write_bytes(b"x")
    (d / "notes.txt").write_text("ignore me")
    joined = _fake_media(monkeypatch, names)
    out = build_highlight(d, tmp_path / "out" / "h.mp4", tmp_path / "out" / "chapters.txt")
    assert out == tmp_path / "out" / "h.mp4"
    assert joined == ["0h02m00s - Clip that - First.mp4", "0h10m00s - Second.mp4", "0h20m00s - Clip that - Third.mp4"]
    assert (tmp_path / "out" / "chapters.txt").read_text(encoding="utf-8").splitlines() == [
        "0:00 First",
        "0:30 Second",
        "0:42 Third",
    ]


def test_highlight_orders_by_time_not_by_text(tmp_path, monkeypatch):
    d = tmp_path / "clips"; d.mkdir()
    names = {f"{h}h00m00s - T{h}.mp4": 12.0 for h in (2, 10, 11)}
    for n in names:
        (d / n).write_bytes(b"x")
    joined = _fake_media(monkeypatch, names)
    build_highlight(d, tmp_path / "h.mp4", tmp_path / "h.txt")
    assert joined == ["2h00m00s - T2.mp4", "10h00m00s - T10.mp4", "11h00m00s - T11.mp4"]


def test_highlight_writes_note_when_chapters_not_allowed(tmp_path, monkeypatch):
    d = tmp_path / "clips"; d.mkdir()
    few = {"0h00m00s - A.mp4": 30.0, "0h00m40s - B.mp4": 30.0}
    for n in few:
        (d / n).write_bytes(b"x")
    _fake_media(monkeypatch, few)
    build_highlight(d, tmp_path / "h.mp4", tmp_path / "h.txt")
    note = (tmp_path / "h.txt").read_text(encoding="utf-8")
    assert note.strip() and "fewer than 3" in note and note.endswith("\n")

    (d / "0h01m00s - C.mp4").write_bytes(b"x")
    _fake_media(monkeypatch, {**few, "0h01m00s - C.mp4": 4.0})
    build_highlight(d, tmp_path / "h.mp4", tmp_path / "h2.txt")
    note = (tmp_path / "h2.txt").read_text(encoding="utf-8")
    assert "under 10" in note


def test_highlight_returns_none_for_empty_folder(tmp_path, monkeypatch):
    d = tmp_path / "clips"; d.mkdir()
    monkeypatch.setattr(media, "concat", lambda *a: (_ for _ in ()).throw(AssertionError("concat called")))
    assert build_highlight(d, tmp_path / "h.mp4", tmp_path / "h.txt") is None
    assert not (tmp_path / "h.mp4").exists() and not (tmp_path / "h.txt").exists()


def test_highlight_does_not_rejoin_its_own_output(tmp_path, monkeypatch):
    d = tmp_path / "clips"; d.mkdir()
    names = {f"0h0{i}m00s - T{i}.mp4": 12.0 for i in range(3)}
    for n in names:
        (d / n).write_bytes(b"x")
    (d / "highlight.mp4").write_bytes(b"old")
    joined = _fake_media(monkeypatch, {**names, "highlight.mp4": 99.0})
    build_highlight(d, d / "highlight.mp4", tmp_path / "h.txt")
    assert "highlight.mp4" not in joined and len(joined) == 3


# filing the original


def test_an_inbox_mp4_is_moved_into_finished_as_it_is(tiny_video, tmp_path):
    data = tiny_video.read_bytes()
    done = tmp_path / "Done"
    dst = file_original(tiny_video, done, "session", in_inbox=True)
    assert dst == done / "session.mp4" and dst.read_bytes() == data and not tiny_video.exists()


def test_an_inbox_mkv_becomes_an_mp4_the_window_can_play(tiny_video, tmp_path):
    mkv = tmp_path / "rec.mkv"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(tiny_video), "-c", "copy", str(mkv)], check=True)
    dst = file_original(mkv, tmp_path / "Done", "session", in_inbox=True)
    assert dst == tmp_path / "Done" / "session.mp4" and media.window_playable(dst)
    assert abs(media.probe(dst).duration - 10) < 0.5 and not mkv.exists()


def test_a_recording_from_outside_the_inbox_stays_where_it_is(tiny_video, tmp_path):
    done = tmp_path / "Done"
    assert file_original(tiny_video, done, "session", in_inbox=False) == tiny_video
    assert tiny_video.exists() and not done.exists()


def test_filing_refuses_to_overwrite(tiny_video, tmp_path):
    done = tmp_path / "Done"; done.mkdir()
    existing = done / "x.mp4"; existing.write_bytes(b"precious")
    with pytest.raises(FileExistsError, match="x.mp4"):
        file_original(tiny_video, done, "x", in_inbox=True)
    assert existing.read_bytes() == b"precious" and tiny_video.exists()


def test_a_short_remux_keeps_the_mkv_and_leaves_nothing(tiny_video, tmp_path, monkeypatch):
    mkv = tmp_path / "rec.mkv"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(tiny_video), "-c", "copy", str(mkv)], check=True)
    monkeypatch.setattr(media, "remux_to_mp4", lambda src, dst: media.cut(src, 0, 5, dst))
    with pytest.raises(RuntimeError, match="duration"):
        file_original(mkv, tmp_path / "Done", "x", in_inbox=True)
    assert mkv.exists() and not (tmp_path / "Done" / "x.mp4").exists()
