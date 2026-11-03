import shutil
import subprocess

import numpy as np
import pytest

from teddyclip.detectors import Lexicon, banner_texts, game_profile, screen_events
from teddyclip.moments import Moment


def test_game_profile_from_subfolder(tmp_path):
    inbox = tmp_path / "1 Inbox"; f = inbox / "Elden Ring" / "2026-11-01 20-14-03.mp4"
    assert game_profile(f, inbox, {"elden ring": "soulslike"}) == "soulslike"
    assert game_profile(inbox / "gta night.mp4", inbox, {"gta": "sandbox"}) == "sandbox"
    assert game_profile(inbox / "x.mp4", inbox, {"gta": "sandbox"}) == "generic"


def test_game_profile_prefers_subfolder_over_filename(tmp_path):
    inbox = tmp_path / "1 Inbox"
    f = inbox / "Elden Ring" / "gta night.mp4"
    assert game_profile(f, inbox, {"elden ring": "soulslike", "gta": "sandbox"}) == "soulslike"


def test_game_profile_outside_inbox_uses_filename(tmp_path):
    assert game_profile(tmp_path / "other" / "GTA run.mp4", tmp_path / "1 Inbox", {"gta": "sandbox"}) == "sandbox"


def test_lexicon_handles_misreads():
    lex = Lexicon(["YOU DIED", "WASTED"])
    assert lex.find("Y0U  DlED") == ["YOU DIED"] and lex.find("WA5TED") == ["WASTED"]
    assert lex.find("you did it") == []


def test_lexicon_short_terms_match_whole_words_only():
    lex = Lexicon(["ACE"])
    assert lex.find("ACE") == ["ACE"] and lex.find("place") == [] and lex.find("an ace!") == ["ACE"]


def test_banner_filter_ignores_small_text():
    result = [([[0, 0], [100, 0], [100, 50], [0, 50]], "YOU DIED", 0.9),
              ([[0, 0], [100, 0], [100, 10], [0, 10]], "chat msg", 0.9)]
    assert banner_texts(result, frame_height=720) == ["YOU DIED"]


def test_banner_filter_handles_none_and_low_confidence():
    assert banner_texts(None, frame_height=720) == []
    low = [([[0, 0], [100, 0], [100, 50], [0, 50]], "YOU DIED", 0.2)]
    assert banner_texts(low, frame_height=720) == []


def test_screen_events_tags_moment(tiny_video):
    fake_ocr = lambda img: ([([[0, 0], [9, 0], [9, 40], [0, 40]], "YOU DIED", 0.9)], None)
    m = screen_events(tiny_video, [Moment(1, 5, 5, "loud")], Lexicon(["YOU DIED"]), ocr=fake_ocr)[0]
    assert m.events == ["YOU DIED"] and m.kind == "game" and m.score > 5


def test_screen_events_joins_words_ocr_split_into_boxes(tiny_video):
    # Real RapidOCR on a YOU DIED banner returns "YOU" and "DIED" as separate boxes.
    fake_ocr = lambda img: ([([[0, 0], [9, 0], [9, 40], [0, 40]], "YOU", 0.98),
                             ([[20, 0], [29, 0], [29, 40], [20, 40]], "DIED", 0.99)], None)
    m = screen_events(tiny_video, [Moment(1, 5, 10, "trigger")], Lexicon(["YOU DIED"]), ocr=fake_ocr)[0]
    assert m.events == ["YOU DIED"] and m.kind == "trigger"


def test_screen_events_keeps_kind_unless_loud_and_never_mutates(tiny_video):
    fake_ocr = lambda img: ([([[0, 0], [9, 0], [9, 40], [0, 40]], "YOU DIED", 0.9)], None)
    laugh = Moment(1, 5, 5, "laughter")
    out = screen_events(tiny_video, [laugh], Lexicon(["YOU DIED"]), ocr=fake_ocr)[0]
    assert out.kind == "laughter" and out.events == ["YOU DIED"] and out.score == pytest.approx(11)
    assert laugh.events == [] and laugh.score == 5 and out is not laugh


def test_screen_events_adds_bonus_and_event_once(tiny_video):
    fake_ocr = lambda img: ([([[0, 0], [9, 0], [9, 40], [0, 40]], "YOU DIED", 0.9)], None)
    m = screen_events(tiny_video, [Moment(0, 8, 5, "loud")], Lexicon(["YOU DIED"]), weight=0.5, ocr=fake_ocr)[0]
    assert m.events == ["YOU DIED"] and m.score == pytest.approx(10)


def test_screen_events_no_hit_leaves_moment_equal(tiny_video):
    nothing = lambda img: (None, None)
    m = Moment(1, 5, 5, "loud")
    out = screen_events(tiny_video, [m], Lexicon(["YOU DIED"]), ocr=nothing)[0]
    assert out == m


def test_screen_events_respects_max_frames(tiny_video):
    seen = []

    def ocr(img):
        seen.append(img.shape)
        return None, None

    screen_events(tiny_video, [Moment(0, 9, 5, "loud"), Moment(0, 9, 4, "loud")], Lexicon(["X"]),
                  step=1.0, max_frames=3, ocr=ocr)
    assert len(seen) == 3
    h, w, _ = seen[0]
    assert (w, h) == (768, 432)  # center 60 percent of 1280x720


@pytest.mark.slow
def test_real_ocr_reads_rendered_banner(tmp_path):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not installed")
    out = tmp_path / "banner.mp4"
    draw = ("drawtext=fontfile='C\\:/Windows/Fonts/arialbd.ttf':text='YOU DIED':"
            "fontcolor=red:fontsize=140:x=(w-text_w)/2:y=(h-text_h)/2")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=0x101010:s=1280x720:r=30:d=4",
         "-vf", draw, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)],
        check=True,
    )
    m = screen_events(out, [Moment(0, 4, 5, "loud")], Lexicon(["YOU DIED", "WASTED"]))[0]
    assert m.events == ["YOU DIED"] and m.kind == "game"
