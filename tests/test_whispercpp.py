import json
import subprocess

import pytest

from teddyclip import transcribe as transcribe_mod
from teddyclip import whispercpp

# The shape of whisper-cli -ojf output (trimmed to what TeddyClip reads).
FULL_JSON = {"transcription": [
    {"offsets": {"from": 1000, "to": 2600}, "text": " Clip that, dude!",
     "tokens": [
         {"text": "[_BEG_]", "offsets": {"from": 1000, "to": 1000}},
         {"text": " Clip", "offsets": {"from": 1000, "to": 1300}},
         {"text": " that", "offsets": {"from": 1300, "to": 1600}},
         {"text": ",", "offsets": {"from": 1600, "to": 1650}},
         {"text": " du", "offsets": {"from": 1700, "to": 1900}},
         {"text": "de", "offsets": {"from": 1900, "to": 2100}},
         {"text": "!", "offsets": {"from": 2100, "to": 2200}},
         {"text": "[_TT_130]", "offsets": {"from": 2600, "to": 2600}},
     ]},
    {"offsets": {"from": 5000, "to": 6000}, "text": "  ", "tokens": []},
]}


def test_tokens_become_words_with_timings():
    segs = whispercpp.to_segments(FULL_JSON["transcription"])
    assert len(segs) == 1 and segs[0].text == "Clip that, dude!"
    assert [(w.text, w.start, w.end) for w in segs[0].words] == [
        ("Clip", 1.0, 1.3), ("that,", 1.3, 1.65), ("dude!", 1.7, 2.2)]


def test_run_reads_progress_device_and_json(tmp_path, monkeypatch):
    stderr = ["ggml_vulkan: Found 1 Vulkan devices:\n",
              "ggml_vulkan: 0 = Intel(R) Graphics (Intel Corporation) | uma: 1\n",
              "whisper_print_progress_callback: progress =  50%\n",
              "whisper_print_progress_callback: progress = 100%\n"]

    class FakeProc:
        def __init__(self, cmd, **kw):
            out = cmd[cmd.index("-of") + 1]
            (tmp_path / "whispercpp.json").write_text(json.dumps(FULL_JSON), encoding="utf-8")
            assert out == str(tmp_path / "whispercpp") and kw.get("creationflags", 0) == getattr(subprocess, "CREATE_NO_WINDOW", 0)
            self.stderr = iter(stderr)

        def wait(self):
            return 0

    seen = []
    monkeypatch.setattr(whispercpp.subprocess, "Popen", FakeProc)
    monkeypatch.setattr(whispercpp.progress, "step", lambda f, label=None: seen.append(f))
    raw, device = whispercpp.run(tmp_path / "a.wav", tmp_path, tmp_path)
    assert device == "Intel(R) Graphics" and seen == [0.5, 1.0] and raw[0]["text"].strip() == "Clip that, dude!"


def test_engine_choice_order(tmp_path, monkeypatch):
    monkeypatch.setattr(transcribe_mod, "gpu_ready", lambda: (True, "NVIDIA"))
    assert transcribe_mod.pick_engine("auto", tmp_path)[0] == "cuda"
    monkeypatch.setattr(transcribe_mod, "gpu_ready", lambda: (False, "no NVIDIA GPU"))
    monkeypatch.setattr(whispercpp, "available", lambda m: (True, "ready"))
    assert transcribe_mod.pick_engine("auto", tmp_path)[0] == "whisper.cpp"
    monkeypatch.setattr(whispercpp, "available", lambda m: (False, "the engine is not installed"))
    engine, reason = transcribe_mod.pick_engine("auto", tmp_path)
    assert engine == "cpu" and "not installed" in reason
    assert transcribe_mod.pick_engine("cpu", tmp_path)[0] == "cpu"


def test_graphics_card_failure_falls_back_to_the_cpu(tmp_path, monkeypatch):
    monkeypatch.setattr(transcribe_mod, "pick_engine", lambda device, models: ("whisper.cpp", "Vulkan"))
    monkeypatch.setattr(transcribe_mod, "_run_whispercpp", lambda *a: (_ for _ in ()).throw(RuntimeError("vk lost")))
    loaded = []
    monkeypatch.setattr(transcribe_mod, "_load_model", lambda model, device: loaded.append(device) or "cpu-model")
    monkeypatch.setattr(transcribe_mod, "_run", lambda m, wav, hw, lang: [transcribe_mod.Segment(0, 1, "hi", [])])
    segs = transcribe_mod.transcribe(tmp_path / "a.wav", tmp_path, models=tmp_path)
    assert loaded == ["cpu"] and segs[0].text == "hi"
    assert (tmp_path / "transcript.json").exists()


def test_available_explains_what_is_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("TEDDYCLIP_WHISPER_CLI", str(tmp_path / "missing.exe"))
    assert "not installed" in whispercpp.available(tmp_path)[1]
    (tmp_path / "missing.exe").write_bytes(b"")
    assert "not downloaded" in whispercpp.available(tmp_path)[1]
    (tmp_path / whispercpp.MODEL_NAME).write_bytes(b"")
    assert whispercpp.available(tmp_path) == (True, "ready")
