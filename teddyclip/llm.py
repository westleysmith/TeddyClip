# Adapted from Clips Kitty (https://github.com/ColinGPT9/clips-studio), AGPL-3.0-or-later, Copyright (C) 2026 ColinGPT9. Modified for TeddyClip.
"""Small client for a local Ollama server: schema-constrained JSON answers,
retried a few times and cached on disk so re-runs skip the model."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

import requests

_TRIES = 3
_PAUSE = 2.0  # seconds before the second try, twice that before the third
_TIMEOUT = 120
_TAGS_TIMEOUT = 5
_GIVE_UP_AFTER = 3  # failed asks in a row before the client turns itself off


def parse_json(text: str) -> dict | None:
    """Tolerant parse: strips code fences, slices the first "{" to the last "}".
    None when nothing usable (no object, bad JSON, or not an object)."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip())
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _same_model(a: str, b: str) -> bool:
    """Ollama lists an untagged model as "name:latest"; the two are one model."""
    def norm(name: str) -> str:
        return name if ":" in name else name + ":latest"
    return norm(a) == norm(b)


class _Problem:
    """Why one request gave no answer. A refusal (a 4xx reply) is not retried."""

    def __init__(self, text: str, refused: bool = False):
        self.text = text
        self.refused = refused


class LLM:
    def __init__(self, url: str, model: str, cache: Path):
        self.url = url.rstrip("/")
        self.model = model
        self.cache = Path(cache)
        self._failures = 0  # failed asks in a row
        self._told = False  # the first problem has been printed
        self._gave_up = False

    @property
    def enabled(self) -> bool:
        """False for model "none", and once Ollama has failed 3 asks in a row."""
        return self.model != "none" and not self._gave_up

    def available(self) -> bool:
        """True when Ollama answers /api/tags and lists the configured model."""
        if not self.enabled:
            return False
        try:
            response = requests.get(f"{self.url}/api/tags", timeout=_TAGS_TIMEOUT)
            response.raise_for_status()
            names = [m.get("name", "") for m in response.json().get("models") or []]
        except Exception:
            return False
        return any(_same_model(name, self.model) for name in names)

    def ask(self, prompt: str, schema: dict) -> dict | None:
        """The model's JSON answer to `prompt`, held to `schema`. Cached; None
        when disabled or when no attempt gave a readable answer (not cached).

        The first problem is printed once. After 3 failed asks in a row the
        client turns itself off for the rest of the recording."""
        if not self.enabled:
            return None
        path = self._cache_path(prompt, schema)
        cached = self._read_cache(path)
        if cached is not None:
            self._failures = 0
            return cached

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "format": schema,
            "stream": False,
            "think": False,
            "options": {"num_ctx": 8192, "temperature": 0.2},
        }
        problem = None
        for attempt in range(1, _TRIES + 1):
            answer = self._try_once(payload)
            if isinstance(answer, dict):
                self._failures = 0
                self._write_cache(path, answer)
                return answer
            problem = answer
            if problem.refused:
                break  # asking again won't change a refusal
            if attempt < _TRIES:
                time.sleep(_PAUSE * attempt)
        self._failed(problem)
        return None

    def _failed(self, problem: _Problem) -> None:
        if not self._told:
            self._told = True
            print(f"  {problem.text}")
        self._failures += 1
        if self._failures >= _GIVE_UP_AFTER:
            self._gave_up = True
            print("  Ollama stopped answering: continuing without AI for this recording")

    def _try_once(self, payload: dict) -> dict | _Problem:
        """One request: the parsed answer, or the _Problem that stopped it."""
        try:
            response = requests.post(f"{self.url}/api/chat", json=payload, timeout=_TIMEOUT)
        except Exception as e:
            return _Problem(f"Ollama did not answer ({type(e).__name__}: {e})")
        if 400 <= response.status_code < 500:
            return _Problem(
                f"Ollama refused the request ({response.status_code}): {_error_text(response)}", refused=True
            )
        if response.status_code >= 500:
            return _Problem(f"Ollama had a server error ({response.status_code}): {_error_text(response)}")
        try:
            content = response.json()["message"]["content"]
        except Exception:
            return _Problem("Ollama sent a reply TeddyClip could not read")
        answer = parse_json(content)
        if answer is None:
            return _Problem("Ollama's answer was not the JSON TeddyClip asked for")
        return answer

    def _cache_path(self, prompt: str, schema: dict) -> Path:
        key = hashlib.sha1((self.model + prompt + json.dumps(schema)).encode("utf-8")).hexdigest()
        return self.cache / "llm" / f"{key}.json"

    @staticmethod
    def _read_cache(path: Path) -> dict | None:
        """The cached answer, or None for a missing or unreadable file."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    @staticmethod
    def _write_cache(path: Path, answer: dict) -> None:
        """Atomic (temp file, then os.replace), so a crash leaves the old file
        or none, never half of one. A cache that can't be written costs only a
        repeat of the question."""
        tmp = path.with_name(path.name + ".tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(answer), encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            pass


def _error_text(response) -> str:
    """Ollama's own error message from a failed reply, kept short."""
    try:
        data = response.json()
        text = data.get("error") if isinstance(data, dict) else None
    except Exception:
        text = None
    if not text:
        text = getattr(response, "text", "") or "no details"
    return " ".join(str(text).split())[:300]
