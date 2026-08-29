"""
checkpoint_agent.py — ADK Agent that generates context checkpoints using Gemini.

The agent:
  1. Receives a WorkSnapshot (git diff, commits, terminal tail, active files).
  2. Infers WHAT the developer was doing and WHY (not just restating the diff).
  3. Returns a strict JSON CheckpointResult with: summary, task_type,
     confidence, next_likely_step.
  4. Uses recent user feedback to improve future classifications.

ADK tools (callable by the agent during its reasoning):
    - get_git_diff_tool(repo_path)
    - get_recent_commits_tool(repo_path, n)
    - get_terminal_tail_tool(lines)

Usage:
    from checkpoint_agent import run_checkpoint_agent
    result = run_checkpoint_agent(snapshot, feedback_history=[...])
"""

from __future__ import annotations

import json
import re
import textwrap
from dataclasses import dataclass
from typing import Any

from config import cfg
from watcher import WorkSnapshot, get_git_diff, get_recent_commits, get_terminal_tail

# ─────────────────────────────────────────────────────────────────────────────
# Result type
# ─────────────────────────────────────────────────────────────────────────────

VALID_TASK_TYPES = {"debugging", "new-feature", "review-response", "refactor", "unclear"}


@dataclass
class CheckpointResult:
    """Structured output from the checkpoint agent."""
    summary: str                  # 2-3 sentence narrative of what was happening
    task_type: str                # one of VALID_TASK_TYPES
    confidence: float             # 0.0–1.0
    next_likely_step: str         # what the developer would probably do next
    raw_response: str = ""        # full agent response (for debugging)

    def is_valid(self) -> bool:
        return (
            bool(self.summary)
            and self.task_type in VALID_TASK_TYPES
            and 0.0 <= self.confidence <= 1.0
            and bool(self.next_likely_step)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "task_type": self.task_type,
            "confidence": self.confidence,
            "next_likely_step": self.next_likely_step,
        }


# ─────────────────────────────────────────────────────────────────────────────
# System prompt
# ─────────────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = textwrap.dedent("""
    You are a senior software engineer's cognitive assistant. Your job is to
    analyse the developer's recent work context and produce a concise, insightful
    checkpoint that lets them resume their train of thought instantly after an
    interruption.

    IMPORTANT RULES:
    1. Focus on WHY, not just WHAT. Don't just restate the diff. Infer the
       developer's intent, mental model, and the problem they were solving.
    2. Be specific. Mention file names, function names, error messages if visible.
    3. Keep the summary to 2-3 sentences max. It must be readable in 10 seconds.
    4. Choose task_type honestly. If uncertain, pick "unclear" rather than guessing.
    5. next_likely_step should be actionable — what would a senior engineer do next?
    6. Quote or closely paraphrase the ACTUAL new lines from the diff in your summary
   (e.g. specific function names, print statements, variable names) — never say
   "made changes to X" without naming what those changes actually were.

    Task types:
    - debugging        → chasing a bug, reading stack traces, adding print/logs
    - new-feature      → implementing new functionality, writing new code
    - review-response  → addressing PR comments, updating based on feedback
    - refactor         → restructuring existing code without changing behaviour
    - unclear          → not enough signal to determine intent

    You MUST respond with ONLY valid JSON, no markdown fences, no explanation:
    {
      "summary": "...",
      "task_type": "...",
      "confidence": 0.0,
      "next_likely_step": "..."
    }
""").strip()


# ─────────────────────────────────────────────────────────────────────────────
# ADK tool definitions
# ─────────────────────────────────────────────────────────────────────────────

def get_git_diff_tool(repo_path: str = ".") -> str:
    """
    Get the current staged and unstaged git diff for the specified repository.

    Args:
        repo_path: Path to the git repository root (default: current directory).

    Returns:
        The combined git diff as a string.
    """
    return get_git_diff(repo_path)


def get_recent_commits_tool(repo_path: str = ".", n: int = 5) -> str:
    """
    Get the most recent git commit messages for the specified repository.

    Args:
        repo_path: Path to the git repository root (default: current directory).
        n: Number of recent commits to retrieve (default: 5).

    Returns:
        Newline-separated list of recent commit summaries with timestamps.
    """
    commits = get_recent_commits(repo_path, n=n)
    return "\n".join(commits) if commits else "(no commits found)"


def get_terminal_tail_tool(lines: int = 50) -> str:
    """
    Get the last N lines from the developer's terminal/shell history file.

    Args:
        lines: Number of lines to retrieve from the end of the history file.

    Returns:
        The last N lines of shell history as a string.
    """
    return get_terminal_tail(lines=lines)


# ─────────────────────────────────────────────────────────────────────────────
# Main agent runner
# ─────────────────────────────────────────────────────────────────────────────

def _build_feedback_context(feedback_history: list[dict[str, Any]]) -> str:
    """Format recent feedback records into a context block for the prompt."""
    if not feedback_history:
        return ""
    lines = ["PAST FEEDBACK CORRECTIONS (use to improve classification):"]
    for fb in feedback_history[:5]:  # limit to 5 most recent
        inferred = fb.get("inferred_type", "?")
        corrected = fb.get("corrected_type", "?")
        summary = fb.get("summary", "")[:100]
        lines.append(f"  • Was classified as '{inferred}', correct type was '{corrected}'. Summary: {summary}")
    return "\n".join(lines)


def _parse_checkpoint_result(raw: str) -> CheckpointResult:
    """
    Parse the agent's raw text response into a CheckpointResult.

    Handles cases where the model wraps JSON in markdown code fences or adds
    extra explanation text.
    """
    # Strip markdown fences if present
    text = raw.strip()
    fence_match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if fence_match:
        text = fence_match.group(1).strip()

    # Extract the first JSON object if there's surrounding text
    json_match = re.search(r"\{[\s\S]*\}", text)
    if json_match:
        text = json_match.group(0)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Fallback: return a minimal result so the app doesn't crash
        return CheckpointResult(
            summary="Unable to parse agent response.",
            task_type="unclear",
            confidence=0.0,
            next_likely_step="Manually review recent changes.",
            raw_response=raw,
        )

    # Validate and coerce types
    task_type = str(data.get("task_type", "unclear")).lower()
    if task_type not in VALID_TASK_TYPES:
        task_type = "unclear"

    try:
        confidence = float(data.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))
    except (TypeError, ValueError):
        confidence = 0.5

    return CheckpointResult(
        summary=str(data.get("summary", "")),
        task_type=task_type,
        confidence=confidence,
        next_likely_step=str(data.get("next_likely_step", "")),
        raw_response=raw,
    )


def run_checkpoint_agent(
    snapshot: WorkSnapshot,
    feedback_history: list[dict[str, Any]] | None = None,
) -> CheckpointResult:
    """
    Run the checkpoint agent against a WorkSnapshot and return a CheckpointResult.

    This function uses Google ADK to create an Agent backed by Gemini. The agent
    has access to tools for fetching live git context, but the snapshot data is
    also injected directly into the prompt so the agent can respond without
    necessarily calling tools (faster for the common case).

    Args:
        snapshot:         The WorkSnapshot to analyse.
        feedback_history: Recent user feedback corrections (from pattern_store).

    Returns:
        A validated CheckpointResult.
    """
    try:
        return _run_with_adk(snapshot, feedback_history or [])
    except Exception as adk_err:
        # Fallback: call Gemini directly without ADK if ADK fails to initialise
        print(f"[checkpoint_agent] ADK error: {adk_err}. Falling back to direct Gemini call.")
        try:
            return _run_direct_gemini(snapshot, feedback_history or [])
        except Exception as gemini_err:
            print(f"[checkpoint_agent] Gemini error: {gemini_err}")
            return CheckpointResult(
                summary="Context capture failed — please review recent changes manually.",
                task_type="unclear",
                confidence=0.0,
                next_likely_step="Run `git diff` and `git log --oneline -5` to reconstruct context.",
                raw_response=str(gemini_err),
            )


def _build_user_prompt(
    snapshot: WorkSnapshot,
    feedback_history: list[dict[str, Any]],
) -> str:
    """Build the user-facing prompt combining snapshot context and feedback."""
    feedback_ctx = _build_feedback_context(feedback_history)
    context_str = snapshot.to_context_string()

    parts = []
    if feedback_ctx:
        parts.append(feedback_ctx)
        parts.append("")

    parts.append("CURRENT DEVELOPER CONTEXT:")
    parts.append(context_str)
    parts.append("")
    parts.append(
        "Based on the above context, produce a checkpoint JSON. "
        "Remember: infer WHY, not just WHAT. "
        "Respond with ONLY the JSON object."
    )
    return "\n".join(parts)


# ── ADK-based runner ──────────────────────────────────────────────────────────

def _run_with_adk(
    snapshot: WorkSnapshot,
    feedback_history: list[dict[str, Any]],
) -> CheckpointResult:
    """Run the agent using Google ADK."""
    from google.adk.agents import LlmAgent
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai.types import Content, Part  # ADK 2.x uses google.genai.types

    # Build the ADK agent with tools
    agent = LlmAgent(
        model=cfg.gemini_model,
        name="resume_checkpoint_agent",
        description="Analyses developer context to generate work checkpoints.",
        instruction=_SYSTEM_PROMPT,
        tools=[get_git_diff_tool, get_recent_commits_tool, get_terminal_tail_tool],
    )

    session_service = InMemorySessionService()
    runner = Runner(
        agent=agent,
        app_name="resume_agent",
        session_service=session_service,
    )

    APP_NAME = "resume_agent"
    USER_ID = "developer"
    SESSION_ID = "checkpoint_session"

    # Create a fresh session for this run
    import asyncio

    async def _run_async() -> str:
        await session_service.create_session(
            app_name=APP_NAME,
            user_id=USER_ID,
            session_id=SESSION_ID,
        )
        prompt = _build_user_prompt(snapshot, feedback_history)
        message = Content(role="user", parts=[Part(text=prompt)])

        final_text = ""
        async for event in runner.run_async(
            user_id=USER_ID,
            session_id=SESSION_ID,
            new_message=message,
        ):
            if event.is_final_response() and event.content:
                for part in event.content.parts:
                    if hasattr(part, "text") and part.text:
                        final_text += part.text
        return final_text

    raw_response = asyncio.run(_run_async())
    result = _parse_checkpoint_result(raw_response)
    result.raw_response = raw_response
    return result



# ── Direct Gemini fallback ────────────────────────────────────────────────────

def _run_direct_gemini(
    snapshot: WorkSnapshot,
    feedback_history: list[dict[str, Any]],
) -> CheckpointResult:
    """
    Fallback: call Gemini directly via google-genai (no ADK).

    Used when ADK is unavailable or fails to initialise.
    """
    from google import genai
    from google.genai import types as genai_types

    client = genai.Client(api_key=cfg.gemini_api_key)
    prompt = _build_user_prompt(snapshot, feedback_history)

    response = client.models.generate_content(
        model=cfg.gemini_model,
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            system_instruction=_SYSTEM_PROMPT,
            temperature=0.2,   # low temperature for structured JSON output
            max_output_tokens=1024,
        ),
    )

    raw = response.text or ""
    result = _parse_checkpoint_result(raw)
    result.raw_response = raw
    return result
