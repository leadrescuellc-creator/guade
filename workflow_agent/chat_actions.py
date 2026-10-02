# Copyright (c) 2026 LeadRescue LLC. All rights reserved.
from __future__ import annotations

import difflib
import os
import json
import secrets
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any


CHAT_TOOLS = [
    {
        "type": "function",
        "name": "guade_list_files",
        "description": "List files and folders in the GUADE project. Use this to understand the project before proposing edits.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": False},
    },
    {
        "type": "function",
        "name": "guade_read_file",
        "description": "Read a UTF-8 text file inside the GUADE project.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": False},
    },
    {
        "type": "function",
        "name": "guade_propose_file_change",
        "description": "Prepare a complete replacement for a project file. The user must review and approve it before anything is written.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"], "additionalProperties": False},
    },
]

_pending: dict[str, dict[str, Any]] = {}
_blocked_parts = {".git", ".venv", "__pycache__", "node_modules"}
_blocked_names = {".env", ".env.local", "provider-settings.json", "mcp-connectors.json"}


def _path(root: Path, raw: Any) -> Path:
    if not isinstance(raw, str) or not raw or len(raw) > 500:
        raise ValueError("Enter a project-relative file path.")
    target = (root / raw).resolve()
    if target == root.resolve() or root.resolve() not in target.parents:
        raise ValueError("The path must stay inside the GUADE project.")
    relative = target.relative_to(root.resolve())
    if any(part in _blocked_parts for part in relative.parts) or target.name in _blocked_names:
        raise ValueError("GUADE chat cannot access credential or internal runtime files.")
    return target


def execute_chat_tool(root: Path, name: str, args: dict[str, Any]) -> str:
    try:
        if name == "guade_list_files":
            target = root.resolve() if args.get("path", ".") == "." else _path(root, args["path"])
            if not target.exists():
                return "Folder not found."
            if target.is_file():
                return target.name
            return "\n".join(sorted(item.name + ("/" if item.is_dir() else "") for item in target.iterdir())[:300])
        if name == "guade_read_file":
            target = _path(root, args.get("path"))
            if not target.is_file():
                return "File not found."
            if target.stat().st_size > 200_000:
                return "File is too large for chat to read (limit: 200 KB)."
            return target.read_text(encoding="utf-8")
        if name == "guade_propose_file_change":
            return json.dumps(queue_file_change(root, args.get("path"), args.get("content")))
        return "TOOL_ERROR: unknown chat action."
    except (OSError, UnicodeError, ValueError, KeyError) as exc:
        return f"TOOL_ERROR: {exc}"


def queue_file_change(root: Path, raw_path: Any, content: Any) -> dict[str, str]:
    target = _path(root, raw_path)
    if not isinstance(content, str) or len(content.encode("utf-8")) > 250_000:
        raise ValueError("Proposed file content must be text up to 250 KB.")
    relative = target.relative_to(root.resolve()).as_posix()
    before = target.read_text(encoding="utf-8") if target.is_file() else ""
    action_id = secrets.token_hex(16)
    _pending[action_id] = {"path": relative, "content": content, "before": before, "created": time.monotonic()}
    _expire_pending()
    diff = "".join(difflib.unified_diff(before.splitlines(keepends=True), content.splitlines(keepends=True), fromfile=f"a/{relative}", tofile=f"b/{relative}"))
    return {"approval_id": action_id, "path": relative, "diff": diff[:30_000], "summary": "Review this proposed file change in the chat and approve it to write."}


def propose_codex_changes(root: Path, instructions: str, prompt: str, model: str | None = None) -> tuple[str, list[dict[str, str]]]:
    executable = shutil.which("codex") or str(Path.home() / ".local/bin/codex")
    if not Path(executable).is_file() or not os.access(executable, os.X_OK):
        raise RuntimeError("Codex CLI is not installed or not available on GUADE's PATH.")
    pattern_ignore = shutil.ignore_patterns(".git", ".venv", "__pycache__", ".pytest_cache", "node_modules", ".env", ".env.*", "*.sqlite3", "*.db", "media", "runs")
    def ignore_symlinks(directory: str, names: list[str]) -> set[str]:
        ignored = pattern_ignore(directory, names)
        return ignored | {name for name in names if (Path(directory) / name).is_symlink()}
    with tempfile.TemporaryDirectory(prefix="guade-chat-stage-") as temporary:
        stage = Path(temporary) / "project"
        shutil.copytree(root, stage, ignore=ignore_symlinks)
        env = {key: os.environ[key] for key in ("PATH", "HOME", "CODEX_HOME", "TMPDIR", "TEMP", "TMP") if key in os.environ}
        git_env = {**env, "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "GUADE", "GIT_AUTHOR_EMAIL": "guade@localhost", "GIT_COMMITTER_NAME": "GUADE", "GIT_COMMITTER_EMAIL": "guade@localhost"}
        for command in (["git", "init", "-q"], ["git", "add", "-A"], ["git", "commit", "-qm", "GUADE review baseline"]):
            completed = subprocess.run(command, cwd=stage, env=git_env, capture_output=True, text=True, timeout=30, check=False)
            if completed.returncode:
                raise RuntimeError(f"Could not prepare an isolated review workspace: {completed.stderr[-1000:]}")
        output_path = Path(temporary) / "answer.txt"
        command = [executable, "exec", "--ignore-user-config", "--sandbox", "workspace-write", "--skip-git-repo-check", "--ephemeral", "--output-last-message", str(output_path)]
        if model:
            command.extend(("--model", model))
        command.append(f"{instructions}\n\n{prompt}\n\nMake requested file edits only inside this isolated project copy. Do not run commands, access networks, or claim changes are applied to the real project. Do not delete files; if deletion is necessary, explain that separately.")
        result = subprocess.run(command, cwd=stage, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=240, check=False)
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()[-2000:]
            raise RuntimeError(f"Codex CLI could not prepare changes (exit {result.returncode}): {detail or 'No error details.'}")
        changed = subprocess.run(["git", "status", "--short", "--untracked-files=all"], cwd=stage, env=git_env, capture_output=True, text=True, timeout=20, check=True).stdout.splitlines()
        paths = []
        for line in changed:
            raw = line[3:]
            if raw and " -> " not in raw and not raw.startswith("D "):
                paths.append(raw)
        if len(paths) > 20:
            raise RuntimeError("Codex proposed more than 20 files. Ask it to make a smaller change.")
        actions = []
        for raw in paths:
            staged_path = _path(stage, raw)
            if not staged_path.is_file() or staged_path.stat().st_size > 250_000:
                continue
            action = queue_file_change(root, raw, staged_path.read_text(encoding="utf-8"))
            actions.append(action)
        answer = output_path.read_text(encoding="utf-8").strip() if output_path.is_file() else ""
        if actions:
            answer += ("\n\n" if answer else "") + f"I prepared {len(actions)} file change(s) in an isolated copy. Review each diff below and apply only the ones you approve."
        elif not answer:
            answer = "I didn't prepare any file changes. Tell me what you'd like changed."
        return answer, actions


def apply_chat_action(root: Path, action_id: str) -> dict[str, str]:
    _expire_pending()
    action = _pending.pop(action_id, None)
    if action is None:
        raise ValueError("That approval expired or was already used. Ask GUADE to prepare it again.")
    target = _path(root, action["path"])
    current = target.read_text(encoding="utf-8") if target.is_file() else ""
    if current != action["before"]:
        raise ValueError("This file changed after the proposal was made. Ask GUADE to review it again before applying.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(action["content"], encoding="utf-8")
    return {"path": action["path"], "status": "applied"}


def _expire_pending() -> None:
    cutoff = time.monotonic() - 900
    for action_id in [key for key, value in _pending.items() if value["created"] < cutoff]:
        _pending.pop(action_id, None)
