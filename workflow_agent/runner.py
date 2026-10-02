# Copyright (c) 2026 LeadRescue LLC. All rights reserved.
from __future__ import annotations

import json
import uuid
from pathlib import Path

from .models import StepResult, WorkflowSpec
from .mcp_connectors import MCPToolSession
from .provider import OpenAIResponsesProvider
from .storage import Ledger
from .tool_runtime import ToolContext, execute_tool, schemas_for
from .tools import describe_tools
from .workflow import workflow_to_dict


class WorkflowRunner:
    def __init__(
        self,
        provider: OpenAIResponsesProvider | None = None,
        ledger: Ledger | None = None,
        allow_shell: bool = False,
    ) -> None:
        self.provider = provider or OpenAIResponsesProvider()
        self.ledger = ledger or Ledger()
        self.allow_shell = allow_shell

    def run(self, workflow: WorkflowSpec, user_task: str, run_id: str | None = None) -> tuple[str, list[StepResult]]:
        if run_id is None:
            run_id = uuid.uuid4().hex[:12]
            run_dir = self.ledger.create_run(run_id, workflow.name, user_task)
        else:
            run_dir = self.ledger.runs_dir / run_id
            if not run_dir.is_dir():
                run_dir = self.ledger.create_run(run_id, workflow.name, user_task)
        (run_dir / "workflow.json").write_text(json.dumps(workflow_to_dict(workflow), indent=2), encoding="utf-8")
        (run_dir / "task.txt").write_text(user_task, encoding="utf-8")

        outputs: dict[str, StepResult] = {}
        results: list[StepResult] = []
        mcp_session = MCPToolSession(workflow.agents)
        try:
            mcp_session.start()
            for step in workflow.steps:
                agent = workflow.agents[step.agent]
                prompt = self._build_prompt(user_task, step.task, step.depends_on, outputs, agent.tools)
                step_dir = run_dir / step.id
                step_dir.mkdir()
                (step_dir / "prompt.txt").write_text(prompt, encoding="utf-8")

                tool_context = ToolContext(workspace=run_dir, allow_shell=self.allow_shell)
                model_result = self.provider.complete_with_tools(
                    agent.instructions,
                    prompt,
                    schemas_for(agent.tools) + mcp_session.schemas_for(agent.tools),
                    lambda name, args: (
                        mcp_session.execute(name, args)
                        if mcp_session.handles(name)
                        else execute_tool(tool_context, name, args)
                    ),
                    agent.model,
                )
                result = StepResult(
                    step_id=step.id,
                    agent_id=agent.id,
                    output=model_result.text,
                    model=model_result.model,
                    usage=model_result.usage,
                )
                outputs[step.id] = result
                results.append(result)
                (step_dir / "output.txt").write_text(result.output, encoding="utf-8")
                (step_dir / "meta.json").write_text(
                    json.dumps(
                        {
                            "agent": agent.__dict__,
                            "model": result.model,
                            "usage": result.usage,
                            "tool_events": model_result.tool_events,
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                self.ledger.add_step(run_id, step.id, agent.id, result.model, result.output, result.usage)
            self.ledger.finish_run(run_id, "succeeded")
        except Exception:
            self.ledger.finish_run(run_id, "failed")
            raise
        finally:
            mcp_session.close()
        return run_id, results

    def _build_prompt(
        self,
        user_task: str,
        step_task: str | None,
        depends_on: list[str],
        outputs: dict[str, StepResult],
        tool_names: list[str],
    ) -> str:
        sections = [
            f"USER TASK:\n{user_task}",
            f"THIS STEP:\n{step_task or 'Complete your part of the workflow.'}",
            f"GRANTED TOOLS:\n{describe_tools(tool_names)}",
        ]
        if depends_on:
            handoffs = []
            for dep in depends_on:
                handoffs.append(f"## Output from {dep}\n{outputs[dep].output}")
            sections.append("UPSTREAM HANDOFFS:\n" + "\n\n".join(handoffs))
        sections.append(
            "RESPONSE CONTRACT:\n"
            "Return concrete work product. Include assumptions, decisions, and next actions only when they are useful. "
            "If you need a dangerous or external action, propose it explicitly instead of pretending it happened."
        )
        return "\n\n".join(sections)
