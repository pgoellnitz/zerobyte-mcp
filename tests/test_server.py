"""Tests for zerobyte_mcp server."""

import json

import httpx
import pytest
import respx

from zerobyte_mcp.server import (
    ZerobyteAuthError,
    ZerobyteError,
    ZerobyteNotFoundError,
    ZerobyteServerError,
    get_http_client,
    deep_omit,
    get_backup_progress,
    get_info,
    get_resource,
    get_volume_health_check,
    keep,
    list_resources,
    validate_id,
    validate_path,
    zerobyte_get,
    zerobyte_post,
)

# ---------------------------------------------------------------------------
# Unit tests: helpers
# ---------------------------------------------------------------------------


class TestKeep:
    def test_keeps_specified_keys(self):
        assert keep({"a": 1, "b": 2, "c": 3}, {"a", "c"}) == {"a": 1, "c": 3}

    def test_missing_keys_ignored(self):
        assert keep({"a": 1}, {"a", "b"}) == {"a": 1}

    def test_empty_keys(self):
        assert keep({"a": 1, "b": 2}, set()) == {}

    def test_empty_dict(self):
        assert keep({}, {"a", "b"}) == {}


class TestDeepOmit:
    def test_omits_top_level_keys(self):
        assert deep_omit({"a": 1, "config": "secret"}, {"config"}) == {"a": 1}

    def test_omits_nested_keys(self):
        result = deep_omit({"a": {"config": "secret", "b": 2}}, {"config"})
        assert result == {"a": {"b": 2}}

    def test_deeply_nested(self):
        data = {"x": {"y": {"config": "secret", "z": 1}}}
        assert deep_omit(data, {"config"}) == {"x": {"y": {"z": 1}}}

    def test_no_matching_keys(self):
        data = {"a": 1, "b": {"c": 2}}
        assert deep_omit(data, {"config"}) == data

    def test_empty_dict(self):
        assert deep_omit({}, {"config"}) == {}


# ---------------------------------------------------------------------------
# Unit tests: input validation
# ---------------------------------------------------------------------------


class TestValidateId:
    def test_valid_short_ids(self):
        validate_id("a1b2c3d4")
        validate_id("18678xcj")
        validate_id("S5ZxHEKu")
        validate_id("abcd")  # min length

    def test_too_short(self):
        with pytest.raises(ZerobyteError, match="Invalid"):
            validate_id("abc")

    def test_too_long(self):
        with pytest.raises(ZerobyteError, match="Invalid"):
            validate_id("a" * 17)

    def test_special_characters(self):
        with pytest.raises(ZerobyteError, match="Invalid"):
            validate_id("ab-cd-ef")

    def test_path_traversal_in_id(self):
        with pytest.raises(ZerobyteError, match="Invalid"):
            validate_id("../../etc")

    def test_empty_string(self):
        with pytest.raises(ZerobyteError, match="Invalid"):
            validate_id("")

    def test_custom_name_in_error(self):
        with pytest.raises(ZerobyteError, match="backup_id"):
            validate_id("!!!", "backup_id")


class TestValidatePath:
    def test_valid_paths(self):
        validate_path("/var/spool")
        validate_path("/home/user/documents")
        validate_path(None)

    def test_path_traversal(self):
        with pytest.raises(ZerobyteError, match="path traversal"):
            validate_path("/var/../etc/passwd")

    def test_path_traversal_start(self):
        with pytest.raises(ZerobyteError, match="path traversal"):
            validate_path("../etc/passwd")


# ---------------------------------------------------------------------------
# Integration tests: HTTP helpers (mocked)
# ---------------------------------------------------------------------------


class TestZerobyteGet:
    @pytest.mark.asyncio
    async def test_success(self):
        with respx.mock(base_url=str(get_http_client().base_url)) as mock:
            mock.get("/api/v1/test").mock(
                return_value=httpx.Response(200, json={"result": "ok"})
            )
            result = await zerobyte_get("/api/v1/test")
            assert result == {"result": "ok"}

    @pytest.mark.asyncio
    async def test_404_raises_not_found(self):
        with respx.mock(base_url=str(get_http_client().base_url)) as mock:
            mock.get("/api/v1/missing").mock(
                return_value=httpx.Response(404, text="not found")
            )
            with pytest.raises(ZerobyteNotFoundError, match="not found"):
                await zerobyte_get("/api/v1/missing")

    @pytest.mark.asyncio
    async def test_401_raises_auth_error(self):
        with respx.mock(base_url=str(get_http_client().base_url)) as mock:
            mock.get("/api/v1/secret").mock(
                return_value=httpx.Response(401, text="unauthorized")
            )
            with pytest.raises(ZerobyteAuthError, match="Invalid or expired"):
                await zerobyte_get("/api/v1/secret")

    @pytest.mark.asyncio
    async def test_500_raises_server_error(self):
        with respx.mock(base_url=str(get_http_client().base_url)) as mock:
            mock.get("/api/v1/broken").mock(
                return_value=httpx.Response(500, text="internal server error")
            )
            with pytest.raises(ZerobyteServerError, match="500"):
                await zerobyte_get("/api/v1/broken")

    @pytest.mark.asyncio
    async def test_429_raises_rate_limit(self):
        with respx.mock(base_url=str(get_http_client().base_url)) as mock:
            mock.get("/api/v1/busy").mock(
                return_value=httpx.Response(429, text="too many requests")
            )
            with pytest.raises(ZerobyteError, match="Rate limited"):
                await zerobyte_get("/api/v1/busy")

    @pytest.mark.asyncio
    async def test_timeout(self):
        with respx.mock(base_url=str(get_http_client().base_url)) as mock:
            mock.get("/api/v1/slow").mock(side_effect=httpx.ReadTimeout("timeout"))
            with pytest.raises(ZerobyteError, match="timed out"):
                await zerobyte_get("/api/v1/slow")

    @pytest.mark.asyncio
    async def test_connection_error(self):
        with respx.mock(base_url=str(get_http_client().base_url)) as mock:
            mock.get("/api/v1/down").mock(side_effect=httpx.ConnectError("refused"))
            with pytest.raises(ZerobyteError, match="connection reset or refused"):
                await zerobyte_get("/api/v1/down")


class TestZerobytePost:
    @pytest.mark.asyncio
    async def test_success(self):
        with respx.mock(base_url=str(get_http_client().base_url)) as mock:
            mock.post("/api/v1/action").mock(
                return_value=httpx.Response(200, json={"started": True})
            )
            result = await zerobyte_post("/api/v1/action")
            assert result == {"started": True}

    @pytest.mark.asyncio
    async def test_404_raises_not_found(self):
        with respx.mock(base_url=str(get_http_client().base_url)) as mock:
            mock.post("/api/v1/missing").mock(
                return_value=httpx.Response(404, text="not found")
            )
            with pytest.raises(ZerobyteNotFoundError):
                await zerobyte_post("/api/v1/missing")


# ---------------------------------------------------------------------------
# Integration tests: tools with error decorator (mocked)
# ---------------------------------------------------------------------------


class TestToolErrorHandling:
    @pytest.mark.asyncio
    async def test_list_resources_success(self):
        with respx.mock(base_url=str(get_http_client().base_url)) as mock:
            mock.get("/api/v1/volumes").mock(
                return_value=httpx.Response(
                    200,
                    json=[
                        {"shortId": "abc123", "name": "vol1", "type": "directory", "organizationId": "org1", "extra": "ignored"}
                    ],
                )
            )
            result = json.loads(await list_resources("volume"))
            assert result == [{"shortId": "abc123", "name": "vol1", "type": "directory", "organizationId": "org1"}]

    @pytest.mark.asyncio
    async def test_tool_returns_error_json_on_404(self):
        with respx.mock(base_url=str(get_http_client().base_url)) as mock:
            mock.get("/api/v1/backups/abcd1234/progress").mock(
                return_value=httpx.Response(404, text="not found")
            )
            result = json.loads(await get_backup_progress("abcd1234"))
            assert result["code"] == "not_found"
            assert "error" in result

    @pytest.mark.asyncio
    async def test_tool_returns_error_on_invalid_id(self):
        result = json.loads(await get_resource("repo", "../../bad"))
        assert result["code"] == "api_error"
        assert "Invalid" in result["error"]

    @pytest.mark.asyncio
    async def test_tool_returns_error_on_timeout(self):
        with respx.mock(base_url=str(get_http_client().base_url)) as mock:
            mock.post("/api/v1/volumes/abcd1234/health-check").mock(
                side_effect=httpx.ReadTimeout("timeout")
            )
            result = json.loads(await get_volume_health_check("abcd1234"))
            assert result["code"] == "api_error"
            assert "timed out" in result["error"]

    @pytest.mark.asyncio
    async def test_get_info_success(self):
        with respx.mock(base_url=str(get_http_client().base_url)) as mock:
            mock.get("/api/v1/system/info").mock(
                return_value=httpx.Response(
                    200, json={"runtime": "server", "capabilities": {}}
                )
            )
            result = json.loads(await get_info())
            assert result["runtime"] == "server"
