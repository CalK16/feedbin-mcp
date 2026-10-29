from __future__ import annotations

import base64
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from feedbin_mcp.cache import EntryCache
from feedbin_mcp.client import FeedbinClient, FeedbinError

EMAIL = "user@example.com"
PASSWORD = "secret"
BASE = "https://api.feedbin.com"


def make_client(
    handler: Callable[[httpx.Request], httpx.Response],
    cache: EntryCache | None = None,
) -> FeedbinClient:
    return FeedbinClient(
        EMAIL,
        PASSWORD,
        base_url=BASE,
        transport=httpx.MockTransport(handler),
        cache=cache,
    )


def json_handler(
    status: int,
    body: Any,
    capture: list[httpx.Request],
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        capture.append(request)
        if body is None:
            return httpx.Response(status)
        return httpx.Response(status, json=body)

    return handler


def basic_auth(request: httpx.Request) -> str:
    header = request.headers["Authorization"]
    scheme, encoded = header.split(" ", 1)
    assert scheme == "Basic"
    return base64.b64decode(encoded).decode()


def test_missing_credentials_raise() -> None:
    with pytest.raises(FeedbinError, match="FEEDBIN_EMAIL and FEEDBIN_PASSWORD"):
        FeedbinClient("", "secret")
    with pytest.raises(FeedbinError, match="FEEDBIN_EMAIL and FEEDBIN_PASSWORD"):
        FeedbinClient("user@example.com", "")


def test_list_subscriptions_sets_basic_auth() -> None:
    capture: list[httpx.Request] = []
    payload = [
        {
            "id": 525,
            "feed_id": 47,
            "title": "Daring Fireball",
            "feed_url": "http://daringfireball.net/index.xml",
            "site_url": "http://daringfireball.net/",
        }
    ]
    client = make_client(json_handler(200, payload, capture))
    result = client.list_subscriptions()
    assert result == payload
    request = capture[0]
    assert request.method == "GET"
    assert request.url.path == "/v2/subscriptions.json"
    assert basic_auth(request) == f"{EMAIL}:{PASSWORD}"
    assert request.headers["Accept"] == "application/json"


def test_list_subscriptions_passes_since() -> None:
    capture: list[httpx.Request] = []
    client = make_client(json_handler(200, [], capture))
    client.list_subscriptions(since="2013-03-08T09:44:20.449047Z", mode="extended")
    assert capture[0].url.params["since"] == "2013-03-08T09:44:20.449047Z"
    assert capture[0].url.params["mode"] == "extended"


def test_list_entries_path_and_filters() -> None:
    capture: list[httpx.Request] = []
    entries = [
        {
            "id": 2077,
            "feed_id": 135,
            "title": "Objective-C Runtime Releases",
            "url": "http://mjtsai.com/blog/",
            "content": "<p>hello</p>",
            "published": "2013-02-03T01:00:19.000000Z",
        }
    ]
    client = make_client(json_handler(200, entries, capture))
    result = client.list_entries(page=2, per_page=50, ids=[1, 2, 3], read=False)
    assert result == entries
    request = capture[0]
    assert request.method == "GET"
    assert request.url.path == "/v2/entries.json"
    assert request.url.params["page"] == "2"
    assert request.url.params["per_page"] == "50"
    assert request.url.params["ids"] == "1,2,3"
    assert request.url.params["read"] == "false"


def test_get_entry_and_list_feed_entries() -> None:
    capture: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        capture.append(request)
        return httpx.Response(200, json={"id": 3648, "content": "<p>full</p>"})

    client = make_client(handler)
    entry = client.get_entry(3648)
    feed_entries = client.list_feed_entries(203, page=1)
    assert entry["id"] == 3648
    assert capture[0].url.path == "/v2/entries/3648.json"
    assert capture[1].url.path == "/v2/feeds/203/entries.json"
    assert capture[1].url.params["page"] == "1"


@pytest.mark.parametrize(
    ("status", "match"),
    [
        (401, "Invalid Feedbin credentials"),
        (403, "Forbidden"),
        (404, "Not found"),
        (429, "Rate limited"),
        (500, "Feedbin server error"),
        (503, "Feedbin server error"),
    ],
)
def test_error_mapping(status: int, match: str) -> None:
    client = make_client(json_handler(status, {"error": "nope"}, []))
    with pytest.raises(FeedbinError, match=match) as exc:
        client.list_subscriptions()
    assert exc.value.status_code == status


def test_check_auth_empty_body() -> None:
    client = make_client(json_handler(200, None, []))
    assert client.check_auth()["ok"] is True


def test_create_subscription_json_body() -> None:
    capture: list[httpx.Request] = []
    client = make_client(json_handler(201, {"id": 1, "title": "DF"}, capture))
    result = client.create_subscription("http://daringfireball.net/index.xml")
    assert result["id"] == 1
    request = capture[0]
    assert request.method == "POST"
    assert request.url.path == "/v2/subscriptions.json"
    assert request.headers["Content-Type"].startswith("application/json")
    assert request.content == b'{"feed_url":"http://daringfireball.net/index.xml"}'


def test_create_subscription_multiple_choices() -> None:
    choices = [{"feed_url": "https://github.com/blog.atom", "title": "The GitHub Blog"}]
    client = make_client(json_handler(300, choices, []))
    assert client.create_subscription("https://blog.github.com") == choices


def test_update_and_delete_subscription() -> None:
    capture: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        capture.append(request)
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(200, json={"id": 525, "title": "Custom Title"})

    client = make_client(handler)
    updated = client.update_subscription(525, "Custom Title")
    deleted = client.delete_subscription(525)
    assert updated["title"] == "Custom Title"
    assert deleted["ok"] is True
    assert capture[0].method == "PATCH"
    assert capture[0].url.path == "/v2/subscriptions/525.json"
    assert capture[1].method == "DELETE"
    assert capture[1].url.path == "/v2/subscriptions/525.json"


def test_unread_starred_recent_updated() -> None:
    capture: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        capture.append(request)
        return httpx.Response(200, json=[4089, 4090])

    client = make_client(handler)
    assert client.list_unread() == [4089, 4090]
    assert client.mark_unread([4089]) == [4089, 4090]
    assert client.mark_read([4089]) == [4089, 4090]
    assert client.list_starred() == [4089, 4090]
    assert client.star_entries([4089]) == [4089, 4090]
    assert client.unstar_entries([4089]) == [4089, 4090]
    assert client.list_recently_read() == [4089, 4090]
    assert client.add_recently_read([4089]) == [4089, 4090]
    assert client.list_updated_entries(since="2013-02-02T14:07:33.000000Z") == [4089, 4090]
    assert client.delete_updated_entries([4089]) == [4089, 4090]

    paths = [(r.method, r.url.path) for r in capture]
    assert paths == [
        ("GET", "/v2/unread_entries.json"),
        ("POST", "/v2/unread_entries.json"),
        ("DELETE", "/v2/unread_entries.json"),
        ("GET", "/v2/starred_entries.json"),
        ("POST", "/v2/starred_entries.json"),
        ("DELETE", "/v2/starred_entries.json"),
        ("GET", "/v2/recently_read_entries.json"),
        ("POST", "/v2/recently_read_entries.json"),
        ("GET", "/v2/updated_entries.json"),
        ("DELETE", "/v2/updated_entries.json"),
    ]
    assert b"unread_entries" in capture[2].content
    assert b"starred_entries" in capture[5].content
    assert capture[8].url.params["since"] == "2013-02-02T14:07:33.000000Z"


def test_taggings_tags_saved_searches() -> None:
    capture: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        capture.append(request)
        if request.method == "DELETE" and request.url.path.endswith("1.json"):
            return httpx.Response(204)
        if request.url.path == "/v2/saved_searches/1.json" and request.method == "GET":
            return httpx.Response(200, json=[2058, 1])
        return httpx.Response(200, json=[{"id": 4, "feed_id": 1, "name": "Tech"}])

    client = make_client(handler)
    client.list_taggings()
    client.get_tagging(4)
    client.create_tagging(1, "Design")
    client.delete_tagging(4)
    client.rename_tag("Old", "New")
    client.delete_tag("Tag Name")
    client.list_saved_searches()
    assert client.get_saved_search(1) == [2058, 1]
    client.create_saved_search("JavaScript", "javascript is:unread")
    client.update_saved_search(1, name="Unread JavaScript")
    client.delete_saved_search(1)

    paths = [(r.method, r.url.path) for r in capture]
    assert ("GET", "/v2/taggings.json") in paths
    assert ("GET", "/v2/taggings/4.json") in paths
    assert ("POST", "/v2/taggings.json") in paths
    assert ("DELETE", "/v2/taggings/4.json") in paths
    assert ("POST", "/v2/tags.json") in paths
    assert ("DELETE", "/v2/tags.json") in paths
    assert ("GET", "/v2/saved_searches.json") in paths
    assert ("GET", "/v2/saved_searches/1.json") in paths
    assert ("POST", "/v2/saved_searches.json") in paths
    assert ("PATCH", "/v2/saved_searches/1.json") in paths
    assert ("DELETE", "/v2/saved_searches/1.json") in paths


def test_pages_icons_imports_feed() -> None:
    capture: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        capture.append(request)
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(200, json={"id": 6})

    client = make_client(handler)
    client.get_feed(1)
    client.save_page("https://example.com", title="Hello")
    client.delete_page(3)
    client.list_icons()
    client.list_imports()
    client.create_import("<opml></opml>")
    client.get_import(1)

    paths = [(r.method, r.url.path) for r in capture]
    assert paths == [
        ("GET", "/v2/feeds/1.json"),
        ("POST", "/v2/pages.json"),
        ("DELETE", "/v2/pages/3.json"),
        ("GET", "/v2/icons.json"),
        ("GET", "/v2/imports.json"),
        ("POST", "/v2/imports.json"),
        ("GET", "/v2/imports/1.json"),
    ]
    assert capture[5].headers["Content-Type"] == "text/xml"
    assert capture[5].content == b"<opml></opml>"


def test_extract_content_follows_entry_url() -> None:
    capture: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        capture.append(request)
        if request.url.path == "/v2/entries/109.json":
            return httpx.Response(
                200,
                json={
                    "id": 109,
                    "extracted_content_url": "https://extract.feedbin.com/parser/feedbin/abc?base64_url=xyz",
                },
            )
        return httpx.Response(200, json={"title": "Private by Default", "content": "<p>full</p>"})

    client = make_client(handler)
    extracted = client.extract_content(109)
    assert extracted["title"] == "Private by Default"
    assert capture[0].url.path == "/v2/entries/109.json"
    assert capture[1].url.host == "extract.feedbin.com"


def test_extract_content_missing_url() -> None:
    client = make_client(json_handler(200, {"id": 1}, []))
    with pytest.raises(FeedbinError, match="extracted_content_url"):
        client.extract_content(1)


def test_get_subscription() -> None:
    capture: list[httpx.Request] = []
    client = make_client(json_handler(200, {"id": 525}, capture))
    assert client.get_subscription(525)["id"] == 525
    assert capture[0].url.path == "/v2/subscriptions/525.json"


def test_context_manager_and_id_formats() -> None:
    capture: list[httpx.Request] = []
    with make_client(json_handler(200, [], capture)) as client:
        client.list_entries()
        client.list_entries(ids="8,9")
    assert "ids" not in capture[0].url.params
    assert capture[1].url.params["ids"] == "8,9"


def test_generic_client_errors() -> None:
    client = make_client(json_handler(415, "unsupported", []))
    with pytest.raises(FeedbinError, match="Feedbin request failed \\(415\\)") as text_exc:
        client.create_subscription("http://x")
    assert text_exc.value.status_code == 415

    def empty_404(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    with pytest.raises(FeedbinError, match="Not found") as empty_exc:
        make_client(empty_404).get_feed(1)
    assert empty_exc.value.body is None

    def garbage_500(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"not-json")

    with pytest.raises(FeedbinError) as garbage_exc:
        make_client(garbage_500).list_subscriptions()
    assert garbage_exc.value.body == "not-json"


def test_check_auth_with_json_payload() -> None:
    client = make_client(json_handler(200, {"detail": "ok"}, []))
    assert client.check_auth() == {"ok": True, "status_code": 200}


def test_update_saved_search_query() -> None:
    capture: list[httpx.Request] = []
    client = make_client(json_handler(200, {"id": 1}, capture))
    client.update_saved_search(1, query="javascript is:unread")
    assert b"javascript is:unread" in capture[0].content


def test_get_entry_uses_cache_on_second_call(tmp_path: Path) -> None:
    capture: list[httpx.Request] = []
    payload = {"id": 5, "feed_id": 1, "title": "Cached", "content": "<p>full</p>"}
    cache = EntryCache(tmp_path / "entries.db")
    client = make_client(json_handler(200, payload, capture), cache=cache)
    first = client.get_entry(5)
    second = client.get_entry(5)
    assert first == payload
    assert second == payload
    assert len(capture) == 1
    assert cache.get(5) == payload
    client.close()


def test_get_entry_force_refresh_hits_api(tmp_path: Path) -> None:
    capture: list[httpx.Request] = []
    payload = {"id": 5, "feed_id": 1, "title": "Cached", "content": "<p>full</p>"}
    cache = EntryCache(tmp_path / "entries.db")
    client = make_client(json_handler(200, payload, capture), cache=cache)
    client.get_entry(5)
    refreshed = client.get_entry(5, force_refresh=True)
    assert refreshed == payload
    assert len(capture) == 2
    client.close()


def test_poll_entries_fetches_only_missing(tmp_path: Path) -> None:
    capture: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        capture.append(request)
        if request.url.path == "/v2/unread_entries.json":
            return httpx.Response(200, json=[1, 2, 3])
        if request.url.path == "/v2/entries.json":
            ids = [int(item) for item in request.url.params["ids"].split(",")]
            return httpx.Response(
                200,
                json=[
                    {"id": entry_id, "feed_id": 1, "title": f"E{entry_id}", "content": f"<p>{entry_id}</p>"}
                    for entry_id in ids
                ],
            )
        return httpx.Response(500, json={"error": request.url.path})

    cache = EntryCache(tmp_path / "entries.db")
    cache.upsert({"id": 1, "feed_id": 1, "title": "already", "content": "<p>1</p>"})
    client = make_client(handler, cache=cache)
    result = client.poll_entries()
    assert result["unread_count"] == 3
    assert result["fetched"] == 2
    assert result["already_cached"] == 1
    assert result["ids"] == [2, 3]
    assert "content" not in result
    entry_gets = [req for req in capture if req.url.path == "/v2/entries.json"]
    assert len(entry_gets) == 1
    assert entry_gets[0].url.params["ids"] == "2,3"
    assert cache.get(2)["title"] == "E2"
    client.close()


def test_list_entries_ids_uses_cache_for_stored(tmp_path: Path) -> None:
    capture: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        capture.append(request)
        return httpx.Response(200, json=[{"id": 2, "title": "fresh", "content": "b"}])

    cache = EntryCache(tmp_path / "entries.db")
    cache.upsert({"id": 1, "title": "cached", "content": "a" * 600})
    client = make_client(handler, cache=cache)
    result = client.list_entries(ids=[1, 2])
    assert [row["id"] for row in result] == [1, 2]
    assert result[0]["content"] == "a" * 600
    assert capture[0].url.params["ids"] == "2"
    client.close()


def test_list_entries_ids_all_cached_skips_http(tmp_path: Path) -> None:
    capture: list[httpx.Request] = []
    cache = EntryCache(tmp_path / "entries.db")
    cache.upsert_many(
        [
            {"id": 1, "title": "one", "content": "a"},
            {"id": 2, "title": "two", "content": "b"},
        ]
    )
    client = make_client(json_handler(200, [], capture), cache=cache)
    result = client.list_entries(ids=[1, 2])
    assert [row["id"] for row in result] == [1, 2]
    assert capture == []
    client.close()


def test_list_feed_entries_caches(tmp_path: Path) -> None:
    payload = [{"id": 8, "feed_id": 203, "title": "feed", "content": "z"}]
    cache = EntryCache(tmp_path / "entries.db")
    client = make_client(json_handler(200, payload, []), cache=cache)
    assert client.list_feed_entries(203) == payload
    assert cache.get(8) == payload[0]
    client.close()


def test_cached_entry_list_and_stats(tmp_path: Path) -> None:
    cache = EntryCache(tmp_path / "entries.db")
    cache.upsert({"id": 1, "feed_id": 10, "title": "Hello", "content": "full"})
    client = make_client(json_handler(200, [], []), cache=cache)
    assert client.cached_entry(1)["content"] == "full"
    with pytest.raises(FeedbinError, match="not in the local cache"):
        client.cached_entry(99)
    listed = client.list_cached_entries(feed_id=10, limit=5, search="hel")
    assert listed[0]["id"] == 1
    stats = client.cache_stats()
    assert stats["count"] == 1
    assert stats["path"] == str(tmp_path / "entries.db")
    client.close()


def test_cache_methods_require_cache() -> None:
    client = make_client(json_handler(200, [], []))
    with pytest.raises(FeedbinError, match="Entry cache is not configured"):
        client.cached_entry(1)
    with pytest.raises(FeedbinError, match="Entry cache is not configured"):
        client.list_cached_entries()
    with pytest.raises(FeedbinError, match="Entry cache is not configured"):
        client.cache_stats()


def test_poll_all_cached_skips_entry_fetch(tmp_path: Path) -> None:
    capture: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        capture.append(request)
        if request.url.path == "/v2/unread_entries.json":
            return httpx.Response(200, json=[1])
        return httpx.Response(500)

    cache = EntryCache(tmp_path / "entries.db")
    cache.upsert({"id": 1, "title": "have"})
    client = make_client(handler, cache=cache)
    result = client.poll_entries()
    assert result["fetched"] == 0
    assert result["already_cached"] == 1
    assert result["ids"] == []
    assert [req.url.path for req in capture] == ["/v2/unread_entries.json"]
    client.close()


def test_poll_batches_ids(tmp_path: Path) -> None:
    capture: list[httpx.Request] = []
    unread = list(range(1, 102))

    def handler(request: httpx.Request) -> httpx.Response:
        capture.append(request)
        if request.url.path == "/v2/unread_entries.json":
            return httpx.Response(200, json=unread)
        ids = [int(item) for item in request.url.params["ids"].split(",")]
        return httpx.Response(200, json=[{"id": entry_id, "title": str(entry_id)} for entry_id in ids])

    client = make_client(handler, cache=EntryCache(tmp_path / "entries.db"))
    result = client.poll_entries()
    assert result["fetched"] == 101
    entry_gets = [req for req in capture if req.url.path == "/v2/entries.json"]
    assert len(entry_gets) == 2
    assert len(entry_gets[0].url.params["ids"].split(",")) == 100
    assert len(entry_gets[1].url.params["ids"].split(",")) == 1
    client.close()


def test_poll_non_list_unread_is_empty() -> None:
    client = make_client(json_handler(204, None, []))
    result = client.poll_entries()
    assert result == {"unread_count": 0, "fetched": 0, "already_cached": 0, "ids": []}


def test_poll_without_cache_fetches_all() -> None:
    capture: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        capture.append(request)
        if request.url.path == "/v2/unread_entries.json":
            return httpx.Response(200, json=[4, 5])
        return httpx.Response(200, json=[{"id": 4}, {"id": 5}])

    client = make_client(handler)
    result = client.poll_entries()
    assert result["already_cached"] == 0
    assert result["fetched"] == 2
    assert result["ids"] == [4, 5]


def test_list_entries_without_ids_caches_live_index(tmp_path: Path) -> None:
    capture: list[httpx.Request] = []
    payload = [{"id": 9, "title": "live", "content": "c"}]
    cache = EntryCache(tmp_path / "entries.db")
    client = make_client(json_handler(200, payload, capture), cache=cache)
    result = client.list_entries(since="2013-01-01T00:00:00Z", page=1)
    assert result == payload
    assert cache.get(9) == payload[0]
    assert capture[0].url.path == "/v2/entries.json"
    assert "ids" not in capture[0].url.params
    client.close()
