# Copyright (c) 2026 LeadRescue LLC. All rights reserved.
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import AgentSpec, StepSpec, WorkflowSpec


class WorkflowError(ValueError):
    pass


def load_workflow(path: Path) -> WorkflowSpec:
    data = json.loads(path.read_text(encoding="utf-8"))
    agents = {
        item["id"]: AgentSpec(
            id=item["id"],
            name=item.get("name", item["id"]),
            instructions=item["instructions"],
            model=item.get("model"),
            tools=list(item.get("tools", [])),
        )
        for item in data.get("agents", [])
    }
    steps = [
        StepSpec(
            id=item["id"],
            agent=item["agent"],
            task=item.get("task"),
            depends_on=list(item.get("depends_on", [])),
        )
        for item in data.get("steps", [])
    ]
    workflow = WorkflowSpec(
        name=data.get("name") or path.stem,
        description=data.get("description", ""),
        agents=agents,
        steps=steps,
        artifact_path=data.get("artifact_path"),
    )
    validate_workflow(workflow)
    return workflow


def validate_workflow(workflow: WorkflowSpec) -> None:
    if not workflow.agents:
        raise WorkflowError("Workflow must define at least one agent.")
    if not workflow.steps:
        raise WorkflowError("Workflow must define at least one step.")
    if workflow.artifact_path:
        artifact = Path(workflow.artifact_path)
        if artifact.is_absolute() or ".." in artifact.parts:
            raise WorkflowError("Workflow artifact_path must stay inside the run workspace.")

    seen: set[str] = set()
    for step in workflow.steps:
        if step.id in seen:
            raise WorkflowError(f"Duplicate step id: {step.id}")
        if step.agent not in workflow.agents:
            raise WorkflowError(f"Step {step.id} references unknown agent {step.agent}")
        missing = [dep for dep in step.depends_on if dep not in seen]
        if missing:
            raise WorkflowError(f"Step {step.id} depends on missing or later step(s): {', '.join(missing)}")
        seen.add(step.id)


def workflow_to_dict(workflow: WorkflowSpec) -> dict[str, Any]:
    return {
        "name": workflow.name,
        "description": workflow.description,
        "agents": [agent.__dict__ for agent in workflow.agents.values()],
        "steps": [step.__dict__ for step in workflow.steps],
        "artifact_path": workflow.artifact_path,
    }
