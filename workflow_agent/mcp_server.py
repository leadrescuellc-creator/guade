# Copyright (c) 2026 LeadRescue LLC. All rights reserved.
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Any

from .provider import ProviderError
from .runner import WorkflowRunner
from .storage import Ledger
from .workflow import WorkflowError, load_workflow

PROJECT_ROOT = Path(__file__).resolve().parents[1]

TOOLS: list[dict[str, Any]] = [
    {
        "name": "guade_list_workflows",
        "description": "List example workflow definitions available to GUADE.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "guade_run",
        "description": "Run a local GUADE workflow against a task and return the step outputs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workflow": {
                    "type": "string",
                    "description": "Workflow JSON path. Relative paths resolve from the GUADE project directory.",
                    "default": "examples/local_builder.json",
                },
                "task": {"type": "string", "description": "The user task to run through the workflow."},
                "allow_shell": {
                    "type": "boolean",
                    "description": "Allow workflows granted shell.run to execute shell commands.",
                    "default": False,
                },
            },
            "required": ["task"],
            "additionalProperties": False,
        },
    },
    {
        "name": "guade_runs",
        "description": "List recent GUADE runs from the local SQLite ledger.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "guade_show",
        "description": "Show one GUADE run and its step outputs.",
        "inputSchema": {
            "type": "object",
            "properties": {"run_id": {"type": "string"}},
            "required": ["run_id"],
            "additionalProperties": False,
        },
    },
]


def main() -> None:
    while True:
        message = _read_message()
        if message is None:
            return
        response = _handle_message(message)
        if response is not None:
            _write_message(response)


def _handle_message(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    message_id = message.get("id")
    try:
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": message_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "GUADE", "version": "0.1.0"},
                },
            }
        if method == "ping":
            return {"jsonrpc": "2.0", "id": message_id, "result": {}}
        if method == "notifications/initialized":
            return None
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": message_id, "result": {"tools": TOOLS}}
        if method == "tools/call":
            params = message.get("params") or {}
            result = _call_tool(params.get("name"), params.get("arguments") or {})
            return {"jsonrpc": "2.0", "id": message_id, "result": {"content": [{"type": "text", "text": result}]}}
        if message_id is None:
            return None
        return _error(message_id, -32601, f"Method not found: {method}")
    except Exception as exc:
        detail = f"{exc}\n\n{traceback.format_exc()}"
        return _error(message_id, -32000, detail)


def _call_tool(name: str, args: dict[str, Any]) -> str:
    if name in ("guade_list_workflows", "workflow_agent_list_workflows"):
        examples = sorted((PROJECT_ROOT / "examples").glob("*.json"))
        return "\n".join(str(path.relative_to(PROJECT_ROOT)) for path in examples) or "No workflows found."

    if name in ("guade_run", "workflow_agent_run"):
        workflow_arg = args.get("workflow") or "examples/local_builder.json"
        workflow = load_workflow(_resolve_project_path(workflow_arg))
        run_id, results = WorkflowRunner(allow_shell=bool(args.get("allow_shell", False))).run(workflow, args["task"])
        parts = [f"run_id: {run_id}"]
        for result in results:
            parts.append(f"=== {result.step_id} / {result.agent_id} / {result.model} ===\n{result.output.strip()}")
        return "\n\n".join(parts)

    if name in ("guade_runs", "workflow_agent_runs"):
        rows = Ledger().list_runs()
        if not rows:
            return "No GUADE runs yet."
        return "\n".join(f"{row['id']}  {row['status']}  {row['workflow']}  {row['task'][:100]}" for row in rows)

    if name in ("guade_show", "workflow_agent_show"):
        run, steps = Ledger().get_run(args["run_id"])
        if not run:
            return f"No run found for {args['run_id']}."
        parts = [json.dumps(dict(run), indent=2)]
        for step in steps:
            parts.append(f"=== {step['step_id']} / {step['agent_id']} / {step['model']} ===\n{step['output'].strip()}")
        return "\n\n".join(parts)

    raise ValueError(f"Unknown tool: {name}")


def _resolve_project_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"No workflow file found: {raw_path}")
    return path


def _error(message_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


def _read_message() -> dict[str, Any] | None:
    line = sys.stdin.buffer.readline()
    if not line:
        return None
    return json.loads(line.decode("utf-8"))


def _write_message(message: dict[str, Any]) -> None:
    body = json.dumps(message, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(body + b"\n")
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    try:
        main()
    except (BrokenPipeError, KeyboardInterrupt, ProviderError, WorkflowError):
        raise SystemExit(0)
