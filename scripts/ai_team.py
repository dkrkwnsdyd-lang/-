"""Local AI development team runner for SHOP SHORTS AI.

Dry-run by default; never merges, pushes, deploys, publishes or calls paid APIs
without explicit CLI opt-in. Requires locally installed/authenticated Claude Code
and Codex CLIs for execution. Python standard library only.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = ROOT / ".ai-team" / "runs"
PROTECTED = {"main", "master"}
MAX_TASK_BYTES = 64_000
MAX_AGENT_SECONDS = 1800
MAX_TEST_SECONDS = 3600


def command_available(command: str) -> bool:
    return shutil.which(command) is not None


def invoke(args: list[str], *, cwd: Path = ROOT, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout, check=False)


def git(args: list[str]) -> str:
    result = invoke(["git", *args])
    if result.returncode:
        raise RuntimeError(f"git command failed: git {' '.join(args)}: {result.stderr[-400:]}")
    return result.stdout.strip()


def ensure_clean_branch(task: Path) -> str:
    if Path(git(["rev-parse", "--show-toplevel"])).resolve() != ROOT:
        raise RuntimeError("Run from the SHOP SHORTS AI repository")
    if git(["status", "--porcelain"]):
        raise RuntimeError("Working tree is not clean; commit or stash changes first")
    current = git(["branch", "--show-current"])
    if current not in PROTECTED and current.startswith("ai-team/"):
        return current
    safe = re.sub(r"[^a-z0-9-]", "-", task.stem.lower()).strip("-")[:45] or "task"
    suffix = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    new_branch = f"ai-team/{safe}-{suffix}"
    git(["switch", "-c", new_branch])
    return new_branch


def task_contents(path: Path) -> str:
    actual = path.expanduser().resolve()
    if not actual.is_file() or actual.stat().st_size > MAX_TASK_BYTES:
        raise ValueError("Task must be an existing text file of 64KB or less")
    return actual.read_text(encoding="utf-8")


def prompts(task: str) -> dict[str, str]:
    safety = (
        "Follow docs/AI_TEAM_WORKFLOW.md, CLAUDE.md and AGENTS.md. "
        "Preserve Product Lock, fact grounding and compliance. Never read, print or commit secrets. "
        "Do not call paid generation services, publish, push, merge or deploy. "
        "State tests actually executed and uncertainties.\n"
    )
    return {
        "plan": safety + "You are the read-only planning lead. Analyze the existing code; "
                "produce exact file-level change list, tests and rollback. Do not edit files.\n\n" + task,
        "implement": safety + "You are the implementation lead. Make minimal code/test changes "
                     "according to the task. Do not modify deployed services or git remotes. "
                     "Run no paid calls. Provide changed files and test evidence.\n\n" + task,
        "review": safety + "You are an independent READ-ONLY reviewer. Review the working tree, "
                  "find correctness/security/grounding regressions and compare with acceptance "
                  "criteria. Do not edit anything. End with PASS, FAIL or NEEDS_REVIEW and reasons.\n\n" + task,
    }


def write_status(folder: Path, status: dict) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")


def prepare(task_path: Path) -> Path:
    content = task_contents(task_path)
    slug = re.sub(r"[^a-z0-9-]", "-", task_path.stem.lower()).strip("-")[:45] or "task"
    folder = RUN_ROOT / f"{slug}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    folder.mkdir(parents=True, exist_ok=True)
    for role, prompt in prompts(content).items():
        (folder / f"{role}.md").write_text(prompt, encoding="utf-8")
    write_status(folder, {"state": "PREPARED", "task": str(task_path), "branch": None,
                          "ai_called": False, "tests": "not_run", "human_approval_required": True})
    return folder


def doctor() -> dict:
    return {
        "python": sys.version.split()[0],
        "claude": command_available("claude"),
        "codex": command_available("codex"),
        "git": command_available("git"),
        "repo": str(ROOT),
        "notice": "CLI availability alone does not confirm sign-in, permissions or billing.",
    }


def run(task_path: Path, *, execute: bool, approve_ai_cost: bool, phase: str) -> dict:
    folder = prepare(task_path)
    status = json.loads((folder / "status.json").read_text(encoding="utf-8"))
    status["phase"] = phase
    status["output_dir"] = str(folder)
    write_status(folder, status)
    if not execute:
        status["state"] = "DRY_RUN"
        status["next_step"] = "Run with --execute --approve-ai-cost on an authenticated local PC"
        write_status(folder, status)
        return status
    if not approve_ai_cost:
        raise ValueError("Model execution requires both --execute and --approve-ai-cost")
    if phase in ("plan", "implement", "all") and not command_available("claude"):
        raise RuntimeError("Claude Code CLI is not installed or not in PATH")
    if phase in ("review", "all") and not command_available("codex"):
        raise RuntimeError("Codex CLI is not installed or not in PATH")
    status["branch"] = ensure_clean_branch(task_path)
    status["ai_called"] = True
    write_status(folder, status)
    phases = ("plan", "implement", "review") if phase == "all" else (phase,)
    for step in phases:
        if step == "review" and phase == "all":
            # Independent reviewer only after local tests have passed.
            pass
        prompt = (folder / f"{step}.md").read_text(encoding="utf-8")
        argv = (["claude", "-p", "--permission-mode", "plan", prompt]
                if step == "plan" else
                ["claude", "-p", "--permission-mode", "acceptEdits", prompt]
                if step == "implement" else
                ["codex", "exec", "--sandbox", "read-only", prompt])
        started = time.monotonic()
        try:
            result = invoke(argv, timeout=MAX_AGENT_SECONDS)
        except subprocess.TimeoutExpired:
            status.update(state="BLOCKED", failed_step=step, error="agent_timeout")
            write_status(folder, status)
            return status
        # Output stays on this local PC; it is not automatically uploaded to GitHub.
        (folder / f"{step}-output.txt").write_text(result.stdout, encoding="utf-8")
        status[step] = {"returncode": result.returncode, "elapsed_seconds": round(time.monotonic() - started, 2)}
        if result.returncode:
            status.update(state="BLOCKED", failed_step=step, error=result.stderr[-700:])
            write_status(folder, status)
            return status
        if step == "implement":
            commands = [
                ["python", "-m", "compileall", "-q", "shortsmaker"],
                ["python", "-m", "pytest", "-q"],
            ]
            status["tests"] = []
            for cmd in commands:
                try:
                    res = invoke(cmd, timeout=MAX_TEST_SECONDS)
                except subprocess.TimeoutExpired:
                    status.update(state="BLOCKED", error="test_timeout")
                    write_status(folder, status)
                    return status
                status["tests"].append({"command": " ".join(cmd), "exit_code": res.returncode})
                (folder / f"test-{len(status['tests'])}.txt").write_text(
                    res.stdout[-15000:] + "\n" + res.stderr[-3000:], encoding="utf-8")
                if res.returncode:
                    status.update(state="BLOCKED", failed_step="test", error="regression_tests_failed")
                    write_status(folder, status)
                    return status
        write_status(folder, status)
    status.update(state="REVIEW_NEEDED", human_approval_required=True,
                  next_step="Inspect local diff, test evidence and reviewer output; create PR manually")
    write_status(folder, status)
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Approval-gated ChatGPT/Claude/Codex developer workflow")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    prep = sub.add_parser("prepare")
    prep.add_argument("--task", required=True, type=Path)
    execute = sub.add_parser("run")
    execute.add_argument("--task", required=True, type=Path)
    execute.add_argument("--phase", choices=("plan", "implement", "review", "all"), default="all")
    execute.add_argument("--execute", action="store_true")
    execute.add_argument("--approve-ai-cost", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            payload = doctor()
        elif args.command == "prepare":
            payload = {"state": "PREPARED", "output_dir": str(prepare(args.task))}
        else:
            payload = run(args.task, execute=args.execute,
                          approve_ai_cost=args.approve_ai_cost, phase=args.phase)
    except (OSError, ValueError, RuntimeError) as exc:
        payload = {"state": "BLOCKED", "error": str(exc)}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["state"] not in ("BLOCKED",) else 1


if __name__ == "__main__":
    sys.exit(main())
