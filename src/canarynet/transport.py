"""Deliberately bounded stdio MCP client; not a sandbox or a general MCP SDK.

Implements the initialized-session tool subset through MCP 2025-11-25.
Newer revisions are rejected rather than silently treated as compatible.
"""
from __future__ import annotations

import asyncio
import os
import signal
import sys
from typing import Any

from . import __version__
from .common import CanaryError, MAX_BYTES, canonical, loads

SUPPORTED = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
BASE_ENV = ("PATH", "LANG", "LC_ALL", "SYSTEMROOT", "WINDIR", "TMPDIR", "TEMP", "TMP")


class TransportError(CanaryError):
    pass


class RpcError(CanaryError):
    def __init__(self, code: int):
        self.code = code
        super().__init__(f"rpc_error_{code}")


class StdioClient:
    def __init__(self, server: dict, timeout: float = 5):
        self.server, self.timeout = server, timeout
        self.process: asyncio.subprocess.Process | None = None
        self.sequence = 0
        self.info: dict = {}
        self.catalog_changed = False

    async def __aenter__(self) -> "StdioClient":
        command = [sys.executable if part == "{python}" else part for part in self.server["command"]]
        environment = {key: os.environ[key] for key in (*BASE_ENV, *self.server.get("envAllow", [])) if key in os.environ}
        try:
            self.process = await asyncio.create_subprocess_exec(
                *command, cwd=self.server.get("cwd"), env=environment,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, limit=MAX_BYTES,
                start_new_session=(os.name == "posix"),
            )
            self.info = await self.request("initialize", {
                "protocolVersion": SUPPORTED[0], "capabilities": {},
                "clientInfo": {"name": "canarynet", "version": __version__},
            })
            if self.info.get("protocolVersion") not in SUPPORTED:
                raise TransportError("unsupported_protocol_version")
            capabilities = self.info.get("capabilities")
            server_info = self.info.get("serverInfo")
            if (not isinstance(capabilities, dict) or not isinstance(capabilities.get("tools"), dict)
                    or not isinstance(server_info, dict) or not isinstance(server_info.get("name"), str)
                    or not isinstance(server_info.get("version"), str)):
                raise TransportError("invalid_initialize_result_or_missing_tools_capability")
            await asyncio.wait_for(self._send({"jsonrpc": "2.0", "method": "notifications/initialized"}), self.timeout)
            return self
        except BaseException:
            await self.close()
            raise

    async def _send(self, message: dict) -> None:
        if self.process is None or self.process.stdin is None:
            raise TransportError("server_not_running")
        raw = canonical(message).encode() + b"\n"
        if len(raw) > MAX_BYTES:
            raise TransportError("outbound_message_too_large")
        self.process.stdin.write(raw)
        await self.process.stdin.drain()

    async def request(self, method: str, params: dict) -> dict:
        self.sequence += 1
        request_id = self.sequence
        try:
            async with asyncio.timeout(self.timeout):
                await self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
                assert self.process is not None and self.process.stdout is not None
                for _ in range(1000):
                    raw = await self.process.stdout.readline()
                    if not raw:
                        raise TransportError("server_closed_stdout")
                    if not raw.endswith(b"\n"):
                        raise TransportError("unterminated_jsonrpc_message")
                    message = loads(raw)
                    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                        raise TransportError("invalid_jsonrpc_envelope")
                    if "method" in message:
                        name = message["method"]
                        if not isinstance(name, str) or "result" in message or "error" in message:
                            raise TransportError("invalid_server_message")
                        if "id" in message:
                            if type(message["id"]) not in (int, str):
                                raise TransportError("invalid_server_request_id")
                            response = {"jsonrpc": "2.0", "id": message["id"]}
                            if name == "ping":
                                response["result"] = {}
                            else:
                                response["error"] = {"code": -32601, "message": "Capability not offered by CanaryNet"}
                            await self._send(response)
                        elif name == "notifications/tools/list_changed":
                            self.catalog_changed = True
                        continue
                    if type(message.get("id")) is not int or message["id"] != request_id:
                        raise TransportError("unexpected_response_id")
                    if ("result" in message) == ("error" in message):
                        raise TransportError("invalid_jsonrpc_response")
                    if "error" in message:
                        error = message["error"]
                        if not isinstance(error, dict) or type(error.get("code")) is not int or not isinstance(error.get("message"), str):
                            raise TransportError("invalid_jsonrpc_error")
                        raise RpcError(error["code"])
                    if not isinstance(message["result"], dict):
                        raise TransportError("mcp_result_must_be_object")
                    return message["result"]
                raise TransportError("server_message_limit_exceeded")
        except TimeoutError as exc:
            # Cancellation is advisory; the caller discards this session after timeout.
            try:
                await asyncio.wait_for(self._send({"jsonrpc": "2.0", "method": "notifications/cancelled",
                                                  "params": {"requestId": request_id, "reason": "deadline"}}), 0.1)
            except Exception:
                pass
            raise TransportError("request_deadline_exceeded") from exc
        except (OSError, ValueError) as exc:
            raise TransportError("transport_io_or_framing_error") from exc
        except CanaryError as exc:
            if isinstance(exc, (TransportError, RpcError)):
                raise
            raise TransportError("invalid_jsonrpc_json") from exc

    async def tools(self) -> dict[str, dict]:
        tools: dict[str, dict] = {}
        cursor = None
        seen = set()
        for _ in range(100):
            result = await self.request("tools/list", {} if cursor is None else {"cursor": cursor})
            page = result.get("tools")
            if not isinstance(page, list):
                raise TransportError("invalid_tools_list")
            for tool in page:
                if (not isinstance(tool, dict) or not isinstance(tool.get("name"), str)
                        or not tool["name"] or len(tool["name"]) > 128
                        or not isinstance(tool.get("inputSchema"), dict)
                        or ("outputSchema" in tool and not isinstance(tool["outputSchema"], dict))):
                    raise TransportError("invalid_tool_definition")
                if tool["name"] in tools:
                    raise TransportError("duplicate_tool_name")
                tools[tool["name"]] = tool
                if len(tools) > 1000:
                    raise TransportError("tool_count_limit_exceeded")
            cursor = result.get("nextCursor")
            if cursor is None:
                return tools
            if not isinstance(cursor, str) or not cursor or cursor in seen:
                raise TransportError("invalid_or_repeated_pagination_cursor")
            seen.add(cursor)
        raise TransportError("pagination_limit_exceeded")

    async def close(self) -> None:
        process = self.process
        if process is None:
            return
        if process.stdin is not None:
            process.stdin.close()
        try:
            await asyncio.wait_for(process.wait(), 0.2)
        except TimeoutError:
            pass
        # On POSIX also clean up descendants in our dedicated process group.
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                if os.name == "posix":
                    os.killpg(process.pid, sig)
                elif process.returncode is None:
                    process.terminate() if sig == signal.SIGTERM else process.kill()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), 0.3)
            except TimeoutError:
                continue
        self.process = None

    async def __aexit__(self, *_: Any) -> None:
        await self.close()
