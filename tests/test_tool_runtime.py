# Copyright (c) 2026 LeadRescue LLC. All rights reserved.
from pathlib import Path

from workflow_agent.tool_runtime import ToolContext, execute_tool


def test_filesystem_write_and_read_stay_in_workspace(tmp_path: Path) -> None:
    context = ToolContext(workspace=tmp_path)
    write_result = execute_tool(context, "filesystem_write", {"path": "notes/output.txt", "content": "hello"})
    assert "Wrote 5 bytes" in write_result

    read_result = execute_tool(context, "filesystem_read", {"path": "notes/output.txt"})
    assert read_result == "hello"


def test_filesystem_rejects_workspace_escape(tmp_path: Path) -> None:
    context = ToolContext(workspace=tmp_path)
    result = execute_tool(context, "filesystem_write", {"path": "../escape.txt", "content": "nope"})
    assert result.startswith("TOOL_ERROR:")
    assert not (tmp_path.parent / "escape.txt").exists()


def test_shell_requires_explicit_enable(tmp_path: Path) -> None:
    context = ToolContext(workspace=tmp_path)
    result = execute_tool(context, "shell_run", {"command": "echo hi", "timeout_seconds": 5})
    assert "requires --allow-shell" in result
