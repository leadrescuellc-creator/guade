# Copyright (c) 2026 LeadRescue LLC. All rights reserved.
from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
import subprocess
import threading
import uuid
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .creator_media import media_file, media_tools_ready, render_clip, store_thumbnail, store_upload
from .models import WorkflowSpec
from .provider import OpenAIResponsesProvider
from .runner import WorkflowRunner
from .storage import Ledger
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
WORKFLOW_ROOT = PROJECT_ROOT / "examples"


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
            provider = OpenAIResponsesProvider()
            self._json(
                {
                    "name": "GUADE",
                    "provider": "ready" if provider.api_key else "missing_key",
                    "model": provider.default_model,
                    "base_url": provider.base_url,
                    "storage": str(Ledger().home),
                    "media_tools": media_tools_ready(),
                }
            )
        elif path == "/api/workflows":
            self._json(_workflow_catalog())
        elif path == "/api/connectors":
            self._json(public_connectors())
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
        elif path == "/app.js":
            self._file("app.js", "text/javascript; charset=utf-8")
        else:
            self._json({"error": "Not found."}, 404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
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

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path
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


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(prog="guade dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    serve(args.host, args.port)
