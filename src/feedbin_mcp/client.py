from __future__ import annotations

from typing import Any

import httpx

from feedbin_mcp.cache import EntryCache

DEFAULT_BASE_URL = "https://api.feedbin.com"
DEFAULT_TIMEOUT = 30.0
ENTRY_IDS_MAX = 100

_SUCCESS_STATUSES = {200, 201, 204, 300, 302}
_STATUS_MESSAGES = {
    401: "Invalid Feedbin credentials (401)",
    403: "Forbidden: you do not own this resource (403)",
    404: "Not found (404)",
    429: "Rate limited by Feedbin (429)",
}


class FeedbinError(Exception):
    def __init__(self, status_code: int, message: str, body: Any = None) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(message)


class FeedbinClient:
    """Thin httpx wrapper around the Feedbin v2 JSON API."""

    def __init__(
        self,
        email: str,
        password: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
        cache: EntryCache | None = None,
    ) -> None:
        if not email or not password:
            raise FeedbinError(0, "FEEDBIN_EMAIL and FEEDBIN_PASSWORD must be set")
        self._cache = cache
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            auth=(email, password),
            headers={"Accept": "application/json"},
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()
        if self._cache is not None:
            self._cache.close()

    @property
    def cache(self) -> EntryCache | None:
        return self._cache

    def __enter__(self) -> FeedbinClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _drop_none(self, params: dict[str, Any] | None) -> dict[str, Any] | None:
        if not params:
            return None
        out = {key: value for key, value in params.items() if value is not None}
        return out or None

    def _format_ids(self, ids: list[int] | str | None) -> str | None:
        if ids is None:
            return None
        if isinstance(ids, str):
            return ids
        return ",".join(str(item) for item in ids)

    def _parse_ids(self, ids: list[int] | str | None) -> list[int] | None:
        if ids is None:
            return None
        if isinstance(ids, str):
            parts = [part.strip() for part in ids.split(",") if part.strip()]
            return [int(part) for part in parts]
        return [int(item) for item in ids]

    def _unique_ids(self, ids: list[Any]) -> list[int]:
        seen: set[int] = set()
        out: list[int] = []
        for item in ids:
            value = int(item)
            if value not in seen:
                seen.add(value)
                out.append(value)
        return out

    def _remember_entries(self, result: Any) -> None:
        if self._cache is None:
            return
        if isinstance(result, dict) and result.get("id") is not None:
            self._cache.upsert(result)
        elif isinstance(result, list):
            self._cache.upsert_many(result)

    def _fetch_entries_by_ids(self, ids: list[int], **kwargs: Any) -> list[Any]:
        extra = dict(kwargs)
        extra.pop("ids", None)
        fetched: list[Any] = []
        for start in range(0, len(ids), ENTRY_IDS_MAX):
            batch = ids[start : start + ENTRY_IDS_MAX]
            result = self.request(
                "GET",
                "/v2/entries.json",
                params=self._entry_params(**extra, ids=batch),
            )
            self._remember_entries(result)
            if isinstance(result, list):
                fetched.extend(result)
        return fetched

    def _entries_by_ids(self, ids: list[int], **kwargs: Any) -> list[Any]:
        have = self._cache.get_many(ids) if self._cache is not None else {}
        missing = [entry_id for entry_id in ids if entry_id not in have]
        fetched = self._fetch_entries_by_ids(missing, **kwargs) if missing else []
        if self._cache is None:
            return fetched
        fetched_map = {
            int(item["id"]): item
            for item in fetched
            if isinstance(item, dict) and item.get("id") is not None
        }
        out: list[Any] = []
        for entry_id in ids:
            if entry_id in have:
                out.append(have[entry_id])
            elif entry_id in fetched_map:
                out.append(fetched_map[entry_id])
        return out

    def _require_cache(self) -> EntryCache:
        if self._cache is None:
            raise FeedbinError(0, "Entry cache is not configured")
        return self._cache

    def _parse_body(self, response: httpx.Response) -> Any:
        if not response.content:
            return None
        try:
            return response.json()
        except Exception:
            return response.text

    def _raise_for_status(self, response: httpx.Response) -> None:
        status = response.status_code
        if status in _SUCCESS_STATUSES:
            return
        body = self._parse_body(response)
        if status in _STATUS_MESSAGES:
            raise FeedbinError(status, _STATUS_MESSAGES[status], body)
        if status >= 500:
            raise FeedbinError(status, f"Feedbin server error ({status})", body)
        raise FeedbinError(status, f"Feedbin request failed ({status})", body)

    def _parse(self, response: httpx.Response) -> Any:
        self._raise_for_status(response)
        if response.status_code == 204 or not response.content:
            return {"ok": True, "status_code": response.status_code}
        return self._parse_body(response)

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        content: bytes | str | None = None,
        headers: dict[str, str] | None = None,
        url: str | None = None,
    ) -> Any:
        hdrs = dict(headers or {})
        kwargs: dict[str, Any] = {"params": self._drop_none(params), "headers": hdrs}
        if json is not None:
            hdrs.setdefault("Content-Type", "application/json; charset=utf-8")
            kwargs["json"] = json
        if content is not None:
            kwargs["content"] = content
        target = url if url is not None else path
        return self._parse(self._client.request(method, target, **kwargs))

    def check_auth(self) -> dict[str, Any]:
        result = self.request("GET", "/v2/authentication.json")
        if isinstance(result, dict) and result.get("ok") is True:
            return {"ok": True, "status_code": result.get("status_code", 200)}
        return {"ok": True, "status_code": 200}

    def list_subscriptions(self, *, since: str | None = None, mode: str | None = None) -> Any:
        return self.request("GET", "/v2/subscriptions.json", params={"since": since, "mode": mode})

    def get_subscription(self, subscription_id: int) -> Any:
        return self.request("GET", f"/v2/subscriptions/{subscription_id}.json")

    def create_subscription(self, feed_url: str) -> Any:
        return self.request("POST", "/v2/subscriptions.json", json={"feed_url": feed_url})

    def update_subscription(self, subscription_id: int, title: str) -> Any:
        return self.request(
            "PATCH",
            f"/v2/subscriptions/{subscription_id}.json",
            json={"title": title},
        )

    def delete_subscription(self, subscription_id: int) -> Any:
        return self.request("DELETE", f"/v2/subscriptions/{subscription_id}.json")

    def get_feed(self, feed_id: int) -> Any:
        return self.request("GET", f"/v2/feeds/{feed_id}.json")

    def _entry_params(
        self,
        *,
        page: int | None = None,
        since: str | None = None,
        ids: list[int] | str | None = None,
        read: bool | None = None,
        starred: bool | None = None,
        per_page: int | None = None,
        mode: str | None = None,
        include_original: bool | None = None,
        include_enclosure: bool | None = None,
        include_content_diff: bool | None = None,
        include_ids: bool = True,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "page": page,
            "since": since,
            "read": read,
            "starred": starred,
            "per_page": per_page,
            "mode": mode,
            "include_original": include_original,
            "include_enclosure": include_enclosure,
            "include_content_diff": include_content_diff,
        }
        if include_ids:
            params["ids"] = self._format_ids(ids)
        return params

    def list_entries(self, **kwargs: Any) -> Any:
        parsed = self._parse_ids(kwargs.pop("ids", None))
        if parsed:
            return self._entries_by_ids(parsed, **kwargs)
        result = self.request("GET", "/v2/entries.json", params=self._entry_params(**kwargs))
        self._remember_entries(result)
        return result

    def get_entry(self, entry_id: int, **kwargs: Any) -> Any:
        kwargs.pop("ids", None)
        force_refresh = bool(kwargs.pop("force_refresh", False))
        if not force_refresh and self._cache is not None:
            cached = self._cache.get(entry_id)
            if cached is not None:
                return cached
        result = self.request(
            "GET",
            f"/v2/entries/{entry_id}.json",
            params=self._entry_params(include_ids=False, **kwargs),
        )
        self._remember_entries(result)
        return result

    def list_feed_entries(self, feed_id: int, **kwargs: Any) -> Any:
        kwargs.pop("ids", None)
        result = self.request(
            "GET",
            f"/v2/feeds/{feed_id}/entries.json",
            params=self._entry_params(include_ids=False, **kwargs),
        )
        self._remember_entries(result)
        return result

    def poll_entries(self) -> dict[str, Any]:
        unread_raw = self.list_unread()
        unread = self._unique_ids(unread_raw if isinstance(unread_raw, list) else [])
        missing = self._cache.missing_ids(unread) if self._cache is not None else unread
        fetched_ids: list[int] = []
        if missing:
            fetched = self._fetch_entries_by_ids(missing)
            present = {
                int(item["id"])
                for item in fetched
                if isinstance(item, dict) and item.get("id") is not None
            }
            fetched_ids = [entry_id for entry_id in missing if entry_id in present]
        if self._cache is not None:
            self._cache.set_last_poll_at()
        return {
            "unread_count": len(unread),
            "fetched": len(fetched_ids),
            "already_cached": len(unread) - len(missing),
            "ids": fetched_ids,
        }

    def cached_entry(self, entry_id: int) -> Any:
        entry = self._require_cache().get(entry_id)
        if entry is None:
            raise FeedbinError(404, f"Entry {entry_id} is not in the local cache")
        return entry

    def list_cached_entries(
        self,
        *,
        feed_id: int | None = None,
        limit: int = 50,
        search: str | None = None,
    ) -> Any:
        return self._require_cache().list_entries(feed_id=feed_id, limit=limit, search=search)

    def cache_stats(self) -> Any:
        return self._require_cache().stats()

    def list_unread(self) -> Any:
        return self.request("GET", "/v2/unread_entries.json")

    def mark_unread(self, entry_ids: list[int]) -> Any:
        return self.request("POST", "/v2/unread_entries.json", json={"unread_entries": entry_ids})

    def mark_read(self, entry_ids: list[int]) -> Any:
        return self.request("DELETE", "/v2/unread_entries.json", json={"unread_entries": entry_ids})

    def list_starred(self) -> Any:
        return self.request("GET", "/v2/starred_entries.json")

    def star_entries(self, entry_ids: list[int]) -> Any:
        return self.request("POST", "/v2/starred_entries.json", json={"starred_entries": entry_ids})

    def unstar_entries(self, entry_ids: list[int]) -> Any:
        return self.request("DELETE", "/v2/starred_entries.json", json={"starred_entries": entry_ids})

    def list_recently_read(self) -> Any:
        return self.request("GET", "/v2/recently_read_entries.json")

    def add_recently_read(self, entry_ids: list[int]) -> Any:
        return self.request(
            "POST",
            "/v2/recently_read_entries.json",
            json={"recently_read_entries": entry_ids},
        )

    def list_updated_entries(self, *, since: str | None = None) -> Any:
        return self.request("GET", "/v2/updated_entries.json", params={"since": since})

    def delete_updated_entries(self, entry_ids: list[int]) -> Any:
        return self.request(
            "DELETE",
            "/v2/updated_entries.json",
            json={"updated_entries": entry_ids},
        )

    def list_taggings(self) -> Any:
        return self.request("GET", "/v2/taggings.json")

    def get_tagging(self, tagging_id: int) -> Any:
        return self.request("GET", f"/v2/taggings/{tagging_id}.json")

    def create_tagging(self, feed_id: int, name: str) -> Any:
        return self.request("POST", "/v2/taggings.json", json={"feed_id": feed_id, "name": name})

    def delete_tagging(self, tagging_id: int) -> Any:
        return self.request("DELETE", f"/v2/taggings/{tagging_id}.json")

    def rename_tag(self, old_name: str, new_name: str) -> Any:
        return self.request("POST", "/v2/tags.json", json={"old_name": old_name, "new_name": new_name})

    def delete_tag(self, name: str) -> Any:
        return self.request("DELETE", "/v2/tags.json", json={"name": name})

    def list_saved_searches(self) -> Any:
        return self.request("GET", "/v2/saved_searches.json")

    def get_saved_search(
        self,
        search_id: int,
        *,
        include_entries: bool | None = None,
        page: int | None = None,
    ) -> Any:
        return self.request(
            "GET",
            f"/v2/saved_searches/{search_id}.json",
            params={"include_entries": include_entries, "page": page},
        )

    def create_saved_search(self, name: str, query: str) -> Any:
        return self.request("POST", "/v2/saved_searches.json", json={"name": name, "query": query})

    def update_saved_search(
        self,
        search_id: int,
        *,
        name: str | None = None,
        query: str | None = None,
    ) -> Any:
        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if query is not None:
            body["query"] = query
        return self.request("PATCH", f"/v2/saved_searches/{search_id}.json", json=body)

    def delete_saved_search(self, search_id: int) -> Any:
        return self.request("DELETE", f"/v2/saved_searches/{search_id}.json")

    def save_page(self, url: str, title: str | None = None) -> Any:
        body: dict[str, Any] = {"url": url}
        if title is not None:
            body["title"] = title
        return self.request("POST", "/v2/pages.json", json=body)

    def delete_page(self, page_id: int) -> Any:
        return self.request("DELETE", f"/v2/pages/{page_id}.json")

    def extract_content(self, entry_id: int) -> Any:
        entry = self.get_entry(entry_id)
        extracted_url = entry.get("extracted_content_url") if isinstance(entry, dict) else None
        if not extracted_url:
            raise FeedbinError(0, f"Entry {entry_id} has no extracted_content_url")
        return self.request("GET", "", url=extracted_url)

    def list_icons(self) -> Any:
        return self.request("GET", "/v2/icons.json")

    def list_imports(self) -> Any:
        return self.request("GET", "/v2/imports.json")

    def create_import(self, opml_xml: str) -> Any:
        return self.request(
            "POST",
            "/v2/imports.json",
            content=opml_xml,
            headers={"Content-Type": "text/xml"},
        )

    def get_import(self, import_id: int) -> Any:
        return self.request("GET", f"/v2/imports/{import_id}.json")
