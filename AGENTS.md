# feedbin-mcp

MCP server wrapping the Feedbin v2 REST API. Image default is streamable HTTP on port 8000. Local `uv run feedbin-mcp` defaults to stdio.

## Source of truth

API spec: https://github.com/feedbin/feedbin-api. Do not invent endpoints. If a method is not in those markdown files, omit it.

## Layout

- `src/feedbin_mcp/client.py` — `FeedbinClient` (httpx, HTTP Basic)
- `src/feedbin_mcp/cache.py` — SQLite entry cache (`sqlite3` only)
- `src/feedbin_mcp/server.py` — MCP tools (`MCPServer` from package `mcp` 2.x)
- `Dockerfile` — HTTP listener, cache at `/data/entries.db`
- `Makefile` — `make build`; `make run` (detached, `--restart unless-stopped`); `make stop`
- `tests/` — pytest with `httpx.MockTransport`

## Env

`FEEDBIN_EMAIL`, `FEEDBIN_PASSWORD`, optional `FEEDBIN_BASE_URL`.

HTTP (image): `FEEDBIN_MCP_TRANSPORT=http`, `FEEDBIN_MCP_HOST=0.0.0.0`, `FEEDBIN_MCP_PORT=8000`, `FEEDBIN_MCP_PATH=/mcp`, `FEEDBIN_CACHE_PATH=/data/entries.db`.

Persist cache: bind-mount a host **directory** to `/data`.

## Rules

- List tools truncate `content`/`summary` to 500 chars. Get-by-id returns full content. The SQLite cache stores the full Feedbin JSON.
- Destructive tools must say they mutate Feedbin state. `feedbin_poll_entries` fetches+caches only; it does not mark entries read.
- No secrets in the repo. Copy `.env.example`, never commit `.env`. Never commit the cache db.
- Run tests with `uv run pytest`. Coverage gate is 90%.
- No docker-compose. `docker build` + `docker run` only.
