# Copyright (c) 2026 LeadRescue LLC. All rights reserved.
from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .storage import Ledger


class MCPConnectorError(RuntimeError):
    pass


def config_path() -> Path:
    return Ledger().home / "mcp-connectors.json"


def read_connectors() -> list[dict[str, Any]]:
    path = config_path()
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    connectors = data.get("connectors", [])
    if not isinstance(connectors, list):
        raise MCPConnectorError("MCP connector configuration must contain a connectors list.")
    return connectors


def write_connectors(connectors: list[dict[str, Any]]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"connectors": connectors}, indent=2), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def public_connectors() -> list[dict[str, Any]]:
    result = []
    for connector in read_connectors():
        env_map = connector.get("env", {})
        header_map = connector.get("headers", {})
        missing = sorted({source for source in [*env_map.values(), *header_map.values()] if not os.environ.get(source)})
        command = connector.get("command", [])
        parsed_url = urlparse(connector.get("url", ""))
        result.append(
            {
                "id": connector["id"],
                "name": connector.get("name", connector["id"]),
                "transport": connector.get("transport", "stdio"),
                "command": command[0] if command else parsed_url.hostname or "",
                "configured": not missing,
                "missing_env": missing,
                "env_names": sorted(env_map.keys()),
            }
        )
    return result


def validate_connector(data: dict[str, Any]) -> dict[str, Any]:
    connector_id = str(data.get("id", "")).strip().lower()
    if not re.fullmatch(r"[a-z][a-z0-9_-]{1,39}", connector_id):
        raise ValueError("Connector ID must start with a letter and contain 2 to 40 letters, numbers, underscores, or hyphens.")
    name = str(data.get("name", "")).strip()
    command = data.get("command")
    args = data.get("args", [])
    env = data.get("env", {})
    headers = data.get("headers", {})
    transport = data.get("transport", "stdio")
    if not name or len(name) > 80:
        raise ValueError("Enter a connector name up to 80 characters.")
    if transport not in {"stdio", "http"}:
        raise ValueError("Transport must be stdio or http.")
    if transport == "stdio" and (not isinstance(command, list) or not command or any(not isinstance(part, str) or not part for part in command)):
        raise ValueError("Command must be a non-empty list of strings.")
    if transport == "http":
        url = data.get("url")
        parsed = urlparse(url or "")
        if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Enter a valid HTTPS MCP endpoint URL.")
        if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Remote MCP endpoints must use HTTPS.")
    if transport == "stdio" and (len(command) > 30 or any(len(part) > 500 for part in command)):
        raise ValueError("Connector command is too long.")
    if not isinstance(args, list) or any(not isinstance(arg, str) or len(arg) > 500 for arg in args):
        raise ValueError("Arguments must be a list of strings.")
    if len(args) > 60:
        raise ValueError("A connector can have at most 60 arguments.")
    if not isinstance(env, dict):
        raise ValueError("Environment mapping must be an object.")
    for target, source in env.items():
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(target)) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(source)):
            raise ValueError("Environment mappings must use variable names, not secret values.")
    if not isinstance(headers, dict):
        raise ValueError("HTTP header mapping must be an object.")
    for target, source in headers.items():
        if not re.fullmatch(r"[A-Za-z0-9-]{1,80}", str(target)) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(source)):
            raise ValueError("HTTP header mappings must use header names and local variable names, not secret values.")
    saved = {"id": connector_id, "name": name, "transport": transport, "args": args, "env": env, "headers": headers}
    if transport == "stdio":
        if len(command) > 30 or any(len(part) > 500 for part in command):
            raise ValueError("Connector command is too long.")
        saved["command"] = command
    else:
        saved["url"] = data["url"]
    return saved


def _function_name(connector_id: str, tool_name: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_-]", "_", f"mcp_{connector_id}_{tool_name}")
    return name[:64].rstrip("_")


def _grants_for_server(agent_tools: list[str], connector_id: str) -> list[str] | None:
    grants = []
    allow_all = False
    for item in agent_tools:
        if not item.startswith("mcp."):
            continue
        _, _, requested = item.partition(".")
        server_id, _, tool_name = requested.partition(".")
        if server_id != connector_id:
            continue
        if not tool_name or tool_name == "*":
            allow_all = True
        else:
            grants.append(tool_name)
    return None if allow_all else grants


class MCPProcess:
    def __init__(self, connector: dict[str, Any]) -> None:
        self.connector = connector
        self.process: subprocess.Popen[str] | None = None
        self.messages: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self.reader: threading.Thread | None = None
        self.counter = 0
        self.write_lock = threading.Lock()

    def start(self) -> list[dict[str, Any]]:
        env = self._process_env()
        try:
            self.process = subprocess.Popen(
                [*self.connector["command"], *self.connector.get("args", [])],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                bufsize=1,
                cwd=Path.home(),
                env=env,
            )
        except OSError as exc:
            raise MCPConnectorError(f"Could not start MCP server '{self.connector['id']}': {exc}") from exc
        self.reader = threading.Thread(target=self._read_loop, daemon=True)
        self.reader.start()
        self._request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "GUADE", "version": "0.2.0"},
            },
        )
        self._notify("notifications/initialized")
        result = self._request("tools/list", {})
        tools = result.get("tools", [])
        if not isinstance(tools, list):
            raise MCPConnectorError("MCP server returned an invalid tools list.")
        return tools

    def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        result = self._request("tools/call", {"name": name, "arguments": arguments}, timeout=180)
        blocks = result.get("content", [])
        text_parts = [block.get("text", "") for block in blocks if block.get("type") == "text"]
        output = "\n".join(text_parts)
        if result.get("isError"):
            return f"MCP_TOOL_ERROR: {output}"
        return output or json.dumps(result)

    def close(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)

    def _process_env(self) -> dict[str, str]:
        inherited = ("PATH", "HOME", "USERPROFILE", "TMP", "TEMP", "TMPDIR", "SYSTEMROOT", "WINDIR", "APPDATA")
        env = {key: os.environ[key] for key in inherited if key in os.environ}
        for target, source in self.connector.get("env", {}).items():
            value = os.environ.get(source)
            if not value:
                raise MCPConnectorError(f"Connector '{self.connector['id']}' requires environment variable {source}.")
            env[target] = value
        return env

    def _read_loop(self) -> None:
        assert self.process and self.process.stdout
        try:
            for line in self.process.stdout:
                if line.strip():
                    try:
                        self.messages.put(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        finally:
            self.messages.put(None)

    def _notify(self, method: str) -> None:
        self._send({"jsonrpc": "2.0", "method": method})

    def _request(self, method: str, params: dict[str, Any], timeout: int = 20) -> dict[str, Any]:
        if not self.process or self.process.poll() is not None:
            raise MCPConnectorError(f"MCP server '{self.connector['id']}' exited unexpectedly.")
        self.counter += 1
        request_id = self.counter
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MCPConnectorError(f"MCP server '{self.connector['id']}' timed out during {method}.")
            try:
                message = self.messages.get(timeout=remaining)
            except queue.Empty as exc:
                raise MCPConnectorError(f"MCP server '{self.connector['id']}' timed out during {method}.") from exc
            if message is None:
                raise MCPConnectorError(f"MCP server '{self.connector['id']}' closed its output.")
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise MCPConnectorError(message["error"].get("message", "MCP request failed."))
            result = message.get("result")
            if not isinstance(result, dict):
                raise MCPConnectorError(f"MCP server returned an invalid result for {method}.")
            return result

    def _send(self, message: dict[str, Any]) -> None:
        if not self.process or not self.process.stdin:
            raise MCPConnectorError("MCP server input is not available.")
        encoded = json.dumps(message, separators=(",", ":"))
        with self.write_lock:
            self.process.stdin.write(encoded + "\n")
            self.process.stdin.flush()


class MCPToolSession:
    def __init__(self, workflow_agents: Any) -> None:
        self.agent_tools = [tool for agent in workflow_agents.values() for tool in agent.tools]
        self.processes: dict[str, MCPProcess] = {}
        self.tools: dict[str, tuple[str, str]] = {}
        self.schemas: dict[str, dict[str, Any]] = {}

    def start(self) -> None:
        requested: dict[str, list[str] | None] = {}
        for grant in self.agent_tools:
            if grant.startswith("mcp."):
                _, _, target = grant.partition(".")
                connector_id, _, _ = target.partition(".")
                if connector_id:
                    requested[connector_id] = _grants_for_server(self.agent_tools, connector_id)
        if not requested:
            return
        configs = {connector["id"]: connector for connector in read_connectors()}
        for connector_id, grants in requested.items():
            connector = configs.get(connector_id)
            if connector is None:
                raise MCPConnectorError(f"MCP connector '{connector_id}' is not configured.")
            process = _connector_client(connector)
            self.processes[connector_id] = process
            remote_tools = process.start()
            available = set()
            for tool in remote_tools:
                remote_name = tool.get("name")
                if not isinstance(remote_name, str):
                    continue
                available.add(remote_name)
                if grants is not None and remote_name not in grants:
                    continue
                parameters = tool.get("inputSchema") or {"type": "object", "properties": {}}
                function_name = _function_name(connector_id, remote_name)
                if function_name in self.tools:
                    raise MCPConnectorError(f"Connector tool name collision after normalization: {remote_name}.")
                self.tools[function_name] = (connector_id, remote_name)
                self.schemas[function_name] = {
                    "type": "function",
                    "name": function_name,
                    "description": f"[{connector.get('name', connector_id)}] {tool.get('description', remote_name)}",
                    "parameters": parameters,
                }
            if grants is not None:
                missing = sorted(set(grants) - available)
                if missing:
                    raise MCPConnectorError(f"Connector '{connector_id}' does not provide tool(s): {', '.join(missing)}.")

    def schemas_for(self, grants: list[str]) -> list[dict[str, Any]]:
        allowed = set()
        for grant in grants:
            if not grant.startswith("mcp."):
                continue
            _, _, target = grant.partition(".")
            connector_id, _, tool_name = target.partition(".")
            for function_name, (server_id, remote_name) in self.tools.items():
                if server_id == connector_id and (not tool_name or tool_name == "*" or remote_name == tool_name):
                    allowed.add(function_name)
        return [schema for name, schema in self.schemas.items() if name in allowed]

    def handles(self, function_name: str) -> bool:
        return function_name in self.tools

    def execute(self, function_name: str, arguments: dict[str, Any]) -> str:
        connector_id, remote_name = self.tools[function_name]
        return self.processes[connector_id].call_tool(remote_name, arguments)

    def close(self) -> None:
        for process in self.processes.values():
            process.close()

    def inspect(self, connector: dict[str, Any]) -> list[dict[str, Any]]:
        process = _connector_client(connector)
        try:
            return process.start()
        finally:
            process.close()


class MCPHttpClient:
    def __init__(self, connector: dict[str, Any]) -> None:
        self.connector = connector
        self.session_id: str | None = None
        self.counter = 0

    def start(self) -> list[dict[str, Any]]:
        self._request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "GUADE", "version": "0.2.0"},
            },
        )
        self._request("notifications/initialized", {}, expects_response=False)
        result = self._request("tools/list", {})
        tools = result.get("tools", [])
        if not isinstance(tools, list):
            raise MCPConnectorError("MCP server returned an invalid tools list.")
        return tools

    def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        result = self._request("tools/call", {"name": name, "arguments": arguments}, timeout=180)
        text_parts = [item.get("text", "") for item in result.get("content", []) if item.get("type") == "text"]
        output = "\n".join(text_parts)
        if result.get("isError"):
            return f"MCP_TOOL_ERROR: {output}"
        return output or json.dumps(result)

    def close(self) -> None:
        return

    def _request(self, method: str, params: dict[str, Any], expects_response: bool = True, timeout: int = 20) -> dict[str, Any]:
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        headers["MCP-Protocol-Version"] = "2025-06-18"
        if self.session_id:
            headers["MCP-Session-Id"] = self.session_id
        for name, source in self.connector.get("headers", {}).items():
            value = os.environ.get(source)
            if not value:
                raise MCPConnectorError(f"Connector '{self.connector['id']}' requires environment variable {source}.")
            headers[name] = value
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "params": params}
        request_id = None
        if expects_response:
            self.counter += 1
            request_id = self.counter
            message["id"] = request_id
        request = Request(self.connector["url"], data=json.dumps(message).encode("utf-8"), headers=headers, method="POST")
        try:
            with urlopen(request, timeout=timeout) as response:
                self.session_id = response.headers.get("MCP-Session-Id", self.session_id)
                content_type = response.headers.get("Content-Type", "")
                raw = response.read(4_000_000).decode("utf-8", errors="replace")
        except HTTPError as exc:
            detail = exc.read(4000).decode("utf-8", errors="replace")
            raise MCPConnectorError(f"MCP HTTP endpoint returned {exc.code}: {detail}") from exc
        except URLError as exc:
            raise MCPConnectorError(f"Could not reach MCP HTTP endpoint: {exc.reason}") from exc
        if not expects_response:
            return {}
        try:
            messages = _parse_sse(raw) if "text/event-stream" in content_type else [json.loads(raw)]
        except json.JSONDecodeError as exc:
            raise MCPConnectorError(f"MCP HTTP endpoint returned invalid JSON for {method}.") from exc
        for result in messages:
            if result.get("id") != request_id:
                continue
            if "error" in result:
                raise MCPConnectorError(result["error"].get("message", "MCP request failed."))
            payload = result.get("result")
            if isinstance(payload, dict):
                return payload
            raise MCPConnectorError(f"MCP server returned an invalid result for {method}.")
        raise MCPConnectorError(f"MCP HTTP endpoint did not return a response for {method}.")


def _parse_sse(raw: str) -> list[dict[str, Any]]:
    messages = []
    for event in re.split(r"\r?\n\r?\n", raw):
        data = "\n".join(line[5:].lstrip() for line in event.splitlines() if line.startswith("data:"))
        if data:
            try:
                messages.append(json.loads(data))
            except json.JSONDecodeError:
                continue
    return messages


def _connector_client(connector: dict[str, Any]) -> MCPProcess | MCPHttpClient:
    if connector.get("transport", "stdio") == "http":
        return MCPHttpClient(connector)
    return MCPProcess(connector)
