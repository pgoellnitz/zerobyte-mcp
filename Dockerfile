FROM python:3.12.11-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.7.12 /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY src/ src/

RUN uv sync --no-dev --frozen

EXPOSE 8000

CMD ["uv", "run", "python", "src/zerobyte_mcp/server.py"]
