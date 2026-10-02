# Copyright (c) 2026 LeadRescue LLC. All rights reserved.
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from .models import ModelResult


class ProviderError(RuntimeError):
    pass


def provider_settings_path() -> Path:
    home = Path(os.environ.get("GUADE_HOME", Path.home() / ".guade")).expanduser()
    return home / "provider-settings.json"


def read_provider_settings() -> dict[str, dict[str, str]]:
    defaults = {
        "workflow": {"provider": "ollama", "model": "qwen3.5:9b", "base_url": ""},
        "assistant": {"provider": "codex", "model": "", "base_url": ""},
    }
    path = provider_settings_path()
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            for scope in defaults:
                if isinstance(raw.get(scope), dict):
                    defaults[scope].update({key: str(raw[scope].get(key, "")) for key in ("provider", "model", "base_url")})
        except (OSError, json.JSONDecodeError):
            pass
    return defaults


def write_provider_settings(settings: dict[str, dict[str, str]]) -> None:
    path = provider_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def validate_provider_settings(body: dict[str, Any]) -> dict[str, dict[str, str]]:
    current = read_provider_settings()
    for scope, allowed in (("workflow", {"openai", "ollama"}), ("assistant", {"openai", "ollama", "codex"})):
        values = body.get(scope)
        if not isinstance(values, dict):
            raise ValueError(f"Missing {scope} provider settings.")
        provider = str(values.get("provider", ""))
        model = str(values.get("model", "")).strip()
        base_url = str(values.get("base_url", "")).strip().rstrip("/")
        if provider not in allowed:
            raise ValueError(f"Unsupported {scope} provider.")
        if len(model) > 120 or len(base_url) > 500:
            raise ValueError("Provider model or endpoint is too long.")
        if base_url and not base_url.startswith(("http://", "https://")):
            raise ValueError("Provider endpoint must start with http:// or https://.")
        if provider == "ollama" and not base_url:
            base_url = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1").rstrip("/")
        current[scope] = {"provider": provider, "model": model, "base_url": base_url}
    return current


class OpenAIResponsesProvider:
    def __init__(self, api_key: str | None = None, base_url: str | None = None, default_model: str | None = None, scope: str = "workflow") -> None:
        settings = read_provider_settings()[scope]
        self.provider_name = settings["provider"]
        if self.provider_name == "ollama":
            self.api_key = api_key or "ollama"
            self.base_url = (base_url or settings["base_url"] or os.environ.get("OLLAMA_BASE_URL") or "http://127.0.0.1:11434/v1").rstrip("/")
            self.default_model = default_model or settings["model"] or os.environ.get("OLLAMA_MODEL") or "qwen3.5:9b"
        else:
            self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
            self.base_url = (base_url or settings["base_url"] or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
            self.default_model = default_model or settings["model"] or os.environ.get("OPENAI_MODEL") or "gpt-5-mini"

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
            "max_output_tokens": int(os.environ.get("GUADE_MAX_OUTPUT_TOKENS", "450")),
            "store": False,
        }
        if tools:
            payload["tools"] = tools

        tool_events: list[dict[str, Any]] = []
        body = self._post_response(payload)
        empty_response_retries = 0

        for _ in range(max_tool_rounds):
            calls = _extract_function_calls(body)
            if not calls:
                try:
                    text = _extract_output_text(body)
                except ProviderError:
                    if not tool_events:
                        if empty_response_retries >= 1:
                            raise
                        empty_response_retries += 1
                        payload = dict(payload)
                        payload["instructions"] = (
                            f"{instructions}\n\n"
                            "Return a short plain-text completion. If a tool is needed, call it first; "
                            "otherwise summarize the completed work in one sentence."
                        )
                        body = self._post_response(payload)
                        continue
                    text = _summarize_tool_events(tool_events)
                if self.provider_name == "ollama" and _looks_cut_off_at_token_limit(body, text):
                    raise ProviderError(
                        "Provider response appears truncated at the local model token limit. "
                        "Use a shorter task or split this workflow into smaller chained runs."
                    )
                return ModelResult(
                    text=text,
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
                "max_output_tokens": int(os.environ.get("GUADE_MAX_OUTPUT_TOKENS", "450")),
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
            with urllib.request.urlopen(request, timeout=int(os.environ.get("GUADE_MODEL_TIMEOUT", "45"))) as response:
                body = json.loads(response.read().decode("utf-8"))
                if body.get("status") == "incomplete":
                    details = body.get("incomplete_details") or {}
                    reason = details.get("reason") if isinstance(details, dict) else None
                    raise ProviderError(f"Provider response was incomplete{f': {reason}' if reason else '.'}")
                return body
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ProviderError(f"Provider request failed with HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ProviderError(f"Provider request failed: {exc.reason}") from exc


class CodexCLIProvider:
    def __init__(self, default_model: str | None = None) -> None:
        settings = read_provider_settings()["assistant"]
        self.provider_name = "codex"
        self.default_model = default_model or settings["model"] or "Codex CLI"
        self.api_key = "codex-cli" if _codex_executable() else None
        self.base_url = "local Codex CLI"

    def complete(self, instructions: str, prompt: str, model: str | None = None) -> ModelResult:
        executable = _codex_executable()
        if not executable:
            raise ProviderError("Codex CLI is not installed or not available on GUADE's PATH.")
        with tempfile.TemporaryDirectory(prefix="guade-codex-") as workspace:
            output_path = Path(workspace) / "answer.txt"
            command = [
                executable, "exec", "--ignore-user-config", "--sandbox", "read-only",
                "--skip-git-repo-check", "--ephemeral", "--output-last-message", str(output_path),
            ]
            if model:
                command.extend(("--model", model))
            command.append(f"{instructions}\n\n{prompt}")
            safe_env = {key: os.environ[key] for key in ("PATH", "HOME", "CODEX_HOME", "TMPDIR", "TEMP", "TMP") if key in os.environ}
            try:
                result = subprocess.run(
                    command,
                    cwd=workspace,
                    env=safe_env,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    timeout=240,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise ProviderError("Codex CLI timed out after 4 minutes.") from exc
            if result.returncode != 0:
                detail = (result.stderr or result.stdout).strip()[-2000:]
                raise ProviderError(f"Codex CLI failed (exit {result.returncode}): {detail or 'No error details.'}")
            if not output_path.is_file():
                raise ProviderError("Codex CLI completed without a final response.")
            answer = output_path.read_text(encoding="utf-8").strip()
            if not answer:
                raise ProviderError("Codex CLI returned an empty response.")
            return ModelResult(text=answer, model=model or self.default_model, usage={}, raw_id=None, tool_events=[])

    def complete_with_tools(self, instructions: str, prompt: str, tools: list[dict[str, Any]], tool_executor: Callable[[str, dict[str, Any]], str], model: str | None = None, max_tool_rounds: int = 6) -> ModelResult:
        if tools:
            raise ProviderError("Codex CLI mode is currently available for direct assistant chat only. Select OpenAI API or Ollama for tool-using workflow runs.")
        return self.complete(instructions, prompt, model)


def create_provider(scope: str = "workflow") -> OpenAIResponsesProvider | CodexCLIProvider:
    settings = read_provider_settings()[scope]
    if settings["provider"] == "codex":
        return CodexCLIProvider()
    return OpenAIResponsesProvider(scope=scope)


def _codex_executable() -> str | None:
    executable = shutil.which("codex")
    if executable:
        return executable
    for candidate in (Path.home() / ".local/bin/codex", Path("/usr/local/bin/codex")):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _extract_output_text(body: dict[str, Any]) -> str:
    if isinstance(body.get("output_text"), str):
        text = body["output_text"].strip()
        if text:
            return text

    chunks: list[str] = []
    for item in body.get("output", []):
        for content in item.get("content", []):
            text = content.get("text")
            if isinstance(text, str):
                chunks.append(text)
    text = "\n".join(chunks).strip()
    if text:
        return text
    raise ProviderError("Provider response did not include non-empty text output.")


def _extract_function_calls(body: dict[str, Any]) -> list[dict[str, Any]]:
    calls = []
    for item in body.get("output", []):
        if item.get("type") == "function_call":
            calls.append(item)
    return calls


def _summarize_tool_events(tool_events: list[dict[str, Any]]) -> str:
    parts = []
    for event in tool_events:
        name = event.get("name", "tool")
        output = str(event.get("output", "")).strip()
        if output:
            parts.append(f"{name}: {output}")
    return "\n".join(parts).strip() or "Tool call completed."


def _looks_cut_off_at_token_limit(body: dict[str, Any], text: str) -> bool:
    usage = body.get("usage") or {}
    total = usage.get("total_tokens")
    if not isinstance(total, int) or total < 4096:
        return False
    stripped = text.rstrip()
    if not stripped:
        return True
    return stripped[-1] not in ".!?:;)>]}`\"'"
