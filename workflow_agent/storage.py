# Copyright (c) 2026 LeadRescue LLC. All rights reserved.
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any


def default_home() -> Path:
    return Path(
        os.environ.get("GUADE_HOME")
        or os.environ.get("WORKFLOW_AGENT_HOME")
        or Path.home() / ".guade"
    ).expanduser()


class Ledger:
    def __init__(self, home: Path | None = None) -> None:
        self.home = home or default_home()
        self.home.mkdir(parents=True, exist_ok=True)
        self.runs_dir = self.home / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.home / "ledger.sqlite3"
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    def _init_db(self) -> None:
        with self._connect() as con:
            con.execute(
                """
                create table if not exists runs (
                    id text primary key,
                    workflow text not null,
                    task text not null,
                    status text not null,
                    created_at real not null,
                    updated_at real not null
                )
                """
            )
            con.execute(
                """
                create table if not exists steps (
                    run_id text not null,
                    step_id text not null,
                    agent_id text not null,
                    model text not null,
                    output text not null,
                    usage_json text not null,
                    created_at real not null,
                    primary key (run_id, step_id)
                )
                """
            )

    def create_run(self, run_id: str, workflow: str, task: str) -> Path:
        now = time.time()
        with self._connect() as con:
            con.execute(
                "insert into runs (id, workflow, task, status, created_at, updated_at) values (?, ?, ?, ?, ?, ?)",
                (run_id, workflow, task, "running", now, now),
            )
        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        return run_dir

    def finish_run(self, run_id: str, status: str) -> None:
        with self._connect() as con:
            con.execute("update runs set status = ?, updated_at = ? where id = ?", (status, time.time(), run_id))

    def add_step(self, run_id: str, step_id: str, agent_id: str, model: str, output: str, usage: dict[str, Any]) -> None:
        with self._connect() as con:
            con.execute(
                """
                insert into steps (run_id, step_id, agent_id, model, output, usage_json, created_at)
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, step_id, agent_id, model, output, json.dumps(usage), time.time()),
            )

    def list_runs(self) -> list[sqlite3.Row]:
        with self._connect() as con:
            return list(con.execute("select * from runs order by created_at desc limit 50"))

    def get_run(self, run_id: str) -> tuple[sqlite3.Row | None, list[sqlite3.Row]]:
        with self._connect() as con:
            run = con.execute("select * from runs where id = ?", (run_id,)).fetchone()
            steps = list(con.execute("select * from steps where run_id = ? order by created_at", (run_id,)))
        return run, steps
