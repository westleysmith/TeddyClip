from teddyclip.config import load_config


def test_defaults_without_file(tmp_path):
    cfg = load_config(tmp_path / "missing.yaml")
    assert cfg.max_clips == 40 and cfg.min_seconds == 20 and cfg.max_seconds == 120
    assert cfg.pre_trigger_seconds == 45
    assert "clip that" in cfg.triggers
    assert cfg.llm_url == "http://127.0.0.1:11434"


def test_yaml_overrides_nested_keys(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("llm:\n  model: none\nclips:\n  max_clips: 5\nresolve:\n  timeline_start: '00:00:00:00'\n")
    cfg = load_config(p)
    assert cfg.llm_model == "none" and cfg.max_clips == 5
    assert cfg.resolve_timeline_start == "00:00:00:00"
    assert cfg.max_seconds == 120  # untouched default


def test_user_placeholder_and_folder_names(tmp_path, monkeypatch):
    monkeypatch.setenv("USERNAME", "teddy")
    p = tmp_path / "c.yaml"; p.write_text("root: C:\\Users\\{user}\\TeddyClip\n")
    paths = load_config(p).paths
    assert str(paths.inbox).endswith(r"teddy\TeddyClip\1 - Raw recordings")
    assert paths.inbox.name == "1 - Raw recordings" and paths.clips.name == "2 - Clips"
    assert paths.highlights.name == "3 - Highlight videos" and paths.done.name == "4 - Finished recordings"
    assert paths.cache.name == ".cache"


def test_old_folder_names_are_renamed_in_place(tmp_path):
    cfg = load_config(tmp_path / "missing.yaml")
    cfg.root = tmp_path
    for old in ("1 Inbox", "2 Clips", "Done"):
        (tmp_path / old).mkdir()
    (tmp_path / "2 Clips" / "keep.mp4").write_bytes(b"x")
    cfg.paths.ensure()
    assert (tmp_path / "2 - Clips" / "keep.mp4").exists() and not (tmp_path / "2 Clips").exists()
    assert (tmp_path / "1 - Raw recordings").is_dir() and (tmp_path / "4 - Finished recordings").is_dir()


def test_language_defaults_to_english_and_null_means_auto_detect(tmp_path):
    assert load_config(tmp_path / "missing.yaml").language == "en"
    p = tmp_path / "c.yaml"
    p.write_text("language: null\n", encoding="utf-8")
    assert load_config(p).language is None
    p.write_text("language: de\n", encoding="utf-8")
    assert load_config(p).language == "de"


def test_whisper_device_defaults_to_auto(tmp_path):
    assert load_config(tmp_path / "missing.yaml").whisper_device == "auto"
    p = tmp_path / "c.yaml"
    p.write_text("whisper_device: cpu\n", encoding="utf-8")
    assert load_config(p).whisper_device == "cpu"


def test_pyproject_pins_python_and_the_gpu_libraries():
    import tomllib
    from pathlib import Path

    project = tomllib.loads((Path(__file__).parent.parent / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    # rapidocr-onnxruntime 1.4.4 has no wheels for Python 3.13 or newer.
    assert project["requires-python"] == ">=3.11,<3.13"
    assert "ctranslate2>=4.8,<4.9" in project["dependencies"]
    assert project["optional-dependencies"]["gpu"] == ["nvidia-cublas-cu12", "nvidia-cudnn-cu12==9.10.*"]
