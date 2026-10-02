# Copyright (c) 2026 LeadRescue LLC. All rights reserved.
from pathlib import Path

import pytest

from workflow_agent.workflow import WorkflowError, load_workflow


def test_example_workflow_loads() -> None:
    workflow = load_workflow(Path("examples/research_build.json"))
    assert workflow.name == "research-build-review"
    assert [step.id for step in workflow.steps] == ["research", "build", "review"]


def test_game_preproduction_stops_at_blueprint() -> None:
    workflow = load_workflow(Path("examples/game_preproduction.json"))
    assert workflow.name == "game-preproduction-blueprint"
    assert [step.id for step in workflow.steps] == ["discovery", "blueprint", "review"]
    assert "do not write implementation code" in workflow.agents["game_designer"].instructions.lower()
    assert "approval gate" in workflow.steps[-1].task.lower()


def test_later_dependency_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(
        """
        {
          "agents": [{"id": "a", "instructions": "x"}],
          "steps": [
            {"id": "one", "agent": "a", "depends_on": ["two"]},
            {"id": "two", "agent": "a"}
          ]
        }
        """,
        encoding="utf-8",
    )
    with pytest.raises(WorkflowError):
        load_workflow(path)
