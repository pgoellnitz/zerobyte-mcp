import asyncio
import functools
import json
import logging
import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("zerobyte_mcp")

BASE_URL = os.environ["ZEROBYTE_URL"]
TOKEN = os.environ["ZEROBYTE_API_TOKEN"]

_http_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"x-api-key": TOKEN},
            timeout=30.0,
            limits=httpx.Limits(
                max_keepalive_connections=5,
                max_connections=10,
                keepalive_expiry=20.0,
            ),
        )
    return _http_client

ERROR_BODY_MAX_LENGTH = 200


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[None]:
    logger.info("Starting zerobyte-mcp server")
    try:
        yield
    finally:
        global _http_client
        if _http_client is not None:
            await _http_client.aclose()
        logger.info("Shut down zerobyte-mcp server")


mcp = FastMCP("zerobyte", host="0.0.0.0", port=8000, lifespan=lifespan)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ZerobyteError(Exception):
    """Base error for Zerobyte API issues."""

    def __init__(self, message: str, status_code: int | None = None):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class ZerobyteNotFoundError(ZerobyteError):
    pass


class ZerobyteAuthError(ZerobyteError):
    pass


class ZerobyteServerError(ZerobyteError):
    pass


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

# Zerobyte short IDs are base64url (crypto.randomBytes(...).toString("base64url")),
# so "-" and "_" are valid. "/" and "." are not, which still blocks path traversal.
VALID_SHORT_ID = re.compile(r"^[A-Za-z0-9_-]{4,16}$")


def validate_id(value: str, name: str = "resource_id") -> None:
    if not VALID_SHORT_ID.match(value):
        raise ZerobyteError(f"Invalid {name}: '{value}' — expected base64url ID (4-16 chars of A-Z, a-z, 0-9, '-', '_')")


def validate_path(value: str | None) -> None:
    if value is not None and ".." in value.split("/"):
        raise ZerobyteError(f"Invalid path: '{value}' — path traversal not allowed")


# ---------------------------------------------------------------------------
# Error handling decorator
# ---------------------------------------------------------------------------


def handle_errors(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except ZerobyteNotFoundError as e:
            logger.warning("Not found: %s", e.message)
            return json.dumps({"error": e.message, "code": "not_found"})
        except ZerobyteAuthError as e:
            logger.error("Auth error: %s", e.message, exc_info=True)
            return json.dumps({"error": e.message, "code": "auth_error"})
        except ZerobyteServerError as e:
            logger.error("Server error (%d): %s", e.status_code, e.message, exc_info=True)
            return json.dumps({"error": e.message, "code": "server_error"})
        except ZerobyteError as e:
            logger.error("API error: %s", e.message, exc_info=True)
            return json.dumps({"error": e.message, "code": "api_error"})
        except httpx.HTTPStatusError as e:
            logger.error("Unexpected HTTP error: %s", e, exc_info=True)
            return json.dumps({"error": f"Unexpected error ({e.response.status_code})", "code": "unexpected"})
        except asyncio.CancelledError:
            logger.info("Tool call cancelled by client disconnect")
            raise
        except Exception:
            logger.exception("Unhandled error in tool")
            return json.dumps({"error": "Internal server error", "code": "internal"})

    return wrapper


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


async def zerobyte_get(path: str, params: dict | None = None) -> dict:
    for attempt in range(2):
        try:
            r = await get_http_client().get(path, params=params)
            break
        except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.LocalProtocolError):
            global _http_client
            _http_client = None
            if attempt == 1:
                raise ZerobyteError("Cannot reach Zerobyte API — connection reset or refused")
            logger.warning("Connection reset, retrying with fresh client")
        except httpx.TimeoutException:
            raise ZerobyteError("Zerobyte API request timed out")

    if r.status_code == 401:
        raise ZerobyteAuthError("Invalid or expired API token", status_code=401)
    if r.status_code == 404:
        raise ZerobyteNotFoundError(f"Resource not found: {path}", status_code=404)
    if r.status_code == 429:
        raise ZerobyteError("Rate limited by Zerobyte API — try again later", status_code=429)
    if r.status_code >= 500:
        raise ZerobyteServerError(
            f"Zerobyte API error ({r.status_code}): {r.text[:ERROR_BODY_MAX_LENGTH]}", status_code=r.status_code
        )

    r.raise_for_status()
    return r.json()


async def zerobyte_post(path: str) -> dict:
    for attempt in range(2):
        try:
            r = await get_http_client().post(path)
            break
        except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.LocalProtocolError):
            global _http_client
            _http_client = None
            if attempt == 1:
                raise ZerobyteError("Cannot reach Zerobyte API — connection reset or refused")
            logger.warning("Connection reset, retrying with fresh client")
        except httpx.TimeoutException:
            raise ZerobyteError("Zerobyte API request timed out")

    if r.status_code == 401:
        raise ZerobyteAuthError("Invalid or expired API token", status_code=401)
    if r.status_code == 404:
        raise ZerobyteNotFoundError(f"Resource not found: {path}", status_code=404)
    if r.status_code == 429:
        raise ZerobyteError("Rate limited by Zerobyte API — try again later", status_code=429)
    if r.status_code >= 500:
        raise ZerobyteServerError(
            f"Zerobyte API error ({r.status_code}): {r.text[:ERROR_BODY_MAX_LENGTH]}", status_code=r.status_code
        )

    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def keep(d: dict, keys: set) -> dict:
    return {k: v for k, v in d.items() if k in keys}


def deep_omit(d: dict, keys: set) -> dict:
    return {
        k: deep_omit(v, keys) if isinstance(v, dict) else v
        for k, v in d.items()
        if k not in keys
    }


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
@handle_errors
async def list_resources(kind: Literal["repo", "volume", "backup"]) -> str:
    """List all resources of a given kind configured in Zerobyte.

    Args:
        kind: The kind of resource to list - 'repo', 'volume', or 'backup'
    """
    data = await zerobyte_get(f"/api/v1/{RESOURCE_ENDPOINTS[kind]}")
    return json.dumps([keep(d, RESOURCE_LIST_FIELDS[kind]) for d in data])


@mcp.tool()
@handle_errors
async def get_resource(kind: Literal["repo", "volume", "backup"], resource_id: str) -> str:
    """Get informations for a specific Zerobyte resource.

    Args:
        kind: The kind of resource to get - 'repo', 'volume', or 'backup'
        resource_id: The resource short_id as returned by list_resources (e.g. 'a1b2c3d4')
    """
    validate_id(resource_id)
    data = await zerobyte_get(f"/api/v1/{RESOURCE_ENDPOINTS[kind]}/{resource_id}")
    return json.dumps(deep_omit(data, {"config"}))


@mcp.tool()
@handle_errors
async def get_backup_progress(backup_id: str) -> str:
    """Get the progress of a specific Zerobyte backup.

    Args:
    backup_id: The backup short_id as returned by list_resources (e.g. 'a1b2c3d4')
    """
    validate_id(backup_id, "backup_id")
    data = await zerobyte_get(f"/api/v1/backups/{backup_id}/progress")
    return json.dumps(data)


@mcp.tool()
@handle_errors
async def get_backup_mirrors(backup_id: str) -> str:
    """Get the mirrors of a specific Zerobyte backup, including their compatibility.

    Args:
    backup_id: The backup short_id as returned by list_resources (e.g. 'a1b2c3d4')
    """
    validate_id(backup_id, "backup_id")
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
@handle_errors
async def get_backup_notifications(backup_id: str) -> str:
    """Get the notification channels assigned to a specific Zerobyte backup.

    Args:
    backup_id: The backup short_id as returned by list_resources (e.g. 'a1b2c3d4')
    """
    validate_id(backup_id, "backup_id")
    data = await zerobyte_get(f"/api/v1/backups/{backup_id}/notifications")
    return json.dumps([deep_omit(d, {"config"}) for d in data])


@mcp.tool()
@handle_errors
async def list_notification_destinations() -> str:
    """List all available notification channels configured in Zerobyte."""
    data = await zerobyte_get("/api/v1/notifications/destinations")
    return json.dumps([deep_omit(d, {"config"}) for d in data])


@mcp.tool()
@handle_errors
async def get_info() -> str:
    """Get Zerobyte system runtime and capabilities info."""
    data = await zerobyte_get("/api/v1/system/info")
    return json.dumps(data)


@mcp.tool()
@handle_errors
async def get_repo_stats(repo_id: str) -> str:
    """Get storage statistics for a specific Zerobyte repository.

    Args:
        repo_id: The repository short_id as returned by list_resources (e.g. 'a1b2c3d4')
    """
    validate_id(repo_id, "repo_id")
    data = await zerobyte_get(f"/api/v1/repositories/{repo_id}/stats")
    return json.dumps(data)


@mcp.tool()
@handle_errors
async def get_repo_snapshots(repo_id: str, backup_id: str | None = None) -> str:
    """Get snapshots for a specific Zerobyte repository.

    It is highly advised to pass backup_id, as the list of snapshots for a
    repository without filtering can be very large.

    Args:
        repo_id: The repository short_id as returned by list_resources (e.g. 'a1b2c3d4')
        backup_id: The backup short_id as returned by list_resources (e.g. 'a1b2c3d4'),
            used to filter snapshots to a specific backup.
    """
    validate_id(repo_id, "repo_id")
    if backup_id is not None:
        validate_id(backup_id, "backup_id")
    data = await zerobyte_get(
        f"/api/v1/repositories/{repo_id}/snapshots",
        params={"backupId": backup_id} if backup_id is not None else None,
    )
    return json.dumps(data)


@mcp.tool()
@handle_errors
async def refresh_repo_stats(repo_id: str) -> str:
    """Trigger a refresh of storage statistics for a specific Zerobyte repository.

    Args:
        repo_id: The repository short_id as returned by list_resources (e.g. 'a1b2c3d4')
    """
    validate_id(repo_id, "repo_id")
    data = await zerobyte_post(f"/api/v1/repositories/{repo_id}/stats/refresh")
    return json.dumps(data)


@mcp.tool()
@handle_errors
async def run_repo_doctor(repo_id: str) -> str:
    """Start a doctor operation (repository check/repair) for a specific Zerobyte repository.

    This only starts the operation, which may take a long time. Use get_resource
    to check the result once it finishes.

    Args:
        repo_id: The repository short_id as returned by list_resources (e.g. 'a1b2c3d4')
    """
    validate_id(repo_id, "repo_id")
    data = await zerobyte_post(f"/api/v1/repositories/{repo_id}/doctor")
    return json.dumps(data)


@mcp.tool()
@handle_errors
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
    validate_id(repo_id, "repo_id")
    validate_id(snapshot_id, "snapshot_id")
    validate_path(path)
    params: dict[str, str | int] = {"offset": offset, "limit": limit}
    if path is not None:
        params["path"] = path
    data = await zerobyte_get(
        f"/api/v1/repositories/{repo_id}/snapshots/{snapshot_id}/files",
        params=params,
    )
    return json.dumps(data)


@mcp.tool()
@handle_errors
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
    validate_id(volume_id, "volume_id")
    validate_path(path)
    params: dict[str, str | int] = {"offset": offset, "limit": limit}
    if path is not None:
        params["path"] = path
    data = await zerobyte_get(f"/api/v1/volumes/{volume_id}/files", params=params)
    return json.dumps(data)


@mcp.tool()
@handle_errors
async def get_volume_health_check(volume_id: str) -> str:
    """Run a health check for a specific Zerobyte volume.

    Args:
    volume_id: The volume short_id as returned by list_resources (e.g. 'a1b2c3d4')
    """
    validate_id(volume_id, "volume_id")
    data = await zerobyte_post(f"/api/v1/volumes/{volume_id}/health-check")
    return json.dumps(data)


@mcp.tool()
@handle_errors
async def browse_filesystem(
    path: str | None = None, offset: int = 0, limit: int = 500
) -> str:
    """Browse the filesystem of the host/container Zerobyte is running on.

    Args:
    path: The directory path to list, e.g. '/var/spool'. Defaults to the filesystem root.
    offset: Pagination offset (default 0)
    limit: Max number of entries to return (default 500)
    """
    validate_path(path)
    params: dict[str, str | int] = {"offset": offset, "limit": limit}
    if path is not None:
        params["path"] = path
    data = await zerobyte_get("/api/v1/volumes/filesystem/browse", params=params)
    return json.dumps(data)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request):
    from starlette.responses import JSONResponse

    try:
        r = await get_http_client().get("/api/v1/system/info")
        r.raise_for_status()
        return JSONResponse({"status": "ok"})
    except Exception:
        logger.warning("Health check failed", exc_info=True)
        return JSONResponse(
            {"status": "unhealthy", "reason": "zerobyte_unreachable"},
            status_code=503,
        )


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
