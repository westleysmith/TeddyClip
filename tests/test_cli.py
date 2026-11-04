import os
import pytest
import shutil
import subprocess
import time
from pathlib import Path

from conftest import stage_in_inbox

from teddyclip import cli, media, session
from teddyclip.cli import check, is_finished, main, process_inbox, process_recording


def test_is_finished(tmp_path):
    f = tmp_path / "r.mp4"; f.write_bytes(b"x")
    assert not is_finished(f, quiet_seconds=60)
    assert is_finished(f, quiet_seconds=60, now=time.time() + 120)


def test_is_finished_is_false_while_another_program_has_the_file_open(tmp_path):
    f = tmp_path / "r.mp4"; f.write_bytes(b"x")
    with open(f, "ab"):
        assert not is_finished(f, quiet_seconds=60, now=time.time() + 120)


def test_process_recording_end_to_end(fake_pipeline, tiny_video, cfg):
    fake_pipeline(trigger_at=8.0)
    out = process_recording(stage_in_inbox(tiny_video, cfg, game="Elden Ring"), cfg, cut=True)
    names = [p.name for p in out.glob("*.mp4")]
    assert any("Clip that" in n for n in names)
    # The clip folder holds only clips; TeddyClip's notes live in its working folder.
    assert {p.suffix for p in out.iterdir()} == {".mp4"}
    assert (cfg.paths.notes / out.name / "moments.csv").exists()
    assert list(cfg.paths.done.glob("*.mp4")) and not list(cfg.paths.inbox.rglob("*.mp4"))


def test_resolve_markers_only_when_turned_on(fake_pipeline, tiny_video, cfg):
    fake_pipeline(trigger_at=8.0)
    cfg.resolve_markers = True
    src = stage_in_inbox(tiny_video, cfg, game="Elden Ring")
    date = time.strftime("%Y-%m-%d", time.localtime(src.stat().st_mtime))
    out = process_recording(src, cfg)
    assert (out / "Resolve markers.edl").read_text(encoding="ascii").startswith(f"TITLE: {date} Elden Ring")


def test_process_recording_names_the_folder_by_date_and_game(fake_pipeline, tiny_video, cfg):
    fake_pipeline(trigger_at=8.0)
    src = stage_in_inbox(tiny_video, cfg, game="Elden Ring")
    date = time.strftime("%Y-%m-%d", time.localtime(src.stat().st_mtime))
    out = process_recording(src, cfg)
    assert out == cfg.paths.clips / f"{date} Elden Ring"
    assert (cfg.paths.done / f"{date} Elden Ring.mp4").exists()


def test_process_recording_adds_a_number_when_the_folder_exists(fake_pipeline, tiny_video, cfg):
    fake_pipeline(trigger_at=8.0)
    src = stage_in_inbox(tiny_video, cfg)
    date = time.strftime("%Y-%m-%d", time.localtime(src.stat().st_mtime))
    (cfg.paths.clips / f"{date} tiny").mkdir(parents=True)
    out = process_recording(src, cfg)
    assert out.name == f"{date} tiny (2)"
    assert (cfg.paths.done / f"{date} tiny (2).mp4").exists()


def test_process_recording_with_no_moments(fake_pipeline, tiny_video, cfg):
    fake_pipeline(trigger_at=None, flat_signals=True)
    out = process_recording(stage_in_inbox(tiny_video, cfg), cfg)
    assert not list(out.glob("*.mp4"))
    assert (cfg.paths.notes / out.name / "moments.csv").read_text(encoding="utf-8-sig").startswith("keep,")
    assert list(cfg.paths.done.glob("*.mp4"))


def test_process_recording_continues_without_ollama(fake_pipeline, tiny_video, cfg, monkeypatch, capsys):
    fake_pipeline(trigger_at=8.0)
    monkeypatch.setattr(cli.LLM, "available", lambda self: False)
    out = process_recording(stage_in_inbox(tiny_video, cfg), cfg, cut=True)
    assert "continuing without AI titles" in capsys.readouterr().out
    assert any("Clip that" in p.name for p in out.glob("*.mp4"))


def test_inbox_continues_after_failure(fake_pipeline, tiny_video, cfg, monkeypatch):
    a = stage_in_inbox(tiny_video, cfg, name="a.mp4"); b = stage_in_inbox(tiny_video, cfg, name="b.mp4")
    real = cli.process_recording
    monkeypatch.setattr(cli, "process_recording", lambda p, c, cut=False: (_ for _ in ()).throw(RuntimeError()) if p == a else real(p, c))
    monkeypatch.setattr(cli, "is_finished", lambda p, **k: True)
    assert process_inbox(cfg) == 1 and a.exists() and not b.exists()


def test_inbox_picks_only_finished_videos(cfg, monkeypatch, capsys):
    cfg.paths.ensure()
    (cfg.paths.inbox / "Game").mkdir()
    done = cfg.paths.inbox / "Game" / "done.MKV"; done.write_bytes(b"x")
    growing = cfg.paths.inbox / "growing.mp4"; growing.write_bytes(b"x")
    (cfg.paths.inbox / "notes.txt").write_text("hi")
    seen = []
    monkeypatch.setattr(cli, "is_finished", lambda p, **k: p != growing)
    monkeypatch.setattr(cli, "process_recording", lambda p, c, cut=False: seen.append(p) or cfg.paths.clips)
    assert process_inbox(cfg) == 0
    assert seen == [done]
    assert "1 processed, 0 failed" in capsys.readouterr().out


def test_check_reports_missing_ffmpeg(cfg, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "empty"))
    assert check(cfg) >= 1 and "ffmpeg not found" in capsys.readouterr().out


def test_bad_config_prints_a_plain_message(tmp_path, capsys):
    bad = tmp_path / "config.yaml"
    bad.write_text("weights: {laughter: loud}\n", encoding="utf-8")
    assert main(["--config", str(bad), "check"]) != 0
    out = capsys.readouterr()
    assert "config" in out.out.lower() and "Traceback" not in out.out + out.err


def test_malformed_yaml_prints_a_plain_message(tmp_path, capsys):
    bad = tmp_path / "config.yaml"
    bad.write_text("people: [Teddy\n", encoding="utf-8")
    assert main(["--config", str(bad)]) != 0
    assert "config" in capsys.readouterr().out.lower()


def test_highlight_joins_a_clip_folder(tiny_video, tmp_path):
    root = tmp_path / "Root"
    conf = tmp_path / "config.yaml"
    conf.write_text(f"root: '{root}'\n", encoding="utf-8")
    folder = root / "2 - Clips" / "2026-11-01 Elden Ring"
    folder.mkdir(parents=True)
    shutil.copy2(tiny_video, folder / "0h00m01s - First.mp4")
    shutil.copy2(tiny_video, folder / "0h00m30s - Second.mp4")
    assert main(["--config", str(conf), "highlight", str(folder)]) == 0
    assert (root / "3 - Highlight videos" / "2026-11-01 Elden Ring.mp4").exists()
    assert (root / "3 - Highlight videos" / "2026-11-01 Elden Ring - chapters.txt").exists()


def test_recording_without_sound_fails_plainly_and_leaves_no_cache(fake_pipeline, cfg, monkeypatch, capsys):
    cfg.paths.ensure()
    silent = cfg.paths.inbox / "silent.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=3",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(silent)],
        check=True,
    )
    monkeypatch.setattr(cli, "is_finished", lambda p, **k: True)
    assert process_inbox(cfg) == 1
    assert "no sound track" in capsys.readouterr().out
    assert silent.exists()
    assert not [p for p in cfg.paths.cache.iterdir() if p.name.startswith("silent.mp4")]


def test_process_outside_the_inbox_keeps_the_original(fake_pipeline, tiny_video, cfg, tmp_path):
    fake_pipeline(trigger_at=8.0)
    elsewhere = tmp_path / "Recordings"
    elsewhere.mkdir()
    src = elsewhere / "session.mp4"
    shutil.copy2(tiny_video, src)
    date = time.strftime("%Y-%m-%d", time.localtime(src.stat().st_mtime))
    conf = tmp_path / "config.yaml"
    conf.write_text(f"root: '{cfg.root}'\n", encoding="utf-8")
    assert main(["--config", str(conf), "process", "--cut-all", str(src)]) == 0
    assert src.exists() and not (cfg.paths.done / f"{date} session.mp4").exists()
    assert any("Clip that" in p.name for p in (cfg.paths.clips / f"{date} session").glob("*.mp4"))
    assert session.load(cfg, f"{date} session")["recording"] == str(src)


def test_process_recording_passes_language_and_device_to_whisper(fake_pipeline, tiny_video, cfg):
    state = fake_pipeline(trigger_at=8.0)
    cfg.language, cfg.whisper_device = None, "cpu"
    process_recording(stage_in_inbox(tiny_video, cfg), cfg)
    assert state["transcribe_calls"] == [{"model": "auto", "language": None, "device": "cpu"}]


def test_check_with_whisper_device_cpu_skips_the_gpu(cfg, monkeypatch, capsys):
    cfg.whisper_device = "cpu"
    monkeypatch.setattr(cli, "pick_engine", lambda *a: (_ for _ in ()).throw(AssertionError("GPU checked")))
    check(cfg)
    assert "whisper_device: cpu" in capsys.readouterr().out


@pytest.mark.parametrize("engine,reason,expected", [
    ("cuda", "NVIDIA graphics card (faster-whisper)", "transcribes on the NVIDIA graphics card"),
    ("whisper.cpp", "graphics card through Vulkan (whisper.cpp)", "transcribes on the graphics card through Vulkan"),
    ("cpu", "no NVIDIA GPU with a working driver was found", "on the CPU, which is slower"),
])
def test_check_says_which_engine_transcribes(cfg, monkeypatch, capsys, engine, reason, expected):
    monkeypatch.setattr(cli, "pick_engine", lambda *a: (engine, reason))
    check(cfg)
    assert expected in capsys.readouterr().out


def test_bad_whisper_device_is_a_config_error(tmp_path, capsys):
    bad = tmp_path / "config.yaml"
    bad.write_text("whisper_device: gpu\n", encoding="utf-8")
    assert main(["--config", str(bad), "check"]) == 2
    assert "whisper_device" in capsys.readouterr().out


# late failures

FFMPEG_ERROR = (
    "ffmpeg could not cut a clip (exit code 1):\n"
    "[out#0/mp4 @ 000001] Error writing trailer: No space left on device\n"
    "Conversion failed!"
)


def test_summary_line_is_the_last_meaningful_line_of_the_error():
    assert cli._summary(FFMPEG_ERROR) == "[out#0/mp4 @ 000001] Error writing trailer: No space left on device"
    assert cli._summary("plain message") == "plain message"
    assert cli._summary("header only:\n\n") == "header only:"


def test_inbox_summary_shows_the_meaningful_line(cfg, monkeypatch, capsys):
    cfg.paths.ensure()
    (cfg.paths.inbox / "a.mp4").write_bytes(b"x")
    monkeypatch.setattr(cli, "is_finished", lambda p, **k: True)
    monkeypatch.setattr(cli, "process_recording", lambda p, c, cut=False: (_ for _ in ()).throw(RuntimeError(FFMPEG_ERROR)))
    assert process_inbox(cfg) == 1
    summary = capsys.readouterr().out.split("\nDone:")[1]
    assert "Failed: a.mp4 ([out#0/mp4 @ 000001] Error writing trailer: No space left on device)" in summary
    assert "exit code" not in summary


def test_a_full_finished_drive_stops_before_an_mkv_is_converted(fake_pipeline, tiny_video, cfg, monkeypatch):
    fake_pipeline(trigger_at=8.0)
    mkv = tiny_video.with_suffix(".mkv")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(tiny_video), "-c", "copy", str(mkv)], check=True)
    src = stage_in_inbox(mkv, cfg)
    monkeypatch.setattr(cli.shutil, "disk_usage", lambda p: shutil._ntuple_diskusage(100, 99, 1))
    with pytest.raises(RuntimeError) as e:
        process_recording(src, cfg)
    assert str(e.value).startswith("Not enough free space on ")
    assert "to file the original in Finished recordings: need about" in str(e.value)
    assert src.exists() and not [p for p in cfg.paths.clips.iterdir()]


def test_an_mp4_is_filed_even_when_the_drive_is_nearly_full(fake_pipeline, tiny_video, cfg, monkeypatch):
    fake_pipeline(trigger_at=8.0)
    monkeypatch.setattr(cli.shutil, "disk_usage", lambda p: shutil._ntuple_diskusage(100, 99, 1))
    process_recording(stage_in_inbox(tiny_video, cfg), cfg)  # a move needs no room
    assert list(cfg.paths.done.glob("*.mp4"))


def test_a_failed_run_leaves_its_clip_folder_marked_incomplete(fake_pipeline, tiny_video, cfg, monkeypatch):
    fake_pipeline(trigger_at=8.0)
    src = stage_in_inbox(tiny_video, cfg)
    date = time.strftime("%Y-%m-%d", time.localtime(src.stat().st_mtime))
    real_file = cli.file_original
    monkeypatch.setattr(cli, "file_original", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk gone")))
    for _ in range(2):
        try:
            process_recording(src, cfg)
        except RuntimeError:
            pass
        else:
            raise AssertionError("no error")
    names = sorted(p.name for p in cfg.paths.clips.iterdir())
    assert names == [f"{date} tiny (incomplete 2)", f"{date} tiny (incomplete)"]
    assert src.exists()
    monkeypatch.setattr(cli, "file_original", real_file)
    assert process_recording(src, cfg).name == f"{date} tiny"


def test_inbox_skips_an_mkv_that_obs_already_remuxed_to_mp4(cfg, monkeypatch, capsys):
    cfg.paths.ensure()
    game = cfg.paths.inbox / "Game"
    game.mkdir()
    for name in ("session.mkv", "session.mp4", "other.mkv"):
        (game / name).write_bytes(b"x")
    (cfg.paths.inbox / "session.mkv").write_bytes(b"x")   # no .mp4 next to this one
    seen = []
    monkeypatch.setattr(cli, "is_finished", lambda p, **k: True)
    monkeypatch.setattr(cli, "process_recording", lambda p, c, cut=False: seen.append(p) or cfg.paths.clips)
    assert process_inbox(cfg) == 0
    assert sorted(seen) == sorted([game / "session.mp4", game / "other.mkv", cfg.paths.inbox / "session.mkv"])
    out = capsys.readouterr().out
    assert out.count("session.mkv") == 1 and "duplicate" in out
    assert (game / "session.mkv").exists()


@pytest.mark.parametrize("seconds,expected", [(600, 3), (3600, 15), (4 * 3600, 40), (30, 3)])
def test_clip_limit_scales_with_length(cfg, seconds, expected):
    assert cli.clip_limit(seconds, cfg) == expected


def test_process_inbox_can_take_just_some_recordings(cfg, monkeypatch):
    for rel in ("A/one.mp4", "B/two.mp4"):
        f = cfg.paths.inbox / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x")
        old = time.time() - 600
        os.utime(f, (old, old))
    done = []
    monkeypatch.setattr(cli, "process_recording", lambda p, c, cut=False: done.append(p.name) or p)
    assert cli.process_inbox(cfg, only=[str(Path("B") / "two.mp4")]) == 0
    assert done == ["two.mp4"]


def test_finding_clips_cuts_nothing_and_saves_the_session(fake_pipeline, tiny_video, cfg):
    fake_pipeline(trigger_at=8.0)
    src = stage_in_inbox(tiny_video, cfg, game="Elden Ring")
    out = process_recording(src, cfg)
    assert out.is_dir() and list(out.iterdir()) == []
    data = session.load(cfg, out.name)
    filed = cfg.paths.done / f"{out.name}.mp4"
    assert data["recording"] == str(filed) and filed.exists() and data["preview"] is None
    assert "trigger" in [s["kind"] for s in data["suggestions"]] and data["made"] == []
    assert len(data["cues"]["laughter"]) == len(data["cues"]["yelling"]) == 10
    assert data["cues"]["laughter"][3] > 0
    assert data["segments"] == [{"start": 8.0, "end": 8.7, "text": "Clip that!"}]


def test_cut_all_cuts_every_suggestion_and_records_it(fake_pipeline, tiny_video, cfg):
    fake_pipeline(trigger_at=8.0)
    out = process_recording(stage_in_inbox(tiny_video, cfg), cfg, cut=True)
    data = session.load(cfg, out.name)
    assert sorted(p.name for p in out.glob("*.mp4")) == sorted(m["file"] for m in data["made"])
    assert len(data["made"]) == len(data["suggestions"]) > 0
    assert {m["suggestion"] for m in data["made"]} == {s["id"] for s in data["suggestions"]}


def test_a_recording_the_window_cannot_play_gets_a_preview(fake_pipeline, tiny_video, cfg):
    fake_pipeline(trigger_at=8.0)
    hevc = tiny_video.with_name("hevc.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(tiny_video), "-c:v", "libx265", "-c:a", "copy", str(hevc)],
                   check=True)
    out = process_recording(stage_in_inbox(hevc, cfg), cfg)
    preview = Path(session.load(cfg, out.name)["preview"])
    assert preview.parent == session.session_dir(cfg, out.name) and media.window_playable(preview)


@pytest.mark.parametrize("argv, cut", [([], False), (["--cut-all"], True)])
def test_cut_all_flag_reaches_the_inbox_run(cfg, tmp_path, monkeypatch, argv, cut):
    seen = []
    monkeypatch.setattr(cli, "process_inbox", lambda c, only=None, cut=False: seen.append(cut) or 0)
    conf = tmp_path / "config.yaml"
    conf.write_text(f"root: '{cfg.root}'\n", encoding="utf-8")
    assert main(["--config", str(conf), *argv]) == 0 and seen == [cut]


@pytest.mark.parametrize("taken", ["archived", "session file", "finished mp4 for an mkv"])
def test_a_new_session_never_reuses_a_name_still_in_use(fake_pipeline, tiny_video, cfg, taken):
    fake_pipeline(trigger_at=8.0)
    src = tiny_video
    if taken == "finished mp4 for an mkv":
        src = tiny_video.with_suffix(".mkv")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(tiny_video), "-c", "copy", str(src)], check=True)
    staged = stage_in_inbox(src, cfg)
    date = time.strftime("%Y-%m-%d", time.localtime(staged.stat().st_mtime))
    name = f"{date} tiny"
    cfg.paths.ensure()
    if taken == "archived":
        (cfg.paths.clips / "Archived" / name).mkdir(parents=True)
    elif taken == "session file":
        session.session_dir(cfg, name).mkdir(parents=True)
    else:
        (cfg.paths.done / f"{name}.mp4").write_bytes(b"older session")
    assert process_recording(staged, cfg).name == f"{name} (2)"


def test_a_preview_that_fails_still_leaves_a_usable_session(fake_pipeline, tiny_video, cfg, monkeypatch, capsys):
    fake_pipeline(trigger_at=8.0)
    monkeypatch.setattr(cli, "window_playable", lambda p: False)
    monkeypatch.setattr(cli, "make_preview", lambda *a: (_ for _ in ()).throw(RuntimeError("encoder said no")))
    out = process_recording(stage_in_inbox(tiny_video, cfg), cfg)
    data = session.load(cfg, out.name)
    assert data["preview"] is None and data["suggestions"] and out.name.endswith("tiny")
    assert "encoder said no" in capsys.readouterr().out


def test_cutting_that_fails_after_filing_keeps_the_session(fake_pipeline, tiny_video, cfg, monkeypatch):
    fake_pipeline(trigger_at=8.0)
    monkeypatch.setattr(cli, "write_clips", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk full")))
    src = stage_in_inbox(tiny_video, cfg)
    with pytest.raises(RuntimeError, match="disk full"):
        process_recording(src, cfg, cut=True)
    folders = [p.name for p in cfg.paths.clips.iterdir()]
    assert len(folders) == 1 and "incomplete" not in folders[0]
    assert session.load(cfg, folders[0])["suggestions"]


def test_the_failure_message_says_where_the_recording_is(fake_pipeline, tiny_video, cfg, monkeypatch, capsys):
    fake_pipeline(trigger_at=8.0)
    monkeypatch.setattr(cli, "write_clips", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk full")))
    monkeypatch.setattr(cli, "is_finished", lambda p: True)
    stage_in_inbox(tiny_video, cfg)
    process_inbox(cfg, cut=True)
    out = capsys.readouterr().out
    assert "It stays in Raw recordings" not in out and "Finished recordings" in out


def test_finding_clips_starts_ollama_when_it_is_not_running(fake_pipeline, tiny_video, cfg, monkeypatch):
    fake_pipeline(trigger_at=8.0)
    started = []
    monkeypatch.setattr(cli.LLM, "available", lambda self: bool(started))
    monkeypatch.setattr(cli, "start_ollama", lambda url: started.append(url) or True)
    process_recording(stage_in_inbox(tiny_video, cfg), cfg)
    assert started == [cfg.llm_url]
