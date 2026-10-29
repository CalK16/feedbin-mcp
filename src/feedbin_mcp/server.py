from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from mcp.server.mcpserver import MCPServer

from feedbin_mcp.cache import EntryCache, default_cache_path
from feedbin_mcp.client import DEFAULT_BASE_URL, FeedbinClient, FeedbinError

CONTENT_LIMIT = 500
CONTENT_KEYS = ("content", "summary")

mcp = MCPServer("feedbin")
_client: FeedbinClient | None = None


def client_from_env() -> FeedbinClient:
    return FeedbinClient(
        os.environ.get("FEEDBIN_EMAIL", ""),
        os.environ.get("FEEDBIN_PASSWORD", ""),
        base_url=os.environ.get("FEEDBIN_BASE_URL", DEFAULT_BASE_URL),
        cache=EntryCache(default_cache_path()),
    )


def get_client() -> FeedbinClient:
    global _client
    if _client is None:
        _client = client_from_env()
    return _client


def truncate_value(value: Any, limit: int = CONTENT_LIMIT) -> Any:
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + "…"
    return value


def summarize_entry(entry: dict[str, Any], *, full: bool = False) -> dict[str, Any]:
    if full:
        return entry
    out = dict(entry)
    for key in CONTENT_KEYS:
        if key in out:
            out[key] = truncate_value(out[key])
    return out


def summarize_entries(data: Any, *, full: bool = False) -> Any:
    if isinstance(data, list):
        return [
            summarize_entry(item, full=full) if isinstance(item, dict) else item for item in data
        ]
    if isinstance(data, dict):
        return summarize_entry(data, full=full)
    return data


def _call(fn: Callable[[], Any]) -> Any:
    try:
        return fn()
    except FeedbinError as exc:
        return {"error": str(exc), "status_code": exc.status_code, "body": exc.body}


@mcp.tool()
def feedbin_check_auth() -> dict[str, Any]:
    """Check Feedbin credentials with GET /v2/authentication.json."""
    return _call(lambda: get_client().check_auth())


@mcp.tool()
def feedbin_list_subscriptions(
    since: str | None = None,
    mode: str | None = None,
) -> Any:
    """List subscriptions. Optional since (ISO 8601) and mode=extended."""
    return _call(lambda: get_client().list_subscriptions(since=since, mode=mode))


@mcp.tool()
def feedbin_get_subscription(subscription_id: int) -> Any:
    """Get one subscription by id."""
    return _call(lambda: get_client().get_subscription(subscription_id))


@mcp.tool()
def feedbin_create_subscription(feed_url: str) -> Any:
    """Subscribe to a feed_url. Mutates Feedbin state. May return multiple feed choices."""
    return _call(lambda: get_client().create_subscription(feed_url))


@mcp.tool()
def feedbin_update_subscription(subscription_id: int, title: str) -> Any:
    """Set a custom subscription title. Mutates Feedbin state."""
    return _call(lambda: get_client().update_subscription(subscription_id, title))


@mcp.tool()
def feedbin_delete_subscription(subscription_id: int) -> Any:
    """Unsubscribe. Mutates Feedbin state."""
    return _call(lambda: get_client().delete_subscription(subscription_id))


@mcp.tool()
def feedbin_get_feed(feed_id: int) -> Any:
    """Get feed metadata by feed id."""
    return _call(lambda: get_client().get_feed(feed_id))


@mcp.tool()
def feedbin_list_entries(
    page: int | None = None,
    per_page: int | None = None,
    since: str | None = None,
    ids: str | None = None,
    read: bool | None = None,
    starred: bool | None = None,
    mode: str | None = None,
    include_original: bool | None = None,
    include_enclosure: bool | None = None,
    include_content_diff: bool | None = None,
) -> Any:
    """List entries. HTML content/summary truncated to 500 chars. ids is a comma-separated list."""
    return _call(
        lambda: summarize_entries(
            get_client().list_entries(
                page=page,
                per_page=per_page,
                since=since,
                ids=ids,
                read=read,
                starred=starred,
                mode=mode,
                include_original=include_original,
                include_enclosure=include_enclosure,
                include_content_diff=include_content_diff,
            )
        )
    )


@mcp.tool()
def feedbin_get_entry(
    entry_id: int,
    mode: str | None = None,
    include_original: bool | None = None,
    include_enclosure: bool | None = None,
    include_content_diff: bool | None = None,
    force_refresh: bool = False,
) -> Any:
    """Get one entry by id with full content. Uses the local cache unless force_refresh is true."""
    return _call(
        lambda: get_client().get_entry(
            entry_id,
            mode=mode,
            include_original=include_original,
            include_enclosure=include_enclosure,
            include_content_diff=include_content_diff,
            force_refresh=force_refresh,
        )
    )


@mcp.tool()
def feedbin_list_feed_entries(
    feed_id: int,
    page: int | None = None,
    per_page: int | None = None,
    since: str | None = None,
    read: bool | None = None,
    starred: bool | None = None,
    mode: str | None = None,
    include_original: bool | None = None,
    include_enclosure: bool | None = None,
    include_content_diff: bool | None = None,
) -> Any:
    """List entries for a feed. HTML content/summary truncated to 500 chars."""
    return _call(
        lambda: summarize_entries(
            get_client().list_feed_entries(
                feed_id,
                page=page,
                per_page=per_page,
                since=since,
                read=read,
                starred=starred,
                mode=mode,
                include_original=include_original,
                include_enclosure=include_enclosure,
                include_content_diff=include_content_diff,
            )
        )
    )


@mcp.tool()
def feedbin_list_unread() -> Any:
    """List unread entry ids."""
    return _call(lambda: get_client().list_unread())


@mcp.tool()
def feedbin_mark_unread(entry_ids: list[int]) -> Any:
    """Mark entry ids as unread. Mutates Feedbin state. Max 1000 ids."""
    return _call(lambda: get_client().mark_unread(entry_ids))


@mcp.tool()
def feedbin_mark_read(entry_ids: list[int]) -> Any:
    """Mark entry ids as read. Mutates Feedbin state. Max 1000 ids."""
    return _call(lambda: get_client().mark_read(entry_ids))


@mcp.tool()
def feedbin_list_starred() -> Any:
    """List starred entry ids."""
    return _call(lambda: get_client().list_starred())


@mcp.tool()
def feedbin_star_entries(entry_ids: list[int]) -> Any:
    """Star entry ids. Mutates Feedbin state. Max 1000 ids."""
    return _call(lambda: get_client().star_entries(entry_ids))


@mcp.tool()
def feedbin_unstar_entries(entry_ids: list[int]) -> Any:
    """Unstar entry ids. Mutates Feedbin state. Max 1000 ids."""
    return _call(lambda: get_client().unstar_entries(entry_ids))


@mcp.tool()
def feedbin_list_recently_read() -> Any:
    """List recently read entry ids in display order."""
    return _call(lambda: get_client().list_recently_read())


@mcp.tool()
def feedbin_add_recently_read(entry_ids: list[int]) -> Any:
    """Add entry ids to recently read. Mutates Feedbin state."""
    return _call(lambda: get_client().add_recently_read(entry_ids))


@mcp.tool()
def feedbin_list_updated_entries(since: str | None = None) -> Any:
    """List entry ids updated after optional since (ISO 8601)."""
    return _call(lambda: get_client().list_updated_entries(since=since))


@mcp.tool()
def feedbin_delete_updated_entries(entry_ids: list[int]) -> Any:
    """Clear updated-entry ids. Mutates Feedbin state."""
    return _call(lambda: get_client().delete_updated_entries(entry_ids))


@mcp.tool()
def feedbin_list_taggings() -> Any:
    """List taggings (feed_id + tag name)."""
    return _call(lambda: get_client().list_taggings())


@mcp.tool()
def feedbin_get_tagging(tagging_id: int) -> Any:
    """Get one tagging by id."""
    return _call(lambda: get_client().get_tagging(tagging_id))


@mcp.tool()
def feedbin_create_tagging(feed_id: int, name: str) -> Any:
    """Tag a feed. Mutates Feedbin state."""
    return _call(lambda: get_client().create_tagging(feed_id, name))


@mcp.tool()
def feedbin_delete_tagging(tagging_id: int) -> Any:
    """Delete a tagging. Mutates Feedbin state."""
    return _call(lambda: get_client().delete_tagging(tagging_id))


@mcp.tool()
def feedbin_rename_tag(old_name: str, new_name: str) -> Any:
    """Rename a tag across taggings. Mutates Feedbin state."""
    return _call(lambda: get_client().rename_tag(old_name, new_name))


@mcp.tool()
def feedbin_delete_tag(name: str) -> Any:
    """Delete a tag and its taggings. Mutates Feedbin state."""
    return _call(lambda: get_client().delete_tag(name))


@mcp.tool()
def feedbin_list_saved_searches() -> Any:
    """List saved searches."""
    return _call(lambda: get_client().list_saved_searches())


@mcp.tool()
def feedbin_create_saved_search(name: str, query: str) -> Any:
    """Create a saved search. Mutates Feedbin state."""
    return _call(lambda: get_client().create_saved_search(name, query))


@mcp.tool()
def feedbin_get_saved_search(
    search_id: int,
    include_entries: bool | None = None,
    page: int | None = None,
) -> Any:
    """Get saved search matches (entry ids, or entries if include_entries=true)."""
    def _run() -> Any:
        result = get_client().get_saved_search(
            search_id,
            include_entries=include_entries,
            page=page,
        )
        if include_entries:
            return summarize_entries(result)
        return result

    return _call(_run)


@mcp.tool()
def feedbin_update_saved_search(
    search_id: int,
    name: str | None = None,
    query: str | None = None,
) -> Any:
    """Update a saved search name or query. Mutates Feedbin state."""
    return _call(lambda: get_client().update_saved_search(search_id, name=name, query=query))


@mcp.tool()
def feedbin_delete_saved_search(search_id: int) -> Any:
    """Delete a saved search. Mutates Feedbin state."""
    return _call(lambda: get_client().delete_saved_search(search_id))


@mcp.tool()
def feedbin_save_page(url: str, title: str | None = None) -> Any:
    """Save a webpage as a Feedbin page/entry. Mutates Feedbin state."""
    return _call(lambda: get_client().save_page(url, title=title))


@mcp.tool()
def feedbin_delete_page(page_id: int) -> Any:
    """Delete a saved page. Mutates Feedbin state."""
    return _call(lambda: get_client().delete_page(page_id))


@mcp.tool()
def feedbin_extract_content(entry_id: int) -> Any:
    """Fetch extracted full content for an entry via its extracted_content_url."""
    return _call(lambda: get_client().extract_content(entry_id))


@mcp.tool()
def feedbin_list_icons() -> Any:
    """List feed favicons for subscribed hosts."""
    return _call(lambda: get_client().list_icons())


@mcp.tool()
def feedbin_list_imports() -> Any:
    """List OPML imports."""
    return _call(lambda: get_client().list_imports())


@mcp.tool()
def feedbin_create_import(opml_xml: str) -> Any:
    """Create an OPML import. Mutates Feedbin state. Body is XML."""
    return _call(lambda: get_client().create_import(opml_xml))


@mcp.tool()
def feedbin_get_import(import_id: int) -> Any:
    """Get one OPML import and its item statuses."""
    return _call(lambda: get_client().get_import(import_id))


@mcp.tool()
def feedbin_poll_entries() -> Any:
    """Fetch unread entry bodies into the local SQLite cache. Does not mark entries read. Returns a summary, not HTML."""
    return _call(lambda: get_client().poll_entries())


@mcp.tool()
def feedbin_cached_entry(entry_id: int) -> Any:
    """Return one cached entry from SQLite only. No Feedbin API call. Full content."""
    return _call(lambda: get_client().cached_entry(entry_id))


@mcp.tool()
def feedbin_list_cached_entries(
    feed_id: int | None = None,
    limit: int = 50,
    search: str | None = None,
) -> Any:
    """List cached entries from SQLite. Optional feed_id, title search, limit. HTML truncated to 500 chars. No API call."""
    return _call(
        lambda: summarize_entries(
            get_client().list_cached_entries(feed_id=feed_id, limit=limit, search=search)
        )
    )


@mcp.tool()
def feedbin_cache_stats() -> Any:
    """Return cached entry count, SQLite path, and last poll time."""
    return _call(lambda: get_client().cache_stats())


def transport_settings() -> tuple[str, dict[str, Any]]:
    """stdio (default) or streamable HTTP for a shared long-lived process."""
    raw = os.environ.get("FEEDBIN_MCP_TRANSPORT", "stdio").strip().lower()
    if raw in {"http", "streamable-http"}:
        return "streamable-http", {
            "host": os.environ.get("FEEDBIN_MCP_HOST", "127.0.0.1"),
            "port": int(os.environ.get("FEEDBIN_MCP_PORT", "8000")),
            "streamable_http_path": os.environ.get("FEEDBIN_MCP_PATH", "/mcp"),
        }
    if raw in {"stdio", ""}:
        return "stdio", {}
    raise ValueError(f"Unknown FEEDBIN_MCP_TRANSPORT: {raw!r} (use stdio or http)")


def main() -> None:
    transport, kwargs = transport_settings()
    mcp.run(transport=transport, **kwargs)


if __name__ == "__main__":  # pragma: no cover
    main()
