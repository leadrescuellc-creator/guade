# Copyright (c) 2026 LeadRescue LLC. All rights reserved.
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Callable

from .models import ModelResult


class ProviderError(RuntimeError):
    pass


class OpenAIResponsesProvider:
    def __init__(self, api_key: str | None = None, base_url: str | None = None, default_model: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.default_model = default_model or os.environ.get("OPENAI_MODEL") or "gpt-5-mini"

    def complete(self, instructions: str, prompt: str, model: str | None = None) -> ModelResult:
        return self.complete_with_tools(instructions, prompt, [], lambda _name, _args: "Tool unavailable.", model)

    def complete_with_tools(
        self,
        instructions: str,
        prompt: str,
        tools: list[dict[str, Any]],
        tool_executor: Callable[[str, dict[str, Any]], str],
        model: str | None = None,
        max_tool_rounds: int = 6,
    ) -> ModelResult:
        if not self.api_key:
            raise ProviderError("OPENAI_API_KEY is not set. Refusing to simulate a model-backed agent run.")

        selected_model = model or self.default_model
        input_items: str | list[dict[str, Any]] = prompt
        payload = {
            "model": selected_model,
            "instructions": instructions,
            "input": input_items,
            "store": False,
        }
        if tools:
            payload["tools"] = tools

        tool_events: list[dict[str, Any]] = []
        body = self._post_response(payload)

        for _ in range(max_tool_rounds):
            calls = _extract_function_calls(body)
            if not calls:
                return ModelResult(
                    text=_extract_output_text(body),
                    model=body.get("model", selected_model),
                    usage=body.get("usage") or {},
                    raw_id=body.get("id"),
                    tool_events=tool_events,
                )

            if isinstance(input_items, str):
                input_items = [{"role": "user", "content": input_items}]
            input_items.extend(body.get("output", []))
            for call in calls:
                args = json.loads(call.get("arguments") or "{}")
                output = tool_executor(call["name"], args)
                tool_events.append({"name": call["name"], "arguments": args, "output": output})
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": call["call_id"],
                        "output": output,
                    }
                )

            payload = {
                "model": selected_model,
                "instructions": instructions,
                "input": input_items,
                "store": False,
            }
            if tools:
                payload["tools"] = tools
            body = self._post_response(payload)

        raise ProviderError(f"Model exceeded max tool rounds ({max_tool_rounds}).")

    def _post_response(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url}/responses",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ProviderError(f"Provider request failed with HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ProviderError(f"Provider request failed: {exc.reason}") from exc


def _extract_output_text(body: dict[str, Any]) -> str:
    if isinstance(body.get("output_text"), str):
        return body["output_text"]

    chunks: list[str] = []
    for item in body.get("output", []):
        for content in item.get("content", []):
            text = content.get("text")
            if isinstance(text, str):
                chunks.append(text)
    if chunks:
        return "\n".join(chunks).strip()
    raise ProviderError("Provider response did not include text output.")


def _extract_function_calls(body: dict[str, Any]) -> list[dict[str, Any]]:
    calls = []
    for item in body.get("output", []):
        if item.get("type") == "function_call":
            calls.append(item)
    return calls
