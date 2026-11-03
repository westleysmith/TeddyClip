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
    assert str(paths.inbox).endswith(r"teddy\TeddyClip\1 Inbox")
    assert paths.clips.name == "2 Clips" and paths.highlights.name == "3 Highlights"
    assert paths.done.name == "Done" and paths.cache.name == ".cache"
