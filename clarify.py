"""
clarify.py — interactive clarifying question module (Collaborative Partner requirement).

After surfacing a resume summary, asks the developer ONE short clarifying question
about whether the inferred task_type / intent was correct. The answer is stored
and used to correct future classifications for similar diffs.

This satisfies the hackathon's "Collaborative Partner" track:
    ✓ Agent asks clarifying questions
    ✓ Guides step-by-step
    ✓ Captures feedback that improves it over time

Usage:
    from clarify import ask_clarifying_question
    corrected_type = ask_clarifying_question(checkpoint_id, result, store)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich import box

from checkpoint_agent import CheckpointResult, VALID_TASK_TYPES

if TYPE_CHECKING:
    from pattern_store import StorageBackend

console = Console()

# ─────────────────────────────────────────────────────────────────────────────
# Task type display helpers
# ─────────────────────────────────────────────────────────────────────────────

_TASK_TYPE_LABELS: dict[str, str] = {
    "debugging":       "[BUG] Debugging",
    "new-feature":     "[NEW] New Feature",
    "review-response": "[REV] Review Response",
    "refactor":        "[REF] Refactor",
    "unclear":         "[???] Unclear",
}

_TASK_TYPE_COLORS: dict[str, str] = {
    "debugging":       "red",
    "new-feature":     "green",
    "review-response": "blue",
    "refactor":        "yellow",
    "unclear":         "dim",
}

_TASK_TYPE_SHORTCUTS: dict[str, str] = {
    "d": "debugging",
    "n": "new-feature",
    "r": "review-response",
    "f": "refactor",
    "u": "unclear",
}


def _render_choices_table() -> Table:
    """Render a compact table of task type choices."""
    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    table.add_column("Key", style="bold cyan", no_wrap=True)
    table.add_column("Type", style="bold")
    for shortcut, task_type in _TASK_TYPE_SHORTCUTS.items():
        label = _TASK_TYPE_LABELS.get(task_type, task_type)
        color = _TASK_TYPE_COLORS.get(task_type, "white")
        table.add_row(f"[{shortcut}]", f"[{color}]{label}[/{color}]")
    return table


def _resolve_task_type_input(raw: str) -> str | None:
    """
    Accept either a shortcut key (d/n/r/f/u) or a full task_type name.

    Returns a valid task_type string, or None if the input is unrecognised.
    """
    raw = raw.strip().lower()
    if raw in _TASK_TYPE_SHORTCUTS:
        return _TASK_TYPE_SHORTCUTS[raw]
    if raw in VALID_TASK_TYPES:
        return raw
    # Allow partial match (e.g. "debug" → "debugging")
    for tt in VALID_TASK_TYPES:
        if tt.startswith(raw) or raw in tt:
            return tt
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def ask_clarifying_question(
    checkpoint_id: str,
    result: CheckpointResult,
    store: "StorageBackend",
    *,
    skip: bool = False,
) -> str | None:
    """
    Ask the developer ONE clarifying question about the inferred task_type.

    If the inference was correct, returns None (no correction needed).
    If the developer corrects it, stores the feedback and returns the corrected type.

    Args:
        checkpoint_id: ID of the checkpoint to potentially correct.
        result:        The CheckpointResult produced by the checkpoint agent.
        store:         Storage backend (for saving feedback).
        skip:          If True, skip the question (e.g. in non-interactive mode).

    Returns:
        The corrected task_type string, or None if no correction was made.
    """
    if skip:
        return None

    inferred_label = _TASK_TYPE_LABELS.get(result.task_type, result.task_type)
    inferred_color = _TASK_TYPE_COLORS.get(result.task_type, "white")
    confidence_pct = int(result.confidence * 100)

    console.print()
    console.rule("[bold cyan]Resume Agent — Quick Check[/bold cyan]")
    console.print()
    console.print(
        f"  I classified this as [{inferred_color}]{inferred_label}[/{inferred_color}] "
        f"([dim]{confidence_pct}% confident[/dim])."
    )
    console.print()

    answer = Prompt.ask(
        "  [bold]Was that right?[/bold] ([green]y[/green] = yes / any key to correct)",
        default="y",
        console=console,
    ).strip().lower()

    if answer in ("y", "yes", ""):
        console.print("  [green]OK, no correction needed.[/green]")
        console.print()
        return None

    # Developer wants to correct — show choices
    console.print()
    console.print("  What were you actually working on?")
    console.print()
    console.print(_render_choices_table())

    corrected_type: str | None = None
    while corrected_type is None:
        raw = Prompt.ask(
            "  Enter shortcut or full name",
            default="",
            console=console,
        )
        if not raw.strip():
            console.print("  [dim]Skipping correction.[/dim]")
            return None
        corrected_type = _resolve_task_type_input(raw)
        if corrected_type is None:
            console.print(f"  [red]Unrecognised: '{raw}'. Try d/n/r/f/u or the full name.[/red]")

    # Save feedback
    try:
        store.save_feedback(checkpoint_id, corrected_type)
        corrected_label = _TASK_TYPE_LABELS.get(corrected_type, corrected_type)
        corrected_color = _TASK_TYPE_COLORS.get(corrected_type, "white")
        console.print(
            f"\n  [green]Noted![/green] I'll classify similar work as "
            f"[{corrected_color}]{corrected_label}[/{corrected_color}] in future."
        )
    except Exception as exc:
        console.print(f"  [yellow]Warning: could not save feedback ({exc})[/yellow]")

    console.print()
    return corrected_type


def display_resume_summary(result: CheckpointResult) -> None:
    """
    Render a rich-formatted resume summary panel to the terminal.

    Called before ask_clarifying_question() so the developer sees their
    context before being asked to confirm it.
    """
    task_label = _TASK_TYPE_LABELS.get(result.task_type, result.task_type)
    task_color = _TASK_TYPE_COLORS.get(result.task_type, "white")
    confidence_pct = int(result.confidence * 100)

    content_lines = [
        f"[bold]Task Type:[/bold]  [{task_color}]{task_label}[/{task_color}]  [dim]({confidence_pct}% confident)[/dim]",
        "",
        f"[bold]What was happening:[/bold]",
        f"  {result.summary}",
        "",
        f"[bold]Your likely next step:[/bold]",
        f"  [italic]{result.next_likely_step}[/italic]",
    ]

    panel = Panel(
        "\n".join(content_lines),
        title="[bold cyan]Resume Summary[/bold cyan]",
        border_style="cyan",
        padding=(1, 2),
    )
    console.print()
    console.print(panel)
