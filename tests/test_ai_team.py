"""AI Team launcher tests: no installed agents or API keys required."""
import json
from pathlib import Path

import pytest

from scripts import ai_team


def test_doctor_has_machine_readable_state():
    result = ai_team.doctor()
    assert result["state"] == "DIAGNOSTIC"
    assert result["git"] in (True, False)


def test_prepare_and_dry_run_never_call_agents(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_team, "RUN_ROOT", tmp_path / "runs")
    task = tmp_path / "issue.md"
    task.write_text("Fix Preview gate, keep tests and no paid calls", encoding="utf-8")

    def not_allowed(*args, **kwargs):
        raise AssertionError("dry-run must never launch subprocess")

    monkeypatch.setattr(ai_team, "invoke", not_allowed)
    result = ai_team.run(task, execute=False, approve_ai_cost=False, phase="all")
    assert result["state"] == "DRY_RUN"
    assert result["ai_called"] is False
    folder = Path(result["output_dir"])
    assert (folder / "plan.md").exists()
    assert (folder / "implement.md").exists()
    assert (folder / "review.md").exists()
    assert json.loads((folder / "status.json").read_text(encoding="utf-8"))["human_approval_required"]


def test_executing_without_cost_approval_is_blocked(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_team, "RUN_ROOT", tmp_path / "runs")
    task = tmp_path / "issue.md"
    task.write_text("test", encoding="utf-8")
    with pytest.raises(ValueError, match="--approve-ai-cost"):
        ai_team.run(task, execute=True, approve_ai_cost=False, phase="all")


def test_missing_and_giant_task_are_rejected(tmp_path):
    with pytest.raises(ValueError):
        ai_team.task_contents(tmp_path / "missing.md")
    large = tmp_path / "huge.md"
    large.write_text("x" * 64001, encoding="utf-8")
    with pytest.raises(ValueError):
        ai_team.task_contents(large)
