# feedbin-mcp

MCP server for the [Feedbin](https://feedbin.com) v2 REST API. One process, HTTP transport, shared by Cursor, Codex, and any other MCP client.

API spec: [feedbin/feedbin-api](https://github.com/feedbin/feedbin-api).

## Image

```bash
make
```

Builds image `feedbin-mcp` (`make IMAGE=other-name` to override).

Listen port is `FEEDBIN_MCP_PORT` (default `8000`). Publish the same host port. Mount a **directory** on `/data` so `entries.db` survives restarts.

Background + start again when the Docker daemon starts (`unless-stopped`). Do not use `--rm`.

```bash
export FEEDBIN_EMAIL='you@example.com'
export FEEDBIN_PASSWORD='your-password'
make run
```

Equivalent:

```bash
mkdir -p ~/.cache/feedbin-mcp
docker run -d --name feedbin-mcp --restart unless-stopped \
  -p 8000:8000 \
  -e FEEDBIN_EMAIL \
  -e FEEDBIN_PASSWORD \
  -v ~/.cache/feedbin-mcp:/data \
  feedbin-mcp
```

Other port: `make run PORT=9000`. Stop: `make stop`. Logs: `docker logs -f feedbin-mcp`.

On macOS, Docker Desktop must itself start on login (Settings → General → Start Docker Desktop when you sign in). `--restart` only runs after the daemon is up.

MCP URL: `http://127.0.0.1:<port>/mcp`

Without `-v`, the SQLite cache lives in the container and is discarded when the container is removed.

## Cursor

`~/.cursor/mcp.json` (or project `.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "feedbin": {
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

Reload MCP. Tools should appear (`feedbin_check_auth`, `feedbin_poll_entries`, …).

## Codex

`~/.codex/config.toml`:

```toml
[mcp_servers.feedbin]
url = "http://127.0.0.1:8000/mcp"
```

Or: `codex mcp add feedbin --url http://127.0.0.1:8000/mcp`

## Env

| Variable | Required | Default (image) | Default (local stdio) |
| --- | --- | --- | --- |
| `FEEDBIN_EMAIL` | yes | — | — |
| `FEEDBIN_PASSWORD` | yes | — | — |
| `FEEDBIN_BASE_URL` | no | `https://api.feedbin.com` | same |
| `FEEDBIN_CACHE_PATH` | no | `/data/entries.db` | `~/.cache/feedbin-mcp/entries.db` |
| `FEEDBIN_MCP_TRANSPORT` | no | `http` | `stdio` |
| `FEEDBIN_MCP_HOST` | no | `0.0.0.0` | `127.0.0.1` |
| `FEEDBIN_MCP_PORT` | no | `8000` | `8000` |
| `FEEDBIN_MCP_PATH` | no | `/mcp` | `/mcp` |

The process reads the environment. It does not load `.env`.

Do not publish this port on the public internet. Anyone who can reach `/mcp` can use your Feedbin credentials.

## Cache

Entry bodies (full Feedbin JSON) go in SQLite. In the image that file is `/data/entries.db`; bind-mount the directory, not the file.

- `feedbin_poll_entries` GETs unread ids, fetches missing bodies in batches of 100, upserts, returns `{unread_count, fetched, already_cached, ids}`. Does not mark read. No HTML in the result.
- `feedbin_get_entry` is cache-first. `force_refresh=true` hits the API.
- `feedbin_list_entries` with `ids` uses the cache for hits and GETs the rest.
- `feedbin_cached_entry`, `feedbin_list_cached_entries`, `feedbin_cache_stats` are SQLite only. List tools still truncate `content`/`summary` to 500 chars.

## Local stdio (no image)

```bash
uv sync
export FEEDBIN_EMAIL FEEDBIN_PASSWORD
uv run feedbin-mcp
```

Each MCP client that uses `command`/`args` spawns its own process. Use the image + `url` if you want one shared server.

## Tests

```bash
uv run pytest
```
