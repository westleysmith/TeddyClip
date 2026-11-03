import shutil
import subprocess
import time

from conftest import stage_in_inbox

from teddyclip import cli
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
    out = process_recording(stage_in_inbox(tiny_video, cfg, game="Elden Ring"), cfg)
    names = [p.name for p in out.glob("*.mp4")]
    assert any("Clip that" in n for n in names)
    assert (out / "moments.csv").exists() and (out / "Resolve markers.edl").exists()
    assert list(cfg.paths.done.glob("*.mp4")) and not list(cfg.paths.inbox.rglob("*.mp4"))


def test_process_recording_names_the_folder_by_date_and_game(fake_pipeline, tiny_video, cfg):
    fake_pipeline(trigger_at=8.0)
    src = stage_in_inbox(tiny_video, cfg, game="Elden Ring")
    date = time.strftime("%Y-%m-%d", time.localtime(src.stat().st_mtime))
    out = process_recording(src, cfg)
    assert out == cfg.paths.clips / f"{date} Elden Ring"
    assert (cfg.paths.done / f"{date} Elden Ring.mp4").exists()
    assert (out / "Resolve markers.edl").read_text(encoding="ascii").startswith(f"TITLE: {date} Elden Ring")


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
    assert (out / "moments.csv").read_text(encoding="utf-8-sig").startswith("keep,")
    assert list(cfg.paths.done.glob("*.mp4"))


def test_process_recording_continues_without_ollama(fake_pipeline, tiny_video, cfg, monkeypatch, capsys):
    fake_pipeline(trigger_at=8.0)
    monkeypatch.setattr(cli.LLM, "available", lambda self: False)
    out = process_recording(stage_in_inbox(tiny_video, cfg), cfg)
    assert "continuing without AI titles" in capsys.readouterr().out
    assert any("Clip that" in p.name for p in out.glob("*.mp4"))


def test_inbox_continues_after_failure(fake_pipeline, tiny_video, cfg, monkeypatch):
    a = stage_in_inbox(tiny_video, cfg, name="a.mp4"); b = stage_in_inbox(tiny_video, cfg, name="b.mp4")
    real = cli.process_recording
    monkeypatch.setattr(cli, "process_recording", lambda p, c: (_ for _ in ()).throw(RuntimeError()) if p == a else real(p, c))
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
    monkeypatch.setattr(cli, "process_recording", lambda p, c: seen.append(p) or cfg.paths.clips)
    assert process_inbox(cfg) == 0
    assert seen == [done]
    assert "1 processed, 0 failed" in capsys.readouterr().out


def test_check_reports_missing_ffmpeg(cfg, monkeypatch, capsys):
    monkeypatch.setattr(shutil, "which", lambda name: None)
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
    folder = root / "2 Clips" / "2026-11-01 Elden Ring"
    folder.mkdir(parents=True)
    shutil.copy2(tiny_video, folder / "0h00m01s - First.mp4")
    shutil.copy2(tiny_video, folder / "0h00m30s - Second.mp4")
    assert main(["--config", str(conf), "highlight", str(folder)]) == 0
    assert (root / "3 Highlights" / "2026-11-01 Elden Ring.mp4").exists()
    assert (root / "3 Highlights" / "2026-11-01 Elden Ring - chapters.txt").exists()


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
    assert main(["--config", str(conf), "process", str(src)]) == 0
    assert src.exists()
    assert (cfg.paths.done / f"{date} session.mp4").exists()
    assert any("Clip that" in p.name for p in (cfg.paths.clips / f"{date} session").glob("*.mp4"))
