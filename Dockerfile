FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml .
COPY src/ src/

RUN uv sync --no-dev

EXPOSE 8000

CMD ["uv", "run", "python", "src/zerobyte_mcp/server.py"]
