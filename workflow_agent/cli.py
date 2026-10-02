# Copyright (c) 2026 LeadRescue LLC. All rights reserved.
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .provider import ProviderError
from .runner import WorkflowRunner
from .storage import Ledger
from .workflow import WorkflowError, load_workflow


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="guade")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="Run a workflow against a task")
    run_parser.add_argument("workflow", type=Path)
    run_parser.add_argument("task")
    run_parser.add_argument("--allow-shell", action="store_true", help="Allow agents with shell.run to execute commands")

    sub.add_parser("runs", help="List recent runs")

    show_parser = sub.add_parser("show", help="Show a run and its step outputs")
    show_parser.add_argument("run_id")

    dashboard_parser = sub.add_parser("dashboard", help="Start the local GUADE dashboard")
    dashboard_parser.add_argument("--host", default="127.0.0.1")
    dashboard_parser.add_argument("--port", type=int, default=8765)

    args = parser.parse_args(argv)

    if args.command == "dashboard":
        from .dashboard import serve

        serve(args.host, args.port)
        return

    try:
        if args.command == "run":
            workflow = load_workflow(args.workflow)
            run_id, results = WorkflowRunner(allow_shell=args.allow_shell).run(workflow, args.task)
            print(f"run_id: {run_id}")
            for result in results:
                print(f"\n=== {result.step_id} / {result.agent_id} / {result.model} ===\n")
                print(result.output.strip())
        elif args.command == "runs":
            for row in Ledger().list_runs():
                print(f"{row['id']}  {row['status']}  {row['workflow']}  {row['task'][:80]}")
        elif args.command == "show":
            run, steps = Ledger().get_run(args.run_id)
            if not run:
                raise SystemExit(f"No run found for {args.run_id}")
            print(json.dumps(dict(run), indent=2))
            for step in steps:
                print(f"\n=== {step['step_id']} / {step['agent_id']} / {step['model']} ===\n")
                print(step["output"].strip())
    except (WorkflowError, ProviderError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
