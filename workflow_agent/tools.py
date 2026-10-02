# Copyright (c) 2026 LeadRescue LLC. All rights reserved.
from __future__ import annotations

TOOL_REGISTRY = {
    "filesystem.list": "List files in the current run workspace.",
    "filesystem.read": "Read files from the current workflow workspace and explicitly provided context paths.",
    "filesystem.write": "Write artifacts into the current workflow workspace.",
    "shell.run": "Run shell commands in the run workspace only when --allow-shell is passed.",
    "shell.propose": "Propose shell commands for human approval; commands are not executed autonomously.",
    "web.fetch": "Fetch public HTTP(S) pages and return text.",
    "web.research": "Use the model's own knowledge unless a workflow grants web.fetch.",
}


def describe_tools(tool_names: list[str]) -> str:
    if not tool_names:
        return "No tools granted."
    lines = []
    for name in tool_names:
        description = TOOL_REGISTRY.get(name, "Unknown tool grant. Treat as unavailable.")
        lines.append(f"- {name}: {description}")
    return "\n".join(lines)
