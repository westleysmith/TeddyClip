"""Configuration: built-in defaults overlaid by an optional config.yaml."""

from __future__ import annotations

import getpass
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_ROOT = r"C:\Users\{user}\TeddyClip"


OLD_FOLDER_NAMES = ("1 Inbox", "2 Clips", "3 Highlights", "Done")


@dataclass
class Paths:
    inbox: Path
    clips: Path
    highlights: Path
    done: Path
    cache: Path
    models: Path
    notes: Path  # moments.csv per clip folder, kept out of the clip folders

    def ensure(self) -> None:
        # Folders from versions before the "1 - Raw recordings" names are renamed in place.
        for old, new in zip(OLD_FOLDER_NAMES, (self.inbox, self.clips, self.highlights, self.done)):
            was = new.parent / old
            if was.is_dir() and not new.exists():
                was.rename(new)
        for p in (self.inbox, self.clips, self.highlights, self.done, self.cache, self.models):
            p.mkdir(parents=True, exist_ok=True)


def _default_triggers() -> list[str]:
    return ["clip that", "clip it", "clip this"]


def _default_weights() -> dict[str, float]:
    return {
        "laughter": 1.0,
        "joke_sweep": 0.7,
        "loudness": 0.6,
        "voice_jump": 0.6,
        "screen_text": 0.6,
    }


def _default_games() -> dict[str, str]:
    return {
        "elden ring": "soulslike",
        "dark souls": "soulslike",
        "gta": "sandbox",
        "counter strike": "shooter",
        "red dead": "sandbox",
    }


def _default_lexicons() -> dict[str, list[str]]:
    return {
        "soulslike": [
            "YOU DIED",
            "ENEMY FELLED",
            "GREAT ENEMY FELLED",
            "DEMIGOD FELLED",
            "VICTORY ACHIEVED",
            "HEIR OF FIRE DESTROYED",
        ],
        "sandbox": ["WASTED", "BUSTED", "MISSION PASSED", "MISSION FAILED"],
        "shooter": ["ROUND WON", "ROUND LOST", "ACE", "BOMB PLANTED", "BOMB DEFUSED"],
    }


@dataclass
class Config:
    root: Path
    people: list[str] = field(default_factory=lambda: ["Teddy", "Friend"])
    triggers: list[str] = field(default_factory=_default_triggers)
    audio_track: int | None = None
    whisper_model: str = "auto"
    whisper_device: str = "auto"  # "auto" (GPU when usable) or "cpu" (never touch the GPU)
    language: str | None = "en"  # spoken language for whisper; None means detect it
    llm_model: str = "qwen3:4b"
    llm_url: str = "http://127.0.0.1:11434"
    min_seconds: float = 20
    max_seconds: float = 120
    max_clips: int = 40
    clips_per_hour: float = 15
    pre_trigger_seconds: float = 45
    weights: dict[str, float] = field(default_factory=_default_weights)
    games: dict[str, str] = field(default_factory=_default_games)
    lexicons: dict[str, list[str]] = field(default_factory=_default_lexicons)
    resolve_timeline_start: str = "01:00:00:00"
    resolve_markers: bool = False

    @property
    def paths(self) -> Paths:
        r = Path(self.root)
        return Paths(
            inbox=r / "1 - Raw recordings",
            clips=r / "2 - Clips",
            highlights=r / "3 - Highlight videos",
            done=r / "4 - Finished recordings",
            cache=r / ".cache",
            models=r / ".cache" / "models",
            notes=r / ".cache" / "sessions",
        )


# Flat Config field -> (nested YAML section, key). A None section means a top-level key.
_FLAT_KEYS: dict[str, tuple[str | None, str]] = {
    "root": (None, "root"),
    "people": (None, "people"),
    "triggers": (None, "triggers"),
    "audio_track": (None, "audio_track"),
    "whisper_model": (None, "whisper_model"),
    "whisper_device": (None, "whisper_device"),
    "language": (None, "language"),
    "llm_model": ("llm", "model"),
    "llm_url": ("llm", "url"),
    "min_seconds": ("clips", "min_seconds"),
    "max_seconds": ("clips", "max_seconds"),
    "max_clips": ("clips", "max_clips"),
    "clips_per_hour": ("clips", "per_hour"),
    "pre_trigger_seconds": ("clips", "pre_trigger_seconds"),
    "weights": (None, "weights"),
    "games": (None, "games"),
    "lexicons": (None, "lexicons"),
    "resolve_timeline_start": ("resolve", "timeline_start"),
    "resolve_markers": ("resolve", "markers"),
}


def _username() -> str:
    return os.environ.get("USERNAME") or getpass.getuser()


def load_config(path: Path | None = None) -> Config:
    """Build a Config from defaults, overlaid by the YAML file at `path` if it exists.

    With no path, `config.yaml` in the current directory is used. A `weights` mapping
    is merged over the defaults so a partial override keeps the other signals; every
    other key is replaced outright. Unknown YAML keys are ignored.
    """
    cfg = Config(root=Path(DEFAULT_ROOT))
    if path is None:
        path = Path.cwd() / "config.yaml"
    path = Path(path)
    data: dict = {}
    if path.is_file():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data = loaded

    for name, (section, key) in _FLAT_KEYS.items():
        source = data if section is None else data.get(section)
        if not isinstance(source, dict) or key not in source:
            continue
        value = source[key]
        if name == "weights":
            value = {**cfg.weights, **value}
        setattr(cfg, name, value)

    cfg.root = Path(str(cfg.root).replace("{user}", _username()))
    return cfg
