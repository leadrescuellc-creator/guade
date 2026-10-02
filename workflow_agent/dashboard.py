# Copyright (c) 2026 LeadRescue LLC. All rights reserved.
from __future__ import annotations

import json
import csv
import mimetypes
import os
import re
import shutil
import subprocess
import threading
import secrets
import uuid
import urllib.request
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .creator_media import media_file, media_tools_ready, render_clip, store_thumbnail, store_upload
from .models import WorkflowSpec
from .provider import (
    ProviderError,
    create_provider,
    read_provider_settings,
    validate_provider_settings,
    write_provider_settings,
)
from .runner import WorkflowRunner
from .storage import Ledger
from .terminal import LocalTerminal
from .mcp_registry import search_registry
from .chat_actions import CHAT_TOOLS, apply_chat_action, execute_chat_tool, propose_codex_changes
from .mcp_connectors import (
    MCPConnectorError,
    MCPToolSession,
    public_connectors,
    read_connectors,
    validate_connector,
    write_connectors,
)
from .workflow import load_workflow

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = PROJECT_ROOT / "web"
OPPORTUNITY_FILE = PROJECT_ROOT / "data" / "creator_monetization.csv"
WORKFLOW_ROOT = PROJECT_ROOT / "examples"
_TERMINAL_SESSIONS: dict[str, LocalTerminal] = {}
_TERMINAL_LOCK = threading.Lock()


def _workflow_catalog() -> list[dict[str, Any]]:
    catalog = []
    for path in sorted(WORKFLOW_ROOT.glob("*.json")):
        workflow = load_workflow(path)
        catalog.append(
            {
                "id": path.stem,
                "name": workflow.name,
                "description": workflow.description,
                "steps": len(workflow.steps),
                "agents": len(workflow.agents),
                "agent_list": [
                    {"id": agent.id, "name": agent.name, "tools": agent.tools}
                    for agent in workflow.agents.values()
                ],
                "step_names": [step.id for step in workflow.steps],
            }
        )
    return catalog


def _run_record(run_id: str) -> dict[str, Any] | None:
    if not re.fullmatch(r"[a-f0-9]{12}", run_id):
        return None
    ledger = Ledger()
    run, steps = ledger.get_run(run_id)
    if run is None:
        return None
    run_dir = ledger.runs_dir / run_id
    artifacts = []
    if run_dir.is_dir():
        for path in sorted(run_dir.rglob("*")):
            if not path.is_file() or path.name in {"workflow.json", "task.txt", "prompt.txt", "meta.json", "output.txt"}:
                continue
            try:
                relative = path.relative_to(run_dir).as_posix()
                raw = path.read_bytes()
                artifacts.append(
                    {
                        "path": relative,
                        "size": len(raw),
                        "text": raw.decode("utf-8") if len(raw) <= 100_000 else None,
                    }
                )
            except (OSError, UnicodeDecodeError):
                continue
    error_path = run_dir / "error.txt"
    return {
        **dict(run),
        "steps": [
            {
                **dict(step),
                "usage": json.loads(step["usage_json"]),
            }
            for step in steps
        ],
        "artifacts": artifacts,
        "error": error_path.read_text(encoding="utf-8") if error_path.is_file() else None,
    }


def _launch_run(run_id: str, workflow: WorkflowSpec, task: str, allow_shell: bool) -> None:
    try:
        WorkflowRunner(allow_shell=allow_shell).run(workflow, task, run_id=run_id)
    except Exception as exc:
        ledger = Ledger()
        ledger.finish_run(run_id, "failed")
        run_dir = ledger.runs_dir / run_id
        (run_dir / "error.txt").write_text(f"{type(exc).__name__}: {exc}", encoding="utf-8")


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "GUADE/0.1"

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/status":
            provider = create_provider("workflow")
            settings = read_provider_settings()
            provider_status = "ready" if provider.api_key else "missing_key"
            if provider.provider_name == "ollama":
                try:
                    with urllib.request.urlopen(f"{provider.base_url}/models", timeout=1):
                        provider_status = "ready"
                except Exception:
                    provider_status = "offline"
            elif provider.provider_name == "codex":
                provider_status = "ready" if provider.api_key else "not_installed"
            self._json(
                {
                    "name": "GUADE",
                    "provider": provider_status,
                    "provider_name": provider.provider_name,
                    "model": provider.default_model,
                    "base_url": provider.base_url,
                    "assistant_provider": settings["assistant"]["provider"],
                    "assistant_model": settings["assistant"]["model"],
                    "storage": str(Ledger().home),
                    "media_tools": media_tools_ready(),
                }
            )
        elif path == "/api/settings/provider":
            self._json(read_provider_settings())
        elif path == "/api/terminal/read":
            session_id = parse_qs(urlparse(self.path).query).get("session", [""])[0]
            with _TERMINAL_LOCK:
                terminal = _TERMINAL_SESSIONS.get(session_id)
            if terminal is None or not re.fullmatch(r"[a-f0-9]{32}", session_id):
                self._json({"error": "Terminal session not found."}, 404)
            else:
                self._json(terminal.read())
        elif path == "/api/workflows":
            self._json(_workflow_catalog())
        elif path == "/api/opportunities":
            query = parse_qs(urlparse(self.path).query).get("search", [""])[0].strip().lower()[:100]
            try:
                with OPPORTUNITY_FILE.open(encoding="utf-8-sig", newline="") as source:
                    rows = list(csv.DictReader(source))
                opportunities = [
                    {"name": row["App Name"].strip(), "model": row["How Money Is Made"].strip()}
                    for row in rows
                    if row.get("App Name", "").strip() and row.get("How Money Is Made", "").strip()
                ]
                if query:
                    opportunities = [item for item in opportunities if query in f"{item['name']} {item['model']}".lower()]
                self._json({"opportunities": opportunities, "total": len(rows), "source": OPPORTUNITY_FILE.name})
            except (OSError, KeyError, csv.Error) as exc:
                self._json({"error": f"Could not read opportunity library: {exc}"}, 500)
        elif path == "/api/connectors":
            self._json(public_connectors())
        elif path == "/api/mcp-catalog":
            query = parse_qs(urlparse(self.path).query).get("search", [""])[0]
            try:
                self._json({"servers": search_registry(query)})
            except RuntimeError as exc:
                self._json({"error": str(exc)}, 502)
        elif path.startswith("/api/connectors/") and path.endswith("/inspect"):
            connector_id = path.removeprefix("/api/connectors/").removesuffix("/inspect").strip("/")
            connector = next((item for item in read_connectors() if item["id"] == connector_id), None)
            if connector is None:
                self._json({"error": "Connector not found."}, 404)
            else:
                try:
                    tools = MCPToolSession({}).inspect(connector)
                    self._json(
                        {
                            "tools": [
                                {"name": item.get("name"), "description": item.get("description", "")}
                                for item in tools
                            ]
                        }
                    )
                except MCPConnectorError as exc:
                    self._json({"error": str(exc)}, 400)
        elif path.startswith("/media/"):
            self._serve_media(path)
        elif path == "/api/runs":
            self._json([dict(row) for row in Ledger().list_runs()])
        elif path.startswith("/api/runs/"):
            run_id = path.removeprefix("/api/runs/")
            record = _run_record(run_id)
            if record is None:
                self._json({"error": "Run not found."}, 404)
            else:
                self._json(record)
        elif path in {"/", "/index.html"}:
            self._file("index.html", "text/html; charset=utf-8")
        elif path == "/app.css":
            self._file("app.css", "text/css; charset=utf-8")
        elif path == "/operations.css":
            self._file("operations.css", "text/css; charset=utf-8")
        elif path == "/grants.css":
            self._file("grants.css", "text/css; charset=utf-8")
        elif path == "/chat.css":
            self._file("chat.css", "text/css; charset=utf-8")
        elif path == "/ui-overrides.css":
            self._file("ui-overrides.css", "text/css; charset=utf-8")
        elif path == "/league.css":
            self._file("league.css", "text/css; charset=utf-8")
        elif path == "/saint-icons.svg":
            self._file("saint-icons.svg", "image/svg+xml; charset=utf-8")
        elif path == "/app.js":
            self._file("app.js", "text/javascript; charset=utf-8")
        elif path == "/guadalupe-icon.png":
            self._file("guadalupe-icon.png", "image/png")
        else:
            self._json({"error": "Not found."}, 404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path.startswith("/api/terminal/"):
            if not self._same_origin_request():
                self._json({"error": "Terminal requests must come from the local GUADE app."}, 403)
                return
            if path == "/api/terminal/start":
                self._start_terminal()
            elif path == "/api/terminal/input":
                self._send_terminal_input()
            else:
                self._json({"error": "Not found."}, 404)
            return
        if path.startswith("/api/chat/actions/"):
            self._approve_chat_action(path)
            return
        if path == "/api/settings/provider":
            self._save_provider_settings()
            return
        if path == "/api/chat":
            self._chat()
            return
        if path == "/api/media/upload":
            self._upload_video()
            return
        if path == "/api/media/clips":
            self._render_clip()
            return
        if path == "/api/media/thumbnails":
            self._save_thumbnail()
            return
        if path == "/api/connectors":
            self._save_connector()
            return
        if path != "/api/runs":
            self._json({"error": "Not found."}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 1_000_000:
                raise ValueError("Request body must be between 1 byte and 1 MB.")
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            workflow_id = body.get("workflow")
            task = body.get("task")
            if not isinstance(workflow_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]+", workflow_id):
                raise ValueError("Choose a valid workflow.")
            workflow_path = (WORKFLOW_ROOT / f"{workflow_id}.json").resolve()
            if workflow_path.parent != WORKFLOW_ROOT.resolve() or not workflow_path.is_file():
                raise ValueError("Workflow not found.")
            if not isinstance(task, str) or not task.strip():
                raise ValueError("Enter a task to run.")
            if len(task) > 30_000:
                raise ValueError("Task must be 30,000 characters or fewer.")
            workflow = load_workflow(workflow_path)
            connector_grants = body.get("connector_grants", {})
            if not isinstance(connector_grants, dict):
                raise ValueError("Agent connector grants must be an object.")
            known_agents = set(workflow.agents)
            if any(agent_id not in known_agents for agent_id in connector_grants):
                raise ValueError("Connector grant references an unknown workflow agent.")
            configured_connectors = {item["id"] for item in read_connectors()}
            agents = dict(workflow.agents)
            for agent_id, connector_ids in connector_grants.items():
                if not isinstance(connector_ids, list) or any(connector_id not in configured_connectors for connector_id in connector_ids):
                    raise ValueError(f"Invalid MCP connector grant for agent {agent_id}.")
                current = agents[agent_id]
                tools = list(current.tools)
                tools.extend(f"mcp.{connector_id}" for connector_id in connector_ids if f"mcp.{connector_id}" not in tools)
                agents[agent_id] = replace(current, tools=tools)
            workflow = replace(workflow, agents=agents)
            run_id = uuid.uuid4().hex[:12]
            Ledger().create_run(run_id, workflow.name, task.strip())
            thread = threading.Thread(
                target=_launch_run,
                args=(run_id, workflow, task.strip(), bool(body.get("allow_shell", False))),
                daemon=True,
            )
            thread.start()
            self._json({"run_id": run_id, "status": "running"}, 202)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc)}, 400)
        except Exception as exc:
            self._json({"error": f"Unable to start run: {exc}"}, 500)

    def _chat(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 150_000:
                raise ValueError("Chat request must be between 1 byte and 150 KB.")
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            messages = body.get("messages")
            if not isinstance(messages, list) or not messages or len(messages) > 20:
                raise ValueError("Send between 1 and 20 chat messages.")
            clean = []
            for message in messages:
                if not isinstance(message, dict) or message.get("role") not in {"user", "assistant"}:
                    raise ValueError("Chat messages must have user or assistant roles.")
                content = message.get("content")
                if not isinstance(content, str) or not content.strip() or len(content) > 8_000:
                    raise ValueError("Each chat message must contain up to 8,000 characters.")
                clean.append({"role": message["role"], "content": content.strip()})
            if clean[-1]["role"] != "user":
                raise ValueError("The latest chat message must be from you.")

            status = create_provider("assistant")
            context = {
                "application": "GUADE, a local-first workflow and creator operations app by LeadRescue LLC",
                "model": status.default_model,
                "model_key_configured": bool(status.api_key),
                "workflows": [{"id": item["id"], "name": item["name"], "description": item["description"]} for item in _workflow_catalog()],
                "connectors": public_connectors(),
                "media_tools_ready": media_tools_ready(),
                "storage": str(Ledger().home),
            }
            if not status.api_key and status.provider_name == "codex":
                self._json({"error": "Codex CLI is not installed or not available on GUADE's PATH."}, 503)
                return
            if not status.api_key:
                self._json({
                    "error": "Chat replies need an OpenAI API key. In a terminal, run `export OPENAI_API_KEY='your-key'`, then start GUADE from that same terminal with `bin/guade-desktop` (or `python3 -m workflow_agent dashboard`). The key is not saved by GUADE."
                }, 503)
                return
            instructions = (
                "You are GUADE Main Player, the in-app operating agent for GUADE by LeadRescue LLC. "
                "Act like the active player inside the command center: read the board, choose useful missions, operate workflows, "
                "improve project files when asked, and keep momentum toward concrete artifacts. "
                "Help directly with setup, model configuration, MCP connections, choosing workflows, creator tools, "
                "and terminal commands. Think through the user's goal, pick the best path, and make the next move obvious. "
                "Keep replies simple and concise. When choices help, offer at most four clearly labeled A/B/C/D options; "
                "when steps help, use a short numbered 1-4 list. Do not force options when a direct answer is better. "
                "Use the supplied live GUADE context instead of generic guesses. "
                "Treat the user as commander: take initiative on local, reversible project work, but ask before risky, credential-sensitive, paid, publishing, or external-account actions. "
                "Distinguish verified app behavior from suggestions, never promise income, and never claim to have "
                "changed files, run commands, connected accounts, or published listings unless a tool result confirms it. "
                "When Codex CLI is the assistant provider, Codex may inspect and edit project files directly with workspace-write access when the user asks for changes. "
                "When another assistant provider uses chat tools, file changes are proposed first and require explicit approval in chat before they are applied. "
                "Never use file tools for secrets, credentials, or files outside the GUADE project. Never run shell commands from non-Codex chat tools. "
                "Give commands for the user to review and run in the separate local terminal panel; explain destructive or credential-sensitive "
                "commands before suggesting them. Never ask the user to paste API keys into chat. If the model key "
                "is missing, clearly say chat replies require OPENAI_API_KEY and show how to set it in a terminal. "
                "For connector secrets, use environment variable names and explain restarting GUADE after setting them. "
                f"Current GUADE context (JSON): {json.dumps(context, ensure_ascii=True)}"
            )
            prompt = "Conversation so far:\n" + "\n".join(
                f"{item['role'].upper()}: {item['content']}" for item in clean[-16:]
            )
            actions = []
            requested_change = re.search(r"\b(add|build|change|configure|connect|create|edit|fix|implement|make|modify|remove|rename|rewrite|set up|setup|update|wire|write)\b", clean[-1]["content"].lower())
            if status.provider_name == "codex" and requested_change:
                answer, actions = propose_codex_changes(PROJECT_ROOT, instructions, prompt, read_provider_settings()["assistant"]["model"] or None)
            elif status.provider_name == "codex":
                answer = status.complete(instructions, prompt).text
            else:
                result = status.complete_with_tools(
                    instructions,
                    prompt,
                    CHAT_TOOLS,
                    lambda name, args: execute_chat_tool(PROJECT_ROOT, name, args),
                )
                answer = result.text
                for event in result.tool_events:
                    if event.get("name") != "guade_propose_file_change":
                        continue
                    try:
                        proposal = json.loads(event.get("output", ""))
                    except json.JSONDecodeError:
                        continue
                    if isinstance(proposal, dict) and re.fullmatch(r"[a-f0-9]{32}", str(proposal.get("approval_id", ""))):
                        actions.append(proposal)
            self._json({"answer": answer, "actions": actions})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc)}, 400)
        except ProviderError as exc:
            self._json({"error": str(exc)}, 503)
        except Exception as exc:
            self._json({"error": str(exc)}, 503)

    def _save_provider_settings(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 20_000:
                raise ValueError("Provider settings must be under 20 KB.")
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            settings = validate_provider_settings(body)
            write_provider_settings(settings)
            self._json(settings)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc)}, 400)

    def _approve_chat_action(self, path: str) -> None:
        if not self._same_origin_request():
            self._json({"error": "Approvals must come from the local GUADE app."}, 403)
            return
        match = re.fullmatch(r"/api/chat/actions/([a-f0-9]{32})/approve", path)
        if not match:
            self._json({"error": "Not found."}, 404)
            return
        try:
            self._json(apply_chat_action(PROJECT_ROOT, match.group(1)))
        except (ValueError, OSError) as exc:
            self._json({"error": str(exc)}, 400)

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path
        terminal_prefix = "/api/terminal/"
        if path.startswith(terminal_prefix):
            if not self._same_origin_request():
                self._json({"error": "Terminal requests must come from the local GUADE app."}, 403)
                return
            session_id = path.removeprefix(terminal_prefix)
            with _TERMINAL_LOCK:
                terminal = _TERMINAL_SESSIONS.pop(session_id, None)
            if terminal is None:
                self._json({"error": "Terminal session not found."}, 404)
            else:
                terminal.close()
                self._json({"stopped": True})
            return
        prefix = "/api/connectors/"
        if not path.startswith(prefix):
            self._json({"error": "Not found."}, 404)
            return
        connector_id = path.removeprefix(prefix)
        connectors = read_connectors()
        remaining = [item for item in connectors if item.get("id") != connector_id]
        if len(remaining) == len(connectors):
            self._json({"error": "Connector not found."}, 404)
            return
        write_connectors(remaining)
        self._json({"removed": connector_id})

    def _same_origin_request(self) -> bool:
        origin = self.headers.get("Origin")
        host = self.headers.get("Host", "").lower()
        if not origin or not host:
            return False
        parsed = urlparse(origin)
        return parsed.scheme in {"http", "https"} and parsed.netloc.lower() == host and parsed.hostname in {"127.0.0.1", "localhost", "::1"}

    def _start_terminal(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 1000:
                raise ValueError("Confirm the terminal disclosure to start a local shell.")
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            if body.get("confirmed") is not True:
                raise ValueError("Confirm that terminal commands run with your Linux account permissions.")
            terminal = LocalTerminal(PROJECT_ROOT)
            terminal.start()
            session_id = secrets.token_hex(16)
            with _TERMINAL_LOCK:
                if len(_TERMINAL_SESSIONS) >= 4:
                    _, oldest = _TERMINAL_SESSIONS.popitem()
                    oldest.close()
                _TERMINAL_SESSIONS[session_id] = terminal
            self._json({"session": session_id, "cwd": str(PROJECT_ROOT)}, 201)
        except (ValueError, TypeError, json.JSONDecodeError, OSError, RuntimeError) as exc:
            self._json({"error": str(exc)}, 400)

    def _send_terminal_input(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 10_000:
                raise ValueError("Terminal input must be under 10 KB.")
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            session_id = str(body.get("session", ""))
            value = body.get("input")
            if not re.fullmatch(r"[a-f0-9]{32}", session_id) or not isinstance(value, str) or len(value) > 8_192:
                raise ValueError("Terminal session or input is invalid.")
            with _TERMINAL_LOCK:
                terminal = _TERMINAL_SESSIONS.get(session_id)
            if terminal is None:
                raise ValueError("Terminal session not found. Start a new terminal session.")
            raw = body.get("raw") is True
            terminal.send(value if raw or value.endswith("\n") else value + "\n")
            self._json({"sent": True})
        except (ValueError, TypeError, json.JSONDecodeError, OSError, RuntimeError) as exc:
            self._json({"error": str(exc)}, 400)

    def _save_connector(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 100_000:
                raise ValueError("Connector configuration must be under 100 KB.")
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            connector = validate_connector(body)
            connectors = read_connectors()
            replaced = False
            for index, existing in enumerate(connectors):
                if existing.get("id") == connector["id"]:
                    connectors[index] = connector
                    replaced = True
                    break
            if not replaced:
                connectors.append(connector)
            write_connectors(connectors)
            saved = next(item for item in public_connectors() if item["id"] == connector["id"])
            self._json(saved, 201 if not replaced else 200)
        except (ValueError, TypeError, json.JSONDecodeError, MCPConnectorError) as exc:
            self._json({"error": str(exc)}, 400)

    def _upload_video(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            filename = parse_qs(urlparse(self.path).query).get("filename", [""])[0]
            self._json(store_upload(self.rfile, filename, length), 201)
        except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
            self._json({"error": str(exc)}, 400)

    def _render_clip(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 100_000:
                raise ValueError("Clip settings are invalid.")
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            result = render_clip(
                str(body.get("file_id", "")),
                float(body["start"]),
                float(body["end"]),
                str(body.get("aspect", "vertical")),
            )
            self._json(result, 201)
        except (ValueError, TypeError, KeyError, json.JSONDecodeError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
            self._json({"error": str(exc)}, 400)

    def _save_thumbnail(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            filename = parse_qs(urlparse(self.path).query).get("filename", ["thumbnail"])[0]
            self._json(store_thumbnail(self.rfile, filename, length), 201)
        except (ValueError, OSError) as exc:
            self._json({"error": str(exc)}, 400)

    def _serve_media(self, request_path: str) -> None:
        parts = request_path.split("/")
        if len(parts) != 4:
            self._json({"error": "Media file not found."}, 404)
            return
        path = media_file(parts[2], parts[3])
        if path is None:
            self._json({"error": "Media file not found."}, 404)
            return
        size = path.stat().st_size
        start, end, status = 0, size - 1, 200
        byte_range = self.headers.get("Range")
        if byte_range:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", byte_range.strip())
            if not match:
                self.send_error(416)
                return
            left, right = match.groups()
            if left:
                start = int(left)
                end = int(right) if right else size - 1
            elif right:
                start = max(0, size - int(right))
            if start >= size or end < start:
                self.send_error(416)
                return
            end = min(end, size - 1)
            status = 206
        remaining = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(remaining))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "private, max-age=3600")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with path.open("rb") as media:
            media.seek(start)
            while remaining:
                block = media.read(min(1024 * 1024, remaining))
                if not block:
                    break
                self.wfile.write(block)
                remaining -= len(block)

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def _json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, filename: str, content_type: str) -> None:
        body = (WEB_ROOT / filename).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    print(f"GUADE dashboard listening at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nGUADE dashboard stopped.")
    finally:
        server.server_close()
        with _TERMINAL_LOCK:
            terminals = list(_TERMINAL_SESSIONS.values())
            _TERMINAL_SESSIONS.clear()
        for terminal in terminals:
            terminal.close()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(prog="guade dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    serve(args.host, args.port)
