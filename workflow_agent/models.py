# Copyright (c) 2026 LeadRescue LLC. All rights reserved.
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentSpec:
    id: str
    name: str
    instructions: str
    model: str | None = None
    tools: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class StepSpec:
    id: str
    agent: str
    task: str | None = None
    depends_on: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WorkflowSpec:
    name: str
    description: str
    agents: dict[str, AgentSpec]
    steps: list[StepSpec]
    artifact_path: str | None = None


@dataclass(frozen=True)
class ModelResult:
    text: str
    model: str
    usage: dict[str, Any] = field(default_factory=dict)
    raw_id: str | None = None
    tool_events: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class StepResult:
    step_id: str
    agent_id: str
    output: str
    model: str
    usage: dict[str, Any]
