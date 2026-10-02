import json

import pytest

from workflow_agent.chat_actions import apply_chat_action, execute_chat_tool


def test_file_change_requires_approval_and_applies_inside_project(tmp_path):
    target = tmp_path / "README.md"
    target.write_text("before\n", encoding="utf-8")

    proposal = json.loads(execute_chat_tool(tmp_path, "guade_propose_file_change", {
        "path": "README.md",
        "content": "after\n",
    }))

    assert target.read_text(encoding="utf-8") == "before\n"
    assert "before" in proposal["diff"]
    assert apply_chat_action(tmp_path, proposal["approval_id"]) == {"path": "README.md", "status": "applied"}
    assert target.read_text(encoding="utf-8") == "after\n"


@pytest.mark.parametrize("path", ["../outside.txt", ".env", "sub/.git/config", "provider-settings.json"])
def test_chat_cannot_access_outside_or_sensitive_files(tmp_path, path):
    result = execute_chat_tool(tmp_path, "guade_read_file", {"path": path})
    assert result.startswith("TOOL_ERROR:")


def test_change_is_rejected_if_file_changed_after_proposal(tmp_path):
    target = tmp_path / "notes.txt"
    target.write_text("original", encoding="utf-8")
    proposal = json.loads(execute_chat_tool(tmp_path, "guade_propose_file_change", {
        "path": "notes.txt",
        "content": "proposed",
    }))
    target.write_text("someone else's update", encoding="utf-8")

    with pytest.raises(ValueError, match="changed after"):
        apply_chat_action(tmp_path, proposal["approval_id"])
