import json
import os
from typing import Literal

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

mcp = FastMCP("zerobyte", host="0.0.0.0", port=8000)

BASE_URL = os.environ["ZEROBYTE_URL"]
TOKEN = os.environ["ZEROBYTE_API_TOKEN"]

http_client = httpx.AsyncClient(
    base_url=BASE_URL, headers={"x-api-key": TOKEN}, timeout=30.0
)


async def zerobyte_get(path: str, params: dict | None = None) -> dict:
    r = await http_client.get(path, params=params)
    r.raise_for_status()
    return r.json()


async def zerobyte_post(path: str) -> dict:
    r = await http_client.post(path)
    r.raise_for_status()
    return r.json()


RESOURCE_ENDPOINTS = {
    "repo": "repositories",
    "volume": "volumes",
    "backup": "backups",
}

RESOURCE_LIST_FIELDS = {
    "repo": {"name", "shortId", "organizationId"},
    "volume": {"name", "type", "shortId", "organizationId"},
    "backup": {"name", "shortId"},
}


@mcp.tool()
async def list_resources(kind: Literal["repo", "volume", "backup"]) -> str:
    """List all resources of a given kind configured in Zerobyte.

    Args:
        kind: The kind of resource to list - 'repo', 'volume', or 'backup'
    """
    data = await zerobyte_get(f"/api/v1/{RESOURCE_ENDPOINTS[kind]}")
    return json.dumps([keep(d, RESOURCE_LIST_FIELDS[kind]) for d in data])


@mcp.tool()
async def get_resource(kind: Literal["repo", "volume", "backup"], resource_id: str) -> str:
    """Get informations for a specific Zerobyte resource.

    Args:
        kind: The kind of resource to get - 'repo', 'volume', or 'backup'
        resource_id: The resource short_id as returned by list_resources (e.g. 'a1b2c3d4')
    """
    data = await zerobyte_get(f"/api/v1/{RESOURCE_ENDPOINTS[kind]}/{resource_id}")
    return json.dumps(deep_omit(data, {"config"}))


@mcp.tool()
async def get_backup_progress(backup_id: str) -> str:
    """Get the progress of a specific Zerobyte backup.

    Args:
    backup_id: The backup short_id as returned by list_resources (e.g. 'a1b2c3d4')
    """
    data = await zerobyte_get(f"/api/v1/backups/{backup_id}/progress")
    return json.dumps(data)


@mcp.tool()
async def get_backup_mirrors(backup_id: str) -> str:
    """Get the mirrors of a specific Zerobyte backup, including their compatibility.

    Args:
    backup_id: The backup short_id as returned by list_resources (e.g. 'a1b2c3d4')
    """
    mirrors, compatibility = (
        await zerobyte_get(f"/api/v1/backups/{backup_id}/mirrors"),
        await zerobyte_get(f"/api/v1/backups/{backup_id}/mirrors/compatibility"),
    )
    return json.dumps(
        {
            "mirrors": [deep_omit(d, {"config"}) for d in mirrors],
            "compatibility": compatibility,
        }
    )


@mcp.tool()
async def get_backup_notifications(backup_id: str) -> str:
    """Get the notification channels assigned to a specific Zerobyte backup.

    Args:
    backup_id: The backup short_id as returned by list_resources (e.g. 'a1b2c3d4')
    """
    data = await zerobyte_get(f"/api/v1/backups/{backup_id}/notifications")
    return json.dumps([deep_omit(d, {"config"}) for d in data])


@mcp.tool()
async def list_notification_destinations() -> str:
    """List all available notification channels configured in Zerobyte."""
    data = await zerobyte_get("/api/v1/notifications/destinations")
    return json.dumps([deep_omit(d, {"config"}) for d in data])


@mcp.tool()
async def get_info() -> str:
    """Get Zerobyte system runtime and capabilities info."""
    data = await zerobyte_get("/api/v1/system/info")
    return json.dumps(data)


@mcp.tool()
async def get_repo_stats(repo_id: str) -> str:
    """Get storage statistics for a specific Zerobyte repository.

    Args:
        repo_id: The repository short_id as returned by list_resources (e.g. 'a1b2c3d4')
    """
    data = await zerobyte_get(f"/api/v1/repositories/{repo_id}/stats")
    return json.dumps(data)


@mcp.tool()
async def get_repo_snapshots(repo_id: str, backup_id: str | None = None) -> str:
    """Get snapshots for a specific Zerobyte repository.

    It is highly advised to pass backup_id, as the list of snapshots for a
    repository without filtering can be very large.

    Args:
        repo_id: The repository short_id as returned by list_resources (e.g. 'a1b2c3d4')
        backup_id: The backup short_id as returned by list_resources (e.g. 'a1b2c3d4'),
            used to filter snapshots to a specific backup.
    """
    data = await zerobyte_get(
        f"/api/v1/repositories/{repo_id}/snapshots",
        params={"backupId": backup_id} if backup_id is not None else None,
    )
    return json.dumps(data)


@mcp.tool()
async def refresh_repo_stats(repo_id: str) -> str:
    """Trigger a refresh of storage statistics for a specific Zerobyte repository.

    Args:
        repo_id: The repository short_id as returned by list_resources (e.g. 'a1b2c3d4')
    """
    data = await zerobyte_post(f"/api/v1/repositories/{repo_id}/stats/refresh")
    return json.dumps(data)


@mcp.tool()
async def run_repo_doctor(repo_id: str) -> str:
    """Start a doctor operation (repository check/repair) for a specific Zerobyte repository.

    This only starts the operation, which may take a long time. Use get_resource
    to check the result once it finishes.

    Args:
        repo_id: The repository short_id as returned by list_resources (e.g. 'a1b2c3d4')
    """
    data = await zerobyte_post(f"/api/v1/repositories/{repo_id}/doctor")
    return json.dumps(data)


@mcp.tool()
async def get_snapshot_files(
    repo_id: str,
    snapshot_id: str,
    path: str | None = None,
    offset: int = 0,
    limit: int = 500,
) -> str:
    """List files and directories at a path within a specific Zerobyte snapshot.

    Args:
        repo_id: The repository short_id as returned by list_resources (e.g. 'a1b2c3d4')
        snapshot_id: The snapshot short_id as returned by get_repo_snapshots (e.g. 'a1b2c3d4')
        path: The directory path to list within the snapshot. Defaults to the snapshot root.
        offset: Pagination offset (default 0)
        limit: Max number of entries to return (default 500)
    """
    params: dict[str, str | int] = {"offset": offset, "limit": limit}
    if path is not None:
        params["path"] = path
    data = await zerobyte_get(
        f"/api/v1/repositories/{repo_id}/snapshots/{snapshot_id}/files",
        params=params,
    )
    return json.dumps(data)


@mcp.tool()
async def get_volume_files(
    volume_id: str, path: str | None = None, offset: int = 0, limit: int = 500
) -> str:
    """List files and directories for a specific Zerobyte path on a volume.

    Args:
    volume_id: The volume short_id as returned by list_resources (e.g. 'a1b2c3d4')
    path: The directory path to list, e.g. '/daria/dockmon'. Defaults to the volume root.
    offset: Pagination offset (default 0)
    limit: Max number of entries to return (default 500)
    """
    params: dict[str, str | int] = {"offset": offset, "limit": limit}
    if path is not None:
        params["path"] = path
    data = await zerobyte_get(f"/api/v1/volumes/{volume_id}/files", params=params)
    return json.dumps(data)


@mcp.tool()
async def get_volume_health_check(volume_id: str) -> str:
    """Run a health check for a specific Zerobyte volume.

    Args:
    volume_id: The volume short_id as returned by list_resources (e.g. 'a1b2c3d4')
    """
    data = await zerobyte_post(f"/api/v1/volumes/{volume_id}/health-check")
    return json.dumps(data)


@mcp.tool()
async def browse_filesystem(
    path: str | None = None, offset: int = 0, limit: int = 500
) -> str:
    """Browse the filesystem of the host/container Zerobyte is running on.

    Args:
    path: The directory path to list, e.g. '/var/spool'. Defaults to the filesystem root.
    offset: Pagination offset (default 0)
    limit: Max number of entries to return (default 500)
    """
    params: dict[str, str | int] = {"offset": offset, "limit": limit}
    if path is not None:
        params["path"] = path
    data = await zerobyte_get("/api/v1/volumes/filesystem/browse", params=params)
    return json.dumps(data)


def keep(d: dict, keys: set) -> dict:
    return {k: v for k, v in d.items() if k in keys}


def deep_omit(d: dict, keys: set) -> dict:
    return {
        k: deep_omit(v, keys) if isinstance(v, dict) else v
        for k, v in d.items()
        if k not in keys
    }


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
