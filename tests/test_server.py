from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import feedbin_mcp.server as srv
from feedbin_mcp.client import FeedbinClient, FeedbinError
from feedbin_mcp.server import (
    CONTENT_LIMIT,
    feedbin_get_entry,
    feedbin_list_entries,
    get_client,
    mcp,
    summarize_entries,
    transport_settings,
    truncate_value,
)


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def list_entries(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("list_entries", (), kwargs))
        return [
            {
                "id": 1,
                "title": "Hello",
                "url": "https://example.com",
                "published": "2013-02-03T01:00:19.000000Z",
                "content": "x" * 800,
                "summary": "y" * 600,
            }
        ]

    def get_entry(self, entry_id: int, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("get_entry", (entry_id,), kwargs))
        return {"id": entry_id, "content": "x" * 800, "title": "Full"}


class RecordingClient:
    def __getattr__(self, name: str) -> Any:
        def method(*args: Any, **kwargs: Any) -> Any:
            if name in {"list_entries", "list_feed_entries"}:
                return [{"id": 1, "content": "ok", "title": "T"}]
            if name == "get_saved_search":
                if kwargs.get("include_entries"):
                    return [{"id": 1, "content": "c" * 600, "title": "S"}]
                return [2058, 1]
            if name == "check_auth":
                return {"ok": True, "status_code": 200}
            return {"ok": True, "name": name, "args": args, "kwargs": kwargs}

        return method


class BoomClient:
    def list_unread(self) -> Any:
        raise FeedbinError(401, "Invalid Feedbin credentials (401)", {"error": "nope"})


def test_summarize_entries_truncates_content() -> None:
    entries = [{"id": 1, "content": "a" * 700, "title": "T", "url": "u", "published": "p"}]
    summarized = summarize_entries(entries)
    assert summarized[0]["id"] == 1
    assert summarized[0]["title"] == "T"
    assert summarized[0]["url"] == "u"
    assert summarized[0]["published"] == "p"
    assert len(summarized[0]["content"]) == CONTENT_LIMIT + 1
    assert summarized[0]["content"].endswith("…")


def test_summarize_entries_full_keeps_content() -> None:
    entries = [{"id": 1, "content": "a" * 700}]
    assert summarize_entries(entries, full=True)[0]["content"] == "a" * 700


def test_summarize_passthrough_and_dict() -> None:
    assert summarize_entries(123) == 123
    assert truncate_value(None) is None
    summarized = summarize_entries({"content": "z" * 700})
    assert summarized["content"].endswith("…")


def test_list_entries_tool_truncates(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeClient()
    monkeypatch.setattr(srv, "get_client", lambda: fake)
    result = feedbin_list_entries()
    assert result[0]["id"] == 1
    assert result[0]["title"] == "Hello"
    assert len(result[0]["content"]) == CONTENT_LIMIT + 1
    assert len(result[0]["summary"]) == CONTENT_LIMIT + 1


def test_get_entry_tool_returns_full_content(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeClient()
    monkeypatch.setattr(srv, "get_client", lambda: fake)
    result = feedbin_get_entry(42)
    assert result["content"] == "x" * 800


def test_mcp_import() -> None:
    assert mcp.name == "feedbin"
    assert get_client.__name__ == "get_client"


def test_tool_error_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(srv, "get_client", lambda: BoomClient())
    result = srv.feedbin_list_unread()
    assert result["error"] == "Invalid Feedbin credentials (401)"
    assert result["status_code"] == 401


def test_get_client_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FEEDBIN_EMAIL", "a@b.com")
    monkeypatch.setenv("FEEDBIN_PASSWORD", "pw")
    monkeypatch.setenv("FEEDBIN_BASE_URL", "https://example.test")
    monkeypatch.setenv("FEEDBIN_CACHE_PATH", str(tmp_path / "entries.db"))
    srv._client = None
    try:
        first = srv.get_client()
        second = srv.get_client()
        assert isinstance(first, FeedbinClient)
        assert first is second
        assert first.cache is not None
        assert first.cache.path == tmp_path / "entries.db"
    finally:
        if srv._client is not None:
            srv._client.close()
        srv._client = None


def test_main_stdio(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, Any] = {}

    def fake_run(transport: str = "stdio", **kwargs: Any) -> None:
        called["t"] = transport
        called["kw"] = kwargs

    monkeypatch.setattr(srv.mcp, "run", fake_run)
    srv.main()
    assert called["t"] == "stdio"
    assert called["kw"] == {}


def test_transport_settings_http(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FEEDBIN_MCP_TRANSPORT", "http")
    monkeypatch.setenv("FEEDBIN_MCP_HOST", "0.0.0.0")
    monkeypatch.setenv("FEEDBIN_MCP_PORT", "9000")
    monkeypatch.setenv("FEEDBIN_MCP_PATH", "/mcp")
    transport, kwargs = transport_settings()
    assert transport == "streamable-http"
    assert kwargs == {"host": "0.0.0.0", "port": 9000, "streamable_http_path": "/mcp"}


def test_transport_settings_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FEEDBIN_MCP_TRANSPORT", "websocket")
    with pytest.raises(ValueError, match="Unknown FEEDBIN_MCP_TRANSPORT"):
        transport_settings()


def test_main_http(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, Any] = {}

    def fake_run(transport: str = "stdio", **kwargs: Any) -> None:
        called["t"] = transport
        called["kw"] = kwargs

    monkeypatch.setenv("FEEDBIN_MCP_TRANSPORT", "streamable-http")
    monkeypatch.setattr(srv.mcp, "run", fake_run)
    srv.main()
    assert called["t"] == "streamable-http"
    assert called["kw"]["host"] == "127.0.0.1"
    assert called["kw"]["port"] == 8000
    assert called["kw"]["streamable_http_path"] == "/mcp"


def test_all_tools_delegate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(srv, "get_client", lambda: RecordingClient())
    assert srv.feedbin_check_auth()["ok"] is True
    assert srv.feedbin_list_subscriptions()["ok"] is True
    assert srv.feedbin_get_subscription(525)["ok"] is True
    assert srv.feedbin_create_subscription("http://example.com")["ok"] is True
    assert srv.feedbin_update_subscription(1, "Title")["ok"] is True
    assert srv.feedbin_delete_subscription(1)["ok"] is True
    assert srv.feedbin_get_feed(1)["ok"] is True
    assert srv.feedbin_list_feed_entries(203)[0]["id"] == 1
    assert srv.feedbin_list_unread()["ok"] is True
    assert srv.feedbin_mark_unread([1])["ok"] is True
    assert srv.feedbin_mark_read([1])["ok"] is True
    assert srv.feedbin_list_starred()["ok"] is True
    assert srv.feedbin_star_entries([1])["ok"] is True
    assert srv.feedbin_unstar_entries([1])["ok"] is True
    assert srv.feedbin_list_recently_read()["ok"] is True
    assert srv.feedbin_add_recently_read([1])["ok"] is True
    assert srv.feedbin_list_updated_entries()["ok"] is True
    assert srv.feedbin_delete_updated_entries([1])["ok"] is True
    assert srv.feedbin_list_taggings()["ok"] is True
    assert srv.feedbin_get_tagging(4)["ok"] is True
    assert srv.feedbin_create_tagging(1, "Tech")["ok"] is True
    assert srv.feedbin_delete_tagging(4)["ok"] is True
    assert srv.feedbin_rename_tag("Old", "New")["ok"] is True
    assert srv.feedbin_delete_tag("Tech")["ok"] is True
    assert srv.feedbin_list_saved_searches()["ok"] is True
    assert srv.feedbin_create_saved_search("JS", "javascript")["ok"] is True
    assert srv.feedbin_get_saved_search(1) == [2058, 1]
    entries = srv.feedbin_get_saved_search(1, include_entries=True)
    assert entries[0]["content"].endswith("…")
    assert srv.feedbin_update_saved_search(1, name="N")["ok"] is True
    assert srv.feedbin_delete_saved_search(1)["ok"] is True
    assert srv.feedbin_save_page("https://example.com")["ok"] is True
    assert srv.feedbin_delete_page(3)["ok"] is True
    assert srv.feedbin_extract_content(109)["ok"] is True
    assert srv.feedbin_list_icons()["ok"] is True
    assert srv.feedbin_list_imports()["ok"] is True
    assert srv.feedbin_create_import("<opml></opml>")["ok"] is True
    assert srv.feedbin_get_import(1)["ok"] is True
    assert srv.feedbin_poll_entries()["ok"] is True
    assert srv.feedbin_cached_entry(1)["ok"] is True
    assert srv.feedbin_list_cached_entries(feed_id=1, limit=10, search="T")["ok"] is True
    assert srv.feedbin_cache_stats()["ok"] is True


def test_poll_and_cached_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    class CacheAwareClient:
        def poll_entries(self) -> dict[str, Any]:
            return {"unread_count": 3, "fetched": 2, "already_cached": 1, "ids": [2, 3]}

        def cached_entry(self, entry_id: int) -> dict[str, Any]:
            return {"id": entry_id, "content": "x" * 800, "title": "Full"}

        def list_cached_entries(self, **kwargs: Any) -> list[dict[str, Any]]:
            assert kwargs == {"feed_id": 10, "limit": 5, "search": "hello"}
            return [{"id": 1, "title": "Hello", "content": "x" * 800, "summary": "y" * 600}]

        def cache_stats(self) -> dict[str, Any]:
            return {"count": 4, "path": "/tmp/entries.db", "last_poll_at": "t"}

        def get_entry(self, entry_id: int, **kwargs: Any) -> dict[str, Any]:
            return {"id": entry_id, "kwargs": kwargs}

    fake = CacheAwareClient()
    monkeypatch.setattr(srv, "get_client", lambda: fake)
    poll = srv.feedbin_poll_entries()
    assert poll == {"unread_count": 3, "fetched": 2, "already_cached": 1, "ids": [2, 3]}
    assert "content" not in poll
    assert srv.feedbin_cached_entry(9)["content"] == "x" * 800
    listed = srv.feedbin_list_cached_entries(feed_id=10, limit=5, search="hello")
    assert listed[0]["content"].endswith("…")
    assert srv.feedbin_cache_stats()["count"] == 4
    assert srv.feedbin_get_entry(9, force_refresh=True)["kwargs"]["force_refresh"] is True


def test_cached_entry_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    class MissingCacheClient:
        def cached_entry(self, entry_id: int) -> Any:
            raise FeedbinError(404, f"Entry {entry_id} is not in the local cache")

    monkeypatch.setattr(srv, "get_client", lambda: MissingCacheClient())
    result = srv.feedbin_cached_entry(99)
    assert result["status_code"] == 404
    assert "not in the local cache" in result["error"]
