import hashlib
import json

import pytest
import requests

import teddyclip.llm as llm_mod
from teddyclip.llm import LLM, parse_json


class FakeResp:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(llm_mod.time, "sleep", lambda s: None)


def test_parse_json_messy():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Sure! {"a": 2} hope that helps') == {"a": 2}
    assert parse_json("no json here") is None


def test_parse_json_rejects_non_objects_and_bad_json():
    assert parse_json("{not json}") is None
    assert parse_json("") is None
    assert parse_json("} {") is None


def test_ask_sends_schema_and_caches(tmp_path, monkeypatch):
    calls = []

    def post(url, json, timeout):
        calls.append((url, json, timeout))
        return FakeResp({"message": {"content": '{"score": 7}'}})

    monkeypatch.setattr(requests, "post", post)
    llm = LLM("http://x", "m", tmp_path)
    assert llm.ask("p", {"type": "object"}) == {"score": 7}
    assert llm.ask("p", {"type": "object"}) == {"score": 7}
    assert len(calls) == 1
    url, body, timeout = calls[0]
    assert url == "http://x/api/chat"
    assert timeout == 120
    assert body["format"] == {"type": "object"} and body["think"] is False
    assert body["model"] == "m" and body["stream"] is False
    assert body["messages"] == [{"role": "user", "content": "p"}]
    assert body["options"] == {"num_ctx": 8192, "temperature": 0.2}


def test_cache_file_location_and_atomic_write(tmp_path, monkeypatch):
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp({"message": {"content": '{"a": 1}'}}))
    schema = {"type": "object"}
    LLM("http://x", "m", tmp_path).ask("p", schema)
    key = hashlib.sha1(("m" + "p" + json.dumps(schema)).encode("utf-8")).hexdigest()
    path = tmp_path / "llm" / f"{key}.json"
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 1}
    assert list((tmp_path / "llm").glob("*.tmp")) == []


def test_corrupt_cache_is_a_miss(tmp_path, monkeypatch):
    calls = []

    def post(url, json, timeout):
        calls.append(1)
        return FakeResp({"message": {"content": '{"a": 1}'}})

    monkeypatch.setattr(requests, "post", post)
    llm = LLM("http://x", "m", tmp_path)
    llm.ask("p", {})
    (path,) = (tmp_path / "llm").glob("*.json")
    path.write_text("{ half a file", encoding="utf-8")
    assert llm.ask("p", {}) == {"a": 1}
    assert len(calls) == 2
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 1}


def test_ask_retries_then_none(tmp_path, monkeypatch):
    calls = []

    def post(url, json, timeout):
        calls.append(1)
        return FakeResp({"message": {"content": "garbage"}})

    monkeypatch.setattr(requests, "post", post)
    assert LLM("http://x", "m", tmp_path).ask("p", {}) is None
    assert len(calls) == 3


def test_failed_answer_is_not_cached(tmp_path, monkeypatch):
    replies = iter(["garbage"] * 3 + ['{"ok": true}'])
    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp({"message": {"content": next(replies)}}))
    llm = LLM("http://x", "m", tmp_path)
    assert llm.ask("p", {}) is None
    assert not (tmp_path / "llm").exists() or not list((tmp_path / "llm").glob("*.json"))
    assert llm.ask("p", {}) == {"ok": True}


def test_retry_succeeds_after_transient_errors(tmp_path, monkeypatch):
    calls = []

    def post(url, json, timeout):
        calls.append(1)
        if len(calls) == 1:
            raise requests.ConnectionError("boom")
        if len(calls) == 2:
            return FakeResp({"error": "server"}, status_code=500)
        return FakeResp({"message": {"content": '{"a": 3}'}})

    monkeypatch.setattr(requests, "post", post)
    assert LLM("http://x", "m", tmp_path).ask("p", {}) == {"a": 3}
    assert len(calls) == 3


def test_client_error_is_not_retried(tmp_path, monkeypatch):
    calls = []

    def post(url, json, timeout):
        calls.append(1)
        return FakeResp({"error": "model not found"}, status_code=404)

    monkeypatch.setattr(requests, "post", post)
    assert LLM("http://x", "m", tmp_path).ask("p", {}) is None
    assert len(calls) == 1


def test_none_model_disabled(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("must not call the network")

    monkeypatch.setattr(requests, "post", boom)
    monkeypatch.setattr(requests, "get", boom)
    llm = LLM("http://x", "none", tmp_path)
    assert not llm.enabled and llm.ask("p", {}) is None
    assert not llm.available()


def test_enabled_for_real_model(tmp_path):
    assert LLM("http://x", "qwen3:4b", tmp_path).enabled


def test_available_lists_model(tmp_path, monkeypatch):
    seen = []

    def get(url, timeout):
        seen.append(url)
        return FakeResp({"models": [{"name": "qwen3:4b"}]})

    monkeypatch.setattr(requests, "get", get)
    assert LLM("http://x/", "qwen3:4b", tmp_path).available()
    assert seen == ["http://x/api/tags"]
    assert not LLM("http://x", "other:1b", tmp_path).available()


def test_available_treats_latest_tag_as_same(tmp_path, monkeypatch):
    monkeypatch.setattr(requests, "get", lambda url, timeout: FakeResp({"models": [{"name": "m:latest"}]}))
    assert LLM("http://x", "m", tmp_path).available()
    monkeypatch.setattr(requests, "get", lambda url, timeout: FakeResp({"models": [{"name": "m"}]}))
    assert LLM("http://x", "m:latest", tmp_path).available()


def test_available_false_on_connection_error(tmp_path, monkeypatch):
    def get(url, timeout):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(requests, "get", get)
    assert not LLM("http://x", "m", tmp_path).available()


def test_available_false_on_http_error(tmp_path, monkeypatch):
    monkeypatch.setattr(requests, "get", lambda url, timeout: FakeResp({}, status_code=500))
    assert not LLM("http://x", "m", tmp_path).available()
