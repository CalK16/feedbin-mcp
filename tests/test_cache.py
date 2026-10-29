from __future__ import annotations

from pathlib import Path

import pytest

from feedbin_mcp.cache import DEFAULT_CACHE_PATH, EntryCache, default_cache_path

ENTRY = {
    "id": 1,
    "feed_id": 10,
    "title": "Hello",
    "url": "https://example.com/hello",
    "published": "2013-02-03T01:00:19.000000Z",
    "created_at": "2013-02-04T01:00:19.127893Z",
    "content": "<p>" + "x" * 600 + "</p>",
    "summary": "Hello world",
}


def test_upsert_and_get(tmp_path: Path) -> None:
    cache = EntryCache(tmp_path / "entries.db")
    cache.upsert(ENTRY)
    got = cache.get(1)
    assert got == ENTRY
    assert got is not None
    assert "<p>" in got["content"]
    assert cache.get(999) is None
    cache.close()


def test_upsert_replaces_and_skips_invalid(tmp_path: Path) -> None:
    cache = EntryCache(tmp_path / "nested" / "entries.db")
    cache.upsert(ENTRY)
    cache.upsert({**ENTRY, "title": "Updated"})
    cache.upsert_many([])
    cache.upsert_many([{"title": "no-id"}, "skip", {**ENTRY, "id": 2, "title": "Two"}])
    assert cache.get(1)["title"] == "Updated"
    assert cache.get(2)["title"] == "Two"
    cache.close()


def test_get_many_and_missing_ids(tmp_path: Path) -> None:
    cache = EntryCache(tmp_path / "entries.db")
    cache.upsert_many([ENTRY, {**ENTRY, "id": 3, "title": "Three"}])
    assert cache.get_many([]) == {}
    many = cache.get_many([1, 2, 3])
    assert set(many) == {1, 3}
    assert cache.missing_ids([1, 2, 3, 3]) == [2]
    cache.close()


def test_list_entries_filters(tmp_path: Path) -> None:
    cache = EntryCache(tmp_path / "entries.db")
    cache.upsert_many(
        [
            {**ENTRY, "id": 1, "feed_id": 10, "title": "Alpha", "created_at": "2020-01-01T00:00:00Z"},
            {**ENTRY, "id": 2, "feed_id": 10, "title": "Beta post", "created_at": "2021-01-01T00:00:00Z"},
            {**ENTRY, "id": 3, "feed_id": 11, "title": "Gamma", "created_at": "2022-01-01T00:00:00Z"},
        ]
    )
    by_feed = cache.list_entries(feed_id=10)
    assert [row["id"] for row in by_feed] == [2, 1]
    found = cache.list_entries(search="beta")
    assert [row["id"] for row in found] == [2]
    limited = cache.list_entries(limit=1)
    assert [row["id"] for row in limited] == [3]
    cache.close()


def test_stats_and_last_poll(tmp_path: Path) -> None:
    path = tmp_path / "entries.db"
    cache = EntryCache(path)
    assert cache.stats() == {"count": 0, "path": str(path), "last_poll_at": None}
    cache.upsert(ENTRY)
    cache.set_last_poll_at("2026-10-20T00:00:00+00:00")
    assert cache.stats() == {
        "count": 1,
        "path": str(path),
        "last_poll_at": "2026-10-20T00:00:00+00:00",
    }
    cache.set_last_poll_at()
    assert cache.stats()["last_poll_at"] is not None
    cache.close()


def test_default_cache_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FEEDBIN_CACHE_PATH", str(tmp_path / "custom.db"))
    assert default_cache_path() == tmp_path / "custom.db"
    monkeypatch.delenv("FEEDBIN_CACHE_PATH")
    assert default_cache_path() == DEFAULT_CACHE_PATH
