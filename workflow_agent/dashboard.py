# Copyright (c) 2026 LeadRescue LLC. All rights reserved.
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .provider import OpenAIResponsesProvider
from .runner import WorkflowRunner
from .storage import Ledger
from .models import WorkflowSpec
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
                }
            )
        elif path == "/api/workflows":
            self._json(_workflow_catalog())
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
        elif path == "/app.js":
            self._file("app.js", "text/javascript; charset=utf-8")
        else:
            self._json({"error": "Not found."}, 404)

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/runs":
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
