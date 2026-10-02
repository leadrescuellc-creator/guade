# Copyright (c) 2026 LeadRescue LLC. All rights reserved.
from __future__ import annotations

import json
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ToolError(RuntimeError):
    pass


@dataclass
class ToolContext:
    workspace: Path
    allow_shell: bool = False


def schemas_for(tool_names: list[str]) -> list[dict[str, Any]]:
    schemas: list[dict[str, Any]] = []
    for name in tool_names:
        if name in TOOL_SCHEMAS:
            schemas.append(TOOL_SCHEMAS[name])
    return schemas


def execute_tool(context: ToolContext, name: str, args: dict[str, Any]) -> str:
    try:
        if name == "filesystem_list":
            return json.dumps(_list(context, args.get("path", ".")))
        if name == "filesystem_read":
            return _read(context, args["path"])
        if name == "filesystem_write":
            return _write(context, args["path"], args.get("content", ""))
        if name == "web_fetch":
            return _fetch(args["url"])
        if name == "shell_run":
            return _shell(context, args["command"], int(args.get("timeout_seconds", 30)))
        raise ToolError(f"Unknown tool: {name}")
    except Exception as exc:
        return f"TOOL_ERROR: {exc}"


def _resolve_workspace_path(context: ToolContext, raw_path: str) -> Path:
    base = context.workspace.resolve()
    target = (base / raw_path).resolve()
    if target != base and base not in target.parents:
        raise ToolError("Path escapes the run workspace.")
    return target


def _list(context: ToolContext, raw_path: str) -> list[str]:
    target = _resolve_workspace_path(context, raw_path)
    if not target.exists():
        return []
    if target.is_file():
        return [target.name]
    return sorted(item.name + ("/" if item.is_dir() else "") for item in target.iterdir())


def _read(context: ToolContext, raw_path: str) -> str:
    target = _resolve_workspace_path(context, raw_path)
    if not target.is_file():
        raise ToolError(f"Not a file: {raw_path}")
    return target.read_text(encoding="utf-8")[:20000]


def _write(context: ToolContext, raw_path: str, content: str) -> str:
    target = _resolve_workspace_path(context, raw_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} bytes to {target.relative_to(context.workspace.resolve())}"


def _fetch(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        raise ToolError("Only http(s) URLs are supported.")
    request = urllib.request.Request(url, headers={"User-Agent": "GUADE/0.1"})
    with urllib.request.urlopen(request, timeout=20) as response:
        content_type = response.headers.get("content-type", "")
        body = response.read(120000).decode("utf-8", errors="replace")
    return f"content-type: {content_type}\n\n{body[:50000]}"


def _shell(context: ToolContext, command: str, timeout_seconds: int) -> str:
    if not context.allow_shell:
        raise ToolError("shell_run requires --allow-shell.")
    completed = subprocess.run(
        command,
        cwd=context.workspace,
        shell=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=min(timeout_seconds, 120),
        check=False,
    )
    return f"exit_code: {completed.returncode}\n{completed.stdout[-20000:]}"


TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "filesystem.list": {
        "type": "function",
        "name": "filesystem_list",
        "description": "List files in the current run workspace.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Workspace-relative path."}},
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    "filesystem.read": {
        "type": "function",
        "name": "filesystem_read",
        "description": "Read a UTF-8 text file from the current run workspace.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Workspace-relative file path."}},
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    "filesystem.write": {
        "type": "function",
        "name": "filesystem_write",
        "description": "Write a UTF-8 text artifact into the current run workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Workspace-relative output path."},
                "content": {"type": "string", "description": "File content."},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
    },
    "shell.run": {
        "type": "function",
        "name": "shell_run",
        "description": "Run a shell command in the current run workspace. Disabled unless the user passes --allow-shell.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 120},
            },
            "required": ["command", "timeout_seconds"],
            "additionalProperties": False,
        },
    },
    "web.fetch": {
        "type": "function",
        "name": "web_fetch",
        "description": "Fetch a public HTTP(S) URL and return text content.",
        "parameters": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
            "additionalProperties": False,
        },
    },
}
