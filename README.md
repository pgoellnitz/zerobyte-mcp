# Zerobyte MCP

An [MCP](https://modelcontextprotocol.io) server that exposes the [Zerobyte](https://zerobyte.com) backup platform's REST API as tools for AI assistants. Built with FastMCP and served over streamable HTTP.

## Available Tools

### Resources

| Tool | Description |
| --- | --- |
| `list_resources` | List all repositories, volumes, or backups configured in Zerobyte |
| `get_resource` | Get detailed information for a specific resource |

### Repositories

| Tool | Description |
| --- | --- |
| `get_repo_stats` | Get storage statistics for a repository |
| `refresh_repo_stats` | Trigger a refresh of repository storage statistics |
| `get_repo_snapshots` | List snapshots in a repository, optionally filtered by backup |
| `run_repo_doctor` | Start a repository check/repair operation |

### Backups

| Tool | Description |
| --- | --- |
| `get_backup_progress` | Get the progress of a backup job |
| `get_backup_mirrors` | Get mirror destinations and compatibility for a backup |
| `get_backup_notifications` | Get notification channels assigned to a backup |

### Snapshots

| Tool | Description |
| --- | --- |
| `get_snapshot_files` | Browse files and directories within a snapshot |

### Volumes

| Tool | Description |
| --- | --- |
| `get_volume_files` | Browse files and directories on a volume |
| `get_volume_health_check` | Run a health check on a volume |

### System

| Tool | Description |
| --- | --- |
| `get_info` | Get Zerobyte system runtime and capabilities |
| `list_notification_destinations` | List all configured notification channels |
| `browse_filesystem` | Browse the filesystem of the Zerobyte host |

### Health

A `GET /health` endpoint returns `{"status": "ok"}` when the upstream Zerobyte API is reachable, or `{"status": "unhealthy"}` (HTTP 503) when it is not.

## Scope

Only **non-destructive** operations are implemented — read-only queries, statistics refresh triggers, health checks, and repository doctor checks. No write, delete, modify, or configuration-change operations are exposed. Sensitive `config` keys are stripped from all API responses.

## Configuration

Environment variables loaded by the server:

| Variable | Required | Description |
| --- | --- |
| `ZEROBYTE_URL` | Yes | Base URL of the Zerobyte installation |
| `ZEROBYTE_API_TOKEN` | Yes | Zerobyte API key |

## Running

### Direct from source

```bash
export ZEROBYTE_URL=http://<your-local-ip>:<port>
export ZEROBYTE_API_TOKEN=<your-api-token>
uv sync
uv run python src/zerobyte_mcp/server.py
```

The server starts on `0.0.0.0:8000` with the streamable HTTP transport.

### Docker Compose

```yaml
services:
  zerobyte-mcp:
    image: ghcr.io/pgoellnitz/zerobyte-mcp:latest
    ports:
      - 8000:8000
    restart: unless-stopped
    environment:
      - ZEROBYTE_URL=http://<your-local-ip>:<port>
      - ZEROBYTE_API_TOKEN=<your-api-token>
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s
```

## MCP Client Setup

Add to your LibreChat `librechat.yaml`:

```yaml
mcpServers:
  zerobyte:
    type: streamable-http
    url: http://localhost:8000/mcp
```

> **Disclaimer:** This project is provided **as-is** for **educational purposes only**. It should not be used on productive Zerobyte instances. No warranty or support is provided.
