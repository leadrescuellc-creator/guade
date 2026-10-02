import pytest

from workflow_agent.provider import ProviderError, _extract_output_text, _looks_cut_off_at_token_limit, _summarize_tool_events


def test_extract_output_text_rejects_empty_output_text() -> None:
    with pytest.raises(ProviderError, match="non-empty"):
        _extract_output_text({"output_text": "   "})


def test_extract_output_text_rejects_empty_content_chunks() -> None:
    with pytest.raises(ProviderError, match="non-empty"):
        _extract_output_text({"output": [{"content": [{"text": ""}, {"text": "  "}]}]})


def test_extract_output_text_reads_content_chunks() -> None:
    assert _extract_output_text({"output": [{"content": [{"text": "done"}]}]}) == "done"


def test_summarize_tool_events_uses_tool_output() -> None:
    assert _summarize_tool_events([{"name": "filesystem_write", "output": "Wrote output.md"}]) == "filesystem_write: Wrote output.md"


def test_cutoff_detection_flags_ollama_style_token_ceiling() -> None:
    body = {"usage": {"total_tokens": 4096}}
    assert _looks_cut_off_at_token_limit(body, "The call takes exactly")


def test_cutoff_detection_allows_finished_text_at_ceiling() -> None:
    body = {"usage": {"total_tokens": 4096}}
    assert not _looks_cut_off_at_token_limit(body, "The call takes exactly 20 minutes.")


def test_cutoff_detection_ignores_lower_usage() -> None:
    body = {"usage": {"total_tokens": 2048}}
    assert not _looks_cut_off_at_token_limit(body, "The call takes exactly")
