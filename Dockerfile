FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN uv sync --frozen --no-dev --no-editable

ENV PATH="/app/.venv/bin:$PATH"
ENV FEEDBIN_MCP_TRANSPORT=http
ENV FEEDBIN_MCP_HOST=0.0.0.0
ENV FEEDBIN_MCP_PORT=8000
ENV FEEDBIN_MCP_PATH=/mcp
ENV FEEDBIN_CACHE_PATH=/data/entries.db

RUN mkdir -p /data
EXPOSE 8000
VOLUME /data

CMD ["feedbin-mcp"]
